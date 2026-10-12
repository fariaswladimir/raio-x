"""Documentos: edição manual de metadados, grupos, documentos.csv e pendências (entregáveis 2.2, 2.3, 2.5)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.models import Documento
from app.schemas import DocumentoEditar, DocumentoOut, GrupoOut, PendenciaOut, SecoesOut
from app.services.etapas import limpeza, metadados_csv
from app.services.limpeza_texto import texto_para_inspecao
from app.services.segmentacao import ler_segmentos
from app.services.texto import avisos_do_documento, ler_qualidade

router = APIRouter(prefix="/api/projetos/{slug}", tags=["documentos"])


def documento_out(doc: Documento) -> DocumentoOut:
    """DocumentoOut com os campos derivados de qualidade_json (páginas, idioma, problemas, avisos)."""
    saida = DocumentoOut.model_validate(doc)
    q = ler_qualidade(doc)
    saida.paginas = q.get("paginas")
    saida.idioma = q.get("idioma")
    saida.problemas = list(q.get("problemas") or [])
    saida.avisos = avisos_do_documento(q, doc.grupo)
    lim = q.get("limpeza") or {}
    saida.referencias = lim.get("metodo_deteccao")
    if lim.get("palavras_total"):
        saida.pct_corpo = round(100 * lim.get("palavras_corpo", 0) / lim["palavras_total"], 1)
    return saida


@router.patch("/documentos/{documento_id}", response_model=DocumentoOut)
def editar_documento(slug: str, documento_id: int, dados: DocumentoEditar, db: Session = Depends(get_db)):
    """Edição manual parcial: só os campos enviados mudam (null ou texto vazio limpa o campo)."""
    doc = db.get(Documento, documento_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não encontrado.")
    for campo in dados.model_fields_set:
        valor = getattr(dados, campo)
        if isinstance(valor, str):
            valor = valor.strip() or None
        if campo == "excluido":
            valor = bool(valor)  # null = reincluir
        setattr(doc, campo, valor)
    if "ocr" in dados.model_fields_set and doc.status == "com_problema":
        # Pedido de nova conversão: o documento volta ao pipeline (a chave de cache já muda com o override de OCR).
        doc.status = "alterado"
    db.commit()
    db.refresh(doc)
    return documento_out(doc)


@router.get("/grupos", response_model=list[GrupoOut])
def listar_grupos(slug: str, db: Session = Depends(get_db)):
    """Contagem de documentos por grupo (documentos removidos não contam)."""
    linhas = db.execute(
        select(Documento.grupo, func.count(Documento.id))
        .where(Documento.status != "removido")
        .group_by(Documento.grupo)
        .order_by(Documento.grupo)
    )
    return [GrupoOut(grupo=g, documentos=n) for g, n in linhas]


@router.post("/documentos-csv")
async def enviar_documentos_csv(slug: str, request: Request, db: Session = Depends(get_db)):
    """Recebe o documentos.csv (corpo bruto, ';', UTF-8 com ou sem BOM), grava no projeto e aplica já."""
    conteudo = await request.body()
    if not conteudo.strip():
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    try:
        linhas = metadados_csv.ler_linhas(metadados_csv.decodificar(conteudo))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    (pasta_do_projeto(slug) / metadados_csv.NOME_ARQUIVO).write_bytes(conteudo)
    return metadados_csv.aplicar_linhas(db, linhas)


@router.get("/pendencias", response_model=list[PendenciaOut])
def listar_pendencias(slug: str, db: Session = Depends(get_db)):
    """Documentos com problemas ou avisos de qualidade."""
    pendencias = []
    for doc in db.scalars(select(Documento).where(Documento.status != "removido").order_by(Documento.arquivo)):
        q = ler_qualidade(doc)
        problemas = list(q.get("problemas") or [])
        avisos = avisos_do_documento(q, doc.grupo)
        if problemas or avisos or doc.status == "com_problema" or doc.excluido:
            texto_ausente = doc.arquivo.lower().endswith(".pdf") and any("escaneado" in p or "sem texto" in p for p in problemas)
            pendencias.append(
                PendenciaOut(id=doc.id, arquivo=doc.arquivo, status=doc.status, problemas=problemas, avisos=avisos,
                             ocr=doc.ocr, excluido=bool(doc.excluido), pode_ocr=texto_ausente)
            )
    return pendencias


def _limpo_ou_404(slug: str, db: Session, documento_id: int) -> tuple[Documento, dict]:
    doc = db.get(Documento, documento_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não encontrado.")
    dados = limpeza.ler_limpo(pasta_do_projeto(slug), documento_id)
    if dados is None:
        raise HTTPException(
            status_code=404,
            detail="Texto limpo não encontrado: execute o pipeline (documentos com problema não passam pela limpeza).",
        )
    return doc, dados


@router.get("/documentos/{documento_id}/secoes", response_model=SecoesOut)
def secoes_do_documento(slug: str, documento_id: int, db: Session = Depends(get_db)):
    """Seções detectadas (3.1) e estatísticas da limpeza do documento."""
    doc, dados = _limpo_ou_404(slug, db, documento_id)
    return SecoesOut(documento_id=doc.id, arquivo=doc.arquivo, secoes=dados["secoes"], estatisticas=dados["estatisticas"])


@router.get("/documentos/{documento_id}/texto", response_class=PlainTextResponse)
def texto_limpo(
    slug: str,
    documento_id: int,
    incluir: str = Query("corpo", pattern="^(corpo|tudo)$"),
    db: Session = Depends(get_db),
):
    """Texto limpo com marcadores de página e de seção, para inspeção. ``incluir=corpo`` omite as seções excluídas."""
    _, dados = _limpo_ou_404(slug, db, documento_id)
    return PlainTextResponse(texto_para_inspecao(dados, incluir), media_type="text/plain; charset=utf-8")


@router.get("/documentos/{documento_id}/segmentos")
def segmentos_do_documento(
    slug: str,
    documento_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Segmentos de ~40 palavras do documento (4.4), paginados: texto, página, seção e intervalo de tokens."""
    doc = db.get(Documento, documento_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não encontrado.")
    seg = ler_segmentos(pasta_do_projeto(slug), documento_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="Segmentos não encontrados: execute o pipeline (documentos com problema não são segmentados).")
    itens = seg["segmentos"]
    return {"documento_id": doc.id, "arquivo": doc.arquivo, "alvo": seg["alvo"], "total": len(itens),
            "offset": offset, "limit": limit, "itens": itens[offset: offset + limit]}
