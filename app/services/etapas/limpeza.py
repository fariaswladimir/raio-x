"""Etapa 30 - Limpeza e estrutura do texto (entregáveis 3.1, 3.2 e 3.3).

Lê cache/md/<id>.md e grava cache/limpo/<id>.json:
- ``blocos``: texto limpo por página e seção, cada um com ``incluir`` (3.2: seções excluídas da contagem);
- ``secoes``: resumo das seções (tipo, título, páginas, palavras, incluída?);
- ``estatisticas``: palavras (total, corpo, referências), detecção de referências e contagens de limpeza.

O resumo das estatísticas também vai para ``documento.qualidade_json["limpeza"]``; os avisos
de pendência ("referências não detectadas", "ocupam > 50%") são calculados a partir dele em
``app/services/texto.py`` (avisos_do_documento). Documentos com_problema não chegam aqui
(o orquestrador os ignora).
"""
import json
import time
from pathlib import Path

from app.models import Documento
from app.services.limpeza_texto import processar
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.texto import gravar_qualidade, ler_qualidade

VERSAO_ETAPA = "2"


def caminho_limpo(pasta_projeto: Path, documento_id: int) -> Path:
    return pasta_projeto / "cache" / "limpo" / f"{documento_id}.json"


def ler_limpo(pasta_projeto: Path, documento_id: int) -> dict | None:
    caminho = caminho_limpo(pasta_projeto, documento_id)
    if not caminho.is_file():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def limpar(ctx: ContextoExecucao, doc: Documento):
    if not doc.caminho_md or not (ctx.pasta_projeto / doc.caminho_md).is_file():
        raise FileNotFoundError("Markdown convertido não encontrado: a conversão precisa rodar antes da limpeza.")
    inicio = time.time()
    md = (ctx.pasta_projeto / doc.caminho_md).read_text(encoding="utf-8")
    dados = processar(md, ctx.parametros)

    destino = caminho_limpo(ctx.pasta_projeto, doc.id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8", newline="\n")

    q = ler_qualidade(doc)
    q["limpeza"] = dados["estatisticas"]
    gravar_qualidade(doc, q)
    ctx.db.commit()
    est = dados["estatisticas"]
    return {
        "referencias": est["metodo_deteccao"],
        "palavras_corpo": est["palavras_corpo"],
        "palavras_total": est["palavras_total"],
        "segundos": round(time.time() - inicio, 2),
    }


registrar_etapa(Etapa(nome="limpeza", ordem=30, escopo="documento", funcao=limpar, versao=VERSAO_ETAPA,
                       parametros_relevantes=["excluir_referencias", "excluir_secoes"], depende_de=["conversao"]))
