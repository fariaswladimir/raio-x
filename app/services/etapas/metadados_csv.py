"""Etapa 11 - Metadados vindos do documentos.csv (entregável 2.3).

Arquivo opcional projetos/<slug>/documentos.csv, separado por ';', UTF-8 com ou
sem BOM (cp1252 como alternativa), colunas: arquivo;grupo;id_estudo;qp (qp é opcional).
Os valores do CSV (quando preenchidos) SOBRESCREVEM os extraídos do nome do arquivo
e as edições manuais, a cada execução. Linhas sem arquivo correspondente são
listadas no resultado.
"""
import csv
import io
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Documento
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa

NOME_ARQUIVO = "documentos.csv"
CAMPOS = ("grupo", "id_estudo", "qp")


def decodificar(conteudo: bytes) -> str:
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("cp1252", errors="replace")


def ler_linhas(texto: str) -> list[dict]:
    """Linhas do CSV como dicionários (cabeçalhos em minúsculas, valores sem espaços)."""
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    campos = [(c or "").strip().lower() for c in (leitor.fieldnames or [])]
    if "arquivo" not in campos:
        raise ValueError("O documentos.csv precisa ter a coluna 'arquivo' (separador ';').")
    linhas = []
    for bruta in leitor:
        linha = {(k or "").strip().lower(): (v or "").strip() for k, v in bruta.items() if k is not None}
        if linha.get("arquivo"):
            linhas.append(linha)
    return linhas


def _localizar(docs: dict[str, Documento], arquivo: str) -> Documento | None:
    chave = arquivo.replace("\\", "/").strip("/")
    if chave in docs:
        return docs[chave]
    minusculo = chave.lower()
    achados = [d for rel, d in docs.items() if rel.lower() == minusculo or rel.lower().rsplit("/", 1)[-1] == minusculo]
    return achados[0] if len(achados) == 1 else None


def aplicar_linhas(db: Session, linhas: list[dict]) -> dict:
    docs = {d.arquivo: d for d in db.scalars(select(Documento).where(Documento.status != "removido"))}
    aplicadas = 0
    sem_arquivo = []
    for linha in linhas:
        doc = _localizar(docs, linha["arquivo"])
        if doc is None:
            sem_arquivo.append(linha["arquivo"])
            continue
        for campo in CAMPOS:
            if linha.get(campo):
                setattr(doc, campo, linha[campo])
        aplicadas += 1
    db.commit()
    return {"linhas": len(linhas), "aplicadas": aplicadas, "sem_arquivo": sem_arquivo}


def aplicar_csv(db: Session, pasta_projeto: Path) -> dict | None:
    caminho = pasta_projeto / NOME_ARQUIVO
    if not caminho.is_file():
        return None
    return aplicar_linhas(db, ler_linhas(decodificar(caminho.read_bytes())))


def executar(ctx: ContextoExecucao):
    resultado = aplicar_csv(ctx.db, ctx.pasta_projeto)
    if resultado is None:
        return "sem documentos.csv"
    if resultado["sem_arquivo"]:
        resultado["aviso"] = f"{len(resultado['sem_arquivo'])} linha(s) do CSV sem arquivo correspondente"
    return resultado


# Roda sempre (cacheavel=False): o CSV pode ter mudado e a operação é barata.
registrar_etapa(Etapa(nome="metadados_csv", ordem=11, escopo="corpus", funcao=executar, versao="1", cacheavel=False))
