"""4.1 - Tokenização e lematização (funções puras; a etapa está em etapas/linguistica.py).

Tokenizador
-----------
Palavra = letra Unicode seguida de letras/marcas/dígitos, com apóstrofos e hífens *internos*
(``don't``, ``multi-agent``, ``d'água``), como no protótipo ``voyant-local``:
``\\p{L}[\\p{L}\\p{M}\\p{N}]*(?:['’\\-‐‑]\\p{L}[\\p{L}\\p{M}\\p{N}]*)*``. Números puros ficam de fora
(a palavra precisa começar por letra). Acentos de PT/ES e ligaduras de PDF (ﬁ, ﬂ) são tratados:
``norm`` usa NFKC.

Formato de ``cache/tokens/<id>.json`` (arrays paralelos, um item por token, na ordem do texto)
------------------------------------------------------------------------------------------------
    {
      "formato": 1,
      "idioma": "en",                       # idioma usado na lematização
      "lematizacao": {"ativa": true, "metodo": "simplemma"},
      "n": 15234,                           # número de tokens (tamanho de todos os arrays)
      "secoes": ["resumo", "introducao"],   # tabela de tipos de seção
      "forma":  ["Agents", ...],            # superfície, caixa original
      "norm":   ["agents", ...],            # minúsculas, NFKC, apóstrofo reto, hífen simples
      "lema":   ["agent", ...],             # lema (= norm se a lematização estiver desligada)
      "pagina": [3, 3, null, ...],          # página do bloco (null se o documento não tem marcadores)
      "secao":  [1, 1, ...],                # índice em "secoes"
      "incluir":[1, 1, 0, ...],             # 1 = bloco conta nas análises (3.2), 0 = referências etc.
      "bloco":  [0, 0, 5, ...],             # índice do bloco em cache/limpo/<id>.json -> blocos
      "inicio": [12, 20, ...],              # deslocamento (caractere) do início no texto do bloco
      "fim":    [18, 26, ...]               # deslocamento do fim (exclusivo): texto[inicio:fim] == forma
    }

Evolução sem quebrar consumidores: chaves novas são acrescentadas (ex.: ``seg`` = índice do
segmento de ~40 palavras na 4.4; ``termo`` = id do termo composto na 4.3; ``classe`` na 4.5);
quem lê só usa as chaves que conhece. O status de palavra vazia NÃO é gravado (ver
palavras_vazias.py).

Lematização
-----------
``simplemma`` (tabela de consulta) no idioma do documento; em PT/ES, palavras que o dicionário
do idioma não conhece tentam também o inglês (textos em português citam muitos termos em inglês).
Ordem de decisão: (1) ``lematizacao.excecoes`` do projeto; (2) ``EXCECOES_PADRAO``
(termos técnicos/siglas); (3) sigla = forma TODA EM MAIÚSCULAS com >= 2 letras -> lema = minúscula
(exceto palavras comuns em caixa alta de títulos, ver ``_eh_sigla``); sigla no plural
(``SMEs``) perde o ``s``; (4) possessivo inglês
(``agent's`` -> ``agent``); (5) composto com hífen: só reduz o plural do último elemento (multi-agents -> multi-agent); em PT/ES, verbo-clítico
(``verificou-se``) vira o verbo;
(6) simplemma. Resultados da simplemma ficam em cache por (idioma, palavra).
"""
import unicodedata

import regex
import simplemma

IDIOMAS_SUPORTADOS = ("en", "pt", "es")

PADRAO_PALAVRA = regex.compile(r"\p{L}[\p{L}\p{M}\p{N}]*(?:['’\-‐‑]\p{L}[\p{L}\p{M}\p{N}]*)*")
_TRADUCAO_NORM = str.maketrans({"’": "'", "‐": "-", "‑": "-"})

# Termos que a simplemma lematiza errado ou que não devem ser lematizados (palavra -> lema).
EXCECOES_PADRAO: dict[str, str] = {
    "data": "data",  # simplemma (pt): "data" é substantivo; em EN fica "data" (não "datum")
    "ai": "ai",  # simplemma: ai -> be
    "ia": "ia",  # simplemma (pt): ia -> ir; aqui é "IA" (inteligência artificial)
    "llm": "llm", "llms": "llm",
    "gpt": "gpt", "gpts": "gpt",
    "agentic": "agentic",
    "genai": "genai",
    "saas": "saas",
    "startup": "startup", "startups": "startup", "start-up": "startup", "start-ups": "startup",
    "chatgpt": "chatgpt",
    "openai": "openai",
    "rag": "rag",
    "agi": "agi",
    "nlp": "nlp",
    "api": "api", "apis": "api",
    "google": "google", "gemini": "gemini", "microsoft": "microsoft",  # simplemma (pt): google -> googlar
    "cf": "cf", "km": "km", "cal": "cal", "etc": "etc", "span": "span", "goods": "goods",
    # Erros da simplemma 2.0 (EN) vistos no corpus MLR: o dicionário devolve radicais que não são palavras.
    "fixed": "fix", "fixing": "fix", "fixes": "fix", "developed": "develop", "growing": "grow",
    "thinking": "think", "preferred": "prefer", "preferring": "prefer", "determining": "determine",
    "mixed": "mix", "mixing": "mix", "playing": "play", "crafted": "craft", "modelling": "model",
    "modelled": "model", "labelled": "label", "cancelled": "cancel", "exemplified": "exemplify",
    "prefixes": "prefix", "crosses": "cross", "axes": "axis", "pending": "pending",
    "reprogramming": "reprogram", "unwilling": "unwilling", "jagged": "jagged",
    # Substantivos/adjetivos em -ing/-ed que a simplemma funde com o verbo (distorcem termos centrais do domínio).
    "learning": "learning", "reasoning": "reasoning", "planning": "planning", "training": "training",
    "processing": "processing", "understanding": "understanding", "engineering": "engineering",
    "marketing": "marketing", "funding": "funding", "crowdfunding": "crowdfunding", "existing": "existing",
    "limited": "limited", "based": "based",
}

_CLITICOS = frozenset({"se", "me", "te", "lhe", "lhes", "nos", "vos", "o", "a", "os", "as", "lo", "la", "los", "las", "le", "les"})
_SIGLA_NO_PLURAL = regex.compile(r"^\p{Lu}{2,}s$")

# 's que NÃO é possessivo (é contração de "is"/"us"/"has"): o token inteiro fica como está.
_CONTRACOES_S = frozenset({"it", "that", "there", "here", "what", "who", "how", "where", "when", "why", "he", "she", "let", "one", "everyone", "someone"})
_MIN_LETRAS_PALAVRA_COMUM = 5  # em caixa alta, >= 5 letras e palavra conhecida: é título, não sigla


def normalizar(forma: str) -> str:
    """Forma normalizada: NFKC, minúsculas, apóstrofo e hífen retos."""
    return unicodedata.normalize("NFKC", forma).lower().translate(_TRADUCAO_NORM)


def tokenizar(texto: str):
    """Gera ``(forma, inicio, fim)`` para cada palavra do texto."""
    for m in PADRAO_PALAVRA.finditer(texto):
        yield m.group(), m.start(), m.end()


def idioma_do_documento(qualidade: dict, parametros: dict) -> str:
    """Idioma detectado pela qualidade; se ausente/não suportado, o primeiro dos parâmetros ``idioma``."""
    idioma = (qualidade or {}).get("idioma")
    if idioma in IDIOMAS_SUPORTADOS:
        return idioma
    for candidato in parametros.get("idioma") or []:
        if candidato in IDIOMAS_SUPORTADOS:
            return candidato
    return "en"


def _normalizar_excecoes(excecoes: dict | None) -> dict[str, str]:
    return {
        normalizar(str(k).strip()): normalizar(str(v).strip())
        for k, v in (excecoes or {}).items()
        if str(k).strip() and str(v).strip()
    }


def _langs(idioma: str) -> tuple[str, ...]:
    return (idioma,) if idioma == "en" else (idioma, "en")


_CACHE_SIMPLEMMA: dict[tuple[str, str], str] = {}


def _lema_simplemma(palavra: str, idioma: str) -> str:
    chave = (idioma, palavra)
    achado = _CACHE_SIMPLEMMA.get(chave)
    if achado is None:
        achado = _CACHE_SIMPLEMMA[chave] = simplemma.lemmatize(palavra, lang=_langs(idioma)).lower()
    return achado


def _conhecida(palavra: str, idioma: str) -> bool:
    return any(simplemma.is_known(palavra, lang=l) for l in _langs(idioma))


class Lematizador:
    """Lematizador de um idioma, com exceções do projeto. Barato de criar; o cache da simplemma é global."""

    def __init__(self, idioma: str, ativa: bool = True, excecoes: dict | None = None):
        self.idioma = idioma
        self.ativa = ativa
        self.excecoes = _normalizar_excecoes(excecoes)

    def lema(self, forma: str, norm: str) -> str:
        if not self.ativa:
            return norm
        ex = self._excecao(norm)
        if ex is not None:
            return ex
        if self._eh_sigla(forma, norm):
            return norm
        if _SIGLA_NO_PLURAL.match(forma):
            return norm[:-1]  # SMEs, APIs, ONGs -> sme, api, ong
        return self._lema_palavra(norm)

    def _excecao(self, norm: str) -> str | None:
        """Exceção do projeto (vence) ou padrão para a palavra, se houver."""
        ex = self.excecoes.get(norm)
        return ex if ex is not None else EXCECOES_PADRAO.get(norm)

    def _eh_sigla(self, forma: str, norm: str) -> bool:
        letras = [c for c in forma if c.isalpha()]
        if len(letras) < 2 or "-" in forma or forma != forma.upper() or forma == forma.lower():
            return False
        # Títulos em caixa alta ("MODELS", "RESULTS"): palavra comum -> lematiza normalmente.
        return not (len(letras) >= _MIN_LETRAS_PALAVRA_COMUM and _conhecida(norm, self.idioma))

    def _lema_palavra(self, norm: str) -> str:
        if self.idioma == "en" and norm.endswith("'s") and len(norm) > 3:
            base = norm[:-2]
            if base in _CONTRACOES_S:
                return norm
            ex = self._excecao(base)
            return ex if ex is not None else self._lema_palavra(base)
        if "'" in norm:
            return norm  # contrações (don't, d'água): ficam como estão
        if "-" in norm:
            return self._lema_composto(norm)
        return _lema_simplemma(norm, self.idioma)

    def _lema_composto(self, norm: str) -> str:
        """Composto com hífen. Só o plural do último elemento é reduzido (multi-agents -> multi-agent):
        "llm-based" não vira "llm-base", "human-ai" não vira "human-be". PT/ES: "verificou-se" -> "verificar"."""
        inicio, _, ultimo = norm.rpartition("-")
        if not inicio or not ultimo:
            return norm
        if self.idioma != "en" and ultimo in _CLITICOS and "-" not in inicio:
            return self._lema_palavra(inicio)  # verbo + pronome oclítico
        ex = self._excecao(ultimo)
        if ex is not None:
            return f"{inicio}-{ex}"
        lema = _lema_simplemma(ultimo, self.idioma)
        return f"{inicio}-{lema}" if _plural_regular(ultimo, lema) else norm


def _plural_regular(palavra: str, lema: str) -> bool:
    """O lema é só a palavra sem o marcador de plural (s, es, ies -> y)?"""
    return lema in (palavra[:-1], palavra[:-2], palavra[:-3] + "y") and palavra.endswith("s")


def tokenizar_blocos(blocos: list[dict], lematizador: Lematizador) -> dict:
    """Tokeniza os blocos de cache/limpo/<id>.json e devolve os arrays paralelos (ver docstring do módulo)."""
    tipos: list[str] = []
    indice_tipo: dict[str, int] = {}
    forma, norm, lema, pagina, secao, incluir, bloco, inicio, fim = ([] for _ in range(9))
    memoria: dict[tuple[str, str], str] = {}  # (forma, norm) -> lema: poupa chamadas repetidas

    for i, b in enumerate(blocos):
        tipo = b.get("secao") or ""
        if tipo not in indice_tipo:
            indice_tipo[tipo] = len(tipos)
            tipos.append(tipo)
        t_idx = indice_tipo[tipo]
        pg = b.get("pagina")
        inc = 1 if b.get("incluir", True) else 0
        for f, a, z in tokenizar(b["texto"]):
            n = normalizar(f)
            l = memoria.get((f, n))
            if l is None:
                l = memoria[(f, n)] = lematizador.lema(f, n)
            forma.append(f); norm.append(n); lema.append(l)
            pagina.append(pg); secao.append(t_idx); incluir.append(inc)
            bloco.append(i); inicio.append(a); fim.append(z)

    return {
        "n": len(forma),
        "secoes": tipos,
        "forma": forma, "norm": norm, "lema": lema,
        "pagina": pagina, "secao": secao, "incluir": incluir,
        "bloco": bloco, "inicio": inicio, "fim": fim,
    }
