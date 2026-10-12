"""Tela de metodologia: método e referências bibliográficas por análise (fonte: services/metodologia/catalogo.yaml).

Rotas (todas somente leitura):
- GET /api/metodologia                        catálogo (filtros ?familia= e ?status=)
- GET /api/metodologia/referencias            referências formatadas (?formato=abnt|apa|bibtex&ids=a,b)
- GET /api/metodologia/referencias.bib|.txt   downloads (mesmos filtros; .txt aceita ?formato=abnt|apa)
- GET /api/metodologia/{id}                   uma análise
- GET /api/projetos/{slug}/metodologia        o catálogo marcando o que o projeto usou e com os parâmetros atuais
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.models import Analise
from app.services import metodologia as svc
from app.services import parametros as svc_parametros
from app.services.metodologia import formatos

router = APIRouter(tags=["metodologia"])

Formato = Literal["abnt", "apa", "bibtex"]


def _ids(ids: str | None) -> list[str]:
    return [i.strip() for i in (ids or "").split(",") if i.strip()]


def _catalogo_json(analises: list[dict], familias_todas: list[str]) -> dict:
    return {"total": len(analises), "familias": [f for f in familias_todas if any(a["familia"] == f for a in analises)],
            "status": list(svc.STATUS), "analises": analises}


def _refs(ids: str | None) -> list[dict]:
    try:
        return svc.referencias_de(_ids(ids))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Análise '{exc.args[0]}' não encontrada no catálogo.")


@router.get("/api/metodologia")
def listar_catalogo(familia: str | None = None, status: Literal["implementado", "parcial", "planejado"] | None = None):
    cat = svc.carregar()
    analises = svc.listar(familia, status)
    return _catalogo_json(analises, cat["familias"])


@router.get("/api/metodologia/referencias")
def referencias(formato: Formato = "abnt", ids: str | None = Query(None, description="ids de análises separados por vírgula")):
    refs = _refs(ids)
    chaves = formatos.chaves_bibtex_unicas(refs)
    itens = []
    for r, chave_bib in zip(refs, chaves):
        itens.append({
            "chave": r["chave"], "bibtex_chave": chave_bib, "analises": r["analises"], "nota": r.get("nota"),
            "texto": formatos.formatar_bibtex(r, chave_bib) if formato == "bibtex" else formatos.formatar(r, formato),
            "html": None if formato == "bibtex" else formatos.formatar(r, formato, html=True),
        })
    return {"formato": formato, "total": len(itens), "referencias": itens}


def _download(conteudo: str, nome: str, tipo: str) -> Response:
    return Response(conteudo.encode("utf-8"), media_type=f"{tipo}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@router.get("/api/metodologia/referencias.bib")
def baixar_bib(ids: str | None = None):
    return _download(svc.texto_referencias(_refs(ids), "bibtex"), "referencias.bib", "application/x-bibtex")


@router.get("/api/metodologia/referencias.txt")
def baixar_txt(formato: Literal["abnt", "apa"] = "abnt", ids: str | None = None):
    return _download(svc.texto_referencias(_refs(ids), formato), f"referencias_{formato}.txt", "text/plain")


@router.get("/api/metodologia/nota")
def nota_metodologica():
    """13.2: a nota metodológica geral (docs/nota_metodologica.md) em texto Markdown."""
    from app.config import RAIZ
    arq = RAIZ / "docs" / "nota_metodologica.md"
    if not arq.is_file():
        raise HTTPException(status_code=404, detail="docs/nota_metodologica.md não encontrado.")
    return Response(arq.read_bytes(), media_type="text/markdown; charset=utf-8")


@router.get("/api/metodologia/{id_}")
def obter_analise(id_: str):
    a = svc.obter(id_)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Análise '{id_}' não encontrada no catálogo.")
    return a


@router.get("/api/projetos/{slug}/metodologia")
def metodologia_do_projeto(slug: str, familia: str | None = None,
                           status: Literal["implementado", "parcial", "planejado"] | None = None,
                           db: Session = Depends(get_db)):
    """Catálogo com ``usada_no_projeto`` (resultado gravado ou cache presente) e os parâmetros atuais do projeto."""
    pasta = pasta_do_projeto(slug)
    tipos = set(db.execute(select(Analise.tipo).distinct()).scalars())
    contagens = {}
    for tabela in ("comentario",):
        contagens[tabela] = db.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar() or 0
    cat = svc.carregar()
    analises = svc.marcar_uso_no_projeto(svc.listar(familia, status), pasta, svc_parametros.carregar(pasta), tipos, contagens)
    out = _catalogo_json(analises, cat["familias"])
    out["projeto"] = slug
    out["usadas"] = [a["id"] for a in analises if a["usada_no_projeto"]]
    out["versao_parametros"] = svc_parametros.carregar(pasta).get("versao_parametros")
    return out


@router.get("/api/projetos/{slug}/metodos-texto")
def texto_de_metodos(slug: str, idioma: Literal["pt", "en"] = "pt", estilo: Literal["abnt", "apa"] = "abnt",
                     formato: Literal["json", "md", "docx"] = "json", db: Session = Depends(get_db)):
    """9.4: seção "Métodos" pronta para o artigo (determinística, sem LLM), com citações e referências do catálogo."""
    from app.services.metodologia import texto_metodos

    pasta = pasta_do_projeto(slug)
    m = texto_metodos.montar(db, pasta, idioma, estilo)
    if formato == "md":
        return Response(m["markdown"].encode("utf-8"), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="metodos_{idioma}.md"'})
    if formato == "docx":
        destino = pasta / "saidas" / f"metodos_{idioma}.docx"
        texto_metodos.para_docx(m, destino)
        return Response(destino.read_bytes(),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="metodos_{idioma}.docx"'})
    return m
