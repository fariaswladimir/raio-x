"""Etapa 1 - Varredura da pasta de origem (entregáveis 2.1 e 2.2).

Lê a pasta recursivamente, calcula o sha256 de cada arquivo suportado e compara
com a tabela ``documento``. SOMENTE LEITURA: nada é escrito na pasta de origem.

Metadados (id, ano, autor) só são preenchidos para documentos NOVOS: edições manuais
(PATCH) e valores do documentos.csv sobrevivem a novas varreduras. Documento
``com_problema`` volta a ser processado quando o arquivo muda (hash diferente -> "alterado").
"""
import datetime
import hashlib
import re
from pathlib import Path

from sqlalchemy import select

from app.config import EXTENSOES_SUPORTADAS
from app.models import Documento
from app.services.texto import ler_qualidade
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa

TAMANHO_BLOCO = 1024 * 1024


def calcular_sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while bloco := f.read(TAMANHO_BLOCO):
            h.update(bloco)
    return h.hexdigest()


def parse_nome(nome_arquivo: str) -> dict:
    """Metadados pelo nome do arquivo, ex.: '001_2026_Kim_Hyunso_Titulo.md'.

    Mesma regra do protótipo voyant-local (parseName): id numérico opcional,
    ano (19xx/20xx) opcional, tokens QP1/QP2... ignorados e, em seguida, o
    sobrenome do autor. Sem id nem ano, não há metadados confiáveis.
    """
    base = re.sub(r"\.(pdf|docx|md|txt|markdown)$", "", Path(nome_arquivo).name, flags=re.I)
    partes = base.split("_")
    i = 0
    id_estudo = ano = None
    if re.fullmatch(r"\d{2,4}", partes[0]):
        id_estudo = partes[0]
        i = 1
    if i < len(partes) and re.fullmatch(r"(19|20)\d{2}", partes[i]):
        ano = int(partes[i])
        i += 1
    while i < len(partes) and re.fullmatch(r"QP\d", partes[i], flags=re.I):
        i += 1
    autor = partes[i] if (id_estudo or ano) and i < len(partes) else None
    return {"id_estudo": id_estudo, "ano": ano, "autor": autor}


def listar_arquivos(pasta_origem: Path) -> dict[str, Path]:
    """Arquivos suportados, indexados pelo caminho relativo (com '/')."""
    achados = {}
    for caminho in pasta_origem.rglob("*"):
        if caminho.is_file() and caminho.suffix.lower() in EXTENSOES_SUPORTADAS:
            achados[caminho.relative_to(pasta_origem).as_posix()] = caminho
    return achados


def varrer(ctx: ContextoExecucao) -> dict:
    db = ctx.db
    if not ctx.pasta_origem.is_dir():
        raise FileNotFoundError(f"Pasta de origem não encontrada: {ctx.pasta_origem}")

    existentes = {d.arquivo: d for d in db.scalars(select(Documento))}
    arquivos = listar_arquivos(ctx.pasta_origem)
    contagem = {"novo": 0, "alterado": 0, "sem_mudanca": 0, "removido": 0}

    for rel, caminho in sorted(arquivos.items()):
        info = caminho.stat()
        hash_atual = calcular_sha256(caminho)
        modificado = datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).replace(tzinfo=None)
        doc = existentes.get(rel)
        if doc is None:
            db.add(
                Documento(
                    arquivo=rel,
                    hash_sha256=hash_atual,
                    tamanho=info.st_size,
                    modificado_em=modificado,
                    status="novo",
                    **parse_nome(rel),
                )
            )
            status = "novo"
        else:
            if doc.status == "removido":
                status = "novo"  # o arquivo voltou à pasta
            elif doc.hash_sha256 != hash_atual:
                status = "alterado"
            elif doc.status == "com_problema":
                if ler_qualidade(doc).get("retentar"):
                    # Problema do ambiente (ex.: Docling não instalado), não do arquivo: tenta de novo.
                    status = "alterado"
                else:
                    status = "com_problema"  # continua pendente até o arquivo mudar
            else:
                status = "sem_mudanca"
            doc.hash_sha256 = hash_atual
            doc.tamanho = info.st_size
            doc.modificado_em = modificado
            doc.status = status
        if status in contagem:
            contagem[status] += 1

    for rel, doc in existentes.items():
        if rel not in arquivos and doc.status != "removido":
            doc.status = "removido"
            contagem["removido"] += 1

    db.commit()
    contagem["total_na_pasta"] = len(arquivos)
    return contagem


# Varredura sempre olha a pasta de novo (cacheavel=False): é ela que decide o que mudou.
registrar_etapa(Etapa(nome="varredura", ordem=10, escopo="corpus", funcao=varrer, versao="1", cacheavel=False))
