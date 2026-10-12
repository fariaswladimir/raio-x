"""17.2 - Palavras-chave e padrões do protocolo, com reconhecimento de lema.

Sintaxe de cada termo (campo ``palavras_chave`` do item):
- ``agent`` : palavra; casa a forma escrita **ou o lema** (``agents``, ``agent's``), sem diferenciar caixa nem acentos;
- ``agent*`` : curinga ``*`` (``agent``, ``agents``, ``agentic``); vale para a forma e para o lema;
- ``"sample size"`` ou ``sample size`` : frase: palavras consecutivas, cada uma casando por forma ou lema;
- ``/n\\s*=\\s*\\d+/`` : expressão regular sobre o texto da frase (sem diferenciar caixa).
A tokenização e a lematização são as mesmas da etapa 4.1 (``tokenizacao``): números ficam fora dos tokens (use ``/regex/`` para eles).
"""
import re
import unicodedata
from dataclasses import dataclass, field

from app.services import tokenizacao as tk


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)).lower()


@dataclass
class Acerto:
    termo: str
    ini: int  # posição de caractere no texto da frase
    fim: int
    tok_i: int
    tok_j: int  # inclusive


@dataclass
class FraseIndexada:
    texto: str
    toks: list = field(default_factory=list)  # (norm sem acento, lema sem acento, ini, fim)


def indexar(texto: str, lematizador: "tk.Lematizador") -> FraseIndexada:
    toks = []
    for forma, ini, fim in tk.tokenizar(texto):
        norm = tk.normalizar(forma)
        toks.append((sem_acento(norm), sem_acento(lematizador.lema(forma, norm)), ini, fim))
    return FraseIndexada(texto, toks)


class Termo:
    def __init__(self, bruto: str, lematizador: "tk.Lematizador"):
        self.bruto = bruto
        self.regex = None
        self.elementos: list = []
        b = bruto.strip()
        if len(b) > 2 and b.startswith("/") and b.endswith("/"):
            self.regex = re.compile(b[1:-1], re.IGNORECASE)
            return
        b = b.strip("\"“”'")
        for palavra in b.split():
            norm = tk.normalizar(palavra)
            if "*" in norm:
                padrao = "".join(".*" if c == "*" else re.escape(sem_acento(c)) for c in norm)
                self.elementos.append(("rx", re.compile(padrao)))
            else:
                self.elementos.append(("conj", {sem_acento(norm), sem_acento(lematizador.lema(palavra, norm))}))

    def _casa(self, elem, tok) -> bool:
        tipo, v = elem
        if tipo == "conj":
            return tok[0] in v or tok[1] in v
        return bool(v.fullmatch(tok[0]) or v.fullmatch(tok[1]))

    def achar(self, fi: FraseIndexada) -> list[Acerto]:
        saida = []
        if self.regex is not None:
            for m in self.regex.finditer(fi.texto):
                ti = next((k for k, t in enumerate(fi.toks) if t[3] > m.start()), len(fi.toks) - 1 if fi.toks else 0)
                tj = max(ti, max((k for k, t in enumerate(fi.toks) if t[2] < m.end()), default=ti))
                saida.append(Acerto(self.bruto, m.start(), m.end(), ti, tj))
            return saida
        n = len(self.elementos)
        if not n:
            return saida
        for i in range(len(fi.toks) - n + 1):
            if all(self._casa(self.elementos[k], fi.toks[i + k]) for k in range(n)):
                saida.append(Acerto(self.bruto, fi.toks[i][2], fi.toks[i + n - 1][3], i, i + n - 1))
        return saida


def compilar(lista: list[str], lematizador: "tk.Lematizador") -> list[Termo]:
    saida = []
    for b in lista:
        t = Termo(b, lematizador)
        if t.regex is not None or t.elementos:
            saida.append(t)
    return saida


def acertos(termos: list[Termo], fi: FraseIndexada) -> list[Acerto]:
    """Todos os acertos de todos os termos na frase, ordenados por posição."""
    saida: list[Acerto] = []
    for t in termos:
        saida.extend(t.achar(fi))
    return sorted(saida, key=lambda a: (a.ini, a.fim))
