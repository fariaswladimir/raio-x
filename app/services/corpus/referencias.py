"""16.3 - Referências citadas: separação da seção de Referências em itens e interpretação (melhor esforço) de cada item.

Entrada: as **linhas do Markdown convertido** que caem na seção ``referencias`` (a mesma detecção da etapa de limpeza, 3.1).
O texto limpo (``cache/limpo``) não serve aqui porque junta o parágrafo inteiro; as linhas do MD preservam uma
referência por item de lista/parágrafo.

Separação (``separar``)
-----------------------
1. linhas de tabela e de texto da seção (títulos e linhas removidas como cabeçalho/rodapé ficam de fora); marcadores de
   lista, ``[CrossRef]``/``[PubMed]``/``[Google Scholar]``, remissões de página ``[146]`` no fim e entidades HTML são limpos;
2. estilo **numerado** (``1.``, ``[1]``, ``(1)`` no início de pelo menos 40% das linhas): cada número abre uma referência;
   linhas sem número continuam a anterior;
3. estilo **autor-ano / linha por item** (o restante): cada linha é uma referência, **exceto** quando é continuação da
   anterior (começa em minúscula ou com URL/DOI/páginas, ou a anterior termina em ``, ; : - &`` ou em ``and``);
4. linhas longas (> 300 caracteres) com mais de um início de referência do tipo ``Sobrenome, I. ... (ANO)`` são divididas ali;
5. itens com menos de 25 caracteres ou sem letras são descartados.

Interpretação (``interpretar``)
-------------------------------
Autores no padrão ``Sobrenome, I.`` (APA/MDPI/Chicago) ou ``Nome Sobrenome`` (ACL/ICML); ano entre parênteses ou solto
(``2019,``); título = primeira sentença depois dos autores/ano; fonte e volume/número/páginas pelo resto. Quando algo não é
reconhecido o campo fica vazio e ``parseada`` = falso; o texto bruto é sempre mantido e é ele que vai ao .bib nesse caso.
Autores corporativos (OECD, Sebrae...) não são reconhecidos: ficam no texto bruto.
"""
import html
import re

_MARCADOR_NUM = re.compile(r"^\s*(?:\[(\d{1,3})\]|\((\d{1,3})\)|(\d{1,3})[.)])\s+")
_ETIQUETAS = re.compile(r"\[(?:CrossRef|PubMed|Google Scholar|Crossref|PMC|Medline|ISI|Scopus)\]", re.IGNORECASE)
_REMISSAO_FIM = re.compile(r"\s*\[\d{1,3}(?:[,;–-]\s*\d{1,3})*\]\s*$")
_LINK_MD = re.compile(r"\[([^\]]+)\]\((?:https?://)[^)]*\)")
_DOI = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*|DOI:?\s*)?(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
_URL = re.compile(r"(?:URL|Available (?:online|at)|Disponível em|Retrieved from)?:?\s*https?://\S+(?:\s+\S*\d\S*)?", re.IGNORECASE)
_ANO_PAREN = re.compile(r"\(((?:19|20)\d{2})([a-z]?)\)")
_ANO_SOLTO = re.compile(r"(?<![\d.:/\-])((?:19|20)\d{2})([a-z]?)(?![\d/]|\.\d|-\d)")
_PALAVRA_NOME = r"[A-ZÀ-ÝÇ][\wÀ-ÿ'’\-]*"
_PARTICULAS = r"(?:(?:de|da|do|dos|das|del|della|di|van|von|der|den|la|le|el|bin|al|ter|ten|y|e)\s+)"
_SOBRENOME = rf"(?:{_PARTICULAS}?{_PALAVRA_NOME})(?:[ \-]{_PARTICULAS}?{_PALAVRA_NOME}){{0,2}}"
_INICIAIS = r"(?:[A-ZÀ-Ý]\.(?:[ \-]?[A-ZÀ-Ý]\.){0,3}|[A-ZÀ-Ý]{1,3}(?![a-zà-ÿ]))"
_INICIO_AUTOR_ANO = re.compile(
    rf"(?<=[.\]\)\d])\s+(?=(?:{_SOBRENOME},\s+{_INICIAIS}|{_INICIAIS}\s+{_SOBRENOME})(?:[^()]{{0,200}}?)\((?:19|20)\d{{2}}[a-z]?\))")
_FIM_FRASE = re.compile(r"(?<=[a-zà-ÿ0-9\)\]”\"’'?!]{2})[.?!]\s+(?=[A-Za-zÀ-ÿ0-9\[“\"‘'(])")
_SEP_AUTOR = re.compile(r"\s*;\s*|\s*,\s*(?:and\s+|&\s*|y\s+|e\s+)?|\s+(?:and|&|y|e)\s+|\s*&amp;\s*")
_CORTA_AUTORES = re.compile(r"^\s*(?:,\s*)?(?:et\s+al\.?)", re.IGNORECASE)

MIN_CARACTERES = 25
LIMITE_LINHA_LONGA = 300


def _limpar_linha(t: str) -> str:
    t = html.unescape(t)
    t = _LINK_MD.sub(r"\1", t)
    t = _ETIQUETAS.sub("", t)
    t = t.replace("\\_", "_").replace("\\'", "'")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _tira_remissao(t: str) -> str:
    return _REMISSAO_FIM.sub("", t).strip()


def _continuacao(anterior: str, atual: str) -> bool:
    if not anterior or re.match(r"(?:and|e|y)\s*,", atual):  # "and , 'Título'": autor repetido (estilo Chicago): item novo
        return False
    if atual[:1].islower() or re.match(r"(?:https?://|www\.|doi\b|10\.\d{4}|pp?\.|\d+\s*[-–]\s*\d+|vol\b|\(\d)", atual, re.IGNORECASE):
        return True
    return bool(re.search(r"(?:[,;:\-–&(]|\band|\bet al\.?,?)\s*$", anterior)) and not re.search(r"[.?!]\s*$", anterior)


def _dividir_linha_longa(t: str) -> list[str]:
    if len(t) <= LIMITE_LINHA_LONGA:
        return [t]
    partes, ini = [], 0
    for m in _INICIO_AUTOR_ANO.finditer(t):
        if m.end() - ini > 40:
            partes.append(t[ini:m.start()].strip())
            ini = m.end()
    partes.append(t[ini:].strip())
    return [p for p in partes if p]


def separar(linhas: list[tuple[str, str]]) -> list[str]:
    """Itens da seção de referências. ``linhas`` = ``[(tipo, texto)]`` (``vazio`` | ``texto`` | ``tabela``), na ordem do documento."""
    brutas = [(t, _limpar_linha(x)) for t, x in linhas if t in ("texto", "tabela", "vazio")]
    conteudo = [x for t, x in brutas if t != "vazio" and x]
    if not conteudo:
        return []
    numeradas = sum(1 for x in conteudo if _MARCADOR_NUM.match(x))
    itens: list[str] = []
    if numeradas >= 0.4 * len(conteudo) and numeradas >= 3:
        atual = ""
        for x in conteudo:
            if _MARCADOR_NUM.match(x):
                if atual:
                    itens.append(atual)
                atual = _MARCADOR_NUM.sub("", x, count=1)
            else:
                atual = (atual + " " + x).strip()
        if atual:
            itens.append(atual)
    else:
        atual = ""
        for tipo, x in brutas:
            if tipo == "vazio" or not x:
                continue
            if atual and _continuacao(atual, x):
                atual = f"{atual} {x}"
            else:
                if atual:
                    itens.append(atual)
                atual = x
        if atual:
            itens.append(atual)
    saida: list[str] = []
    for it in itens:
        for p in _dividir_linha_longa(_tira_remissao(it)):
            p = _tira_remissao(p)
            if len(p) >= MIN_CARACTERES and re.search(r"[^\W\d_]{3}", p):
                saida.append(p)
    return saida


# ---------- interpretação ----------

def _autor_sobrenome_inicial(texto: str, pos: int) -> tuple[str, str, int] | None:
    m = re.compile(rf"\s*({_SOBRENOME}),\s*((?:{_INICIAIS}|{_PALAVRA_NOME}(?:[ \-]{_PALAVRA_NOME}){{0,3}}))(?=[\s,;.&(]|$)").match(texto, pos)
    if not m:
        return None
    return m.group(1), m.group(2).strip(), m.end()


def _autor_nome_sobrenome(texto: str, pos: int) -> tuple[str, str, int] | None:
    m = re.compile(rf"\s*((?:{_PALAVRA_NOME}\.?\s+){{1,3}}{_SOBRENOME})(?=[\s,;.&(]|$)").match(texto, pos)
    if not m:
        return None
    palavras = m.group(1).split()
    if len(palavras) < 2:
        return None
    k = len(palavras) - 1
    while k > 1 and palavras[k - 1].lower() in ("de", "da", "do", "van", "von", "der", "del", "la", "le", "di", "bin", "al"):
        k -= 1
    return " ".join(palavras[k:]), " ".join(palavras[:k]), m.end()


def _ler_autores(texto: str) -> tuple[list[str], int, str]:
    """Autores no início do texto: ``(["Sobrenome, N", ...], posição do fim, estilo)``; lista vazia se não reconhecer."""
    for estilo, leitor in (("sobrenome_inicial", _autor_sobrenome_inicial), ("nome_sobrenome", _autor_nome_sobrenome)):
        autores: list[str] = []
        pos = 0
        while True:
            r = leitor(texto, pos)
            if r is None:
                break
            sob, nome, fim = r
            autores.append(f"{sob}, {nome}")
            pos = fim
            corta = _CORTA_AUTORES.match(texto, pos)
            if corta:
                pos = corta.end()
                break
            sep = _SEP_AUTOR.match(texto, pos)
            if not sep or sep.end() == pos:
                break
            prox = leitor(texto, sep.end())
            if prox is None:
                if re.match(r"\s*et\s+al", texto[sep.end():], re.IGNORECASE):
                    pos = sep.end() + re.match(r"\s*et\s+al\.?", texto[sep.end():], re.IGNORECASE).end()
                break
            pos = sep.end()
        if estilo == "sobrenome_inicial" and ";" not in texto[:pos]:
            # "Josh Achiam, Steven Adler": sobrenome de várias palavras com nome por extenso, sem ";": é "Nome Sobrenome" (ACL)
            def _iniciais(a: str) -> bool:
                return bool(re.fullmatch(_INICIAIS, a.partition(", ")[2].strip()))
            if any(" " in a.partition(", ")[0] and not _iniciais(a) and (len(autores) >= 2 or len(a.partition(", ")[2].split()) >= 2) for a in autores):
                continue
        if autores and (estilo == "sobrenome_inicial" or len(autores) >= 1):
            if estilo == "nome_sobrenome" and len(autores) == 1 and not re.match(r"\s*[.,]\s*(?:19|20)\d{2}|\s*\(", texto[pos:]):
                continue  # um único "nome sobrenome" sem ano logo depois: provavelmente é o título
            return autores, pos, estilo
    return [], 0, ""


def _primeira_sentenca(texto: str) -> tuple[str, str]:
    texto = texto.strip()
    if texto[:1] in "“\"'‘":
        m = re.match(r"[“\"'‘](.+?)[,.]?[”\"'’](?:,|\.)?\s*(.*)$", texto)
        if m:
            return m.group(1).strip(" ,."), m.group(2).strip()
    m = _FIM_FRASE.search(texto)
    if m and m.start() > 5:
        return texto[:m.start() + (1 if texto[m.start()] in "?!" else 0)].strip(" ,."), texto[m.end():].strip()
    return texto.strip(" ,."), ""


def _volume_paginas(fonte: str) -> dict:
    d: dict = {}
    m = re.search(r"\b(\d{1,4})\s*\(\s*([\w\-–]{1,12})\s*\)\s*[:,]?\s*(?:Article\s+)?([A-Za-z]?\d+(?:\s*[-–]\s*[A-Za-z]?\d+)?)?", fonte)
    if m:
        d["volume"], d["numero"] = m.group(1), m.group(2)
        if m.group(3):
            d["paginas"] = re.sub(r"\s*[-–]\s*", "-", m.group(3))
        return d
    m = re.search(r"(?:19|20)\d{2}[a-z]?,\s*(\d{1,4}),\s*([A-Za-z]?\d+(?:\s*[-–]\s*\d+)?)\b", fonte)
    if m:
        d["volume"] = m.group(1)
        d["paginas"] = re.sub(r"\s*[-–]\s*", "-", m.group(2))
        return d
    m = re.search(r"\b[Vv]ol(?:ume)?\.?\s*(\d+)(?:\W+(?:no|n|issue)\.?\s*(\d+))?", fonte)
    if m:
        d["volume"] = m.group(1)
        if m.group(2):
            d["numero"] = m.group(2)
    m = re.search(r"\bpp?\.\s*(\d+\s*[-–]\s*\d+|\d+)", fonte)
    if m:
        d["paginas"] = re.sub(r"\s*[-–]\s*", "-", m.group(1))
    if "volume" not in d:
        m = re.search(r",\s*(\d{1,4}),\s*(\d+\s*[-–]\s*\d+)\s*\.?$", fonte)
        if m:
            d["volume"], d["paginas"] = m.group(1), re.sub(r"\s*[-–]\s*", "-", m.group(2))
    return d


def _nome_da_fonte(fonte: str) -> str:
    f = re.sub(r"^\s*(?:In|Em|En)[:\s]\s*", "", fonte.strip())
    corte = re.search(r",\s*\d|\s\(?(?:19|20)\d{2}|\s\d{1,4}\s*\(|[:,]\s*(?:vol|pp?)\b|\bvol\.|,\s*pages\b|\bpp?\.", f, re.IGNORECASE)
    if corte:
        f = f[:corte.start()]
    return f.strip(" ,.;:")


def interpretar(bruto: str) -> dict:
    """Campos reconhecidos de uma referência: ``autores`` (lista "Sobrenome, N"), ``ano``, ``titulo``, ``fonte``, ``volume``,
    ``numero``, ``paginas``, ``doi``, ``parseada`` e ``bruto``."""
    r: dict = {"bruto": bruto, "autores": [], "ano": None, "titulo": None, "fonte": None, "volume": None, "numero": None,
               "paginas": None, "doi": None, "parseada": False}
    t = bruto
    m = _DOI.search(t)
    if m:
        r["doi"] = m.group(1).rstrip(".,;)")
        t = (t[:m.start()] + " " + t[m.end():]).strip()
    t = _URL.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,;")
    autores, pos, _estilo = _ler_autores(t)
    resto = t[pos:] if autores else t
    ano = None
    am = _ANO_PAREN.search(resto)
    if am and (not autores or am.start() < 40):
        ano = am.group(1)
        resto = resto[am.end():]
    else:
        sm = _ANO_SOLTO.match(resto.lstrip(" .,;:-–"))
        if autores and sm:
            ano = sm.group(1)
            resto = resto.lstrip(" .,;:-–")[sm.end():]
    resto = resto.strip(" .,;:-–")
    if ano:
        r["ano"] = int(ano)
    titulo, fonte = _primeira_sentenca(resto) if resto else ("", "")
    if titulo and not fonte:  # "Título?, 2024": ano colado ao fim do título
        fim = re.search(r"([?!.])?\s*,\s*((?:19|20)\d{2})$", titulo)
        if fim:
            titulo, fonte = titulo[:fim.start()] + (fim.group(1) or ""), fim.group(2)
    if autores and titulo and len(titulo) >= 8 and not re.match(r"(?:and|et|y|e)", titulo):
        r["autores"] = autores
        r["titulo"] = titulo
        r["fonte"] = _nome_da_fonte(fonte) or None
        r.update(_volume_paginas(fonte or ""))
        if not r["ano"]:
            achados = list(_ANO_SOLTO.finditer(fonte or ""))
            if achados:
                r["ano"] = int(achados[0].group(1))
        r["parseada"] = bool(r["autores"] and r["ano"] and r["titulo"])
    elif not r["ano"]:
        achados = list(_ANO_SOLTO.finditer(t))
        if achados:
            r["ano"] = int(achados[-1].group(1))
    return r


def formato_scopus(r: dict) -> str:
    """Referência no estilo do campo ``references`` do Scopus: ``AUTOR, A., AUTOR, B., Título (ANO) Fonte, vol (num), pp. x-y``.

    Sem interpretação completa devolve o texto bruto (sem ``;``, que separa as referências no campo)."""
    if not r.get("parseada"):
        return re.sub(r"\s*;\s*", ", ", r["bruto"]).strip()
    autores = []
    for a in r["autores"]:
        sob, _, nome = a.partition(", ")
        iniciais = "".join(p[0].upper() + "." for p in re.split(r"[\s\-]+", nome.replace(".", " ")) if p)
        autores.append(f"{sob}, {iniciais}" if iniciais else sob)
    texto = ", ".join(autores) + ", " + r["titulo"].rstrip(".")
    texto += f" ({r['ano']})"
    partes = []
    if r.get("fonte"):
        partes.append(r["fonte"])
    if r.get("volume"):
        partes.append(r["volume"] + (f" ({r['numero']})" if r.get("numero") else ""))
    if r.get("paginas"):
        partes.append("pp. " + r["paginas"])
    if partes:
        texto += " " + ", ".join(partes)
    return re.sub(r"\s*;\s*", ", ", texto).strip()


def da_secao_do_markdown(md: str) -> list[dict]:
    """Referências interpretadas de um Markdown convertido (usa a detecção de seções da etapa de limpeza)."""
    from app.services import limpeza_texto as L

    linhas = L.extrair_linhas(md)
    L.remover_repetidas(linhas)
    secoes, mapa, _metodo = L.detectar_secoes(linhas)
    escolhidas = [(l.tipo, l.texto) for l, s in zip(linhas, mapa)
                  if secoes[s]["tipo"] == "referencias" and not l.removida and l.tipo != "titulo"]
    return [interpretar(x) for x in separar(escolhidas)]
