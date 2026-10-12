"""Etapa 43 - Detector de segmentos de ruído (entregável 3.4; regras em app/services/ruido.py).

Escopo corpus (a regra de cláusulas repetidas compara documentos). Lê ``cache/segmentos/<id>.json``, grava
``cache/ruido/<id>.json`` e o resumo em ``documento.qualidade_json["ruido"]`` (vira pendência do documento). A etapa
sempre marca; quem exclui é a análise, conforme ``limpeza.excluir_ruido``.
"""
import time

from sqlalchemy import select

from app.models import Documento
from app.services import ruido
from app.services.orquestrador import ContextoExecucao, Etapa, condicao_ativo, registrar_etapa
from app.services.segmentacao import ler_segmentos
from app.services.texto import gravar_qualidade, ler_qualidade

VERSAO_ETAPA = "1"


def marcar_ruido(ctx: ContextoExecucao):
    inicio = time.time()
    docs = list(ctx.db.scalars(select(Documento).where(condicao_ativo()).order_by(Documento.arquivo)))
    por_doc, objetos = {}, {}
    for doc in docs:
        sg = ler_segmentos(ctx.pasta_projeto, doc.id)
        if sg is None:
            continue
        por_doc[doc.id] = sg["segmentos"]
        objetos[doc.id] = doc
    achados = ruido.detectar(por_doc, ctx.parametros)
    total_seg = total_tok = 0
    for doc_id, marcados in achados.items():
        resumo = ruido.gravar(ctx.pasta_projeto, doc_id, len(por_doc[doc_id]), marcados)
        total_seg += resumo["segmentos"]
        total_tok += resumo["tokens"]
        doc = objetos[doc_id]
        q = ler_qualidade(doc)
        if resumo["segmentos"]:
            q["ruido"] = resumo
            gravar_qualidade(doc, q)
        elif "ruido" in q:
            del q["ruido"]
            gravar_qualidade(doc, q)
    ctx.db.commit()
    return {"segmentos_ruido": total_seg, "palavras_ruido": total_tok, "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="ruido", ordem=43, escopo="corpus", funcao=marcar_ruido, versao=VERSAO_ETAPA,
    parametros_relevantes=["limpeza", "segmento_palavras", "lematizacao", "idioma", "excluir_referencias", "excluir_secoes"],
    depende_de=["segmentos"],
))
