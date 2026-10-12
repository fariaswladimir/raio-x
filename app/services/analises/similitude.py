"""7.2 - Análise de similitude (árvore máxima) e rede de coocorrência; 15.2 - comunidades, centralidade e layout.

Similitude (Flament 1981; Marchand & Ratinaud 2012) = "análise de similitude" do IRaMuTeQ: grafo das formas mais
frequentes ligado pelo índice de coocorrência nos segmentos de texto e reduzido à **árvore geradora máxima**.
Rede de coocorrência por Jaccard (Higuchi 2016) = "co-occurrence network" do KH Coder. **Não** é o Links do Voyant
(rede em torno de um termo, por janela de palavras) nem os colocados da 5.4.

Unidades e formas
-----------------
- Unidade = segmento de texto (ST, 4.4), como no IRaMuTeQ. Formas = lemas plenos (fora das palavras vazias, >= 2
  letras), as ``n_formas`` mais frequentes em ocorrências (60; empate alfabético). Matriz binária ST × forma.
- n_i = nº de ST com a forma i; c_ij = nº de ST com as duas; N = nº de ST.

Índices (``indice``)
--------------------
- ``coocorrencia`` (padrão do IRaMuTeQ): c_ij;
- ``jaccard``: c_ij / (n_i + n_j − c_ij);
- ``cosseno``: c_ij / √(n_i · n_j);
- ``pmi``: log2(c_ij · N / (n_i · n_j)) (só pares com c_ij > 0; na árvore e na rede entram só os de PMI > 0, isto é,
  coocorrência acima do acaso).
Pares sem coocorrência (c_ij = 0) nunca formam aresta.

Grafos
------
- ``arvore=True``: **árvore geradora máxima** (floresta, se o grafo for desconexo) por Kruskal com as arestas em ordem
  decrescente de peso; empate: menor par (i, j) na ordem das formas (frequência). A árvore só depende da ordem dos
  pesos.
- ``arvore=False``: rede no estilo KH Coder: cada forma mantém suas ``arestas_por_no`` (3) arestas mais fortes
  (união); com ``limiar`` > 0 entram, em vez disso, todas as arestas com peso >= limiar.

15.2 (networkx)
---------------
- Comunidades: Louvain (Blondel et al. 2008; ``networkx.community.louvain_communities``, peso = índice, resolução 1,
  semente fixa ``SEMENTE``) e modularidade ponderada. O Leiden (Traag et al. 2019) não está disponível sem o pacote
  ``leidenalg``/``igraph`` (no networkx 3.6 ele só despacha para outros backends): por isso só Louvain.
  Comunidades numeradas por tamanho decrescente (empate: forma mais frequente).
- Centralidades: grau (nº de arestas), grau ponderado (soma dos pesos), intermediação (Freeman 1977; Brandes, com
  distância = 1 / peso normalizado, normalizada) e PageRank ponderado (Page et al. 1999; amortecimento 0,85).
- Layout Fruchterman-Reingold (``networkx.spring_layout``, pesos normalizados para (0, 1], semente fixa,
  ``ITERACOES_LAYOUT``), coordenadas normalizadas para [0, 1] mantendo a proporção; a interface só desenha.
A posição no desenho não tem significado estatístico.
"""
import math

import networkx as nx
import numpy as np

from app.services.analises import reinert

INDICES = ("coocorrencia", "jaccard", "cosseno", "pmi")
SEMENTE = 42
ITERACOES_LAYOUT = 200
N_FORMAS_MAX = 300
PADRAO = {"n_formas": 60, "indice": "coocorrencia", "arvore": True}
FERRAMENTA_ARVORE = "IRaMuTeQ análise de similitude"
FERRAMENTA_REDE = "KH Coder co-occurrence network"
NAO_EQUIVALENTE = "Voyant Links (rede em torno de um termo)"
METODOLOGIA = (
    "Coocorrência das formas plenas mais frequentes nos segmentos de texto (~40 palavras); índice de coocorrência "
    "bruta (padrão do IRaMuTeQ), Jaccard, cosseno ou PMI; árvore geradora máxima (Kruskal, empate pela ordem das "
    "formas) ou rede com as k arestas mais fortes de cada forma. Comunidades por Louvain (semente fixa) com "
    "modularidade; grau, grau ponderado, intermediação (distância = 1/peso) e PageRank; layout Fruchterman-Reingold "
    "com semente fixa."
)


# ---------- estatística (funções puras) ----------

def matriz_de_indices(B, indice: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(pesos, coocorrências c, frequências n) a partir da matriz binária unidade × forma ``B`` (densa ou esparsa).

    ``pesos[i, j]`` = índice escolhido (NaN onde não há aresta possível: c = 0, diagonal, ou PMI <= 0)."""
    if indice not in INDICES:
        raise ValueError(f"Índice inválido '{indice}': use {', '.join(INDICES)}.")
    B = B.astype(float)
    C = np.asarray((B.T @ B).todense() if hasattr(B, "todense") else B.T @ B, dtype=float)
    N = B.shape[0]
    n = np.diag(C).copy()
    with np.errstate(divide="ignore", invalid="ignore"):
        if indice == "coocorrencia":
            W = C.copy()
        elif indice == "jaccard":
            W = C / (n[:, None] + n[None, :] - C)
        elif indice == "cosseno":
            W = C / np.sqrt(np.outer(n, n))
        else:
            W = np.log2(C * N / np.outer(n, n))
    W = np.where(C > 0, W, np.nan)
    if indice == "pmi":
        W = np.where(W > 0, W, np.nan)
    np.fill_diagonal(W, np.nan)
    return W, C, n


def arestas_candidatas(W: np.ndarray) -> list[tuple[float, int, int]]:
    """[(peso, i, j)] com i < j, na ordem de Kruskal: peso decrescente, depois (i, j) crescente."""
    I, J = np.triu_indices(W.shape[0], k=1)
    ok = ~np.isnan(W[I, J])
    arestas = [(float(W[i, j]), int(i), int(j)) for i, j in zip(I[ok], J[ok])]
    arestas.sort(key=lambda a: (-a[0], a[1], a[2]))
    return arestas


def arvore_maxima(W: np.ndarray) -> list[tuple[int, int, float]]:
    """Árvore (floresta) geradora máxima por Kruskal com união-busca; arestas [(i, j, peso)]."""
    pai = list(range(W.shape[0]))

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    saida = []
    for w, i, j in arestas_candidatas(W):
        ri, rj = raiz(i), raiz(j)
        if ri != rj:
            pai[max(ri, rj)] = min(ri, rj)
            saida.append((i, j, w))
    return saida


def rede_top_k(W: np.ndarray, k: int = 3, limiar: float | None = None) -> list[tuple[int, int, float]]:
    """Rede: união das k arestas mais fortes de cada nó (empate: menor índice) ou, com ``limiar``, peso >= limiar."""
    m = W.shape[0]
    escolhidas = set()
    if limiar is not None and limiar > 0:
        for w, i, j in arestas_candidatas(W):
            if w >= limiar:
                escolhidas.add((i, j))
    else:
        for i in range(m):
            viz = [(W[i, j], j) for j in range(m) if j != i and not np.isnan(W[i, j])]
            viz.sort(key=lambda x: (-x[0], x[1]))
            for _, j in viz[:k]:
                escolhidas.add((min(i, j), max(i, j)))
    return sorted(((i, j, float(W[i, j])) for i, j in escolhidas), key=lambda a: (-a[2], a[0], a[1]))


def grafo(n_nos: int, arestas: list[tuple[int, int, float]]) -> nx.Graph:
    """Grafo networkx com nós 0..n−1 (ordem fixa), ``weight`` = peso e ``dist`` = 1 / (peso / maior peso)."""
    G = nx.Graph()
    G.add_nodes_from(range(n_nos))
    maior = max((w for _, _, w in arestas), default=1.0) or 1.0
    for i, j, w in arestas:
        G.add_edge(i, j, weight=float(w), w_norm=float(w) / maior, dist=maior / float(w))
    return G


def comunidades(G: nx.Graph, semente: int = SEMENTE, resolucao: float = 1.0) -> tuple[list[list[int]], float]:
    """Louvain (semente fixa) só sobre os nós com aresta; isolados viram comunidades unitárias. (comunidades, Q)."""
    if G.number_of_edges() == 0:
        return [[v] for v in G.nodes], 0.0
    comms = nx.community.louvain_communities(G, weight="weight", resolution=resolucao, seed=semente)
    comms = [sorted(c) for c in comms]
    comms.sort(key=lambda c: (-len(c), c[0]))
    q = nx.community.modularity(G, comms, weight="weight", resolution=resolucao)
    return comms, float(q)


def centralidades(G: nx.Graph) -> dict:
    """Grau, grau ponderado, intermediação (dist = 1/peso normalizado) e PageRank ponderado, por nó."""
    grau = dict(G.degree())
    forca = dict(G.degree(weight="weight"))
    inter = nx.betweenness_centrality(G, weight="dist", normalized=True)
    pr = nx.pagerank(G, alpha=0.85, weight="weight", tol=1e-10, max_iter=1000) if G.number_of_edges() else \
        {v: 1.0 / max(1, G.number_of_nodes()) for v in G.nodes}
    return {"grau": grau, "grau_ponderado": forca, "intermediacao": inter, "pagerank": pr}


def layout(G: nx.Graph, semente: int = SEMENTE) -> dict[int, tuple[float, float]]:
    """Fruchterman-Reingold (spring_layout) com pesos normalizados; coordenadas em [0, 1] mantendo a proporção."""
    if G.number_of_nodes() == 0:
        return {}
    if G.number_of_nodes() == 1:
        return {next(iter(G.nodes)): (0.5, 0.5)}
    pos = nx.spring_layout(G, weight="w_norm", seed=semente, iterations=ITERACOES_LAYOUT)
    xy = np.array([pos[v] for v in G.nodes])
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    escala = float((hi - lo).max()) or 1.0
    centro = (lo + hi) / 2
    norm = (xy - centro) / escala + 0.5
    return {v: (float(norm[k, 0]), float(norm[k, 1])) for k, v in enumerate(G.nodes)}


# ---------- análise sobre o corpus ----------

def calcular(pasta, metas: list[dict], filtro, n_formas: int = 60, indice: str = "coocorrencia", arvore: bool = True,
             comunidades_on: bool = True, arestas_por_no: int = 3, limiar: float | None = None) -> dict:
    """Similitude/rede sobre os ST do corpus. Levanta ValueError (parâmetros, corpus pequeno)."""
    if not 3 <= n_formas <= N_FORMAS_MAX:
        raise ValueError(f"n_formas deve estar entre 3 e {N_FORMAS_MAX}.")
    if indice not in INDICES:
        raise ValueError(f"Índice inválido '{indice}': use {', '.join(INDICES)}.")
    if not 1 <= arestas_por_no <= 20:
        raise ValueError("arestas_por_no deve estar entre 1 e 20.")
    u = reinert.carregar_unidades(pasta, metas, filtro)
    if not u["st"]:
        raise ValueError("Nenhum segmento de texto: execute o pipeline (etapa segmentos).")
    formas = sorted(u["freq"], key=lambda f: (-u["freq"][f], f))[:n_formas]
    if len(formas) < 3:
        raise ValueError("Menos de 3 formas plenas no corpus: a similitude não se aplica.")
    B = reinert.matriz_st_forma(u["formas"], formas)
    W, C, n = matriz_de_indices(B, indice)
    N = B.shape[0]
    arestas = arvore_maxima(W) if arvore else rede_top_k(W, arestas_por_no, limiar)
    G = grafo(len(formas), arestas)
    comms, q = comunidades(G) if comunidades_on else ([list(range(len(formas)))], None)
    comunidade_de = {v: k + 1 for k, c in enumerate(comms) for v in c}
    cen = centralidades(G)
    pos = layout(G)
    with np.errstate(divide="ignore", invalid="ignore"):
        jac = C / (n[:, None] + n[None, :] - C)
        cos = C / np.sqrt(np.outer(n, n))
        pmi = np.where(C > 0, np.log2(C * N / np.outer(n, n)), np.nan)
    nos = [{
        "forma": f, "freq": int(u["freq"][f]), "n_st": int(n[i]), "comunidade": comunidade_de.get(i),
        "grau": int(cen["grau"][i]), "grau_ponderado": round(float(cen["grau_ponderado"][i]), 6),
        "intermediacao": round(float(cen["intermediacao"][i]), 6), "pagerank": round(float(cen["pagerank"][i]), 6),
        "x": round(pos[i][0], 5), "y": round(pos[i][1], 5),
    } for i, f in enumerate(formas)]
    saida_arestas = [{
        "a": formas[i], "b": formas[j], "peso": round(w, 6), "coocorrencias": int(C[i, j]),
        "jaccard": round(float(jac[i, j]), 6), "cosseno": round(float(cos[i, j]), 6),
        "pmi": None if math.isnan(pmi[i, j]) else round(float(pmi[i, j]), 6),
        "comunidade": comunidade_de.get(i) if comunidade_de.get(i) == comunidade_de.get(j) else None,
    } for i, j, w in arestas]
    lista_comms = [{"comunidade": k + 1, "n": len(c),
                    "formas": [formas[v] for v in sorted(c, key=lambda v: (-cen["pagerank"][v], v))]}
                   for k, c in enumerate(comms)] if comunidades_on else []
    mensagem = None
    componentes = nx.number_connected_components(G)
    if componentes > 1:
        isolados = sum(1 for v in G.nodes if G.degree(v) == 0)
        mensagem = (f"O grafo tem {componentes} componentes ({isolados} forma(s) sem aresta): "
                    + ("a árvore máxima vira uma floresta." if arvore else "aumente arestas_por_no ou reduza o limiar."))
    return {
        "indice": indice, "arvore": bool(arvore), "n_formas": len(formas), "segmentos": N,
        "n_arestas": len(saida_arestas), "componentes": componentes, "nos": nos, "arestas": saida_arestas,
        "comunidades": lista_comms, "modularidade": None if q is None else round(q, 6),
        "mensagem": mensagem,
        "parametros": {"n_formas": n_formas, "indice": indice, "arvore": bool(arvore), "comunidades": bool(comunidades_on),
                       "arestas_por_no": arestas_por_no, "limiar": limiar, "semente": SEMENTE,
                       "unidade": "lema", "vazias": "filtrar"},
        "algoritmos": {"comunidades": "Louvain (networkx; Leiden indisponível)", "layout": "Fruchterman-Reingold",
                       "intermediacao": "Brandes, distância = 1/peso normalizado", "pagerank": "ponderado, α = 0,85"},
        "metodologia": METODOLOGIA,
        "ferramenta_equivalente": FERRAMENTA_ARVORE if arvore else FERRAMENTA_REDE,
        "nao_equivalente": NAO_EQUIVALENTE,
    }
