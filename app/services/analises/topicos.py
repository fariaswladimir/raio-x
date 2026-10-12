"""15.7 (fecha a 7.4) - Tópicos: LSA, NMF e LDA, com coerência (UMass, NPMI, C_v) e perplexidade.

Matriz documento × termo
------------------------
Unidades: ``documento`` (padrão) ou ``segmento`` (os segmentos de ~40 palavras da 4.4; melhores para corpora pequenos
ou de textos curtos). Tokens: os do corpo (``incluir`` = 1), lema por padrão, sem palavras vazias (4.2) e sem os
segmentos de ruído (3.4, se ``limpeza.excluir_ruido``), exatamente como na CHD (7.1). Termos com df >= ``min_df`` (2)
e df/N <= ``max_df`` (0,9), df contado nas unidades do modelo. Unidades que ficam sem termo saem (``excluidas``).

Modelos
-------
- **LSA** (Deerwester et al., 1990): SVD truncada da matriz TF-IDF (mesma convenção da 6.3: tf sublinear 1 + ln f,
  idf = ln((1 + N)/(1 + df)) + 1, norma L2 por unidade). Sinal determinístico: em cada componente, o termo de maior
  |carga| fica positivo. Componentes são bipolares: mostramos as palavras de carga positiva (e as negativas à parte);
  o "peso" de uma unidade é a coordenada U·S, não uma proporção.
- **NMF** (Lee & Seung, 1999, 2001): X ≈ W·H sobre a TF-IDF, atualizações multiplicativas para a norma de Frobenius,
  início NNDSVDa (Boutsidis & Gallopoulos, 2008: NNDSVD com os zeros trocados pela média de X, pois zeros não saem do
  lugar nas atualizações multiplicativas). Determinístico (SVD com vetor inicial fixo). Pesos dos tópicos = linhas de H
  normalizadas para somar 1; proporção da unidade = linha de W normalizada.
- **LDA** (Blei, Ng & Jordan, 2003) por amostragem de Gibbs colapsada (Griffiths & Steyvers, 2004), semente fixa,
  alfa = 50/K e beta = 0,01 (padrões de G&S; com unidade = segmento, alfa = 0,1, ver ``alfa_padrao``). Escolhida por transparência (contagens inteiras, sem otimização
  variacional). **Atualização em blocos:** os tokens são embaralhados uma vez (semente) e divididos em 64 blocos
  por varredura; dentro de um bloco cada token é amostrado com as contagens do início do bloco, descontada a própria
  atribuição (exatamente como no Gibbs sequencial), e as contagens são atualizadas no fim do bloco. É a amostragem
  paralela aproximada do AD-LDA (Newman et al., 2009), com defasagem de no máximo 1/64 dos tokens (~1,6%); com ``bloco=1`` é
  o Gibbs sequencial exato (lento em Python puro, por isso não é o padrão). Estimativas: phi = (n_kw + beta)/(n_k + V·beta)
  e theta = (n_dk + alfa)/(n_d + K·alfa), médias das amostras a cada ``intervalo`` (10) varreduras depois do
  aquecimento (``burn_in``, padrão = metade das iterações). Também se registra log p(w|z) (G&S, eq. 2) para ver a
  convergência.
- Tópicos de NMF e LDA são ordenados pela prevalência no corpus (soma das proporções ponderada pelo nº de tokens).

Coerência (top-10 palavras por tópico)
--------------------------------------
- **UMass** (Mimno et al., 2011): para as palavras em ordem decrescente de peso, média sobre os pares m > l de
  log((D(w_m, w_l) + 1)/D(w_l)), com D = nº de **unidades do modelo** (documentos ou segmentos) que contêm a(s)
  palavra(s). O artigo define a **soma** sobre os pares; aqui se divulga a média (soma / 45 com 10 palavras), que é a
  agregação do gensim e permite comparar tópicos com listas de tamanhos diferentes. O gensim usa epsilon = 1e-12 em
  probabilidade no lugar do +1 em contagem (``suavizacao`` reproduz os dois).
- **NPMI** (Bouma, 2009; Aletras & Stevenson, 2013) e **C_v** (Röder, Both & Hinneburg, 2015): probabilidades por
  **janela deslizante booleana de 110 tokens** sobre o corpus de referência = o próprio corpus do projeto, na mesma
  sequência de tokens do modelo (lemas plenos, sem vazias e sem ruído), como no Palmetto/gensim para o C_v. Cada
  posição da janela é um "documento virtual"; documentos menores que a janela contam como uma janela.
  NPMI(wi, wj) = log((P(wi,wj) + e)/(P(wi)P(wj))) / -log(P(wi,wj) + e), e = 1e-12; coerência NPMI = média sobre os
  pares. C_v: vetor de contexto v(wi) = [NPMI(wi, wj)] para j nas top-N (inclui j = i, NPMI = 1); confirmação
  indireta = cosseno entre v(wi) e a soma dos vetores das top-N (segmentação "um contra o conjunto"); C_v = média.
  (O C_NPMI do Palmetto usa janela de 10; aqui a janela é a mesma do C_v, parâmetro ``janela``.)
  Conferência com o gensim 4.4 (fora do projeto): UMass idêntico (|dif| < 1e-15, com ``suavizacao`` = 1e-12·N);
  NPMI e C_v idênticos (|dif| < 1e-15) **dadas as mesmas contagens de janela**. As contagens diferem porque o
  acumulador do gensim, ao deslizar a janela, desmarca a palavra que sai pela borda mesmo se ela ainda ocorre dentro
  da janela; aqui a presença é exata (conferida por força bruta nos testes), como na definição de Röder et al.

Perplexidade (só LDA)
---------------------
Divisão por documento (semente fixa): 20% dos documentos (no mínimo 1) ficam de fora do treino; o vocabulário vem só
das unidades de treino. Para cada unidade de teste, "completamento de documento" (Wallach et al., 2009): tokens
alternados (posições pares) estimam theta por Gibbs com phi fixo (fold-in); os tokens das posições ímpares são
avaliados: perplexidade = exp(-soma log sum_k theta_dk·phi_kw / N_avaliados). NMF e LSA não são modelos
probabilísticos: sem perplexidade.

Tópicos × ano/grupo
-------------------
Proporção média dos documentos (cada documento com o mesmo peso) por ano e por grupo; com unidade = segmento, a
proporção do documento é a média das proporções dos segmentos ponderada pelos tokens. **São agregações descritivas,
não STM (Roberts et al., 2014) nem DTM (Blei & Lafferty, 2006):** os metadados não entram no modelo.
"""
import hashlib
import math
import threading
from collections import Counter, OrderedDict
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import svds
from scipy.special import gammaln

from app.services import parametros as parametros_do_projeto
from app.services import ruido, segmentacao
from app.services.analises import dados
from app.services.palavras_vazias import token_vazio

MODELOS = ("lda", "nmf", "lsa")
UNIDADES = ("documento", "segmento")
PADRAO = {"modelo": "lda", "k": 8, "unidade": "documento", "semente": 42, "iteracoes": 1000}
K_MAX = 40
N_PALAVRAS = 10
JANELA = 110
EPS_NPMI = 1e-12
BLOCOS_POR_VARREDURA = 64
MIN_TOKENS_TRECHO = 8
FERRAMENTA_EQUIVALENTE = "Voyant Topics (LDA); gensim/MALLET (LDA), scikit-learn (NMF, TruncatedSVD)"
NOTA_AGREGACAO = ("Tópicos × ano e × grupo são agregações descritivas das proporções por documento (média simples), não "
                  "STM nem DTM: ano e grupo não entram no modelo.")


# =====================================================================================================
# Corpus: unidades (documentos/segmentos) e sequências de tokens
# =====================================================================================================

class _Cache:
    def __init__(self, maximo: int):
        self.maximo, self._d, self._trava = maximo, OrderedDict(), threading.Lock()

    def obter(self, chave):
        with self._trava:
            v = self._d.get(chave)
            if v is not None:
                self._d.move_to_end(chave)
            return v

    def guardar(self, chave, valor):
        with self._trava:
            self._d[chave] = valor
            while len(self._d) > self.maximo:
                self._d.popitem(last=False)


_CORPUS = _Cache(4)
_RESULTADOS = _Cache(16)


def _marca(caminho: Path):
    try:
        e = caminho.stat()
        return e.st_mtime_ns, e.st_size
    except OSError:
        return None


def marcas_do_corpus(pasta: Path, metas: list[dict]) -> tuple:
    from app.services.etapas.linguistica import caminho_tokens
    return tuple((m["id"], _marca(caminho_tokens(pasta, m["id"])), _marca(segmentacao.caminho_segmentos(pasta, m["id"])),
                  ruido.marca_do_arquivo(pasta, m["id"])) for m in metas)


def _assinatura_filtro(filtro) -> str:
    return hashlib.sha256("\n".join(sorted(filtro)).encode("utf-8")).hexdigest()[:16]


def carregar_corpus(pasta: Path, metas: list[dict], filtro, por: str = "lema") -> dict:
    """Segmentos (com os termos plenos de cada um) e a sequência de termos plenos de cada documento.

    ``segmentos``: [{doc, seg, pagina, contagem: Counter}] na ordem do corpus; ``sequencias``: {doc: [termos]}
    (referência das janelas do NPMI/C_v); ``sem_segmentos``: documentos sem arquivo de segmentos compatível."""
    sem_ruido = ruido.excluir_ruido(parametros_do_projeto.carregar(pasta))
    chave = (str(pasta), por, _assinatura_filtro(filtro), marcas_do_corpus(pasta, metas), sem_ruido)
    em_cache = _CORPUS.obter(chave)
    if em_cache is not None:
        return em_cache
    campo = "lema" if por == "lema" else "norm"
    segmentos, sequencias, faltam = [], {}, []
    ruido_fora = 0
    for m in metas:
        tk = dados.carregar_tokens(pasta, m["id"])
        sg = segmentacao.ler_segmentos(pasta, m["id"])
        if tk is None or sg is None or sg.get("n") != tk["n"]:
            faltam.append(m["id"])
            continue
        fora = ruido.segmentos_de_ruido(pasta, m["id"]) if sem_ruido else {}
        locais = [Counter() for _ in sg["segmentos"]]
        seq: list[str] = []
        termos, normas, lemas, incl = tk[campo], tk["norm"], tk["lema"], tk["incluir"]
        for i, s in enumerate(sg["seg"]):
            if s < 0 or s in fora or not incl[i] or token_vazio(normas[i], lemas[i], filtro):
                continue
            locais[s][termos[i]] += 1
            seq.append(termos[i])
        sequencias[m["id"]] = seq
        for s, c in zip(sg["segmentos"], locais):
            if s["seg"] in fora:
                ruido_fora += 1
                continue
            segmentos.append({"doc": m["id"], "seg": s["seg"], "pagina": s["pagina"], "contagem": c})
    r = {"segmentos": segmentos, "sequencias": sequencias, "sem_segmentos": faltam, "segmentos_ruido": ruido_fora}
    _CORPUS.guardar(chave, r)
    return r


def unidades(corpus: dict, unidade: str) -> tuple[list[Counter], list[dict]]:
    """(contagens, descrição) das unidades: documentos (soma dos segmentos) ou segmentos."""
    if unidade == "segmento":
        return ([s["contagem"] for s in corpus["segmentos"]],
                [{"doc": s["doc"], "seg": s["seg"], "pagina": s["pagina"]} for s in corpus["segmentos"]])
    por_doc: dict[int, Counter] = {}
    for s in corpus["segmentos"]:
        por_doc.setdefault(s["doc"], Counter()).update(s["contagem"])
    ids = [d for d in corpus["sequencias"] if d in por_doc]
    return [por_doc[d] for d in ids], [{"doc": d, "seg": None, "pagina": None} for d in ids]


def matriz_dtm(contagens: list[Counter], min_df: int = 2, max_df: float = 0.9,
               vocab: list[str] | None = None) -> tuple[sp.csr_matrix, list[str]]:
    """Matriz unidade × termo (contagens inteiras). Sem ``vocab``: termos com df >= min_df e df/N <= max_df, em ordem
    alfabética (determinística). Com ``vocab``: projeta nas colunas dadas (termos fora dele são ignorados)."""
    n = len(contagens)
    if vocab is None:
        df = Counter()
        for c in contagens:
            df.update(c.keys())
        teto = max_df * n
        vocab = sorted(t for t, f in df.items() if f >= min_df and f <= teto)
    idx = {t: j for j, t in enumerate(vocab)}
    linhas, cols, vals = [], [], []
    for i, c in enumerate(contagens):
        for t, f in c.items():
            j = idx.get(t)
            if j is not None:
                linhas.append(i)
                cols.append(j)
                vals.append(f)
    X = sp.csr_matrix((np.asarray(vals, dtype=np.float64), (linhas, cols)), shape=(n, len(vocab)))
    X.sort_indices()
    return X, list(vocab)


def tfidf(X: sp.csr_matrix, idf: np.ndarray | None = None) -> tuple[sp.csr_matrix, np.ndarray]:
    """TF-IDF esparsa (convenção da 6.3): tf = 1 + ln f, idf = ln((1 + N)/(1 + df)) + 1, norma L2 por linha."""
    X = sp.csr_matrix(X, dtype=np.float64)
    if idf is None:
        df = np.asarray((X > 0).sum(axis=0)).ravel()
        idf = np.log((1.0 + X.shape[0]) / (1.0 + df)) + 1.0
    T = X.copy()
    T.data = 1.0 + np.log(T.data)
    T = sp.csr_matrix(T.multiply(idf[None, :]))
    normas = np.sqrt(np.asarray(T.multiply(T).sum(axis=1)).ravel())
    normas[normas == 0] = 1.0
    return sp.csr_matrix(sp.diags(1.0 / normas) @ T), idf


# =====================================================================================================
# SVD determinística, LSA e NMF
# =====================================================================================================

def svd_truncada(X, k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """k maiores valores singulares (ordem decrescente) com sinal fixo: em cada componente, o maior |Vt[j]| é positivo."""
    m, n = X.shape
    if k >= min(m, n) - 1 or m * n <= 4_000_000:
        U, S, Vt = np.linalg.svd(X.toarray() if sp.issparse(X) else np.asarray(X), full_matrices=False)
        U, S, Vt = U[:, :k], S[:k], Vt[:k]
    else:
        v0 = np.ones(min(m, n)) / math.sqrt(min(m, n))
        U, S, Vt = svds(sp.csr_matrix(X), k=k, v0=v0, which="LM")
        ordem = np.argsort(-S)
        U, S, Vt = U[:, ordem], S[ordem], Vt[ordem]
    sinais = np.sign(Vt[np.arange(len(S)), np.argmax(np.abs(Vt), axis=1)])
    sinais[sinais == 0] = 1.0
    return U * sinais, S, Vt * sinais[:, None]


def lsa(T: sp.csr_matrix, k: int) -> dict:
    """LSA: coordenadas das unidades (U·S), cargas dos termos (Vt) e valores singulares."""
    U, S, Vt = svd_truncada(T, k)
    return {"coordenadas": U * S, "cargas": Vt, "valores_singulares": S, "U": U}


def nndsvd(X, k: int, variante: str = "a") -> tuple[np.ndarray, np.ndarray]:
    """Início NNDSVD (Boutsidis & Gallopoulos, 2008); ``variante="a"`` troca os zeros pela média de X."""
    U, S, Vt = svd_truncada(X, k)
    W, H = np.zeros((X.shape[0], k)), np.zeros((k, X.shape[1]))
    W[:, 0] = math.sqrt(S[0]) * np.abs(U[:, 0])
    H[0, :] = math.sqrt(S[0]) * np.abs(Vt[0, :])
    for j in range(1, k):
        x, y = U[:, j], Vt[j, :]
        xp, xn, yp, yn = np.maximum(x, 0), np.maximum(-x, 0), np.maximum(y, 0), np.maximum(-y, 0)
        nxp, nyp, nxn, nyn = map(np.linalg.norm, (xp, yp, xn, yn))
        mp, mn = nxp * nyp, nxn * nyn
        if mp > mn:
            u, v, sigma = (xp / nxp if nxp else xp), (yp / nyp if nyp else yp), mp
        else:
            u, v, sigma = (xn / nxn if nxn else xn), (yn / nyn if nyn else yn), mn
        f = math.sqrt(S[j] * sigma)
        W[:, j], H[j, :] = f * u, f * v
    if variante == "a":
        media = X.sum() / (X.shape[0] * X.shape[1])
        W[W == 0] = media
        H[H == 0] = media
    return W, H


def nmf(X, k: int, iteracoes: int = 1000, tol: float = 1e-5) -> dict:
    """NMF (Frobenius) por atualizações multiplicativas de Lee & Seung, início NNDSVDa. Para quando a queda relativa
    do erro em 10 iterações fica abaixo de ``tol``."""
    X = sp.csr_matrix(X) if sp.issparse(X) else np.asarray(X, dtype=float)
    W, H = nndsvd(X, k, "a")
    eps = 1e-12
    norma2 = float(X.multiply(X).sum()) if sp.issparse(X) else float((X * X).sum())

    def erro():
        WtX = np.asarray((X.T @ W).T) if sp.issparse(X) else W.T @ X
        return max(0.0, norma2 - 2 * float((WtX * H).sum()) + float(((W.T @ W) * (H @ H.T)).sum()))

    e0 = anterior = erro()
    it = 0
    for it in range(1, iteracoes + 1):
        WtX = np.asarray((X.T @ W).T) if sp.issparse(X) else W.T @ X
        H *= WtX / (W.T @ W @ H + eps)
        XHt = np.asarray(X @ H.T)
        W *= XHt / (W @ (H @ H.T) + eps)
        if it % 10 == 0:
            e = erro()
            if (anterior - e) / max(e0, eps) < tol:
                break
            anterior = e
    return {"W": W, "H": H, "iteracoes": it, "erro_frobenius": math.sqrt(erro()), "norma_x": math.sqrt(norma2)}


# =====================================================================================================
# LDA por Gibbs colapsado (em blocos)
# =====================================================================================================

def _tokens(X: sp.csr_matrix) -> tuple[np.ndarray, np.ndarray]:
    X = sp.csr_matrix(X)
    cont = X.data.astype(np.int64)
    linhas = np.repeat(np.arange(X.shape[0]), np.diff(X.indptr))
    return np.repeat(linhas, cont), np.repeat(X.indices, cont)


def _tamanho_bloco(n: int, bloco: int | None) -> int:
    return max(1, int(bloco)) if bloco else max(1, math.ceil(n / BLOCOS_POR_VARREDURA))


def log_verossimilhanca(nkw: np.ndarray, beta: float) -> float:
    """log p(w|z) (Griffiths & Steyvers, 2004, eq. 2)."""
    K, V = nkw.shape
    return float(K * (gammaln(V * beta) - V * gammaln(beta)) + gammaln(nkw + beta).sum() - gammaln(nkw.sum(axis=1) + V * beta).sum())


def lda_gibbs(X: sp.csr_matrix, k: int, alpha: float | None = None, beta: float = 0.01, iteracoes: int = 1000,
              burn_in: int | None = None, intervalo: int = 10, semente: int = 42, bloco: int | None = None) -> dict:
    """LDA por Gibbs colapsado (ver docstring do módulo). Devolve phi (K × V), theta (D × K), traço de log p(w|z).

    Contagens em ``ndk`` (D × K) e ``nwk`` (V × K, linhas contíguas para a coleta por palavra). Para cada token do bloco,
    p_k ∝ (n_dk + alfa)(n_wk + beta)/(n_k + V·beta) com as contagens do início do bloco, e na coluna do tópico atual
    do token as três contagens descontam 1 (o próprio token), como no Gibbs sequencial."""
    X = sp.csr_matrix(X)
    D, V = X.shape
    alpha = 50.0 / k if alpha is None else float(alpha)
    burn_in = iteracoes // 2 if burn_in is None else int(burn_in)
    if not 0 <= burn_in < iteracoes:
        raise ValueError("burn_in deve estar entre 0 e iteracoes - 1.")
    rng = np.random.default_rng(semente)
    d_tok, w_tok = _tokens(X)
    n = len(w_tok)
    if n == 0:
        raise ValueError("Nenhum token na matriz.")
    ordem = rng.permutation(n)
    d_tok, w_tok = d_tok[ordem], w_tok[ordem]
    z = rng.integers(0, k, n)
    ndk = np.bincount(d_tok * k + z, minlength=D * k).reshape(D, k).astype(np.float64)
    nwk = np.bincount(w_tok * k + z, minlength=V * k).reshape(V, k).astype(np.float64)
    nk = nwk.sum(axis=0)
    b = _tamanho_bloco(n, bloco)
    vbeta = V * beta
    phi_soma, theta_soma, amostras = np.zeros((k, V)), np.zeros((D, k)), 0
    traco = []
    for it in range(1, iteracoes + 1):
        for ini in range(0, n, b):
            d, w, zv = d_tok[ini:ini + b], w_tok[ini:ini + b], z[ini:ini + b]
            r = np.arange(len(zv))
            a_, b_ = ndk[d], nwk[w]
            p = (a_ + alpha) * (b_ + beta) * (1.0 / (nk + vbeta))
            p[r, zv] = (a_[r, zv] - 1 + alpha) * (b_[r, zv] - 1 + beta) / (nk[zv] - 1 + vbeta)
            np.cumsum(p, axis=1, out=p)
            u = rng.random(len(zv)) * p[:, -1]
            novo = (p >= u[:, None]).argmax(axis=1)
            mudou = novo != zv
            if mudou.any():
                dm, wm, zo, zn = d[mudou], w[mudou], zv[mudou], novo[mudou]
                um = np.ones(len(zn))
                ndk += np.bincount(np.concatenate([dm * k + zn, dm * k + zo]), np.concatenate([um, -um]), D * k).reshape(D, k)
                nwk += np.bincount(np.concatenate([wm * k + zn, wm * k + zo]), np.concatenate([um, -um]), V * k).reshape(V, k)
                nk += np.bincount(zn, minlength=k) - np.bincount(zo, minlength=k)
                z[ini:ini + b] = novo
        if it % intervalo == 0 or it == iteracoes:
            traco.append({"iteracao": it, "log_p_w_z": round(log_verossimilhanca(nwk.T, beta), 3)})
        if it > burn_in and ((it - burn_in) % intervalo == 0 or it == iteracoes):
            phi_soma += ((nwk + beta) / (nk[None, :] + vbeta)).T
            theta_soma += (ndk + alpha) / (ndk.sum(axis=1, keepdims=True) + k * alpha)
            amostras += 1
    return {"phi": phi_soma / amostras, "theta": theta_soma / amostras, "alpha": alpha, "beta": beta,
            "iteracoes": iteracoes, "burn_in": burn_in, "intervalo": intervalo, "amostras": amostras, "bloco": b,
            "n_tokens": int(n), "traco": traco, "ndk": ndk, "nkw": nwk.T.copy()}


def lda_fold_in(X: sp.csr_matrix, phi: np.ndarray, alpha: float, iteracoes: int = 200, semente: int = 42,
                bloco: int | None = None) -> np.ndarray:
    """theta das unidades de X com phi fixo (Gibbs só sobre z; média das amostras da 2ª metade)."""
    X = sp.csr_matrix(X)
    D = X.shape[0]
    k = phi.shape[0]
    rng = np.random.default_rng(semente)
    d_tok, w_tok = _tokens(X)
    n = len(w_tok)
    if n == 0:
        return np.full((D, k), 1.0 / k)
    ordem = rng.permutation(n)
    d_tok, w_tok = d_tok[ordem], w_tok[ordem]
    z = rng.integers(0, k, n)
    ndk = np.bincount(d_tok * k + z, minlength=D * k).reshape(D, k).astype(np.float64)
    phiT = np.ascontiguousarray(phi.T)
    b = _tamanho_bloco(n, bloco)
    soma, amostras = np.zeros((D, k)), 0
    for it in range(1, iteracoes + 1):
        for ini in range(0, n, b):
            d, w, zv = d_tok[ini:ini + b], w_tok[ini:ini + b], z[ini:ini + b]
            r = np.arange(len(zv))
            a_ = ndk[d]
            p = (a_ + alpha) * phiT[w]
            p[r, zv] = (a_[r, zv] - 1 + alpha) * phiT[w, zv]
            np.cumsum(p, axis=1, out=p)
            u = rng.random(len(zv)) * p[:, -1]
            novo = (p >= u[:, None]).argmax(axis=1)
            mudou = novo != zv
            if mudou.any():
                dm, zo, zn = d[mudou], zv[mudou], novo[mudou]
                um = np.ones(len(zn))
                ndk += np.bincount(np.concatenate([dm * k + zn, dm * k + zo]), np.concatenate([um, -um]), D * k).reshape(D, k)
                z[ini:ini + b] = novo
        if it > iteracoes // 2:
            soma += (ndk + alpha) / (ndk.sum(axis=1, keepdims=True) + k * alpha)
            amostras += 1
    return soma / amostras


def _metades_alternadas(X: sp.csr_matrix) -> tuple[sp.csr_matrix, sp.csr_matrix]:
    """Divide os tokens de cada unidade em posições pares (observadas) e ímpares (avaliadas), na ordem das colunas."""
    X = sp.csr_matrix(X)
    d_tok, w_tok = _tokens(X)
    obs = np.zeros(len(w_tok), dtype=bool)
    # posição do token dentro da sua unidade
    inicio = np.concatenate([[0], np.cumsum(np.asarray(X.sum(axis=1)).ravel().astype(int))])
    pos = np.arange(len(w_tok)) - inicio[d_tok]
    obs[pos % 2 == 0] = True
    forma = X.shape

    def montar(m):
        return sp.csr_matrix((np.ones(m.sum()), (d_tok[m], w_tok[m])), shape=forma)

    return montar(obs), montar(~obs)


def perplexidade_lda(contagens: list[Counter], docs: list[int], k: int, min_df: int = 2, max_df: float = 0.9,
                     iteracoes: int = 1000, semente: int = 42, frac_teste: float = 0.2, beta: float = 0.01,
                     iteracoes_fold_in: int = 200, alpha: float | None = None) -> dict | None:
    """Perplexidade por documentos retidos + completamento de documento (ver docstring). ``docs`` = documento de cada
    unidade. None se houver menos de 3 documentos."""
    distintos = list(dict.fromkeys(docs))
    if len(distintos) < 3:
        return None
    rng = np.random.default_rng(semente)
    n_teste = max(1, int(round(frac_teste * len(distintos))))
    teste = set(np.asarray(distintos)[rng.permutation(len(distintos))[:n_teste]].tolist())
    treino_c = [c for c, d in zip(contagens, docs) if d not in teste]
    teste_c = [c for c, d in zip(contagens, docs) if d in teste]
    Xtr, vocab = matriz_dtm(treino_c, min_df, max_df)
    Xtr = Xtr[np.asarray(Xtr.sum(axis=1)).ravel() > 0]
    if Xtr.shape[0] < 2 or Xtr.shape[1] < k:
        return None
    modelo = lda_gibbs(Xtr, k, alpha=alpha, iteracoes=iteracoes, semente=semente, beta=beta)
    Xte, _ = matriz_dtm(teste_c, vocab=vocab)
    Xte = Xte[np.asarray(Xte.sum(axis=1)).ravel() > 1]
    if Xte.shape[0] == 0:
        return None
    obs, aval = _metades_alternadas(Xte)
    theta = lda_fold_in(obs, modelo["phi"], modelo["alpha"], iteracoes=iteracoes_fold_in, semente=semente)
    aval = sp.coo_matrix(aval)
    probs = np.einsum("ik,ki->i", theta[aval.row], modelo["phi"][:, aval.col])
    n_aval = float(aval.data.sum())
    ll = float((aval.data * np.log(probs)).sum())
    return {"valor": math.exp(-ll / n_aval), "log_verossimilhanca": ll, "tokens_avaliados": int(n_aval),
            "documentos_teste": len(teste), "documentos_treino": len(distintos) - len(teste),
            "metodo": "documentos retidos (20%) + completamento de documento (tokens alternados), phi do treino fixo"}


# =====================================================================================================
# Coerência
# =====================================================================================================

def umass(topos: list[list[int]], Xbin: sp.csr_matrix, suavizacao: float = 1.0) -> list[float]:
    """UMass (Mimno et al., 2011), média sobre os pares m > l de log((D(w_m, w_l) + s)/D(w_l)). ``topos``: índices das
    colunas de ``Xbin`` (unidades × termos, binária) em ordem decrescente de peso."""
    Xbin = sp.csr_matrix(Xbin)
    saida = []
    for ids in topos:
        sub = Xbin[:, ids]
        sub = (sub > 0).astype(np.float64)
        co = np.asarray((sub.T @ sub).todense())
        df = np.diag(co)
        termos = [math.log((co[m, l] + suavizacao) / df[l]) for m in range(1, len(ids)) for l in range(m)]
        saida.append(float(np.mean(termos)) if termos else float("nan"))
    return saida


def contagens_janela(sequencias: list[list[str]], palavras: list[str], janela: int = JANELA) -> tuple[int, np.ndarray, np.ndarray]:
    """Janela deslizante booleana: (nº de janelas, nº de janelas com cada palavra, nº de janelas com cada par)."""
    idx = {p: i for i, p in enumerate(palavras)}
    P = len(palavras)
    cont = np.zeros(P)
    conj = np.zeros((P, P))
    n_jan = 0
    for seq in sequencias:
        L = len(seq)
        if L == 0:
            continue
        nw = max(1, L - janela + 1)
        n_jan += nw
        pos: dict[int, list[int]] = {}
        for i, t in enumerate(seq):
            j = idx.get(t)
            if j is not None:
                pos.setdefault(j, []).append(i)
        if not pos:
            continue
        presentes = sorted(pos)
        M = np.zeros((len(presentes), nw), dtype=np.float32)
        for r, j in enumerate(presentes):
            if L <= janela:
                M[r, 0] = 1.0
                continue
            ind = np.zeros(L + 1)
            ind[np.asarray(pos[j]) + 1] = 1.0
            cs = np.cumsum(ind)
            M[r] = (cs[janela:janela + nw] - cs[0:nw]) > 0
        cont[presentes] += M.sum(axis=1)
        conj[np.ix_(presentes, presentes)] += (M @ M.T).astype(np.float64)
    return n_jan, cont, conj


def matriz_npmi(n_jan: int, cont: np.ndarray, conj: np.ndarray, eps: float = EPS_NPMI) -> np.ndarray:
    """NPMI entre todas as palavras (com o epsilon do Palmetto/gensim). Palavra ausente de todas as janelas: 0."""
    p = cont / n_jan
    pj = conj / n_jan
    with np.errstate(divide="ignore", invalid="ignore"):
        num = np.log((pj + eps) / np.outer(p, p))
        den = -np.log(pj + eps)
        m = num / den
    m[~np.isfinite(m)] = 0.0
    return m


def coerencia_npmi(N: np.ndarray) -> float:
    """Média do NPMI sobre os pares (i < j) das palavras do tópico (N = submatriz NPMI do tópico)."""
    n = N.shape[0]
    iu = np.triu_indices(n, 1)
    return float(N[iu].mean()) if n > 1 else float("nan")


def coerencia_cv(N: np.ndarray) -> float:
    """C_v (Röder et al., 2015): média do cosseno entre v(wi) e a soma dos vetores de contexto do tópico."""
    total = N.sum(axis=0)
    nt = np.linalg.norm(total)
    cos = [float(N[i] @ total / (np.linalg.norm(N[i]) * nt)) if np.linalg.norm(N[i]) and nt else 0.0 for i in range(N.shape[0])]
    return float(np.mean(cos))


def coerencias(topos_palavras: list[list[str]], vocab: list[str], Xbin: sp.csr_matrix, sequencias: list[list[str]],
               janela: int = JANELA) -> list[dict]:
    """UMass, NPMI e C_v de cada tópico (listas de palavras em ordem decrescente de peso)."""
    pos = {t: j for j, t in enumerate(vocab)}
    um = umass([[pos[t] for t in ps] for ps in topos_palavras], Xbin)
    todas = sorted({t for ps in topos_palavras for t in ps})
    n_jan, cont, conj = contagens_janela(sequencias, todas, janela)
    M = matriz_npmi(n_jan, cont, conj)
    ii = {t: i for i, t in enumerate(todas)}
    saida = []
    for ps, u in zip(topos_palavras, um):
        sel = [ii[t] for t in ps]
        sub = M[np.ix_(sel, sel)]
        saida.append({"umass": round(u, 4), "npmi": round(coerencia_npmi(sub), 4), "cv": round(coerencia_cv(sub), 4)})
    return saida


# =====================================================================================================
# Ajuste e montagem do resultado
# =====================================================================================================

def _validar(modelo: str, k: int, unidade: str, iteracoes: int):
    if modelo not in MODELOS:
        raise ValueError(f"Modelo inválido '{modelo}': use {', '.join(MODELOS)}.")
    if unidade not in UNIDADES:
        raise ValueError(f"Unidade inválida '{unidade}': use {', '.join(UNIDADES)}.")
    if not 2 <= k <= K_MAX:
        raise ValueError(f"k deve estar entre 2 e {K_MAX}.")
    if not 10 <= iteracoes <= 20000:
        raise ValueError("iteracoes deve estar entre 10 e 20000.")


def alfa_padrao(k: int, unidade: str) -> float:
    """50/K (Griffiths & Steyvers) para documentos; 0,1 para segmentos: com ~20-40 tokens por segmento, alfa·K = 50
    domina as contagens e achata as proporções (todos os tópicos perto de 1/K)."""
    return 0.1 if unidade == "segmento" else 50.0 / k


def ajustar(X: sp.csr_matrix, modelo: str, k: int, semente: int = 42, iteracoes: int = 1000, alpha: float | None = None) -> dict:
    """Ajusta o modelo e devolve ``pesos_termos`` (K × V, para ordenar palavras), ``proporcoes`` (D × K) e extras."""
    if modelo == "lda":
        m = lda_gibbs(X, k, alpha=alpha, iteracoes=iteracoes, semente=semente)
        prev = (m["theta"] * np.asarray(X.sum(axis=1))).sum(axis=0)
        ordem = np.argsort(-prev, kind="stable")
        return {"pesos_termos": m["phi"][ordem], "proporcoes": m["theta"][:, ordem], "prevalencia": prev[ordem] / prev.sum(),
                "extra": {"alpha": m["alpha"], "beta": m["beta"], "burn_in": m["burn_in"], "intervalo": m["intervalo"],
                          "amostras": m["amostras"], "bloco": m["bloco"], "n_tokens": m["n_tokens"], "traco": m["traco"]}}
    T, idf = tfidf(X)
    if modelo == "nmf":
        m = nmf(T, k, iteracoes=iteracoes)
        H = m["H"]
        Hn = H / np.maximum(H.sum(axis=1, keepdims=True), 1e-300)
        W = m["W"] * H.sum(axis=1)[None, :]  # escala de H passada para W: W·H inalterado
        prop = W / np.maximum(W.sum(axis=1, keepdims=True), 1e-300)
        prev = (prop * np.asarray(X.sum(axis=1))).sum(axis=0)
        ordem = np.argsort(-prev, kind="stable")
        return {"pesos_termos": Hn[ordem], "proporcoes": prop[:, ordem], "prevalencia": prev[ordem] / prev.sum(),
                "extra": {"iteracoes_usadas": m["iteracoes"], "erro_relativo": m["erro_frobenius"] / m["norma_x"], "idf": idf}}
    m = lsa(T, k)
    S = m["valores_singulares"]
    total = float(T.multiply(T).sum())
    return {"pesos_termos": m["cargas"], "proporcoes": m["coordenadas"], "prevalencia": (S ** 2) / total,
            "extra": {"valores_singulares": S, "idf": idf}}


def _top(pesos: np.ndarray, n: int, negativo: bool = False) -> np.ndarray:
    v = -pesos if negativo else pesos
    return np.lexsort((np.arange(len(v)), -v))[:n]


def _por_doc(prop: np.ndarray, info: list[dict], X: sp.csr_matrix) -> tuple[list[int], np.ndarray]:
    """Proporção por documento: a da unidade (documento) ou a média dos segmentos ponderada pelos tokens."""
    docs = list(dict.fromkeys(u["doc"] for u in info))
    if all(u["seg"] is None for u in info):
        return docs, prop
    pos = {d: i for i, d in enumerate(docs)}
    pesos = np.asarray(X.sum(axis=1)).ravel()
    acum = np.zeros((len(docs), prop.shape[1]))
    soma = np.zeros(len(docs))
    for u, linha, w in zip(info, prop, pesos):
        acum[pos[u["doc"]]] += w * linha
        soma[pos[u["doc"]]] += w
    return docs, acum / np.maximum(soma, 1e-300)[:, None]


def _agregar(docs: list[int], prop_doc: np.ndarray, metas_por_id: dict, chave) -> dict:
    partes = sorted({chave(metas_por_id[d]) for d in docs}, key=lambda x: (x == dados.SEM_ANO or x == dados.SEM_GRUPO, str(x)))
    matriz = []
    n = []
    for p in partes:
        sel = [i for i, d in enumerate(docs) if chave(metas_por_id[d]) == p]
        matriz.append(prop_doc[sel].mean(axis=0))
        n.append(len(sel))
    M = np.asarray(matriz).T if matriz else np.zeros((prop_doc.shape[1], 0))
    return {"partes": partes, "n_documentos": n, "matriz": [[round(float(x), 4) for x in linha] for linha in M]}


def _trechos(pasta: Path, corpus: dict, modelo: str, ajuste: dict, vocab: list[str], info: list[dict],
             docs: list[int], prop_doc: np.ndarray, metas_por_id: dict, por_topico: int = 3) -> list[list[dict]]:
    """Segmentos mais representativos de cada tópico (com página). LDA/NMF: média, nos tokens do segmento, da
    responsabilidade theta_dk·phi_kw / soma_j theta_dj·phi_jw; LSA: projeção da TF-IDF do segmento na componente."""
    segs = [s for s in corpus["segmentos"] if s["doc"] in metas_por_id]
    S, _ = matriz_dtm([s["contagem"] for s in segs], vocab=vocab)
    n_s = np.asarray(S.sum(axis=1)).ravel()
    ok = n_s >= MIN_TOKENS_TRECHO
    K = ajuste["pesos_termos"].shape[0]
    score = np.full((len(segs), K), -np.inf)
    if modelo == "lsa":
        T, _ = tfidf(S, ajuste["extra"]["idf"])
        score = np.asarray(T @ ajuste["pesos_termos"].T)
    else:
        phi = ajuste["pesos_termos"]
        if all(u["seg"] is not None for u in info):  # unidade = segmento: proporção do próprio segmento
            linha = {(u["doc"], u["seg"]): i for i, u in enumerate(info)}
            for i, s in enumerate(segs):
                j = linha.get((s["doc"], s["seg"]))
                if j is not None:
                    score[i] = ajuste["proporcoes"][j]
        else:
            pos_doc = {d: i for i, d in enumerate(docs)}
            por_doc: dict[int, list[int]] = {}
            for i, s in enumerate(segs):
                por_doc.setdefault(s["doc"], []).append(i)
            for d, linhas in por_doc.items():
                if d not in pos_doc:
                    continue
                M = prop_doc[pos_doc[d]][:, None] * phi
                M = M / np.maximum(M.sum(axis=0, keepdims=True), 1e-300)
                sub = S[linhas]
                score[linhas] = np.asarray(sub @ M.T) / np.maximum(n_s[linhas], 1)[:, None]
    score[~ok] = -np.inf
    saida = []
    for k in range(K):
        escolhidos, por_doc_n = [], Counter()
        for i in np.lexsort((np.arange(len(segs)), -score[:, k])):
            if not np.isfinite(score[i, k]) or len(escolhidos) >= por_topico:
                break
            s = segs[i]
            if por_doc_n[s["doc"]] >= 1:
                continue
            por_doc_n[s["doc"]] += 1
            escolhidos.append({"documento_id": s["doc"], "rotulo": metas_por_id[s["doc"]]["rotulo"], "pagina": s["pagina"],
                               "seg": s["seg"], "peso": round(float(score[i, k]), 4),
                               "texto": dados_texto(pasta, s["doc"], s["seg"])})
        saida.append(escolhidos)
    return saida


def dados_texto(pasta: Path, doc_id: int, seg: int, limite: int = 500) -> str:
    sg = segmentacao.ler_segmentos(pasta, doc_id)
    t = sg["segmentos"][seg]["texto"] if sg and 0 <= seg < len(sg["segmentos"]) else ""
    return t if len(t) <= limite else t[:limite].rsplit(" ", 1)[0] + " …"


def preparar(pasta: Path, metas: list[dict], filtro, unidade: str, min_df: int, max_df: float):
    corpus = carregar_corpus(pasta, metas, filtro)
    contagens, info = unidades(corpus, unidade)
    X, vocab = matriz_dtm(contagens, min_df, max_df)
    vivas = np.asarray(X.sum(axis=1)).ravel() > 0
    excluidas = [info[i]["doc"] for i in np.flatnonzero(~vivas)] if unidade == "documento" else []
    X = X[vivas]
    info = [u for u, v in zip(info, vivas) if v]
    contagens = [c for c, v in zip(contagens, vivas) if v]
    return corpus, contagens, info, X, vocab, excluidas


def _chave(pasta, metas, filtro, *resto):
    return (str(pasta), marcas_do_corpus(pasta, metas), dados.assinatura_metadados(metas), _assinatura_filtro(filtro),
            ruido.excluir_ruido(parametros_do_projeto.carregar(pasta)), *resto)


def assinatura(pasta: Path, metas: list[dict], filtro, modelo: str = "lda", k: int = 8, unidade: str = "documento",
               semente: int = 42, iteracoes: int = 1000, n_palavras: int = N_PALAVRAS, janela: int = JANELA,
               min_df: int = 2, max_df: float = 0.9, perplexidade: bool = False) -> str:
    """Hash do corpus (arquivos, metadados, filtro, ruído) e dos parâmetros: diz se um instantâneo ainda vale."""
    chave = _chave(pasta, metas, filtro, modelo, k, unidade, semente, iteracoes, n_palavras, janela, min_df, max_df, perplexidade)
    return hashlib.sha256(repr(chave).encode("utf-8")).hexdigest()


def guardar_em_cache(res: dict, pasta: Path, metas: list[dict], filtro) -> None:
    p = res["parametros"]
    chave = _chave(pasta, metas, filtro, p["modelo"], p["k"], p["unidade"], p["semente"], p["iteracoes"], p["n_palavras"],
                   p["janela"], p["min_df"], p["max_df"], res["perplexidade"] is not None)
    _RESULTADOS.guardar(chave, res)


def calcular(pasta: Path, metas: list[dict], filtro, modelo: str = "lda", k: int = 8, unidade: str = "documento",
             semente: int = 42, iteracoes: int = 1000, n_palavras: int = N_PALAVRAS, janela: int = JANELA,
             min_df: int = 2, max_df: float = 0.9, perplexidade: bool = False) -> dict:
    """Ajusta o modelo de tópicos no corpus e devolve tópicos, coerências, proporções e agregações (ver docstring)."""
    _validar(modelo, k, unidade, iteracoes)
    chave = _chave(pasta, metas, filtro, modelo, k, unidade, semente, iteracoes, n_palavras, janela, min_df, max_df, perplexidade)
    em_cache = _RESULTADOS.obter(chave)
    if em_cache is not None:
        return em_cache
    corpus, contagens, info, X, vocab, excluidas = preparar(pasta, metas, filtro, unidade, min_df, max_df)
    n_docs = len({u["doc"] for u in info})
    if X.shape[0] < 2 * k or X.shape[1] < 2 * k:
        raise ValueError(f"Corpus pequeno demais para {k} tópicos: {X.shape[0]} unidade(s) e {X.shape[1]} termo(s) depois "
                         f"do filtro (são precisas ao menos {2 * k} de cada). Use menos tópicos ou unidade = segmento.")
    aj = ajustar(X, modelo, k, semente, iteracoes, alfa_padrao(k, unidade))
    metas_por_id = {m["id"]: m for m in metas}
    topos_idx = [_top(aj["pesos_termos"][j], n_palavras) for j in range(k)]
    topos_palavras = [[vocab[i] for i in ids] for ids in topos_idx]
    sequencias = [corpus["sequencias"][d] for d in corpus["sequencias"]]
    coer = coerencias(topos_palavras, vocab, X, sequencias, janela)
    docs, prop_doc = _por_doc(aj["proporcoes"], info, X)
    trechos = _trechos(pasta, corpus, modelo, aj, vocab, info, docs, prop_doc, metas_por_id)
    topicos = []
    for j in range(k):
        pesos = aj["pesos_termos"][j]
        t = {"id": j + 1, "palavras": [{"termo": vocab[i], "peso": round(float(pesos[i]), 5)} for i in topos_idx[j]],
             "prevalencia": round(float(aj["prevalencia"][j]), 4), "coerencia": coer[j],
             "documentos": [{"id": docs[i], "rotulo": metas_por_id[docs[i]]["rotulo"], "peso": round(float(prop_doc[i, j]), 4)}
                            for i in np.lexsort((np.arange(len(docs)), -prop_doc[:, j]))[:5]],
             "trechos": trechos[j]}
        if modelo == "lsa":
            t["palavras_negativas"] = [{"termo": vocab[i], "peso": round(float(pesos[i]), 5)} for i in _top(pesos, n_palavras, True)]
        topicos.append(t)
    media = {m: round(float(np.mean([c[m] for c in coer])), 4) for m in ("umass", "npmi", "cv")}
    perp = None
    if perplexidade and modelo == "lda":
        perp = perplexidade_lda(contagens, [u["doc"] for u in info], k, min_df, max_df, iteracoes, semente,
                                    alpha=alfa_padrao(k, unidade))
    avisos = []
    if corpus["sem_segmentos"]:
        avisos.append(f"{len(corpus['sem_segmentos'])} documento(s) sem segmentos: execute o pipeline.")
    if excluidas:
        avisos.append(f"{len(excluidas)} documento(s) sem nenhum termo depois do filtro ficaram fora.")
    if unidade == "documento" and n_docs < 3 * k:
        avisos.append(f"Só {n_docs} documentos para {k} tópicos: considere unidade = segmento ou menos tópicos.")
    extra = {kk: v for kk, v in aj["extra"].items() if kk not in ("idf", "traco", "valores_singulares")}
    if modelo == "lsa":
        extra["valores_singulares"] = [round(float(s), 4) for s in aj["extra"]["valores_singulares"]]
    res = {
        "modelo": modelo, "k": k, "unidade": unidade, "semente": semente, "iteracoes": iteracoes,
        "parametros": {"modelo": modelo, "k": k, "unidade": unidade, "semente": semente, "iteracoes": iteracoes,
                       "n_palavras": n_palavras, "janela": janela, "min_df": min_df, "max_df": max_df, "por": "lema"},
        "n_unidades": int(X.shape[0]), "n_documentos": n_docs, "n_termos": int(X.shape[1]), "n_tokens": int(X.sum()),
        "topicos": topicos, "coerencia_media": media, "perplexidade": perp,
        "documentos": [{"id": d, "rotulo": metas_por_id[d]["rotulo"], "ano": metas_por_id[d]["ano"],
                        "grupo": metas_por_id[d]["grupo"], "pesos": [round(float(x), 4) for x in prop_doc[i]]}
                       for i, d in enumerate(docs)],
        "por_ano": _agregar(docs, prop_doc, metas_por_id, dados.chave_ano),
        "por_grupo": _agregar(docs, prop_doc, metas_por_id, dados.chave_grupo),
        "convergencia": aj["extra"].get("traco"), "ajuste": extra,
        "pesos_sao_proporcoes": modelo != "lsa",
        "nota_agregacao": NOTA_AGREGACAO, "avisos": avisos, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE,
        "assinatura": hashlib.sha256(repr(chave).encode("utf-8")).hexdigest(),
    }
    _RESULTADOS.guardar(chave, res)
    return res


def varredura(pasta: Path, metas: list[dict], filtro, modelo: str = "lda", k_min: int = 3, k_max: int = 12,
              unidade: str = "documento", semente: int = 42, iteracoes: int = 300, janela: int = JANELA,
              min_df: int = 2, max_df: float = 0.9, perplexidade: bool = True) -> dict:
    """Varredura de K: coerência média (UMass, NPMI, C_v) e, no LDA, perplexidade em documentos retidos."""
    if not 2 <= k_min <= k_max <= K_MAX or k_max - k_min > 20:
        raise ValueError(f"Use 2 <= k_min <= k_max <= {K_MAX}, com no máximo 21 valores de K.")
    _validar(modelo, k_min, unidade, iteracoes)
    chave = _chave(pasta, metas, filtro, "varredura", modelo, k_min, k_max, unidade, semente, iteracoes, janela, min_df, max_df, perplexidade)
    em_cache = _RESULTADOS.obter(chave)
    if em_cache is not None:
        return em_cache
    corpus, contagens, info, X, vocab, _ = preparar(pasta, metas, filtro, unidade, min_df, max_df)
    sequencias = [corpus["sequencias"][d] for d in corpus["sequencias"]]
    linhas = []
    for k in range(k_min, k_max + 1):
        if X.shape[0] < 2 * k or X.shape[1] < 2 * k:
            linhas.append({"k": k, "umass": None, "npmi": None, "cv": None, "perplexidade": None, "mensagem": "corpus pequeno demais"})
            continue
        aj = ajustar(X, modelo, k, semente, iteracoes, alfa_padrao(k, unidade))
        topos = [[vocab[i] for i in _top(aj["pesos_termos"][j], N_PALAVRAS)] for j in range(k)]
        coer = coerencias(topos, vocab, X, sequencias, janela)
        perp = None
        if perplexidade and modelo == "lda":
            perp = perplexidade_lda(contagens, [u["doc"] for u in info], k, min_df, max_df, iteracoes, semente,
                                    alpha=alfa_padrao(k, unidade))
        linhas.append({"k": k, **{m: round(float(np.mean([c[m] for c in coer])), 4) for m in ("umass", "npmi", "cv")},
                       "perplexidade": round(perp["valor"], 2) if perp else None})
    res = {"modelo": modelo, "unidade": unidade, "semente": semente, "iteracoes": iteracoes, "janela": janela,
           "k_min": k_min, "k_max": k_max, "n_unidades": int(X.shape[0]), "n_termos": int(X.shape[1]), "linhas": linhas,
           "nota": ("Coerência: maior é melhor (UMass é negativa; mais perto de 0 é melhor). Perplexidade (só LDA): menor é "
                    "melhor, em documentos retidos. Nenhuma métrica escolhe K sozinha: leia os tópicos.")}
    _RESULTADOS.guardar(chave, res)
    return res
