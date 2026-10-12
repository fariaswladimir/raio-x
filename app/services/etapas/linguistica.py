"""Etapa 40 - Linguística: tokens e lemas por documento (entregável 4.1).

Lê cache/limpo/<id>.json (blocos da Frente 3) e grava cache/tokens/<id>.json com arrays
paralelos (formato documentado em app/services/tokenizacao.py). O idioma vem de
``qualidade_json.idioma`` (fallback: primeiro de ``idioma`` nos parâmetros).

Parâmetros relevantes: ``lematizacao`` (ativa, metodo, excecoes) e ``idioma``. A mudança de
seções excluídas chega aqui pela dependência da etapa ``limpeza`` (o ``incluir`` de cada token
vem do bloco). Palavras vazias NÃO entram: são aplicadas na consulta (palavras_vazias.py).
"""
import json
import time
from pathlib import Path

from app.models import Documento
from app.services.etapas.limpeza import ler_limpo
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.texto import ler_qualidade
from app.services.tokenizacao import Lematizador, idioma_do_documento, tokenizar_blocos

VERSAO_ETAPA = "1"
FORMATO = 1


def caminho_tokens(pasta_projeto: Path, documento_id: int) -> Path:
    return pasta_projeto / "cache" / "tokens" / f"{documento_id}.json"


def ler_tokens(pasta_projeto: Path, documento_id: int) -> dict | None:
    caminho = caminho_tokens(pasta_projeto, documento_id)
    if not caminho.is_file():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def analisar(ctx: ContextoExecucao, doc: Documento):
    limpo = ler_limpo(ctx.pasta_projeto, doc.id)
    if limpo is None:
        raise FileNotFoundError("Texto limpo não encontrado: a limpeza precisa rodar antes da linguística.")
    inicio = time.time()
    lem = ctx.parametros.get("lematizacao") or {}
    idioma = idioma_do_documento(ler_qualidade(doc), ctx.parametros)
    lematizador = Lematizador(idioma, ativa=bool(lem.get("ativa", True)), excecoes=lem.get("excecoes"))
    dados = tokenizar_blocos(limpo["blocos"], lematizador)
    info_lem = {"ativa": lematizador.ativa, "metodo": lem.get("metodo", "simplemma")}
    if str(info_lem["metodo"]).lower() == "spacy" and lematizador.ativa:  # 4.5: opcional (services/spacy_nlp.py)
        from app.services import spacy_nlp
        info_lem.update(spacy_nlp.lematizar_com_spacy(ctx.pasta_projeto, doc.id, limpo["blocos"], dados, idioma, lematizador))
    dados = {
        "formato": FORMATO,
        "idioma": idioma,
        "lematizacao": info_lem,
        **dados,
    }

    destino = caminho_tokens(ctx.pasta_projeto, doc.id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    return {"idioma": idioma, "tokens": dados["n"], "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="linguistica", ordem=40, escopo="documento", funcao=analisar, versao=VERSAO_ETAPA,
    parametros_relevantes=["lematizacao", "idioma"], depende_de=["limpeza", "qualidade"],
))
