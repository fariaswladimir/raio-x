"""Estilometria (15.6): Delta de Burrows e variantes, agrupamento, consenso entre faixas de MFW, PCA e MDS.

Rotas em /api/projetos/{slug}/analises/estilometria* (cálculo em services/analises/estilometria.py). Sem parâmetros na
URL valem os do projeto (bloco ``estilometria`` de parametros.json). Calculado na hora a partir do cache de tokens,
com memória em processo; a etapa ``estilometria`` grava o instantâneo para o laudo. CSV em UTF-8 com BOM e ``;``.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services import parametros as svc_parametros
from app.services import ruido as svc_ruido
from app.services.analises import dados, estilometria
from app.services.analises.dados import _marca
from app.services.etapas.linguistica import caminho_tokens
from app.services.etapas.estilometria import parametros_estilometria
from app.services.exportar.planilhas import _n, csv_bytes

router = APIRouter(prefix="/api/projetos/{slug}/analises", tags=["analises"])

Distancia = Literal["delta_classico", "argamon", "eder", "eder_simples", "cosine_delta", "cosseno"]
Unidade = Literal["documento", "amostra"]
Metodo = Literal["ward", "average"]
Pca = Literal["correlacao", "covariancia"]

_MEMO: dict = {}
_MEMO_MAX = 16


def _csv(nome: str, cabecalho: list[str], linhas) -> Response:
    return Response(content=csv_bytes(cabecalho, ([_n(v) for v in linha] for linha in linhas)),
                    media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _params(mfw: int | None = Query(None, ge=2, le=estilometria.MFW_MAX), distancia: Distancia | None = None,
            culling: float | None = Query(None, ge=0, le=100), unidade: Unidade | None = None,
            tamanho_amostra: int | None = Query(None, ge=100, le=100000), metodo: Metodo = "ward",
            k: int | None = Query(None, ge=2, le=50), pca: Pca = "correlacao",
            bandas: str | None = Query(None, description="Faixas de MFW do consenso, ex.: 100,200,300,400,500")) -> dict:
    return {"mfw": mfw, "distancia": distancia, "culling": culling, "unidade": unidade, "tamanho_amostra": tamanho_amostra,
            "metodo": metodo, "k": k, "pca": pca, "bandas": bandas}


def _bandas(texto: str | None) -> tuple[int, ...]:
    if not texto:
        return estilometria.BANDAS
    try:
        v = tuple(sorted({int(x) for x in texto.split(",") if x.strip()}))
    except ValueError:
        raise HTTPException(status_code=422, detail="bandas: use números separados por vírgula (ex.: 100,200,300).")
    if not v or len(v) > 20 or min(v) < 2 or max(v) > estilometria.MFW_MAX:
        raise HTTPException(status_code=422, detail=f"bandas: de 1 a 20 valores entre 2 e {estilometria.MFW_MAX}.")
    return v


def _estilometria(slug: str, db: Session, p: dict) -> dict:
    pasta = pasta_do_projeto(slug)
    params = svc_parametros.carregar(pasta)
    metas = dados.documentos_do_corpus(db, pasta)
    if not metas:
        raise HTTPException(status_code=404, detail="Nenhum documento processado: execute o pipeline primeiro.")
    base = parametros_estilometria(params)
    efetivos = {"mfw": p["mfw"] or base["mfw"], "culling": base["culling"] if p["culling"] is None else p["culling"],
                "distancia_": p["distancia"] or base["distancia_"], "unidade": p["unidade"] or base["unidade"],
                "tamanho_amostra": p["tamanho_amostra"] or base["tamanho_amostra"]}
    bandas = _bandas(p["bandas"])
    excluir = svc_ruido.excluir_ruido(params)
    marcas = tuple((m["id"], _marca(caminho_tokens(pasta, m["id"])), svc_ruido.marca_do_arquivo(pasta, m["id"])) for m in metas)
    chave = (str(pasta), marcas, dados.assinatura_metadados(metas), excluir, tuple(sorted(efetivos.items())),
             p["metodo"], p["k"], p["pca"], bandas)
    achado = _MEMO.get(chave)
    if achado is None:
        try:
            achado = estilometria.calcular(pasta, metas, metodo=p["metodo"], k=p["k"], pca_=p["pca"], bandas=bandas,
                                           excluir_ruido=excluir, **efetivos)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[chave] = achado
    return achado


@router.get("/estilometria")
def estilometria_do_corpus(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    """Distâncias Delta entre documentos (ou amostras), agrupamento, consenso entre faixas de MFW, PCA, MDS e perfis de estilo."""
    return _estilometria(slug, db, p)


@router.get("/estilometria/distancias.csv")
def estilometria_distancias_csv(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    r = _estilometria(slug, db, p)
    rot = [u["rotulo"] for u in r["unidades"]]
    linhas = [[rot[i], *linha] for i, linha in enumerate(r["matriz"])]
    return _csv(f"estilometria_{r['distancia']}_{r['mfw_efetivo']}mfw_distancias.csv", ["unidade", *rot], linhas)


@router.get("/estilometria/cargas.csv")
def estilometria_cargas_csv(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    r = _estilometria(slug, db, p)
    linhas = [[i, c["palavra"], c["pc1"], c["pc2"]] for i, c in enumerate(r["pca"]["cargas_todas"], 1)]
    return _csv(f"estilometria_pca_{r['pca']['tipo']}_{r['mfw_efetivo']}mfw_cargas.csv", ["posicao_mfw", "palavra", "carga_pc1", "carga_pc2"], linhas)


@router.get("/estilometria/unidades.csv")
def estilometria_unidades_csv(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    r = _estilometria(slug, db, p)
    linhas = [[u["id"], u["parte"], u["rotulo"], u["grupo"], u["ano"], u["idioma"], u["tokens"], u["cluster"], u["x"], u["y"],
               u["mx"], u["my"], u["distancia_media"], " | ".join(f"{v['rotulo']} ({v['distancia']})" for v in u["vizinhos"])]
              for u in r["unidades"]]
    cab = ["documento_id", "amostra", "rotulo", "grupo", "ano", "idioma", "tokens", "cluster", "pca_x", "pca_y", "mds_x", "mds_y",
           "distancia_media", "vizinhos"]
    return _csv(f"estilometria_{r['distancia']}_{r['mfw_efetivo']}mfw_unidades.csv", cab, linhas)
