"""3.4 - Detector de segmentos de ruído (listas de autores/afiliações, tabelas de regressão/estatística, cláusulas repetidas).

Motivação (achado na 7.1): no corpus MLR, listas de autores/afiliações, tabelas de regressão e cláusulas padrão
(licença, direitos autorais) formavam classes inteiras da CHD de Reinert e poluíam os n-gramas. O detector é
**conservador** (prefere deixar passar ruído a derrubar texto de verdade) e age sobre os segmentos de texto da 4.4,
que são a unidade da CHD e da similitude. Os limiares ficam em ``parametros.json`` → ``limpeza.ruido``.

Regras (um segmento recebe o **primeiro** motivo que casar; ``None`` = texto normal)
------------------------------------------------------------------------------
- ``tabela``: segmento com ``min_tokens`` ou mais itens (separados por espaço) em que a fração de itens numéricos
  ("0.123", "(0.045)", "2,73***", "p<0.01") ou só símbolos ("***", "±", "|") é >= ``prop_numerica`` (0,45); ou em que
  essa fração somada à de siglas de 1–2 letras que não são palavras funcionais ("t", "SE", "df", "R2") é >= 0,60;
  ou com >= ``separadores_tabela`` (3) barras verticais ``|``.
- ``autores``: >= ``min_tokens`` itens, fração de itens iniciados em maiúscula >= ``prop_maiuscula`` (0,60), fração de
  palavras de prosa (verbos e conectivos como "is", "that", "para", "não"; "of/de/and/e/the" não contam, pois ocorrem
  em "University of X") <= ``prop_prosa_max`` (0,08) e >= 3 separadores de lista (vírgula, ponto e vírgula, "and", "&",
  "e"). Pega listas de autores, afiliações e endereços; títulos em caixa alta/baixa sem vírgulas passam.
- ``repetitivo``: >= ``min_tokens_repetitivo`` (12) palavras com razão tipo/ocorrência <= ``tipo_token_min`` (0,35).
- ``clausula_repetida``: >= ``min_tokens`` palavras e cobertura >= ``repeticao_cobertura`` (0,80) das posições por
  sequências de 6 palavras (minúsculas, só letras) que aparecem em >= ``repeticao_min_docs`` (4) documentos
  diferentes ("This work is licensed under a Creative Commons ...", "Copyright © ... all rights reserved").

Limites assumidos: o detector olha só a forma do texto, não o sentido. Tabelas com muito texto em células e listas
de autores com poucas vírgulas escapam; um parágrafo narrativo cheio de números (resultado descritivo com muitos
percentuais) pode atingir a fração numérica de 0,45 só se for quase só números. Os motivos e as contagens aparecem
nas pendências do documento e dá para desligar tudo com ``limpeza.excluir_ruido = false``.

Arquivo ``cache/ruido/<id>.json``: ``{"formato", "n_segmentos", "segmentos": [{seg, motivo, inicio_token, fim_token,
n_tokens, pagina}], "resumo": {segmentos, tokens, por_motivo}}`` (só os segmentos marcados). Consumidores:
``analises/reinert.carregar_unidades`` (CHD e similitude), ``analises/ngramas`` e a marca ``ruido`` do KWIC.
"""
import json
import re
from bisect import bisect_right
from collections import Counter
from pathlib import Path

FORMATO = 1
PADRAO = {
    "min_tokens": 8, "prop_numerica": 0.45, "prop_maiuscula": 0.60, "prop_prosa_max": 0.08,
    "tipo_token_min": 0.35, "min_tokens_repetitivo": 12, "separadores_tabela": 3,
    "repeticao_min_docs": 4, "repeticao_cobertura": 0.80, "ngrama_repeticao": 6,
}
MOTIVOS = {
    "tabela": "tabela ou números", "autores": "autores/afiliações", "repetitivo": "texto repetitivo",
    "clausula_repetida": "cláusula repetida entre documentos",
}

_PROSA = frozenset(
    "is are was were be been being has have had do does did will would can could may might must should that this these "
    "those which who whom whose with for in on at to as by from not no we our it its they their there here than then "
    "also however but or if when while although because into between among over under about after before during "
    "um uma uns umas que para com sem não nao é são foi foram ser está estão como mais mas ou se quando porque pelo "
    "pela pelos pelas entre sobre após ao aos às uma el los las es son fue por con una".split())
_CONECTIVOS = frozenset("and e y &".split())
_NUMERICO = re.compile(r"^[\(\[\{]?[-+−–]?[$€£]?\d*[.,]?\d+(?:[.,]\d+)*[\)\]\}]?[*†‡%]*[,;]?$")
_PALAVRAS = re.compile(r"[^\W\d_]+", re.UNICODE)
_ESPACOS = re.compile(r"\s+")


def parametros_do_ruido(parametros: dict | None) -> dict:
    lim = (parametros or {}).get("limpeza") or {}
    return {**PADRAO, **(lim.get("ruido") or {})}


def excluir_ruido(parametros: dict | None) -> bool:
    return bool(((parametros or {}).get("limpeza") or {}).get("excluir_ruido", True))


def caminho_ruido(pasta_projeto: Path, documento_id: int) -> Path:
    return pasta_projeto / "cache" / "ruido" / f"{documento_id}.json"


def ler_ruido(pasta_projeto: Path, documento_id: int) -> dict | None:
    caminho = caminho_ruido(pasta_projeto, documento_id)
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.is_file() else None


# ---------- detectores por segmento ----------

def _item_numerico(t: str) -> bool:
    if _NUMERICO.match(t):
        return True
    if not any(c.isalnum() for c in t):
        return True  # só símbolos: *** ± | - =
    return sum(c.isdigit() for c in t) >= 0.5 * len(t) and len(t) <= 14


def motivo_tabela(itens: list[str], texto: str, p: dict) -> str | None:
    n = len(itens)
    if n < 6:
        return None
    if texto.count("|") >= p["separadores_tabela"]:
        return "tabela"
    if n < p["min_tokens"]:
        return None
    numericos = sum(_item_numerico(t) for t in itens)
    siglas = sum(1 for t in itens if not _item_numerico(t) and len(t.strip(".,;:()")) <= 2
                 and t.strip(".,;:()").lower() not in _PROSA and t.strip(".,;:()").lower() not in _CONECTIVOS)
    if numericos / n >= p["prop_numerica"] or (numericos + siglas) / n >= 0.60:
        return "tabela"
    return None


def motivo_autores(itens: list[str], p: dict) -> str | None:
    n = len(itens)
    if n < p["min_tokens"]:
        return None
    limpos = [t.strip(".,;:()[]*†‡&0123456789") for t in itens]
    maiusculas = sum(1 for t in limpos if t[:1].isupper())
    prosa = sum(1 for t in limpos if t.lower() in _PROSA)
    separadores = sum(t.count(",") + t.count(";") for t in itens) + sum(1 for t in limpos if t.lower() in _CONECTIVOS) \
        + sum(1 for t in itens if t == "&")
    if maiusculas / n >= p["prop_maiuscula"] and prosa / n <= p["prop_prosa_max"] and separadores >= 3:
        return "autores"
    return None


def motivo_repetitivo(palavras: list[str], p: dict) -> str | None:
    n = len(palavras)
    if n >= p["min_tokens_repetitivo"] and len(set(palavras)) / n <= p["tipo_token_min"]:
        return "repetitivo"
    return None


def _palavras(texto: str) -> list[str]:
    return [w.lower() for w in _PALAVRAS.findall(texto)]


def classificar_segmento(texto: str, p: dict) -> str | None:
    """Motivo (sem a regra entre documentos) ou ``None``."""
    itens = texto.split()
    return (motivo_tabela(itens, texto, p) or motivo_autores(itens, p) or motivo_repetitivo(_palavras(texto), p))


def _ngramas(palavras: list[str], k: int) -> list[tuple]:
    return [tuple(palavras[i:i + k]) for i in range(len(palavras) - k + 1)]


# ---------- corpus ----------

def detectar(segmentos_por_doc: dict[int, list[dict]], parametros: dict | None = None) -> dict[int, list[dict]]:
    """``{documento: [segmento]}`` (cada segmento com ``seg``, ``texto``, ``inicio_token``, ``fim_token``, ``n_tokens``,
    ``pagina``) -> ``{documento: [marcados]}`` com ``motivo`` acrescentado. Documentos sem ruído vêm com lista vazia."""
    p = parametros_do_ruido(parametros)
    k = int(p["ngrama_repeticao"])
    marcados: dict[int, dict[int, str]] = {d: {} for d in segmentos_por_doc}
    palavras_de: dict[tuple[int, int], list[str]] = {}
    for d, segs in segmentos_por_doc.items():
        for s in segs:
            motivo = classificar_segmento(s["texto"], p)
            if motivo:
                marcados[d][s["seg"]] = motivo
            else:
                palavras_de[(d, s["seg"])] = _palavras(s["texto"])
    # cláusulas repetidas: n-gramas de k palavras presentes em muitos documentos
    df: Counter = Counter()
    for d, segs in segmentos_por_doc.items():
        vistos: set = set()
        for s in segs:
            if (d, s["seg"]) in palavras_de:
                vistos.update(_ngramas(palavras_de[(d, s["seg"])], k))
        df.update(vistos)
    comuns = {g for g, c in df.items() if c >= p["repeticao_min_docs"]}
    if comuns:
        for (d, seg), pal in palavras_de.items():
            if len(pal) < p["min_tokens"] or len(pal) < k:
                continue
            coberto = [False] * len(pal)
            for i, g in enumerate(_ngramas(pal, k)):
                if g in comuns:
                    for j in range(i, i + k):
                        coberto[j] = True
            if sum(coberto) / len(pal) >= p["repeticao_cobertura"]:
                marcados[d][seg] = "clausula_repetida"
    saida: dict[int, list[dict]] = {}
    for d, segs in segmentos_por_doc.items():
        saida[d] = [{**s, "motivo": marcados[d][s["seg"]]} for s in segs if s["seg"] in marcados[d]]
    return saida


def resumo_do_documento(marcados: list[dict]) -> dict:
    por_motivo = Counter(m["motivo"] for m in marcados)
    return {"segmentos": len(marcados), "tokens": sum(m["n_tokens"] for m in marcados), "por_motivo": dict(por_motivo)}


def gravar(pasta_projeto: Path, documento_id: int, n_segmentos: int, marcados: list[dict]) -> dict:
    resumo = resumo_do_documento(marcados)
    destino = caminho_ruido(pasta_projeto, documento_id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    itens = [{"seg": m["seg"], "motivo": m["motivo"], "inicio_token": m["inicio_token"], "fim_token": m["fim_token"],
              "n_tokens": m["n_tokens"], "pagina": m.get("pagina")} for m in marcados]
    destino.write_text(json.dumps({"formato": FORMATO, "n_segmentos": n_segmentos, "segmentos": itens, "resumo": resumo},
                                  ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    return resumo


def frase_aviso(resumo: dict) -> str | None:
    """Texto da pendência do documento (``None`` se nada foi marcado)."""
    if not resumo or not resumo.get("segmentos"):
        return None
    partes = ", ".join(f"{MOTIVOS.get(m, m)} {c}" for m, c in sorted(resumo["por_motivo"].items(), key=lambda kv: -kv[1]))
    n = resumo["segmentos"]
    return (f"{n} segmento{'s' if n != 1 else ''} de ruído ({partes}; ~{resumo['tokens']} palavras): "
            "fora da CHD, da similitude e dos n-gramas enquanto limpeza.excluir_ruido estiver ligado")


# ---------- consumo pelas análises ----------

def segmentos_de_ruido(pasta_projeto: Path, documento_id: int) -> dict[int, str]:
    """``{índice do segmento: motivo}`` do documento ({} sem arquivo)."""
    r = ler_ruido(pasta_projeto, documento_id)
    return {s["seg"]: s["motivo"] for s in r["segmentos"]} if r else {}


def intervalos_de_tokens(pasta_projeto: Path, documento_id: int) -> list[tuple[int, int, str]]:
    """``[(início, fim_inclusivo, motivo)]`` em índices de token, ordenados."""
    r = ler_ruido(pasta_projeto, documento_id)
    if not r:
        return []
    return sorted((s["inicio_token"], s["fim_token"], s["motivo"]) for s in r["segmentos"])


def motivo_do_token(intervalos: list[tuple[int, int, str]], i: int) -> str | None:
    j = bisect_right(intervalos, (i, 10 ** 12, "")) - 1
    return intervalos[j][2] if j >= 0 and intervalos[j][0] <= i <= intervalos[j][1] else None


def subtrair_intervalos(seqs: list[tuple[int, int]], ruido: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """Remove dos intervalos ``[a, b)`` (``seqs``) os tokens dos intervalos de ruído (fechados)."""
    if not ruido:
        return seqs
    saida: list[tuple[int, int]] = []
    for a, b in seqs:
        pos = a
        for ini, fim, _ in ruido:
            if fim < pos or ini >= b:
                continue
            if ini > pos:
                saida.append((pos, ini))
            pos = max(pos, fim + 1)
            if pos >= b:
                break
        if pos < b:
            saida.append((pos, b))
    return saida


def marca_do_arquivo(pasta_projeto: Path, documento_id: int) -> tuple | None:
    c = caminho_ruido(pasta_projeto, documento_id)
    if not c.is_file():
        return None
    e = c.stat()
    return (e.st_mtime_ns, e.st_size)
