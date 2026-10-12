"""Acesso ao SQLite de cada projeto.

Não há banco global: cada projeto tem projetos/<slug>/projeto.sqlite, com
engine criado sob demanda e mantido em cache.
"""
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import projetos_dir
from app.models import Base

_engines: dict[str, Engine] = {}
_trava = Lock()


def _adicionar_colunas_novas(engine: Engine) -> None:
    """Migração mínima: acrescenta colunas novas em bancos criados por versões anteriores.

    create_all só cria tabelas ausentes; quando o schema estabilizar, trocar por Alembic.
    """
    colunas_novas = {
        "documento": {"qp": "TEXT", "convertido_em": "DATETIME", "caminho_md": "TEXT",
                      "ocr": "BOOLEAN", "excluido": "BOOLEAN DEFAULT 0"},
        "execucao": {"alvo": "TEXT"},
        "evidencia": {"termo": "TEXT", "posicao": "INTEGER"},
        "comentario": {
            "chave": "VARCHAR(300)", "analise_tipo": "VARCHAR(50)", "metricas_json": "TEXT", "forca": "FLOAT",
            "hash_evidencia": "VARCHAR(64)", "texto_original": "TEXT", "nota": "TEXT", "historico_json": "TEXT",
            "origem": "VARCHAR(10) DEFAULT 'regra'",
        },
    }
    inspetor = inspect(engine)
    with engine.begin() as conn:
        for tabela, colunas in colunas_novas.items():
            existentes = {c["name"] for c in inspetor.get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))


def pasta_do_projeto(slug: str) -> Path:
    return projetos_dir() / slug


def projeto_existe(slug: str) -> bool:
    return (pasta_do_projeto(slug) / "parametros.json").is_file()


def engine_do_projeto(slug: str) -> Engine:
    """Engine do projeto (cria o arquivo e as tabelas na primeira vez)."""
    caminho = pasta_do_projeto(slug) / "projeto.sqlite"
    chave = str(caminho)
    with _trava:
        engine = _engines.get(chave)
        if engine is None:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                f"sqlite:///{caminho.as_posix()}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(bind=engine)
            _adicionar_colunas_novas(engine)
            _engines[chave] = engine
        return engine


def sessao_do_projeto(slug: str) -> Session:
    return sessionmaker(autocommit=False, autoflush=False, bind=engine_do_projeto(slug))()


def descartar_engine(slug: str) -> None:
    """Fecha e esquece o engine (necessário antes de apagar a pasta no Windows)."""
    chave = str(pasta_do_projeto(slug) / "projeto.sqlite")
    with _trava:
        engine = _engines.pop(chave, None)
    if engine is not None:
        engine.dispose()


def get_db(slug: str):
    """Dependência FastAPI: sessão do projeto indicado em /api/projetos/{slug}/..."""
    if not projeto_existe(slug):
        raise HTTPException(status_code=404, detail=f"Projeto '{slug}' não encontrado.")
    db = sessao_do_projeto(slug)
    try:
        yield db
    finally:
        db.close()
