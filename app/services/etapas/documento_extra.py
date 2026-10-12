"""Etapa 69 - Raio-x por documento: legibilidade, palavras-chave e resumo extrativo (entregáveis 15.3, 15.4 e 15.5).

Escopo corpus. Para cada documento com texto limpo calcula (ver ``app/services/analises/documento_extra.py``)

- ``legibilidade``: Flesch EN/PT, Flesch-Kincaid, Gunning Fog, Coleman-Liau e SMOG (com contagens e avisos de confiabilidade);
- ``palavras_chave``: RAKE, YAKE e TextRank (10 por método, com frequência e páginas);
- ``resumos``: TextRank, LexRank e MMR (``documento_extra.resumo_frases`` frases, com página e seção);

e grava **uma** linha da tabela ``analise`` (tipo ``documento_extra``), substituída a cada execução. O agrupamento
(15.9) não tem instantâneo: é barato e a API calcula na hora com as opções escolhidas.

Cache: depende de ``vocabulario`` e ``ruido``; parâmetros relevantes = os do conteúdo (lematização, idioma, seções excluídas,
palavras vazias, ruído, segmentação) e o bloco ``documento_extra``.
"""
import json
import time

from sqlalchemy import delete

from app.models import Analise
from app.services.etapas.descritivo import _metadados_assinatura
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa

VERSAO_ETAPA = "3"
PARAMETROS_RELEVANTES = ["documento_extra", "idioma", "excluir_referencias", "excluir_secoes", "lematizacao", "palavras_vazias",
                         "limpeza", "segmento_palavras"]
FERRAMENTA = "Estatísticas de legibilidade (textstat/Coh-Metrix), YAKE/RAKE/TextRank e resumo extrativo (sumy)"


def calcular_documento_extra(ctx: ContextoExecucao):
    from app.services.analises import dados, documento_extra

    inicio = time.time()
    metas = dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)
    docs, sem_texto = [], 0
    for m in metas:
        r = documento_extra.calcular_documento(ctx.pasta_projeto, m["id"], ctx.parametros)
        if r is None:
            sem_texto += 1
            continue
        docs.append({"rotulo": m["rotulo"], "arquivo": m["arquivo"], **r})
    ctx.db.execute(delete(Analise).where(Analise.tipo == "documento_extra"))
    if docs:
        pe = ctx.parametros.get("documento_extra") or {}
        ctx.db.add(Analise(
            tipo="documento_extra",
            parametros_json=json.dumps({"documento_extra": pe, "excluir_ruido": documento_extra.excluir_ruido(ctx.parametros)},
                                       ensure_ascii=False),
            ferramenta_equivalente=FERRAMENTA,
            resultado_json=json.dumps({"documentos": docs}, ensure_ascii=False, separators=(",", ":")),
        ))
    ctx.db.commit()
    return {"documentos": len(docs), "sem_texto": sem_texto, "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="documento_extra", ordem=69, escopo="corpus", funcao=calcular_documento_extra, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario", "ruido"],
    entrada_extra=_metadados_assinatura,
))
