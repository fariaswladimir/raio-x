"""Projetos: criação, listagem e parâmetros (entregáveis 1.2 e 1.4)."""
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import projetos_dir
from app.database import get_db, pasta_do_projeto, projeto_existe, sessao_do_projeto
from app.models import Projeto
from app.schemas import ParametrosIn, ParametrosOut, ProjetoCriar, ProjetoOut
from app.services import parametros as svc_parametros

router = APIRouter(prefix="/api/projetos", tags=["projetos"])


def gerar_slug(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")[:80]


def _projeto_out(slug: str) -> ProjetoOut:
    db = sessao_do_projeto(slug)
    try:
        p = db.scalars(select(Projeto).limit(1)).first()
        params = svc_parametros.carregar(pasta_do_projeto(slug))
        return ProjetoOut(
            slug=slug,
            nome=p.nome if p else slug,
            pasta_origem=p.pasta_origem if p else "",
            criado_em=p.criado_em if p else None,
            versao_parametros=params["versao_parametros"],
        )
    finally:
        db.close()


@router.post("", response_model=ProjetoOut, status_code=201)
def criar_projeto(dados: ProjetoCriar):
    pasta = Path(dados.pasta_origem.strip().strip('"'))
    if not pasta.is_dir():
        raise HTTPException(status_code=400, detail=f"A pasta de origem não existe: {pasta}")
    slug = gerar_slug(dados.nome)
    if not slug:
        raise HTTPException(status_code=400, detail="O nome do projeto precisa ter letras ou números.")
    if projeto_existe(slug) or pasta_do_projeto(slug).exists():
        raise HTTPException(status_code=409, detail=f"Já existe um projeto '{slug}'.")

    raiz = pasta_do_projeto(slug)
    for sub in ("cache", "saidas"):
        (raiz / sub).mkdir(parents=True, exist_ok=True)
    db = sessao_do_projeto(slug)  # cria projeto.sqlite e as tabelas
    try:
        db.add(Projeto(nome=dados.nome.strip(), pasta_origem=str(pasta.resolve())))
        db.commit()
    finally:
        db.close()
    svc_parametros.salvar(raiz, svc_parametros.parametros_padrao())  # grava parametros.json por último: marca o projeto como existente
    return _projeto_out(slug)


@router.get("", response_model=list[ProjetoOut])
def listar_projetos():
    base = projetos_dir()
    if not base.is_dir():
        return []
    slugs = sorted(p.parent.name for p in base.glob("*/parametros.json"))
    return [_projeto_out(s) for s in slugs]


@router.get("/{slug}", response_model=ProjetoOut)
def obter_projeto(slug: str):
    if not projeto_existe(slug):
        raise HTTPException(status_code=404, detail=f"Projeto '{slug}' não encontrado.")
    return _projeto_out(slug)


def _parametros_out(slug: str) -> ParametrosOut:
    params = svc_parametros.carregar(pasta_do_projeto(slug))
    return ParametrosOut(**params, hash_parametros=svc_parametros.hash_parametros(params))


@router.get("/{slug}/parametros", response_model=ParametrosOut)
def obter_parametros(slug: str, _db: Session = Depends(get_db)):
    return _parametros_out(slug)


@router.put("/{slug}/parametros", response_model=ParametrosOut)
def atualizar_parametros(slug: str, dados: ParametrosIn, _db: Session = Depends(get_db)):
    svc_parametros.salvar(pasta_do_projeto(slug), dados.model_dump())
    return _parametros_out(slug)
