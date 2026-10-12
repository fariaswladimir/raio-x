"""Etapa 45 - Vocabulário do corpus (agregado de cache/tokens/*.json; entregável 4.2).

Escopo corpus: junta os tokens de todos os documentos ativos em cache/vocabulario.json
(formato em app/services/vocabulario.py). Frente 5 lê esse arquivo. Roda em poucos segundos
para ~50 documentos. Documentos sem tokens (ex.: linguística com erro) ficam de fora e são
citados na mensagem.
"""
import json
import time

from sqlalchemy import select

from app.models import Documento
from app.services.etapas.linguistica import ler_tokens
from app.services.orquestrador import condicao_ativo, ContextoExecucao, Etapa, registrar_etapa
from app.services.vocabulario import caminho_vocabulario, construir, contar_documento

VERSAO_ETAPA = "1"


def agregar(ctx: ContextoExecucao):
    inicio = time.time()
    docs: dict[int, dict] = {}
    sem_tokens: list[str] = []
    ativos = ctx.db.scalars(
        select(Documento).where(condicao_ativo()).order_by(Documento.arquivo)
    )
    for doc in ativos:
        tokens = ler_tokens(ctx.pasta_projeto, doc.id)
        if tokens is None:
            sem_tokens.append(doc.arquivo)
            continue
        docs[doc.id] = {"arquivo": doc.arquivo, **contar_documento(tokens)}

    voc = construir(docs, ctx.parametros)
    destino = caminho_vocabulario(ctx.pasta_projeto)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(voc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    resumo = {
        "documentos": len(docs),
        "tokens": voc["corpus"]["tokens"],
        "tipos_lema": voc["corpus"]["tipos_lema"],
        "segundos": round(time.time() - inicio, 2),
    }
    if sem_tokens:
        resumo["sem_tokens"] = sem_tokens
    return resumo


registrar_etapa(Etapa(
    nome="vocabulario", ordem=45, escopo="corpus", funcao=agregar, versao=VERSAO_ETAPA,
    parametros_relevantes=["lematizacao", "idioma", "excluir_referencias", "excluir_secoes"],
    depende_de=["linguistica"],
))
