"""16.1 / 16.2 - Monta a planilha do corpus (dados para a tela e para o .xlsx) a partir das partes (``partes``), dos metadados
(``metadados``) e das sugestões de LLM aceitas (``llm_partes``). As regras de preenchimento estão no docstring de ``partes.py``.

Abas do .xlsx: **Corpus** (uma linha por documento; rótulo, arquivo, ano, grupo, título, autores, DOI, uma coluna por parte e a coluna
"Sugestões LLM (não aceitas)"), **Rastreabilidade** (uma linha por documento/parte/trecho: página, seção de origem, regra, método
seção|padrão|llm, nota), **Metadados** (campos da 16.4 com origem e confiança), **Cobertura** (por parte: seção / padrão / LLM / não
encontrado) e **LEIA-ME**. Formatação: texto com quebra de linha, cabeçalho congelado, larguras, filtros; texto que começa com
``= + - @`` ganha apóstrofo (injeção de fórmula).
"""
import io
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.services import parametros as svc_parametros
from app.services import ruido as svc_ruido
from app.services.analises import dados as svc_dados
from app.services.corpus import llm_partes as L
from app.services.corpus import metadados as M
from app.services.corpus import partes as P
from app.services.corpus import projeto as svc_projeto
from app.services.exportar.planilhas import _seguro
from app.services.etapas.limpeza import caminho_limpo

_CACHE: dict = {}
_ILEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
LIMITE_CELULA = 32000
COLUNAS_FIXAS = ("Rótulo", "Arquivo", "Ano", "Grupo", "Título", "Autores", "DOI")
COLUNA_SUGESTOES = "Sugestões LLM (não aceitas)"


def parametros_planilha(pasta: Path) -> dict:
    p = svc_parametros.carregar(pasta)
    extra = p.get("planilha_corpus") if isinstance(p.get("planilha_corpus"), dict) else {}
    return {**P.PADRAO_PARAMETROS, **{k: v for k, v in extra.items() if k in P.PADRAO_PARAMETROS}}


def analise_do_documento(pasta: Path, documento_id: int, params: dict, excluir_ruido: bool) -> dict | None:
    """``partes.analisar_documento`` com cache em processo (chave: arquivos de texto limpo/ruído, parâmetros)."""
    lim = caminho_limpo(pasta, documento_id)
    if not lim.is_file():
        return None
    st = lim.stat()
    chave = (str(pasta), documento_id, st.st_mtime_ns, st.st_size, svc_ruido.marca_do_arquivo(pasta, documento_id),
             tuple(sorted(params.items())), excluir_ruido)
    if chave not in _CACHE:
        if len(_CACHE) > 400:
            _CACHE.clear()
        _CACHE[chave] = P.analisar_documento(pasta, documento_id, params, excluir_ruido)
    return _CACHE[chave]


def _celula(chave: str, base: dict | None, sugestoes: list[dict]) -> dict:
    trechos = list(base["trechos"]) if base else []
    aceitas = [s for s in sugestoes if s["status"] == "aceita"]
    for s in aceitas:
        trechos.append({"texto": s["texto"], "pagina": s["pagina"], "paginas": f"p. {s['pagina']}" if s["pagina"] else "", "secao": s.get("secao"),
                        "titulo_secao": s.get("titulo_secao"), "regra": f"{L.ROTULO_ORIGEM}: {s.get('modelo') or '?'}", "metodo": "llm", "nota": None})
    if not trechos:
        metodo = "nao"
    elif base and aceitas:
        metodo = "misto"
    elif aceitas:
        metodo = "llm"
    else:
        metodo = base["metodo"]
    partes_texto = []
    for t in trechos:
        pref = f"[{t['paginas']}] " if t.get("paginas") else ""
        marca = f"[{L.ROTULO_ORIGEM}] " if t["metodo"] == "llm" else ""
        partes_texto.append(pref + marca + t["texto"])
    return {"trechos": trechos, "metodo": metodo, "texto": "\n\n".join(partes_texto) if trechos else P.NAO_ENCONTRADO,
            "sugestoes": [{**s, "indice": i} for i, s in enumerate(sugestoes) if s["status"] != "aceita"]}


def montar(db: Session, pasta: Path) -> dict:
    """Dados da planilha: ``{"partes": [...], "linhas": [...], "cobertura": {...}, "parametros": {...}, "sem_texto": [...]}``."""
    params = parametros_planilha(pasta)
    excluir = svc_ruido.excluir_ruido(svc_parametros.carregar(pasta))
    meta = M.carregar(pasta)
    llm = L.carregar(pasta)
    linhas, sem_texto = [], []
    cob = {k: {"secao": 0, "padrao": 0, "llm": 0, "nao": 0} for k in P.CHAVES}
    for doc in svc_projeto.documentos_ativos(db):
        analise = analise_do_documento(pasta, doc.id, params, excluir)
        if analise is None:
            sem_texto.append(doc.arquivo)
            continue
        v = M.valores(meta["documentos"].get(doc.arquivo))
        celulas = {}
        sug_txt = []
        for chave in P.CHAVES:
            sugs = L.sugestoes_do_documento(llm, doc.arquivo, chave)
            c = _celula(chave, analise.get(chave), sugs)
            celulas[chave] = c
            base = analise.get(chave)
            if c["metodo"] == "nao":
                cob[chave]["nao"] += 1
            elif base:
                cob[chave][base["metodo"]] += 1
            else:
                cob[chave]["llm"] += 1
            for s in c["sugestoes"]:
                if s["status"] == "sugerida":
                    sug_txt.append(f"{P.ROTULO[chave]}: [p. {s['pagina']}] {s['texto']}" if s["pagina"] else f"{P.ROTULO[chave]}: {s['texto']}")
        linhas.append({
            "documento_id": doc.id, "rotulo": svc_dados.rotulo_do_documento(doc), "arquivo": doc.arquivo, "ano": doc.ano or v.get("ano"),
            "grupo": doc.grupo, "titulo": v.get("titulo"), "autores": "; ".join(v.get("autores") or []), "doi": v.get("doi"),
            "partes": celulas, "sugestoes_llm": "\n\n".join(sug_txt),
        })
    return {"partes": [{"chave": k, "rotulo": r, "modo": m} for k, r, m, _t in P.PARTES], "linhas": linhas, "cobertura": cob,
            "parametros": params, "sem_texto": sem_texto, "documentos": len(linhas)}


# ---------- xlsx ----------

def _txt(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = _ILEGAL.sub("", str(v))
    if len(s) > LIMITE_CELULA:
        s = s[:LIMITE_CELULA - 4] + " (…)"
    return _seguro(s)


def _cabecalho(ws, nomes: list[str], larguras: list[int]) -> None:
    ws.append([_txt(n) for n in nomes])
    for i, (n, w) in enumerate(zip(nomes, larguras), 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5D8A")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "B2"


def _fim(ws) -> None:
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.auto_filter.ref = ws.dimensions


LEIA_ME = [
    ("Planilha do corpus (Raio-X, Frente 16)", ""),
    ("", ""),
    ("O que é", "Uma linha por documento e uma coluna por parte do artigo, com trechos literais do próprio documento, a página e a origem. "
                "Nada é inventado: sem trecho, a célula diz \"não encontrado\"."),
    ("Colunas fixas", "Rótulo, arquivo, ano, grupo, título, autores e DOI (metadados da 16.4: o valor com a maior confiança, ou o editado à mão)."),
    ("Partes por seção", "Resumo, Introdução, Referencial teórico, Método, Resultados, Discussão, Conclusão: frases da seção detectada (3.1) "
                         "até o limite de caracteres ({max_caracteres}), cortando no fim de uma frase; \"(…)\" indica corte; [p. N] ou [pp. a-b] é a página."),
    ("Partes por padrão", "Objetivo, Perguntas de pesquisa/hipóteses, Dados/amostra/contexto, Limitações, Trabalhos futuros, Contribuições/implicações: "
                          "até {max_frases} frases com expressões típicas em inglês, português e espanhol (ex.: \"this paper aims\", \"RQ1\", \"data were collected\", "
                          "\"limitations\", \"future research\", \"we contribute\"), ordenadas por força do padrão, seção preferida e posição; cada uma com [p. N]. "
                          "Nota mínima {nota_minima}."),
    ("Exclusões", "Referências, apêndices, agradecimentos, declarações e os segmentos de ruído (autores, tabelas, repetições; 3.4) ficam de fora."),
    ("Método", "seção = trecho vem de uma seção detectada; padrão = frase que casou com padrões de linguagem (ver aba Rastreabilidade: regra e nota); "
               "llm = sugestão de LLM aceita pelo usuário e conferida contra o texto (marcada \"LLM (modelo)\")."),
    ("Sugestões LLM (não aceitas)", "Frases literais sugeridas por um LLM (16.2, opcional) que ainda não foram aceitas na tela: não fazem parte das células."),
    ("Cuidados", "A detecção de seções e frases é heurística: confira o trecho no documento (a tela abre o contexto) antes de citar. Padrões podem achar frases "
                 "que não são o objetivo/limitação do estudo; \"não encontrado\" não prova que o documento não tem a parte."),
    ("Abas", "Corpus; Rastreabilidade (um trecho por linha); Metadados (valor, origem e confiança); Cobertura; LEIA-ME."),
]


def gerar_xlsx(dados: dict, db: Session, pasta: Path) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Corpus"
    nomes = list(COLUNAS_FIXAS) + [p["rotulo"] for p in dados["partes"]] + [COLUNA_SUGESTOES]
    _cabecalho(ws, nomes, [22, 30, 7, 12, 40, 32, 22] + [60] * len(dados["partes"]) + [60])
    for l in dados["linhas"]:
        ws.append([_txt(l["rotulo"]), _txt(l["arquivo"]), l["ano"], _txt(l["grupo"]), _txt(l["titulo"]), _txt(l["autores"]), _txt(l["doi"])]
                  + [_txt(l["partes"][p["chave"]]["texto"]) for p in dados["partes"]] + [_txt(l["sugestoes_llm"]) or None])
    _fim(ws)

    wr = wb.create_sheet("Rastreabilidade")
    _cabecalho(wr, ["Documento", "Arquivo", "Parte", "Trecho", "Página", "Seção de origem", "Regra/padrão", "Método", "Nota"], [22, 30, 24, 80, 8, 28, 40, 10, 8])
    nomes_metodo = {"secao": "seção", "padrao": "padrão", "llm": "llm"}
    for l in dados["linhas"]:
        for p in dados["partes"]:
            for t in l["partes"][p["chave"]]["trechos"]:
                wr.append([_txt(l["rotulo"]), _txt(l["arquivo"]), _txt(p["rotulo"]), _txt(t["texto"]), t.get("pagina"),
                           _txt(t.get("titulo_secao") or t.get("secao")), _txt(t.get("regra")), nomes_metodo.get(t["metodo"], t["metodo"]), t.get("nota")])
    _fim(wr)

    wm = wb.create_sheet("Metadados")
    campos = [c for c in M.CAMPOS]
    cab = ["Rótulo", "Arquivo"]
    for c in campos:
        cab += [M.ROTULOS[c], f"{M.ROTULOS[c]} (origem)", f"{M.ROTULOS[c]} (confiança)"]
    _cabecalho(wm, cab, [22, 30] + [30, 12, 10] * len(campos))
    meta = M.carregar(pasta)
    por_arquivo = {l["arquivo"]: l for l in dados["linhas"]}
    for arquivo, l in por_arquivo.items():
        res = M.resolver(meta["documentos"].get(arquivo))
        linha = [_txt(l["rotulo"]), _txt(arquivo)]
        for c in campos:
            r = res.get(c)
            if r:
                v = r["valor"]
                linha += [_txt("; ".join(v) if isinstance(v, list) else v) if not isinstance(v, int) else v,
                          r["origem"] + (" (conflito)" if r["conflito"] else ""), r["confianca"]]
            else:
                linha += [None, None, None]
        wm.append(linha)
    _fim(wm)

    wc = wb.create_sheet("Cobertura")
    _cabecalho(wc, ["Parte", "Por seção", "Por padrão", "Por LLM (aceita)", "Não encontrado", "Total de documentos"], [34, 12, 12, 16, 16, 18])
    for p in dados["partes"]:
        c = dados["cobertura"][p["chave"]]
        wc.append([_txt(p["rotulo"]), c["secao"], c["padrao"], c["llm"], c["nao"], dados["documentos"]])
    _fim(wc)

    wl = wb.create_sheet("LEIA-ME")
    wl.column_dimensions["A"].width = 28
    wl.column_dimensions["B"].width = 120
    for a, b in LEIA_ME:
        wl.append([a, b.format(**dados["parametros"]) if b else ""])
    wl["A1"].font = Font(bold=True, size=14)
    for row in wl.iter_rows(min_row=2):
        row[0].font = Font(bold=True)
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- detalhe de uma célula (tela) ----------

def posicao_do_trecho(pasta: Path, documento_id: int, texto: str) -> int | None:
    """Posição (índice de token) do início do trecho no documento, para abrir o contexto ampliado do KWIC. ``None`` se não achar."""
    blocos = svc_dados.carregar_blocos(pasta, documento_id)
    tk = svc_dados.carregar_tokens(pasta, documento_id)
    if blocos is None or tk is None:
        return None
    trecho = re.sub(r"\s*\(…\)\s*$", "", texto)
    loc = L.TextoDoDocumento(blocos).localizar(trecho[:400])
    if loc is None:
        return None
    for i in range(tk["n"]):
        if tk["bloco"][i] == loc["bloco"] and tk["inicio"][i] >= loc["offset"]:
            return i
        if tk["bloco"][i] > loc["bloco"]:
            return i
    return None


def celula(db: Session, pasta: Path, documento_id: int, parte: str) -> dict | None:
    """Trechos de uma célula com página, seção, regra, método e a posição para o contexto (``/analises/kwic/contexto``)."""
    dados = montar(db, pasta)
    for l in dados["linhas"]:
        if l["documento_id"] == documento_id:
            c = l["partes"].get(parte)
            if c is None:
                return None
            trechos = []
            for t in c["trechos"]:
                pos = posicao_do_trecho(pasta, documento_id, t["texto"])
                trechos.append({**t, "posicao": pos,
                                "contexto": (f"/api/projetos/{pasta.name}/analises/kwic/contexto?documento_id={documento_id}&posicao={pos}" if pos is not None else None)})
            return {"documento_id": documento_id, "rotulo": l["rotulo"], "arquivo": l["arquivo"], "parte": parte, "rotulo_parte": P.ROTULO[parte],
                    "metodo": c["metodo"], "trechos": trechos, "sugestoes": c["sugestoes"]}
    return None
