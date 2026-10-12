"""15.4 - Palavras-chave por documento: RAKE, YAKE e TextRank (texto do corpo, sem referências nem ruído).

Texto e unidades
----------------
Frases de ``texto_documento.py`` (corpo, sem ruído). Cada frase é quebrada em **trechos** nos símbolos, números e
pontuação (``, ; : ( ) " ...``); só sequências de letras formam palavras. Palavras vazias = lista do idioma do documento
+ lista "acadêmico" + palavras próprias do projeto (``palavras_vazias.py``); palavras de 1 letra nunca são candidatas.
Tudo em minúsculas (YAKE usa a caixa original só no atributo de caixa).

RAKE (Rose et al., 2010)
------------------------
Frases candidatas = sequências máximas de palavras não vazias dentro de um trecho. Para cada palavra w:
``freq(w)`` = ocorrências nas candidatas e ``deg(w)`` = soma, sobre as ocorrências, do comprimento da candidata (conta a
própria palavra e as vizinhas); ``score(w) = deg(w)/freq(w)``. Pontuação da candidata = soma dos scores das palavras.
**Maior é melhor.** Candidatas com mais de ``max_palavras`` (4) palavras são descartadas e só entram as que aparecem
pelo menos ``min_freq`` vezes (padrão 2 em documentos de 1.500+ palavras, senão 1; evita nomes de autores e frases únicas).
Não implementa "palavras vazias adjacentes" (*axis of evil*) do artigo.

YAKE (Campos et al., 2020) - implementação própria, só características de documento único
---------------------------------------------------------------------------------------
Para cada termo t (palavra não vazia, minúscula): TF; ``caixa = max(TF_sigla, TF_capitalizada) / (1 + ln TF)`` (sigla = toda
em maiúsculas; capitalizada = inicial maiúscula **fora** do início de frase); ``posição = ln(3 + mediana das posições
(índice da frase) das ocorrências)``; ``frequência = TF / (média(TF) + desvio(TF))`` sobre os termos não vazios;
``relação com o contexto = 1 + (WL + WR)·TF/MaxTF + PL + PR`` com janela de 1 palavra (WL = vizinhos esquerdos
distintos / ocorrências à esquerda; PL = vizinhos esquerdos distintos / MaxTF; WR e PR à direita);
``diferentes frases = frases com t / total de frases``. Pontuação do termo
``S(t) = rel·pos / (caixa + freq/rel + dif/rel)``. Candidatas = n-gramas de até ``ngrama_max`` (3) palavras consecutivas
**sem palavras vazias** (o original admite vazias no meio, com peso especial: diferença), dentro de um trecho;
``S(kw) = Π S(t) / (TF(kw)·(1 + Σ S(t)))``. **Menor é melhor.** Desduplicação: percorrendo da melhor para a pior, uma candidata
é descartada se a razão de similaridade (``difflib.SequenceMatcher``) com alguma já escolhida for >= ``dedup`` (0,8;
o YAKE usa Levenshtein com 0,9). Mesmo ``min_freq`` do RAKE. O pacote ``yake`` não foi usado (puxa segtok/jellyfish,
só inglês e sem controle das palavras vazias do projeto).

TextRank (Mihalcea e Tarau, 2004)
---------------------------------
Nós = lemas (simplemma) das palavras não vazias com 2+ letras (**sem filtro sintático**: não há etiquetador, o filtro é
o de palavras vazias). Aresta entre duas palavras distintas que coocorrem a menos de ``janela`` posições (padrão 4;
2-10) na sequência de palavras não vazias **da mesma frase**. PageRank do networkx (d = 0,85, não ponderado). Escolhem-se
os ``max(1, nós/3)`` nós de maior pontuação (no máximo 200) e as palavras escolhidas **adjacentes no texto** (mesmo
trecho) são fundidas em frases de até ``max_palavras`` (4); pontuação da frase = soma das palavras. **Maior é melhor.** Mesmo ``min_freq`` do RAKE (sem ele, as frases fundidas
são quase todas únicas: sem etiquetador, verbos adjacentes às palavras-chave entram na mesma frase).

Comparação lado a lado com os termos distintivos TF-IDF (5.1, ``resumo.py``) fica a cargo da API/etapa.
"""
import difflib
import math
import re
import statistics
from collections import Counter, defaultdict

from app.services.analises import texto_documento
from app.services.palavras_vazias import PALAVRAS, palavras_proprias

METODOS = ("rake", "yake", "textrank")
PADRAO = {
    "n": 10,
    "rake": {"max_palavras": 4, "min_freq": None},
    "yake": {"ngrama_max": 3, "dedup": 0.8, "min_freq": None},
    "textrank": {"janela": 4, "max_palavras": 4, "fracao": 1 / 3, "max_nos": 200, "min_freq": None},
}
LIMITE_PALAVRAS_MIN_FREQ = 1500
_TOKEN = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*|\S")
_E_PALAVRA = re.compile(r"[^\W\d_]")
_POSSESSIVO = re.compile(r"['’]s$")


def parametros(parametros_projeto: dict | None) -> dict:
    """Parâmetros efetivos: padrão + ``documento_extra`` do projeto (``n_palavras_chave``, ``rake``, ``yake``, ``textrank``)."""
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in PADRAO.items()}
    extra = (parametros_projeto or {}).get("documento_extra") or {}
    if "n_palavras_chave" in extra:
        p["n"] = int(extra["n_palavras_chave"])
    for m in ("rake", "yake", "textrank"):
        if isinstance(extra.get(m), dict):
            p[m].update(extra[m])
    return p


def vazias(idioma: str | None, parametros_projeto: dict | None = None) -> frozenset:
    lingua = idioma if idioma in PALAVRAS and idioma != "academico" else "en"
    return frozenset(PALAVRAS[lingua] | PALAVRAS["academico"] | set(palavras_proprias(parametros_projeto)))


# ---------- preparo: trechos de palavras ----------

def trechos(frases: list[dict]) -> list[dict]:
    """``[{"frase": i, "pos": (0 = 1ª palavra da frase), "palavras": [forma, ...]}]``; trechos quebram em tudo que não é palavra."""
    saida: list[dict] = []
    for f in frases:
        atual: list[str] = []
        inicio_frase = True
        for m in _TOKEN.finditer(f["texto"]):
            t = m.group()
            if _E_PALAVRA.match(t):
                atual.append(_POSSESSIVO.sub("", t) if len(t) > 3 else t)  # AI's -> AI
            else:
                if atual:
                    saida.append({"frase": f["i"], "inicio": inicio_frase, "palavras": atual})
                    inicio_frase = False
                    atual = []
        if atual:
            saida.append({"frase": f["i"], "inicio": inicio_frase, "palavras": atual})
    return saida


def _valida(p: str, sw: frozenset) -> bool:
    return len(p) >= 2 and p not in sw


def _pagina(frases: list[dict], idxs) -> list[int]:
    return sorted({frases[i]["pagina"] for i in idxs if frases[i]["pagina"] is not None})[:3]  # texto sem paginação: []


def _linha(frase: str, pontuacao: float, freq: int, frases: list[dict], idxs) -> dict:
    return {"frase": frase, "pontuacao": round(float(pontuacao), 4), "frequencia": int(freq), "paginas": _pagina(frases, idxs)}


# ---------- RAKE ----------

def rake(frases: list[dict], tr: list[dict], sw: frozenset, max_palavras: int = 4, min_freq: int = 1, n: int = 10) -> list[dict]:
    cand: dict[tuple, list[int]] = defaultdict(list)
    for t in tr:
        corrente: list[str] = []
        for w in t["palavras"] + [""]:
            baixa = w.lower()
            if w and _valida(baixa, sw):
                corrente.append(baixa)
            else:
                if corrente and len(corrente) <= max_palavras:
                    cand[tuple(corrente)].append(t["frase"])
                corrente = []
    freq: Counter = Counter()
    grau: Counter = Counter()
    for frase, ocs in cand.items():
        for w in frase:
            freq[w] += len(ocs)
            grau[w] += len(ocs) * len(frase)
    pont = {frase: sum(grau[w] / freq[w] for w in frase) for frase in cand}
    ordem = sorted((f for f in cand if len(cand[f]) >= min_freq), key=lambda f: (-pont[f], -len(cand[f]), f))
    return [_linha(" ".join(f), pont[f], len(cand[f]), frases, cand[f]) for f in ordem[:n]]


# ---------- YAKE ----------

def yake(frases: list[dict], tr: list[dict], sw: frozenset, ngrama_max: int = 3, dedup: float = 0.8, min_freq: int = 1, n: int = 10) -> list[dict]:
    tf: Counter = Counter()
    tf_sigla: Counter = Counter()
    tf_cap: Counter = Counter()
    posicoes: dict[str, list[int]] = defaultdict(list)
    frases_do_termo: dict[str, set[int]] = defaultdict(set)
    esq: dict[str, Counter] = defaultdict(Counter)
    dir_: dict[str, Counter] = defaultdict(Counter)
    for t in tr:
        ws = t["palavras"]
        for k, w in enumerate(ws):
            b = w.lower()
            if not _valida(b, sw):
                continue
            tf[b] += 1
            if len(w) > 1 and w.isupper():
                tf_sigla[b] += 1
            elif w[:1].isupper() and not (t["inicio"] and k == 0):
                tf_cap[b] += 1
            posicoes[b].append(t["frase"])
            frases_do_termo[b].add(t["frase"])
            if k > 0 and _valida(ws[k - 1].lower(), sw):
                esq[b][ws[k - 1].lower()] += 1
            if k + 1 < len(ws) and _valida(ws[k + 1].lower(), sw):
                dir_[b][ws[k + 1].lower()] += 1
    if not tf:
        return []
    total_frases = max(1, len(frases))
    valores = list(tf.values())
    media = statistics.fmean(valores)
    desvio = statistics.pstdev(valores)
    max_tf = max(valores)
    S: dict[str, float] = {}
    for t_, f in tf.items():
        caixa = max(tf_sigla[t_], tf_cap[t_]) / (1 + math.log(f))
        pos = math.log(3 + statistics.median(posicoes[t_]))
        fn = f / (media + desvio) if media + desvio > 0 else 1.0
        cl, cr = sum(esq[t_].values()), sum(dir_[t_].values())
        wl = len(esq[t_]) / cl if cl else 0.0
        wr = len(dir_[t_]) / cr if cr else 0.0
        rel = 1 + (wl + wr) * (f / max_tf) + len(esq[t_]) / max_tf + len(dir_[t_]) / max_tf
        dif = len(frases_do_termo[t_]) / total_frases
        S[t_] = (rel * pos) / (caixa + fn / rel + dif / rel) if (caixa + fn / rel + dif / rel) > 0 else float("inf")
    cand: dict[tuple, list[int]] = defaultdict(list)
    for t in tr:
        baixas = [w.lower() for w in t["palavras"]]
        ok = [_valida(b, sw) for b in baixas]
        for i in range(len(baixas)):
            for m in range(1, ngrama_max + 1):
                if i + m > len(baixas) or not all(ok[i:i + m]):
                    break
                cand[tuple(baixas[i:i + m])].append(t["frase"])
    pont: dict[tuple, float] = {}
    for kw, ocs in cand.items():
        if len(ocs) < min_freq:
            continue
        prod = math.prod(S[w] for w in kw)
        pont[kw] = prod / (len(ocs) * (1 + sum(S[w] for w in kw)))
    escolhidas: list[tuple] = []
    for kw in sorted(pont, key=lambda k: (pont[k], -len(cand[k]), k)):
        texto = " ".join(kw)
        if any(difflib.SequenceMatcher(None, texto, " ".join(e)).ratio() >= dedup for e in escolhidas):
            continue
        escolhidas.append(kw)
        if len(escolhidas) >= n:
            break
    return [_linha(" ".join(k), pont[k], len(cand[k]), frases, cand[k]) for k in escolhidas]


# ---------- TextRank ----------

def _lema(p: str, idioma: str | None) -> str:
    from app.services.tokenizacao import _lema_simplemma

    return _lema_simplemma(p, idioma if idioma in ("en", "pt", "es") else "en")


def textrank(frases: list[dict], tr: list[dict], sw: frozenset, idioma: str | None, janela: int = 4, max_palavras: int = 4,
             fracao: float = 1 / 3, max_nos: int = 200, min_freq: int = 1, n: int = 10) -> list[dict]:
    import networkx as nx

    if not 2 <= janela <= 10:
        raise ValueError("A janela do TextRank deve estar entre 2 e 10.")
    g = nx.Graph()
    por_frase: dict[int, list[str]] = defaultdict(list)
    for t in tr:
        for w in t["palavras"]:
            b = w.lower()
            if _valida(b, sw):
                por_frase[t["frase"]].append(_lema(b, idioma))
    for seq in por_frase.values():
        for i, a in enumerate(seq):
            g.add_node(a)
            for b in seq[i + 1:i + janela]:
                if a != b:
                    g.add_edge(a, b)
    if g.number_of_nodes() == 0:
        return []
    rank = nx.pagerank(g, alpha=0.85, max_iter=200, tol=1e-8)
    k = max(1, min(max_nos, int(round(g.number_of_nodes() * fracao))))
    top = {w for w, _ in sorted(rank.items(), key=lambda kv: (-kv[1], kv[0]))[:k]}
    cand: dict[tuple, list[int]] = defaultdict(list)      # sequência de lemas -> frases onde ocorre
    formas: dict[tuple, Counter] = defaultdict(Counter)   # sequência de lemas -> formas de superfície
    for t in tr:
        corrente: list[tuple[str, str]] = []
        for w in t["palavras"] + [""]:
            b = w.lower()
            lema = _lema(b, idioma) if w and _valida(b, sw) else None
            if lema in top:
                corrente.append((b, lema))
            else:
                for i in range(0, len(corrente), max_palavras):  # sequências longas são fatiadas
                    parte = corrente[i:i + max_palavras]
                    chave = tuple(x[1] for x in parte)
                    cand[chave].append(t["frase"])
                    formas[chave][" ".join(x[0] for x in parte)] += 1
                corrente = []
    pont = {kw: sum(rank[l] for l in kw) for kw in cand}
    ordem = sorted((kw for kw in cand if len(cand[kw]) >= min_freq), key=lambda kw: (-pont[kw], -len(cand[kw]), kw))
    return [_linha(max(formas[kw].items(), key=lambda kv: (kv[1], kv[0]))[0], pont[kw], len(cand[kw]), frases, cand[kw])
            for kw in ordem[:n]]


def calcular(frases: list[dict], idioma: str | None, metodo: str, parametros_projeto: dict | None = None, n: int | None = None) -> list[dict]:
    """Palavras-chave de um documento por ``metodo`` (``rake``, ``yake`` ou ``textrank``); lista ordenada do melhor ao pior."""
    if metodo not in METODOS:
        raise ValueError(f"Método inválido '{metodo}': use rake, yake ou textrank.")
    p = parametros(parametros_projeto)
    n = n or p["n"]
    sw = vazias(idioma, parametros_projeto)
    tr = trechos(frases)
    palavras = sum(len(t["palavras"]) for t in tr)
    padrao_freq = 2 if palavras >= LIMITE_PALAVRAS_MIN_FREQ else 1
    if metodo == "rake":
        o = p["rake"]
        return rake(frases, tr, sw, int(o["max_palavras"]), int(o["min_freq"] or padrao_freq), n)
    if metodo == "yake":
        o = p["yake"]
        return yake(frases, tr, sw, int(o["ngrama_max"]), float(o["dedup"]), int(o["min_freq"] or padrao_freq), n)
    o = p["textrank"]
    return textrank(frases, tr, sw, idioma, int(o["janela"]), int(o["max_palavras"]), float(o["fracao"]), int(o["max_nos"]), int(o["min_freq"] or padrao_freq), n)


def calcular_todos(frases: list[dict], idioma: str | None, parametros_projeto: dict | None = None, n: int | None = None) -> dict:
    return {m: calcular(frases, idioma, m, parametros_projeto, n) for m in METODOS}


def frases_do_documento(pasta, documento_id: int, excluir_ruido: bool = True):
    return texto_documento.frases_do_documento(pasta, documento_id, excluir_ruido)
