"""Etapa 63 - Dicionário / codebook: instantâneo da contagem de categorias por grupo (entregável 6.4).

Escopo corpus. Só roda se ``projetos/<slug>/dicionario.yaml`` tem >= 1 categoria com termos; então grava **uma** linha da
tabela ``analise`` (tipo ``dicionario``; lema, ``agrupar=grupo``), substituída a cada execução. Sem categorias com termos a
linha antiga é removida e nada é gravado.

Cache: ``entrada_extra`` = hash do arquivo do dicionário + hash dos metadados editáveis (grupo/ano). Editar o dicionário
pela API (PUT/importação) também apaga o instantâneo na hora, para não deixar números que já não valem.
"""
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import delete

from app.models import Analise
from app.services import dicionario as svc_dic
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES, _metadados_assinatura, _parametros_do_conteudo
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa

VERSAO_ETAPA = "1"


def _pasta_do_banco(db) -> Path:
    return Path(db.get_bind().url.database).parent


def _entrada(db) -> str:
    texto = svc_dic.hash_do_arquivo(_pasta_do_banco(db)) + "|" + _metadados_assinatura(db)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def apagar_instantaneo(db) -> None:
    db.execute(delete(Analise).where(Analise.tipo == "dicionario"))
    db.commit()


def contar_dicionario(ctx: ContextoExecucao):
    from app.services.analises import dados, dicionario
    from app.services.vocabulario import ler_vocabulario

    inicio = time.time()
    ctx.db.execute(delete(Analise).where(Analise.tipo == "dicionario"))
    dic = svc_dic.carregar(ctx.pasta_projeto)
    if not svc_dic.categorias_com_termos(dic):
        ctx.db.commit()
        return {"categorias": 0, "mensagem": "Dicionário sem categorias com termos: preencha os termos em dicionario.yaml."}
    voc = ler_vocabulario(ctx.pasta_projeto)
    if voc is None:
        raise FileNotFoundError("Vocabulário não encontrado: a etapa vocabulario precisa rodar antes do dicionário.")
    metas = dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)
    res = dicionario.calcular(ctx.pasta_projeto, voc, metas, dic, por="lema", agrupar="grupo")
    ctx.db.add(Analise(
        tipo="dicionario",
        parametros_json=json.dumps({**_parametros_do_conteudo(ctx.parametros), "por": "lema", "agrupar": "grupo",
                                    "hash_dicionario": svc_dic.hash_do_arquivo(ctx.pasta_projeto)}, ensure_ascii=False),
        ferramenta_equivalente=dicionario.FERRAMENTA_EQUIVALENTE,
        resultado_json=json.dumps(res, ensure_ascii=False, separators=(",", ":")),
    ))
    ctx.db.commit()
    return {"categorias": len(res["categorias"]), "sem_termos": len(res["sem_termos"]),
            "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="dicionario", ordem=63, escopo="corpus", funcao=contar_dicionario, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario"],
    entrada_extra=_entrada,
))
