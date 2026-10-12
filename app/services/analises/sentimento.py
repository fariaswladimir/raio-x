"""15.10 - Sentimento por léxico (exploratório): polaridade por frase e por documento, agregada por grupo e ano.

**Uso exploratório.** Prosa acadêmica é, em geral, neutra; os léxicos foram construídos para outros gêneros (redes
sociais, resenhas, notícias) e não captam a argumentação científica ("limitação", "risco" e "falha" são termos técnicos,
não opinião). Leia a distribuição e os trechos extremos, não o escore como medida de "tom" do artigo. A tela repete o aviso.

Unidade de análise
------------------
A **frase** do corpo (``texto_documento.frases_do_documento``: mesmas frases do painel de documento, com página e seção,
sem referências nem ruído). "Segmento" na tela = frase.

Inglês: VADER (Hutto & Gilbert 2014; pacote ``vaderSentiment``, licença MIT, instalável por pip; **não** é copiado para o
repositório). Escore = ``compound`` em [-1, 1] (já trata negação, intensificadores, "but" e caixa alta).

Português (e qualquer idioma com léxico importado): **léxico importado pelo usuário** (OpLexicon, SentiLex-PT ou outro;
ver ``importar_lexico``): não são distribuídos com o Raio-X porque a licença de redistribuição não está clara para o
OpLexicon (PUCRS/OntoLP) e, para o SentiLex-PT 02, a confirmação encontrada é só indireta (catálogo B2FIND lista CC BY);
sem confirmação na fonte primária o Raio-X não os embute. Os léxicos importados ficam na pasta de configuração do usuário
(``%APPDATA%/RaioX/lexicos``, ``RAIOX_CONFIG_DIR`` troca), nunca no repositório nem no projeto.

Cálculo para léxico (``pontuar_frase_lexico``)
---------------------------------------------
1. Tokens da frase com o tokenizador do projeto; busca da forma normalizada e, se ausente, do lema (simplemma no idioma
   do léxico). Palavras de polaridade 0 não contam.
2. **Negação simples**: se um negador (não, nunca, jamais, nem, sem, nenhum/nenhuma, nada, tampouco; ES: no, nunca, jamás,
   ni, sin, ningún, nada; EN: not, no, never, n't, without) aparece nas 3 palavras anteriores, a polaridade da palavra é
   invertida (×-1). Não há intensificadores, ironia nem escopo sintático.
3. ``soma`` = soma das polaridades; escore = ``soma / sqrt(soma² + 15)`` (a normalização do VADER) em (-1, 1).
Classe: positivo se escore >= 0,05; negativo se <= -0,05; senão neutro (os limiares do VADER).

Agregação
---------
Por documento: média dos escores das frases, % de frases positivas/neutras/negativas, nº de frases e de frases com algum
termo do léxico (``cobertura``). Por grupo/ano: média dos escores **das frases** do grupo (pondera por frase) e média das
médias dos documentos (``media_docs``, pondera por documento); % por classe. Documentos de idioma sem léxico ficam de fora
e são listados em ``ignorados``.

Formatos de importação aceitos (``ler_lexico``)
-----------------------------------------------
- Genérico: ``termo;polaridade`` (separador ``;``, tabulação ou vírgula; polaridade -1/0/1 ou decimal com ponto).
- OpLexicon 2.1/3.0: ``termo,classe,polaridade,fonte`` (ex.: ``bom,adj,1,A``): usa-se a 3ª coluna.
- SentiLex-PT 02: ``lema.PoS=Adj;TG=HUM:N0;POL:N0=-1;ANOT=MAN`` (arquivo de lemas) e ``flexao,lema.PoS=...`` (arquivo de
  flexões): usa-se ``POL:N0``. Termos com mais de uma palavra são ignorados (o cálculo é por palavra).
Termos repetidos com polaridades diferentes: média.
"""
import json
import math
import re
import statistics
import unicodedata
from datetime import datetime
from pathlib import Path

from app.services.analises import texto_documento
from app.services.llm.config import pasta_config
from app.services.tokenizacao import IDIOMAS_SUPORTADOS, Lematizador, normalizar, tokenizar

LIMIAR = 0.05
ALFA = 15.0
JANELA_NEGACAO = 3
NEGADORES = {
    "pt": {"não", "nao", "nunca", "jamais", "nem", "sem", "nenhum", "nenhuma", "nada", "tampouco"},
    "es": {"no", "nunca", "jamás", "jamas", "ni", "sin", "ningún", "ninguna", "ninguno", "nada"},
    "en": {"not", "no", "never", "without", "neither", "nor", "cannot", "n't"},
}
AVISO = ("Uso exploratório: prosa acadêmica é, em geral, neutra, e os léxicos foram construídos para outros gêneros (redes sociais, "
         "resenhas, notícias). Termos técnicos como 'limitação', 'risco' ou 'falha' contam como negativos sem expressar opinião. "
         "Leia a distribuição e os trechos extremos, não o escore como o tom do artigo.")
METODOLOGIA = ("Inglês: VADER compound por frase (Hutto & Gilbert 2014). Outros idiomas: soma das polaridades do léxico importado com "
               "negação simples (inversão nas 3 palavras seguintes ao negador), normalizada por soma/√(soma²+15); positivo >= 0,05, "
               "negativo <= -0,05. Agregado por documento, grupo e ano.")
MAX_LEXICO = 500_000


class LexicoInvalido(ValueError):
    """Léxico inválido ou não encontrado (mensagem em português para a tela)."""


# ---------- VADER ----------

def vader_disponivel() -> bool:
    try:
        import vaderSentiment.vaderSentiment  # noqa: F401
        return True
    except ImportError:
        return False


_VADER = None


def pontuar_frase_vader(frase: str) -> dict:
    global _VADER
    if _VADER is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _VADER = SentimentIntensityAnalyzer()
    return {"escore": _VADER.polarity_scores(frase)["compound"], "termos": None}


# ---------- léxicos do usuário ----------

def pasta_lexicos() -> Path:
    return pasta_config() / "lexicos"


def _arquivo(lex_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,60}", lex_id or ""):
        raise LexicoInvalido("Identificador de léxico inválido.")
    return pasta_lexicos() / f"{lex_id}.json"


def _num(texto: str) -> float | None:
    try:
        return float(texto.strip().replace(",", "."))
    except ValueError:
        return None


def ler_lexico(texto: str) -> dict[str, float]:
    """Interpreta o texto de um léxico (formatos no docstring). Devolve {termo normalizado: polaridade média}."""
    acc: dict[str, list[float]] = {}

    def somar(termo: str, pol: float):
        t = normalizar(termo.strip())
        if t and " " not in t and re.search(r"[^\W\d_]", t):
            acc.setdefault(t, []).append(pol)

    for linha in texto.lstrip("﻿").splitlines():
        l = linha.strip()
        if not l or l.startswith("#"):
            continue
        m = re.match(r"^(?P<cab>[^;\t]+?)\.PoS=[^;]*(?:;.*?)?;POL(?::N0)?=(?P<pol>-?\d+(?:[.,]\d+)?)", l) or \
            re.match(r"^(?P<cab>[^;\t]+?)\.PoS=.*?POL:N\d=(?P<pol>-?\d+)", l)
        if m:  # SentiLex-PT: "flexão,lema.PoS=..." ou "lema.PoS=..."
            pol = _num(m.group("pol"))
            if pol is not None:
                somar(m.group("cab").split(",")[0], pol)
            continue
        partes = [p.strip().strip('"') for p in re.split(r"[;\t,]", l)]
        if len(partes) >= 3 and _num(partes[2]) is not None and _num(partes[1]) is None:
            somar(partes[0], _num(partes[2]))  # OpLexicon: termo,classe,polaridade,fonte
        elif len(partes) >= 2 and _num(partes[1]) is not None:
            somar(partes[0], _num(partes[1]))
        if len(acc) > MAX_LEXICO:
            raise LexicoInvalido("Léxico grande demais.")
    if not acc:
        raise LexicoInvalido("Nenhum termo com polaridade reconhecido: use 'termo;polaridade' (-1, 0 ou 1), OpLexicon "
                             "('termo,classe,polaridade,fonte') ou SentiLex-PT ('lema.PoS=...;POL:N0=-1').")
    return {t: round(sum(v) / len(v), 4) for t, v in acc.items()}


def importar_lexico(nome: str, idioma: str, texto: str, fonte: str = "") -> dict:
    """Importa e guarda o léxico na configuração do usuário. Devolve os metadados."""
    if not (nome or "").strip():
        raise LexicoInvalido("Informe um nome para o léxico.")
    if idioma not in IDIOMAS_SUPORTADOS:
        raise LexicoInvalido(f"Idioma '{idioma}' não suportado: use {', '.join(IDIOMAS_SUPORTADOS)}.")
    termos = ler_lexico(texto)
    base = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()).strip("-")[:40] or "lexico"
    lex_id, n = base, 2
    pasta_lexicos().mkdir(parents=True, exist_ok=True)
    while (pasta_lexicos() / f"{lex_id}.json").exists():
        lex_id, n = f"{base}-{n}", n + 1
    meta = {"id": lex_id, "nome": nome.strip(), "idioma": idioma, "fonte": (fonte or "").strip(), "termos": len(termos),
            "positivos": sum(1 for v in termos.values() if v > 0), "negativos": sum(1 for v in termos.values() if v < 0),
            "importado_em": datetime.now().isoformat(timespec="seconds")}
    (pasta_lexicos() / f"{lex_id}.json").write_text(json.dumps({"meta": meta, "termos": termos}, ensure_ascii=False, separators=(",", ":")),
                                                    encoding="utf-8", newline="\n")
    return meta


def listar_lexicos() -> list[dict]:
    saida = []
    for arq in sorted(pasta_lexicos().glob("*.json")) if pasta_lexicos().is_dir() else []:
        try:
            saida.append(json.loads(arq.read_text(encoding="utf-8"))["meta"])
        except (ValueError, KeyError, OSError):
            continue
    return saida


def carregar_lexico(lex_id: str) -> dict:
    arq = _arquivo(lex_id)
    if not arq.is_file():
        raise LexicoInvalido("Léxico não encontrado.")
    return json.loads(arq.read_text(encoding="utf-8"))


def remover_lexico(lex_id: str) -> bool:
    arq = _arquivo(lex_id)
    if not arq.is_file():
        return False
    arq.unlink()
    return True


def lexico_do_idioma(idioma: str, preferido: str | None = None) -> dict | None:
    """Léxico a usar para o idioma: o ``preferido`` (se for do idioma) ou o mais recente importado para ele."""
    metas = [m for m in listar_lexicos() if m["idioma"] == idioma]
    if preferido:
        metas = [m for m in metas if m["id"] == preferido] or metas
    if not metas:
        return None
    return carregar_lexico(sorted(metas, key=lambda m: m["importado_em"])[-1]["id"])


# ---------- pontuação ----------

def pontuar_frase_lexico(frase: str, termos: dict[str, float], idioma: str, lem: Lematizador | None = None) -> dict:
    """Escore da frase pelo léxico (regras no docstring do módulo). ``termos`` = quantos termos do léxico apareceram."""
    lem = lem or Lematizador(idioma, ativa=True)
    negadores = NEGADORES.get(idioma, set())
    palavras = [normalizar(f) for f, _a, _z in tokenizar(frase)]
    soma, achados = 0.0, 0
    for i, w in enumerate(palavras):
        pol = termos.get(w)
        if pol is None:
            pol = termos.get(lem.lema(w, w))
        if not pol:
            continue
        achados += 1
        if any(p in negadores for p in palavras[max(0, i - JANELA_NEGACAO):i]):
            pol = -pol
        soma += pol
    escore = soma / math.sqrt(soma * soma + ALFA) if soma else 0.0
    return {"escore": round(escore, 4), "termos": achados}


def classe(escore: float) -> str:
    return "positivo" if escore >= LIMIAR else "negativo" if escore <= -LIMIAR else "neutro"


# ---------- cálculo ----------

def _resumo_frases(escores: list[float]) -> dict:
    n = len(escores)
    if not n:
        return {"frases": 0, "media": None, "positivo": 0, "neutro": 0, "negativo": 0}
    cont = {"positivo": 0, "neutro": 0, "negativo": 0}
    for e in escores:
        cont[classe(e)] += 1
    return {"frases": n, "media": round(sum(escores) / n, 4), **{k: round(100 * v / n, 1) for k, v in cont.items()}}


def calcular(pasta_projeto: Path, metas: list[dict], idiomas: dict[int, str], lexico_ids: dict[str, str] | None = None,
             excluir_ruido: bool = True, extremos: int = 10, tamanho_citacao: int = 400) -> dict:
    """Sentimento do corpus. ``idiomas``: idioma de cada documento (id -> "en"/"pt"/"es"); ``lexico_ids``: léxico por idioma."""
    lexico_ids = lexico_ids or {}
    lexicos: dict[str, dict | None] = {}
    docs, todas, ignorados = [], [], []
    for m in metas:
        idioma = idiomas.get(m["id"]) or "en"
        if idioma == "en" and not lexico_ids.get("en"):
            if not vader_disponivel():
                ignorados.append({"id": m["id"], "rotulo": m["rotulo"], "motivo": "VADER não instalado (pip install vaderSentiment)"})
                continue
            usar = ("vader", None)
        else:
            if idioma not in lexicos:
                try:
                    lexicos[idioma] = lexico_do_idioma(idioma, lexico_ids.get(idioma))
                except LexicoInvalido:
                    lexicos[idioma] = None
            lex = lexicos[idioma]
            if lex is None:
                ignorados.append({"id": m["id"], "rotulo": m["rotulo"], "motivo": f"sem léxico importado para o idioma '{idioma}'"})
                continue
            usar = ("lexico", lex)
        frases = texto_documento.frases_do_documento(pasta_projeto, m["id"], excluir_ruido=excluir_ruido)
        if not frases:
            ignorados.append({"id": m["id"], "rotulo": m["rotulo"], "motivo": "sem texto"})
            continue
        lem = Lematizador(idioma, ativa=True) if usar[0] == "lexico" else None
        escores, com_termo = [], 0
        for f in frases:
            r = pontuar_frase_vader(f["texto"]) if usar[0] == "vader" else pontuar_frase_lexico(f["texto"], usar[1]["termos"], idioma, lem)
            escores.append(r["escore"])
            if r["termos"]:
                com_termo += 1
            todas.append({"documento_id": m["id"], "rotulo": m["rotulo"], "grupo": m.get("grupo"), "ano": m.get("ano"),
                          "pagina": f["pagina"], "secao": f["secao"], "frase": f["i"], "escore": r["escore"],
                          "texto": f["texto"][:tamanho_citacao]})
        resumo = _resumo_frases(escores)
        docs.append({"id": m["id"], "rotulo": m["rotulo"], "grupo": m.get("grupo"), "ano": m.get("ano"), "idioma": idioma,
                     "metodo": "VADER" if usar[0] == "vader" else usar[1]["meta"]["nome"],
                     "cobertura": None if usar[0] == "vader" else round(100 * com_termo / len(frases), 1), **resumo})
    por_grupo = _agregar(docs, todas, "grupo", "sem grupo")
    por_ano = _agregar(docs, todas, "ano", "s/ano")
    ordenadas = sorted(todas, key=lambda x: (x["escore"], x["documento_id"], x["frase"]))
    neg = [x for x in ordenadas if x["escore"] < 0][:extremos]
    pos = [x for x in reversed(ordenadas) if x["escore"] > 0][:extremos]
    return {"documentos": docs, "ignorados": ignorados, "corpus": _resumo_frases([x["escore"] for x in todas]),
            "por_grupo": por_grupo, "por_ano": por_ano, "mais_positivas": pos, "mais_negativas": neg,
            "aviso": AVISO, "metodologia": METODOLOGIA, "limiar": LIMIAR}


def _agregar(docs: list[dict], frases: list[dict], campo: str, vazio: str) -> list[dict]:
    chaves = sorted({str(d[campo]) if d[campo] else vazio for d in docs}, key=lambda c: (c == vazio, c.lower()))
    saida = []
    for c in chaves:
        ids = {d["id"] for d in docs if (str(d[campo]) if d[campo] else vazio) == c}
        res = _resumo_frases([f["escore"] for f in frases if f["documento_id"] in ids])
        medias = [d["media"] for d in docs if d["id"] in ids and d["media"] is not None]
        saida.append({"valor": c, "documentos": len(ids), "media_docs": round(statistics.fmean(medias), 4) if medias else None, **res})
    return saida
