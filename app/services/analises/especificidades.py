"""6.2 - Especificidades por parte (modelo hipergeométrico de Lafon), como no TXM, no Lexico e no IRaMuTeQ.

Equivale às "Especificidades" do TXM e do Lexico e às especificidades do IRaMuTeQ. **Não** é a keyness da 6.1
(G² de cada lado contra o resto, aproximação assintótica do qui-quadrado): aqui a probabilidade é exata.

Partição
--------
O corpus é dividido em **partes** disjuntas que o cobrem por inteiro: ``particao`` = ``grupo`` ("sem grupo" é uma
parte), ``ano`` ("s/ano" é uma parte) ou ``documento``. O núcleo (``tabela_de_especificidades``) recebe só a tabela
termo × parte e os tamanhos das partes, então as classes da CHD (7.1, segmentos) entram depois como outra partição
sem mudar a estatística. Partes sem tokens ficam fora (``partes_excluidas``).

Universo de tokens
------------------
O mesmo da keyness (6.1) e do painel Frequências: só o corpo (``incluir`` = 1), tokens com >= 2 letras, por lema
(padrão, D5), forma ou termo (4.3). As palavras vazias saem **da lista de termos** (na consulta), mas os tamanhos
t (da parte) e T (do corpus) contam todos os tokens do universo, com as palavras vazias.

Modelo (Lafon 1980; Lebart, Salem & Berry 1998, cap. 6)
-------------------------------------------------------
Para o termo de frequência F no corpus (T tokens) e a parte com t tokens, a frequência X do termo na parte é
hipergeométrica: tirar t tokens sem reposição de uma urna de T, dos quais F são o termo. Com f = frequência
observada na parte e ``esperada`` = F·t/T (média de X):

- se f >= esperada: P = P(X >= f) (cauda superior)  ->  ``score`` = −log10 P  (>= 0, termo sobre-representado);
- se f <  esperada: P = P(X <= f) (cauda inferior)  ->  ``score`` = +log10 P  (<= 0, termo sub-representado).

O pacote R ``textometry`` 0.1.7 (CRAN, equipe do TXM) decide o lado pela **média**, como aqui (conferido na 12.2,
docs/validacao_cruzada.md: scores iguais a ±5e-4, o arredondamento); se alguma versão do TXM decidir pela **moda** da
hipergeométrica, as duas convenções só diferem para f entre a moda e a média, onde |score| < 0,5 (sempre "banal";
máximo de 0,43 no corpus MLR por ano), então as listas de específicos são iguais.

Cálculo: ``scipy.stats.hypergeom.sf``/``cdf`` (Boost, vetorizado); quando a probabilidade fica abaixo de 1e-250
(perto do limite do ponto flutuante, ~1e-308) recalcula-se em escala logarítmica (``logsf``/``logcdf``), para não
haver estouro por baixo. **Teto**: |score| é limitado a ``TETO`` = 50 (P < 1e-50): ``score`` = ±50 e
``acima_do_teto`` = True (a interface mostra "> 50"); a ordenação usa o valor sem teto (``_bruto``), que pode ser
maior que 50 com precisão, e só é infinito se nem o logaritmo couber em float.

Banal e limiar
--------------
|score| < ``limiar`` (padrão 2, isto é, P > 0,01) = **banal**: o termo não é específico da parte. As listas por parte
trazem os específicos positivos (score >= limiar, do maior para o menor) e negativos (score <= −limiar, do mais
negativo), até ``limite`` de cada. Só entram termos com frequência no corpus F >= ``min_freq`` (padrão 5). Não há
correção para comparações múltiplas (como no TXM): o score é um indicador de ordenação, não um teste.
"""
import math
from collections import Counter

import numpy as np
from scipy.stats import hypergeom

from app.services.analises import dados, frequencias

PARTICOES = ("grupo", "ano", "documento")
# "classe" (CHD, 7.1): a tabela termo × classe vem pronta de ``reinert.tabela_por_classe`` (argumento ``tabela``)
PARTICAO_CLASSE = "classe"
TETO = 50.0
LIMIAR_PADRAO = 2.0
P_MINIMO_DIRETO = 1e-250  # abaixo disto, refaz em escala logarítmica
FERRAMENTA_EQUIVALENTE = "TXM Especificidades, Lexico, IRaMuTeQ especificidades"
NAO_EQUIVALENTE = "keyness LL contra o resto (6.1)"
METODOLOGIA = (
    "Modelo hipergeométrico de Lafon (1980): para cada termo e parte, score = −log10 P(X >= f) se f >= F·t/T "
    "(sobre-representado) ou +log10 P(X <= f) se f < F·t/T (sub-representado), com X ~ Hipergeométrica(T, F, t). "
    "|score| < 2 (P > 0,01) = banal; teto de 50 (exibido como \"> 50\"). Tamanhos t e T com todas as palavras do "
    "corpo (>= 2 letras); palavras vazias filtradas na lista de termos."
)


# ---------- estatística (funções puras) ----------

def _log10_cauda(f: np.ndarray, F: np.ndarray, t: np.ndarray, T: int, superior: np.ndarray) -> np.ndarray:
    """log10 da cauda escolhida (P(X >= f) onde ``superior``, senão P(X <= f)), vetorizado e sem estouro por baixo."""
    f, F, t = (np.asarray(x, dtype=np.int64) for x in (f, F, t))
    sup = np.asarray(superior, dtype=bool)
    p = np.where(sup, hypergeom.sf(f - 1, T, F, t), hypergeom.cdf(f, T, F, t))
    p = np.clip(p, 0.0, 1.0)
    saida = np.full(p.shape, 0.0)
    ok = p >= P_MINIMO_DIRETO
    saida[ok] = np.log10(p[ok])
    for i in np.flatnonzero(~ok):  # raros: probabilidades minúsculas em escala log (logsumexp da pmf)
        if sup.flat[i]:
            ln = hypergeom.logsf(f.flat[i] - 1, T, F.flat[i], t.flat[i])
        else:
            ln = hypergeom.logcdf(f.flat[i], T, F.flat[i], t.flat[i])
        saida.flat[i] = float(ln) / math.log(10.0)
    return np.minimum(saida, 0.0)


def scores(f, F, t, T: int) -> np.ndarray:
    """Score de especificidade com sinal e **sem teto** (arrays de mesma forma; T = tokens do corpus)."""
    f, F, t = np.broadcast_arrays(*(np.asarray(x, dtype=np.int64) for x in (f, F, t)))
    esperada = F * t / T
    superior = f >= esperada
    lg = _log10_cauda(f, F, t, T, superior)
    s = np.where(superior, -lg, lg)
    return s + 0.0  # converte −0,0 em 0,0


def score(f: int, F: int, t: int, T: int) -> float:
    """Score de um termo numa parte (sem teto). Ver docstring do módulo."""
    return float(scores(np.array([f]), np.array([F]), np.array([t]), T)[0])


def com_teto(s: float, teto: float = TETO) -> tuple[float, bool]:
    """(score limitado a ±teto, se passou do teto)."""
    if abs(s) > teto:
        return math.copysign(teto, s), True
    return float(s), False


# ---------- partes e tabela termo × parte ----------

def partes_dos_documentos(metas: list[dict], particao: str) -> list[dict]:
    """Partes [{"chave", "rotulo", "metas"}] em ordem estável (a mesma das tendências)."""
    if particao not in PARTICOES:
        raise ValueError(f"Partição inválida '{particao}': use {', '.join(PARTICOES)}.")
    return frequencias.unidades(metas, particao)


def tabela_lexical(voc: dict, partes: list[dict], filtro, por: str = "lema", filtrar: bool = True):
    """(termos, contagens K×P, tamanhos P, partes válidas, partes excluídas). Tamanhos com todas as palavras."""
    contagens: list[Counter] = []
    tamanhos, validas, excluidas = [], [], []
    for p in partes:
        docs = frequencias._docs_do_escopo(voc, p["metas"])
        tokens = sum(d["tokens"] for d in docs)
        if tokens == 0:
            excluidas.append({"chave": p["chave"], "rotulo": p["rotulo"], "motivo": "parte sem tokens"})
            continue
        c: Counter = Counter()
        for d in docs:
            c.update(frequencias.contagem_documento(d, filtro, por, filtrar))
        contagens.append(c)
        tamanhos.append(tokens)
        validas.append({"chave": p["chave"], "rotulo": p["rotulo"], "documentos": len(docs), "tokens": tokens,
                        "ids": [m["id"] for m in p["metas"]]})
    termos = sorted(set().union(*contagens)) if contagens else []
    mat = np.zeros((len(termos), len(validas)), dtype=np.int64)
    linha = {t: i for i, t in enumerate(termos)}
    for j, c in enumerate(contagens):
        for t, v in c.items():
            mat[linha[t], j] = v
    return termos, mat, np.array(tamanhos, dtype=np.int64), validas, excluidas


def matriz_de_scores(contagens: np.ndarray, tamanhos: np.ndarray, total: int | None = None) -> np.ndarray:
    """Scores (sem teto) de uma tabela termo × parte. ``total`` = T (padrão: soma dos tamanhos)."""
    T = int(tamanhos.sum()) if total is None else int(total)
    F = contagens.sum(axis=1, keepdims=True)
    return scores(contagens, F, tamanhos[None, :], T)


def _item(termo: str, f: int, F: int, t: int, T: int, s: float) -> dict:
    sc, acima = com_teto(s)
    return {"termo": termo, "f": int(f), "F": int(F), "esperada": round(F * t / T, 3), "score": round(sc, 3),
            "acima_do_teto": acima, "por_10k": round(f / t * 10000, 2)}


def tabela_de_especificidades(termos: list[str], contagens: np.ndarray, tamanhos: np.ndarray, partes: list[dict],
                              min_freq: int = 5, limiar: float = LIMIAR_PADRAO, limite: int = 20,
                              termos_matriz: list[str] | None = None, n_matriz: int = 3) -> dict:
    """Núcleo: específicos positivos e negativos de cada parte e matriz parte × termo para os termos escolhidos.

    ``termos_matriz`` omitido = união dos ``n_matriz`` mais específicos (positivos) de cada parte."""
    T = int(tamanhos.sum())
    F = contagens.sum(axis=1)
    sel = np.flatnonzero(F >= min_freq)
    sub = contagens[sel]
    S = matriz_de_scores(sub, tamanhos, T) if len(sel) else np.zeros((0, len(partes)))
    nomes = [termos[i] for i in sel]
    saida_partes = []
    for j, p in enumerate(partes):
        col = S[:, j]
        pos = [i for i in np.flatnonzero(col >= limiar)]
        neg = [i for i in np.flatnonzero(col <= -limiar)]
        pos.sort(key=lambda i: (-col[i], -sub[i, j], nomes[i]))
        neg.sort(key=lambda i: (col[i], -F[sel[i]], nomes[i]))
        t = int(tamanhos[j])
        saida_partes.append({
            **{k: p[k] for k in ("chave", "rotulo", "documentos", "tokens") if k in p},
            "n_positivas": len(pos), "n_negativas": len(neg),
            "positivas": [_item(nomes[i], sub[i, j], F[sel[i]], t, T, col[i]) for i in pos[:limite]],
            "negativas": [_item(nomes[i], sub[i, j], F[sel[i]], t, T, col[i]) for i in neg[:limite]],
        })
    if termos_matriz is None:
        termos_matriz = list(dict.fromkeys(i["termo"] for p in saida_partes for i in p["positivas"][:n_matriz]))
    idx = {t: i for i, t in enumerate(nomes)}
    escolhidos = [t for t in termos_matriz if t in idx]
    matriz = [[com_teto(S[idx[t], j])[0] for t in escolhidos] for j in range(len(partes))]
    return {"T": T, "termos_testados": len(sel), "partes": saida_partes,
            "matriz": {"termos": escolhidos, "partes": [p["chave"] for p in partes],
                       "scores": [[round(v, 3) for v in linha] for linha in matriz]}}


# ---------- análise sobre o corpus ----------

def _tabela(voc, metas, filtro, particao, por, filtrar, tabela):
    if tabela is not None:
        termos, mat, tam, partes, excluidas = tabela
        return termos, mat, tam, partes, list(excluidas)
    if particao == PARTICAO_CLASSE:
        raise ValueError("A partição 'classe' precisa da CHD de Reinert (7.1) calculada.")
    return tabela_lexical(voc, partes_dos_documentos(metas, particao), filtro, por, filtrar)


def _parametros(particao, por, filtrar, min_freq, limiar, limite) -> dict:
    return {"particao": particao, "por": por, "vazias": "filtrar" if filtrar else "manter", "min_freq": min_freq,
            "limiar": limiar, "limite": limite, "teto": TETO}


def calcular(voc: dict, metas: list[dict], filtro, particao: str = "ano", por: str = "lema", filtrar: bool = True,
             min_freq: int = 5, limiar: float = LIMIAR_PADRAO, limite: int = 20,
             termos_matriz: list[str] | None = None, tabela=None) -> dict:
    """Especificidades de cada parte da partição. Levanta ValueError (partição inválida, < 2 partes com tokens).

    ``tabela`` = (termos, contagens, tamanhos, partes, excluídas) pronta (partição "classe" da CHD, 7.1)."""
    termos, mat, tam, partes, excluidas = _tabela(voc, metas, filtro, particao, por, filtrar, tabela)
    if len(partes) < 2:
        raise ValueError(f"Especificidades precisam de pelo menos 2 partes com tokens (partição '{particao}' tem {len(partes)}).")
    r = tabela_de_especificidades(termos, mat, tam, partes, min_freq, limiar, max(0, limite), termos_matriz)
    return {"particao": particao, "por": por, **r, "partes_excluidas": excluidas, "limiar": limiar, "teto": TETO,
            "parametros": _parametros(particao, por, filtrar, min_freq, limiar, limite),
            "metodologia": METODOLOGIA, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE,
            "nao_equivalente": NAO_EQUIVALENTE}


def do_termo(voc: dict, metas: list[dict], filtro, termo: str, particao: str = "ano", por: str = "lema",
             filtrar: bool = True, limiar: float = LIMIAR_PADRAO, tabela=None) -> dict:
    """Score de um termo em todas as partes (gráfico de especificidades do TXM). ValueError se o termo não ocorre."""
    alvo = dados.normalizar(termo.strip()) if termo else ""
    termos, mat, tam, partes, excluidas = _tabela(voc, metas, filtro, particao, por, filtrar, tabela)
    if alvo not in termos:
        raise ValueError(f"O termo '{termo}' não ocorre no corpus (com a unidade e o filtro de palavras vazias atuais).")
    linha = mat[termos.index(alvo)]
    T, F = int(tam.sum()), int(linha.sum())
    s = scores(linha, np.full(len(linha), F), tam, T)
    itens = []
    for j, p in enumerate(partes):
        it = _item(alvo, linha[j], F, int(tam[j]), T, s[j])
        itens.append({"chave": p["chave"], "rotulo": p["rotulo"], "tokens": p["tokens"], "documentos": p["documentos"],
                      **{k: it[k] for k in ("f", "esperada", "score", "acima_do_teto", "por_10k")},
                      "banal": abs(it["score"]) < limiar})
    return {"termo": alvo, "particao": particao, "por": por, "F": F, "T": T, "limiar": limiar, "teto": TETO,
            "partes": itens, "partes_excluidas": excluidas, "metodologia": METODOLOGIA,
            "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE, "nao_equivalente": NAO_EQUIVALENTE}


# ---------- instantâneo (etapa) ----------

def particao_do_instantaneo(metas: list[dict], minimo: int) -> str | None:
    """Grupo se houver >= ``minimo`` grupos definidos; senão ano (>= ``minimo`` anos); senão None."""
    grupos = {dados.chave_grupo(m) for m in metas} - {dados.SEM_GRUPO}
    if len(grupos) >= minimo:
        return "grupo"
    anos = {dados.chave_ano(m) for m in metas} - {dados.SEM_ANO}
    if len(anos) >= minimo:
        return "ano"
    return None
