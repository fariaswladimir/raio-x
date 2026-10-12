"""5.2 - Frequências e distribuição (tendências), a partir de ``cache/vocabulario.json`` (Frente 4).

Equivale ao painel Terms/Cirrus/Trends do Voyant e à Word list do AntConc, com os termos contados
por lema (padrão, D5) ou por forma. Documentação das métricas:

- ``freq``: ocorrências no escopo; ``por_10k`` = freq / tokens contados do escopo * 10.000;
  ``docs`` = em quantos documentos do escopo o termo aparece (df).
- "Tokens contados" são os do vocabulário: palavras do corpo (``incluir``) com >= 2 letras, *com* as
  palavras vazias (denominador igual ao do Voyant). O filtro de palavras vazias é aplicado na consulta.
- Tendências: para cada termo (ou curinga, ex.: ``agent*``) soma a frequência de todas as formas/lemas
  que casam, por documento (ordem do arquivo), ano ou grupo; ``rel`` = por 10 mil tokens da unidade.
"""
from collections import Counter

from app.services.analises import dados
from app.services.palavras_vazias import token_vazio


def contagem_documento(d: dict, filtro, por: str, filtrar: bool) -> Counter:
    """Contagem de um documento do vocabulário por lema ou por forma (``norma``), com ou sem palavras vazias."""
    if not filtrar:
        return Counter(d["lema"] if por == "lema" else d["norma"])
    c: Counter = Counter()
    for norm, lema, freq in d["pares"]:
        if not token_vazio(norm, lema, filtro):
            c[lema if por == "lema" else norm] += freq
    return c


def _docs_do_escopo(voc: dict, metas: list[dict]) -> list[dict]:
    return [voc["documentos"][str(m["id"])] for m in metas if str(m["id"]) in voc["documentos"]]


def _casador_de_texto(texto: str):
    """Caixa de filtro: substring (sem curinga) ou curinga ``*`` (casa o termo inteiro)."""
    texto = (texto or "").strip().lower()
    if not texto:
        return None
    if "*" in texto:
        itens = dados.compilar_consulta(texto)
        return lambda t: any(dados.casa(i, t) for i in itens)
    return lambda t: texto in t


def listar(voc: dict, metas: list[dict], filtro, por: str = "lema", filtrar: bool = True, limite: int = 200,
           filtro_texto: str = "") -> dict:
    """Termos mais frequentes do escopo (``metas`` = documentos do escopo). Também usado por /vocabulario."""
    docs = _docs_do_escopo(voc, metas)
    total_tokens = sum(d["tokens"] for d in docs)
    freq: Counter = Counter()
    df: Counter = Counter()
    for d in docs:
        local = contagem_documento(d, filtro, por, filtrar)
        freq.update(local)
        df.update(local.keys())
    casador = _casador_de_texto(filtro_texto)
    ordenados = sorted(((t, c) for t, c in freq.items() if casador is None or casador(t)), key=lambda kv: (-kv[1], kv[0]))
    itens = [
        {"termo": t, "freq": c, "por_10k": round(c / total_tokens * 10000, 2) if total_tokens else 0.0, "docs": df[t]}
        for t, c in ordenados[: max(0, limite)]
    ]
    return {"por": por, "filtradas": filtrar, "documentos": len(docs), "tokens": total_tokens,
            "tipos": len(ordenados), "itens": itens}


# ---------- distribuição (tendências) ----------

def _ordem_ano(chave: str):
    return (chave == dados.SEM_ANO, chave)


def _ordem_grupo(chave: str):
    return (chave == dados.SEM_GRUPO, chave.lower())


def unidades(metas: list[dict], agrupar: str) -> list[dict]:
    """Unidades da distribuição: [{"chave", "rotulo", "metas": [...]}] em ordem estável."""
    if agrupar == "documento":
        return [{"chave": str(m["id"]), "rotulo": m["rotulo"], "metas": [m]} for m in metas]
    chave_de = dados.chave_ano if agrupar == "ano" else dados.chave_grupo
    ordem = _ordem_ano if agrupar == "ano" else _ordem_grupo
    grupos: dict[str, list[dict]] = {}
    for m in metas:
        grupos.setdefault(chave_de(m), []).append(m)
    return [{"chave": k, "rotulo": k, "metas": grupos[k]} for k in sorted(grupos, key=ordem)]


def distribuicao(voc: dict, metas: list[dict], termos: list[str], por: str = "lema", agrupar: str = "documento",
                 metrica: str = "rel") -> dict:
    """Frequência de até 6 termos (curinga ``*``) por documento, ano ou grupo.

    ``valores`` segue a ``metrica`` ("rel" = por 10 mil tokens da unidade; "bruta" = contagem); ``brutos`` e
    ``rel`` vêm sempre, para o tooltip. Termo ausente do corpus resulta em série de zeros.
    """
    campo = "lema" if por == "lema" else "norma"
    termos = termos[: dados.MAX_TERMOS]
    itens = [dados.compilar_consulta(t)[0] for t in termos if dados.compilar_consulta(t)]
    categorias = []
    series = [{"termo": i["texto"], "brutos": [], "rel": [], "valores": []} for i in itens]
    for u in unidades(metas, agrupar):
        docs = _docs_do_escopo(voc, u["metas"])
        tokens = sum(d["tokens"] for d in docs)
        categorias.append({"chave": u["chave"], "rotulo": u["rotulo"], "tokens": tokens, "documentos": len(docs)})
        for s, item in zip(series, itens):
            bruto = 0
            for d in docs:
                mapa = d[campo]
                bruto += sum(mapa[k] for k in dados.chaves_que_casam([item], mapa))
            rel = round(bruto / tokens * 10000, 2) if tokens else 0.0
            s["brutos"].append(bruto)
            s["rel"].append(rel)
            s["valores"].append(rel if metrica == "rel" else bruto)
    return {"por": por, "agrupar": agrupar, "metrica": metrica, "termos": [i["texto"] for i in itens],
            "categorias": categorias, "series": series}
