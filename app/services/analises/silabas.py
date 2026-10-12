"""Contagem de sílabas em inglês e português (base da legibilidade, 15.3).

Contar sílabas por regras nunca é exato; o objetivo é um erro pequeno e **sem viés** em textos acadêmicos. A acurácia
medida em listas conferidas à mão (50 palavras EN, 57 PT) está em ``tests/test_frente15_r.py`` e no relatório do lote.

Inglês (``silabas_en``) - heurística de grupos vocálicos
--------------------------------------------------------
1. Conta grupos de vogais ``aeiouy`` (``y`` é vogal; ``qu`` conta o ``u`` como consoante).
2. Termina em ``e`` mudo: subtrai 1 (exceto ``-le`` depois de consoante: *table*, e a lista curta ``EXCECOES_EN``).
3. ``-ed``: subtrai 1 quando o ``e`` é mudo (não depois de ``t``/``d``); ``-es``: subtrai 1 quando o ``e`` é mudo (não
   depois de ``s x z c g h`` nem de ``e`` em ``-ies/-oes`` isolados).
4. Hiato: soma 1 em ``ia``, ``io`` (exceto ``-tion/-sion/-cion/-gion`` e ``-ious``/``-iou``), ``ua``, ``uo``, ``eo``,
   ``ii``, ``iu``, ``eu`` raro e ``oe`` depois de consoante, ``ea`` no fim e ``ie`` antes de ``r``: *media*, *video*,
   *radio*, *quiet*, *area*... Sempre pelo menos 1.
5. Palavras com hífen somam as partes; contrações (`don't`) ficam com a base (sem o sufixo depois do apóstrofo); `-ism` soma 1 (m silábico).
O módulo também oferece ``silabas_en_pyphen`` (padrões de hifenização en_US do pacote ``pyphen``, que dividem em
posições de hífen e não em sílabas fonéticas) para comparação; o padrão do projeto é a heurística (mais precisa na lista
de teste, ver testes).

Português (``silabas_pt``) - núcleos silábicos
----------------------------------------------
Uma sílaba por **núcleo vocálico**. Sequências de vogais são divididas pelas regras abaixo (``h`` e consoantes separam
sequências); ``u`` depois de ``q``/``g`` e antes de vogal é consoante (*quatro*, *queijo*, *água*, *língua*).

- ``í``/``ú`` acentuados abrem sílaba (*sa-í-da*, *sa-ú-de*); ``ã``/``õ`` com ``o``/``e`` formam ditongo nasal
  (*ão*, *ãe*, *õe*: *mãe*, *relação*).
- Vogal forte (``a e o`` e acentuadas) + fraca (``i u``, sem acento) = **ditongo decrescente** (*mais*, *muito*, *deu*),
  exceto se a fraca fecha sílaba com ``l m n r z`` ou ``nh`` (hiato: *sa-ir*, *ru-im*, *ju-iz*, *ra-i-nha*, *a-in-da*).
- Fraca + fraca (``iu``, ``ui``): ditongo (*viu*, *muito*), com a mesma exceção (*ru-im*, *cons-ti-tu-ir*).
- Duas vogais fortes: **hiato** (*te-a-tro*, *po-e-ta*, *co-or-de-nar*, *em-pre-en-de-dor*).
- Fraca + forte no fim da palavra (``-ia -io -ua -ue -uo``, com ``-s`` opcional): **ditongo crescente** só se houver
  acento gráfico antes na palavra (*his-tó-ria*, *fa-mí-lia*, *ci-ên-cia*, *ne-gó-cio*); sem acento a palavra é paroxítona
  e o ``i``/``u`` é tônico, logo **hiato** (*tec-no-lo-gi-a*, *di-a*, *va-zi-o*, *con-ti-nu-a*). No meio da palavra,
  fraca + forte é hiato (*pi-a-no*, *am-bi-en-te*).
- Um núcleo já com duas vogais não recebe uma terceira (*i-dei-a*, *joi-a*).
Espanhol (``silabas_es``): ditongo = vogal fraca sem acento com qualquer vogal; hiato com ``í``/``ú`` ou duas fortes (sem lista de teste própria: uso só para os índices de série).
"""
import re
import unicodedata

VOGAIS_EN = "aeiouy"
# Exceções (dicionário): palavras comuns em que as regras erram por construção.
EXCECOES_EN = {
    "recipe": 3, "simile": 3, "apostrophe": 4, "catastrophe": 4, "epitome": 4, "forte": 2, "karate": 3, "acne": 2,
    "people": 2, "the": 1, "framework": 2, "frameworks": 2, "fire": 1, "hour": 1, "our": 1, "pigeon": 2, "leopard": 2, "bias": 2, "being": 2,
}
_SO_LETRAS = re.compile(r"[^a-z]")


def silabas_en(palavra: str) -> int:
    """Sílabas de uma palavra em inglês (heurística; ver o docstring do módulo)."""
    p = unicodedata.normalize("NFKD", palavra.lower())
    p = "".join(c for c in p if not unicodedata.combining(c))
    if "'" in p or "’" in p:  # contrações (don't, we're, it's, I'll): o sufixo depois do apóstrofo não soma sílaba
        base = re.split(r"['’]", p, maxsplit=1)[0]
        return silabas_en(base) if base else 1
    if "-" in p:
        return sum(silabas_en(parte) for parte in p.split("-") if parte) or 1
    p = _SO_LETRAS.sub("", p)
    if not p:
        return 0
    if p in EXCECOES_EN:
        return EXCECOES_EN[p]
    q = re.sub(r"(?<=[qg])u", "w", p)           # qu-/gu-: o u é consoante (queue, language, guess)
    q = re.sub(r"y(?=[aeiou])", "x", q)         # y antes de vogal é consoante (beyond, player, year)
    n = len(re.findall(r"[aeiouy]+", q))
    # e mudo final e terminações -ed / -es sem sílaba própria
    if len(p) > 2:
        if p.endswith("e") and not re.search(r"[^aeiouy]le$", p) and not p.endswith(("ee", "ye", "oe", "ie"))                 and not (p.endswith("ue") and p[-3] not in "qg"):   # -ue = um grupo vocálico (continue, value, blue)
            n -= 1
        elif re.search(r"[^aeiouytd]ed$", p):
            n -= 1
        elif re.search(r"[^aeiouy]es$", p) and not re.search(r"(?:[sxzcgh]|[^aeiouy]l)es$", p):
            n -= 1
    if len(p) > 6 and re.search(r"[gvcr]ement$", p):                # e mudo do radical: management, movement, requirement
        n -= 1
    # hiatos (duas vogais que formam sílabas separadas)
    n += len(re.findall(r"(?:ia|ua|uo|eo|ii|iu)", q))
    n -= len(re.findall(r"[cstgx]ia[ln]|[cstg]ian", q))            # special, initial, martial, technician: ditongo
    n += len(re.findall(r"io(?!n)", q)) - len(re.findall(r"[cstgx]ious|[cstgx]iou", q))
    n += len(re.findall(r"(?<=cr)ea(?=t)", q)) + len(re.findall(r"[dr]ea$", q))   # create, idea, area
    n += len(re.findall(r"(?<=sc)ie", q)) + len(re.findall(r"(?<=[dlr])ie(?=n[ct])", q))  # science, experience, client
    n += len(re.findall(r"(?:[dlr]|qu)iet", q))                    # quiet, diet
    n += 1 if p.endswith("ism") else 0                             # m silábico: organism
    return max(1, n)


# ---------- pyphen (opcional) ----------

_PYPHEN = {}


def silabas_en_pyphen(palavra: str) -> int | None:
    """Sílabas pelas posições de hifenização en_US do ``pyphen`` (``None`` se o pacote não está instalado)."""
    try:
        import pyphen
    except ImportError:
        return None
    dic = _PYPHEN.get("en")
    if dic is None:
        dic = _PYPHEN["en"] = pyphen.Pyphen(lang="en_US", left=1, right=1)
    p = _SO_LETRAS.sub("", unicodedata.normalize("NFKD", palavra.lower()))
    if not p:
        return 0
    return max(1, dic.inserted(p).count("-") + 1)


# ---------- português ----------

_FORTES = set("aeoáéóâêôàãõ")
_FRACAS = set("iuy")
_FRACAS_ACENTO = set("íú")
_VOGAIS_PT = _FORTES | _FRACAS | _FRACAS_ACENTO
_ACENTUADAS = set("áéíóúâêôàãõ")
_HIATO_FECHA = re.compile(r"(?:nh|[lmnrz](?:[^aeiouáéíóúâêôàãõy]|$))")


def _letras_pt(p: str) -> str:
    p = unicodedata.normalize("NFC", p.lower())
    return "".join(c for c in p if c.isalpha() or c == "ü")


def silabas_pt(palavra: str) -> int:
    """Sílabas de uma palavra em português (núcleos vocálicos; ver o docstring do módulo)."""
    p0 = unicodedata.normalize("NFC", palavra.lower())
    if "-" in p0 or "'" in p0:
        return sum(silabas_pt(parte) for parte in re.split(r"[-']+", p0) if parte) or 1
    p = _letras_pt(p0)
    if not p:
        return 0
    # u mudo ou semivogal depois de q/g antes de vogal (e trema): vira consoante
    p = re.sub(r"(?<=[qg])u(?=[aeiouáéíóúâêôãõ])", "x", p).replace("ü", "x")
    tem_acento_antes = [any(c in _ACENTUADAS for c in p[:i]) for i in range(len(p) + 1)]
    n = 0
    i = 0
    while i < len(p):
        if p[i] not in _VOGAIS_PT:
            i += 1
            continue
        j = i
        while j < len(p) and p[j] in _VOGAIS_PT:
            j += 1
        n += _nucleos_da_sequencia(p, i, j, tem_acento_antes)
        i = j
    return max(1, n)


def _nucleos_da_sequencia(p: str, ini: int, fim: int, acento_antes: list[bool]) -> int:
    nucleos = 1
    tamanho = 1  # vogais no núcleo atual
    for k in range(ini + 1, fim):
        a, b = p[k - 1], p[k]
        resto = p[k + 1:]
        junta = False
        if b in _FRACAS_ACENTO or a in _FRACAS_ACENTO:
            junta = False
        elif b in _FRACAS:
            if tamanho == 1 and (a in _FORTES or a in _FRACAS):
                junta = not _HIATO_FECHA.match(resto) or resto.startswith("s")
                if a in _FRACAS and a != b:
                    junta = not _HIATO_FECHA.match(resto)
                if a == b:
                    junta = False
        elif b in _FORTES:
            if a in _FORTES:
                junta = tamanho == 1 and ((a == "ã" and b == "o") or (a in "ãõ" and b == "e"))
            elif a in _FRACAS and tamanho == 1:
                final = re.fullmatch(r"s?", resto) is not None and b in "aeo"
                junta = final and acento_antes[k] and a != b
                if a == "i" and b == "a" and resto == "l" and p[max(0, k - 2):k - 1] in ("c", "t", "s"):
                    junta = True  # -cial/-tial/-sial: artificial, social, especial
        if junta:
            tamanho += 1
        else:
            nucleos += 1
            tamanho = 1
    return nucleos


def silabas_es(palavra: str) -> int:
    """Sílabas em espanhol: ditongo = vogal fraca (``i u``, sem acento) com qualquer vogal ou fraca com fraca (*ción*, *bien*,
    *cuando*); ``í``/``ú`` e duas vogais fortes (``a e o``) formam hiato (*país*, *poeta*, *leer*); ``qu``/``gu`` + ``e i``: ``u`` mudo."""
    p0 = unicodedata.normalize("NFC", palavra.lower())
    if "-" in p0 or "'" in p0:
        return sum(silabas_es(parte) for parte in re.split(r"[-']+", p0) if parte) or 1
    p = "".join(c for c in p0 if c.isalpha() or c == "ü")
    if not p:
        return 0
    p = re.sub(r"(?<=[qg])u(?=[eiéí])", "x", p).replace("ü", "u")
    n = 0
    for m in re.finditer(r"[aeiouáéíóúy]+", p):
        seq = m.group()
        n += 1
        for a, b in zip(seq, seq[1:]):
            forte_a, forte_b = a in "aeoáéó", b in "aeoáéó"
            if (forte_a and forte_b) or a in "íú" or b in "íú":
                n += 1
    return max(1, n)


def contar_silabas(palavra: str, idioma: str = "en", metodo: str = "heuristica") -> int:
    """Sílabas de uma palavra: ``pt`` e ``es`` por núcleos vocálicos; ``en`` pela heurística (``metodo="pyphen"`` usa o pacote)."""
    if idioma == "es":
        return silabas_es(palavra)
    if idioma == "pt":
        return silabas_pt(palavra)
    if metodo == "pyphen":
        v = silabas_en_pyphen(palavra)
        if v is not None:
            return v
    return silabas_en(palavra)
