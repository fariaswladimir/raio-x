"""15.9 - Agrupamento de documentos: k-means, espectral e PCA (sobre a mesma matriz TF-IDF da similaridade, 6.3).

Matriz
------
Mesma da 6.3 (``similaridade.matriz_contagens`` + ``similaridade.tfidf``): lemas (ou formas/termos) sem palavras vazias,
``df >= min_df`` e ``<= max_df·N``, TF-IDF sublinear com norma L2 por documento. ``cos = X·Xᵀ`` e distância ``1 - cos``.
Documentos sem termos saem (``excluidos``), como na 6.3.

k-means (Lloyd, 1982; Arthur e Vassilvitskii, 2007)
---------------------------------------------------
Distância euclidiana sobre os vetores L2 (equivale a k-means esférico: ``||a - b||² = 2(1 - cos)``). Inicialização
**k-means++**, ``n_init`` = 10 reinícios com sementes derivadas de uma semente fixa (``semente`` = 42), até 300 iterações de
Lloyd (parada quando nenhum documento muda de grupo); fica o reinício de menor inércia (empate: o primeiro). Grupo vazio
é refeito com o documento mais distante do seu centroide.

Espectral (Ng, Jordan e Weiss, 2002; von Luxburg, 2007)
-------------------------------------------------------
Grafo de similaridade: aresta ``i-j`` com peso cosseno se ``j`` está entre os ``vizinhos`` (10, no máximo N-1) mais parecidos
de ``i`` **ou** vice-versa (grafo kNN simétrico); diagonal 0. Laplaciano normalizado simétrico
``L = I - D^(-1/2) W D^(-1/2)``; os ``k`` autovetores de menor autovalor formam a matriz ``U`` (N x k), cujas linhas são
normalizadas a norma 1 e agrupadas por k-means (mesma rotina, mesma semente). Nós de grau 0 ficam com linha nula.
O sinal e a ordem das colunas não afetam o resultado. Determinístico.

Escolha de k e silhueta
-----------------------
``silhuetas`` = silhueta média sobre ``1 - cos`` para ``k = 2..min(8, N-1)`` (a mesma de ``similaridade.silhueta``). Com ``k``
omitido, usa-se o k de maior silhueta (empate: menor k). Os grupos são numerados 1..k pelo menor índice de documento.

PCA
---
Colunas centradas e SVD de ``X - média``: coordenadas = ``U·S`` nas 2 primeiras componentes (sinal fixado de modo que a
maior coordenada absoluta seja positiva); ``variancia_explicada`` = ``s²/Σs²`` das primeiras componentes (a soma de todas
vale 1). É a projeção linear do TF-IDF; o mapa MDS da 6.3 (sobre ``1 - cos``) é outra projeção e **não coincide**.

Comparação com o Ward (6.3)
---------------------------
Corte do Ward (vetores L2) no mesmo k; ``ari_ward`` = índice de Rand ajustado (Hubert e Arabie, 1985) entre as duas partições
(1 = iguais; ~0 = acordo ao acaso; pode ser negativo). ``ari_ward_por_k`` traz o ARI para cada k avaliado.
"""
import math

import numpy as np
from scipy.cluster import hierarchy

from app.services.analises import dados, similaridade

METODOS = ("kmeans", "espectral")
SEMENTE = 42
N_INIT = 10
MAX_ITER = 300
K_MAX_AUTO = 8
N_VIZINHOS = 10
N_TERMOS_GRUPO = 10
METODOLOGIA = (
    "k-means (Lloyd, k-means++, 10 reinícios, semente 42) e agrupamento espectral (Laplaciano normalizado do grafo kNN de cosseno, "
    "Ng-Jordan-Weiss) sobre o TF-IDF da 6.3; k pela maior silhueta (1 - cosseno); PCA por SVD do TF-IDF centrado; "
    "concordância com o Ward pelo índice de Rand ajustado."
)


# ---------- k-means ----------

def _kmeans_mais_mais(x: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    n = x.shape[0]
    centros = [x[int(rng.integers(n))]]
    d2 = ((x - centros[0]) ** 2).sum(axis=1)
    for _ in range(1, k):
        total = d2.sum()
        if total <= 0:
            idx = int(rng.integers(n))
        else:
            idx = int(rng.choice(n, p=d2 / total))
        centros.append(x[idx])
        d2 = np.minimum(d2, ((x - x[idx]) ** 2).sum(axis=1))
    return np.array(centros)


def _lloyd(x: np.ndarray, centros: np.ndarray, max_iter: int) -> tuple[np.ndarray, np.ndarray, float]:
    k = centros.shape[0]
    rotulos = np.full(x.shape[0], -1)
    for _ in range(max_iter):
        d = np.maximum((x ** 2).sum(1)[:, None] - 2 * x @ centros.T + (centros ** 2).sum(1)[None, :], 0.0)
        novo = d.argmin(axis=1)
        for g in range(k):  # grupo vazio: leva o documento mais distante do próprio centroide
            if not (novo == g).any():
                dist_propria = d[np.arange(len(novo)), novo]
                j = int(dist_propria.argmax())
                novo[j] = g
        if (novo == rotulos).all():
            break
        rotulos = novo
        for g in range(k):
            centros[g] = x[rotulos == g].mean(axis=0)
    inercia = float(((x - centros[rotulos]) ** 2).sum())
    return rotulos, centros, inercia


def kmeans(x: np.ndarray, k: int, semente: int = SEMENTE, n_init: int = N_INIT, max_iter: int = MAX_ITER) -> tuple[np.ndarray, float]:
    """Rótulos (0..k-1) e inércia do melhor de ``n_init`` reinícios (k-means++; Lloyd)."""
    n = x.shape[0]
    if not 1 <= k <= n:
        raise ValueError(f"k deve estar entre 1 e {n}.")
    x = np.asarray(x, dtype=np.float64)
    melhor = None
    for r in range(n_init):
        rng = np.random.default_rng([semente, r])
        rotulos, _c, inercia = _lloyd(x, _kmeans_mais_mais(x, k, rng), max_iter)
        if melhor is None or inercia < melhor[1] - 1e-12:
            melhor = (rotulos, inercia)
    return melhor


def renumerar(rotulos: np.ndarray) -> np.ndarray:
    """Rótulos 1..k pela ordem do menor índice de documento de cada grupo."""
    novo: dict[int, int] = {}
    for r in rotulos:
        novo.setdefault(int(r), len(novo) + 1)
    return np.array([novo[int(r)] for r in rotulos])


# ---------- espectral ----------

def grafo_knn(sim: np.ndarray, vizinhos: int) -> np.ndarray:
    """Pesos (cosseno) das arestas do grafo kNN simétrico (``i-j`` se j está entre os mais parecidos de i, ou o contrário)."""
    n = sim.shape[0]
    v = max(1, min(vizinhos, n - 1))
    s = sim.copy()
    np.fill_diagonal(s, -np.inf)
    w = np.zeros_like(sim)
    ordem = np.argsort(-s, axis=1, kind="stable")[:, :v]
    for i in range(n):
        w[i, ordem[i]] = sim[i, ordem[i]]
    w = np.maximum(w, w.T)
    np.fill_diagonal(w, 0.0)
    return w


def incorporacao_espectral(w: np.ndarray, k: int) -> np.ndarray:
    """Linhas (normalizadas) dos ``k`` autovetores de menor autovalor do Laplaciano normalizado simétrico."""
    grau = w.sum(axis=1)
    inv = np.divide(1.0, np.sqrt(grau), out=np.zeros_like(grau), where=grau > 0)
    lap = np.eye(w.shape[0]) - inv[:, None] * w * inv[None, :]
    lap = (lap + lap.T) / 2.0
    _val, vec = np.linalg.eigh(lap)
    u = vec[:, :k]
    normas = np.sqrt((u ** 2).sum(axis=1, keepdims=True))
    return np.divide(u, normas, out=np.zeros_like(u), where=normas > 0)


def espectral(sim: np.ndarray, k: int, vizinhos: int = N_VIZINHOS, semente: int = SEMENTE) -> np.ndarray:
    u = incorporacao_espectral(grafo_knn(sim, vizinhos), k)
    rotulos, _ = kmeans(u, k, semente)
    return rotulos


# ---------- PCA e ARI ----------

def pca(x: np.ndarray, componentes: int = 2) -> tuple[np.ndarray, list[float]]:
    """Coordenadas nas primeiras ``componentes`` e a variância explicada de todas as componentes (soma 1)."""
    n = x.shape[0]
    c = x - x.mean(axis=0, keepdims=True)
    u, s, vt = np.linalg.svd(c, full_matrices=False)
    total = float((s ** 2).sum())
    var = [float(v) / total for v in (s ** 2)] if total > 0 else [0.0] * len(s)
    coords = np.zeros((n, componentes))
    for d in range(min(componentes, len(s))):
        col = u[:, d] * s[d]
        i_max = int(np.argmax(np.abs(col)))
        if col[i_max] < 0:
            col = -col
        coords[:, d] = col
    return coords, var


def ari(a, b) -> float:
    """Índice de Rand ajustado entre duas partições (Hubert e Arabie, 1985)."""
    a, b = np.asarray(a), np.asarray(b)
    n = len(a)
    if n < 2:
        return 1.0
    _, ia = np.unique(a, return_inverse=True)
    _, ib = np.unique(b, return_inverse=True)
    tab = np.zeros((ia.max() + 1, ib.max() + 1))
    for i, j in zip(ia, ib):
        tab[i, j] += 1
    c2 = lambda v: v * (v - 1) / 2.0  # noqa: E731
    soma_celulas = c2(tab).sum()
    soma_a = c2(tab.sum(axis=1)).sum()
    soma_b = c2(tab.sum(axis=0)).sum()
    esperado = soma_a * soma_b / c2(n)
    maximo = (soma_a + soma_b) / 2.0
    if maximo == esperado:
        return 1.0
    return float((soma_celulas - esperado) / (maximo - esperado))


# ---------- análise completa ----------

def preparar(voc: dict, metas: list[dict], filtro, por: str = "lema", min_df: int = 2, max_df: float = 0.9, sublinear: bool = True):
    """``(x, mat, docs, termos, excluidos)``: TF-IDF L2 (a mesma matriz da similaridade 6.3)."""
    mat, docs, termos, excluidos = similaridade.matriz_contagens(voc, metas, filtro, por, min_df, max_df)
    n_antes = len(docs)
    vazios = mat.sum(axis=1) == 0
    if vazios.any():
        for i in np.where(vazios)[0]:
            excluidos.append({"id": docs[i]["id"], "rotulo": docs[i]["rotulo"], "motivo": "nenhum termo passa em min_df/max_df"})
        mat = mat[~vazios]
        docs = [d for d, e in zip(docs, vazios) if not e]
    if len(docs) < 3:
        raise ValueError("São necessários ao menos 3 documentos com texto para agrupar (após os filtros).")
    x = similaridade.tfidf(mat, sublinear, n_antes)
    return x, mat, docs, termos, excluidos


def particao(metodo: str, x: np.ndarray, sim: np.ndarray, k: int, vizinhos: int = N_VIZINHOS, semente: int = SEMENTE) -> np.ndarray:
    if metodo == "kmeans":
        rotulos, _ = kmeans(x, k, semente)
    else:
        rotulos = espectral(sim, k, vizinhos, semente)
    return renumerar(rotulos)


def calcular(voc: dict, metas: list[dict], filtro, por: str = "lema", metodo: str = "kmeans", k: int | None = None,
             min_df: int = 2, max_df: float = 0.9, sublinear: bool = True, vizinhos: int = N_VIZINHOS,
             semente: int = SEMENTE, n_termos: int = N_TERMOS_GRUPO) -> dict:
    """Agrupamento k-means ou espectral, PCA e comparação com o Ward (ver o docstring do módulo)."""
    if metodo not in METODOS:
        raise ValueError(f"Método inválido '{metodo}': use 'kmeans' ou 'espectral'.")
    if por not in ("lema", "forma"):
        raise ValueError(f"Unidade inválida '{por}'.")
    if not 0 < max_df <= 1:
        raise ValueError("max_df deve estar entre 0 (exclusive) e 1.")
    if min_df < 1:
        raise ValueError("min_df deve ser >= 1.")
    x, mat, docs, termos, excluidos = preparar(voc, metas, filtro, por, min_df, max_df, sublinear)
    n = len(docs)
    if k is not None and not 2 <= k <= n - 1:
        raise ValueError(f"k deve estar entre 2 e {n - 1} (ou omitido para escolha automática).")
    sim = similaridade.cosseno(x)
    dist = 1.0 - sim
    np.fill_diagonal(dist, 0.0)
    z = similaridade.ligar(x, dist, "ward")
    kmax = min(K_MAX_AUTO, n - 1)
    parts: dict[int, np.ndarray] = {}
    silhuetas, aris = [], []
    for kk in range(2, kmax + 1):
        parts[kk] = particao(metodo, x, sim, kk, vizinhos, semente)
        s = similaridade.silhueta(dist, parts[kk])
        ward_k = hierarchy.cut_tree(z, n_clusters=kk).ravel()
        silhuetas.append({"k": kk, "silhueta": round(float(s), 4)})
        aris.append({"k": kk, "ari_ward": round(ari(parts[kk], ward_k), 4)})
    if k is None:
        k_usado = max(silhuetas, key=lambda r: (r["silhueta"], -r["k"]))["k"]
    else:
        k_usado = k
        if k_usado not in parts:
            parts[k_usado] = particao(metodo, x, sim, k_usado, vizinhos, semente)
    rotulos = parts[k_usado]
    ward = hierarchy.cut_tree(z, n_clusters=k_usado).ravel()
    ari_k = ari(rotulos, ward)
    coords, var = pca(x)
    media_geral = x.mean(axis=0)
    grupos = []
    for g in range(1, k_usado + 1):
        idx = np.where(rotulos == g)[0]
        dif = x[idx].mean(axis=0) - media_geral
        ranque = sorted(range(len(termos)), key=lambda j: (-dif[j], termos[j]))[:n_termos]
        grupos.append({"cluster": g, "documentos": int(len(idx)), "ids": [docs[i]["id"] for i in idx],
                       "termos": [{"termo": termos[j], "diferenca": round(float(dif[j]), 5)} for j in ranque if dif[j] > 0]})
    documentos = [{
        "id": m["id"], "rotulo": m["rotulo"], "arquivo": m["arquivo"], "grupo": dados.chave_grupo(m), "ano": dados.chave_ano(m),
        "cluster": int(rotulos[i]), "ward": int(ward[i]) + 1, "x": round(float(coords[i, 0]), 6), "y": round(float(coords[i, 1]), 6),
    } for i, m in enumerate(docs)]
    return {
        "unidade": por, "metodo": metodo, "n_documentos": n, "n_termos": len(termos), "excluidos": excluidos,
        "k": k_usado, "k_automatico": k is None, "silhueta": next(r["silhueta"] for r in silhuetas if r["k"] == k_usado),
        "silhuetas": silhuetas, "ari_ward": round(ari_k, 4), "ari_ward_por_k": aris,
        "documentos": documentos, "grupos": grupos,
        "pca": {"variancia_explicada": [round(v, 4) for v in var[:10]], "soma_eixos": round(sum(var[:2]), 4),
                "n_componentes": len(var)},
        "parametros": {"por": por, "metodo": metodo, "k": k, "min_df": min_df, "max_df": max_df, "sublinear": sublinear,
                       "vizinhos": vizinhos, "semente": semente, "n_init": N_INIT},
        "metodologia": METODOLOGIA,
    }
