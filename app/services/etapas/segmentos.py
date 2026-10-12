"""Etapa 42 - Segmentos de ~40 palavras por documento (entregável 4.4; regras em app/services/segmentacao.py).

Lê cache/tokens/<id>.json e cache/limpo/<id>.json e grava cache/segmentos/<id>.json. Parâmetro: ``segmento_palavras``.
"""
import json
import time

from app.models import Documento
from app.services.etapas.limpeza import ler_limpo
from app.services.etapas.linguistica import ler_tokens
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.segmentacao import caminho_segmentos, segmentar

VERSAO_ETAPA = "1"


def analisar(ctx: ContextoExecucao, doc: Documento):
    tokens, limpo = ler_tokens(ctx.pasta_projeto, doc.id), ler_limpo(ctx.pasta_projeto, doc.id)
    if tokens is None or limpo is None:
        raise FileNotFoundError("Tokens não encontrados: a linguística precisa rodar antes da segmentação.")
    inicio = time.time()
    dados = segmentar(tokens, limpo["blocos"], int(ctx.parametros.get("segmento_palavras") or 40))
    destino = caminho_segmentos(ctx.pasta_projeto, doc.id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    return {"segmentos": len(dados["segmentos"]), "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="segmentos", ordem=42, escopo="documento", funcao=analisar, versao=VERSAO_ETAPA,
    parametros_relevantes=["segmento_palavras", "lematizacao", "idioma", "excluir_referencias", "excluir_secoes"],
    depende_de=["linguistica"],
))
