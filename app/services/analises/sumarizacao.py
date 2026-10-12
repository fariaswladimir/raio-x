"""15.5 - Sumarização extrativa por documento: TextRank, LexRank e MMR (frases do corpo, com página e seção).

Candidatas
----------
Frases de ``texto_documento.py`` (corpo, sem referências e sem ruído) **elegíveis**: 8 a 70 palavras; terminam em
pontuação final; sem URL/DOI/``©``/``arXiv``; menos de 15% de dígitos; menos da metade das palavras em maiúscula inicial
(listas de autores e afiliações); não começam por ``Source``/``Note``/``Figure``/``Table``/``Fonte``/``Nota``/``Figura``/``Tabela``
(legendas, com número de página opcional na frente) e não têm 2 ou mais "número + maiúscula" (sumários e listas de figuras). Exclui-se assim boa parte de títulos, legendas, rodapés e linhas de tabela.

Vetores
-------
Cada frase vira o conjunto/contagem dos **lemas** (simplemma) das palavras não vazias (2+ letras). TF-IDF por frase:
``tf = contagem``, ``idf = ln(N/df) + 1`` (N = frases candidatas), norma L2. Similaridade = cosseno.

Métodos (a nota de cada frase é a "centralidade" da frase no documento)
-----------------------------------------------------------------------
- **TextRank** (Mihalcea e Tarau, 2004): grafo ponderado completo; peso = ``|palavras em comum| / (ln|S1| + ln|S2|)`` sobre os
  conjuntos de lemas (a medida do artigo; 0 se algum conjunto tem 1 lema); PageRank ponderado, d = 0,85.
- **LexRank** (Erkan e Radev, 2004): cosseno TF-IDF entre frases; aresta se cosseno >= ``limiar`` (0,1); PageRank com
  matriz de transição = adjacência normalizada por linha (centralidade de grau suavizada), d = 0,85 (a "teleportação" de
  0,15 do artigo).
- **MMR** (Carbonell e Goldstein, 1998): escolhe iterativamente a frase que maximiza
  ``λ·cos(frase, centroide do documento) - (1 - λ)·max cos(frase, já escolhidas)``, λ = 0,7 (centroide = média dos vetores
  das frases, normalizada). Não depende de PageRank; a redundância é tratada na própria seleção. As duas outras
  não tratam redundância (frases quase iguais podem entrar juntas).

Seleção
-------
``n`` frases (padrão 5): as ``n`` de maior nota (TextRank e LexRank, empate = frase mais cedo) ou as escolhidas pelo MMR, **devolvidas na
ordem original do texto**, cada uma com página, seção, posição (índice da frase), ordem de seleção (``classificacao``) e nota.
Tudo é determinístico (sem sementes). PageRank por iteração de potência (tol 1e-9, 200 iterações).
"""
import math
import re
from collections import Counter

import numpy as np

from app.services.analises import palavras_chave, texto_documento

METODOS = ("textrank", "lexrank", "mmr")
PADRAO = {"n": 5, "lambda": 0.7, "limiar": 0.1, "min_palavras": 8, "max_palavras": 70}
_RUIM = re.compile(r"https?://|www\.|doi\.org|©|arxiv|\bdoi:", re.IGNORECASE)
_FINAL = re.compile(r"[.?!…][\"'”’)\]]*\s*$")
_LEGENDA = re.compile(r"^\s*(?:\d{1,3}\s+)?(?:source|sources|note|notes|figure|fig\.|table|chart|box|fonte|nota|figura|tabela|gráfico|quadro)\b", re.IGNORECASE)
_SUMARIO = re.compile(r"\s\d{1,3}\s+(?=[A-ZÀ-Ö])")  # "... 29 Generative AI helps ... 33 Generative AI reduces ...": sumário/lista de figuras


def parametros(parametros_projeto: dict | None) -> dict:
    p = dict(PADRAO)
    extra = (parametros_projeto or {}).get("documento_extra") or {}
    if "resumo_frases" in extra:
        p["n"] = int(extra["resumo_frases"])
    sub = extra.get("sumarizacao") if isinstance(extra.get("sumarizacao"), dict) else {}
    for k in ("lambda", "limiar", "min_palavras", "max_palavras"):
        if k in sub:
            p[k] = sub[k]
    return p


def elegivel(frase: str, min_palavras: int = 8, max_palavras: int = 70) -> bool:
    ws = texto_documento.palavras_da_frase(frase)
    if not min_palavras <= len(ws) <= max_palavras or not _FINAL.search(frase) or _RUIM.search(frase):
        return False
    if _LEGENDA.match(frase) or len(_SUMARIO.findall(frase)) >= 2:
        return False
    if sum(c.isdigit() for c in frase) / max(1, len(frase)) > 0.15:
        return False
    return sum(1 for w in ws if w[:1].isupper()) / len(ws) < 0.5


def _conjuntos(frases: list[dict], idioma: str | None, sw: frozenset) -> list[Counter]:
    saida = []
    for f in frases:
        c: Counter = Counter()
        for w in texto_documento.palavras_da_frase(f["texto"]):
            b = w.lower()
            if len(b) >= 2 and b not in sw:
                c[palavras_chave._lema(b, idioma)] += 1
        saida.append(c)
    return saida


def matriz_tfidf(contagens: list[Counter]) -> np.ndarray:
    """Matriz frases x lemas, TF-IDF (``idf = ln(N/df) + 1``) com norma L2 por linha."""
    vocab = {t: j for j, t in enumerate(sorted({t for c in contagens for t in c}))}
    n = len(contagens)
    x = np.zeros((n, len(vocab)), dtype=np.float32)
    df = np.zeros(len(vocab))
    for i, c in enumerate(contagens):
        for t, f in c.items():
            x[i, vocab[t]] = f
            df[vocab[t]] += 1
    idf = (np.log(n / np.maximum(df, 1)) + 1.0).astype(np.float32)
    x *= idf
    normas = np.sqrt((x ** 2).sum(axis=1, keepdims=True))
    return np.divide(x, normas, out=np.zeros_like(x), where=normas > 0)


def pagerank(w: np.ndarray, d: float = 0.85, tol: float = 1e-9, max_iter: int = 200) -> np.ndarray:
    """PageRank por iteração de potência sobre pesos ``w`` (linhas sem saída distribuem uniformemente)."""
    n = w.shape[0]
    if n == 0:
        return np.zeros(0)
    w = np.asarray(w, dtype=np.float64)
    soma = w.sum(axis=1, keepdims=True)
    p = np.divide(w, soma, out=np.full_like(w, 1.0 / n), where=soma > 0)
    r = np.full(n, 1.0 / n)
    for _ in range(max_iter):
        novo = (1 - d) / n + d * (p.T @ r)
        if np.abs(novo - r).sum() < tol:
            r = novo
            break
        r = novo
    return r


def notas_textrank(contagens: list[Counter]) -> np.ndarray:
    vocab = {t: k for k, t in enumerate(sorted({t for c in contagens for t in c}))}
    b = np.zeros((len(contagens), len(vocab)), dtype=np.float32)
    for i, c in enumerate(contagens):
        for t in c:
            b[i, vocab[t]] = 1.0
    tam = b.sum(axis=1)
    log = np.where(tam > 1, np.log(np.maximum(tam, 1)), 0.0)
    comum = b @ b.T
    den = log[:, None] + log[None, :]
    w = np.divide(comum, den, out=np.zeros_like(comum, dtype=np.float64), where=den > 0)
    np.fill_diagonal(w, 0.0)
    return pagerank(w)


def notas_lexrank(x: np.ndarray, limiar: float = 0.1) -> np.ndarray:
    s = x @ x.T
    adj = (s >= limiar).astype(np.float64)
    np.fill_diagonal(adj, 0.0)
    return pagerank(adj)


def selecionar_mmr(x: np.ndarray, n: int, lam: float = 0.7) -> tuple[list[int], dict[int, float]]:
    """Índices escolhidos (na ordem de seleção) e a nota MMR de cada um no momento da escolha."""
    centro = x.mean(axis=0)
    norma = float(np.linalg.norm(centro))
    centro = centro / norma if norma > 0 else centro
    relevancia = x @ centro
    s = x @ x.T
    escolhidos: list[int] = []
    notas: dict[int, float] = {}
    livres = set(range(x.shape[0]))
    while livres and len(escolhidos) < n:
        melhor, melhor_nota = None, -math.inf
        for i in sorted(livres):
            redund = max((float(s[i, j]) for j in escolhidos), default=0.0)
            nota = lam * float(relevancia[i]) - (1 - lam) * redund
            if nota > melhor_nota + 1e-12:
                melhor, melhor_nota = i, nota
        escolhidos.append(melhor)
        notas[melhor] = melhor_nota
        livres.discard(melhor)
    return escolhidos, notas


def resumir(frases: list[dict], idioma: str | None, metodo: str, parametros_projeto: dict | None = None,
            n: int | None = None) -> dict:
    """Resumo extrativo: ``{"metodo", "n", "n_candidatas", "frases": [{i, texto, pagina, secao, classificacao, nota}]}``."""
    if metodo not in METODOS:
        raise ValueError(f"Método inválido '{metodo}': use textrank, lexrank ou mmr.")
    p = parametros(parametros_projeto)
    n = int(p["n"] if n is None else n)
    if n < 1:
        raise ValueError("O número de frases deve ser >= 1.")
    cand = [f for f in frases if elegivel(f["texto"], p["min_palavras"], p["max_palavras"])]
    base = {"metodo": metodo, "n": n, "n_candidatas": len(cand), "total_frases": len(frases)}
    if len(cand) == 0:
        return {**base, "frases": []}
    sw = palavras_chave.vazias(idioma, parametros_projeto)
    contagens = _conjuntos(cand, idioma, sw)
    x = matriz_tfidf(contagens)
    if metodo == "mmr":
        ordem_sel, notas = selecionar_mmr(x, n, float(p["lambda"]))
        rank = {i: k + 1 for k, i in enumerate(ordem_sel)}
    else:
        notas_v = notas_textrank(contagens) if metodo == "textrank" else notas_lexrank(x, float(p["limiar"]))
        ordem_sel = sorted(range(len(cand)), key=lambda i: (-notas_v[i], i))[:n]
        rank = {i: k + 1 for k, i in enumerate(ordem_sel)}
        notas = {i: float(notas_v[i]) for i in ordem_sel}
    saida = []
    for i in sorted(ordem_sel):
        f = cand[i]
        saida.append({"i": f["i"], "texto": f["texto"], "pagina": f["pagina"], "secao": f["secao"],
                      "titulo_secao": f.get("titulo_secao"), "classificacao": rank[i], "nota": round(notas[i], 5)})
    return {**base, "frases": saida}


def resumir_todos(frases: list[dict], idioma: str | None, parametros_projeto: dict | None = None, n: int | None = None) -> dict:
    return {m: resumir(frases, idioma, m, parametros_projeto, n) for m in METODOS}
