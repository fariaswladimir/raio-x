"""Etapa 62 - Similaridade entre documentos: instantâneo com as configurações padrão (entregável 6.3).

Escopo corpus. Calcula ``similaridade.calcular`` (lema, palavras vazias filtradas, ligação média, k automático, min_df 2,
max_df 0,9, tf sublinear) e grava **uma** linha da tabela ``analise`` (tipo ``similaridade``), substituída a cada execução.
Com menos de 2 documentos com texto (ou vocabulário vazio) nada é gravado e a linha antiga é removida.

Cache: depende de ``vocabulario`` e dos metadados editáveis (``entrada_extra``); os parâmetros relevantes são os do conteúdo
(lematização, idioma, seções excluídas) e as palavras vazias. A API consulta o mesmo cálculo na hora, com outras opções.
"""
import json
import time

from sqlalchemy import delete

from app.models import Analise
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES, _metadados_assinatura, _parametros_do_conteudo
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias

VERSAO_ETAPA = "1"
PADRAO = {"por": "lema", "metodo": "ward", "k": None, "min_df": 2, "max_df": 0.9, "sublinear": True}


def calcular_similaridade(ctx: ContextoExecucao):
    from app.services.analises import dados, similaridade
    from app.services.vocabulario import ler_vocabulario

    inicio = time.time()
    voc = ler_vocabulario(ctx.pasta_projeto)
    if voc is None:
        raise FileNotFoundError("Vocabulário não encontrado: a etapa vocabulario precisa rodar antes da similaridade.")
    metas = dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)
    ctx.db.execute(delete(Analise).where(Analise.tipo == "similaridade"))
    try:
        res = similaridade.calcular(voc, metas, filtro_palavras_vazias(ctx.parametros), **PADRAO)
    except ValueError as exc:  # poucos documentos ou vocabulário vazio: não é erro do pipeline
        ctx.db.commit()
        return {"documentos": 0, "mensagem": str(exc)}
    ctx.db.add(Analise(
        tipo="similaridade",
        parametros_json=json.dumps({**_parametros_do_conteudo(ctx.parametros), **PADRAO}, ensure_ascii=False),
        ferramenta_equivalente=similaridade.FERRAMENTA_EQUIVALENTE,
        resultado_json=json.dumps(res, ensure_ascii=False, separators=(",", ":")),
    ))
    ctx.db.commit()
    return {"documentos": res["n_documentos"], "termos": res["n_termos"], "k": res["k"],
            "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="similaridade", ordem=62, escopo="corpus", funcao=calcular_similaridade, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario"],
    entrada_extra=_metadados_assinatura,
))
