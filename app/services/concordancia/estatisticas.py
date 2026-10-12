"""15.1 - Estatísticas de concordância entre codificadores (escala nominal, com opções ordinal/intervalar no alfa).

Percentual de concordância
    p_o = proporção das unidades com o mesmo código. Não corrige o acaso.

Kappa de Cohen (1960), 2 codificadores, nominal
    kappa = (p_o - p_e)/(1 - p_e), p_e = soma_i p_i. * p_.i (marginais de cada codificador).
    Erro-padrão assintótico **não nulo** (para IC) de Fleiss, Cohen & Everitt (1969), na forma de Fleiss, Levin &
    Paik (2003, eq. 18.13):
        EP = sqrt(A + B - C) / ((1 - p_e)·sqrt(n)),
        A = soma_i p_ii [1 - (p_i. + p_.i)(1 - kappa)]²,
        B = (1 - kappa)² soma_{i != j} p_ij (p_.i + p_j.)²,
        C = [kappa - p_e(1 - kappa)]².
    IC 95% = kappa ± 1,96·EP (truncado em [-1, 1]). É o método delta sobre a multinomial das células (os testes
    conferem com o gradiente numérico). Opcional: IC bootstrap percentil reamostrando unidades (semente fixa).
    Sem variação (p_e = 1, os dois usam um único e mesmo código): kappa indefinido (None).

Alfa de Krippendorff (2011, "Computing Krippendorff's Alpha-Reliability"; 2018, cap. 12)
    Dados: matriz codificadores × unidades, com faltantes (None). Só contam unidades com m_u >= 2 valores
    ("pareáveis"). Matriz de coincidências o_ck = soma_u (nº de pares ordenados (c, k) de codificadores diferentes
    na unidade u)/(m_u - 1); n_c = soma_k o_ck; n = soma n_c.
        alfa = 1 - (n - 1)·soma_{c,k} o_ck·d²_ck / soma_{c,k} n_c·n_k·d²_ck
    d² nominal: 0 se c = k, 1 se não; intervalar: (c - k)²; razão: ((c - k)/(c + k))²; ordinal:
    (soma_{g=c..k} n_g - (n_c + n_k)/2)² com os valores ordenados. Sem variação (D_e = 0): alfa indefinido (None).
    IC bootstrap: reamostragem de **unidades** com reposição (percentil, semente fixa), mais a probabilidade de
    alfa < 0,667 e < 0,800 na distribuição bootstrap, como no relatório de Hayes & Krippendorff (2007).
    **Diferença:** a macro KALPHA de Hayes & Krippendorff reamostra pares de valores dentro das unidades, não
    unidades inteiras; os dois são percentis de bootstrap, mas os intervalos não coincidem exatamente.

Por código (um contra o resto)
    Para cada código c: kappa da tabela 2 × 2 (humano = c? × LLM = c?), e precisão = VP/(VP + FP), revocação =
    VP/(VP + FN) e F1 do LLM tomando o humano como referência; suporte = nº de trechos com c pelo humano.

Faixas de leitura
    Kappa: Landis & Koch (1977) - < 0 pobre; 0-0,20 leve; 0,21-0,40 razoável; 0,41-0,60 moderada; 0,61-0,80
    substancial; 0,81-1 quase perfeita (faixas convencionais, sem base inferencial). Alfa: Krippendorff (2004, 2018)
    - >= 0,800 confiável; 0,667-0,800 só conclusões provisórias; < 0,667 descartar.
"""
import math
from collections import Counter

import numpy as np

Z95 = 1.959963984540054
FAIXAS_KAPPA = ((0.0, "pobre"), (0.20, "leve"), (0.40, "razoável"), (0.60, "moderada"), (0.80, "substancial"),
                (1.0, "quase perfeita"))


def _presentes(a, b) -> tuple[list, list]:
    pares = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    return [x for x, _ in pares], [y for _, y in pares]


def percentual(a, b) -> float | None:
    a, b = _presentes(a, b)
    return sum(x == y for x, y in zip(a, b)) / len(a) if a else None


def tabela(a, b, categorias: list | None = None) -> tuple[np.ndarray, list]:
    """Tabela de contingência (linhas = codificador a, colunas = b) nas ``categorias`` (padrão: união ordenada)."""
    a, b = _presentes(a, b)
    cats = categorias or sorted(set(a) | set(b), key=str)
    idx = {c: i for i, c in enumerate(cats)}
    M = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b):
        M[idx[x], idx[y]] += 1
    return M, cats


def kappa_da_tabela(M: np.ndarray) -> dict:
    """Kappa, p_o, p_e e EP assintótico (Fleiss, Cohen & Everitt, 1969) de uma tabela de contingência."""
    n = float(M.sum())
    if n == 0:
        return {"kappa": None, "p_o": None, "p_e": None, "ep": None, "n": 0}
    p = M / n
    lin, col = p.sum(axis=1), p.sum(axis=0)
    p_o = float(np.trace(p))
    p_e = float(lin @ col)
    if 1 - p_e <= 1e-15:
        return {"kappa": None, "p_o": p_o, "p_e": p_e, "ep": None, "n": int(n),
                "nota": "Sem variação: os dois codificadores usaram uma única e mesma categoria (kappa indefinido)."}
    k = (p_o - p_e) / (1 - p_e)
    A = float(sum(p[i, i] * (1 - (lin[i] + col[i]) * (1 - k)) ** 2 for i in range(len(p))))
    soma = (col[:, None] + lin[None, :]) ** 2  # (p_.i + p_j.)² na posição (i, j)
    fora = ~np.eye(len(p), dtype=bool)
    B = float((1 - k) ** 2 * (p[fora] * soma[fora]).sum())
    C = (k - p_e * (1 - k)) ** 2
    ep = math.sqrt(max(A + B - C, 0.0)) / ((1 - p_e) * math.sqrt(n))
    return {"kappa": k, "p_o": p_o, "p_e": p_e, "ep": ep, "n": int(n)}


def cohen_kappa(a, b, categorias: list | None = None, bootstrap: int = 0, semente: int = 42) -> dict:
    """Kappa de Cohen com IC 95% assintótico e, se ``bootstrap`` > 0, IC percentil por reamostragem de unidades."""
    M, cats = tabela(a, b, categorias)
    r = kappa_da_tabela(M)
    if r["kappa"] is not None:
        r["ic95"] = [max(-1.0, r["kappa"] - Z95 * r["ep"]), min(1.0, r["kappa"] + Z95 * r["ep"])]
        r["faixa"] = faixa_kappa(r["kappa"])
    if bootstrap and r["kappa"] is not None:
        aa, bb = _presentes(a, b)
        idx = {c: i for i, c in enumerate(cats)}
        ia, ib = np.array([idx[x] for x in aa]), np.array([idx[y] for y in bb])
        rng = np.random.default_rng(semente)
        q = len(cats)
        vals = []
        for _ in range(bootstrap):
            s = rng.integers(0, len(ia), len(ia))
            Mb = np.bincount(ia[s] * q + ib[s], minlength=q * q).reshape(q, q).astype(float)
            kb = kappa_da_tabela(Mb)["kappa"]
            if kb is not None:
                vals.append(kb)
        r["bootstrap"] = _resumo_bootstrap(vals, bootstrap, semente)
    r["categorias"] = cats
    return r


def faixa_kappa(k: float | None) -> str | None:
    """Faixa de Landis & Koch (1977)."""
    if k is None:
        return None
    if k < 0:
        return "pobre"
    for limite, nome in FAIXAS_KAPPA[1:]:
        if k <= limite + 1e-12:
            return nome
    return "quase perfeita"


def faixa_alfa(a: float | None) -> str | None:
    """Orientação de Krippendorff: >= 0,800 confiável; >= 0,667 provisório; abaixo, descartar."""
    if a is None:
        return None
    if a >= 0.800:
        return "confiável (>= 0,800)"
    if a >= 0.667:
        return "só conclusões provisórias (0,667 a 0,800)"
    return "insuficiente (< 0,667)"


def _resumo_bootstrap(vals: list[float], pedidas: int, semente: int) -> dict:
    if not vals:
        return {"replicas": pedidas, "validas": 0, "ic95": None, "semente": semente}
    v = np.asarray(vals)
    return {"replicas": pedidas, "validas": int(len(v)), "semente": semente,
            "ic95": [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))],
            "p_abaixo_0667": float((v < 0.667).mean()), "p_abaixo_0800": float((v < 0.800).mean())}


# ---------- alfa de Krippendorff ----------

def coincidencias(dados: list[list], valores: list | None = None) -> tuple[np.ndarray, list]:
    """Matriz de coincidências o_ck a partir de codificadores × unidades (None = faltante)."""
    n_cod = len(dados)
    n_uni = max((len(l) for l in dados), default=0)
    colunas = [[dados[c][u] for c in range(n_cod) if u < len(dados[c]) and dados[c][u] is not None] for u in range(n_uni)]
    vals = valores or sorted({v for col in colunas for v in col}, key=lambda x: (isinstance(x, str), x))
    idx = {v: i for i, v in enumerate(vals)}
    O = np.zeros((len(vals), len(vals)))
    for col in colunas:
        m = len(col)
        if m < 2:
            continue
        cont = Counter(col)
        for c, nc in cont.items():
            for k, nk in cont.items():
                pares = nc * (nk - 1) if c == k else nc * nk
                O[idx[c], idx[k]] += pares / (m - 1)
    return O, vals


def _delta2(vals: list, n_c: np.ndarray, metrica: str) -> np.ndarray:
    q = len(vals)
    if metrica == "nominal":
        return 1.0 - np.eye(q)
    x = np.asarray(vals, dtype=float)
    if metrica == "intervalar":
        return (x[:, None] - x[None, :]) ** 2
    if metrica == "razao":
        with np.errstate(divide="ignore", invalid="ignore"):
            d = ((x[:, None] - x[None, :]) / (x[:, None] + x[None, :])) ** 2
        return np.nan_to_num(d)
    if metrica == "ordinal":
        D = np.zeros((q, q))
        for i in range(q):
            for j in range(q):
                lo, hi = min(i, j), max(i, j)
                D[i, j] = (n_c[lo:hi + 1].sum() - (n_c[i] + n_c[j]) / 2) ** 2
        return D
    raise ValueError(f"Métrica inválida '{metrica}': use nominal, ordinal, intervalar ou razao.")


def alfa_da_coincidencia(O: np.ndarray, vals: list, metrica: str = "nominal") -> dict:
    n_c = O.sum(axis=1)
    n = float(n_c.sum())
    if n <= 1:
        return {"alfa": None, "n_valores_pareaveis": n, "d_o": None, "d_e": None, "nota": "Sem unidades pareáveis."}
    D = _delta2(vals, n_c, metrica)
    d_o = float((O * D).sum()) / n
    d_e = float((np.outer(n_c, n_c) * D).sum()) / (n * (n - 1))
    if d_e <= 1e-15:
        return {"alfa": None, "n_valores_pareaveis": n, "d_o": d_o, "d_e": d_e,
                "nota": "Sem variação nos valores: alfa indefinido."}
    return {"alfa": 1 - d_o / d_e, "n_valores_pareaveis": n, "d_o": d_o, "d_e": d_e}


def krippendorff_alfa(dados: list[list], metrica: str = "nominal", bootstrap: int = 0, semente: int = 42) -> dict:
    """Alfa de Krippendorff para 2+ codificadores com faltantes (``dados`` = codificadores × unidades)."""
    O, vals = coincidencias(dados)
    r = alfa_da_coincidencia(O, vals, metrica)
    r["metrica"] = metrica
    r["faixa"] = faixa_alfa(r["alfa"])
    n_uni = max((len(l) for l in dados), default=0)
    pareaveis = [u for u in range(n_uni) if sum(1 for l in dados if u < len(l) and l[u] is not None) >= 2]
    r["unidades_pareaveis"] = len(pareaveis)
    if bootstrap and r["alfa"] is not None:
        rng = np.random.default_rng(semente)
        cols = [[l[u] if u < len(l) else None for l in dados] for u in pareaveis]
        vals_b = []
        for _ in range(bootstrap):
            s = rng.integers(0, len(cols), len(cols))
            amostra = [[cols[i][c] for i in s] for c in range(len(dados))]
            Ob, _ = coincidencias(amostra, vals)
            ab = alfa_da_coincidencia(Ob, vals, metrica)["alfa"]
            if ab is not None:
                vals_b.append(ab)
        r["bootstrap"] = _resumo_bootstrap(vals_b, bootstrap, semente)
    return r


# ---------- por código e matriz de confusão ----------

def por_codigo(humano, llm, categorias: list | None = None) -> list[dict]:
    """Kappa um-contra-o-resto, precisão, revocação e F1 do LLM (referência = humano) para cada código."""
    a, b = _presentes(humano, llm)
    cats = categorias or sorted(set(a) | set(b), key=str)
    saida = []
    for c in cats:
        vp = sum(1 for x, y in zip(a, b) if x == c and y == c)
        fp = sum(1 for x, y in zip(a, b) if x != c and y == c)
        fn = sum(1 for x, y in zip(a, b) if x == c and y != c)
        vn = len(a) - vp - fp - fn
        kap = kappa_da_tabela(np.array([[vp, fn], [fp, vn]], dtype=float))
        prec = vp / (vp + fp) if vp + fp else None
        rev = vp / (vp + fn) if vp + fn else None
        f1 = 2 * prec * rev / (prec + rev) if prec and rev else (0.0 if prec is not None and rev is not None else None)
        saida.append({"codigo": c, "suporte_humano": vp + fn, "atribuidos_llm": vp + fp, "vp": vp, "fp": fp, "fn": fn,
                      "kappa": kap["kappa"], "precisao": prec, "revocacao": rev, "f1": f1})
    return saida


def matriz_confusao(humano, llm, categorias: list | None = None) -> dict:
    M, cats = tabela(humano, llm, categorias)
    return {"categorias": cats, "linhas": "humano", "colunas": "llm", "matriz": M.astype(int).tolist()}


def resumo(humano, llm, bootstrap: int = 1000, semente: int = 42, nivel_codigos: list | None = None) -> dict:
    """Pacote completo para 2 codificadores (humano × LLM): percentual, kappa, alfa nominal, por código e confusão."""
    a, b = _presentes(humano, llm)
    cats = nivel_codigos or sorted(set(a) | set(b), key=str)
    return {
        "n_pares": len(a), "n_unidades": len(list(humano)), "percentual": percentual(a, b),
        "kappa": cohen_kappa(a, b, cats, bootstrap=bootstrap, semente=semente),
        "alfa": krippendorff_alfa([list(humano), list(llm)], "nominal", bootstrap=bootstrap, semente=semente),
        "por_codigo": por_codigo(a, b, cats), "confusao": matriz_confusao(a, b, cats),
    }
