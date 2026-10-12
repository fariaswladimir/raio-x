"""16.4 (b) - Importação genérica de um índice de downloads (CSV) de uma revisão: metadados por documento.

Aceita qualquer CSV com cabeçalho; reconhece as colunas pelo nome (sem acento, minúsculas), por exemplo o
``Indice_downloads_fontes_RSL.csv`` da MLR: ``ID, Citação, Ano, Trilha candidata, URL da fonte, URL do PDF, Estado, Ficheiro, Bytes,
Autor/produtor (extraído da citação), Título (extraído da citação), ...``. O arquivo é só lido (nunca alterado).

Casamento com os documentos do projeto: pelo **nome do arquivo sem extensão** (coluna ``Ficheiro``/``Arquivo``/``File``; o ``.pdf`` do
índice casa com o ``.md`` convertido, sem diferenciar maiúsculas nem acentos). Quando duas linhas apontam para o mesmo arquivo
(duplicatas), vale a linha cujo número de ``ID`` é o prefixo do nome do arquivo; as demais são listadas no relatório.

A coluna de **trilha/grupo** só gera uma **sugestão de grupo** (``grupo_sugerido``): ela nunca altera o grupo do documento sozinha;
o usuário confirma na tela (ou pelo ``PATCH /documentos/{id}``). "branca..." sugere ``branca``; "cinzenta..." sugere ``cinzenta``.
"""
import csv
import io
import re
import unicodedata

from app.services.corpus import referencias as R

CONF = {"titulo": 0.9, "autores": 0.85, "ano": 0.9, "doi": 0.9, "fonte": 0.75, "tipo_documento": 0.7, "url": 0.9, "volume": 0.75, "numero": 0.75, "paginas": 0.75}

_SINONIMOS = {
    "id": ("id", "codigo", "identificador"),
    "citacao": ("citacao", "citation", "referencia", "reference"),
    "ano": ("ano", "year", "ano de publicacao"),
    "trilha": ("trilha", "grupo", "track", "tipo de literatura", "literatura"),
    "url": ("url da fonte", "url fonte", "url", "link", "source url"),
    "url_pdf": ("url do pdf", "pdf url", "url pdf"),
    "estado": ("estado", "status", "situacao"),
    "arquivo": ("ficheiro", "arquivo", "file", "filename", "nome do arquivo", "pdf"),
    "autores": ("autor/produtor", "autor", "autores", "authors", "author"),
    "titulo": ("titulo", "title"),
    "doi": ("doi",),
}


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", _sem_acento(t or "").lower()).strip()


def chave_arquivo(nome: str) -> str:
    base = (nome or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"\.(pdf|md|markdown|txt|docx)$", "", base, flags=re.IGNORECASE)
    return unicodedata.normalize("NFC", base).casefold().strip()


def decodificar(conteudo: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace")


def ler_csv(conteudo: bytes) -> tuple[list[str], list[dict]]:
    texto = decodificar(conteudo)
    amostra = texto[:4000]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t")
    except csv.Error:
        dialeto = csv.excel
    leitor = csv.reader(io.StringIO(texto), dialeto)
    linhas = [l for l in leitor if any(c.strip() for c in l)]
    if len(linhas) < 2:
        return [], []
    cab = [c.strip() for c in linhas[0]]
    return cab, [dict(zip(cab, l + [""] * (len(cab) - len(l)))) for l in linhas[1:]]


def mapear_colunas(cab: list[str]) -> dict[str, str]:
    """Papel -> nome da coluna (primeira que casa, exata antes de por prefixo)."""
    mapa: dict[str, str] = {}
    normas = {c: _norm(c) for c in cab}
    for papel, nomes in _SINONIMOS.items():
        for exata in (True, False):
            achou = None
            for c, n in normas.items():
                if c in mapa.values():
                    continue
                if any((n == s) if exata else (n.startswith(s + " ") or n.startswith(s + "(") or n.startswith(s + "/")) for s in nomes):
                    achou = c
                    break
            if achou:
                mapa[papel] = achou
                break
    return mapa


def sugerir_grupo(trilha: str) -> str | None:
    n = _norm(trilha)
    if not n:
        return None
    if "cinzent" in n or "grey" in n or "gray" in n:
        return "cinzenta"
    if "branca" in n or "white" in n or "academic" in n:
        return "branca"
    return None


def _limpar_tags(t: str) -> str:
    return re.sub(r"^\s*(?:\[[^\]]{1,30}\]\s*)+", "", t or "").strip()


def _autores_do_texto(autores: str, citacao: str, titulo: str | None) -> tuple[list[str], float]:
    bruto = _limpar_tags(autores)
    if not bruto and citacao:  # sem coluna de autores: lê os autores no início da citação
        c = _limpar_tags(citacao)
        achados, _pos, _ = R._ler_autores(c)
        return (achados, 0.8) if achados else ([], 0)
    if not bruto:
        return [], 0
    et_al = bool(re.search(r"\bet\.?\s*al\b", bruto, re.IGNORECASE))
    bruto = re.sub(r",?\s*(?:;\s*)?et\.?\s*al\.?.*$", "", bruto, flags=re.IGNORECASE).strip(" .;,")
    achados, pos, _ = R._ler_autores(bruto + ".")
    if achados and pos >= len(bruto) - 3:
        lista = achados
    elif ";" in bruto and re.search(r"[A-Za-z],\s*\w", bruto):
        lista = [p.strip(" .") for p in bruto.split(";") if p.strip(" .")]
    else:  # produtor institucional ou lista irreconhecível
        partes = [p.strip(" .") for p in re.split(r"\s*;\s*|/", bruto) if p.strip(" .")]
        lista = partes if partes and all(len(p) <= 80 and "," not in p for p in partes) else []
    return lista, 0.7 if et_al else CONF["autores"]


def _tipo_e_fonte(citacao: str, titulo: str | None) -> tuple[dict, str]:
    """Fonte, volume, número, páginas, tipo e DOI a partir do restante da citação (depois do título)."""
    resto = _limpar_tags(citacao)
    if titulo and titulo in resto:
        resto = resto[resto.index(titulo) + len(titulo):]
    elif ". " in resto:
        resto = resto.split(". ", 1)[1]
    resto = resto.lstrip(" .,;:")
    saida: dict = {}
    m = re.search(r"(?:doi|DOI)[:\s]*(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s,;]+)", citacao)
    if m:
        saida["doi"] = m.group(1).rstrip(".,;)")
    n = resto.lower()
    if re.search(r"\barxiv\b", n):
        saida["fonte"], saida["tipo_documento"] = "arXiv", "preprint"
    elif re.search(r"\bssrn\b", n):
        saida["fonte"], saida["tipo_documento"] = "SSRN", "preprint"
    elif re.search(r"preprints\.org", n):
        saida["fonte"], saida["tipo_documento"] = "Preprints.org", "preprint"
    elif re.search(r"\bzenodo\b", n):
        saida["fonte"], saida["tipo_documento"] = "Zenodo", "preprint"
    elif re.search(r"working paper|discussion paper|paper no\.", n):
        saida["tipo_documento"] = "working paper"
        mm = re.search(r"(NBER|IZA|ILO|HKU[^,.]*|Working Paper|Discussion Paper)[^,.;]*", resto, re.IGNORECASE)
        if mm:
            saida["fonte"] = mm.group(0).strip()
    elif re.search(r"\b(neurips|icml|iclr|emnlp|acl|naacl|chi|colm|icetc|aaai|ijcai|kdd|cvpr)\b|proceedings|conference", n):
        saida["tipo_documento"] = "conference paper"
        mm = re.search(r"\b(NeurIPS|ICML|ICLR|EMNLP|NAACL|ACL|CHI|COLM|ICETC|AAAI|IJCAI|KDD|CVPR)\b", resto)
        if mm:
            saida["fonte"] = mm.group(1)
    elif re.search(r"report|relat[oó]rio|technical research post|white ?paper", n):
        saida["tipo_documento"] = "report"
    elif re.search(r"\b\d{1,4}\s*\(\d+[\w\-]*\)|\bv\.\s*\d+|\bvol", n):
        saida["tipo_documento"] = "article"
    if "fonte" not in saida and saida.get("tipo_documento") in ("article", None):
        nome = R._nome_da_fonte(re.split(r"\.\s|,\s*publicad|,\s*submetid|\((?:19|20)\d{2}\)", resto)[0])
        if nome and 3 <= len(nome) <= 120 and not re.match(r"^\d", nome):
            saida["fonte"] = nome
            saida.setdefault("tipo_documento", "article" if re.search(r"\d+\s*\(|\bv\.|vol", resto, re.IGNORECASE) else None)
    vp = R._volume_paginas(resto)
    if not vp.get("volume"):
        mm = re.search(r"\bv\.\s*(\d+),\s*n\.\s*(\d+)", resto)
        if mm:
            vp = {"volume": mm.group(1), "numero": mm.group(2)}
    for k in ("volume", "numero", "paginas"):
        if vp.get(k):
            saida[k] = vp[k]
    return {k: v for k, v in saida.items() if v}, resto


def _titulo_da_citacao(citacao: str) -> str | None:
    """Título = primeira sentença depois dos autores no início da citação (quando a coluna de título falta ou está truncada)."""
    c = _limpar_tags(citacao)
    achados, pos, _ = R._ler_autores(c)
    if not achados:
        return None
    resto = re.sub(r"^\(?(?:19|20)\d{2}[a-z]?\)?[.,]?\s*", "", c[pos:].lstrip(" .,;:"))
    t, _resto = R._primeira_sentenca(resto)
    return t if 8 <= len(t) <= 300 else None


def linha_para_campos(linha: dict, mapa: dict[str, str]) -> dict:
    """Campos candidatos ``{campo: (valor, confianca, detalhe)}`` de uma linha do índice."""
    g = lambda papel: (linha.get(mapa.get(papel, ""), "") or "").strip()
    citacao, titulo = g("citacao"), _limpar_tags(g("titulo"))
    if len(titulo) < 8 and citacao:
        titulo = _titulo_da_citacao(citacao) or titulo
    if len(titulo) < 8 or re.fullmatch(r"\(?(?:19|20)\d{2}\)?\W*", titulo):
        titulo = ""
    campos: dict = {}
    autor_col = _limpar_tags(g("autores"))
    org = None
    if titulo and autor_col and _norm(autor_col) == _norm(titulo):  # a coluna de autores repete a citação inteira ("OECD, Título")
        m = re.match(r"^([^,:.]{2,70}?)\s*[,.]\s+(.{12,})$", titulo)
        if m and len(m.group(1).split()) <= 6:
            org, titulo = m.group(1).strip(), m.group(2).strip(" .")
        autor_col = ""
    if titulo:
        campos["titulo"] = (titulo, CONF["titulo"], "coluna de título do índice")
    if org:
        autores, conf = [org], 0.7
    else:
        autores, conf = _autores_do_texto(autor_col, citacao, titulo or None)
    if autores:
        campos["autores"] = (autores, conf, "coluna de autores do índice" if g("autores") else "citação do índice")
    ano = re.search(r"(?:19|20)\d{2}", g("ano"))
    if ano:
        campos["ano"] = (int(ano.group(0)), CONF["ano"], "coluna de ano do índice")
    if g("url"):
        campos["url"] = (g("url"), CONF["url"], "URL da fonte no índice")
    if citacao:
        extra, _ = _tipo_e_fonte(citacao, titulo or None)
        for k, v in extra.items():
            campos[k] = (v, CONF.get(k, 0.7), "extraído da citação do índice")
    doi = g("doi")
    if doi:
        m = re.search(r"10\.\d{4,9}/\S+", doi)
        if m:
            campos["doi"] = (m.group(0).rstrip(".,;)"), CONF["doi"], "coluna de DOI do índice")
    return campos


def importar(conteudo: bytes, arquivos: dict[str, str]) -> dict:
    """Interpreta o CSV e casa com os documentos. ``arquivos`` = ``{chave_arquivo: arquivo do documento}``.

    Devolve ``{"colunas": {...}, "linhas": n, "casados": {arquivo: {"campos", "grupo", "id", "trilha"}}, "sem_arquivo": [...],
    "sem_documento": [...], "duplicatas": [...]}``."""
    cab, linhas = ler_csv(conteudo)
    if not cab:
        raise ValueError("CSV vazio ou sem cabeçalho.")
    mapa = mapear_colunas(cab)
    if "arquivo" not in mapa:
        raise ValueError("Não encontrei a coluna do nome do arquivo (Ficheiro/Arquivo/File). Colunas: " + ", ".join(cab))
    por_arquivo: dict[str, list[dict]] = {}
    sem_arquivo: list[str] = []
    for l in linhas:
        nome = (l.get(mapa["arquivo"]) or "").strip()
        ident = (l.get(mapa.get("id", ""), "") or "").strip()
        if not nome:
            sem_arquivo.append(ident or "?")
            continue
        por_arquivo.setdefault(chave_arquivo(nome), []).append(l)
    casados: dict = {}
    sem_documento: list[str] = []
    duplicatas: list[dict] = []
    for chave, itens in por_arquivo.items():
        escolhida = itens[0]
        if len(itens) > 1:
            numero = re.match(r"(\d+)", chave)
            for it in itens:
                ident = re.sub(r"\D", "", (it.get(mapa.get("id", ""), "") or ""))
                if numero and ident and int(ident) == int(numero.group(1)):
                    escolhida = it
                    break
            duplicatas.append({"arquivo": chave, "ids": [(it.get(mapa.get("id", ""), "") or "?") for it in itens],
                               "usado": escolhida.get(mapa.get("id", ""), "")})
        if chave not in arquivos:
            sem_documento.append(chave)
            continue
        trilha = (escolhida.get(mapa.get("trilha", ""), "") or "").strip()
        casados[arquivos[chave]] = {"campos": linha_para_campos(escolhida, mapa), "trilha": trilha, "grupo": sugerir_grupo(trilha),
                                    "id": (escolhida.get(mapa.get("id", ""), "") or "").strip()}
    return {"colunas": mapa, "linhas": len(linhas), "casados": casados, "sem_arquivo": sem_arquivo,
            "sem_documento": sem_documento, "duplicatas": duplicatas}
