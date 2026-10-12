"""17.3 - Revisão: matriz documento x item, detalhe da célula (trechos, página, contexto KWIC), decisões por célula e em lote, contadores.

Matriz: uma linha por documento, uma coluna por item do protocolo atual; cada célula traz status, valor, origem, confiança e se precisa de revisão.
Contadores por item: sugerido, aceito, editado, rejeitado, não encontrado, não se aplica, ``pendentes`` (ainda sem decisão: sugerido) e, se o item é
obrigatório, ``obrigatorio_sem_valor`` (não encontrado ou rejeitado). Filtros: ``status`` (da célula), ``item``, ``grupo``.
Decisão em lote: aceitar (ou rejeitar) todas as células **sugeridas** de um item ou de um documento; valores ambíguos e sem valor ficam de fora.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.analises import dados as svc_dados
from app.services.coleta import celulas as C
from app.services.coleta import extratores as E
from app.services.coleta import motor as M
from app.services.coleta import protocolo as PR
from app.services.corpus import planilha as svc_planilha
from app.services.corpus import projeto as svc_projeto
from app.services import ruido as svc_ruido
from app.services import parametros as svc_parametros


def _documentos(db: Session, pasta: Path) -> list:
    return svc_projeto.documentos_ativos(db)


def _resumo_celula(cel: dict | None, tipo: str) -> dict | None:
    if cel is None:
        return None
    return {"status": cel["status"], "valor": C.valor_como_texto(cel, tipo), "unidade": cel.get("unidade"), "origem": cel.get("origem"),
            "confianca": cel.get("confianca"), "revisar": cel.get("revisar"), "definicao_mudou": bool(cel.get("definicao_mudou")),
            "n_trechos": len(cel.get("trechos") or []), "pagina": next((t.get("pagina") for t in (cel.get("trechos") or []) if t.get("pagina") is not None), None),
            "nota": cel.get("nota")}


def contadores(itens: list[dict], dados: dict, arquivos: list[str]) -> list[dict]:
    saida = []
    for it in itens:
        cont = {s: 0 for s in C.STATUS}
        faltando = 0
        for a in arquivos:
            cel = C.celula_de(dados, a, it["id"])
            if cel is None:
                faltando += 1
                continue
            cont[cel["status"]] += 1
        decididos = sum(cont[s] for s in C.DECIDIDOS)
        saida.append({"id": it["id"], "nome": it["nome"], "tipo": it["tipo"], "obrigatorio": it["obrigatorio"], "contagem": cont, "sem_celula": faltando,
                      "decididos": decididos, "pendentes": cont["sugerido"], "total": len(arquivos),
                      "obrigatorio_sem_valor": (cont["nao_encontrado"] + cont["rejeitado"] + faltando) if it["obrigatorio"] else 0,
                      "progresso": round(decididos / len(arquivos), 3) if arquivos else 0})
    return saida


def matriz(db: Session, pasta: Path, status: str | None = None, item: str | None = None, grupo: str | None = None) -> dict:
    prot = PR.carregar(pasta)
    itens = prot["itens"]
    dados = C.carregar(pasta)
    docs = _documentos(db, pasta)
    todos_arquivos = [d.arquivo for d in docs]
    itens_vis = [i for i in itens if not item or i["id"] == item]
    linhas = []
    for d in docs:
        if grupo and (d.grupo or "") != grupo:
            continue
        celulas = {}
        for it in itens_vis:
            r = _resumo_celula(C.celula_de(dados, d.arquivo, it["id"]), it["tipo"])
            if r and status and r["status"] != status:
                r = {**r, "oculta": True}
            celulas[it["id"]] = r
        if status and not any(c and not c.get("oculta") for c in celulas.values()):
            continue
        n_dec = sum(1 for it in itens if C.decidida(C.celula_de(dados, d.arquivo, it["id"])))
        linhas.append({"documento_id": d.id, "arquivo": d.arquivo, "rotulo": svc_dados.rotulo_do_documento(d), "grupo": d.grupo, "ano": d.ano, "celulas": celulas,
                       "decididas": n_dec, "total": len(itens)})
    return {"itens": [{"id": i["id"], "nome": i["nome"], "tipo": i["tipo"], "obrigatorio": i["obrigatorio"]} for i in itens_vis], "linhas": linhas,
            "contadores": contadores(itens, dados, todos_arquivos), "grupos": sorted({d.grupo for d in docs if d.grupo}), "versao_protocolo": prot["versao_protocolo"],
            "ultima_execucao": dados.get("ultima_execucao"), "documentos": len(docs), "status": list(C.STATUS), "rotulo_status": C.ROTULO_STATUS}


def _item_ou_erro(pasta: Path, item_id: str) -> dict:
    for i in PR.carregar(pasta)["itens"]:
        if i["id"] == item_id:
            return i
    raise KeyError(f"O item '{item_id}' não está no protocolo.")


def detalhe(db: Session, pasta: Path, documento_id: int, item_id: str) -> dict:
    from app.models import Documento

    doc = db.get(Documento, documento_id)
    if doc is None:
        raise KeyError(f"Documento {documento_id} não existe.")
    item = _item_ou_erro(pasta, item_id)
    cel = C.celula_de(C.carregar(pasta), doc.arquivo, item_id)
    if cel is None:
        raise LookupError("Esta célula ainda não foi coletada: execute a coleta.")
    trechos = []
    for t in cel.get("trechos") or []:
        pos = svc_planilha.posicao_do_trecho(pasta, documento_id, t["texto"])
        trechos.append({**t, "posicao": pos, "contexto": f"/api/projetos/{pasta.name}/analises/kwic/contexto?documento_id={documento_id}&posicao={pos}" if pos is not None else None})
    return {"documento_id": documento_id, "arquivo": doc.arquivo, "rotulo": svc_dados.rotulo_do_documento(doc), "item": item, "celula": {**cel, "trechos": trechos},
            "valor_texto": C.valor_como_texto(cel, item["tipo"])}


def _hashes(db: Session, pasta: Path, doc, item: dict) -> tuple[str | None, str]:
    params = svc_parametros.carregar(pasta)
    return M.hash_documento(pasta, doc.id, svc_ruido.excluir_ruido(params)), PR.hash_item(item)


def decidir(db: Session, pasta: Path, documento_id: int, item_id: str, acao: str, valor=None, nota: str | None = None) -> dict:
    from app.models import Documento

    doc = db.get(Documento, documento_id)
    if doc is None:
        raise KeyError(f"Documento {documento_id} não existe.")
    item = _item_ou_erro(pasta, item_id)
    hd, hi = _hashes(db, pasta, doc, item)
    with C.trava(pasta):
        dados = C.carregar(pasta)
        cel = C.celula_de(dados, doc.arquivo, item_id)
        if cel is None:
            raise LookupError("Esta célula ainda não foi coletada: execute a coleta.")
        C.decidir(cel, acao, item, valor, nota, hd, hi)
        C.salvar(pasta, dados)
    return {"status": cel["status"], "valor": C.valor_como_texto(cel, item["tipo"]), "origem": cel.get("origem")}


def decidir_lote(db: Session, pasta: Path, acao: str, item_id: str | None = None, documento_id: int | None = None, min_confianca: float | None = None) -> dict:
    if acao not in ("aceitar", "rejeitar"):
        raise ValueError("Em lote só é possível aceitar ou rejeitar.")
    if not item_id and not documento_id:
        raise ValueError("Informe o item ou o documento.")
    prot = PR.carregar(pasta)
    itens = {i["id"]: i for i in prot["itens"]}
    if item_id and item_id not in itens:
        raise KeyError(f"O item '{item_id}' não está no protocolo.")
    docs = [d for d in _documentos(db, pasta) if not documento_id or d.id == documento_id]
    if documento_id and not docs:
        raise KeyError(f"Documento {documento_id} não existe.")
    aplicadas = ignoradas_ambiguas = ignoradas_sem_valor = ignoradas_baixa = 0
    with C.trava(pasta):
        dados = C.carregar(pasta)
        for d in docs:
            for iid, it in itens.items():
                if item_id and iid != item_id:
                    continue
                cel = C.celula_de(dados, d.arquivo, iid)
                if cel is None or cel["status"] != "sugerido":
                    continue
                if cel.get("valor") == E.AMBIGUO:
                    ignoradas_ambiguas += 1
                    continue
                if cel.get("valor") is None:
                    ignoradas_sem_valor += 1
                    continue
                if min_confianca is not None and float(cel.get("confianca") or 0) < min_confianca:
                    ignoradas_baixa += 1
                    continue
                hd, hi = _hashes(db, pasta, d, it)
                C.decidir(cel, acao, it, None, None, hd, hi)
                aplicadas += 1
        C.salvar(pasta, dados)
    return {"aplicadas": aplicadas, "ignoradas_ambiguas": ignoradas_ambiguas, "ignoradas_sem_valor": ignoradas_sem_valor, "ignoradas_baixa_confianca": ignoradas_baixa}
