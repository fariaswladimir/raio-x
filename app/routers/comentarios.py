"""Revisão dos comentários por regra (entregável 8.2): listar, aceitar, editar, rejeitar, anotar, reabrir, em lote.

Todo comentário nasce "sugerido" (princípio 4: comentário automático é só sugestão). Cada ação grava o revisor
(texto livre), a data (``atualizado_em``) e uma linha no histórico do comentário.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import STATUS_COMENTARIO, Comentario, agora
from app.services.analises.dados import rotulo_do_documento
from app.services.regras.catalogo import ANALISES
from app.services.regras.motor import ler_historico, registrar_historico

router = APIRouter(prefix="/api/projetos/{slug}/comentarios", tags=["comentarios"])

MAX_TEXTO = 5000
MAX_NOTA = 5000
Acao = Literal["aceitar", "rejeitar", "editar", "reabrir", "anotar"]


class AcaoIn(BaseModel):
    acao: Acao
    texto: str | None = Field(None, max_length=MAX_TEXTO)  # obrigatório em "editar"
    nota: str | None = Field(None, max_length=MAX_NOTA)  # obrigatória em "anotar" (vazia apaga a nota)
    revisor: str | None = Field(None, max_length=200)
    usar_proposta: bool = False  # em "aceitar" de um comentário "revisar": adota o texto novo gerado pelo motor


class LoteIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    acao: Literal["aceitar", "rejeitar"]
    revisor: str | None = Field(None, max_length=200)
    usar_proposta: bool = False


class EvidenciaOut(BaseModel):
    id: int
    documento_id: int
    documento: str
    arquivo: str
    pagina: int | None
    trecho: str
    termo: list[str]
    posicao: int | None


class ComentarioOut(BaseModel):
    id: int
    chave: str | None
    regra: str
    analise_tipo: str | None
    texto: str
    texto_original: str | None
    status: str
    forca: float | None
    metricas: dict
    origem: str = "regra"  # regra | llm | humano (Frente 14)
    llm: dict | None = None  # provedor, modelo, uso, request_id, prompt_hash (só origem llm)
    verificacao: dict | None = None  # conferência automática de números, citações e trechos (só origem llm)
    nota: str | None
    revisor: str | None
    motivo_revisao: str | None
    evidencias: list[EvidenciaOut]
    criado_em: str
    atualizado_em: str


_ORDEM_ANALISE = case(*[(Comentario.analise_tipo == a, i) for i, a in enumerate(ANALISES)], else_=len(ANALISES))


def _lista(texto: str | None) -> list[str]:
    return [t.strip() for t in (texto or "").split(",") if t.strip()]


def _out(c: Comentario) -> ComentarioOut:
    motivo = None
    if c.status == "revisar":
        motivos = [e.get("motivo") for e in ler_historico(c) if e.get("evento") == "revisar"]
        motivo = motivos[-1] if motivos else None
    try:
        metricas = json.loads(c.metricas_json) if c.metricas_json else {}
    except ValueError:
        metricas = {}
    return ComentarioOut(
        id=c.id, chave=c.chave, regra=c.regra, analise_tipo=c.analise_tipo, texto=c.texto, texto_original=c.texto_original,
        status=c.status, forca=c.forca, metricas=metricas, origem=c.origem or "regra",
        llm=metricas.get("llm") if c.origem == "llm" else None, verificacao=metricas.get("verificacao") if c.origem == "llm" else None, nota=c.nota, revisor=c.revisor, motivo_revisao=motivo,
        evidencias=[
            EvidenciaOut(id=e.id, documento_id=e.documento_id, documento=rotulo_do_documento(e.documento), arquivo=e.documento.arquivo,
                         pagina=e.pagina, trecho=e.trecho, termo=(e.termo or "").split("|") if e.termo else [], posicao=e.posicao)
            for e in sorted(c.evidencias, key=lambda e: e.id)],
        criado_em=c.criado_em.isoformat(), atualizado_em=c.atualizado_em.isoformat())


@router.get("", response_model=list[ComentarioOut])
def listar(
    slug: str,
    status: str | None = Query(None, description="Um ou mais status separados por vírgula"),
    analise: str | None = None,
    regra: str | None = None,
    origem: str | None = Query(None, description="regra, llm ou humano (vírgula = alternativas)"),
    db: Session = Depends(get_db),
):
    """Comentários ordenados por análise e, dentro dela, pela força (maior primeiro)."""
    consulta = select(Comentario)
    if status:
        lista = _lista(status)
        invalidos = [s for s in lista if s not in STATUS_COMENTARIO]
        if invalidos:
            raise HTTPException(status_code=422, detail=f"Status inválido: {', '.join(invalidos)}. Use: {', '.join(STATUS_COMENTARIO)}.")
        consulta = consulta.where(Comentario.status.in_(lista))
    if analise:
        consulta = consulta.where(Comentario.analise_tipo.in_(_lista(analise)))
    if regra:
        consulta = consulta.where(Comentario.regra.in_(_lista(regra)))
    if origem:
        consulta = consulta.where(Comentario.origem.in_(_lista(origem)))
    consulta = consulta.order_by(_ORDEM_ANALISE, Comentario.forca.desc(), Comentario.id)
    return [_out(c) for c in db.scalars(consulta)]


@router.get("/resumo")
def resumo(slug: str, db: Session = Depends(get_db)):
    """Contagem por status (todos os status, mesmo com zero), por regra e por análise."""
    por_status = {s: 0 for s in STATUS_COMENTARIO}
    por_regra: dict[str, int] = {}
    por_analise: dict[str, int] = {}
    total = 0
    for status, regra, analise in db.execute(select(Comentario.status, Comentario.regra, Comentario.analise_tipo)):
        total += 1
        por_status[status] = por_status.get(status, 0) + 1
        por_regra[regra] = por_regra.get(regra, 0) + 1
        por_analise[analise or "outra"] = por_analise.get(analise or "outra", 0) + 1
    return {"total": total, "por_status": por_status, "por_regra": dict(sorted(por_regra.items())), "por_analise": por_analise}


def _aplicar(c: Comentario, dados: AcaoIn) -> None:
    """Aplica uma ação ao comentário (levanta HTTPException 409/422 se não for permitida)."""
    acao, antes = dados.acao, c.status
    revisor = (dados.revisor or "").strip() or None
    if c.status == "obsoleto" and acao not in ("anotar", "rejeitar"):
        raise HTTPException(status_code=409, detail="Comentário obsoleto (a regra já não o gera): só é possível anotar ou rejeitar.")
    detalhe: dict = {}
    if acao == "aceitar":
        if dados.usar_proposta and c.texto_original:
            detalhe["texto_anterior"] = c.texto
            c.texto = c.texto_original
        c.status = "aceito"
    elif acao == "rejeitar":
        c.status = "rejeitado"
    elif acao == "editar":
        texto = (dados.texto or "").strip()
        if not texto:
            raise HTTPException(status_code=422, detail="Informe o texto editado.")
        if texto != c.texto:
            detalhe["texto_anterior"] = c.texto
        c.texto = texto
        c.status = "aceito" if texto == c.texto_original else "editado"
    elif acao == "reabrir":
        if c.status == "sugerido":
            raise HTTPException(status_code=409, detail="O comentário já está como sugerido.")
        if c.texto != c.texto_original and c.texto_original:
            detalhe["texto_anterior"] = c.texto
            c.texto = c.texto_original
        c.status = "sugerido"
    elif acao == "anotar":
        if dados.nota is None:
            raise HTTPException(status_code=422, detail="Informe a nota (texto vazio apaga).")
        detalhe["nota_anterior"] = c.nota
        c.nota = dados.nota.strip() or None
    if revisor:
        c.revisor = revisor
    c.atualizado_em = agora()
    registrar_historico(c, acao, revisor=c.revisor, status_anterior=antes, status_novo=c.status, **detalhe)


def _buscar(db: Session, comentario_id: int) -> Comentario:
    c = db.get(Comentario, comentario_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Comentário {comentario_id} não encontrado.")
    return c


@router.patch("/{comentario_id}", response_model=ComentarioOut)
def agir(slug: str, comentario_id: int, dados: AcaoIn, db: Session = Depends(get_db)):
    c = _buscar(db, comentario_id)
    _aplicar(c, dados)
    db.commit()
    db.refresh(c)
    return _out(c)


@router.post("/checagem")
def checar_evidencias(slug: str, db: Session = Depends(get_db)):
    """8.3: confere evidências (trecho existe no texto atual, na página citada) e números; quem falha vai para ``revisar``."""
    from app.database import pasta_do_projeto
    from app.services import parametros as svc_parametros
    from app.services.regras import checagem

    pasta = pasta_do_projeto(slug)
    return checagem.checar_todos(db, pasta, svc_parametros.carregar(pasta))


@router.post("/lote")
def agir_em_lote(slug: str, dados: LoteIn, db: Session = Depends(get_db)):
    """Aceita ou rejeita vários de uma vez. Os que não aceitam a ação (ex.: obsoletos) voltam em ``ignorados``."""
    atualizados: list[int] = []
    ignorados: list[dict] = []
    for cid in dict.fromkeys(dados.ids):
        c = db.get(Comentario, cid)
        if c is None:
            ignorados.append({"id": cid, "motivo": "não encontrado"})
            continue
        try:
            _aplicar(c, AcaoIn(acao=dados.acao, revisor=dados.revisor, usar_proposta=dados.usar_proposta))
            atualizados.append(cid)
        except HTTPException as exc:
            ignorados.append({"id": cid, "motivo": exc.detail})
    db.commit()
    return {"acao": dados.acao, "atualizados": len(atualizados), "ids": atualizados, "ignorados": ignorados}
