"""4.5 Classes gramaticais e entidades (spaCy opcional): situação, frequências por classe e painel de entidades (NER).

Rotas: /api/spacy/status e /api/projetos/{slug}/analises/classes-gramaticais(.csv), /analises/entidades(.csv).
Sem spaCy, ``/api/spacy/status`` diz "não instalado" e as consultas devolvem listas vazias com ``sem_classes``.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.analises import _contexto
from app.services import spacy_nlp
from app.services.analises import classes_gramaticais as cg
from app.services.analises import dados
from app.services.exportar.planilhas import _n, csv_bytes
from app.services.palavras_vazias import filtro_palavras_vazias

router_config = APIRouter(prefix="/api/spacy", tags=["spacy"])
router = APIRouter(prefix="/api/projetos/{slug}/analises", tags=["spacy"])


@router_config.get("/status")
def status_spacy():
    """Pacote e modelos instalados (a tela mostra "não instalado" na opção de lematização "spacy")."""
    return {**spacy_nlp.status(),
            "instalar": "execute instalar_spacy.bat (pip install -r requirements-spacy.txt e os modelos en_core_web_sm e pt_core_news_sm)",
            "idiomas_suportados": list(spacy_nlp.MODELOS)}


def _csv(nome: str, cab: list[str], linhas) -> Response:
    return Response(content=csv_bytes(cab, ([_n(v) for v in l] for l in linhas)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _classes_params(classes: str = Query("substantivos", description="UPOS ou atalhos separados por vírgula: substantivos, adjetivos, verbos, plenas"),
                    escopo: Literal["corpus", "documento", "grupo", "ano"] = "corpus", valor: str | None = None,
                    por: Literal["lema", "forma"] = "lema", vazias: Literal["filtrar", "manter"] = "filtrar") -> dict:
    return dict(classes=classes, escopo=escopo, valor=valor, por=por, vazias=vazias)


def _frequencias(slug, db, limite, classes, escopo, valor, por, vazias):
    pasta, params, _voc, metas = _contexto(slug, db)
    try:
        sel = dados.filtrar_escopo(metas, escopo, valor)
        r = cg.frequencias(pasta, sel, filtro_palavras_vazias(params), classes.split(","), por=por,
                           filtrar=(vazias == "filtrar"), limite=limite)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    r["spacy"] = spacy_nlp.status()
    return r


@router.get("/classes-gramaticais")
def frequencias_por_classe(slug: str, p: dict = Depends(_classes_params), limite: int = Query(200, ge=1, le=5000),
                           db: Session = Depends(get_db)):
    """Termos mais frequentes só das classes pedidas (ex.: substantivos, adjetivos, verbos), com a classe predominante."""
    return _frequencias(slug, db, limite, **p)


@router.get("/classes-gramaticais.csv")
def frequencias_por_classe_csv(slug: str, p: dict = Depends(_classes_params), limite: int = Query(5000, ge=1, le=100000),
                               db: Session = Depends(get_db)):
    r = _frequencias(slug, db, limite, **p)
    return _csv("classes_gramaticais.csv", ["posicao", "termo", "classe", "freq", "por_10k", "docs"],
                ([i + 1, t["termo"], t["classe"], t["freq"], t["por_10k"], t["docs"]] for i, t in enumerate(r["itens"])))


def _entidades(slug, db, tipos, min_freq, documento_id, limite):
    pasta, params, _voc, metas = _contexto(slug, db)
    r = cg.entidades(pasta, metas, (tipos or "").split(","), min_freq=min_freq, limite=limite, documento_id=documento_id,
                     filtro=filtro_palavras_vazias(params))
    r["spacy"] = spacy_nlp.status()
    return r


@router.get("/entidades")
def entidades_nomeadas(slug: str, tipos: str = Query("ORG,PERSON,GPE", description="Rótulos do NER separados por vírgula"),
                       min_freq: int = Query(1, ge=1), documento_id: int | None = None, limite: int = Query(200, ge=1, le=5000),
                       db: Session = Depends(get_db)):
    """Entidades nomeadas (NER do spaCy) do corpus ou de um documento, com contagem, documentos, exemplos com página e a consulta KWIC."""
    return _entidades(slug, db, tipos, min_freq, documento_id, limite)


@router.get("/entidades.csv")
def entidades_csv(slug: str, tipos: str = "ORG,PERSON,GPE", min_freq: int = Query(1, ge=1), documento_id: int | None = None,
                  limite: int = Query(5000, ge=1, le=100000), db: Session = Depends(get_db)):
    r = _entidades(slug, db, tipos, min_freq, documento_id, limite)
    return _csv("entidades.csv", ["posicao", "entidade", "tipo", "freq", "docs", "consulta_kwic"],
                ([i + 1, e["texto"], e["tipo"], e["freq"], e["docs"], e["kwic"]] for i, e in enumerate(r["itens"])))
