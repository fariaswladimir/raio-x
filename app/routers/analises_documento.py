"""Raio-x por documento (15.3 legibilidade, 15.4 palavras-chave, 15.5 resumo) e agrupamento k-means/espectral/PCA (15.9).

Rotas em /api/projetos/{slug}/analises/{legibilidade, palavras-chave, sumarizacao, documento-extra/{id}, agrupamento}, num
roteador próprio (cálculo em services/analises/{legibilidade, palavras_chave, sumarizacao, agrupamento}.py). Tudo é calculado na
hora a partir do cache do pipeline, com memória em processo; a etapa ``documento_extra`` grava o instantâneo para o laudo.
CSV em UTF-8 com BOM e ``;``.
"""
import statistics
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.routers.analises import Por, voc_por
from app.services import parametros as svc_parametros
from app.services import vocabulario as svc_vocabulario
from app.services.analises import agrupamento, dados, documento_extra, legibilidade, palavras_chave, resumo, sumarizacao
from app.services.exportar.planilhas import _n, csv_bytes
from app.services.palavras_vazias import filtro_palavras_vazias

router = APIRouter(prefix="/api/projetos/{slug}/analises", tags=["analises"])

MetodoChave = Literal["rake", "yake", "textrank"]
MetodoResumo = Literal["textrank", "lexrank", "mmr"]
MetodoAgrupamento = Literal["kmeans", "espectral"]


def _csv(nome: str, cabecalho: list[str], linhas) -> Response:
    return Response(content=csv_bytes(cabecalho, ([_n(v) for v in linha] for linha in linhas)),
                    media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _contexto(slug: str, db: Session):
    pasta = pasta_do_projeto(slug)
    params = svc_parametros.carregar(pasta)
    metas = dados.documentos_do_corpus(db, pasta)
    if not metas:
        raise HTTPException(status_code=404, detail="Nenhum documento processado: execute o pipeline primeiro.")
    return pasta, params, metas


def _meta(metas: list[dict], documento_id: int) -> dict:
    for m in metas:
        if m["id"] == documento_id:
            return m
    raise HTTPException(status_code=404, detail=f"Documento {documento_id} sem análise (não processado ou com problema).")


def _ou_404(valor, documento_id: int):
    if valor is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} sem texto limpo: execute o pipeline.")
    return valor


# ---------- 15.3 legibilidade ----------

def _legibilidade(slug: str, db: Session) -> dict:
    pasta, params, metas = _contexto(slug, db)
    docs = []
    for m in metas:
        r = documento_extra.legibilidade_do_documento(pasta, m["id"], params)
        if r is None:
            continue
        docs.append({"documento_id": m["id"], "rotulo": m["rotulo"], "arquivo": m["arquivo"], "ano": m["ano"],
                     "grupo": m["grupo"], "paginas": m["paginas"], **r})
    por_idioma: dict[str, dict] = {}
    for idioma in sorted({str(d["idioma"]) for d in docs}):
        sel = [d for d in docs if str(d["idioma"]) == idioma]
        item = {"documentos": len(sel), "nao_confiaveis": sum(1 for d in sel if not d["confiavel"])}
        for k in ("flesch_en", "flesch_pt", "flesch_kincaid", "gunning_fog", "coleman_liau", "smog"):
            v = [d["indices"][k]["valor"] for d in sel if k in d["indices"]]
            if v:
                item[k] = {"min": min(v), "mediana": round(statistics.median(v), 2), "max": max(v)}
        por_idioma[idioma] = item
    return {
        "documentos": docs, "por_idioma": por_idioma, "metodologia": legibilidade.METODOLOGIA,
        "parametros": {"silabas_en": documento_extra.metodo_silabas(params), "excluir_ruido": documento_extra.excluir_ruido(params),
                       "min_frases": legibilidade.MIN_FRASES},
        "nota": "Fórmula principal = a do idioma do documento (Flesch EN ou Flesch PT); os índices de série foram calibrados para o inglês.",
    }


@router.get("/legibilidade")
def legibilidade_dos_documentos(slug: str, db: Session = Depends(get_db)):
    """Legibilidade de cada documento do corpo: Flesch (EN), Flesch PT, Kincaid, Fog, Coleman-Liau, SMOG, com faixas e avisos."""
    return _legibilidade(slug, db)


@router.get("/legibilidade.csv")
def legibilidade_csv(slug: str, db: Session = Depends(get_db)):
    r = _legibilidade(slug, db)
    ids = ["flesch_en", "flesch_pt", "flesch_kincaid", "gunning_fog", "coleman_liau", "smog"]
    cab = ["documento_id", "rotulo", "idioma", "frases", "palavras", "palavras_por_frase", "silabas_por_palavra", "formula_principal",
           *ids, "confiavel", "avisos"]
    linhas = [[d["documento_id"], d["rotulo"], d["idioma"] or "", d["frases"], d["palavras"], d["palavras_por_frase"] or "",
               d["silabas_por_palavra"] or "", d["formula_principal"] or "", *[d["indices"].get(k, {}).get("valor", "") for k in ids],
               "sim" if d["confiavel"] else "não", " | ".join(d["avisos"])] for d in r["documentos"]]
    return _csv("legibilidade.csv", cab, linhas)


# ---------- 15.4 palavras-chave ----------

def _tfidf_do_documento(pasta, params, metas, documento_id: int) -> list[dict]:
    res = resumo.resumo_do_projeto(pasta, metas, params)
    for d in (res or {}).get("documentos", []):
        if d["documento_id"] == documento_id:
            return d["termos_distintivos"]
    return []


def _palavras_chave(slug: str, db: Session, documento_id: int, metodo: str | None, n: int | None) -> dict:
    pasta, params, metas = _contexto(slug, db)
    m = _meta(metas, documento_id)
    metodos = [metodo] if metodo else list(palavras_chave.METODOS)
    saida = {}
    try:
        for mt in metodos:
            saida[mt] = _ou_404(documento_extra.palavras_chave_do_documento(pasta, documento_id, params, mt, n), documento_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    leg = documento_extra.legibilidade_do_documento(pasta, documento_id, params)
    return {
        "documento_id": documento_id, "rotulo": m["rotulo"], "idioma": (leg or {}).get("idioma"),
        "metodos": saida, "tfidf": _tfidf_do_documento(pasta, params, metas, documento_id),
        "parametros": palavras_chave.parametros(params),
        "metodologia": ("RAKE (Rose et al., 2010), YAKE (Campos et al., 2020; implementação própria, menor é melhor) e TextRank "
                        "(Mihalcea e Tarau, 2004; sem filtro sintático), sobre o corpo do documento; ao lado, os termos distintivos "
                        "TF-IDF por lema (5.1), que comparam o documento com o corpus."),
    }


@router.get("/palavras-chave")
def palavras_chave_do_documento(slug: str, documento_id: int, metodo: MetodoChave | None = None,
                                n: int | None = Query(None, ge=1, le=50), db: Session = Depends(get_db)):
    """Palavras-chave de um documento por RAKE, YAKE e TextRank (todos, se ``metodo`` omitido), com TF-IDF ao lado."""
    return _palavras_chave(slug, db, documento_id, metodo, n)


@router.get("/palavras-chave.csv")
def palavras_chave_csv(slug: str, documento_id: int, metodo: MetodoChave | None = None,
                       n: int | None = Query(None, ge=1, le=50), db: Session = Depends(get_db)):
    r = _palavras_chave(slug, db, documento_id, metodo, n)
    linhas = [[mt, i, x["frase"], x["pontuacao"], x["frequencia"], ", ".join(str(p) for p in x["paginas"])]
              for mt, lista in r["metodos"].items() for i, x in enumerate(lista, 1)]
    linhas += [["tfidf", i, t["termo"], t.get("tfidf", ""), t.get("freq", ""), ""] for i, t in enumerate(r["tfidf"], 1)]
    return _csv(f"palavras_chave_{documento_id}.csv", ["metodo", "posicao", "frase", "pontuacao", "frequencia", "paginas"], linhas)


# ---------- 15.5 sumarização ----------

def _sumarizacao(slug: str, db: Session, documento_id: int, metodo: str, n: int | None) -> dict:
    pasta, params, metas = _contexto(slug, db)
    m = _meta(metas, documento_id)
    try:
        r = _ou_404(documento_extra.resumo_do_documento(pasta, documento_id, params, metodo, n), documento_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"documento_id": documento_id, "rotulo": m["rotulo"], **r, "parametros": sumarizacao.parametros(params),
            "metodologia": ("Frases do corpo (sem referências nem ruído), em ordem original, com página e seção; TextRank "
                            "(Mihalcea e Tarau, 2004), LexRank (Erkan e Radev, 2004, limiar 0,1) ou MMR (Carbonell e "
                            "Goldstein, 1998, λ = 0,7). São frases do próprio documento: confira o contexto antes de citar.")}


@router.get("/sumarizacao")
def sumarizacao_do_documento(slug: str, documento_id: int, metodo: MetodoResumo = "mmr",
                             n: int | None = Query(None, ge=1, le=30), db: Session = Depends(get_db)):
    """Resumo extrativo de um documento: ``n`` frases (padrão do projeto) em ordem original, com página e seção."""
    return _sumarizacao(slug, db, documento_id, metodo, n)


@router.get("/sumarizacao.csv")
def sumarizacao_csv(slug: str, documento_id: int, metodo: MetodoResumo = "mmr",
                    n: int | None = Query(None, ge=1, le=30), db: Session = Depends(get_db)):
    r = _sumarizacao(slug, db, documento_id, metodo, n)
    linhas = [[r["rotulo"], r["metodo"], f["classificacao"], f["pagina"], f["secao"], f["nota"], f["texto"]] for f in r["frases"]]
    return _csv(f"resumo_{documento_id}_{metodo}.csv", ["documento", "metodo", "classificacao", "pagina", "secao", "nota", "frase"], linhas)


@router.get("/documento-extra/{documento_id}")
def raio_x_do_documento(slug: str, documento_id: int, db: Session = Depends(get_db)):
    """Tudo do "Raio-x do documento" numa chamada: legibilidade, palavras-chave (3 métodos + TF-IDF) e resumos (3 métodos)."""
    pasta, params, metas = _contexto(slug, db)
    m = _meta(metas, documento_id)
    r = _ou_404(documento_extra.calcular_documento(pasta, documento_id, params), documento_id)
    return {**r, "rotulo": m["rotulo"], "arquivo": m["arquivo"], "paginas": m["paginas"],
            "tfidf": _tfidf_do_documento(pasta, params, metas, documento_id)}


# ---------- 15.9 agrupamento ----------

_MEMO: dict = {}
_MEMO_MAX = 12


def _agrupamento(slug: str, db: Session, metodo: str, k: int | None, por: str, max_df: float, min_df: int, vizinhos: int, semente: int) -> dict:
    pasta, params, metas = _contexto(slug, db)
    voc = svc_vocabulario.ler_vocabulario(pasta)
    if voc is None:
        raise HTTPException(status_code=404, detail="Vocabulário não encontrado: execute o pipeline primeiro.")
    voc_u, interno = voc_por(pasta, voc, por)
    filtro = filtro_palavras_vazias(params)
    chave = (str(pasta), svc_vocabulario.caminho_vocabulario(pasta).stat().st_mtime_ns, hash(filtro), dados.assinatura_metadados(metas),
             metodo, k, por, max_df, min_df, vizinhos, semente)
    achado = _MEMO.get(chave)
    if achado is None:
        try:
            achado = agrupamento.calcular(voc_u, metas, filtro, por=interno, metodo=metodo, k=k, min_df=min_df, max_df=max_df,
                                          vizinhos=vizinhos, semente=semente)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        achado = {**achado, "unidade": por}
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[chave] = achado
    return achado


def _params_agrupamento(metodo: MetodoAgrupamento = "kmeans", k: int | None = Query(None, ge=2, le=30), por: Por = "lema",
                        max_df: float = Query(0.9, gt=0, le=1), min_df: int = Query(2, ge=1),
                        vizinhos: int = Query(agrupamento.N_VIZINHOS, ge=1, le=100),
                        semente: int = Query(agrupamento.SEMENTE, ge=0)) -> dict:
    return {"metodo": metodo, "k": k, "por": por, "max_df": max_df, "min_df": min_df, "vizinhos": vizinhos, "semente": semente}


@router.get("/agrupamento")
def agrupar_documentos(slug: str, p: dict = Depends(_params_agrupamento), db: Session = Depends(get_db)):
    """k-means ou espectral sobre o TF-IDF da similaridade (k automático por silhueta), PCA 2D e ARI contra o Ward."""
    return _agrupamento(slug, db, **p)


@router.get("/agrupamento.csv")
def agrupamento_csv(slug: str, p: dict = Depends(_params_agrupamento), db: Session = Depends(get_db)):
    r = _agrupamento(slug, db, **p)
    linhas = [[d["id"], d["rotulo"], d["grupo"], d["ano"], d["cluster"], d["ward"], d["x"], d["y"]] for d in r["documentos"]]
    return _csv(f"agrupamento_{r['metodo']}_k{r['k']}.csv", ["documento_id", "rotulo", "grupo", "ano", "cluster", "cluster_ward", "pca_x", "pca_y"], linhas)
