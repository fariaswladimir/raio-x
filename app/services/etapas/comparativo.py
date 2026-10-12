"""Etapa 60 - Raio-x comparativo: instantâneo da keyness de cada grupo contra o resto (entregável 6.1).

Escopo corpus. Com >= 2 grupos com documentos, calcula as palavras-chave de cada grupo contra todos os demais
documentos (``keyness.calcular``, lema, palavras vazias filtradas, padrões da análise) e grava **uma** linha da
tabela ``analise`` (tipo ``keyness``). Na reexecução a linha anterior é substituída; com menos de 2 grupos nada
é gravado (e a linha antiga é removida, para não deixar um instantâneo que já não vale).

Cache: depende de ``vocabulario`` e de ``entrada_extra`` = hash dos metadados editáveis (grupo e ano entram),
então editar o grupo de um documento invalida a etapa. A API consulta o mesmo cálculo na hora, com A e B livres.
"""
import json
import time

from sqlalchemy import delete

from app.models import Analise
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES, _metadados_assinatura, _parametros_do_conteudo
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias

VERSAO_ETAPA = "1"
LIMITE_INSTANTANEO = 50
MENSAGEM_POUCOS_GRUPOS = "Menos de 2 grupos com documentos: defina grupos na tabela de documentos ou envie documentos.csv."


def comparar(ctx: ContextoExecucao):
    from app.services.analises import dados, keyness
    from app.services.vocabulario import ler_vocabulario

    inicio = time.time()
    voc = ler_vocabulario(ctx.pasta_projeto)
    if voc is None:
        raise FileNotFoundError("Vocabulário não encontrado: a etapa vocabulario precisa rodar antes do comparativo.")
    metas = dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)
    ctx.db.execute(delete(Analise).where(Analise.tipo == "keyness"))
    res = keyness.comparar_grupos(voc, metas, filtro_palavras_vazias(ctx.parametros), limite=LIMITE_INSTANTANEO)
    if res is None:
        ctx.db.commit()
        return {"grupos": 0, "mensagem": MENSAGEM_POUCOS_GRUPOS}
    ctx.db.add(Analise(
        tipo="keyness",
        parametros_json=json.dumps({**_parametros_do_conteudo(ctx.parametros), "por": "lema", "b": keyness.RESTO,
                                    "vazias": "filtrar", "limite": LIMITE_INSTANTANEO}, ensure_ascii=False),
        ferramenta_equivalente=keyness.FERRAMENTA_EQUIVALENTE,
        resultado_json=json.dumps(res, ensure_ascii=False, separators=(",", ":")),
    ))
    ctx.db.commit()
    return {"grupos": len(res["grupos"]), "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="comparativo", ordem=60, escopo="corpus", funcao=comparar, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario"],
    entrada_extra=_metadados_assinatura,
))
