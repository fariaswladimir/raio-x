"""7.1 - Classificação hierárquica descendente (CHD) pelo método de Reinert, como no IRaMuTeQ e no ALCESTE.

Equivale à CHD do IRaMuTeQ (Ratinaud 2009; Camargo & Justo 2013) e do ALCESTE (Reinert 1983, 1990). **Não** é o
agrupamento hierárquico aglomerativo de palavras do KH Coder nem um modelo de tópicos (LDA): aqui se dividem
*segmentos de texto* (de cima para baixo), e cada classe é descrita depois pelo qui-quadrado das palavras.

Unidades e formas ativas
------------------------
- Unidade = segmento de texto (ST, ~40 palavras, 4.4; ``cache/segmentos/<id>.json``).
- Formas ativas = lemas (D5) dos tokens do corpo (``incluir``), com >= 2 letras e **fora das palavras vazias** (só
  palavras "plenas"; não há etiquetagem morfológica, então a lista de palavras vazias faz o papel do filtro de
  classes gramaticais do IRaMuTeQ), com frequência no corpus >= ``min_freq`` (3, contando ocorrências).
- Tabela binária ST × forma (presença/ausência). ST sem nenhuma forma ativa não são classificáveis.
- **Classes gramaticais (4.5, opcional)**: com ``reinert.formas_ativas = "classes"`` em parametros.json (padrão ``"todas"``) só entram
  as formas cuja classe gramatical (spaCy, ``cache/spacy``) está em ``reinert.classes_ativas`` (padrão ``plenas`` = substantivos, nomes
  próprios, adjetivos e verbos, como as formas ativas do IRaMuTeQ); documentos sem etiquetagem ficam sem filtro e são avisados.

Uma bipartição (Reinert 1983)
-----------------------------
Dada a classe a dividir (linhas) e as formas presentes nela (colunas com soma > 0):

1. **Eixo 1 da AFC** da tabela binária da classe (núcleo de ``afc.py``; acima de ``LIMITE_DENSO`` células usa-se o
   mesmo cálculo só para o 1º par singular, por ``scipy.sparse.linalg.svds`` com operador linear e vetor inicial fixo).
   Sinal: a forma de maior |coordenada| fica positiva (mesma convenção da 7.3).
2. **Corte**: ordenam-se os ST pela coordenada no eixo 1 (empate: índice do ST) e, para cada ponto de corte k,
   forma-se a tabela 2 × p (soma das presenças de cada forma em cada grupo). Escolhe-se o k de maior χ² dessa tabela
   (empate: o menor k). Com a_j, b_j = presenças da forma j nos grupos A e B, t_j = a_j + b_j, N_A, N_B = totais de
   presenças e n = N_A + N_B:  χ² = Σ_j (a_j·N_B − b_j·N_A)² / (t_j·N_A·N_B) = n·(n·S − N_A²) / (N_A·N_B), com
   S = Σ_j a_j² / t_j (identidade usada para atualizar o χ² em O(formas do ST) a cada ST movido).
3. **Realocação** (troca do ALCESTE/IRaMuTeQ, aqui documentada como varredura gulosa): no início de cada varredura
   calcula-se (vetorizado) o χ² que resultaria de trocar cada ST isoladamente de grupo; os ST cuja troca aumentaria o
   χ² são então testados em ordem de índice, **no estado corrente**, e trocados se o χ² aumentar (nenhum grupo pode
   ficar vazio). Repete-se até uma varredura sem candidatos (ótimo local exato: nenhuma troca isolada melhora) ou
   ``max_iter`` (50) varreduras. Como só se aceita troca que aumenta o critério, o χ² nunca diminui (o histórico vai
   na resposta).
4. Filhos: o 1º filho é o grupo de menor coordenada média no eixo 1 (determinístico).

Classificação (simples, o padrão do IRaMuTeQ)
---------------------------------------------
Começa com todos os ST classificáveis numa classe e **divide sempre a maior classe terminal** (em nº de ST; empate:
a criada antes) até haver ``classes`` classes terminais (10, como a "fase 1" do IRaMuTeQ) ou nenhuma divisível.
Uma classe só é dividida se tiver >= 2 × ``min_classe`` ST, >= 2 formas e inércia > 0. No fim, folhas com menos de
``min_classe`` ST são **descartadas** e seus ST ficam não classificados. ``min_classe`` = 0 escolhe automaticamente
max(5, ⌈2,5% dos ST classificáveis⌉) (escolha do Raio-X; o IRaMuTeQ também tem um mínimo automático).
Classes finais numeradas 1..K na ordem das folhas do dendrograma (da esquerda para a direita).

Classificação dupla (opção; "classification double" do IRaMuTeQ/ALCESTE)
------------------------------------------------------------------------
Os ST de cada documento são agrupados, em ordem, em **unidades de contexto (UC)** de dois tamanhos (``tamanhos`` em
palavras, padrão 40 e 60): soma-se o próximo ST enquanto isso deixa o total de palavras mais perto do alvo (pelo
menos 1 ST por UC). Faz-se a CHD (como acima) em cada tabela UC × forma (presença na UC) e cada ST herda a classe de
sua UC. Cruzam-se as duas classificações: para cada par (classe i da 1ª, classe j da 2ª), n_ij = ST nas duas e o χ²
2 × 2 (ST em i? × ST em j?) entre os ST classificados nas duas. São **classes estáveis** os pares com associação
positiva, χ² >= 3,84 e n_ij >= ``min_classe``, escolhidos de forma gulosa por χ² decrescente sem repetir classe de
nenhum dos lados. Só os ST da interseção de um par estável ficam classificados (a retenção cai, como no IRaMuTeQ).

Descrição das classes
---------------------
Sobre os ST classificados (N): para a forma f e a classe k, tabela 2 × 2 (ST da classe com f, ST de fora com f, ...),
χ² de Pearson sem correção de continuidade, com sinal (+ se a frequência na classe passa da esperada), p de 1 g.l.
(``scipy.stats.chi2.sf``). Forma característica: χ² >= 3,84 (p < 0,05) e positiva. O mesmo para as variáveis
suplementares (documento, grupo, ano), tratadas como "formas" de cada ST. ST típicos de uma classe = soma dos χ² das
formas características da classe presentes no ST (como os "segmentos de texto característicos" do IRaMuTeQ).
AFC classe × forma: tabela "nº de ST da classe com a forma" das formas características (até 30 por classe), pelo
núcleo da 7.3.

Determinismo: sem aleatoriedade; ordem dos ST = ordem do corpus (arquivo) e dos segmentos; empates resolvidos por
índice. A mesma entrada dá as mesmas classes.
"""
import hashlib
import math
import threading
from collections import Counter, OrderedDict
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import LinearOperator, svds
from scipy.stats import chi2 as dist_chi2

from app.services import parametros as parametros_do_projeto
from app.services import ruido, segmentacao, spacy_nlp
from app.services.analises import afc, dados
from app.services.palavras_vazias import token_vazio

FERRAMENTA_EQUIVALENTE = "IRaMuTeQ CHD (método Reinert), ALCESTE"
NAO_EQUIVALENTE = "agrupamento hierárquico aglomerativo de palavras (KH Coder) nem tópicos (LDA)"
METODOLOGIA = (
    "Classificação hierárquica descendente de Reinert (1983, 1990) sobre a tabela binária segmento de texto × forma "
    "ativa (lemas fora das palavras vazias, frequência >= min_freq): divide-se sempre a maior classe; corte no eixo 1 da "
    "AFC da classe que maximiza o χ² da tabela 2 × formas, seguido de realocação gulosa dos segmentos enquanto o χ² "
    "aumenta; folhas menores que o mínimo são descartadas (segmentos não classificados). Classes descritas pelo χ² 2 × 2 "
    "(sem correção) de formas e variáveis (documento, grupo, ano)."
)
CHI2_CRITICO = 3.841458820694124  # p = 0,05 com 1 g.l.
LIMITE_DENSO = 250_000  # células: até aqui a AFC completa de afc.py; acima, só o 1º par singular (svds)
MAX_ITER = 50
MULT_DIVISOES = 5  # teto de bipartições = 5 × classes (as que só isolam ST atípicos não contam como classe)
MAX_FORMAS = 3000  # formas ativas mais frequentes (como o "nombre maximum de formes analysées" do IRaMuTeQ)
RETENCAO_MINIMA = 75.0
PADRAO = {"classes": 10, "min_freq": 3, "dupla": False, "tamanhos": [40, 60], "min_classe": 0, "max_formas": MAX_FORMAS}
CLASSES_MAX = 30
VARIAVEIS = ("documento", "grupo", "ano")


# =====================================================================================================
# Estatística (funções puras sobre matrizes binárias CSR)
# =====================================================================================================

def binaria(X) -> sp.csr_matrix:
    """CSR float com 1 onde X > 0 (presença), índices ordenados."""
    M = sp.csr_matrix(X, dtype=float, copy=True)
    M.data[:] = 1.0
    M.eliminate_zeros()
    M.sort_indices()
    return M


def chi2_tabela_2xp(a, b) -> float:
    """χ² de Pearson da tabela 2 × p (linhas a e b), pela fórmula direta (colunas nulas ignoradas)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    t = a + b
    ok = t > 0
    a, b, t = a[ok], b[ok], t[ok]
    NA, NB = a.sum(), b.sum()
    if NA <= 0 or NB <= 0:
        return 0.0
    return float(np.sum((a * NB - b * NA) ** 2 / t) / (NA * NB))


def chi2_da_particao(X: sp.csr_matrix, grupo_a) -> float:
    """χ² da tabela 2 × formas (soma das presenças de cada forma nos ST do grupo A e do grupo B)."""
    g = np.asarray(grupo_a, dtype=bool)
    a = np.asarray(X[g].sum(axis=0)).ravel()
    b = np.asarray(X[~g].sum(axis=0)).ravel()
    return chi2_tabela_2xp(a, b)


def primeiro_fator(X: sp.csr_matrix, denso: bool | None = None) -> tuple[np.ndarray | None, float]:
    """Coordenadas principais das linhas no eixo 1 da AFC de X e o autovalor λ1 (None, 0 se não houver inércia).

    ``denso`` força o caminho (None = automático por ``LIMITE_DENSO``). Os dois caminhos usam a mesma convenção
    de sinal de ``afc.analise_de_correspondencia`` (a coluna de maior |coordenada| positiva)."""
    X = X[:, np.flatnonzero(np.asarray(X.sum(axis=0)).ravel() > 0)]  # formas ausentes não entram na AFC
    I, J = X.shape
    if I < 2 or J < 2:
        return None, 0.0
    if denso is None:
        denso = I * J <= LIMITE_DENSO
    if denso:
        ac = afc.analise_de_correspondencia(X.toarray(), eixos=1)
        if ac["k"] < 1:
            return None, 0.0
        return ac["F"][:, 0].copy(), float(ac["autovalores"][0])
    n = float(X.sum())
    r = np.asarray(X.sum(axis=1)).ravel() / n
    c = np.asarray(X.sum(axis=0)).ravel() / n
    sr, sc = np.sqrt(r), np.sqrt(c)
    Xs = (sp.diags(1.0 / sr) @ (X / n) @ sp.diags(1.0 / sc)).tocsr()
    XsT = Xs.T.tocsr()

    def mv(v):
        v = np.ravel(v)
        return Xs @ v - sr * (sc @ v)

    def rmv(u):
        u = np.ravel(u)
        return XsT @ u - sc * (sr @ u)

    op = LinearOperator((I, J), matvec=mv, rmatvec=rmv, dtype=float)
    m = min(I, J)
    v0 = 1.0 + np.arange(m, dtype=float) % 7 / 7.0  # vetor inicial fixo (determinismo do ARPACK)
    u, s, vt = svds(op, k=1, v0=v0 / np.linalg.norm(v0), which="LM", tol=1e-10, maxiter=5000)
    lam = float(s[0]) ** 2
    if lam < afc.EPS_AUTOVALOR:
        return None, 0.0
    F = u[:, 0] * s[0] / sr
    G = vt[0] * s[0] / sc
    j = int(np.argmax(np.abs(G)))
    if G[j] < 0:
        F = -F
    return F, lam


def _chi2_de_S(S: float, NA: float, n: float) -> float:
    NB = n - NA
    if NA <= 0 or NB <= 0:
        return 0.0
    return n * (n * S - NA * NA) / (NA * NB)


def melhor_corte(X: sp.csr_matrix, coords: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """Corte de maior χ² ao longo da ordem das coordenadas: (máscara do grupo A, χ², χ² de cada corte k = 1..I−1)."""
    I = X.shape[0]
    ordem = np.lexsort((np.arange(I), np.asarray(coords)))
    t = np.asarray(X.sum(axis=0)).ravel()
    n = float(t.sum())
    t = np.where(t > 0, t, 1.0)  # colunas vazias: a_j = 0, termo nulo
    m = np.diff(X.indptr).astype(float)
    # Ao entrar a linha k (na ordem), cada forma j dela soma (2·a_j + 1)/t_j a S, com a_j = nº de linhas anteriores
    # com j = posição do não nulo dentro da coluna j da matriz reordenada (CSC com índices ordenados).
    Xo = X[ordem].tocsc()
    Xo.sort_indices()
    cp = Xo.indptr
    col_nz = np.repeat(np.arange(X.shape[1]), np.diff(cp))
    pos = np.arange(Xo.nnz) - cp[:-1][col_nz]
    dS = np.bincount(Xo.indices, weights=(2.0 * pos + 1.0) / t[col_nz], minlength=I)
    S = np.cumsum(dS)[:-1]
    NA = np.cumsum(m[ordem])[:-1]
    NB = n - NA
    with np.errstate(divide="ignore", invalid="ignore"):
        chis = np.where((NA > 0) & (NB > 0), n * (n * S - NA * NA) / (NA * NB), 0.0)
    kmax = int(np.argmax(chis))  # primeiro máximo = menor k
    mask = np.zeros(I, dtype=bool)
    mask[ordem[:kmax + 1]] = True
    return mask, float(chis[kmax]), chis


def realocar(X: sp.csr_matrix, grupo_a: np.ndarray, max_iter: int = MAX_ITER) -> tuple[np.ndarray, list[float], int]:
    """Realocação gulosa (ver docstring do módulo): (máscara final, histórico do χ² por varredura, ST movidos)."""
    g = np.array(grupo_a, dtype=bool)
    I = X.shape[0]
    t = np.asarray(X.sum(axis=0)).ravel()
    n = float(t.sum())
    t = np.where(t > 0, t, 1.0)  # colunas vazias: a_j = 0, termo nulo
    m = np.diff(X.indptr).astype(float)
    ind, ptr = X.indices, X.indptr
    a = np.asarray(X[g].sum(axis=0)).ravel()
    S = float(np.sum(a * a / t))
    NA = float(m[g].sum())
    na_linhas = int(g.sum())
    chi = _chi2_de_S(S, NA, n)
    historico = [chi]
    movidos = 0
    inv_t = 1.0 / t
    for _ in range(max_iter):
        mudou = 0
        # Ganho exato de cada troca isolada no estado do início da varredura (vetorizado); só esses ST são testados,
        # um a um e no estado corrente. Uma varredura sem candidatos = ótimo local exato (nenhuma troca melhora).
        q = X @ (a * inv_t)
        u = X @ inv_t
        S2v = np.where(g, S - (2.0 * q - u), S + (2.0 * q + u))
        NA2v = np.where(g, NA - m, NA + m)
        NB2v = n - NA2v
        with np.errstate(divide="ignore", invalid="ignore"):
            chiv = np.where((NA2v > 0) & (NB2v > 0), n * (n * S2v - NA2v ** 2) / (NA2v * NB2v), -np.inf)
        candidatos = np.flatnonzero(chiv > chi + 1e-9 * max(1.0, chi))
        if len(candidatos) == 0:
            break
        for i in candidatos:
            cols = ind[ptr[i]:ptr[i + 1]]
            if g[i]:
                if na_linhas <= 1:
                    continue
                S2 = S - float(np.sum((2.0 * a[cols] - 1.0) / t[cols]))
                NA2 = NA - m[i]
            else:
                if I - na_linhas <= 1:
                    continue
                S2 = S + float(np.sum((2.0 * a[cols] + 1.0) / t[cols]))
                NA2 = NA + m[i]
            chi2n = _chi2_de_S(S2, NA2, n)
            if chi2n > chi + 1e-9 * max(1.0, chi):
                if g[i]:
                    a[cols] -= 1.0
                    na_linhas -= 1
                else:
                    a[cols] += 1.0
                    na_linhas += 1
                g[i] = not g[i]
                S, NA, chi = S2, NA2, chi2n
                mudou += 1
        # recalcula exatamente (evita acúmulo de erro de arredondamento nas atualizações incrementais)
        S = float(np.sum(a * a / t))
        chi = _chi2_de_S(S, NA, n)
        historico.append(chi)
        movidos += mudou
        if mudou == 0:
            break
    return g, historico, movidos


def bipartir(X: sp.csr_matrix, max_iter: int = MAX_ITER, denso: bool | None = None) -> dict | None:
    """Uma bipartição de Reinert de X (linhas = unidades). None se não houver como dividir.

    Devolve ``grupos`` (2 arrays de índices locais, 1º = menor coordenada média), ``chi2_corte`` (antes da
    realocação), ``chi2`` (final), ``historico``, ``movidos``, ``lambda1``."""
    cols = np.flatnonzero(np.asarray(X.sum(axis=0)).ravel() > 0)
    if X.shape[0] < 2 or len(cols) < 2:
        return None
    Xc = X[:, cols]
    coords, lam = primeiro_fator(Xc, denso)
    if coords is None:
        return None
    mask0, chi_corte, _ = melhor_corte(Xc, coords)
    mask, hist, movidos = realocar(Xc, mask0, max_iter)
    a_idx, b_idx = np.flatnonzero(mask), np.flatnonzero(~mask)
    if len(a_idx) == 0 or len(b_idx) == 0:
        return None
    if coords[b_idx].mean() < coords[a_idx].mean() or (
            coords[b_idx].mean() == coords[a_idx].mean() and b_idx[0] < a_idx[0]):
        a_idx, b_idx = b_idx, a_idx
    return {"grupos": [a_idx, b_idx], "chi2_corte": chi_corte, "chi2": hist[-1], "historico": hist,
            "movidos": movidos, "lambda1": lam}


def min_classe_automatico(n: int) -> int:
    return max(5, math.ceil(0.025 * n))


def chd(X: sp.csr_matrix, classes: int = 10, min_classe: int = 0, max_iter: int = MAX_ITER,
        denso: bool | None = None) -> dict:
    """CHD descendente sobre as linhas de X. Devolve ``nos`` (dendrograma), ``classe`` (por linha, 1..K, 0 = não
    classificada), ``k`` e ``min_classe`` usado. Ver docstring do módulo."""
    X = binaria(X)
    I = X.shape[0]
    minc = int(min_classe) if min_classe and min_classe > 0 else min_classe_automatico(I)
    nos = [{"id": 0, "pai": None, "filhos": [], "linhas": np.arange(I), "divisivel": True}]
    folhas = [0]  # folhas válidas (>= min_classe ou a raiz); as pequenas ficam fora e são descartadas no fim
    divisoes = 0
    while len(folhas) < classes and divisoes < max(1, MULT_DIVISOES * classes):
        candidatas = [f for f in folhas if nos[f]["divisivel"] and len(nos[f]["linhas"]) >= max(2, 2 * minc)]
        if not candidatas:
            break
        alvo = max(candidatas, key=lambda f: (len(nos[f]["linhas"]), -f))
        linhas = nos[alvo]["linhas"]
        b = bipartir(X[linhas], max_iter, denso)
        if b is None:
            nos[alvo]["divisivel"] = False
            continue
        divisoes += 1
        nos[alvo].update({"chi2": b["chi2"], "chi2_corte": b["chi2_corte"], "historico": b["historico"],
                          "movidos": b["movidos"], "lambda1": b["lambda1"]})
        folhas.remove(alvo)
        for grupo in b["grupos"]:
            novo = {"id": len(nos), "pai": alvo, "filhos": [], "linhas": linhas[grupo], "divisivel": True}
            nos.append(novo)
            nos[alvo]["filhos"].append(novo["id"])
            if len(novo["linhas"]) >= minc:
                folhas.append(novo["id"])
    # folhas na ordem do dendrograma (busca em profundidade, 1º filho antes)
    ordem_folhas, pilha = [], [0]
    while pilha:
        no = nos[pilha.pop()]
        if no["filhos"]:
            pilha.extend(reversed(no["filhos"]))
        else:
            ordem_folhas.append(no["id"])
    classe = np.zeros(I, dtype=int)
    k = 0
    for f in ordem_folhas:
        no = nos[f]
        if len(no["linhas"]) >= minc:
            k += 1
            no["classe"] = k
            classe[no["linhas"]] = k
        else:
            no["classe"] = None
            no["descartada"] = True
    return {"nos": nos, "classe": classe, "k": k, "min_classe": minc}


def nos_publicos(nos: list[dict]) -> list[dict]:
    """Dendrograma serializável (sem as listas de linhas)."""
    saida = []
    for no in nos:
        saida.append({
            "id": no["id"], "pai": no["pai"], "filhos": list(no["filhos"]), "n": int(len(no["linhas"])),
            "folha": not no["filhos"], "classe": no.get("classe"), "descartada": bool(no.get("descartada", False)),
            **({"chi2": round(float(no["chi2"]), 4), "chi2_corte": round(float(no["chi2_corte"]), 4),
                "lambda1": round(float(no["lambda1"]), 6), "movidos": int(no["movidos"]),
                "varreduras": len(no["historico"]) - 1} if "chi2" in no else {}),
        })
    return saida


def chi2_2x2(a, n_linha, n_coluna, N):
    """χ² de Pearson 2 × 2 sem correção, com sinal (+ se a > esperado), vetorizado; e o p-valor (1 g.l.).

    a = ocorrências conjuntas; n_linha = total da linha (ex.: ST da classe); n_coluna = total da coluna (ST com a
    forma); N = total."""
    a, nl, nc = (np.asarray(x, dtype=float) for x in np.broadcast_arrays(a, n_linha, n_coluna))
    N = float(N)
    b, c = nc - a, nl - a
    d = N - nl - nc + a
    den = nl * (N - nl) * nc * (N - nc)
    with np.errstate(divide="ignore", invalid="ignore"):
        x2 = np.where(den > 0, N * (a * d - b * c) ** 2 / den, 0.0)
    sinal = np.where(a * N >= nl * nc, 1.0, -1.0)
    return sinal * x2, dist_chi2.sf(x2, 1)


def cruzar(classe_a: np.ndarray, classe_b: np.ndarray, min_classe: int) -> dict:
    """Classes estáveis da classificação dupla (ver docstring do módulo). ``classe_a``/``classe_b``: por ST, 0 = não
    classificado. Devolve ``classe`` final por ST, ``pares`` escolhidos e a ``tabela`` de cruzamento completa."""
    ambos = (classe_a > 0) & (classe_b > 0)
    N = int(ambos.sum())
    ka, kb = int(classe_a.max(initial=0)), int(classe_b.max(initial=0))
    tabela = np.zeros((ka, kb), dtype=int)
    for i, j in zip(classe_a[ambos], classe_b[ambos]):
        tabela[i - 1, j - 1] += 1
    na, nb = tabela.sum(axis=1), tabela.sum(axis=0)
    candidatos = []
    for i in range(ka):
        for j in range(kb):
            nij = int(tabela[i, j])
            if nij < min_classe:
                continue
            x2, _ = chi2_2x2(nij, na[i], nb[j], N)
            if x2 >= CHI2_CRITICO:
                candidatos.append((-float(x2), -nij, i, j))
    candidatos.sort()
    usados_a, usados_b, pares = set(), set(), []
    for x2n, nn, i, j in candidatos:
        if i in usados_a or j in usados_b:
            continue
        usados_a.add(i)
        usados_b.add(j)
        pares.append({"classe_a": i + 1, "classe_b": j + 1, "n": -nn, "chi2": round(-x2n, 4)})
    pares.sort(key=lambda p: (p["classe_a"], p["classe_b"]))
    classe = np.zeros(len(classe_a), dtype=int)
    for k, p in enumerate(pares, start=1):
        p["classe"] = k
        classe[(classe_a == p["classe_a"]) & (classe_b == p["classe_b"])] = k
    return {"classe": classe, "pares": pares, "tabela": tabela.tolist()}


def agrupar_em_uc(docs_dos_st: list, tamanhos_st: list[int], alvo: int) -> np.ndarray:
    """Índice da UC de cada ST: ST consecutivos do mesmo documento somados enquanto o total fica mais perto do alvo."""
    uc = np.zeros(len(tamanhos_st), dtype=int)
    atual, soma, doc_atual = -1, 0, object()
    for i, (doc, tam) in enumerate(zip(docs_dos_st, tamanhos_st)):
        if doc != doc_atual or atual < 0 or abs(soma + tam - alvo) >= abs(soma - alvo):
            atual += 1
            soma = 0
            doc_atual = doc
        uc[i] = atual
        soma += tam
    return uc


# =====================================================================================================
# Dados do corpus: segmentos e formas
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


_UNIDADES = _Cache(4)
_RESULTADOS = _Cache(8)


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


def assinatura_filtro(filtro) -> str:
    return hashlib.sha256("\n".join(sorted(filtro)).encode("utf-8")).hexdigest()[:16]


def classes_ativas(pasta: Path) -> frozenset | None:
    """Conjunto de UPOS das formas ativas (``reinert.formas_ativas = "classes"``) ou ``None`` (todas as formas plenas)."""
    r = parametros_do_projeto.carregar(pasta).get("reinert") or {}
    if str(r.get("formas_ativas", "todas")).lower() != "classes":
        return None
    try:
        return spacy_nlp.expandir_classes(r.get("classes_ativas") or ["plenas"]) or None
    except ValueError:
        return None


def carregar_unidades(pasta: Path, metas: list[dict], filtro, por: str = "lema") -> dict:
    """ST do corpus e as formas plenas de cada um (cache em processo por mtime dos arquivos).

    ``st``: [{doc, seg, pagina, n_tokens}] na ordem do corpus; ``formas``: lista de Counter (forma -> ocorrências);
    ``freq``: Counter do corpus; ``sem_segmentos``: documentos sem arquivo de segmentos compatível."""
    sem_ruido = ruido.excluir_ruido(parametros_do_projeto.carregar(pasta))
    ativas = classes_ativas(pasta)
    chave = (str(pasta), por, assinatura_filtro(filtro), marcas_do_corpus(pasta, metas), sem_ruido, ativas)
    em_cache = _UNIDADES.obter(chave)
    if em_cache is not None:
        return em_cache
    campo = "lema" if por == "lema" else "norm"
    st, formas, freq, faltam = [], [], Counter(), []
    n_seg_doc: dict[int, int] = {}
    ruido_fora = {"segmentos": 0, "palavras": 0}
    sem_classes: list[int] = []
    for m in metas:
        tk = dados.carregar_tokens(pasta, m["id"])
        sg = segmentacao.ler_segmentos(pasta, m["id"])
        if tk is None or sg is None or sg.get("n") != tk["n"]:
            faltam.append(m["id"])
            continue
        locais = [Counter() for _ in sg["segmentos"]]
        n_seg_doc[m["id"]] = len(sg["segmentos"])
        fora = ruido.segmentos_de_ruido(pasta, m["id"]) if sem_ruido else {}
        termos, normas, lemas, incl, seg = tk[campo], tk["norm"], tk["lema"], tk["incluir"], sg["seg"]
        pos = None
        if ativas:
            pos = spacy_nlp.classes_do_documento(spacy_nlp.sidecar_valido(pasta, m["id"], tk, tk["idioma"]))
            if pos is None:
                sem_classes.append(m["id"])
        for i, s in enumerate(seg):
            if s < 0 or s in fora or not incl[i] or token_vazio(normas[i], lemas[i], filtro):
                continue
            if pos is not None and pos[i] not in ativas:
                continue
            locais[s][termos[i]] += 1
        for s, c in zip(sg["segmentos"], locais):
            if s["seg"] in fora:  # ruído (3.4): fora da CHD e da similitude; o índice do segmento é preservado
                ruido_fora["segmentos"] += 1
                ruido_fora["palavras"] += s["n_tokens"]
                continue
            st.append({"doc": m["id"], "seg": s["seg"], "pagina": s["pagina"], "n_tokens": s["n_tokens"]})
            formas.append(c)
            freq.update(c)
    r = {"st": st, "formas": formas, "freq": freq, "sem_segmentos": faltam, "n_seg_doc": n_seg_doc, "ruido": ruido_fora,
         "sem_classes": sem_classes, "classes_ativas": sorted(ativas) if ativas else None}
    _UNIDADES.guardar(chave, r)
    return r


def texto_do_st(pasta: Path, doc_id: int, seg: int) -> str:
    sg = segmentacao.ler_segmentos(pasta, doc_id)
    return sg["segmentos"][seg]["texto"] if sg and 0 <= seg < len(sg["segmentos"]) else ""


def matriz_st_forma(formas_por_st: list[Counter], vocab: list[str]) -> sp.csr_matrix:
    idx = {f: j for j, f in enumerate(vocab)}
    linhas, cols = [], []
    for i, c in enumerate(formas_por_st):
        js = sorted(idx[f] for f in c if f in idx)
        linhas.extend([i] * len(js))
        cols.extend(js)
    return sp.csr_matrix((np.ones(len(linhas)), (linhas, cols)), shape=(len(formas_por_st), len(vocab)))


# =====================================================================================================
# Análise sobre o corpus
# =====================================================================================================

def _validar(classes, min_freq, tamanhos, min_classe):
    if not 2 <= classes <= CLASSES_MAX:
        raise ValueError(f"classes deve estar entre 2 e {CLASSES_MAX}.")
    if min_freq < 1:
        raise ValueError("min_freq deve ser >= 1.")
    if len(tamanhos) != 2 or any(int(t) < 5 for t in tamanhos) or tamanhos[0] == tamanhos[1]:
        raise ValueError("tamanhos deve ter 2 tamanhos diferentes de UC (>= 5 palavras cada).")
    if min_classe < 0:
        raise ValueError("min_classe deve ser >= 0 (0 = automático).")


def _descrever_classes(Xc: sp.csr_matrix, vocab: list[str], classe: np.ndarray, k: int, limite: int):
    """Formas características de cada classe (χ² 2 × 2 entre os ST classificados)."""
    N = Xc.shape[0]
    C = sp.csr_matrix((np.ones(N), (np.arange(N), classe - 1)), shape=(N, k))
    A = (C.T @ Xc).toarray()  # k × p: ST da classe com a forma
    tot = np.asarray(Xc.sum(axis=0)).ravel()
    tam = np.bincount(classe - 1, minlength=k)
    X2, P = chi2_2x2(A, tam[:, None], tot[None, :], N)
    saida = []
    for c in range(k):
        pos = np.flatnonzero((X2[c] >= CHI2_CRITICO) & (A[c] > 0))
        pos = sorted(pos, key=lambda j: (-X2[c, j], vocab[j]))
        saida.append({"n_formas": len(pos), "formas": [{
            "forma": vocab[j], "chi2": round(float(X2[c, j]), 3), "p": float(f"{P[c, j]:.3g}"),
            "freq_classe": int(A[c, j]), "freq_total": int(tot[j]),
            "pct_classe": round(100 * A[c, j] / tot[j], 2)} for j in pos[:limite]]})
    return saida, A, X2


def _variaveis(st: list[dict], metas_por_id: dict, classe: np.ndarray, k: int, limite: int = 10) -> list[dict]:
    """Variáveis suplementares (documento, grupo, ano) características de cada classe."""
    N = len(classe)
    tam = np.bincount(classe - 1, minlength=k)
    por_classe = [{v: [] for v in VARIAVEIS} for _ in range(k)]
    for var in VARIAVEIS:
        if var == "documento":
            mod = [metas_por_id[s["doc"]]["rotulo"] for s in st]
        elif var == "grupo":
            mod = [dados.chave_grupo(metas_por_id[s["doc"]]) for s in st]
        else:
            mod = [dados.chave_ano(metas_por_id[s["doc"]]) for s in st]
        nomes = sorted(set(mod))
        if len(nomes) < 2:
            continue
        idx = {n: j for j, n in enumerate(nomes)}
        A = np.zeros((k, len(nomes)))
        for c, mo in zip(classe, mod):
            A[c - 1, idx[mo]] += 1
        tot = A.sum(axis=0)
        X2, P = chi2_2x2(A, tam[:, None], tot[None, :], N)
        for c in range(k):
            pos = sorted(np.flatnonzero((X2[c] >= CHI2_CRITICO) & (A[c] > 0)), key=lambda j: (-X2[c, j], nomes[j]))
            por_classe[c][var] = [{"modalidade": nomes[j], "chi2": round(float(X2[c, j]), 3),
                                   "p": float(f"{P[c, j]:.3g}"), "st_classe": int(A[c, j]), "st_total": int(tot[j]),
                                   "pct_classe": round(100 * A[c, j] / tot[j], 2)} for j in pos[:limite]]
    return por_classe


def _afc_das_classes(A: np.ndarray, X2: np.ndarray, vocab: list[str], k: int, por_classe: int = 30) -> dict | None:
    if k < 2:
        return None
    escolhidas = []
    for c in range(k):
        pos = sorted(np.flatnonzero((X2[c] >= CHI2_CRITICO) & (A[c] > 0)), key=lambda j: (-X2[c, j], vocab[j]))
        escolhidas.extend(pos[:por_classe])
    escolhidas = sorted(set(int(j) for j in escolhidas))
    if len(escolhidas) < 2:
        return None
    N = A[:, escolhidas].T  # formas × classes
    vivas = N.sum(axis=0) > 0
    if vivas.sum() < 2:
        return None
    ac = afc.analise_de_correspondencia(N[:, vivas], eixos=min(5, k - 1))
    total = ac["inercia_total"]
    classes_vivas = [c + 1 for c in range(k) if vivas[c]]
    return {
        "k": ac["k"], "inercia_total": round(total, 8),
        "eixos": [{"eixo": e + 1, "autovalor": round(float(v), 8), "pct": round(float(v / total * 100), 3) if total else 0.0}
                  for e, v in enumerate(ac["autovalores"][:ac["k"]])],
        "formas": [{"forma": vocab[j], "classe": int(np.argmax(X2[:, j])) + 1, "chi2": round(float(X2[:, j].max()), 3),
                    "coord": [round(float(v), 5) for v in ac["F"][a]], "ctr": [round(float(v), 3) for v in ac["ctr_linhas"][a]]}
                   for a, j in enumerate(escolhidas)],
        "classes": [{"classe": c, "coord": [round(float(v), 5) for v in ac["G"][b]],
                     "ctr": [round(float(v), 3) for v in ac["ctr_colunas"][b]]} for b, c in enumerate(classes_vivas)],
        "convencao_sinal": "Em cada eixo, a classe de maior |coordenada| fica positiva.",
    }


def calcular(pasta: Path, metas: list[dict], filtro, classes: int = 10, min_freq: int = 3, dupla: bool = False,
             tamanhos=(40, 60), min_classe: int = 0, max_formas: int = MAX_FORMAS, max_iter: int = MAX_ITER,
             limite_formas: int = 50, n_segmentos: int = 10) -> dict:
    """CHD de Reinert sobre os segmentos do corpus. Levanta ValueError (parâmetros, corpus pequeno)."""
    tamanhos = [int(t) for t in tamanhos]
    _validar(classes, min_freq, tamanhos, min_classe)
    chave = (str(pasta), marcas_do_corpus(pasta, metas), dados.assinatura_metadados(metas), assinatura_filtro(filtro),
             classes, min_freq, bool(dupla), tuple(tamanhos), min_classe, max_formas, max_iter, limite_formas, n_segmentos,
             ruido.excluir_ruido(parametros_do_projeto.carregar(pasta)), classes_ativas(pasta))
    em_cache = _RESULTADOS.obter(chave)
    if em_cache is not None:
        return em_cache
    u = carregar_unidades(pasta, metas, filtro)
    vocab = sorted(f for f, c in u["freq"].items() if c >= min_freq)
    if max_formas and len(vocab) > max_formas:
        vocab = sorted(sorted(vocab, key=lambda f: (-u["freq"][f], f))[:max_formas])
    total_st = len(u["st"])
    if total_st == 0:
        raise ValueError("Nenhum segmento de texto: execute o pipeline (etapa segmentos).")
    X = matriz_st_forma(u["formas"], vocab)
    classificaveis = np.flatnonzero(np.diff(X.indptr) > 0)
    if len(classificaveis) < 10 or len(vocab) < 5:
        raise ValueError(f"Corpus pequeno demais para a CHD: {len(classificaveis)} segmentos com formas ativas e "
                         f"{len(vocab)} formas com frequência >= {min_freq} (mínimo 10 e 5).")
    Xa = X[classificaveis]
    classe = np.zeros(total_st, dtype=int)
    dendrogramas, cruzamento = [], None
    if not dupla:
        r = chd(Xa, classes, min_classe, max_iter)
        minc = r["min_classe"]
        classe[classificaveis] = r["classe"]
        dendrogramas.append({"unidade": "segmento", "n_unidades": int(Xa.shape[0]), "nos": nos_publicos(r["nos"])})
    else:
        docs = [u["st"][i]["doc"] for i in classificaveis]
        tams = [u["st"][i]["n_tokens"] for i in classificaveis]
        minc = int(min_classe) if min_classe > 0 else min_classe_automatico(len(classificaveis))
        por_st = []
        for alvo in tamanhos:
            uc = agrupar_em_uc(docs, tams, alvo)
            n_uc = int(uc.max()) + 1
            G = sp.csr_matrix((np.ones(len(uc)), (uc, np.arange(len(uc)))), shape=(n_uc, len(uc)))
            Xuc = binaria(G @ Xa)
            r = chd(Xuc, classes, minc, max_iter)
            por_st.append(r["classe"][uc])
            dendrogramas.append({"unidade": f"UC de ~{alvo} palavras", "n_unidades": n_uc, "nos": nos_publicos(r["nos"])})
        cz = cruzar(por_st[0], por_st[1], minc)
        classe[classificaveis] = cz["classe"]
        cruzamento = {"pares": cz["pares"], "tabela": cz["tabela"]}
        # anota no 1º dendrograma a classe final de cada folha estável
        mapa = {p["classe_a"]: p["classe"] for p in cz["pares"]}
        for no in dendrogramas[0]["nos"]:
            no["classe_final"] = mapa.get(no["classe"]) if no["folha"] else None
    k = int(classe.max(initial=0))
    if k == 0:
        raise ValueError("Nenhuma classe estável/suficientemente grande: reduza min_classe ou o número de classes.")
    clas = np.flatnonzero(classe > 0)
    Xc = X[clas]
    cl = classe[clas]
    desc, A, X2 = _descrever_classes(Xc, vocab, cl, k, limite_formas)
    metas_por_id = {m["id"]: m for m in metas}
    st_c = [u["st"][i] for i in clas]
    variaveis = _variaveis(st_c, metas_por_id, cl, k)
    # segmentos típicos: soma dos χ² das formas características da classe presentes no ST
    peso = np.where((X2 >= CHI2_CRITICO) & (A > 0), X2, 0.0)  # k × p
    linha_nz = np.repeat(np.arange(Xc.shape[0]), np.diff(Xc.indptr))
    pontos = np.bincount(linha_nz, weights=peso[cl[linha_nz] - 1, Xc.indices], minlength=Xc.shape[0])
    n_classificados = len(clas)
    saida_classes = []
    for c in range(1, k + 1):
        membros = np.flatnonzero(cl == c)
        topo = sorted(membros, key=lambda i: (-pontos[i], int(clas[i])))[:n_segmentos]
        tipicos = []
        for i in topo:
            s = st_c[i]
            tipicos.append({"documento_id": s["doc"], "rotulo": metas_por_id[s["doc"]]["rotulo"], "seg": s["seg"],
                            "pagina": s["pagina"], "pontuacao": round(float(pontos[i]), 3),
                            "texto": texto_do_st(pasta, s["doc"], s["seg"])})
        saida_classes.append({
            "classe": c, "n_st": int(len(membros)), "pct": round(100 * len(membros) / n_classificados, 2),
            "pct_total": round(100 * len(membros) / total_st, 2),
            "n_documentos": len({st_c[i]["doc"] for i in membros}),
            **desc[c - 1], "variaveis": variaveis[c - 1], "segmentos": tipicos,
        })
    retencao = round(100 * n_classificados / total_st, 2)
    avisos = []
    if retencao < RETENCAO_MINIMA:
        avisos.append(f"Retenção de {retencao}% abaixo de {RETENCAO_MINIMA:.0f}%: a classificação aproveita pouco do "
                      "corpus; interprete com cautela (reduza o número de classes ou min_classe).")
    if u["ruido"]["segmentos"]:
        avisos.append(f"{u['ruido']['segmentos']} segmento(s) de ruído (~{u['ruido']['palavras']} palavras) ficaram fora "
                      "(limpeza.excluir_ruido); a retenção é calculada sobre os demais.")
    if u["classes_ativas"]:
        avisos.append(f"Formas ativas restritas às classes {', '.join(u['classes_ativas'])} (spaCy)." + (f" {len(u['sem_classes'])} documento(s) sem etiquetagem ficaram sem filtro de classe." if u["sem_classes"] else ""))
    if u["sem_segmentos"]:
        avisos.append(f"{len(u['sem_segmentos'])} documento(s) sem segmentos atualizados ficaram de fora: execute o pipeline.")
    # lista por documento indexada pelo índice do segmento (0 = sem classe; inclui os segmentos de ruído excluídos)
    por_doc: dict[str, list[int]] = {str(d): [0] * n for d, n in u["n_seg_doc"].items()}
    for s, c in zip(u["st"], classe):
        por_doc[str(s["doc"])][s["seg"]] = int(c)
    res = {
        "segmentos_total": total_st, "segmentos_ruido": u["ruido"]["segmentos"], "segmentos_classificaveis": int(len(classificaveis)),
        "segmentos_classificados": n_classificados, "retencao_pct": retencao, "k": k, "min_classe": minc,
        "formas_ativas": len(vocab), "dupla": bool(dupla), "dendrogramas": dendrogramas, "cruzamento": cruzamento,
        "classes": saida_classes, "afc": _afc_das_classes(A, X2, vocab, k), "avisos": avisos,
        "classes_por_documento": por_doc,
        "parametros": {"classes": classes, "min_freq": min_freq, "dupla": bool(dupla), "tamanhos": tamanhos,
                       "min_classe": min_classe, "max_formas": max_formas, "max_iter": max_iter, "unidade": "lema", "vazias": "filtrar",
                       "classes_ativas": u["classes_ativas"]},
        "metodologia": METODOLOGIA, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE, "nao_equivalente": NAO_EQUIVALENTE,
    }
    _RESULTADOS.guardar(chave, res)
    return res


# ---------- partição "classe" para especificidades (6.2) e AFC (7.3) ----------

def tabela_por_classe(pasta: Path, metas: list[dict], filtro, resultado: dict, por: str = "lema", filtrar: bool = True):
    """Tabela termo × classe no formato de ``especificidades.tabela_lexical``: (termos, contagens, tamanhos, partes,
    excluídas). Tamanhos = palavras do universo da 6.2 (corpo, >= 2 letras, com as vazias) nos ST da classe."""
    from app.services.palavras_vazias import COMPRIMENTO_MINIMO

    k = resultado["k"]
    contagens = [Counter() for _ in range(k)]
    tamanhos = np.zeros(k, dtype=np.int64)
    docs_por_classe = [set() for _ in range(k)]
    campo = {"lema": "lema", "forma": "norm", "termo": "termo"}[por]
    for m in metas:
        mapa = resultado["classes_por_documento"].get(str(m["id"]))
        if not mapa:
            continue
        tk = dados.carregar_tokens(pasta, m["id"], termos=(por == "termo"))
        sg = segmentacao.ler_segmentos(pasta, m["id"])
        if tk is None or sg is None or sg.get("n") != tk["n"] or len(sg["segmentos"]) != len(mapa):
            continue
        termos, normas, lemas, incl, seg = tk[campo], tk["norm"], tk["lema"], tk["incluir"], sg["seg"]
        for i, s in enumerate(seg):
            if s < 0 or not incl[i] or len(normas[i]) < COMPRIMENTO_MINIMO:
                continue
            c = mapa[s]
            if c <= 0:
                continue
            tamanhos[c - 1] += 1
            docs_por_classe[c - 1].add(m["id"])
            t = termos[i]
            if not t or (filtrar and token_vazio(normas[i], lemas[i], filtro)):
                continue
            contagens[c - 1][t] += 1
    partes, validas, cont, excluidas = [], [], [], []
    for c in range(k):
        rot = f"classe {c + 1}"
        if tamanhos[c] == 0:
            excluidas.append({"chave": str(c + 1), "rotulo": rot, "motivo": "parte sem tokens"})
            continue
        validas.append(c)
        partes.append({"chave": str(c + 1), "rotulo": rot, "documentos": len(docs_por_classe[c]),
                       "tokens": int(tamanhos[c]), "ids": sorted(docs_por_classe[c])})
        cont.append(contagens[c])
    termos = sorted(set().union(*cont)) if cont else []
    linha = {t: i for i, t in enumerate(termos)}
    mat = np.zeros((len(termos), len(cont)), dtype=np.int64)
    for j, c in enumerate(cont):
        for t, v in c.items():
            mat[linha[t], j] = v
    return termos, mat, tamanhos[validas], partes, excluidas
