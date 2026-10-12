"""Etapas 66 e 67 - instantâneos da CHD de Reinert (7.1) e da similitude (7.2 + 15.2).

Escopo corpus, segmentos de texto (4.4), lemas plenos (palavras vazias filtradas). Parâmetros nos blocos
``reinert`` e ``similitude`` de parametros.json (padrões em services/parametros.py). Cada etapa grava **uma** linha da
tabela ``analise`` (tipo ``reinert`` / ``similitude``), substituída a cada execução; se o corpus for pequeno demais
nada é gravado e a linha antiga é removida.

Cache: dependem de ``segmentos`` e ``vocabulario`` e de ``entrada_extra`` = hash dos metadados editáveis (as
variáveis suplementares da CHD usam grupo e ano), então editar o grupo ou o ano de um documento invalida a CHD.
"""
import time

from sqlalchemy import delete

from app.models import Analise
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES, _metadados_assinatura
from app.services.etapas.especificidades import _gravar
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias

VERSAO_ETAPA = "1"


def parametros_reinert(parametros: dict) -> dict:
    from app.services.analises import reinert
    p = {**reinert.PADRAO, **((parametros or {}).get("reinert") or {})}
    return {"classes": int(p["classes"]), "min_freq": int(p["min_freq"]), "dupla": bool(p["dupla"]),
            "tamanhos": [int(t) for t in p["tamanhos"]], "min_classe": int(p.get("min_classe") or 0),
            "max_formas": int(p.get("max_formas") or 0)}


def parametros_similitude(parametros: dict) -> dict:
    from app.services.analises import similitude
    p = {**similitude.PADRAO, **((parametros or {}).get("similitude") or {})}
    return {"n_formas": int(p["n_formas"]), "indice": str(p["indice"]), "arvore": bool(p["arvore"])}


def _contexto(ctx: ContextoExecucao):
    from app.services.analises import dados
    return dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto), filtro_palavras_vazias(ctx.parametros)


def calcular_reinert(ctx: ContextoExecucao):
    from app.services.analises import reinert

    inicio = time.time()
    metas, filtro = _contexto(ctx)
    ctx.db.execute(delete(Analise).where(Analise.tipo == "reinert"))
    p = parametros_reinert(ctx.parametros)
    try:
        res = reinert.calcular(ctx.pasta_projeto, metas, filtro, **p)
    except ValueError as exc:
        ctx.db.commit()
        return {"classes": 0, "mensagem": str(exc)}
    _gravar(ctx, "reinert", {**p, "vazias": "filtrar"}, reinert.FERRAMENTA_EQUIVALENTE, res)
    ctx.db.commit()
    return {"classes": res["k"], "retencao_pct": res["retencao_pct"], "segmentos": res["segmentos_total"],
            "segundos": round(time.time() - inicio, 2)}


def calcular_similitude(ctx: ContextoExecucao):
    from app.services.analises import similitude

    inicio = time.time()
    metas, filtro = _contexto(ctx)
    ctx.db.execute(delete(Analise).where(Analise.tipo == "similitude"))
    p = parametros_similitude(ctx.parametros)
    try:
        res = similitude.calcular(ctx.pasta_projeto, metas, filtro, **p)
    except ValueError as exc:
        ctx.db.commit()
        return {"arestas": 0, "mensagem": str(exc)}
    _gravar(ctx, "similitude", {**p, "vazias": "filtrar"}, res["ferramenta_equivalente"], res)
    ctx.db.commit()
    return {"formas": res["n_formas"], "arestas": res["n_arestas"], "comunidades": len(res["comunidades"]),
            "modularidade": res["modularidade"], "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="reinert", ordem=66, escopo="corpus", funcao=calcular_reinert, versao=VERSAO_ETAPA,
    parametros_relevantes=[*PARAMETROS_RELEVANTES, "segmento_palavras", "limpeza", "reinert"],
    depende_de=["segmentos", "ruido", "vocabulario"], entrada_extra=_metadados_assinatura,
))
registrar_etapa(Etapa(
    nome="similitude", ordem=67, escopo="corpus", funcao=calcular_similitude, versao=VERSAO_ETAPA,
    parametros_relevantes=[*PARAMETROS_RELEVANTES, "segmento_palavras", "limpeza", "similitude"],
    depende_de=["segmentos", "ruido", "vocabulario"],
))
