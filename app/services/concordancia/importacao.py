"""15.1 - Importação da codificação humana (planilha .xlsx de coleta) para a tabela ``codificacao_trecho``.

A planilha só é lida (openpyxl ``read_only``, ``data_only``); nada é gravado nela.

Abas e colunas
--------------
- Aba de trechos: a pedida (``aba``), ou ``"*"`` para todas as abas com colunas de trecho e código reconhecidas, ou,
  sem pedido, a que tem "trecho" no nome; senão a que tem mais linhas com trecho e código.
- Cabeçalho: a primeira das 10 primeiras linhas com colunas de **trecho** e **código** reconhecidas (sem acento,
  minúsculas). Papéis: ``texto`` (trecho original/citação original/trecho/texto/excerpt/quote), ``traducao``,
  ``codigo`` (código; "códigos secundários" e "rótulo do código" não contam), ``tema``, ``registro`` (ID registro),
  ``fonte`` (ID fonte/documento/arquivo), ``fonte_rotulo`` (Fonte (autor, ano)), ``pagina``, ``secao``.
  ``mapeamento`` ({papel: nome exato da coluna}) sobrepõe a detecção.
- Documento do corpus: (1) se a planilha tiver uma aba de identificação com "ID fonte" e uma coluna "Arquivo", a
  fonte vira o nome do arquivo, comparado sem extensão com os arquivos do projeto (igual, ou um começa com o outro);
  (2) senão, os dígitos da fonte (R001 -> 1) contra o ``id_estudo`` numérico do documento. Sem casamento, o trecho
  entra sem documento (o relatório lista as fontes).
- Codebook: se houver aba "Codebook" e ``codebook`` for verdadeiro (padrão: só quando o dicionário do projeto está
  vazio), as categorias entram no dicionário do projeto (6.4), que é o codebook que o LLM recebe.
"""
import io
import re
import unicodedata
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CodificacaoTrecho, Documento


class PlanilhaInvalida(ValueError):
    """Arquivo ou colunas que não servem (mensagem para a tela)."""


def _sa(s) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch)).lower().strip()


# Ordem importa: cada papel pega a 1ª coluna livre que passa no teste; testes "fortes" antes dos "fracos".
_PAPEIS: list[tuple[str, callable]] = [
    ("texto", lambda h: ("original" in h and ("trecho" in h or "citac" in h or "texto" in h))),
    ("traducao", lambda h: "traduz" in h or "traducao" in h or "translat" in h),
    ("texto", lambda h: h in ("trecho", "citacao", "texto", "excerpt", "quote", "sentenca", "trecho (sentenca)", "segmento")),
    ("codigo", lambda h: h in ("codigo", "code", "cod", "codigo humano", "codigo principal", "codigo (humano)")),
    ("codigo", lambda h: h.startswith("codigo") and "secund" not in h and "rotulo" not in h),
    ("tema", lambda h: h in ("tema", "theme")),
    ("registro", lambda h: h in ("id registro", "registro", "id trecho", "id")),
    ("fonte", lambda h: h in ("id fonte", "fonte id", "id documento", "documento", "arquivo", "id estudo", "estudo", "source")),
    ("fonte_rotulo", lambda h: h.startswith("fonte") or "autor, ano" in h or h in ("referencia", "citacao da fonte")),
    ("pagina", lambda h: h in ("pagina", "pag", "pag.", "page", "p.", "paginas") or h.startswith("pagina")),
    ("secao", lambda h: h.startswith("secao") or h == "section"),
]
OBRIGATORIOS = ("texto", "codigo")
PAPEIS = ("texto", "traducao", "codigo", "tema", "registro", "fonte", "fonte_rotulo", "pagina", "secao")


def mapear_colunas(cabecalho: list) -> dict[str, int]:
    hs = [_sa(h) if h is not None else "" for h in cabecalho]
    achados: dict[str, int] = {}
    for papel, teste in _PAPEIS:
        if papel in achados:
            continue
        for j, h in enumerate(hs):
            if h and j not in achados.values() and teste(h):
                achados[papel] = j
                break
    return achados


def _aplicar_mapeamento(cabecalho: list, auto: dict[str, int], mapeamento: dict | None) -> dict[str, int]:
    if not mapeamento:
        return auto
    hs = [str(h).strip() if h is not None else "" for h in cabecalho]
    saida = dict(auto)
    for papel, coluna in mapeamento.items():
        if papel not in PAPEIS:
            raise PlanilhaInvalida(f"Papel desconhecido '{papel}'. Use: {', '.join(PAPEIS)}.")
        if coluna in (None, ""):
            saida.pop(papel, None)
            continue
        if str(coluna) not in hs:
            raise PlanilhaInvalida(f"Coluna '{coluna}' (para {papel}) não existe. Colunas: {', '.join(h for h in hs if h)}.")
        j = hs.index(str(coluna))
        saida = {p: i for p, i in saida.items() if i != j}
        saida[papel] = j
    return saida


def _cabecalho(linhas: list[tuple], mapeamento: dict | None = None) -> tuple[int | None, dict[str, int]]:
    for i, linha in enumerate(linhas[:10]):
        try:
            m = _aplicar_mapeamento(list(linha), mapear_colunas(list(linha)), mapeamento)
        except PlanilhaInvalida:  # coluna do mapeamento não está nesta linha: não é o cabeçalho
            continue
        if all(p in m for p in OBRIGATORIOS):
            return i, m
    return None, {}


def ler_planilha(conteudo: bytes) -> dict[str, list[tuple]]:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as e:  # não é .xlsx
        raise PlanilhaInvalida(f"Não foi possível ler o .xlsx: {type(e).__name__}: {e}")
    try:
        return {ws.title: list(ws.iter_rows(values_only=True)) for ws in wb.worksheets}
    finally:
        wb.close()


def _celula(linha: tuple, j: int | None):
    v = linha[j] if j is not None and j < len(linha) else None
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _pagina(v) -> int | None:
    if v is None:
        return None
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else None


def inspecionar(abas: dict[str, list[tuple]], mapeamento: dict | None = None) -> list[dict]:
    """Abas com trecho e código reconhecidos: cabeçalho, colunas por papel e nº de linhas com trecho (e com código)."""
    saida = []
    for nome, linhas in abas.items():
        i, m = _cabecalho(linhas, mapeamento)
        if i is None:
            continue
        corpo = linhas[i + 1:]
        com_texto = [l for l in corpo if _celula(l, m["texto"])]
        cab = [str(c) if c is not None else "" for c in linhas[i]]
        saida.append({"aba": nome, "linha_cabecalho": i + 1, "colunas": {p: cab[j] for p, j in m.items()},
                      "cabecalho": [c for c in cab if c], "trechos": len(com_texto),
                      "com_codigo": sum(1 for l in com_texto if _celula(l, m["codigo"]))})
    return saida


def escolher_abas(info: list[dict], aba: str | None) -> list[str]:
    if not info:
        raise PlanilhaInvalida("Nenhuma aba com colunas de trecho e de código reconhecidas (informe o mapeamento).")
    nomes = [i["aba"] for i in info]
    if aba == "*":
        return nomes
    if aba:
        if aba not in nomes:
            raise PlanilhaInvalida(f"A aba '{aba}' não tem colunas de trecho e código reconhecidas. Abas aceitas: {', '.join(nomes)}.")
        return [aba]
    com_trecho = [i for i in info if "trecho" in _sa(i["aba"])]
    escolhida = max(com_trecho or info, key=lambda i: i["com_codigo"])
    return [escolhida["aba"]]


# ---------- casamento com os documentos do corpus ----------

def _sem_ext(nome: str) -> str:
    n = _sa(Path(str(nome).replace("\\", "/")).name)
    return re.sub(r"\.(md|pdf|txt|docx?|html?)$", "", n)


def arquivos_por_fonte(abas: dict[str, list[tuple]]) -> dict[str, str]:
    """{fonte: arquivo} de uma aba de identificação (coluna "ID fonte" + coluna com "arquivo" no nome)."""
    for linhas in abas.values():
        for i, linha in enumerate(linhas[:10]):
            hs = [_sa(h) if h is not None else "" for h in linha]
            jf = next((j for j, h in enumerate(hs) if h in ("id fonte", "fonte id", "id estudo")), None)
            ja = next((j for j, h in enumerate(hs) if "arquivo" in h), None)
            if jf is not None and ja is not None:
                return {str(l[jf]).strip(): str(l[ja]).strip() for l in linhas[i + 1:]
                        if jf < len(l) and ja < len(l) and l[jf] and l[ja]}
    return {}


def casar_documentos(db: Session, fontes: set[str], arquivos: dict[str, str]) -> tuple[dict[str, int], dict[str, str]]:
    """({fonte: documento_id}, {fonte: método}). Ver docstring do módulo."""
    docs = list(db.scalars(select(Documento).where(Documento.status != "removido")))
    por_stem = {_sem_ext(d.arquivo): d.id for d in docs}
    por_numero: dict[int, int] = {}
    for d in docs:
        if d.id_estudo and str(d.id_estudo).isdigit():
            por_numero.setdefault(int(d.id_estudo), d.id)
    achados, metodo = {}, {}
    for f in fontes:
        arq = arquivos.get(f)
        if arq:
            alvo = _sem_ext(arq)
            did = por_stem.get(alvo) or next((i for s, i in por_stem.items() if s.startswith(alvo) or alvo.startswith(s)), None)
            if did is not None:
                achados[f], metodo[f] = did, "arquivo"
                continue
        m = re.search(r"\d+", f or "")
        if m and int(m.group()) in por_numero:
            achados[f], metodo[f] = por_numero[int(m.group())], "id_estudo"
    return achados, metodo


# ---------- importação ----------

def importar(db: Session, pasta: Path, conteudo: bytes, aba: str | None = None, mapeamento: dict | None = None,
             modo: str = "substituir", codebook: bool | None = None) -> dict:
    """Lê a planilha e grava os trechos. ``modo`` "substituir" (padrão) apaga os trechos anteriores (e a codificação do
    LLM deles); "acrescentar" mantém e pula registros já existentes. Devolve o relatório da importação."""
    if modo not in ("substituir", "acrescentar"):
        raise PlanilhaInvalida(f"Modo inválido '{modo}': use 'substituir' ou 'acrescentar'.")
    abas = ler_planilha(conteudo)
    info = inspecionar(abas, mapeamento)
    escolhidas = escolher_abas(info, aba)
    arquivos = arquivos_por_fonte(abas)
    if modo == "substituir":
        db.execute(delete(CodificacaoTrecho))
        existentes: set = set()
    else:
        existentes = {(r.aba, r.registro, r.texto) for r in db.scalars(select(CodificacaoTrecho))}
    novos, repetidos, sem_codigo = [], 0, 0
    for nome in escolhidas:
        linhas = abas[nome]
        i, m = _cabecalho(linhas, mapeamento)
        for linha in linhas[i + 1:]:
            texto = _celula(linha, m.get("texto"))
            if not texto:
                continue
            reg = _celula(linha, m.get("registro"))
            chave = (nome, reg, texto)
            if chave in existentes:
                repetidos += 1
                continue
            existentes.add(chave)
            cod = _celula(linha, m.get("codigo"))
            sem_codigo += cod is None
            novos.append(CodificacaoTrecho(
                registro=reg, fonte=_celula(linha, m.get("fonte")), fonte_rotulo=_celula(linha, m.get("fonte_rotulo")),
                aba=nome, pagina=_pagina(_celula(linha, m.get("pagina"))), secao=_celula(linha, m.get("secao")), texto=texto,
                traducao=_celula(linha, m.get("traducao")), codigo_humano=cod, tema_humano=_celula(linha, m.get("tema")),
                status="pendente"))
    fontes = {t.fonte for t in novos if t.fonte}
    casados, metodo = casar_documentos(db, fontes, arquivos)
    for t in novos:
        t.documento_id = casados.get(t.fonte)
    db.add_all(novos)
    db.commit()
    rel_codebook = _importar_codebook(db, pasta, conteudo, abas, codebook)
    total = db.query(CodificacaoTrecho).count()
    com_doc = sum(1 for t in novos if t.documento_id)
    return {
        "abas_reconhecidas": info, "abas_importadas": escolhidas, "modo": modo,
        "trechos_importados": len(novos), "repetidos_pulados": repetidos, "sem_codigo_humano": sem_codigo,
        "trechos_no_projeto": total, "codigos_distintos": len({t.codigo_humano for t in novos if t.codigo_humano}),
        "fontes": len(fontes), "fontes_casadas": len(casados),
        "metodo_casamento": {mm: sum(1 for v in metodo.values() if v == mm) for mm in ("arquivo", "id_estudo")},
        "fontes_sem_documento": sorted(fontes - set(casados)),
        "trechos_com_documento": com_doc, "pct_com_documento": round(100 * com_doc / len(novos), 1) if novos else None,
        "aba_de_arquivos": bool(arquivos), "codebook": rel_codebook,
    }


def _importar_codebook(db: Session, pasta: Path, conteudo: bytes, abas: dict, codebook: bool | None) -> dict | None:
    from app.services import dicionario as svc_dic
    from app.services.etapas.dicionario import apagar_instantaneo

    if not any("codebook" in _sa(n) for n in abas):
        return None
    atual = svc_dic.carregar(pasta)
    if codebook is None:
        codebook = not atual["categorias"]
    if not codebook:
        return {"importado": False, "motivo": "o dicionário do projeto já tem categorias (use codebook=true para mesclar)",
                "categorias_no_dicionario": len(atual["categorias"])}
    dic, rel = svc_dic.importar_codebook(conteudo, atual, modo="mesclar")
    svc_dic.salvar(pasta, dic)
    apagar_instantaneo(db)
    return {"importado": True, **{k: rel[k] for k in ("aba", "categorias_importadas", "novas", "atualizadas", "categorias_no_dicionario")}}
