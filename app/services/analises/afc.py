"""7.3 - Análise fatorial de correspondência (AFC) de uma tabela lexical termo × parte.

Equivale à AFC do IRaMuTeQ e do TXM e ao Correspondence Analysis do KH Coder. **Não** é uma PCA: a AFC trabalha com
perfis e a distância do qui-quadrado (pesos = massas), não com variáveis centradas na média e distância euclidiana.

Tabela
------
Linhas = termos, colunas = partes (``grupo`` | ``ano`` | ``documento`` | ``classe``: as classes da CHD, 7.1, com a
tabela termo × classe montada sobre os segmentos classificados). Unidade lema (padrão), forma ou termo
(4.3), palavras vazias filtradas, frequência no corpus >= ``min_freq`` (5). Termos escolhidos por:

- ``selecao="freq"`` (padrão): os ``n_termos`` mais frequentes (100; até 500), desempate alfabético;
- ``selecao="especificidade"``: os ``n_termos`` de maior max |score| de especificidade (6.2) entre as partes da mesma
  partição (os que mais diferenciam as partes), desempate pela frequência.

Partes sem nenhuma ocorrência dos termos escolhidos saem (``partes_excluidas``). São necessárias >= 2 partes; com
2 partes a AFC tem um único eixo (a resposta traz ``mensagem`` e o resultado em 1 dimensão).

Cálculo (Benzécri 1973; Greenacre 2017, cap. 4–7)
-------------------------------------------------
N = tabela (I × J), n = soma, P = N / n, massas r = P·1 (linhas) e c = Pᵀ·1 (colunas),
S = D_r^(−1/2) (P − r cᵀ) D_c^(−1/2) (resíduos padronizados), SVD S = U Σ Vᵀ.

- autovalores (inércias principais) λ_k = σ_k²; inércia total = Σ S² = Σ λ_k = χ² / n; % = λ_k / inércia total.
- coordenadas principais: linhas F = D_r^(−1/2) U Σ; colunas G = D_c^(−1/2) V Σ
  (coordenadas-padrão = as mesmas sem o Σ). Fórmulas de transição: F = D_r^(−1) P G Σ^(−1) e G = D_c^(−1) Pᵀ F Σ^(−1).
- contribuição (ctr, em %) da linha i ao eixo k = 100 · r_i F_ik² / λ_k (soma 100 em cada eixo; o mesmo nas colunas).
- cos² da linha i no eixo k = F_ik² / d_i², com d_i² = Σ_j (p_ij/r_i − c_j)² / c_j (distância do qui-quadrado do
  perfil ao centro, calculada em todas as dimensões, então Σ_k cos² <= 1); ``qualidade`` = soma dos cos² dos eixos
  devolvidos. ``inercia`` da linha = r_i d_i² (em % da total em ``inercia_pct``).

Eixos devolvidos: min(I − 1, J − 1, ``eixos``) (padrão 5), sem os de autovalor numericamente nulo (< 1e−12).

Convenção de sinal (determinística)
-----------------------------------
O sinal de um eixo da AFC é arbitrário. Aqui, em cada eixo, a **coluna (parte) de maior |coordenada|** fica com
coordenada positiva (empate: a de menor índice); linhas e colunas trocam de sinal juntas (U e V), preservando as
fórmulas de transição. Outros programas podem mostrar o mesmo mapa espelhado.
"""
import numpy as np

from app.services.analises import especificidades as esp

SELECOES = ("freq", "especificidade")
EIXOS_MAX = 5
N_TERMOS_MAX = 500
EPS_AUTOVALOR = 1e-12
FERRAMENTA_EQUIVALENTE = "IRaMuTeQ AFC, TXM AFC, KH Coder Correspondence"
NAO_EQUIVALENTE = "PCA"
METODOLOGIA = (
    "Análise de correspondência simples (Benzécri 1973; Greenacre 2017) da tabela termo × parte: SVD dos resíduos "
    "padronizados D_r^(−1/2)(P − rcᵀ)D_c^(−1/2); autovalores = inércias principais (soma = χ²/n); coordenadas "
    "principais, contribuições (ctr, % por eixo) e cos² de linhas e colunas. Sinal de cada eixo: a parte de maior "
    "|coordenada| fica positiva."
)


# ---------- estatística (funções puras) ----------

def analise_de_correspondencia(N, eixos: int = EIXOS_MAX) -> dict:
    """AFC de uma matriz de contagens não negativas (I × J, sem linha/coluna nula). Ver docstring do módulo.

    Devolve arrays numpy: ``autovalores`` (todos os não nulos), ``inercia_total``, ``chi2``, ``n``, ``r``, ``c``,
    ``F``/``G`` (coordenadas principais, K eixos), ``ctr_linhas``/``ctr_colunas`` (%), ``cos2_linhas``/``cos2_colunas``,
    ``d2_linhas``/``d2_colunas`` e ``k`` (eixos devolvidos)."""
    N = np.asarray(N, dtype=float)
    if N.ndim != 2 or N.shape[0] < 2 or N.shape[1] < 2:
        raise ValueError("A AFC precisa de pelo menos 2 linhas e 2 colunas.")
    if (N < 0).any():
        raise ValueError("A tabela da AFC não pode ter valores negativos.")
    n = N.sum()
    P = N / n
    r, c = P.sum(axis=1), P.sum(axis=0)
    if (r <= 0).any() or (c <= 0).any():
        raise ValueError("A tabela da AFC não pode ter linha ou coluna nula.")
    sr, sc = np.sqrt(r), np.sqrt(c)
    S = (P - np.outer(r, c)) / np.outer(sr, sc)
    U, sig, Vt = np.linalg.svd(S, full_matrices=False)
    V = Vt.T
    lam_todos = sig ** 2
    nao_nulos = int((lam_todos > EPS_AUTOVALOR).sum())
    k = max(0, min(N.shape[0] - 1, N.shape[1] - 1, int(eixos), nao_nulos))
    U, V, sig = U[:, :k], V[:, :k], sig[:k]
    G = V * sig / sc[:, None]
    for e in range(k):  # convenção de sinal: a coluna de maior |coordenada| fica positiva
        j = int(np.argmax(np.abs(G[:, e])))  # argmax devolve o primeiro índice em empate
        if G[j, e] < 0:
            U[:, e] *= -1
            V[:, e] *= -1
    F = U * sig / sr[:, None]
    G = V * sig / sc[:, None]
    lam = sig ** 2
    perfis_l = P / r[:, None]
    perfis_c = P / c[None, :]
    d2_l = (((perfis_l - c[None, :]) ** 2) / c[None, :]).sum(axis=1)
    d2_c = (((perfis_c - r[:, None]) ** 2) / r[:, None]).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ctr_l = np.where(lam > 0, 100.0 * r[:, None] * F ** 2 / lam, 0.0)
        ctr_c = np.where(lam > 0, 100.0 * c[:, None] * G ** 2 / lam, 0.0)
        cos2_l = np.where(d2_l[:, None] > 0, F ** 2 / d2_l[:, None], 0.0)
        cos2_c = np.where(d2_c[:, None] > 0, G ** 2 / d2_c[:, None], 0.0)
    inercia = float((S ** 2).sum())
    return {"n": float(n), "r": r, "c": c, "autovalores": lam_todos[:nao_nulos], "inercia_total": inercia,
            "chi2": inercia * n, "k": k, "F": F, "G": G, "ctr_linhas": ctr_l, "ctr_colunas": ctr_c,
            "cos2_linhas": np.minimum(cos2_l, 1.0), "cos2_colunas": np.minimum(cos2_c, 1.0),
            "d2_linhas": d2_l, "d2_colunas": d2_c}


# ---------- análise sobre o corpus ----------

def escolher_termos(termos: list[str], contagens: np.ndarray, tamanhos: np.ndarray, n_termos: int, selecao: str,
                    min_freq: int) -> list[int]:
    """Índices das linhas escolhidas (ver docstring do módulo)."""
    F = contagens.sum(axis=1)
    cand = np.flatnonzero(F >= min_freq)
    if selecao == "freq":
        ordem = sorted(cand, key=lambda i: (-F[i], termos[i]))
    else:
        S = esp.matriz_de_scores(contagens[cand], tamanhos)
        forca = np.abs(S).max(axis=1) if len(cand) else np.zeros(0)
        ordem = [cand[i] for i in sorted(range(len(cand)), key=lambda i: (-forca[i], -F[cand[i]], termos[cand[i]]))]
    return [int(i) for i in ordem[:n_termos]]


def _r(x, casas=6):
    return [round(float(v), casas) for v in x]


def calcular(voc: dict, metas: list[dict], filtro, particao: str = "ano", por: str = "lema", filtrar: bool = True,
             n_termos: int = 100, selecao: str = "freq", eixos: int = EIXOS_MAX, min_freq: int = 5, tabela=None) -> dict:
    """AFC termo × parte. Levanta ValueError (parâmetros inválidos, < 2 partes, < 2 termos).

    ``tabela`` pronta = partição "classe" (classes da CHD, 7.1; ver ``reinert.tabela_por_classe``)."""
    if selecao not in SELECOES:
        raise ValueError(f"Seleção inválida '{selecao}': use 'freq' ou 'especificidade'.")
    if not 2 <= n_termos <= N_TERMOS_MAX:
        raise ValueError(f"n_termos deve estar entre 2 e {N_TERMOS_MAX}.")
    if not 1 <= eixos <= EIXOS_MAX:
        raise ValueError(f"eixos deve estar entre 1 e {EIXOS_MAX}.")
    termos, mat, tam, partes, excluidas = esp._tabela(voc, metas, filtro, particao, por, filtrar, tabela)
    if len(partes) < 2:
        raise ValueError(f"A AFC precisa de pelo menos 2 partes com tokens (partição '{particao}' tem {len(partes)}).")
    linhas = escolher_termos(termos, mat, tam, n_termos, selecao, min_freq)
    if len(linhas) < 2:
        raise ValueError("Menos de 2 termos passam na frequência mínima: reduza min_freq.")
    N = mat[linhas]
    vivas = np.flatnonzero(N.sum(axis=0) > 0)
    for j in np.flatnonzero(N.sum(axis=0) == 0):
        excluidas.append({"chave": partes[j]["chave"], "rotulo": partes[j]["rotulo"],
                          "motivo": "nenhuma ocorrência dos termos escolhidos"})
    partes = [partes[j] for j in vivas]
    N = N[:, vivas]
    if len(partes) < 2:
        raise ValueError("Menos de 2 partes com ocorrências dos termos escolhidos.")
    ac = analise_de_correspondencia(N, eixos)
    k, total = ac["k"], ac["inercia_total"]
    lam = ac["autovalores"]
    acum = np.cumsum(lam) / total * 100 if total > 0 else np.zeros_like(lam)
    tabela_eixos = [{"eixo": i + 1, "autovalor": round(float(v), 8), "pct": round(float(v / total * 100), 4) if total else 0.0,
                     "pct_acumulado": round(float(acum[i]), 4)} for i, v in enumerate(lam)]
    mensagem = None
    if len(partes) == 2:
        mensagem = "Com 2 partes a AFC tem um único eixo (o mapa é uma reta): use uma partição com 3 ou mais partes."
    elif k == 0:
        mensagem = "A tabela não tem inércia (perfis idênticos): não há eixos."
    inercia_l = ac["r"] * ac["d2_linhas"]
    inercia_c = ac["c"] * ac["d2_colunas"]
    linhas_out = [{
        "termo": termos[i], "freq": int(N[a].sum()), "massa": round(float(ac["r"][a]), 6),
        "inercia_pct": round(float(inercia_l[a] / total * 100), 4) if total else 0.0,
        "coord": _r(ac["F"][a]), "ctr": _r(ac["ctr_linhas"][a], 4), "cos2": _r(ac["cos2_linhas"][a], 4),
        "qualidade": round(float(ac["cos2_linhas"][a].sum()), 4),
    } for a, i in enumerate(linhas)]
    colunas_out = [{
        "chave": p["chave"], "rotulo": p["rotulo"], "documentos": p["documentos"], "tokens": p["tokens"],
        "freq": int(N[:, b].sum()), "massa": round(float(ac["c"][b]), 6),
        "inercia_pct": round(float(inercia_c[b] / total * 100), 4) if total else 0.0,
        "coord": _r(ac["G"][b]), "ctr": _r(ac["ctr_colunas"][b], 4), "cos2": _r(ac["cos2_colunas"][b], 4),
        "qualidade": round(float(ac["cos2_colunas"][b].sum()), 4),
    } for b, p in enumerate(partes)]
    return {
        "particao": particao, "por": por, "n_linhas": len(linhas_out), "n_colunas": len(colunas_out), "k": k,
        "n": int(ac["n"]), "inercia_total": round(total, 8), "chi2": round(ac["chi2"], 4),
        "eixos": tabela_eixos, "linhas": linhas_out, "colunas": colunas_out,
        "ctr_media_linhas": round(100 / len(linhas_out), 4), "ctr_media_colunas": round(100 / len(colunas_out), 4),
        "partes_excluidas": excluidas, "mensagem": mensagem,
        "parametros": {"particao": particao, "por": por, "vazias": "filtrar" if filtrar else "manter",
                       "n_termos": n_termos, "selecao": selecao, "eixos": eixos, "min_freq": min_freq},
        "convencao_sinal": "Em cada eixo, a parte de maior |coordenada| fica positiva.",
        "metodologia": METODOLOGIA, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE,
        "nao_equivalente": NAO_EQUIVALENTE,
    }


def particao_do_instantaneo(metas: list[dict]) -> str | None:
    """Grupo com >= 3 grupos definidos; senão ano com >= 3 anos; senão documento (>= 3 documentos); senão None."""
    p = esp.particao_do_instantaneo(metas, 3)
    if p:
        return p
    return "documento" if len(metas) >= 3 else None
