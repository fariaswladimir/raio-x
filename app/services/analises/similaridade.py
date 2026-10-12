"""6.3 - Similaridade entre documentos (TF-IDF, cosseno) e agrupamento hierárquico.

Equivale à similaridade/dendrograma do Lexos e ao mapa de documentos do Orange. **Não** é o "termos distintivos"
do Voyant (TF-IDF por documento, sem agrupamento) nem os tópicos do LDA.

Matriz documento x termo
------------------------
Unidade ``por`` = lema (padrão, D5), forma (``norma``) ou termo (4.3). Só tokens do corpo (``incluir`` = 1) com >= 2
letras, com as palavras vazias filtradas (filtro dos parâmetros atuais). Documentos sem nenhum termo após o filtro
saem da análise (``excluidos``); documentos ``com_problema`` já não fazem parte do corpus.
Um termo fica se aparece em ``df >= min_df`` (2) documentos e em ``df <= max_df * N`` (0,9; N = nº de documentos
da análise). Se nada sobra, ValueError.

Pesos (TF-IDF, convenção do scikit-learn com idf suavizado), para o termo t no documento d, com f = contagem:

    tf(t, d)  = f                       (sublinear = False)
              = 1 + ln f   se f > 0     (sublinear = True, padrão: atenua o peso de repetições em textos longos)
    idf(t)    = ln((1 + N) / (1 + df(t))) + 1
    x(t, d)   = tf(t, d) * idf(t)
    v(d)      = x(., d) / ||x(., d)||_2         (normalização L2 por documento)

Documentos cujo vetor fica nulo (nenhum termo sobrevive ao df) também saem (``excluidos``); N do idf é o nº de
documentos com algum termo antes desse segundo corte.

Similaridade e distância
------------------------
``cos(d, e) = v(d) . v(e)`` (matriz simétrica, diagonal 1) e distância ``1 - cos`` (em [0, 1] porque os pesos
são não negativos).

Agrupamento hierárquico aglomerativo (scipy.cluster.hierarchy)
--------------------------------------------------------------
- ``average``: ligação média (UPGMA) sobre ``1 - cos``;
- ``ward``: Ward sobre os vetores L2-normalizados (distância euclidiana; para vetores unitários
  ``||a - b||^2 = 2 (1 - cos)``, então Ward aqui é coerente com o cosseno).
``fusoes`` = lista de fusões (``esquerda``/``direita`` são índices de documento < N ou N + i = fusão i, como na
matriz Z do scipy), com altura e tamanho; ``ordem_folhas`` = ordem das folhas (a mesma de percorrer a árvore da
esquerda para a direita). Corte em k grupos (``cut_tree``): k informado ou **automático** = k de 2 a min(8, N-1)
com a maior silhueta média sobre ``1 - cos`` (empate: menor k). Os grupos são numerados 1..k pela ordem das
folhas. Tudo determinístico (sem sementes).

Mapa 2D
-------
Escalonamento multidimensional clássico (Torgerson) sobre ``1 - cos``: B = -J D² J / 2 (J = centralização),
coordenadas = autovetores dos 2 maiores autovalores x sqrt(autovalor). O sinal de cada eixo é fixado de modo que a
coordenada de maior valor absoluto seja positiva (desempate: menor índice). ``variancia_explicada`` = parcela dos
autovalores positivos que cada eixo guarda.

Vizinhos e termos característicos
---------------------------------
Os 5 documentos mais parecidos de cada um (cosseno, desempate pela ordem do corpus). Termos característicos de
cada grupo: os 10 de maior (média do TF-IDF L2 no grupo - média no corpus), só diferenças positivas.
"""
import math

import numpy as np
from scipy.cluster import hierarchy

from app.services.analises import dados, frequencias

UNIDADES = ("lema", "forma", "termo")
METODOS = ("average", "ward")
FERRAMENTA_EQUIVALENTE = "Lexos (similaridade/dendrograma), Orange (mapa de documentos)"
NAO_EQUIVALENTE = "Voyant 'termos distintivos' (TF-IDF sem agrupamento); tópicos do LDA"
K_MAX_AUTO = 8
N_VIZINHOS = 5
N_TERMOS_GRUPO = 10
METODOLOGIA = (
    "TF-IDF por documento (tf sublinear 1 + ln f; idf = ln((1 + N)/(1 + df)) + 1; norma L2), cosseno entre "
    "documentos, agrupamento hierárquico (ligação média sobre 1 - cos, ou Ward sobre vetores L2) e mapa 2D por "
    "escalonamento multidimensional clássico. Termos com df >= min_df e df <= max_df x N; palavras vazias filtradas."
)


# ---------- matriz e pesos (funções puras) ----------

def tfidf(contagens: np.ndarray, sublinear: bool = True, n_documentos: int | None = None) -> np.ndarray:
    """Matriz documento x termo de contagens -> TF-IDF com norma L2 por linha (fórmulas no docstring do módulo).

    Linhas nulas continuam nulas. ``df`` vem da própria matriz; ``N`` também, salvo ``n_documentos``."""
    f = np.asarray(contagens, dtype=float)
    n = f.shape[0] if n_documentos is None else n_documentos
    df = (f > 0).sum(axis=0)
    idf = np.log((1.0 + n) / (1.0 + df)) + 1.0
    tf = np.where(f > 0, 1.0 + np.log(np.where(f > 0, f, 1.0)), 0.0) if sublinear else f
    x = tf * idf
    normas = np.sqrt((x ** 2).sum(axis=1, keepdims=True))
    return np.divide(x, normas, out=np.zeros_like(x), where=normas > 0)


def cosseno(v: np.ndarray) -> np.ndarray:
    """Cosseno entre as linhas (já L2-normalizadas): simétrica, diagonal 1 (1 só se a linha não for nula)."""
    s = v @ v.T
    s = (s + s.T) / 2.0
    return np.clip(s, 0.0, 1.0)


def matriz_contagens(voc: dict, metas: list[dict], filtro, por: str = "lema", min_df: int = 2, max_df: float = 0.9):
    """(contagens, documentos, termos, excluidos). ``voc`` = vocabulário (ou a visão por termo); ``por`` = lema/forma."""
    docs_voc = voc["documentos"]
    contagens_doc, validos, excluidos = [], [], []
    for m in metas:
        d = docs_voc.get(str(m["id"]))
        c = frequencias.contagem_documento(d, filtro, por, True) if d is not None else {}
        if c:
            contagens_doc.append(c)
            validos.append(m)
        else:
            excluidos.append({"id": m["id"], "rotulo": m["rotulo"], "motivo": "sem termos após o filtro de palavras vazias"})
    n = len(validos)
    df: dict[str, int] = {}
    for c in contagens_doc:
        for t in c:
            df[t] = df.get(t, 0) + 1
    teto = max_df * n + 1e-9
    termos = sorted(t for t, v in df.items() if v >= min_df and v <= teto)
    if not termos:
        raise ValueError("Nenhum termo passa nos limites de documentos (min_df/max_df): reduza min_df, aumente max_df ou use mais documentos.")
    col = {t: j for j, t in enumerate(termos)}
    mat = np.zeros((n, len(termos)))
    for i, c in enumerate(contagens_doc):
        for t, f in c.items():
            j = col.get(t)
            if j is not None:
                mat[i, j] = f
    return mat, validos, termos, excluidos


# ---------- agrupamento ----------

def silhueta(dist: np.ndarray, rotulos: np.ndarray) -> float:
    """Silhueta média sobre uma matriz de distâncias (grupos de 1 documento contam 0)."""
    n = len(rotulos)
    ks = np.unique(rotulos)
    if len(ks) < 2 or len(ks) >= n:
        return 0.0
    soma = 0.0
    for i in range(n):
        meu = rotulos == rotulos[i]
        if meu.sum() <= 1:
            continue
        a = dist[i, meu].sum() / (meu.sum() - 1)
        b = min(dist[i, rotulos == k].mean() for k in ks if k != rotulos[i])
        soma += (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return soma / n


def ligar(v: np.ndarray, dist: np.ndarray, metodo: str) -> np.ndarray:
    n = v.shape[0]
    if n < 2:
        raise ValueError("São necessários ao menos 2 documentos com texto.")
    if metodo == "ward":
        return hierarchy.linkage(v, method="ward")
    condensada = dist[np.triu_indices(n, 1)]
    return hierarchy.linkage(condensada, method="average")


def cortar(z: np.ndarray, dist: np.ndarray, k: int | None) -> tuple[np.ndarray, int, list[dict]]:
    """Rótulos 1..k pela ordem das folhas, k escolhido e (se automático) a lista de silhuetas."""
    n = z.shape[0] + 1
    ordem = hierarchy.leaves_list(z)
    silhuetas: list[dict] = []
    if k is None:
        if n < 3:
            k = n
        else:
            melhor = None
            for kk in range(2, min(K_MAX_AUTO, n - 1) + 1):
                s = silhueta(dist, hierarchy.cut_tree(z, n_clusters=kk).ravel())
                silhuetas.append({"k": kk, "silhueta": round(float(s), 4)})
                if melhor is None or s > melhor[1] + 1e-12:
                    melhor = (kk, s)
            k = melhor[0]
    k = max(1, min(int(k), n))
    bruto = hierarchy.cut_tree(z, n_clusters=k).ravel()
    novo: dict[int, int] = {}
    for i in ordem:  # numeração pela ordem das folhas
        novo.setdefault(int(bruto[i]), len(novo) + 1)
    return np.array([novo[int(b)] for b in bruto]), k, silhuetas


def altura_de_corte(z: np.ndarray, k: int) -> float | None:
    """Altura entre a fusão que deixa k grupos e a seguinte (linha do dendrograma); ``None`` para k = 1 ou k = N."""
    n = z.shape[0] + 1
    if k <= 1 or k >= n:
        return None
    return float((z[n - k - 1, 2] + z[n - k, 2]) / 2.0)


# ---------- mapa 2D ----------

def mds_classico(dist: np.ndarray, dims: int = 2) -> tuple[np.ndarray, list[float]]:
    """Escalonamento multidimensional clássico (Torgerson), com sinal determinístico dos eixos."""
    n = dist.shape[0]
    coords = np.zeros((n, dims))
    if n < 2:
        return coords, [0.0] * dims
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ (dist ** 2) @ j
    b = (b + b.T) / 2.0
    valores, vetores = np.linalg.eigh(b)
    ordem = np.argsort(-valores, kind="stable")
    positivos = float(valores[valores > 0].sum()) or 1.0
    explicada = []
    for d in range(min(dims, n)):
        lam = float(valores[ordem[d]])
        vec = vetores[:, ordem[d]].copy()
        i_max = int(np.argmax(np.abs(vec)))  # argmax devolve o menor índice no empate
        if vec[i_max] < 0:
            vec = -vec
        coords[:, d] = vec * math.sqrt(max(lam, 0.0))
        explicada.append(max(lam, 0.0) / positivos)
    explicada += [0.0] * (dims - len(explicada))
    return coords, explicada


# ---------- análise completa ----------

def calcular(voc: dict, metas: list[dict], filtro, por: str = "lema", metodo: str = "ward", k: int | None = None,
             min_df: int = 2, max_df: float = 0.9, sublinear: bool = True, n_vizinhos: int = N_VIZINHOS,
             n_termos: int = N_TERMOS_GRUPO) -> dict:
    """Similaridade, agrupamento, mapa 2D, vizinhos e termos de cada grupo para os documentos ``metas``.

    ``voc``/``por``: vocabulário e unidade interna ("lema" ou "forma"; para termos compostos, a visão por termo lida
    como "lema"). Levanta ValueError (parâmetros inválidos, poucos documentos, vocabulário vazio)."""
    if metodo not in METODOS:
        raise ValueError(f"Método inválido '{metodo}': use 'average' ou 'ward'.")
    if por not in ("lema", "forma"):
        raise ValueError(f"Unidade inválida '{por}'.")
    if not 0 < max_df <= 1:
        raise ValueError("max_df deve estar entre 0 (exclusive) e 1.")
    if min_df < 1:
        raise ValueError("min_df deve ser >= 1.")
    if k is not None and k < 1:
        raise ValueError("k deve ser >= 1 (ou omitido para escolha automática).")
    mat, docs, termos, excluidos = matriz_contagens(voc, metas, filtro, por, min_df, max_df)
    n_antes = len(docs)
    vazios = mat.sum(axis=1) == 0
    if vazios.any():  # documentos sem nenhum termo após min_df/max_df
        for i in np.where(vazios)[0]:
            excluidos.append({"id": docs[i]["id"], "rotulo": docs[i]["rotulo"], "motivo": "nenhum termo passa em min_df/max_df"})
        mat = mat[~vazios]
        docs = [d for d, e in zip(docs, vazios) if not e]
    n = len(docs)
    if n < 2:
        raise ValueError("São necessários ao menos 2 documentos com texto para comparar (após os filtros).")
    # idf com N = documentos com algum termo antes do segundo corte (ver docstring)
    x = tfidf(mat, sublinear, n_antes)
    sim = cosseno(x)
    dist = 1.0 - sim
    np.fill_diagonal(dist, 0.0)
    z = ligar(x, dist, metodo)
    rotulos, k_usado, silhuetas = cortar(z, dist, k)
    ordem = [int(i) for i in hierarchy.leaves_list(z)]
    coords, explicada = mds_classico(dist)
    ordem_n = np.argsort(-sim, axis=1, kind="stable")

    media_geral = x.mean(axis=0)
    grupos = []
    for g in range(1, k_usado + 1):
        idx = np.where(rotulos == g)[0]
        media_g = x[idx].mean(axis=0)
        dif = media_g - media_geral
        ranque = sorted(range(len(termos)), key=lambda j: (-dif[j], termos[j]))[:n_termos]
        grupos.append({
            "cluster": g, "documentos": int(len(idx)), "ids": [docs[i]["id"] for i in idx],
            "termos": [{"termo": termos[j], "diferenca": round(float(dif[j]), 5), "media_grupo": round(float(media_g[j]), 5),
                        "media_corpus": round(float(media_geral[j]), 5),
                        "docs_no_grupo": int((mat[idx, j] > 0).sum())} for j in ranque if dif[j] > 0],
        })

    documentos = []
    for i, m in enumerate(docs):
        viz = [int(j) for j in ordem_n[i] if j != i][:n_vizinhos]
        documentos.append({
            "id": m["id"], "rotulo": m["rotulo"], "arquivo": m["arquivo"], "grupo": dados.chave_grupo(m),
            "ano": dados.chave_ano(m), "cluster": int(rotulos[i]),
            "x": round(float(coords[i, 0]), 6), "y": round(float(coords[i, 1]), 6),
            "n_termos": int((mat[i] > 0).sum()),
            "vizinhos": [{"id": docs[j]["id"], "rotulo": docs[j]["rotulo"], "similaridade": round(float(sim[i, j]), 4),
                          "cluster": int(rotulos[j])} for j in viz],
        })
    fusoes = [{"esquerda": int(a), "direita": int(b), "altura": round(float(h), 6), "tamanho": int(t)} for a, b, h, t in z]
    return {
        "unidade": por, "metodo": metodo,
        "n_documentos": n, "n_termos": len(termos), "excluidos": excluidos,
        "k": k_usado, "k_automatico": k is None, "silhuetas": silhuetas,
        "documentos": documentos, "grupos": grupos,
        "similaridade": [[round(float(v), 4) for v in linha] for linha in sim],
        "dendrograma": {"metodo": metodo, "ordem_folhas": ordem, "fusoes": fusoes, "altura_corte": altura_de_corte(z, k_usado)},
        "variancia_explicada": [round(e, 4) for e in explicada],
        "parametros": {"por": por, "metodo": metodo, "k": k, "min_df": min_df, "max_df": max_df, "sublinear": sublinear,
                       "vizinhos": n_vizinhos, "termos_por_grupo": n_termos},
        "metodologia": METODOLOGIA, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE, "nao_equivalente": NAO_EQUIVALENTE,
    }
