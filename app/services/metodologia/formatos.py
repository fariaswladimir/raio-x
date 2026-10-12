"""Formatação de referências bibliográficas: ABNT (NBR 6023), APA 7 e BibTeX.

Entrada: um dicionário de referência do catálogo (``autores``, ``ano``, ``titulo``, ``tipo``, ``veiculo``,
``detalhes``, ``doi_ou_url``...; ver catalogo.yaml). Saída: texto simples ou, com ``html=True``, HTML com
negrito (ABNT) e itálico (APA) e todo o texto escapado.

Convenções (resumo)
-------------------
- ABNT: SOBRENOME, N. N. Título. Veículo, v., n., p., ano. Até 3 autores; com mais (ou ``et_al``), o primeiro
  seguido de "et al.". Partículas em minúscula (von, van, de) vão para depois das iniciais.
- APA 7: Sobrenome, N. N., & Sobrenome, N. (ano). Título. *Veículo*, *vol*(n), pp. DOI.
- BibTeX: chave = sobrenome do 1º autor + ano + 1ª palavra do título, em minúsculas e ASCII.
"""
from __future__ import annotations

import html as _html
import re
import unicodedata

_PARTICULAS = {"von", "van", "de", "da", "do", "dos", "das", "der", "den", "di", "du", "le", "la", "del"}


# ---------------------------------------------------------------- utilidades
def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def _partes_nome(autor: str) -> tuple[str, str]:
    """"Sobrenome, Iniciais" -> (sobrenome, iniciais). Sem vírgula, tudo é sobrenome (autor institucional)."""
    sobrenome, _, iniciais = autor.partition(",")
    return sobrenome.strip(), iniciais.strip()


def sobrenome_primeiro_autor(ref: dict) -> str:
    return _partes_nome(ref["autores"][0])[0] if ref.get("autores") else ""


def _detalhe(ref: dict, chave: str) -> str:
    valor = (ref.get("detalhes") or {}).get(chave)
    return "" if valor is None else str(valor).strip()


def _paginas(texto: str, separador: str) -> str:
    """Troca hífen/travessão entre números por ``separador`` ("94-100" -> "94–100" na APA)."""
    return re.sub(r"\s*[-–—]\s*", separador, texto.strip()) if texto else ""


def _fim(texto: str) -> str:
    texto = texto.rstrip()
    return texto if texto.endswith((".", "?", "!")) else texto + "."


class _Marcas:
    """Aplica negrito/itálico conforme o modo (texto simples ou HTML), escapando o conteúdo."""

    def __init__(self, html: bool):
        self.html = html

    def t(self, s: str) -> str:
        return _html.escape(s, quote=False) if self.html else s

    def neg(self, s: str) -> str:
        return f"<b>{_html.escape(s, quote=False)}</b>" if self.html else s

    def it(self, s: str) -> str:
        return f"<i>{_html.escape(s, quote=False)}</i>" if self.html else s

    def url(self, s: str, href: str | None = None) -> str:
        if self.html:
            e = _html.escape(href or s, quote=True)
            return f'<a href="{e}" target="_blank" rel="noopener">{_html.escape(s, quote=False)}</a>'
        return s


def _url_doi(valor: str) -> tuple[str, str]:
    """(tipo, url): tipo = "doi" | "url" | "outro"."""
    v = (valor or "").strip()
    if not v:
        return "", ""
    if v.lower().startswith("doi:"):
        v = v[4:].strip()
    if v.startswith("10."):
        return "doi", v
    if v.lower().startswith("http"):
        return "url", v
    return "outro", v


# ---------------------------------------------------------------- ABNT
def _autor_abnt(autor: str) -> str:
    sob, ini = _partes_nome(autor)
    partic = []
    palavras = sob.split()
    while len(palavras) > 1 and palavras[0] in _PARTICULAS:
        partic.append(palavras.pop(0))
    sob_txt = " ".join(palavras).upper()
    resultado = f"{sob_txt}, {ini}" if ini else sob_txt
    return f"{resultado} {' '.join(partic)}" if partic else resultado


def _autores_abnt(ref: dict) -> str:
    autores = ref.get("autores") or []
    if not autores:
        return ""
    if ref.get("et_al") or len(autores) > 3:
        return f"{_autor_abnt(autores[0])} et al."
    return "; ".join(_autor_abnt(a) for a in autores)


def _organizadores_abnt(orgs: list[str]) -> str:
    if len(orgs) > 3:
        return f"{_autor_abnt(orgs[0])} et al."
    return "; ".join(_autor_abnt(o) for o in orgs)


def _local_editora_abnt(ref: dict, obrigatorio: bool) -> str:
    local, editora = _detalhe(ref, "local"), _detalhe(ref, "editora")
    if not local and not editora and not obrigatorio:
        return ""
    return f"{local or '[S. l.]'}: {editora or '[s. n.]'}"


def formatar_abnt(ref: dict, html: bool = False) -> str:
    """Referência em ABNT NBR 6023."""
    m = _Marcas(html)
    tipo = ref.get("tipo", "artigo")
    titulo = ref["titulo"].rstrip(". ")
    veiculo = ref.get("veiculo", "")
    ano = str(ref["ano"])
    paginas = _paginas(_detalhe(ref, "paginas"), "-")
    edicao = _detalhe(ref, "edicao")
    partes: list[str] = []
    autores = _autores_abnt(ref)
    if autores:
        partes.append(m.t(_fim(autores)))

    if tipo == "artigo":
        partes.append(m.t(_fim(titulo)))
        trecho = [m.neg(veiculo)]
        if _detalhe(ref, "volume"):
            trecho.append(m.t(f"v. {_detalhe(ref, 'volume')}"))
        if _detalhe(ref, "numero"):
            trecho.append(m.t(f"n. {_detalhe(ref, 'numero')}"))
        if paginas:
            trecho.append(m.t(f"p. {paginas}"))
        trecho.append(m.t(ano))
        partes.append(", ".join(trecho) + ".")
    elif tipo == "livro":
        partes.append(m.neg(titulo) + ".")
        if edicao:
            partes.append(m.t(_fim(edicao)))
        partes.append(m.t(f"{_local_editora_abnt(ref, True)}, {ano}."))
    elif tipo == "capitulo":
        partes.append(m.t(_fim(titulo)))
        orgs = ref.get("detalhes", {}).get("organizadores") or []
        entrada = "In:"
        if orgs:
            entrada += f" {_organizadores_abnt(orgs)} ({'org.' if len(orgs) == 1 else 'orgs.'})."
        partes.append(m.t(entrada))
        livro = m.neg(veiculo) + "."
        if _detalhe(ref, "volume"):
            livro += m.t(f" v. {_detalhe(ref, 'volume')}.")
        partes.append(livro)
        if edicao:
            partes.append(m.t(_fim(edicao)))
        le = _local_editora_abnt(ref, False)
        partes.append(m.t(f"{le}, {ano}." if le else f"{ano}."))
        if paginas:
            partes.append(m.t(f"p. {paginas}."))
    elif tipo == "congresso":
        partes.append(m.t(_fim(titulo)))
        partes.append(m.t(f"In: {veiculo.upper()}, {ano}."))
        if paginas:
            partes.append(m.t(f"p. {paginas}."))
    elif tipo == "tese":
        grau = _detalhe(ref, "grau") or "Doutorado"
        nivel = "Dissertação" if grau.lower().startswith("mestr") else "Tese"
        partes.append(m.neg(titulo) + ".")
        partes.append(m.t(f"{ano}."))
        instituicao = ", ".join(x for x in (veiculo, _detalhe(ref, "local")) if x)
        partes.append(m.t(f"{nivel} ({grau}) – {instituicao}, {ano}."))
    elif tipo == "software":
        partes.append(m.neg(titulo) + m.t(" [software]."))
        if edicao:
            partes.append(m.t(_fim(edicao[0].upper() + edicao[1:])))
        le = _local_editora_abnt(ref, False) or veiculo
        partes.append(m.t(f"{le}, {ano}." if le else f"{ano}."))
    else:  # relatorio, web, preprint
        partes.append(m.t(_fim(titulo)))
        resto = veiculo
        if _detalhe(ref, "numero"):
            resto = f"{resto}, {_detalhe(ref, 'numero')}" if resto else _detalhe(ref, "numero")
        le = _local_editora_abnt(ref, False)
        if resto:
            partes.append(m.t(_fim(resto)))
        partes.append(m.t(f"{le}, {ano}." if le else f"{ano}."))

    kind, valor = _url_doi(ref.get("doi_ou_url", ""))
    if kind == "doi":
        partes.append(m.t("DOI: ") + m.url(valor, f"https://doi.org/{valor}") + ".")
    elif kind == "url":
        partes.append(m.t("Disponível em: ") + m.url(valor) + ".")
    elif kind == "outro":
        partes.append(m.t(valor))
    return " ".join(p for p in partes if p)


# ---------------------------------------------------------------- APA 7
def _autor_apa(autor: str) -> str:
    sob, ini = _partes_nome(autor)
    return f"{sob}, {ini}" if ini else sob


def _autor_apa_invertido(autor: str) -> str:
    """Para editores: "M. W. Berry"."""
    sob, ini = _partes_nome(autor)
    return f"{ini} {sob}".strip()


def _lista_apa(nomes: list[str], et_al: bool = False) -> str:
    if et_al:
        return f"{nomes[0]}, et al."
    if len(nomes) == 1:
        return nomes[0]
    if len(nomes) == 2:
        return f"{nomes[0]}, & {nomes[1]}"
    return ", ".join(nomes[:-1]) + f", & {nomes[-1]}"


def _autores_apa(ref: dict) -> str:
    autores = [_autor_apa(a) for a in ref.get("autores") or []]
    if not autores:
        return ""
    return _lista_apa(autores[:20], bool(ref.get("et_al")))


def _edicao_apa(edicao: str) -> str:
    achou = re.match(r"^(\d+)\.\s*ed\.?$", edicao.strip())
    if achou:
        n = int(achou.group(1))
        sufixo = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{sufixo} ed."
    achou = re.match(r"^vers[ãa]o\s+(.+)$", edicao.strip(), re.I)
    if achou:
        return f"Version {achou.group(1)}"
    return edicao


def formatar_apa(ref: dict, html: bool = False) -> str:
    """Referência em APA 7 (inglês, como no estilo original)."""
    m = _Marcas(html)
    tipo = ref.get("tipo", "artigo")
    titulo = ref["titulo"].rstrip(". ")
    veiculo = ref.get("veiculo", "")
    ano = str(ref["ano"])
    paginas = _paginas(_detalhe(ref, "paginas"), "–")
    edicao = _edicao_apa(_detalhe(ref, "edicao")) if _detalhe(ref, "edicao") else ""
    editora = _detalhe(ref, "editora")
    autores = _autores_apa(ref)
    cabeca = f"{_fim(autores)} ({ano})." if autores else f"({ano})."
    partes: list[str] = [m.t(cabeca)]

    if tipo == "artigo":
        partes.append(m.t(_fim(titulo)))
        vol, num = _detalhe(ref, "volume"), _detalhe(ref, "numero")
        trecho = m.it(veiculo)
        if vol:
            trecho += ", " + m.it(vol)
        if num:
            trecho += m.t(f"({num})")
        if paginas:
            trecho += m.t(f", {paginas}")
        partes.append(trecho + ".")
    elif tipo == "livro":
        entre = f" ({edicao})" if edicao else ""
        partes.append(m.it(titulo) + m.t(entre + "."))
        if editora:
            partes.append(m.t(_fim(editora)))
    elif tipo == "capitulo":
        partes.append(m.t(_fim(titulo)))
        orgs = [_autor_apa_invertido(o) for o in ref.get("detalhes", {}).get("organizadores") or []]
        rotulo = "Ed." if len(orgs) == 1 else "Eds."
        entrada = "In "
        if orgs:
            entrada += (orgs[0] if len(orgs) == 1 else " & ".join(orgs) if len(orgs) == 2
                        else ", ".join(orgs[:-1]) + ", & " + orgs[-1]) + f" ({rotulo}), "
        partes.append(m.t(entrada) + m.it(veiculo))
        extras = []
        if _detalhe(ref, "volume"):
            extras.append(f"Vol. {_detalhe(ref, 'volume')}")
        if edicao:
            extras.append(edicao.rstrip("."))
        if paginas:
            extras.append(f"pp. {paginas}")
        partes[-1] += (m.t(f" ({', '.join(extras)})") if extras else "") + "."
        if editora:
            partes.append(m.t(_fim(editora)))
    elif tipo == "congresso":
        partes.append(m.t(_fim(titulo)))
        trecho = m.t("In ") + m.it(veiculo)
        if paginas:
            trecho += m.t(f" (pp. {paginas})")
        partes.append(trecho + ".")
        if editora:
            partes.append(m.t(_fim(editora)))
    elif tipo == "tese":
        grau = _detalhe(ref, "grau") or "Doutorado"
        rotulo = "Master's thesis" if grau.lower().startswith("mestr") else "Doctoral dissertation"
        partes.append(m.it(titulo) + m.t(f" [{rotulo}, {veiculo}]."))
    elif tipo == "software":
        entre = f" ({edicao})" if edicao else ""
        partes.append(m.it(titulo) + m.t(f"{entre} [Computer software]."))
        publicador = editora or veiculo
        if publicador:
            partes.append(m.t(_fim(publicador)))
    elif tipo == "relatorio":
        entre = f" ({veiculo})" if veiculo else ""
        partes.append(m.it(titulo) + m.t(entre + "."))
        if editora:
            partes.append(m.t(_fim(editora)))
    else:  # preprint, web
        partes.append(m.it(titulo) + ".")
        if veiculo:
            partes.append(m.t(_fim(veiculo)))

    kind, valor = _url_doi(ref.get("doi_ou_url", ""))
    if kind == "doi":
        partes.append(m.url(f"https://doi.org/{valor}"))
    elif kind == "url":
        partes.append(m.url(valor))
    elif kind == "outro":
        partes.append(m.t(valor))
    return " ".join(p for p in partes if p)


# ---------------------------------------------------------------- BibTeX
def chave_bibtex(ref: dict) -> str:
    """sobrenome do 1º autor + ano + 1ª palavra do título (minúsculas, ASCII, só letras e dígitos)."""
    sob = re.sub(r"[^a-z0-9]", "", _ascii(sobrenome_primeiro_autor(ref)).lower())
    palavras = ref["titulo"].split()
    primeira = re.sub(r"[^a-z0-9]", "", _ascii(palavras[0]).lower()) if palavras else ""
    return f"{sob}{ref['ano']}{primeira}"


def _tex(texto: str) -> str:
    return re.sub(r"([&%$#_])", r"\\\1", texto)


def _autor_bib(autor: str) -> str:
    sob, ini = _partes_nome(autor)
    return f"{sob}, {ini}" if ini else f"{{{sob}}}"


def formatar_bibtex(ref: dict, chave: str | None = None) -> str:
    """Entrada BibTeX. ``chave`` substitui a calculada (usado para desfazer colisões)."""
    tipo = ref.get("tipo", "artigo")
    entrada = {"artigo": "article", "livro": "book", "capitulo": "incollection", "congresso": "inproceedings",
               "tese": "phdthesis", "relatorio": "techreport"}.get(tipo, "misc")
    if tipo == "tese" and (_detalhe(ref, "grau").lower().startswith("mestr")):
        entrada = "mastersthesis"
    campos: list[tuple[str, str]] = []
    autores = [_autor_bib(a) for a in ref.get("autores") or []]
    if autores:
        campos.append(("author", " and ".join(autores) + (" and others" if ref.get("et_al") else "")))
    campos.append(("title", "{" + _tex(ref["titulo"]) + "}"))
    veiculo = ref.get("veiculo", "")
    paginas = _paginas(_detalhe(ref, "paginas"), "--")
    if tipo == "artigo":
        campos.append(("journal", _tex(veiculo)))
        for nome, chave_d in (("volume", "volume"), ("number", "numero")):
            if _detalhe(ref, chave_d):
                campos.append((nome, _detalhe(ref, chave_d)))
        if paginas:
            campos.append(("pages", paginas))
    elif tipo == "livro":
        campos.append(("publisher", _tex(_detalhe(ref, "editora"))))
        if _detalhe(ref, "local"):
            campos.append(("address", _tex(_detalhe(ref, "local"))))
        if _detalhe(ref, "edicao"):
            campos.append(("edition", _detalhe(ref, "edicao")))
    elif tipo == "capitulo":
        campos.append(("booktitle", _tex(veiculo)))
        orgs = ref.get("detalhes", {}).get("organizadores") or []
        if orgs:
            campos.append(("editor", " and ".join(_autor_bib(o) for o in orgs)))
        for nome, chave_d in (("volume", "volume"), ("publisher", "editora"), ("address", "local")):
            if _detalhe(ref, chave_d):
                campos.append((nome, _tex(_detalhe(ref, chave_d))))
        if paginas:
            campos.append(("pages", paginas))
    elif tipo == "congresso":
        campos.append(("booktitle", _tex(veiculo)))
        if paginas:
            campos.append(("pages", paginas))
    elif tipo == "tese":
        campos.append(("school", _tex(veiculo)))
        if _detalhe(ref, "local"):
            campos.append(("address", _tex(_detalhe(ref, "local"))))
    elif tipo == "relatorio":
        campos.append(("institution", _tex(_detalhe(ref, "editora") or veiculo)))
        if _detalhe(ref, "editora") and veiculo:
            campos.append(("type", _tex(veiculo)))
        if _detalhe(ref, "local"):
            campos.append(("address", _tex(_detalhe(ref, "local"))))
    else:  # software, web, preprint
        publicador = _detalhe(ref, "editora") or veiculo
        if publicador:
            campos.append(("howpublished" if tipo == "web" else "publisher", _tex(publicador)))
        if tipo == "software":
            nota = "Software" + (f", {_detalhe(ref, 'edicao')}" if _detalhe(ref, "edicao") else "")
            campos.append(("note", nota))
        elif _detalhe(ref, "numero"):
            campos.append(("note", _tex(_detalhe(ref, "numero"))))
    campos.append(("year", str(ref["ano"])))
    kind, valor = _url_doi(ref.get("doi_ou_url", ""))
    if kind == "doi":
        campos.append(("doi", valor))
    elif kind in ("url", "outro") and valor.lower().startswith("http"):
        campos.append(("url", valor))
    corpo = ",\n".join(f"  {nome} = {{{valor}}}" for nome, valor in campos if valor != "")
    return f"@{entrada}{{{chave or chave_bibtex(ref)},\n{corpo}\n}}"


# ---------------------------------------------------------------- conjuntos
def _chave_ordem(ref: dict) -> tuple:
    return (_ascii(sobrenome_primeiro_autor(ref)).lower(), ref["ano"], _ascii(ref["titulo"]).lower())


def ordenar(refs: list[dict]) -> list[dict]:
    """Ordem alfabética por sobrenome do primeiro autor, ano e título."""
    return sorted(refs, key=_chave_ordem)


def chaves_bibtex_unicas(refs: list[dict]) -> list[str]:
    """Chave BibTeX de cada referência, com sufixo a, b, c... quando duas coincidem."""
    base = [chave_bibtex(r) for r in refs]
    vistos: dict[str, int] = {}
    resultado = []
    for chave in base:
        n = vistos.get(chave, 0)
        vistos[chave] = n + 1
        resultado.append(chave if n == 0 else f"{chave}{chr(ord('a') + n - 1)}")
    return resultado


def formatar(ref: dict, formato: str, html: bool = False) -> str:
    formato = formato.lower()
    if formato == "abnt":
        return formatar_abnt(ref, html)
    if formato == "apa":
        return formatar_apa(ref, html)
    if formato == "bibtex":
        return formatar_bibtex(ref)
    raise ValueError(f"Formato inválido '{formato}': use abnt, apa ou bibtex.")
