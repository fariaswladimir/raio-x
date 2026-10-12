"""15.10 Sentimento por léxico (exploratório): léxicos importados (config do usuário) e análise do corpus.

Rotas: /api/config/sentimento/lexicos (GET/POST/DELETE) e /api/projetos/{slug}/analises/sentimento(.csv).
Lógica e licenças em services/analises/sentimento.py. O VADER (EN, MIT) vem do pacote ``vaderSentiment``; OpLexicon e
SentiLex-PT não acompanham o Raio-X: o usuário importa o arquivo que baixou.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Literal

from app.database import get_db, pasta_do_projeto
from app.models import Documento
from app.routers.analises import _contexto
from app.services import ruido as svc_ruido
from app.services.analises import sentimento as sent
from app.services.exportar.planilhas import _n, csv_bytes
from app.services.texto import ler_qualidade
from app.services.tokenizacao import idioma_do_documento

router_config = APIRouter(prefix="/api/config/sentimento", tags=["sentimento"])
router = APIRouter(prefix="/api/projetos/{slug}/analises", tags=["sentimento"])


class LexicoIn(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    idioma: Literal["en", "pt", "es"] = "pt"
    fonte: str = Field("", max_length=500)
    conteudo: str | None = Field(None, description="Texto do léxico (lido no navegador)")
    caminho: str | None = Field(None, description="Arquivo do léxico no computador do usuário")


@router_config.get("/lexicos")
def listar_lexicos():
    return {"itens": sent.listar_lexicos(), "vader": sent.vader_disponivel(), "aviso": sent.AVISO,
            "formatos": "termo;polaridade | OpLexicon (termo,classe,polaridade,fonte) | SentiLex-PT (lema.PoS=...;POL:N0=-1)"}


@router_config.post("/lexicos", status_code=201)
def importar_lexico(corpo: LexicoIn):
    try:
        if corpo.conteudo is not None:
            texto = corpo.conteudo
        elif corpo.caminho and Path(corpo.caminho).is_file():
            texto = Path(corpo.caminho).read_text(encoding="utf-8-sig", errors="replace")
        else:
            raise sent.LexicoInvalido("Envie o conteúdo do arquivo (conteudo) ou o caminho de um arquivo existente (caminho).")
        return sent.importar_lexico(corpo.nome, corpo.idioma, texto, corpo.fonte)
    except sent.LexicoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router_config.delete("/lexicos/{lex_id}", status_code=204)
def remover_lexico(lex_id: str):
    try:
        if not sent.remover_lexico(lex_id):
            raise HTTPException(status_code=404, detail="Léxico não encontrado.")
    except sent.LexicoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))


_MEMO: dict = {}


def _calcular(slug: str, db: Session, pt: str | None, en: str | None, es: str | None, extremos: int) -> dict:
    pasta, params, _voc, metas = _contexto(slug, db)
    idiomas = {m["id"]: idioma_do_documento(ler_qualidade(db.get(Documento, m["id"])), params) for m in metas}
    ids = {k: v for k, v in (("pt", pt), ("en", en), ("es", es)) if v}
    excluir = svc_ruido.excluir_ruido(params)
    marcas = tuple((m["id"], (pasta / "cache" / "limpo" / f"{m['id']}.json").stat().st_mtime_ns) for m in metas)
    chave = (str(pasta), marcas, tuple(sorted(idiomas.items())), tuple(sorted(ids.items())), excluir, extremos,
             tuple((l["id"], l["importado_em"]) for l in sent.listar_lexicos()))
    achado = _MEMO.get(chave)
    if achado is None:
        try:
            achado = sent.calcular(pasta, metas, idiomas, ids, excluir_ruido=excluir, extremos=extremos)
        except sent.LexicoInvalido as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if len(_MEMO) >= 8:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[chave] = achado
    return achado


def _params(lexico_pt: str | None = None, lexico_en: str | None = None, lexico_es: str | None = None,
            extremos: int = Query(10, ge=1, le=100)) -> dict:
    return {"pt": lexico_pt, "en": lexico_en, "es": lexico_es, "extremos": extremos}


@router.get("/sentimento")
def sentimento_do_corpus(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    """Polaridade por documento, grupo e ano e frases mais positivas/negativas (com página). Exploratório."""
    r = _calcular(slug, db, **p)
    return {**r, "lexicos": sent.listar_lexicos(), "vader": sent.vader_disponivel()}


@router.get("/sentimento.csv")
def sentimento_csv(slug: str, p: dict = Depends(_params), db: Session = Depends(get_db)):
    r = _calcular(slug, db, **p)
    cab = ["documento_id", "rotulo", "grupo", "ano", "idioma", "metodo", "frases", "escore_medio", "pct_positivo", "pct_neutro",
           "pct_negativo", "cobertura_lexico_pct"]
    linhas = [[d["id"], d["rotulo"], d["grupo"], d["ano"], d["idioma"], d["metodo"], d["frases"], d["media"], d["positivo"],
               d["neutro"], d["negativo"], d["cobertura"]] for d in r["documentos"]]
    return Response(content=csv_bytes(cab, ([_n(v) for v in l] for l in linhas)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="sentimento.csv"'})
