"""15.7 (7.4) - Tópicos: LSA, NMF e LDA com coerência; varredura de K; CSV (UTF-8 com BOM, ``;``).

Rotas em /api/projetos/{slug}/analises/topicos*, num roteador próprio (o cálculo está em services/analises/topicos.py).
Sem parâmetros na URL valem os do projeto (bloco ``topicos`` de parametros.json): a 1ª carga reaproveita o cálculo
da etapa ``topicos``, que fica no cache em processo.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.models import Analise
from app.services import parametros as svc_parametros
from app.services.analises import dados, topicos
from app.services.etapas.topicos import parametros_topicos
from app.services.exportar.planilhas import _n, csv_bytes
from app.services.palavras_vazias import filtro_palavras_vazias

router = APIRouter(prefix="/api/projetos/{slug}/analises", tags=["analises"])

def _csv_seguro(nome: str, cabecalho: list[str], linhas) -> Response:
    """CSV com neutralização de fórmulas (mesma rotina das demais planilhas)."""
    return Response(content=csv_bytes(cabecalho, ([_n(v) for v in linha] for linha in linhas)),
                    media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


Modelo = Literal["lda", "nmf", "lsa"]
Unidade = Literal["documento", "segmento"]


def _contexto(slug: str, db: Session):
    pasta = pasta_do_projeto(slug)
    params = svc_parametros.carregar(pasta)
    metas = dados.documentos_do_corpus(db, pasta)
    if not metas:
        raise HTTPException(status_code=404, detail="Nenhum documento processado: execute o pipeline primeiro.")
    return pasta, params, metas


def _params(modelo: Modelo | None = None, k: int | None = Query(None, ge=2, le=topicos.K_MAX), unidade: Unidade | None = None,
            semente: int | None = None, iteracoes: int | None = Query(None, ge=10, le=20000),
            janela: int = Query(topicos.JANELA, ge=2, le=1000), perplexidade: bool = False) -> dict:
    return {"modelo": modelo, "k": k, "unidade": unidade, "semente": semente, "iteracoes": iteracoes, "janela": janela,
            "perplexidade": perplexidade}


def _do_instantaneo(db: Session, pasta, metas, filtro, efetivos: dict, p: dict) -> dict | None:
    """Resultado gravado pela etapa ``topicos``, se ainda vale (mesma assinatura de corpus e parâmetros): evita refazer
    o LDA (1000 iterações) na 1ª abertura do painel depois de reiniciar o servidor."""
    snap = db.scalars(select(Analise).where(Analise.tipo == "topicos").order_by(Analise.id.desc())).first()
    if snap is None or not snap.resultado_json:
        return None
    res = json.loads(snap.resultado_json)
    try:
        atual = topicos.assinatura(pasta, metas, filtro, janela=p["janela"], perplexidade=p["perplexidade"], **efetivos)
    except ValueError:
        return None
    if res.get("assinatura") != atual:
        return None
    topicos.guardar_em_cache(res, pasta, metas, filtro)
    return res


def _resultado(slug: str, db: Session, p: dict) -> dict:
    pasta, params, metas = _contexto(slug, db)
    base = parametros_topicos(params)
    efetivos = {c: (p[c] if p.get(c) is not None else base[c]) for c in base}
    filtro = filtro_palavras_vazias(params)
    if efetivos == base and p["janela"] == topicos.JANELA and not p["perplexidade"]:
        res = _do_instantaneo(db, pasta, metas, filtro, efetivos, p)
        if res is not None:
            return res
    try:
        return topicos.calcular(pasta, metas, filtro, janela=p["janela"],
                                perplexidade=p["perplexidade"], **efetivos)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/topicos")
def modelo_de_topicos(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    """Tópicos (palavras e pesos), coerência por tópico e média, proporções por documento, tópicos × ano/grupo e trechos
    representativos com página. ``perplexidade=true`` (só LDA) ajusta também o modelo de treino e avalia os retidos."""
    return _resultado(slug, db, p)


def _params_varredura(modelo: Modelo = "lda", k_min: int = Query(3, ge=2, le=topicos.K_MAX),
                      k_max: int = Query(12, ge=2, le=topicos.K_MAX), unidade: Unidade | None = None,
                      semente: int | None = None, iteracoes: int = Query(300, ge=10, le=5000),
                      janela: int = Query(topicos.JANELA, ge=2, le=1000), perplexidade: bool = True) -> dict:
    return {"modelo": modelo, "k_min": k_min, "k_max": k_max, "unidade": unidade, "semente": semente,
            "iteracoes": iteracoes, "janela": janela, "perplexidade": perplexidade}


def _varredura(slug: str, db: Session, p: dict) -> dict:
    pasta, params, metas = _contexto(slug, db)
    base = parametros_topicos(params)
    try:
        return topicos.varredura(pasta, metas, filtro_palavras_vazias(params), modelo=p["modelo"], k_min=p["k_min"],
                                 k_max=p["k_max"], unidade=p["unidade"] or base["unidade"],
                                 semente=base["semente"] if p["semente"] is None else p["semente"], iteracoes=p["iteracoes"],
                                 janela=p["janela"], perplexidade=p["perplexidade"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/topicos/varredura")
def varredura_de_k(slug: str, p: dict = Depends(_params_varredura), db: Session = Depends(get_db)):
    """Coerência média (UMass, NPMI, C_v) e perplexidade (LDA) para K de k_min a k_max (padrão 300 iterações)."""
    return _varredura(slug, db, p)


@router.get("/topicos/palavras.csv")
def topicos_palavras_csv(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    r = _resultado(slug, db, p)
    linhas = []
    for t in r["topicos"]:
        for i, w in enumerate(t["palavras"], 1):
            linhas.append([t["id"], i, w["termo"], w["peso"], t["prevalencia"], t["coerencia"]["umass"],
                           t["coerencia"]["npmi"], t["coerencia"]["cv"]])
    return _csv_seguro(f"topicos_{r['modelo']}_k{r['k']}_palavras.csv",
                       ["topico", "posicao", "termo", "peso", "prevalencia", "umass", "npmi", "cv"], linhas)


@router.get("/topicos/documentos.csv")
def topicos_documentos_csv(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    r = _resultado(slug, db, p)
    cab = ["documento_id", "rotulo", "ano", "grupo", *[f"topico_{t['id']}" for t in r["topicos"]]]
    linhas = [[d["id"], d["rotulo"], d["ano"] or "", d["grupo"] or "", *d["pesos"]] for d in r["documentos"]]
    return _csv_seguro(f"topicos_{r['modelo']}_k{r['k']}_documentos.csv", cab, linhas)


@router.get("/topicos/varredura.csv")
def varredura_csv(slug: str, p: dict = Depends(_params_varredura), db: Session = Depends(get_db)):
    r = _varredura(slug, db, p)
    linhas = [[l["k"], l["umass"], l["npmi"], l["cv"], l["perplexidade"] if l["perplexidade"] is not None else ""] for l in r["linhas"]]
    return _csv_seguro(f"topicos_{r['modelo']}_varredura.csv", ["k", "umass", "npmi", "cv", "perplexidade"], linhas)
