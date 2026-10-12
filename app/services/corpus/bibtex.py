"""16.3 - Exportação BibTeX no padrão do export do **Scopus**, para ``bibliometrix::convert2df(file, dbsource = "scopus", format = "bibtex")``.

Uma entrada por documento ativo, com os metadados efetivos da 16.4 (``metadados.resolver``) e as **referências citadas** extraídas da
seção de Referências (``referencias``). Campos (nomes do Scopus, que o bibliometrix mapeia para as colunas AU, TI, SO, PY, VL, IS, PP,
DI, URL, C1, AB, DE, CR, LA, DT, DB): ``author`` ("Sobrenome, I. and Sobrenome2, I."; autor institucional entre chaves duplas), ``title``,
``journal`` (fonte; para literatura cinzenta sem periódico, a organização/editora), ``year``, ``volume``, ``number``, ``pages``, ``doi``,
``url``, ``affiliations`` ("Inst1; Inst2"), ``abstract``, ``author_keywords`` ("k1; k2"), ``references`` (itens separados por "; ", cada um
no estilo "AUTOR, A., AUTOR, B., Título (ANO) Fonte, vol (num), pp. x-y"; sem interpretação completa, o texto bruto), ``language``
("English"...), ``document_type``, ``source = {Scopus}`` (o bibliometrix o lê como base de origem) e ``note`` com a origem "Raio-X" (sem dígitos: o bibliometrix os lê
como número de citações). Valores com confiança < 0,35 (ex.: o ano "mais frequente na página") ficam de fora. ``keywords`` (palavras-chave
indexadas, que o Raio-X não tem) só é gravado com ``palavras_indexadas="copiar"`` (cópia das do autor); sem ele o bibliometrix avisa
"Missing fields: ID", sem prejuízo para as análises por palavras-chave do autor (DE).

Tipos de entrada (o Scopus só usa estes): ``article`` -> ``@ARTICLE``; ``conference paper`` -> ``@CONFERENCE``; ``book`` -> ``@BOOK``;
``book chapter`` -> ``@INCOLLECTION``; os demais (relatório, preprint, working paper, página web, desconhecido) -> ``@MISC``, com
``document_type`` coerente ("Report", "Preprint", "Working Paper", "Document").

Escape (``escape``): ``"completo"`` (padrão) protege ``\\ { } & % $ # _ ~ ^`` com a forma LaTeX; ``"minimo"`` só protege ``\\``, ``{`` e ``}``
(como o export real do Scopus, que deixa ``&``/``%`` crus). O arquivo é UTF-8. Dentro de ``references`` um ";" original vira ",".
"""
import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.corpus import metadados as M
from app.services.corpus import projeto as svc_projeto
from app.services.corpus import referencias as R

TIPOS_ENTRADA = {"article": "ARTICLE", "conference paper": "CONFERENCE", "book": "BOOK", "book chapter": "INCOLLECTION"}
TIPOS_DOCUMENTO_SCOPUS = {"article": "Article", "conference paper": "Conference Paper", "book": "Book", "book chapter": "Book Chapter",
                          "report": "Report", "preprint": "Preprint", "working paper": "Working Paper", "thesis": "Thesis",
                          "web page": "Document", "document": "Document"}
IDIOMAS = {"en": "English", "pt": "Portuguese", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "zh": "Chinese"}
_ESCAPES = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
_ESCAPES_MIN = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}"}


def escapar(texto: str, modo: str = "completo") -> str:
    tabela = _ESCAPES if modo == "completo" else _ESCAPES_MIN
    return "".join(tabela.get(c, c) for c in str(texto))


def _limpa_espacos(t: str) -> str:
    return re.sub(r"\s+", " ", str(t)).strip()


def autor_bib(a: str) -> str:
    """"Sobrenome, Nome Composto" -> "Sobrenome, N.C."; sem vírgula (organização) -> "{{Org}}" (marcado com ``@@`` para não ser escapado)."""
    a = _limpa_espacos(a)
    if "," not in a:
        return "{" + a + "}" if a else ""
    sob, _, nome = a.partition(",")
    iniciais = "".join(p[0].upper() + "." for p in re.split(r"[\s\-]+", nome.replace(".", " ")) if p and p[0].isalpha())
    return f"{sob.strip()}, {iniciais}".strip(", ") if iniciais else sob.strip()


def chave_citacao(autores: list[str], ano, usados: set[str]) -> str:
    sob = ""
    if autores:
        sob = autores[0].split(",")[0]
    sob = unicodedata.normalize("NFKD", sob).encode("ascii", "ignore").decode()
    sob = re.sub(r"[^A-Za-z0-9]+", "", sob) or "Doc"
    base = f"{sob}{ano or 'nd'}"
    chave, i = base, 0
    while chave in usados:
        i += 1
        chave = base + chr(ord("a") + (i - 1) % 26) + (str(i // 26) if i >= 26 else "")
    usados.add(chave)
    return chave


def entrada_do_documento(doc, valores: dict, referencias: list[dict], palavras_indexadas: str = "omitir") -> dict:
    tipo = valores.get("tipo_documento") or "document"
    autores = valores.get("autores") or []
    fonte = valores.get("fonte")
    if not fonte and tipo in ("report", "document", "web page", "working paper", "preprint"):
        corporativos = [a for a in autores if "," not in a]
        fonte = valores.get("editora") or (corporativos[0] if corporativos else None)
    ano = valores.get("ano") or doc.ano
    campos: dict[str, str] = {}
    if autores:
        campos["author"] = " and ".join(a for a in (autor_bib(x) for x in autores) if a)
    if valores.get("titulo"):
        campos["title"] = _limpa_espacos(valores["titulo"])
    if fonte:
        campos["journal"] = _limpa_espacos(fonte)
    if ano:
        campos["year"] = str(ano)
    for k_in, k_out in (("volume", "volume"), ("numero", "number"), ("paginas", "pages"), ("doi", "doi"), ("editora", "publisher")):
        if valores.get(k_in):
            campos[k_out] = _limpa_espacos(valores[k_in])
    url = valores.get("url") or (f"https://doi.org/{valores['doi']}" if valores.get("doi") else None)
    if url:
        campos["url"] = url
    if valores.get("afiliacoes"):
        campos["affiliations"] = "; ".join(_limpa_espacos(a) for a in valores["afiliacoes"])
    if valores.get("resumo"):
        campos["abstract"] = _limpa_espacos(valores["resumo"])
    if valores.get("palavras_chave"):
        campos["author_keywords"] = "; ".join(_limpa_espacos(k) for k in valores["palavras_chave"])
    if valores.get("palavras_chave") and palavras_indexadas == "copiar":
        campos["keywords"] = campos["author_keywords"]
    if referencias:
        campos["references"] = "; ".join(R.formato_scopus(r) for r in referencias)
    if valores.get("idioma"):
        campos["language"] = IDIOMAS.get(str(valores["idioma"]).lower()[:2], str(valores["idioma"]))
    campos["document_type"] = TIPOS_DOCUMENTO_SCOPUS.get(tipo, "Document")
    campos["source"] = "Scopus"
    # sem dígitos: o bibliometrix lê números do campo note como "Cited by" (TC)
    campos["note"] = "Origem: Raio-X (exportação para o bibliometrix)"
    return {"tipo": TIPOS_ENTRADA.get(tipo, "MISC"), "campos": campos, "autores": autores, "ano": ano, "n_referencias": len(referencias),
            "referencias_interpretadas": sum(1 for r in referencias if r["parseada"])}


CONFIANCA_MINIMA = 0.35  # abaixo disso (ex.: "ano mais frequente na primeira página") o valor não vai para o .bib


def montar_entradas(db: Session, pasta: Path, palavras_indexadas: str = "omitir", confianca_minima: float = CONFIANCA_MINIMA) -> list[dict]:
    meta = M.carregar(pasta)
    entradas = []
    for doc in svc_projeto.documentos_ativos(db):
        md = svc_projeto.ler_md(pasta, doc)
        refs = R.da_secao_do_markdown(md) if md else []
        e = entrada_do_documento(doc, M.valores(meta["documentos"].get(doc.arquivo), confianca_minima), refs, palavras_indexadas)
        e["arquivo"] = doc.arquivo
        e["documento_id"] = doc.id
        entradas.append(e)
    return entradas


def para_bibtex(entradas: list[dict], escape: str = "completo") -> str:
    usados: set[str] = set()
    saida = []
    for e in entradas:
        chave = chave_citacao(e["autores"], e["ano"], usados)
        linhas = [f"@{e['tipo']}{{{chave},"]
        for campo, valor in e["campos"].items():
            if campo == "author":
                partes = []
                for p in valor.split(" and "):
                    partes.append("{" + escapar(p[1:-1], escape) + "}" if p.startswith("{") and p.endswith("}") else escapar(p, escape))
                texto = " and ".join(partes)
            else:
                texto = escapar(valor, escape)
            linhas.append(f"\t{campo} = {{{texto}}},")
        linhas.append("}")
        saida.append("\n".join(linhas))
    return "\n\n".join(saida) + "\n"
