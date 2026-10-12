"""Etapa 68 - instantâneo dos tópicos (15.7 / 7.4).

Escopo corpus. Parâmetros no bloco ``topicos`` de parametros.json (padrão: LDA, K = 8, unidade documento, semente 42,
1000 iterações). Grava **uma** linha da tabela ``analise`` (tipo ``topicos``), substituída a cada execução; se o corpus
for pequeno demais para K (menos de 2·K unidades ou termos) nada é gravado e a linha antiga é removida.

Cache: depende de ``segmentos``, ``ruido`` e ``vocabulario`` e de ``entrada_extra`` = hash dos metadados editáveis
(as agregações por ano e grupo usam esses campos).
"""
import time

from sqlalchemy import delete

from app.models import Analise
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES, _metadados_assinatura
from app.services.etapas.especificidades import _gravar
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias

VERSAO_ETAPA = "1"


def parametros_topicos(parametros: dict) -> dict:
    from app.services.analises import topicos
    p = {**topicos.PADRAO, **((parametros or {}).get("topicos") or {})}
    return {"modelo": str(p["modelo"]), "k": int(p["k"]), "unidade": str(p["unidade"]), "semente": int(p["semente"]),
            "iteracoes": int(p["iteracoes"])}


def calcular_topicos(ctx: ContextoExecucao):
    from app.services.analises import dados, topicos

    inicio = time.time()
    metas = dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)
    ctx.db.execute(delete(Analise).where(Analise.tipo == "topicos"))
    p = parametros_topicos(ctx.parametros)
    try:
        res = topicos.calcular(ctx.pasta_projeto, metas, filtro_palavras_vazias(ctx.parametros), **p)
    except ValueError as exc:
        ctx.db.commit()
        return {"topicos": 0, "mensagem": str(exc)}
    _gravar(ctx, "topicos", {**p, "vazias": "filtrar"}, res["ferramenta_equivalente"], res)
    ctx.db.commit()
    return {"topicos": res["k"], "modelo": res["modelo"], "unidades": res["n_unidades"], **res["coerencia_media"],
            "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="topicos", ordem=68, escopo="corpus", funcao=calcular_topicos, versao=VERSAO_ETAPA,
    parametros_relevantes=[*PARAMETROS_RELEVANTES, "segmento_palavras", "limpeza", "topicos"],
    depende_de=["segmentos", "ruido", "vocabulario"], entrada_extra=_metadados_assinatura,
))
