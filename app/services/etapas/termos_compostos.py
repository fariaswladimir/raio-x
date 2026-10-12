"""Etapa 46 - Termos compostos do corpus (entregável 4.3; regras em app/services/termos_compostos.py).

Escopo corpus, depois do vocabulário: detecta os candidatos nos lemas dos documentos ativos, junta a ``lista`` do
usuário, tira os ``bloqueados`` e marca os trechos em cada documento. Grava ``cache/termos_compostos.json`` (lista
efetiva com freq, docs, escore e origem + contagens por documento) e ``cache/termos/<id>.json`` (ocorrências).
Mudar ``termos_compostos`` (inclusive aceitar/bloquear um termo) invalida só esta etapa.
"""
import json
import time
from collections import Counter

from sqlalchemy import select

from app.models import Documento
from app.services import parametros as svc_parametros
from app.services import spacy_nlp
from app.services import termos_compostos as tc
from app.services.etapas.limpeza import ler_limpo
from app.services.etapas.linguistica import ler_tokens
from app.services.orquestrador import condicao_ativo, ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias

VERSAO_ETAPA = "4"
PARAMETROS_RELEVANTES = ["termos_compostos", "palavras_vazias", "lematizacao", "idioma", "excluir_referencias",
                         "excluir_secoes"]


def hash_relevante(parametros: dict) -> str:
    return svc_parametros.hash_parametros(parametros, PARAMETROS_RELEVANTES)


def _escrever(caminho, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")


def processar(ctx: ContextoExecucao):
    inicio = time.time()
    cfg = tc.configuracao(ctx.parametros)
    filtro = filtro_palavras_vazias(ctx.parametros)
    docs: dict[int, dict] = {}
    ativos = ctx.db.scalars(select(Documento).where(condicao_ativo()).order_by(Documento.arquivo))
    for doc in ativos:
        tokens, limpo = ler_tokens(ctx.pasta_projeto, doc.id), ler_limpo(ctx.pasta_projeto, doc.id)
        if tokens is not None and limpo is not None:
            docs[doc.id] = {"tokens": tokens, "blocos": limpo["blocos"]}
            if cfg["classes"]:  # filtro por classe gramatical (4.5): POS do arquivo lateral do spaCy, se houver
                docs[doc.id]["pos"] = spacy_nlp.classes_do_documento(spacy_nlp.sidecar_valido(ctx.pasta_projeto, doc.id, tokens, tokens.get("idioma")))

    ativa = bool(cfg["ativa"])
    automaticos = tc.detectar(list(docs.values()), filtro, cfg) if ativa else []
    extras = tc.contar_lista(list(docs.values()), cfg["lista"]) if ativa and cfg["lista"] else {}
    itens = tc.montar_lista(automaticos, extras, cfg) if ativa else []
    termos = {c["termo"] for c in itens}

    por_documento: dict[str, dict] = {}
    aplicados: dict[str, int] = {}
    formas: dict[str, Counter] = {}
    for id_, d in docs.items():
        ocorrencias = tc.marcar(d["tokens"], d["blocos"], termos)
        _escrever(tc.caminho_termos_doc(ctx.pasta_projeto, id_), {"formato": tc.FORMATO, "ocorrencias": ocorrencias})
        por_documento[str(id_)] = tc.contagens_do_documento(d["tokens"], ocorrencias)
        for _i, _n, t in ocorrencias:
            aplicados[t] = aplicados.get(t, 0) + 1
        for t, cont in tc.formas_do_termo(d["tokens"], ocorrencias).items():
            formas.setdefault(t, Counter()).update(cont)
    for c in itens:
        c["aplicados"] = aplicados.get(c["termo"], 0)
        c["exibicao"] = tc.melhor_exibicao(formas.get(c["termo"]), c["termo"])  # só para mostrar; a chave é o lema

    _escrever(tc.caminho_termos_corpus(ctx.pasta_projeto), {
        "formato": tc.FORMATO, "hash": hash_relevante(ctx.parametros), "configuracao": cfg, "ativa": ativa,
        "itens": itens, "documentos": por_documento,
    })
    return {"documentos": len(docs), "termos": len(itens), "automaticos": len(automaticos),
            "da_lista": sum(1 for c in itens if c["origem"] == "lista"), "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="termos_compostos", ordem=46, escopo="corpus", funcao=processar, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario", "spacy"],
))
