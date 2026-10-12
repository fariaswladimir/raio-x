"""6.4 - Dicionário do projeto (``dicionario.yaml``): leitura, gravação e importação do codebook (.xlsx)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services import dicionario as svc
from app.services.etapas.dicionario import apagar_instantaneo

router = APIRouter(prefix="/api/projetos/{slug}/dicionario", tags=["dicionario"])


def _resposta(dic: dict) -> dict:
    marcado = svc.com_marcas(dic)
    return {**marcado, "total": len(dic["categorias"]), "sem_termos": sum(1 for c in marcado["categorias"] if c["sem_termos"])}


def _carregar_ou_422(pasta) -> dict:
    try:
        return svc.carregar(pasta)
    except svc.DicionarioInvalido as exc:
        raise HTTPException(status_code=422, detail={"erros": exc.erros})


@router.get("")
def ler_dicionario(slug: str, formato: str = Query("json", pattern="^(json|yaml)$"), db: Session = Depends(get_db)):
    """Dicionário do projeto em JSON (com ``sem_termos`` por categoria) ou, com ``formato=yaml``, o texto do arquivo."""
    dic = _carregar_ou_422(pasta_do_projeto(slug))
    if formato == "yaml":
        return Response(content=svc.para_yaml(dic), media_type="text/yaml; charset=utf-8")
    return _resposta(dic)


@router.put("")
async def gravar_dicionario(slug: str, request: Request, db: Session = Depends(get_db)):
    """Substitui o dicionário (corpo YAML ou JSON, ``{"categorias": [...]}``). Valida tudo (422 lista os erros) e apaga o
    instantâneo ``dicionario`` (a próxima execução do pipeline recalcula)."""
    corpo = (await request.body()).decode("utf-8-sig", errors="replace")
    try:
        dic = svc.salvar(pasta_do_projeto(slug), svc.ler_texto(corpo))
    except svc.DicionarioInvalido as exc:
        raise HTTPException(status_code=422, detail={"erros": exc.erros})
    apagar_instantaneo(db)
    return _resposta(dic)


@router.post("/importar-codebook")
async def importar_codebook(slug: str, request: Request, aba: str | None = None,
                            modo: str = Query("mesclar", pattern="^(mesclar|substituir)$"), db: Session = Depends(get_db)):
    """Recebe o .xlsx do codebook (corpo bruto), mapeia código, rótulo, tema, regra e palavras-chave (se houver) e grava as
    categorias. Sem coluna de palavras-chave os ``termos`` ficam vazios ("sem termos — preencha"): nada é inventado."""
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    pasta = pasta_do_projeto(slug)
    try:
        dic, relatorio = svc.importar_codebook(conteudo, _carregar_ou_422(pasta), aba=aba, modo=modo)
        svc.salvar(pasta, dic)
    except svc.DicionarioInvalido as exc:
        raise HTTPException(status_code=422, detail={"erros": exc.erros})
    apagar_instantaneo(db)
    return {"relatorio": relatorio, "dicionario": _resposta(dic)}
