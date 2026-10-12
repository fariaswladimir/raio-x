"""Etapa 47 - Duplicatas próximas por texto (extensão do entregável 2.5).

Escopo corpus. Reaproveita ``analises.similaridade`` (matriz de contagens por lema, TF-IDF sublinear, cosseno) sobre os
documentos ativos e marca, em ``qualidade_json.similar_texto`` = ``{"arquivo", "similaridade"}``, o documento que vem
**depois** (ordem alfabética do caminho) quando o cosseno com um anterior é >= ``LIMIAR_COSSENO`` (0,95); se houver
vários anteriores, vale o mais parecido. Aviso na interface: "provável duplicata de <arquivo> (similaridade 0,99)".

Diferenças para a similaridade da 6.3: ``min_df`` = 1 e ``max_df`` = 1 (nenhum termo é descartado: com ``min_df`` = 2 dois
documentos que só compartilham meia dúzia de termos teriam cosseno 1 porque o resto do vocabulário sumiria; e com poucos
documentos o teto de 0,9 apagaria justamente os termos compartilhados), e nada é agrupado nem desenhado: só a matriz de cosseno. O documento NÃO é
excluído: o usuário decide (PATCH ``excluido`` / ``com_problema``). Duplicatas idênticas em bytes (``duplicado_de``) já têm
aviso próprio e ficam fora. O título idêntico é checado em ``qualidade_duplicados`` (26), que não precisa do vocabulário.

Cache: depende do vocabulário (que depende de conversão, qualidade e limpeza dos documentos); a lista de documentos ativos
entra na chave do corpus, então excluir/reincluir recalcula.
"""
import time

import numpy as np
from sqlalchemy import select

from app.models import Documento
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias
from app.services.texto import gravar_qualidade, ler_qualidade

LIMIAR_COSSENO = 0.95
VERSAO_ETAPA = "1"


def detectar_pares(voc: dict, metas: list[dict], filtro, limiar: float = LIMIAR_COSSENO) -> dict[int, tuple[int, float]]:
    """{id do documento posterior: (id do anterior mais parecido, cosseno)} para os pares com cosseno >= limiar.

    ``metas`` já vem na ordem do corpus (arquivo); o "posterior" é o de índice maior."""
    from app.services.analises import similaridade

    try:
        mat, docs, _termos, _excl = similaridade.matriz_contagens(voc, metas, filtro, "lema", min_df=1, max_df=1.0)
    except ValueError:  # sem termos compartilhados: nada a comparar
        return {}
    if len(docs) < 2:
        return {}
    sim = similaridade.cosseno(similaridade.tfidf(mat, True))
    achados: dict[int, tuple[int, float]] = {}
    for j in range(1, len(docs)):
        i = int(np.argmax(sim[j, :j]))
        if sim[j, i] >= limiar - 1e-9:
            achados[docs[j]["id"]] = (docs[i]["id"], float(sim[j, i]))
    return achados


def marcar_duplicatas_proximas(ctx: ContextoExecucao):
    from app.services.analises import dados
    from app.services.vocabulario import ler_vocabulario

    inicio = time.time()
    voc = ler_vocabulario(ctx.pasta_projeto)
    if voc is None:
        raise FileNotFoundError("Vocabulário não encontrado: a etapa vocabulario precisa rodar antes das duplicatas próximas.")
    metas = [m for m in dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)]
    achados = detectar_pares(voc, metas, filtro_palavras_vazias(ctx.parametros))
    por_id = {m["id"]: m["arquivo"] for m in metas}
    marcados = 0
    for doc in ctx.db.scalars(select(Documento).where(Documento.status != "removido")):
        q = ler_qualidade(doc)
        achado = achados.get(doc.id) if not q.get("duplicado_de") else None
        if achado:
            novo = {"arquivo": por_id[achado[0]], "similaridade": round(achado[1], 4)}
            marcados += 1
            if q.get("similar_texto") != novo:
                q["similar_texto"] = novo
                gravar_qualidade(doc, q)
        elif "similar_texto" in q:
            del q["similar_texto"]
            gravar_qualidade(doc, q)
    ctx.db.commit()
    return {"provaveis_duplicatas": marcados, "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="duplicatas_proximas", ordem=47, escopo="corpus", funcao=marcar_duplicatas_proximas, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES,
    depende_de=["vocabulario"],
))
