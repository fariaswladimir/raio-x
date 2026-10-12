"""16.4 - Metadados por projeto: extração do texto, importação do índice, consulta online e tabela para a tela.

Depende do banco do projeto (documentos) e de ``metadados.json``; a lógica de cada origem está em ``metadados``, ``indice`` e ``online``.
"""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Documento
from app.services.analises import dados as svc_dados
from app.services.corpus import indice as svc_indice
from app.services.corpus import metadados as M
from app.services.corpus import online as svc_online
from app.services.orquestrador import condicao_ativo
from app.services.texto import ler_qualidade


def documentos_ativos(db: Session) -> list[Documento]:
    return list(db.scalars(select(Documento).where(condicao_ativo()).order_by(Documento.arquivo)))


def resumo_do_limpo(blocos: list[dict] | None) -> str | None:
    """Texto da seção de resumo (o ``Abstract`` se houver mais de um título de resumo; senão o primeiro). Tira a linha de palavras-chave."""
    if not blocos:
        return None
    grupos: dict[str, list[str]] = {}
    for b in blocos:
        if b.get("secao") == "resumo" and b.get("incluir", True):
            grupos.setdefault(b.get("titulo_secao") or "", []).append(b["texto"])
    if not grupos:
        return None
    chave = next((k for k in grupos if k.lower().strip(" :.") == "abstract"), next(iter(grupos)))
    texto = " ".join(" ".join(grupos[chave]).split())
    import re

    texto = re.split(r"\s+(?:\*{0,2}(?:key\s*words?|keywords?|palavras[\s-]*chave|palabras[\s-]*clave|index terms)\*{0,2}\s*[:：—–-])", texto, maxsplit=1, flags=re.IGNORECASE)[0]
    return texto.strip() or None


def ler_md(pasta: Path, doc: Documento) -> str | None:
    if not doc.caminho_md:
        return None
    p = pasta / doc.caminho_md
    return p.read_text(encoding="utf-8") if p.is_file() else None


def extrair_textos(db: Session, pasta: Path) -> dict:
    """Extrai os metadados do texto de todos os documentos ativos (origem ``texto``; substitui a extração anterior)."""
    dados = M.carregar(pasta)
    n = 0
    for doc in documentos_ativos(db):
        md = ler_md(pasta, doc)
        if md is None:
            continue
        blocos = svc_dados.carregar_blocos(pasta, doc.id)
        idioma = ler_qualidade(doc).get("idioma")
        achados = M.extrair_do_texto(md, resumo_do_limpo(blocos), idioma)
        entrada = M._entrada(dados, doc.arquivo)
        M.limpar_origem(entrada, "texto")
        for campo, v in achados.items():
            M.definir_candidato(entrada, campo, "texto", v["valor"], v["confianca"], v.get("detalhe", ""))
        n += 1
    M.salvar(pasta, dados)
    return {"documentos": n}


def importar_indice(db: Session, pasta: Path, conteudo: bytes, nome: str | None = None) -> dict:
    """Importa o CSV do índice: candidatos de origem ``indice`` + sugestão de grupo (nunca aplicada)."""
    docs = documentos_ativos(db)
    por_chave = {svc_indice.chave_arquivo(d.arquivo): d.arquivo for d in docs}
    r = svc_indice.importar(conteudo, por_chave)
    dados = M.carregar(pasta)
    for arquivo, item in r["casados"].items():
        entrada = M._entrada(dados, arquivo)
        M.limpar_origem(entrada, "indice")
        for campo, (valor, conf, detalhe) in item["campos"].items():
            M.definir_candidato(entrada, campo, "indice", valor, conf, detalhe)
        entrada["grupo_sugerido"] = ({"valor": item["grupo"], "trilha": item["trilha"], "id_indice": item["id"]}
                                     if item["grupo"] or item["trilha"] else None)
    dados["indice"] = {"nome": nome, "linhas": r["linhas"], "casados": len(r["casados"])}
    M.salvar(pasta, dados)
    por_id = {d.arquivo: d for d in docs}
    sugestoes = [{"documento_id": por_id[a].id, "arquivo": a, "trilha": i["trilha"], "grupo_sugerido": i["grupo"],
                  "grupo_atual": por_id[a].grupo} for a, i in r["casados"].items() if i["grupo"]]
    return {"linhas": r["linhas"], "colunas": r["colunas"], "casados": len(r["casados"]), "sem_arquivo": r["sem_arquivo"],
            "sem_documento": r["sem_documento"], "duplicatas": r["duplicatas"],
            "documentos_sem_linha": sorted(set(d.arquivo for d in docs) - set(r["casados"])), "sugestoes_de_grupo": sugestoes,
            "grupo_aplicado": False,
            "aviso": "Nenhum grupo foi alterado: confirme as sugestões na tela de metadados."}


def aplicar_grupos(db: Session, pasta: Path, documento_ids: list[int] | None) -> dict:
    """Aplica a sugestão de grupo do índice aos documentos indicados (ação explícita do usuário)."""
    dados = M.carregar(pasta)
    aplicados = []
    for doc in documentos_ativos(db):
        if documento_ids is not None and doc.id not in documento_ids:
            continue
        sug = (dados["documentos"].get(doc.arquivo) or {}).get("grupo_sugerido")
        if sug and sug.get("valor") and doc.grupo != sug["valor"]:
            aplicados.append({"documento_id": doc.id, "de": doc.grupo, "para": sug["valor"]})
            doc.grupo = sug["valor"]
    db.commit()
    return {"aplicados": aplicados}


def consultar_online(db: Session, pasta: Path, fontes: tuple[str, ...] = ("crossref",), documento_ids: list[int] | None = None,
                     email: str | None = None, cliente=None) -> dict:
    """Consulta Crossref/OpenAlex pelo DOI efetivo de cada documento. Levanta ``SemEmail`` sem e-mail configurado."""
    if not (email if email is not None else svc_online.carregar_config()["email_contato"]).strip():
        raise svc_online.SemEmail("Configure um e-mail de contato antes de usar a consulta online.")
    dados = M.carregar(pasta)
    relatorio = {"consultados": 0, "com_resposta": 0, "erros": []}
    for doc in documentos_ativos(db):
        if documento_ids is not None and doc.id not in documento_ids:
            continue
        entrada = dados["documentos"].get(doc.arquivo)
        doi = (M.valores(entrada) or {}).get("doi")
        if not doi:
            continue
        relatorio["consultados"] += 1
        achou = False
        for fonte in fontes:
            r = svc_online.consultar(doi, fonte, email=email, cliente=cliente)
            if r["erro"]:
                relatorio["erros"].append({"documento_id": doc.id, "doi": doi, "fonte": fonte, "erro": r["erro"]})
                continue
            achou = True
            M.limpar_origem(entrada, "online") if fonte == fontes[0] else None
            for campo, valor in r["campos"].items():
                if campo == "doi":
                    continue
                atual = [c for c in entrada["candidatos"].get(campo, []) if c["origem"] == "online"]
                if atual and fonte != fontes[0]:
                    continue  # o primeiro provedor que responde vale
                M.definir_candidato(entrada, campo, "online", valor, svc_online.CONFIANCA, f"{fonte} (DOI {doi})")
        relatorio["com_resposta"] += int(achou)
    M.salvar(pasta, dados)
    return relatorio


def tabela(db: Session, pasta: Path) -> list[dict]:
    dados = M.carregar(pasta)
    saida = []
    for doc in documentos_ativos(db):
        entrada = dados["documentos"].get(doc.arquivo)
        res = M.resolver(entrada)
        sug = (entrada or {}).get("grupo_sugerido")
        saida.append({
            "documento_id": doc.id, "arquivo": doc.arquivo, "rotulo": svc_dados.rotulo_do_documento(doc), "grupo": doc.grupo,
            "grupo_sugerido": sug, "grupo_difere": bool(sug and sug.get("valor") and sug["valor"] != doc.grupo),
            "campos": res,
        })
    return saida


def cobertura(linhas: list[dict]) -> dict:
    """Por campo: quantos documentos têm valor e de qual origem; conflitos."""
    campos = ("titulo", "autores", "ano", "doi", "resumo", "palavras_chave", "afiliacoes", "fonte", "tipo_documento", "idioma")
    out = {"documentos": len(linhas), "campos": {}, "conflitos": 0}
    for c in campos:
        origens: dict[str, int] = {}
        for l in linhas:
            v = l["campos"].get(c)
            if v:
                origens[v["origem"]] = origens.get(v["origem"], 0) + 1
        out["campos"][c] = {"com_valor": sum(origens.values()), "por_origem": origens}
    out["conflitos"] = sum(1 for l in linhas for v in l["campos"].values() if v["conflito"])
    return out
