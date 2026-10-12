"""Vocabulário e tokens (entregáveis 4.1 e 4.2)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.models import Documento
from app.schemas import TokenOut, TokensOut, VocabularioOut
from app.services import parametros as svc_parametros
from app.services import vocabulario as svc_vocabulario
from app.services.analises import dados, frequencias
from app.routers.analises import voc_por
from app.services.etapas import linguistica
from app.services.palavras_vazias import filtro_palavras_vazias

router = APIRouter(prefix="/api/projetos/{slug}", tags=["vocabulario"])

MAX_TOKENS_POR_PAGINA = 2000


@router.get("/vocabulario", response_model=VocabularioOut)
def vocabulario(
    slug: str,
    por: str = Query("lema", pattern="^(lema|forma|termo)$"),
    vazias: str = Query("filtrar", pattern="^(filtrar|manter)$"),
    limite: int = Query(200, ge=1, le=5000),
    documento_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Termos por frequência, com o filtro de palavras vazias dos parâmetros ATUAIS (aplicado na consulta).

    Não é preciso reexecutar o pipeline ao mudar ``palavras_vazias``.
    """
    pasta = pasta_do_projeto(slug)
    voc = svc_vocabulario.ler_vocabulario(pasta)
    if voc is None:
        raise HTTPException(status_code=404, detail="Vocabulário não encontrado: execute o pipeline primeiro.")
    if documento_id is not None and str(documento_id) not in voc["documentos"]:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} sem vocabulário (não processado ou com problema).")
    filtro = filtro_palavras_vazias(svc_parametros.carregar(pasta))
    metas = dados.documentos_do_corpus(db, pasta)
    if documento_id is not None:
        metas = dados.filtrar_escopo(metas, "documento", documento_id)
    voc, interno = voc_por(pasta, voc, por)
    r = frequencias.listar(voc, metas, filtro, por=interno, filtrar=(vazias == "filtrar"), limite=limite)
    return {**r, "por": por}


@router.get("/documentos/{documento_id}/tokens", response_model=TokensOut)
def tokens_do_documento(
    slug: str,
    documento_id: int,
    inicio: int = Query(0, ge=0),
    fim: int | None = Query(None, ge=0),
    db: Session = Depends(get_db),
):
    """Tokens do documento no intervalo [inicio, fim) (no máximo 2000 por chamada), para inspeção."""
    doc = db.get(Documento, documento_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não encontrado.")
    dados = linguistica.ler_tokens(pasta_do_projeto(slug), documento_id)
    if dados is None:
        raise HTTPException(status_code=404, detail="Tokens não encontrados: execute o pipeline (documentos com problema não são tokenizados).")
    n = dados["n"]
    if fim is None:
        fim = inicio + 200
    fim = min(fim, n, inicio + MAX_TOKENS_POR_PAGINA)
    secoes = dados["secoes"]
    itens = [
        TokenOut(
            i=i, forma=dados["forma"][i], norm=dados["norm"][i], lema=dados["lema"][i], pagina=dados["pagina"][i],
            secao=secoes[dados["secao"][i]], incluir=bool(dados["incluir"][i]), bloco=dados["bloco"][i],
            offset_inicio=dados["inicio"][i], offset_fim=dados["fim"][i],
        )
        for i in range(min(inicio, n), max(fim, min(inicio, n)))
    ]
    return TokensOut(documento_id=doc.id, arquivo=doc.arquivo, idioma=dados.get("idioma"),
                     lematizacao=dados.get("lematizacao") or {}, n=n, inicio=inicio, fim=fim, tokens=itens)
