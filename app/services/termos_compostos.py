"""4.3 - Termos compostos (multiword terms): detecção de candidatos, marcação nos tokens e contagem por termo.

Convenções
----------
Unidade de análise: o *lema* dos tokens do corpo (``incluir`` = 1) com >= 2 letras (o mesmo universo do vocabulário).
Um termo composto é uma sequência de 2..``n_max`` lemas, escrita com espaço (``"large language model"``).

Contiguidade: dois tokens vizinhos só se ligam se (1) estão no mesmo bloco (página/seção do texto limpo), (2) ambos
contam (corpo, >= 2 letras) e (3) o texto original entre eles tem apenas espaço, no máximo uma quebra de linha
(linha em branco = parágrafo novo, que quebra) e no máximo um hífen (``human - AI``, ``multi-`` + quebra + ``agent``).
Qualquer outra pontuação (vírgula, ponto, parêntese, travessão) quebra a sequência. Hífen *interno* (``llm-based``) já
é um único token.

Candidatos automáticos
----------------------
- Sem palavra vazia nas bordas (``token_vazio`` com o filtro do projeto); no meio, palavra vazia só em trigramas e só
  se estiver na lista ``internas_permitidas`` (padrão: of, on, for, in, to, de, da, do: ``return on investment``,
  ``cost of capital``; "number of ai" ou "use that tool" não passam); nunca todos os tokens iguais.
- Classes gramaticais (4.5, opcional): com ``classes`` (ex.: ``["substantivos", "adjetivos"]``) toda palavra não vazia do candidato precisa ter
  uma dessas classes (spaCy, ``cache/spacy``; ``internas_permitidas`` continuam valendo); documentos sem etiquetagem ficam sem esse filtro.
- Frequência >= ``min_freq`` e documentos >= ``min_docs``.
- Ruído (ajuste do lote F2): ``excluir_regex`` (expressões aplicadas ao termo em lemas; padrão: palavra repetida
  seguida dela mesma, resíduo de tabela como "fe yes yes", e termos só de palavras de 1-2 letras) e
  ``max_concentracao`` (padrão 0,8: sai o candidato com >= 80% das ocorrências num único documento; só vale quando
  ``min_docs`` >= 2, pois com ``min_docs`` = 1 o usuário aceitou termos de um só documento). Termos da ``lista`` não
  passam por nenhuma dessas regras.
- Escore: log-likelihood (G² de Dunning 1993) da tabela 2×2 dos pares adjacentes (N = pares adjacentes do corpus;
  O11 = par; R1 = pares que começam com w1; C1 = pares que terminam com w2). Para n >= 3 o escore é o **mínimo** do
  G² dos bigramas internos. Só atração (G² > 0).
- Candidatos aninhados: um termo mais curto é descartado se um candidato mais longo que o contém tem frequência
  >= 80% da dele (``large language`` some quando quase toda ocorrência é ``large language model``).
- Ficam os ``max_automaticos`` de maior escore. Depois entram os da ``lista`` (origem "lista", sempre) e saem os
  ``bloqueados`` (a remoção dos bloqueados é feita *antes* do corte, para que bloquear não encolha a lista).

Marcação (longest match)
------------------------
Da esquerda para a direita, em cada posição vale o termo mais longo da lista efetiva que casa; as palavras cobertas
são consumidas (não reiniciam outro termo). Os termos de ``lista`` casam mesmo com palavras vazias e acima de ``n_max``.

Armazenamento (decisão): NÃO se reescreve ``cache/tokens/<id>.json`` (produto da etapa ``linguistica``: reescrevê-lo
daria a ele dois donos e o cache por etapa deixaria de dizer de onde vem cada arquivo). Cada documento ganha o arquivo
lateral ``cache/termos/<id>.json`` com as ocorrências esparsas ``[posição, comprimento, termo]``; ``dados.carregar_tokens(...,
termos=True)`` monta o array paralelo ``termo`` (lema em toda parte; o termo composto no 1º token do trecho; ``""`` nos
demais), com o cache LRU por mtime dos dois arquivos. ``cache/termos_compostos.json`` guarda a lista efetiva e, por
documento, as contagens ``compostos`` e ``cobertos`` (pares (norm, lema) consumidos), com as quais
``visao_vocabulario`` produz as contagens por termo sem reler os tokens.

Contagem por termo: a unidade é o termo composto (1) ou o token que sobrou; o denominador (``tokens``) continua o do
vocabulário, para que o /10k seja comparável ao por lema.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

from app.services.palavras_vazias import token_vazio

FORMATO = 1
PADRAO = {"ativa": True, "automaticos": True, "n_max": 3, "min_freq": 10, "min_docs": 3, "max_automaticos": 200,
          "lista": [], "bloqueados": [], "internas_permitidas": ["of", "on", "for", "in", "to", "de", "da", "do"],
          "excluir_regex": [r"\b(\w+) \1\b", r"^(\w{1,2} )+\w{1,2}$"], "max_concentracao": 0.8, "classes": []}
RAZAO_ANINHADO = 0.8
_HIFENS = ("-", "‐", "‑")
_ESPACOS = re.compile(r"\s+")


def configuracao(parametros: dict) -> dict:
    """``parametros["termos_compostos"]`` completado com o padrão e normalizado (listas em lemas minúsculos)."""
    cfg = {**PADRAO, **((parametros or {}).get("termos_compostos") or {})}
    for chave in ("lista", "bloqueados"):
        cfg[chave] = list(dict.fromkeys(t for t in (normalizar_termo(x) for x in cfg.get(chave) or []) if " " in t))
    for chave in ("n_max", "min_freq", "min_docs", "max_automaticos"):
        cfg[chave] = int(cfg[chave])
    cfg["n_max"] = max(2, cfg["n_max"])
    cfg["internas_permitidas"] = list(dict.fromkeys(normalizar_termo(x) for x in cfg.get("internas_permitidas") or []))
    cfg["excluir_regex"] = [str(x) for x in cfg.get("excluir_regex") or [] if str(x).strip()]
    cfg["max_concentracao"] = float(cfg["max_concentracao"])
    from app.services import spacy_nlp
    cfg["classes"] = sorted(spacy_nlp.expandir_classes(cfg.get("classes") or []))
    return cfg


def normalizar_termo(termo: str) -> str:
    return _ESPACOS.sub(" ", str(termo).strip().lower())


def caminho_termos_doc(pasta_projeto: Path, documento_id: int) -> Path:
    return pasta_projeto / "cache" / "termos" / f"{documento_id}.json"


def caminho_termos_corpus(pasta_projeto: Path) -> Path:
    return pasta_projeto / "cache" / "termos_compostos.json"


_LEITURA: dict[str, tuple] = {}


def marca_termos_corpus(pasta_projeto: Path):
    caminho = caminho_termos_corpus(pasta_projeto)
    if not caminho.is_file():
        return None
    e = caminho.stat()
    return e.st_mtime_ns, e.st_size


_LEITURA: dict[str, tuple] = {}


def marca_termos_corpus(pasta_projeto: Path):
    caminho = caminho_termos_corpus(pasta_projeto)
    if not caminho.is_file():
        return None
    e = caminho.stat()
    return e.st_mtime_ns, e.st_size


def ler_termos_corpus(pasta_projeto: Path) -> dict | None:
    """``cache/termos_compostos.json`` (com memória por data de modificação; não altere o resultado)."""
    marca = marca_termos_corpus(pasta_projeto)
    if marca is None:
        return None
    guardado = _LEITURA.get(str(pasta_projeto))
    if guardado and guardado[0] == marca:
        return guardado[1]
    dados = json.loads(caminho_termos_corpus(pasta_projeto).read_text(encoding="utf-8"))
    _LEITURA[str(pasta_projeto)] = (marca, dados)
    return dados


# ---------- sequências contíguas ----------

def _gap_liga(gap: str, quebrar_pontuacao: bool = True) -> bool:
    if gap.count("\n") > 1:
        return False
    if not quebrar_pontuacao:
        return True  # 5.5 (n-gramas): pontuação não quebra; só parágrafo, bloco e token excluído quebram
    resto = gap.strip()
    return resto == "" or resto in _HIFENS


def sequencias(tk: dict, blocos: list[dict], quebrar_pontuacao: bool = True) -> list[tuple[int, int]]:
    """Intervalos ``[a, b)`` de tokens ligados (mesmo bloco, corpo, >= 2 letras, só espaço/hífen entre eles).

    ``quebrar_pontuacao=False`` (n-gramas): qualquer pontuação entre os tokens é tolerada; continuam quebrando a
    fronteira de bloco, o parágrafo (linha em branco) e os tokens fora do corpo ou com 1 letra."""
    norm, inc, bloco, ini, fim = tk["norm"], tk["incluir"], tk["bloco"], tk["inicio"], tk["fim"]
    n = tk["n"]
    saida: list[tuple[int, int]] = []
    a = None
    for i in range(n):
        if not inc[i] or len(norm[i]) < 2:
            if a is not None:
                saida.append((a, i))
                a = None
            continue
        if a is not None:
            ligado = bloco[i] == bloco[i - 1] and _gap_liga(blocos[bloco[i]]["texto"][fim[i - 1]:ini[i]], quebrar_pontuacao)
            if not ligado:
                saida.append((a, i))
                a = i
        else:
            a = i
    if a is not None:
        saida.append((a, n))
    return saida


# ---------- detecção ----------

def _ll_bigrama(o11: int, r1: int, c1: int, n: int, log_likelihood) -> float:
    if r1 >= n or c1 >= n or o11 <= 0:
        return 0.0
    return log_likelihood(o11, r1, c1, n)


def detectar(docs: list[dict], filtro, cfg: dict) -> list[dict]:
    """Candidatos automáticos do corpus. ``docs``: ``[{"tokens": tk, "blocos": [...]}]`` (arrays de cache/tokens).

    Devolve ``[{"termo", "n", "freq", "docs", "score"}]`` ordenados por escore (já sem aninhados, sem bloqueados e
    cortados em ``max_automaticos``). Lista vazia se ``automaticos`` estiver desligado.
    """
    from app.services.analises.colocacoes import log_likelihood  # import tardio: colocacoes importa dados

    if not cfg["automaticos"]:
        return []
    n_max = cfg["n_max"]
    pares: Counter = Counter()
    primeiro: Counter = Counter()
    segundo: Counter = Counter()
    freq: list[Counter] = [Counter() for _ in range(n_max + 1)]  # freq[n][tupla de lemas] (só bordas válidas)
    df: Counter = Counter()
    maximo_doc: dict[tuple, int] = {}  # maior frequência do candidato num único documento (concentração)
    permitidas = set(cfg["internas_permitidas"])
    classes = frozenset(cfg.get("classes") or [])
    for d in docs:
        tk = d["tokens"]
        lema, norm = tk["lema"], tk["norm"]
        local: Counter = Counter()
        pos = d.get("pos") if classes else None  # POS por token (spaCy) ou None: sem filtro de classe neste documento
        for a, b in sequencias(tk, d["blocos"]):
            ls = lema[a:b]
            vz = [token_vazio(norm[i], lema[i], filtro) for i in range(a, b)]
            fora_classe = [pos is not None and not vz[i - a] and pos[i] not in classes for i in range(a, b)]
            m = b - a
            for k in range(m - 1):
                par = (ls[k], ls[k + 1])
                pares[par] += 1
                primeiro[ls[k]] += 1
                segundo[ls[k + 1]] += 1
            for n in range(2, min(n_max, m) + 1):
                for k in range(m - n + 1):
                    if vz[k] or vz[k + n - 1]:
                        continue
                    if n > 3 and any(vz[k + 1:k + n - 1]):
                        continue  # palavra vazia no meio só em trigramas
                    if n == 3 and vz[k + 1] and not (ls[k + 1] in permitidas or norm[a + k + 1] in permitidas):
                        continue  # ...e só as da lista ``internas_permitidas``
                    if any(fora_classe[k:k + n]):
                        continue
                    g = tuple(ls[k:k + n])
                    if len(set(g)) == 1:
                        continue
                    freq[n][g] += 1
                    local[g] += 1
        df.update(local.keys())
        for g, c in local.items():
            if c > maximo_doc.get(g, 0):
                maximo_doc[g] = c
    total = sum(pares.values())
    ll_par: dict[tuple, float] = {}

    def ll(par):
        v = ll_par.get(par)
        if v is None:
            v = ll_par[par] = _ll_bigrama(pares[par], primeiro[par[0]], segundo[par[1]], total, log_likelihood)
        return v

    bloqueados = set(cfg["bloqueados"])
    regexes = [re.compile(r) for r in cfg["excluir_regex"]]
    limite_conc = cfg["max_concentracao"] if cfg["min_docs"] >= 2 else None
    achados: dict[tuple, dict] = {}
    for n in range(2, n_max + 1):
        for g, f in freq[n].items():
            if f < cfg["min_freq"] or df[g] < cfg["min_docs"]:
                continue
            termo = " ".join(g)
            if termo in bloqueados:
                continue
            score = min(ll(g[k:k + 2]) for k in range(n - 1))
            if score > 0:
                # Os candidatos "ruidosos" (concentrados num documento ou casados por ``excluir_regex``) não entram na
                # lista, mas ainda cobrem os mais curtos: "yes yes" sai e arrasta "fe yes" (que só aparece dentro dele).
                ruido = (limite_conc is not None and maximo_doc[g] >= limite_conc * f) or any(r.search(termo) for r in regexes)
                achados[g] = {"termo": termo, "n": n, "freq": f, "docs": df[g], "score": score, "_ruido": ruido}

    # aninhados: o mais curto some se um mais longo que o contém cobre >= 80% das suas ocorrências
    cobertura: dict[tuple, int] = {}
    for g in achados:
        for n in range(2, len(g)):
            for k in range(len(g) - n + 1):
                sub = g[k:k + n]
                cobertura[sub] = max(cobertura.get(sub, 0), achados[g]["freq"])
    restantes = [{k: v for k, v in c.items() if k != "_ruido"} for g, c in achados.items()
                 if not c["_ruido"] and cobertura.get(g, 0) < RAZAO_ANINHADO * c["freq"]]
    restantes.sort(key=lambda c: (-c["score"], -c["freq"], c["termo"]))
    return restantes[: max(0, cfg["max_automaticos"])]


def contar_lista(docs: list[dict], termos: list[str]) -> dict[str, dict]:
    """Frequência e documentos de cada termo da ``lista`` (sem regras de borda), contados sobre as sequências."""
    achados = {t: {"freq": 0, "docs": 0} for t in termos}
    por_tamanho: dict[int, set] = {}
    for t in termos:
        por_tamanho.setdefault(len(t.split()), set()).add(t)
    for d in docs:
        tk = d["tokens"]
        lema = tk["lema"]
        no_doc: set = set()
        for a, b in sequencias(tk, d["blocos"]):
            for n, conj in por_tamanho.items():
                for k in range(a, b - n + 1):
                    g = " ".join(lema[k:k + n])
                    if g in conj:
                        achados[g]["freq"] += 1
                        no_doc.add(g)
        for g in no_doc:
            achados[g]["docs"] += 1
    return achados


def montar_lista(automaticos: list[dict], extras: dict[str, dict], cfg: dict) -> list[dict]:
    """Lista efetiva: automáticos + ``lista`` (origem "lista"), sem bloqueados."""
    bloqueados = set(cfg["bloqueados"])
    por_termo = {c["termo"]: {**c, "origem": "automatico"} for c in automaticos}
    for termo in cfg["lista"]:
        if termo in por_termo:
            por_termo[termo]["origem"] = "lista"
        else:
            por_termo[termo] = {"termo": termo, "n": len(termo.split()), "score": None, **extras.get(termo, {}),
                                "origem": "lista"}
    itens = [c for t, c in por_termo.items() if t not in bloqueados]
    itens.sort(key=lambda c: (c["origem"] != "lista", -(c["score"] if c["score"] is not None else math.inf), c["termo"]))
    return itens


# ---------- marcação ----------

def marcar(tk: dict, blocos: list[dict], termos: set[str]) -> list[list]:
    """Ocorrências ``[posição, comprimento, termo]`` com casamento mais longo da esquerda para a direita."""
    if not termos:
        return []
    maximo = max(len(t.split()) for t in termos)
    primeiros = {t.split()[0] for t in termos}
    lema = tk["lema"]
    achados: list[list] = []
    for a, b in sequencias(tk, blocos):
        i = a
        while i < b:
            if lema[i] in primeiros:
                for n in range(min(maximo, b - i), 1, -1):
                    g = " ".join(lema[i:i + n])
                    if g in termos:
                        achados.append([i, n, g])
                        i += n - 1
                        break
            i += 1
    return achados


def contagens_do_documento(tk: dict, ocorrencias: list[list]) -> dict:
    """``compostos`` {termo: n} e ``cobertos`` [[norm, lema, n]] (tokens consumidos, para subtrair do vocabulário)."""
    compostos: Counter = Counter()
    cobertos: Counter = Counter()
    for i, n, termo in ocorrencias:
        compostos[termo] += 1
        for k in range(i, i + n):
            cobertos[(tk["norm"][k], tk["lema"][k])] += 1
    return {"compostos": dict(compostos), "cobertos": [[a, b, c] for (a, b), c in cobertos.items()]}


def array_termo(tk: dict, ocorrencias: list[list]) -> list[str]:
    """Array paralelo ``termo`` (ver o docstring do módulo)."""
    termo = list(tk["lema"])
    for i, n, t in ocorrencias:
        termo[i] = t
        for k in range(i + 1, i + n):
            termo[k] = ""
    return termo


def fim_do_termo(termo: list[str], i: int) -> int:
    """Índice do último token do trecho que começa em ``i`` (``i`` se não for composto)."""
    e = i
    n = len(termo)
    while e + 1 < n and termo[e + 1] == "":
        e += 1
    return e


# ---------- contagem por termo a partir do vocabulário ----------

_VISOES: dict[str, tuple] = {}


def visao_vocabulario(voc: dict, tc: dict, chave_cache: str | None = None, marca=None) -> dict:
    """Vocabulário com a unidade "termo": ``{"documentos": {id: {tokens, lema, norma, pares}}}`` (mesmo formato do
    ``vocabulario.json``, que ``frequencias``/``keyness`` já sabem ler; ``lema`` e ``norma`` valem os termos)."""
    if chave_cache is not None:
        guardado = _VISOES.get(chave_cache)
        if guardado and guardado[0] == marca:
            return guardado[1]
    docs = {}
    for id_, d in voc["documentos"].items():
        extra = tc["documentos"].get(id_)
        if extra is None:
            pares = {(n, l): c for n, l, c in d["pares"]}
        else:
            pares = Counter({(n, l): c for n, l, c in d["pares"]})
            for n, l, c in extra["cobertos"]:
                pares[(n, l)] -= c
            for t, c in extra["compostos"].items():
                pares[(t, t)] += c
            pares = {k: c for k, c in pares.items() if c > 0}
        por_termo: Counter = Counter()
        for (_n, t), c in pares.items():
            por_termo[t] += c
        docs[id_] = {"arquivo": d.get("arquivo"), "tokens": d["tokens"], "lema": dict(por_termo),
                     "norma": dict(por_termo), "pares": [[n, t, c] for (n, t), c in pares.items()]}
    visao = {"formato": FORMATO, "documentos": docs}
    if chave_cache is not None:
        _VISOES[chave_cache] = (marca, visao)
    return visao


# ---------- exibição (4.3, lote F2) ----------

def formas_do_termo(tk: dict, ocorrencias: list[list]) -> dict[str, Counter]:
    """Por termo, as sequências de *formas originais* (com a caixa do texto) que foram marcadas neste documento."""
    forma = tk["forma"]
    achados: dict[str, Counter] = {}
    for i, n, termo in ocorrencias:
        achados.setdefault(termo, Counter())[" ".join(forma[i:i + n])] += 1
    return achados


def melhor_exibicao(contagens: Counter | None, termo: str) -> str:
    """Forma original mais frequente ("United States" para o termo "unite state"); sem marcações, o próprio termo.
    Empate: a que tem mais letras maiúsculas e depois a ordem alfabética (determinístico)."""
    if not contagens:
        return termo
    return min(contagens, key=lambda f: (-contagens[f], -sum(c.isupper() for c in f), f))
