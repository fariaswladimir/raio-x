"""Laudo HTML (entregável 9.1): gerar (POST) e servir o último (GET) em projetos/<slug>/saidas/laudo.html."""
import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services.exportar import comum, laudo_html

router = APIRouter(prefix="/api/projetos/{slug}/laudo", tags=["laudo"])


@router.post("")
def gerar_laudo(slug: str, db: Session = Depends(get_db)):
    """Gera o laudo (só comentários aceitos/editados) e devolve o resumo; o arquivo fica em ``saidas/laudo.html``."""
    try:
        return laudo_html.gerar_laudo(db, pasta_do_projeto(slug))
    except comum.SemDados as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/info")
def info_do_laudo(slug: str, db: Session = Depends(get_db)):
    arq = pasta_do_projeto(slug) / "saidas" / "laudo.html"
    if not arq.is_file():
        return {"existe": False}
    e = arq.stat()
    docx = pasta_do_projeto(slug) / "saidas" / "laudo.docx"
    return {"existe": True, "tamanho_bytes": e.st_size, "docx": docx.is_file(),
            "tamanho_docx_bytes": docx.stat().st_size if docx.is_file() else None,
            "gerado_em": datetime.datetime.fromtimestamp(e.st_mtime, datetime.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")}


@router.get("")
def obter_laudo(slug: str, db: Session = Depends(get_db)):
    """Serve o último laudo gerado (404 se ainda não houve geração)."""
    arq = pasta_do_projeto(slug) / "saidas" / "laudo.html"
    if not arq.is_file():
        raise HTTPException(status_code=404, detail="Laudo ainda não gerado: use POST /laudo ou o botão \"Gerar laudo\".")
    return FileResponse(arq, media_type="text/html; charset=utf-8")


@router.get("/docx")
def obter_laudo_docx(slug: str, db: Session = Depends(get_db)):
    """Serve o último laudo .docx (gerado junto com o HTML; 404 se ainda não houve geração)."""
    arq = pasta_do_projeto(slug) / "saidas" / "laudo.docx"
    if not arq.is_file():
        raise HTTPException(status_code=404, detail="Laudo .docx ainda não gerado: use POST /laudo ou o botão \"Gerar laudo\".")
    return FileResponse(arq, filename="laudo.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
