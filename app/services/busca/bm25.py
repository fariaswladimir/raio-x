"""15.13 - BM25 (Okapi) e fusão por ranking recíproco (RRF), sem dependências além da biblioteca padrão.

BM25 (Robertson & Zaragoza, 2009), variante com idf não negativo (a mesma do Lucene):

    idf(t)   = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))
    score(d) = soma sobre os termos t distintos da consulta de  idf(t) * f * (k1 + 1) / (f + k1 * (1 - b + b * |d| / avgdl))

com f = frequência do termo em d, |d| = nº de termos de d, avgdl = média de |d|, k1 = 1,5 e b = 0,75 (valores usuais).

RRF (Cormack, Clarke & Büttcher, 2009): score(d) = soma sobre os rankings r de 1 / (k + posição_r(d)), com k = 60 e
posição começando em 1; documentos ausentes de um ranking não recebem parcela dele.

Termos: minúsculas, sem acentos, só letras/dígitos, >= 2 caracteres, sem palavras vazias (en, pt, es) e com um radical
mínimo (plural em "s"), para que "limitations" case com "limitation". Sem lematização: é uma busca lexical.
"""
import math
import re
import unicodedata
from collections import Counter

from app.services.palavras_vazias import PALAVRAS

K1 = 1.5
B = 0.75
K_RRF = 60
_PALAVRA = re.compile(r"[a-z0-9]+")
_VAZIAS = frozenset(sum((list(PALAVRAS[k]) for k in ("en", "pt", "es") if k in PALAVRAS), []))


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _radical(t: str) -> str:
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def termos(texto: str) -> list[str]:
    """Termos de busca de um texto (ver o cabeçalho do módulo)."""
    saida = []
    for t in _PALAVRA.findall(_sem_acento(texto or "").lower()):
        if len(t) < 2 or _sem_acento(t) in _VAZIAS or t in _VAZIAS:
            continue
        saida.append(_radical(t))
    return saida


class IndiceBM25:
    def __init__(self, textos: list[str], k1: float = K1, b: float = B):
        self.k1, self.b = k1, b
        self.tf = [Counter(termos(t)) for t in textos]
        self.tam = [sum(c.values()) for c in self.tf]
        self.n = len(textos)
        self.avgdl = (sum(self.tam) / self.n) if self.n else 0.0
        self.df: Counter = Counter()
        for c in self.tf:
            self.df.update(c.keys())

    def idf(self, termo: str) -> float:
        n_t = self.df.get(termo, 0)
        return math.log(1 + (self.n - n_t + 0.5) / (n_t + 0.5))

    def pontuar(self, consulta: str) -> list[float]:
        q = list(dict.fromkeys(termos(consulta)))
        notas = [0.0] * self.n
        if not q or not self.n:
            return notas
        idf = {t: self.idf(t) for t in q}
        for i, c in enumerate(self.tf):
            norm = self.k1 * (1 - self.b + self.b * (self.tam[i] / self.avgdl if self.avgdl else 0))
            s = 0.0
            for t in q:
                f = c.get(t)
                if f:
                    s += idf[t] * f * (self.k1 + 1) / (f + norm)
            notas[i] = s
        return notas

    def ranking(self, consulta: str, k: int = 10) -> list[tuple[int, float]]:
        """[(índice, nota)] das ``k`` maiores notas > 0; empate: índice menor (determinístico)."""
        notas = self.pontuar(consulta)
        ordem = sorted((i for i, s in enumerate(notas) if s > 0), key=lambda i: (-notas[i], i))
        return [(i, notas[i]) for i in ordem[:k]]


def rrf(rankings: list[list], k: int = K_RRF) -> list[tuple[object, float]]:
    """Fusão por ranking recíproco. ``rankings``: listas de identificadores, do melhor ao pior. Devolve [(id, nota)]
    em ordem decrescente de nota (empate: quem aparece primeiro na 1ª lista em que aparece)."""
    notas: dict = {}
    ordem: dict = {}
    for r in rankings:
        for pos, ident in enumerate(r, start=1):
            notas[ident] = notas.get(ident, 0.0) + 1.0 / (k + pos)
            ordem.setdefault(ident, len(ordem))
    return sorted(notas.items(), key=lambda kv: (-kv[1], ordem[kv[0]]))
