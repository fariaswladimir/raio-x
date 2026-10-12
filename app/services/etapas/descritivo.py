"""Etapa 50 - Raio-x descritivo: instantâneos do resumo e das frequências (entregáveis 5.1 e 5.2).

Escopo corpus. A partir de ``cache/vocabulario.json`` e ``cache/tokens/*.json`` calcula

- ``resumo`` (corpus + por documento: tokens, tipos, densidade, MATTR, termos distintivos TF-IDF) e
- ``frequencias`` (top 500 por lema, escopo corpus, palavras vazias filtradas),

e grava cada um como linha da tabela ``analise`` (tipo, parâmetros, ferramenta equivalente, resultado).
Na reexecução, as linhas anteriores do mesmo tipo são substituídas. A API consulta os mesmos cálculos
na hora (a concordância e o filtro/ordem das tabelas não são instantâneo); o instantâneo serve ao laudo
(Frentes 8 e 9), que precisa de números fixos por execução.

Cache: só os parâmetros que mudam o resultado (lematização, idioma, exclusão de seções, palavras
vazias); mudar ``kwic_janela`` não reexecuta. Depende de ``vocabulario`` (a chave dele entra na desta) e
dos metadados editáveis (ano, grupo, id, autor), via ``entrada_extra``.
"""
import hashlib
import json
import time

from sqlalchemy import delete, select

from app.models import Analise, Documento
from app.services.orquestrador import condicao_ativo, ContextoExecucao, Etapa, registrar_etapa
from app.services.palavras_vazias import filtro_palavras_vazias

VERSAO_ETAPA = "1"
TOP_FREQUENCIAS = 500
PARAMETROS_RELEVANTES = ["lematizacao", "idioma", "excluir_referencias", "excluir_secoes", "palavras_vazias"]

FERRAMENTAS = {
    "resumo": "Voyant Summary / IRaMuTeQ estatísticas",
    "frequencias": "Voyant Terms/Cirrus, AntConc Word list",
}


def _metadados_assinatura(db) -> str:
    """Hash dos metadados editáveis dos documentos ativos (entra na chave de cache da etapa)."""
    from app.services.analises.dados import meta_do_documento

    ativos = db.scalars(select(Documento).where(condicao_ativo()).order_by(Documento.arquivo))
    texto = repr([(m["id"], m["rotulo"], m["ano"], m["grupo"]) for m in map(meta_do_documento, ativos)])
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _parametros_do_conteudo(parametros: dict) -> dict:
    return {k: parametros.get(k) for k in PARAMETROS_RELEVANTES}


def descrever(ctx: ContextoExecucao):
    from app.services.analises import dados, frequencias, resumo
    from app.services.vocabulario import ler_vocabulario

    inicio = time.time()
    voc = ler_vocabulario(ctx.pasta_projeto)
    if voc is None:
        raise FileNotFoundError("Vocabulário não encontrado: a etapa vocabulario precisa rodar antes do descritivo.")
    metas = dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)
    filtro = filtro_palavras_vazias(ctx.parametros)

    res = resumo.calcular(ctx.pasta_projeto, metas, voc, filtro)
    freq = frequencias.listar(voc, metas, filtro, por="lema", filtrar=True, limite=TOP_FREQUENCIAS)
    freq = {**freq, "escopo": "corpus"}

    base = _parametros_do_conteudo(ctx.parametros)
    ctx.db.execute(delete(Analise).where(Analise.tipo.in_(tuple(FERRAMENTAS))))
    for tipo, resultado, extra in (
        ("resumo", res, {"mattr_janela": resumo.JANELA_MATTR}),
        ("frequencias", freq, {"por": "lema", "escopo": "corpus", "vazias": "filtrar", "limite": TOP_FREQUENCIAS}),
    ):
        ctx.db.add(Analise(
            tipo=tipo,
            parametros_json=json.dumps({**base, **extra}, ensure_ascii=False),
            ferramenta_equivalente=FERRAMENTAS[tipo],
            resultado_json=json.dumps(resultado, ensure_ascii=False, separators=(",", ":")),
        ))
    ctx.db.commit()
    return {
        "documentos": res["corpus"]["n_documentos"],
        "tokens": res["corpus"]["tokens"],
        "mattr_media": res["corpus"]["mattr_media"],
        "termos_frequentes": len(freq["itens"]),
        "segundos": round(time.time() - inicio, 2),
    }


registrar_etapa(Etapa(
    nome="descritivo", ordem=50, escopo="corpus", funcao=descrever, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario"],
    entrada_extra=_metadados_assinatura,
))
