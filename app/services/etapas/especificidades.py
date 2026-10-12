"""Etapas 64 e 65 - instantâneos das especificidades (6.2) e da AFC (7.3).

Escopo corpus, unidade lema, palavras vazias filtradas, padrões das análises. Cada etapa grava **uma** linha da
tabela ``analise`` (tipo ``especificidades`` / ``afc``), substituída a cada execução; sem partição possível nada é
gravado e a linha antiga é removida.

- ``especificidades``: por grupo se houver >= 2 grupos definidos; senão por ano (>= 2 anos).
- ``afc``: por grupo se houver >= 3 grupos definidos; senão por ano (>= 3 anos); senão por documento (>= 3).

Cache: dependem de ``vocabulario`` e de ``entrada_extra`` = hash dos metadados editáveis (grupo e ano), então editar
o grupo ou o ano de um documento invalida as duas. A API consulta os mesmos cálculos na hora, com outras opções.
"""
import json
import time

from sqlalchemy import delete

from app.models import Analise
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES, _metadados_assinatura, _parametros_do_conteudo
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias

VERSAO_ETAPA = "1"
PADRAO_ESPECIFICIDADES = {"por": "lema", "min_freq": 5, "limiar": 2.0, "limite": 30}
PADRAO_AFC = {"por": "lema", "n_termos": 100, "selecao": "freq", "eixos": 5, "min_freq": 5}


def _contexto(ctx: ContextoExecucao, etapa: str):
    from app.services.analises import dados
    from app.services.vocabulario import ler_vocabulario

    voc = ler_vocabulario(ctx.pasta_projeto)
    if voc is None:
        raise FileNotFoundError(f"Vocabulário não encontrado: a etapa vocabulario precisa rodar antes de {etapa}.")
    return voc, dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)


def _gravar(ctx, tipo: str, parametros: dict, ferramenta: str, res: dict) -> None:
    ctx.db.add(Analise(
        tipo=tipo, parametros_json=json.dumps({**_parametros_do_conteudo(ctx.parametros), **parametros}, ensure_ascii=False),
        ferramenta_equivalente=ferramenta, resultado_json=json.dumps(res, ensure_ascii=False, separators=(",", ":")),
    ))


def calcular_especificidades(ctx: ContextoExecucao):
    from app.services.analises import especificidades as esp

    inicio = time.time()
    voc, metas = _contexto(ctx, "especificidades")
    ctx.db.execute(delete(Analise).where(Analise.tipo == "especificidades"))
    particao = esp.particao_do_instantaneo(metas, 2)
    if particao is None:
        ctx.db.commit()
        return {"partes": 0, "mensagem": "Menos de 2 grupos e menos de 2 anos: nada a comparar."}
    try:
        res = esp.calcular(voc, metas, filtro_palavras_vazias(ctx.parametros), particao=particao, **PADRAO_ESPECIFICIDADES)
    except ValueError as exc:
        ctx.db.commit()
        return {"partes": 0, "mensagem": str(exc)}
    _gravar(ctx, "especificidades", {**PADRAO_ESPECIFICIDADES, "particao": particao, "vazias": "filtrar"},
            esp.FERRAMENTA_EQUIVALENTE, res)
    ctx.db.commit()
    return {"particao": particao, "partes": len(res["partes"]), "termos": res["termos_testados"],
            "segundos": round(time.time() - inicio, 2)}


def calcular_afc(ctx: ContextoExecucao):
    from app.services.analises import afc

    inicio = time.time()
    voc, metas = _contexto(ctx, "afc")
    ctx.db.execute(delete(Analise).where(Analise.tipo == "afc"))
    particao = afc.particao_do_instantaneo(metas)
    if particao is None:
        ctx.db.commit()
        return {"partes": 0, "mensagem": "Menos de 3 documentos: a AFC não se aplica."}
    try:
        res = afc.calcular(voc, metas, filtro_palavras_vazias(ctx.parametros), particao=particao, **PADRAO_AFC)
    except ValueError as exc:
        ctx.db.commit()
        return {"partes": 0, "mensagem": str(exc)}
    _gravar(ctx, "afc", {**PADRAO_AFC, "particao": particao, "vazias": "filtrar"}, afc.FERRAMENTA_EQUIVALENTE, res)
    ctx.db.commit()
    return {"particao": particao, "partes": res["n_colunas"], "termos": res["n_linhas"], "eixos": res["k"],
            "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="especificidades", ordem=64, escopo="corpus", funcao=calcular_especificidades, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario"], entrada_extra=_metadados_assinatura,
))
registrar_etapa(Etapa(
    nome="afc", ordem=65, escopo="corpus", funcao=calcular_afc, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario"], entrada_extra=_metadados_assinatura,
))
