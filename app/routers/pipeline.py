"""Pipeline: executar etapas e consultar execuções e documentos."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.models import Documento, Execucao
from app.routers.documentos import documento_out
from app.schemas import DocumentoOut, ExecucaoOut, ResumoExecucao
from app.services import execucao_bg, orquestrador

router = APIRouter(prefix="/api/projetos/{slug}", tags=["pipeline"])


@router.post("/executar", response_model=None)
def executar(slug: str, response: Response, sincrono: bool = False, db: Session = Depends(get_db)):
    """Por padrão inicia a execução em segundo plano (202 + run_id; acompanhe em /progresso).

    Com ``?sincrono=1`` espera terminar e devolve o resumo (comportamento original, usado nos testes).
    Só uma execução por projeto de cada vez: 409 se já houver uma rodando.
    """
    if execucao_bg.esta_rodando(slug):
        raise HTTPException(status_code=409, detail="Já existe uma execução em andamento neste projeto.")
    if sincrono:
        return ResumoExecucao(**orquestrador.executar_pipeline(db, pasta_do_projeto(slug)))
    try:
        iniciada = execucao_bg.iniciar(slug)
    except execucao_bg.ExecucaoEmAndamento:
        raise HTTPException(status_code=409, detail="Já existe uma execução em andamento neste projeto.")
    response.status_code = 202
    return iniciada


@router.get("/progresso")
def progresso(slug: str, _db: Session = Depends(get_db)):
    """Estado da última execução em segundo plano: etapa atual, contagens por etapa e resumo final."""
    return execucao_bg.progresso(slug)


@router.get("/execucoes", response_model=list[ExecucaoOut])
def listar_execucoes(slug: str, limite: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    return list(db.scalars(select(Execucao).order_by(Execucao.id.desc()).limit(limite)))


@router.get("/documentos", response_model=list[DocumentoOut])
def listar_documentos(slug: str, status: str | None = None, db: Session = Depends(get_db)):
    consulta = select(Documento).order_by(Documento.arquivo)
    if status:
        consulta = consulta.where(Documento.status == status)
    return [documento_out(d) for d in db.scalars(consulta)]
