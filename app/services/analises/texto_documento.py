"""Texto do corpo de um documento, dividido em frases com página e seção (base de 15.3, 15.4 e 15.5).

Texto-base
----------
Blocos de ``cache/limpo/<id>.json`` com ``incluir`` = verdadeiro (corpo, sem referências/apêndice/agradecimentos,
conforme ``excluir_secoes``). Quando ``limpeza.excluir_ruido`` está ligado, os **segmentos de ruído** marcados na
etapa ``ruido`` (autores, tabelas, cláusulas repetidas; 3.4) são cortados do texto do bloco usando as posições em
caracteres dos tokens (``inicio``/``fim`` de ``cache/tokens``); no lugar do trecho fica uma quebra de parágrafo.

Divisão em frases (regra única, usada por todas as análises por documento)
--------------------------------------------------------------------------
1. Blocos consecutivos da **mesma seção** são unidos quando o primeiro não termina em pontuação final e o seguinte
   começa em minúscula (frase que atravessa a quebra de página); caso contrário ficam separados por parágrafo.
   A página de uma frase é a da página em que ela **começa**.
2. Um parágrafo (quebra em branco) fecha a frase, **exceto** quando o parágrafo anterior não termina em pontuação final
   e o seguinte começa em minúscula (linha quebrada pela diagramação em colunas: a frase continua).
3. Dentro do parágrafo, ``.`` ``?`` ``!`` ``…`` (com fechamento de aspas/parênteses opcional) encerram a frase se
   forem seguidos de espaço e de **maiúscula, dígito, aspas ou parêntese de abertura**; ``?`` e ``!`` encerram sempre
   que seguidos de espaço. O ponto **não** encerra após abreviações conhecidas (``et al.``, ``e.g.``, ``i.e.``,
   ``Fig.``, ``Eq.``, ``Dr.``, ``Sr.``, ``p.``, ``vs.``...), após inicial isolada (``J. Smith``) nem dentro de
   números (``3.5``, sem espaço depois).
4. Fragmentos **sem pontuação final e com menos de 4 palavras** são tratados como título/rótulo e descartados;
   fragmentos sem letras também.

Limitações: PDFs acadêmicos com tabelas, listas e legendas misturam fragmentos que não são frases; o detector de
ruído (3.4) tira parte deles. ``avaliar_frases`` resume a confiabilidade da divisão (ver ``legibilidade.py``).
"""
import bisect
import re
from pathlib import Path

from app.services import ruido as svc_ruido
from app.services.analises import dados

ABREVIACOES = frozenset({
    "al", "e.g", "i.e", "fig", "figs", "eq", "eqs", "tab", "vs", "cf", "dr", "dra", "mr", "mrs", "ms", "prof", "profa",
    "sr", "sra", "srs", "no", "nº", "p", "pp", "vol", "sec", "cap", "ch", "inc", "ltd", "co", "st", "approx", "resp",
    "ex", "av", "etc", "ed", "eds", "ref", "refs", "apud", "u.s", "u.k",
})
_FIM = re.compile(r"([.?!…]+)([\"'”’)\]]*)(\s+)")
_ABRE = re.compile(r"[\"'“‘(\[]*[A-ZÀ-ÖØ-Þ0-9]")
_PALAVRA = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_TERMINAL = re.compile(r"[.?!…][\"'”’)\]]*\s*$")
_ESPACOS = re.compile(r"\s+")
_CONTINUA = re.compile(r"(?<![.?!…:;\"”’)\]])[ \t]*\n\s*\n[ \t]*(?=[a-zà-öø-ÿ])")


def _cortar_ruido(blocos: list[dict], tk: dict | None, intervalos: list[tuple[int, int, str]]) -> list[str]:
    """Texto de cada bloco com os trechos de ruído trocados por quebra de parágrafo."""
    textos = [b["texto"] for b in blocos]
    if not intervalos or tk is None:
        return textos
    cortes: dict[int, list[tuple[int, int]]] = {}
    for ini, fim, _motivo in intervalos:
        if ini >= tk["n"]:
            continue
        b = tk["bloco"][ini]
        cortes.setdefault(b, []).append((tk["inicio"][ini], tk["fim"][min(fim, tk["n"] - 1)]))
    for b, lista in cortes.items():
        texto = textos[b]
        saida, pos = [], 0
        for a, z in sorted(lista):
            if a > pos:
                saida.append(texto[pos:a])
            saida.append("\n\n")
            pos = max(pos, z)
        saida.append(texto[pos:])
        textos[b] = "".join(saida)
    return textos


def _unir_blocos(blocos: list[dict], textos: list[str]) -> list[dict]:
    """Corridas de blocos incluídos da mesma seção: ``{"texto", "inicios": [(offset, pagina)], "secao", "titulo"}``."""
    corridas: list[dict] = []
    for b, t in zip(blocos, textos):
        if not b.get("incluir", True) or not t.strip():
            continue
        t = t.strip()
        ult = corridas[-1] if corridas else None
        mesma = ult is not None and ult["secao"] == b["secao"] and ult["titulo"] == b.get("titulo_secao")
        if mesma and not _TERMINAL.search(ult["texto"]) and t[:1].islower():
            ult["texto"] += " "
        elif mesma:
            ult["texto"] += "\n\n"
        else:
            ult = None
        if ult is None:
            ult = {"texto": "", "inicios": [], "secao": b["secao"], "titulo": b.get("titulo_secao")}
            corridas.append(ult)
        ult["inicios"].append((len(ult["texto"]), b["pagina"]))
        ult["texto"] += t
    return corridas


def _eh_abreviacao(antes: str) -> bool:
    m = re.search(r"([^\W\d_][\w.]*)$", antes)
    if not m:
        return False
    palavra = m.group(1).lower().rstrip(".")
    if palavra in ABREVIACOES:
        return True
    return len(m.group(1)) == 1 and m.group(1).isupper()  # inicial: "J. Smith"


def dividir_frases(texto: str) -> list[tuple[int, str]]:
    """``[(offset_inicial, frase)]`` no ``texto`` (ver regra no docstring do módulo). Quebras de parágrafo fecham a frase."""
    saida: list[tuple[int, str]] = []
    texto = _CONTINUA.sub(lambda m: " " * len(m.group()), texto)  # mesmo tamanho: os deslocamentos continuam valendo
    for par in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]*)*", texto):
        trecho, base = par.group(), par.start()
        ini = 0
        for m in _FIM.finditer(trecho):
            pont = m.group(1)
            resto = trecho[m.end():]
            if pont[0] in ".…" and not _ABRE.match(resto):
                continue  # ponto/reticências seguidos de minúscula: a frase continua
            if pont == "." and _eh_abreviacao(trecho[ini:m.start(1)]):
                continue
            saida.append((base + ini, trecho[ini:m.end(2)]))
            ini = m.end()
        if ini < len(trecho):
            saida.append((base + ini, trecho[ini:]))
    resultado = []
    for off, f in saida:
        limpa = _ESPACOS.sub(" ", f).strip()
        if not limpa or not re.search(r"[^\W\d_]", limpa):
            continue
        n = len(_PALAVRA.findall(limpa))
        if n < 4 and not _TERMINAL.search(limpa):
            continue  # título ou rótulo
        resultado.append((off, limpa))
    return resultado


def frases_do_documento(pasta_projeto: Path, documento_id: int, excluir_ruido: bool = True) -> list[dict] | None:
    """Frases do corpo: ``[{"i", "texto", "pagina", "secao", "titulo_secao", "bloco_fim"}]`` (``None`` sem texto limpo).

    ``bloco_fim`` = a frase fecha um parágrafo (usado só como informação)."""
    blocos = dados.carregar_blocos(pasta_projeto, documento_id)
    if blocos is None:
        return None
    tk = dados.carregar_tokens(pasta_projeto, documento_id)
    intervalos = svc_ruido.intervalos_de_tokens(pasta_projeto, documento_id) if excluir_ruido else []
    textos = _cortar_ruido(blocos, tk, intervalos)
    frases: list[dict] = []
    for corrida in _unir_blocos(blocos, textos):
        offs = [o for o, _p in corrida["inicios"]]
        for off, f in dividir_frases(corrida["texto"]):
            k = max(0, bisect.bisect_right(offs, off) - 1)
            frases.append({"i": len(frases), "texto": f, "pagina": corrida["inicios"][k][1], "secao": corrida["secao"],
                           "titulo_secao": corrida["titulo"]})
    return frases


def palavras_da_frase(frase: str) -> list[str]:
    """Palavras (só letras; ``-`` e apóstrofo internos mantêm a palavra inteira); números e símbolos ficam de fora."""
    return _PALAVRA.findall(frase)
