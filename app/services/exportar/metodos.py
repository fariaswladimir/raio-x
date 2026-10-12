"""Texto de Métodos por análise para o laudo.

As referências vêm do catálogo único da tela Metodologia (app/services/metodologia/catalogo.yaml):
cada entrada aponta, em ``refs``, os ids das análises do catálogo cujas referências cita.
"""

from app.services import metodologia


def referencias(ids_catalogo: list[str]) -> list[dict]:
    """Referências das análises do catálogo único (app/services/metodologia/catalogo.yaml), sem duplicatas."""
    return metodologia.referencias_de(ids_catalogo)


# Ordem de exibição no laudo.
ORDEM = ("resumo", "frequencias", "tendencias", "kwic", "keyness", "colocacoes")

METODOS: dict[str, dict] = {
    "resumo": {
        "titulo": "Resumo do corpus e diversidade lexical",
        "mede": "O tamanho do corpus (documentos, palavras do corpo do texto, tipos) e a diversidade lexical de cada documento.",
        "metrica": "Contagens; densidade vocabular (tipos/palavras); MATTR com janela de 500 palavras; termos distintivos por TF-IDF (lema).",
        "equivale": "Voyant Summary; estatísticas do IRaMuTeQ (o MATTR não tem equivalente direto nessas ferramentas).",
        "nao_igual": "TTR simples do Voyant (depende do tamanho do texto); os termos distintivos por TF-IDF não são keyness.",
        "refs": ["diversidade_lexical", "tfidf_termos_distintivos"],
    },
    "frequencias": {
        "titulo": "Frequências",
        "mede": "Quantas vezes cada lema aparece no corpo do texto e em quantos documentos.",
        "metrica": "Contagem e frequência por 10 mil palavras, por lema, sem palavras vazias.",
        "equivale": "Voyant Terms/Cirrus, IRaMuTeQ, AntConc Word list.",
        "nao_igual": "Voyant sem lematização (os números diferem).",
        "refs": ["frequencias"],
    },
    "tendencias": {
        "titulo": "Tendências no tempo",
        "mede": "Como a frequência relativa de um termo muda entre os anos dos documentos.",
        "metrica": "Frequência por 10 mil palavras de cada ano (mesma contagem de lemas das Frequências, agrupada por ano).",
        "equivale": "Voyant Terms/Cirrus e AntConc Word list, filtrados por ano.",
        "nao_igual": "Voyant sem lematização (os números diferem).",
        "refs": ["frequencias"],
    },
    "kwic": {
        "titulo": "Concordância (KWIC)",
        "mede": "O contexto de cada ocorrência de um termo, com a página de origem.",
        "metrica": "Janela de N palavras de cada lado do termo e página do documento.",
        "equivale": "Todas as ferramentas de concordância (AntConc, Voyant Contexts, IRaMuTeQ).",
        "nao_igual": "—",
        "refs": ["kwic"],
    },
    "keyness": {
        "titulo": "Palavras-chave entre grupos (keyness)",
        "mede": "Quais palavras são mais (ou menos) frequentes em um grupo de documentos do que no restante do corpus.",
        "metrica": "Log-likelihood (G² de 2 células, com p pelo qui-quadrado de 1 g.l.) e tamanho de efeito (Log Ratio e %DIFF).",
        "equivale": "AntConc Keywords e quanteda textstat_keyness.",
        "nao_igual": "TF-IDF (os \"termos distintivos\" do Voyant).",
        "refs": ["keyness"],
    },
    "colocacoes": {
        "titulo": "Colocações",
        "mede": "Quais palavras coocorrem com um termo mais do que o esperado ao acaso.",
        "metrica": "Contagem de coocorrências, log-likelihood e informação mútua (MI); também t e logDice nos CSV.",
        "equivale": "AntConc e LancsBox Collocates.",
        "nao_igual": "Voyant Collocates (só contagem); quanteda textstat_collocations (expressões de várias palavras).",
        "refs": ["colocacoes"],
    },
}


def _base(params: dict) -> list[str]:
    lem = params.get("lematizacao") or {}
    pv = params.get("palavras_vazias") or {}
    vazias = [k for k, v in pv.items() if v is True]
    prop = pv.get("proprias") or []
    return [
        f"lematização {'ligada' if lem.get('ativa', True) else 'desligada'} ({lem.get('metodo', 'simplemma')})",
        "palavras vazias: " + (", ".join(vazias) or "nenhuma") + (f" + {len(prop)} próprias" if prop else ""),
        "seções fora da contagem: "
        + (", ".join(params.get("excluir_secoes") or []) if params.get("excluir_referencias", True) else "nenhuma"),
    ]


def parametros_do_metodo(analise: str, params: dict, snap_keyness: dict | None = None) -> list[str]:
    """Parâmetros efetivamente usados na análise, em frases curtas."""
    base = _base(params)
    j = int(params.get("colocacao_janela") or 5)
    if analise == "resumo":
        return ["janela do MATTR = 500", "TF-IDF: frequência mínima 3 no documento", *base]
    if analise in ("frequencias", "tendencias"):
        extra = ["agrupado por ano; frequência por 10 mil palavras"] if analise == "tendencias" else []
        return [*extra, *base]
    if analise == "kwic":
        return [f"janela de {int(params.get('kwic_janela') or 10)} palavras de cada lado", *base]
    if analise == "colocacoes":
        return [f"janela de {j} palavras à esquerda e {j} à direita (coocorrência de superfície, união das janelas sobrepostas)",
                "frequência mínima do par 3 e do colocado 5; fronteira: bloco de texto", "ordenado por log-likelihood", *base]
    if analise == "keyness":
        p = ((snap_keyness or {}).get("comparacoes") or [{}])[0].get("parametros") or {}
        return [f"cada grupo contra os demais documentos; frequência mínima {p.get('min_freq', 5)}",
                f"dispersão mínima: {p.get('min_docs_a', 2)} documentos do lado em que a palavra-chave ocorre",
                f"significância p < {str(p.get('p', 0.01)).replace('.', ',')}" + (" com Bonferroni" if p.get("bonferroni") else ""), *base]
    return base


ROTULO_METRICA = {
    "g2": "G²", "log_ratio": "Log Ratio", "p": "p", "a": "freq. A", "b": "freq. B", "por_10k_a": "A por 10 mil",
    "por_10k_b": "B por 10 mil", "docs_a": "docs A", "docs_b": "docs B", "ll": "LL", "mi": "MI", "o11": "coocorrências",
    "c1": "freq. do colocado", "e11": "esperado", "z": "z", "mattr": "MATTR", "media": "média", "desvio": "desvio",
    "n_comparaveis": "docs comparáveis", "freq": "freq.", "por_10k": "por 10 mil", "docs": "docs", "n_docs": "nº docs",
    "posicao": "posição", "tokens": "palavras", "tokens_total": "palavras (total)", "pct": "% do corpus", "razao": "razão",
    "rel_ultimo": "por 10 mil (último ano)", "rel_media": "média anterior", "freq_ultimo": "freq. último ano",
    "docs_ultimo": "docs último ano", "ano_ultimo": "ano", "pct_maior_doc": "% no maior doc.", "janela": "janela",
    "n_pend": "pendências", "n_total": "total", "n_excl": "excluídos", "n_av": "avisos",
}
