"""Etapa 41 - Classes gramaticais e entidades nomeadas com spaCy (entregável 4.5), opcional.

Escopo documento, depois da linguística: grava o arquivo lateral ``cache/spacy/<id>.json`` (POS por token, lema do spaCy e
entidades; formato em ``services/spacy_nlp.py``) **sem alterar** ``cache/tokens``. Sem spaCy ou sem o modelo do idioma
(só ``en`` e ``pt``), a etapa não faz nada e diz o motivo ("não instalado"); o pipeline segue normalmente. O bloco
``spacy.pos_ner`` de parametros.json (padrão ligado) desliga a etapa. Se o arquivo lateral já corresponde aos tokens (por
exemplo, gravado pela linguística com ``lematizacao.metodo = "spacy"``), ele é reaproveitado.
"""
import time

from app.models import Documento
from app.services import spacy_nlp
from app.services.etapas.limpeza import ler_limpo
from app.services.etapas.linguistica import ler_tokens
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa

VERSAO_ETAPA = "1"


def analisar(ctx: ContextoExecucao, doc: Documento):
    if not spacy_nlp.opcoes(ctx.parametros)["pos_ner"]:
        return {"ativo": False, "mensagem": "POS/NER desligados (spacy.pos_ner = false)"}
    tk = ler_tokens(ctx.pasta_projeto, doc.id)
    limpo = ler_limpo(ctx.pasta_projeto, doc.id)
    if tk is None or limpo is None:
        raise FileNotFoundError("Tokens não encontrados: a linguística precisa rodar antes.")
    idioma = tk.get("idioma")
    if not spacy_nlp.spacy_instalado():
        return {"ativo": False, "mensagem": spacy_nlp.MENSAGEM_NAO_INSTALADO}
    if not spacy_nlp.modelo_instalado(idioma):
        return {"ativo": False, "mensagem": f"sem modelo do spaCy para o idioma '{idioma}' (suportados: en, pt)"}
    inicio = time.time()
    ann = spacy_nlp.sidecar_valido(ctx.pasta_projeto, doc.id, tk, idioma)
    reaproveitado = ann is not None
    if ann is None:
        ann = spacy_nlp.anotar(limpo["blocos"], tk, idioma)
        spacy_nlp.gravar_sidecar(ctx.pasta_projeto, doc.id, ann)
    return {"ativo": True, "idioma": idioma, "modelo": ann["modelo"], "tokens": ann["n"], "entidades": len(ann["ents"]),
            "reaproveitado": reaproveitado, "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="spacy", ordem=41, escopo="documento", funcao=analisar, versao=VERSAO_ETAPA,
    parametros_relevantes=["spacy", "lematizacao", "idioma"], depende_de=["linguistica"],
    entrada_doc=lambda _doc: repr([(k, v["instalado"]) for k, v in spacy_nlp.status()["modelos"].items()]),  # instalar depois reprocessa
))
