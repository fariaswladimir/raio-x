"""16.4 - Metadados bibliográficos por documento: título, autores, ano, fonte, DOI, resumo, palavras-chave do autor,
afiliações, idioma e tipo de documento, cada campo com **valor, origem e confiança**.

Origens (``origem``), da mais para a menos confiável por padrão:
- ``manual``: editado pelo usuário (PATCH); sempre vence;
- ``online``: consulta por DOI (Crossref/OpenAlex), **desligada por padrão** (ver ``online.py`` e a tela);
- ``indice``: índice de downloads da revisão importado (CSV genérico, ``importar_indice``), casado pelo nome do arquivo;
- ``texto``: extraído das primeiras páginas do Markdown convertido (``extrair_do_texto``): melhor esforço, com confiança 0,4-0,8.

Armazenamento: ``projetos/<slug>/metadados.json`` (compatível com projetos antigos: sem o arquivo, nada muda), chaveado pelo
``arquivo`` do documento (estável entre execuções). Para cada documento guarda os **candidatos** de cada campo por origem
(``candidatos``), os valores **manuais** e a sugestão de grupo vinda do índice (``grupo_sugerido``, nunca aplicada sozinha).
O valor efetivo (``resolver``) é: manual > o candidato de maior confiança; quando duas origens discordam (comparação
normalizada) o campo entra em ``conflitos`` para o usuário decidir.

Extração do texto (primeira página, depois da segunda se faltar algo):
- título: primeiro título ``##`` que não é genérico (Abstract, Article, Resumo, Highlights...), senão a primeira linha longa;
- autores/afiliações: linhas entre o título e o resumo; linha de afiliação = tem Universidade/Institute/Department/...;
  linha de autores = nomes (2 a 5 palavras com inicial maiúscula) separados por vírgula/``and``/``y``/``e``/``&`` ou por marcas
  (``*``, ``†``, dígitos sobrescritos); e-mails, ORCID, datas e marcas saem;
- DOI: ``10.xxxx/...`` (ou link doi.org) nas duas primeiras páginas; palavras-chave: linha ``Keywords:``/``Palavras-chave:``/
  ``Palabras clave:``; resumo: seção ``resumo`` do texto limpo (o ``Abstract`` em inglês se houver os dois);
- ano: ``©``, ``Published/Publicado``, data junto aos autores, senão o ano mais citado na primeira página (confiança baixa);
- fonte (periódico/evento): linha curta com Journal/Proceedings/Conference/Review... ou ``arXiv``.
"""
import datetime
import html
import json
import re
import unicodedata
from pathlib import Path

CAMPOS = ("titulo", "autores", "ano", "fonte", "doi", "resumo", "palavras_chave", "afiliacoes", "idioma", "tipo_documento",
          "volume", "numero", "paginas", "editora", "url")
CAMPOS_LISTA = ("autores", "palavras_chave", "afiliacoes")
ROTULOS = {
    "titulo": "Título", "autores": "Autores", "ano": "Ano", "fonte": "Fonte (periódico/evento/organização)", "doi": "DOI",
    "resumo": "Resumo", "palavras_chave": "Palavras-chave do autor", "afiliacoes": "Afiliações", "idioma": "Idioma",
    "tipo_documento": "Tipo de documento", "volume": "Volume", "numero": "Número", "paginas": "Páginas", "editora": "Editora",
    "url": "URL",
}
ORIGENS = ("manual", "online", "indice", "texto")
ARQUIVO = "metadados.json"
VERSAO = 1
TIPOS_DOCUMENTO = ("article", "conference paper", "book", "book chapter", "report", "working paper", "preprint", "thesis", "web page", "document")

_GENERICOS = {
    "abstract", "resumo", "resumen", "article", "articulo", "artigo", "research article", "original article", "review", "review article",
    "preprint", "working paper", "highlights", "contents", "table of contents", "sumario", "indice", "keywords", "introduction",
    "introducao", "executive summary", "summary", "report", "paper", "research paper", "original research", "full paper", "short paper",
    "regular article", "open access", "check for updates", "editorial", "case study", "systematic review", "literature review",
    "acknowledgements", "references", "contents lists available at sciencedirect", "peer review", "peer-reviewed",
}
_AFILIACAO = re.compile(
    r"\b(universit|universidad|universidade|institut|instituto|department|departamento|school of|school$|college|faculty|facultad|"
    r"faculdade|laborator|laboratorio|centre|center|centro|academy|hospital|corporation|inc\b|ltd\b|gmbh|research|business school|"
    r"escuela|escola|politecnic|polytechnic|ministry|agency|foundation|fundação|bank|group|lab\b|labs\b|cnrs|mit\b|inria)", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_URL = re.compile(r"https?://\S+|www\.\S+|orcid\.org/\S+", re.IGNORECASE)
_DOI = re.compile(r"\b(?:doi\s*[:.]?\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s<>\"\]\)]+)", re.IGNORECASE)
_MARCAS = re.compile(r"[∗*†‡§¶♦♣♠⋆#¹²³⁴⁵⁶⁷⁸⁹⁰✉]+")
_SUPER = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+")
_DATA = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?|janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|enero|febrero|marzo|mayo|junio|"
    r"julio|septiembre|octubre|noviembre|diciembre)\.?\s*\d{0,2},?\s*(?:19|20)\d{2}\b|\b\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}\b", re.IGNORECASE)
_PALAVRAS_CHAVE = re.compile(
    r"^[\s*_#>\-]*(?:author\s+)?(?:key\s*words?|keywords?|index terms|palavras[\s\-]*chave|palabras[\s\-]*clave|mots[\s\-]*cl[eé]s|schl[uü]sselw[oö]rter)\s*[:：\-–—.]?\s*\**\s*(.*)$",
    re.IGNORECASE)
_FONTE_LINHA = re.compile(
    r"\b(journal of|journal|proceedings|conference|symposium|workshop|review of|transactions|letters|quarterly|annals|revista|anais|"
    r"bulletin|magazine|iza discussion paper|nber working paper|working paper|technical report)\b", re.IGNORECASE)
_PARTICULAS = {"de", "da", "do", "dos", "das", "del", "della", "di", "van", "von", "der", "den", "la", "le", "bin", "al", "ter", "ten", "dos"}
_CONECTORES = re.compile(r"\s*(?:,|;|\band\b|\by\b|\be\b|&|&amp;|\|)\s*", re.IGNORECASE)


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def _chave_titulo(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _sem_acento(t).lower()).strip()


# ---------- extração do texto ----------

def _linhas_da_pagina(md: str, max_paginas: int = 2) -> list[tuple[str, str]]:
    """Linhas ``(tipo, texto)`` das primeiras páginas; tipo = ``titulo`` (## ...) | ``texto`` | ``vazio``. Comentários HTML saem."""
    from app.services.texto import MARCADOR_PAGINA, COMENTARIO_HTML

    md = md.replace("\r\n", "\n")
    saida: list[tuple[str, str]] = []
    pagina = 0
    for bruta in md.split("\n"):
        m = MARCADOR_PAGINA.search(bruta)
        if m:
            pagina = int(m.group(1))
            continue
        if pagina > max_paginas:
            break
        t = html.unescape(COMENTARIO_HTML.sub("", bruta)).strip()
        if not t:
            saida.append(("vazio", ""))
            continue
        h = re.match(r"^#{1,6}\s+(.*?)\s*#*$", t)
        if h:
            saida.append(("titulo", re.sub(r"[*_`]+", "", h.group(1)).strip()))
        else:
            saida.append(("texto", re.sub(r"^[-*+•]\s+", "", t)))
    return saida


def _titulo_generico(t: str) -> bool:
    k = _chave_titulo(t)
    if not k or k in _GENERICOS or re.search(r"(?:series|journal homepage)$", k) or re.match(r"^(?:discussion|working|technical|research) paper", k):
        return True
    if re.match(r"^(?:\d+\s+|[ivx]+\s+)?(?:abstract|resumo|resumen|introduction|introducao|keywords|contents)\b", k):
        return True
    return len(k.split()) < 2 and len(k) < 14


def extrair_titulo(linhas: list[tuple[str, str]]) -> tuple[str | None, int, float]:
    """``(título, índice da linha, confiança)``."""
    for i, (tipo, t) in enumerate(linhas):
        if tipo == "titulo" and not _titulo_generico(t) and not re.match(r"^\W*(?:arxiv|preprint|doi|received|recibido)", t, re.IGNORECASE):
            t = re.sub(r"\s+", " ", t)
            # título quebrado em dois "##" consecutivos: junta se o segundo não é genérico nem parece nome/afiliação
            j = i + 1
            while j < len(linhas) and linhas[j][0] == "vazio":
                j += 1
            if j < len(linhas) and linhas[j][0] == "titulo" and not _titulo_generico(linhas[j][1]) and len(linhas[j][1]) > 3 \
                    and t[-1] not in ".?!" and linhas[j][1][:1].islower():
                t = t + " " + linhas[j][1]
            return t.strip(" .:"), i, 0.8
    for i, (tipo, t) in enumerate(linhas):
        if tipo == "texto" and 20 <= len(t) <= 220 and not _titulo_generico(t) and not _EMAIL.search(t) and not _AFILIACAO.search(t) \
                and not re.match(r"^\W*(?:arxiv|preprint|http|doi|received|published|©|copyright)", t, re.IGNORECASE):
            return t.strip(" .:"), i, 0.4
    return None, -1, 0.0


def _limpar_nome_linha(t: str) -> str:
    t = _EMAIL.sub(" ", t)
    t = _URL.sub(" ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = _DATA.sub(" ", t)
    return t


def _nome_valido(p: str) -> bool:
    p = p.strip(" .,;:")
    if not p:
        return False
    palavras = p.split()
    if not 2 <= len(palavras) <= 6:
        return False
    for w in palavras:
        if w.lower() in _PARTICULAS:
            continue
        if not re.match(r"^[A-ZÀ-ÝÇ][\wÀ-ÿ'’\-]*\.?$", w) and not re.match(r"^[A-Z]\.?$", w):
            return False
    return not _AFILIACAO.search(p) and not re.search(r"\d", p)


def _formatar_autor(nome: str) -> str:
    """"Given Names Surname" -> "Surname, Given Names" (partículas de/van/da ficam com o sobrenome)."""
    palavras = nome.replace(".", ". ").split()
    palavras = [w for w in palavras if w]
    if len(palavras) < 2:
        return nome.strip()
    k = len(palavras) - 1
    while k > 1 and palavras[k - 1].lower() in _PARTICULAS:
        k -= 1
    return f"{' '.join(palavras[k:])}, {' '.join(palavras[:k])}".replace(" .", ".")


def extrair_autores_afiliacoes(linhas: list[tuple[str, str]], ini: int, fim: int) -> tuple[list[str], list[str]]:
    autores: list[str] = []
    afiliacoes: list[str] = []
    for tipo, t in linhas[max(ini + 1, 0):fim]:
        if tipo != "texto" or not t:
            continue
        if re.match(r"^(?:received|recibido|recebido|accepted|aceito|published|publicado|correspond|cita:|citation|copyright|©|how to cite)", t, re.IGNORECASE):
            continue
        base = _limpar_nome_linha(t)
        sem_numero = re.sub(r"^\s*[\d\W]{0,4}\s*(?=[A-Za-z])", "", base)
        sem_numero = _MARCAS.sub(" ", sem_numero).strip(" ,;.-")
        if _AFILIACAO.search(base) and len(sem_numero.split()) >= 2:
            af = re.sub(r"\s+", " ", sem_numero).strip(" ,;.-")
            af = re.sub(r"[.,;]?\s*(?:co-?)?corresponding author.*$", "", af, flags=re.IGNORECASE).strip(" ,;.-")
            if 6 <= len(af) <= 250 and af not in afiliacoes:
                afiliacoes.append(af)
            continue
        if len(autores) >= 40:
            continue
        # linha de autores: marcas e números de afiliação viram separadores
        cand = re.sub(r"(?<=[A-Za-zÀ-ÿ])\s*\d+(?:\s*,\s*\d+)*\s*(?:,\s*\*)?", " | ", base)
        cand = _MARCAS.sub(" | ", cand)
        cand = re.sub(r"\band(?=[A-Z])", " and ", cand)
        partes = [p.strip(" .,;:") for p in _CONECTORES.split(cand)]
        partes = [p for p in partes if p]
        if partes and all(_nome_valido(p) for p in partes) and len(" ".join(partes)) < 400:
            for p in partes:
                a = _formatar_autor(p)
                if a not in autores:
                    autores.append(a)
    return autores, afiliacoes


def _ano_do_texto(texto: str) -> tuple[int | None, float, str]:
    anoatual = datetime.date.today().year + 1
    for padrao, conf, motivo in (
        (r"(?:©|\(c\)|copyright)\s*(?:by\s+)?(?:the\s+author\w*,?\s*)?((?:19|20)\d{2})", 0.7, "©"),
        (r"(?:published|publicado|publicaci[oó]n|publicada|accepted|aceito|aceptado|received|recibido|recebido)\W{0,12}(?:online\W{0,6})?(?:\w+\W{1,3}){0,3}?((?:19|20)\d{2})", 0.65, "data de publicação"),
        (r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december|janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s*\d{0,2},?\s*((?:19|20)\d{2})\b", 0.55, "data na primeira página"),
        (r"\barxiv:\s*(\d{2})\d{2}\.\d{4,5}", 0.6, "arXiv"),
    ):
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            a = int(m.group(1))
            if a < 100:
                a += 2000
            if 1950 <= a <= anoatual:
                return a, conf, motivo
    anos = [int(x) for x in re.findall(r"\b((?:19|20)\d{2})\b", texto) if 1950 <= int(x) <= anoatual]
    if anos:
        from collections import Counter

        a, n = Counter(anos).most_common(1)[0]
        return a, 0.3, "ano mais frequente na primeira página"
    return None, 0.0, ""


def _tipo_do_texto(texto: str, fonte: str | None) -> tuple[str | None, float]:
    t = texto.lower()
    if re.search(r"arxiv[:\s]\s*\d{4}\.\d{4,5}|\barxiv\b.{0,40}\[(?:cs|stat|econ|q-fin|math|physics)\.", t):
        return "preprint", 0.7
    if re.search(r"preprints?\.org|ssrn|zenodo|researchsquare|osf\.io|preprint", t):
        return "preprint", 0.55
    if re.search(r"working paper|discussion paper|documento de trabajo|texto para discuss", t):
        return "working paper", 0.6
    if re.search(r"proceedings of|conference on|symposium|workshop|\bconferência\b|\bcongreso\b", t[:2500]):
        return "conference paper", 0.5
    if re.search(r"white ?paper|technical report|relat[óo]rio t[ée]cnico|informe t[ée]cnico|\bsurvey report\b|policy brief|\breport\b", t[:1200]):
        return "report", 0.45
    if fonte and re.search(r"journal|revista|review|letters|transactions|annals", fonte, re.IGNORECASE):
        return "article", 0.6
    if re.search(r"\bjournal\b|\brevista\b|\babstract\b|\bresumo\b", t[:3000]) and re.search(r"keywords?|palavras.chave|palabras clave", t[:5000]):
        return "article", 0.45
    return None, 0.0


def extrair_do_texto(md: str, resumo_limpo: str | None = None, idioma: str | None = None) -> dict:
    """Campos extraídos do Markdown convertido (primeiras páginas): ``{campo: {"valor", "confianca", "detalhe"}}`` (só os achados)."""
    linhas = _linhas_da_pagina(md, 2)
    pagina1 = _linhas_da_pagina(md, 1)
    texto1 = "\n".join(t for _, t in pagina1)
    texto12 = "\n".join(t for _, t in linhas)
    res: dict = {}
    titulo, i_titulo, c = extrair_titulo(pagina1 if any(t == "titulo" for t, _ in pagina1) else linhas)
    base_linhas = pagina1 if any(t == "titulo" for t, _ in pagina1) else linhas
    if titulo:
        res["titulo"] = {"valor": titulo, "confianca": c, "detalhe": "primeiro título não genérico" if c >= 0.7 else "primeira linha longa"}
    # fim do bloco de autores: início do resumo/palavras-chave
    fim = len(base_linhas)
    for j in range(max(i_titulo + 1, 0), len(base_linhas)):
        tipo, t = base_linhas[j]
        if (tipo == "titulo" and re.match(r"^\W*(?:abstract|resumo|resumen|summary|highlights|keywords)", t, re.IGNORECASE)) \
                or re.match(r"^\W*(?:abstract|resumo|resumen)\b", t, re.IGNORECASE) or _PALAVRAS_CHAVE.match(t):
            fim = j
            break
        if tipo == "titulo" and j > i_titulo + 1 and not _titulo_generico(t) and re.match(r"^\d", t):
            fim = j
            break
    if i_titulo >= 0:
        autores, afs = extrair_autores_afiliacoes(base_linhas, i_titulo, min(fim, i_titulo + 40))
        if autores:
            res["autores"] = {"valor": autores, "confianca": 0.6, "detalhe": "linhas entre o título e o resumo"}
        if afs:
            res["afiliacoes"] = {"valor": afs, "confianca": 0.55, "detalhe": "linhas de afiliação da primeira página"}
    # rodapés tipo "∗SNU Business School, ..." (marca no início): afiliações que ficaram fora do bloco
    if "afiliacoes" not in res or len(res["afiliacoes"]["valor"]) < 1:
        extras = []
        for _, t in base_linhas:
            if _MARCAS.match(t[:2]) or re.match(r"^\d\s", t):
                sem = _MARCAS.sub(" ", _EMAIL.sub(" ", _URL.sub(" ", t))).strip(" ,;.-")
                sem = re.sub(r"^\d\s+", "", sem)
                sem = re.sub(r"[.,;]?\s*(?:co-?)?corresponding author.*$", "", sem, flags=re.IGNORECASE).strip(" ,;.-")
                if _AFILIACAO.search(sem) and 6 <= len(sem) <= 250 and sem not in extras:
                    extras.append(sem)
        if extras:
            res["afiliacoes"] = {"valor": extras, "confianca": 0.5, "detalhe": "notas de rodapé da primeira página"}
    m = _DOI.search(texto12)
    if m:
        res["doi"] = {"valor": m.group(1).rstrip(".,;)"), "confianca": 0.8, "detalhe": "DOI nas duas primeiras páginas"}
    for _, t in linhas:
        m = _PALAVRAS_CHAVE.match(t)
        if m and m.group(1).strip():
            partes = [p.strip(" .*_") for p in re.split(r"\s*[;·•|]\s*|\s*,\s*(?![^()]*\))", m.group(1)) if p.strip(" .*_")]
            if len(partes) == 1 and re.search(r"\s{2,}|\s[-–—]\s", m.group(1)):
                partes = [p.strip() for p in re.split(r"\s[-–—]\s|\s{2,}", m.group(1)) if p.strip()]
            partes = [p for p in partes if 1 < len(p) < 80][:15]
            if partes:
                res["palavras_chave"] = {"valor": partes, "confianca": 0.8, "detalhe": "linha de palavras-chave"}
                break
    if resumo_limpo and len(resumo_limpo.split()) >= 20:
        res["resumo"] = {"valor": resumo_limpo, "confianca": 0.75, "detalhe": "seção de resumo detectada (3.1)"}
    ano, c, motivo = _ano_do_texto(texto1 or texto12)
    if ano:
        res["ano"] = {"valor": ano, "confianca": c, "detalhe": motivo}
    # fonte
    fonte = None
    if re.search(r"arxiv[:\s]\s*\d{4}\.\d{4,5}", texto12, re.IGNORECASE):
        fonte, c = "arXiv", 0.6
    else:
        for _, t in base_linhas[:25]:
            if _FONTE_LINHA.search(t) and 8 <= len(t) <= 110 and not re.search(r"\b(?:this|we|our|the)\b.{0,40}\b(?:paper|study|article)\b", t, re.IGNORECASE) \
                    and not _EMAIL.search(t) and not t.rstrip().endswith("."):
                fonte, c = re.sub(r"[*_#]+", "", t).strip(" |·-"), 0.4
                break
    if fonte:
        res["fonte"] = {"valor": fonte, "confianca": c, "detalhe": "cabeçalho da primeira página"}
    tipo, ct = _tipo_do_texto(texto12, fonte)
    if tipo:
        res["tipo_documento"] = {"valor": tipo, "confianca": ct, "detalhe": "indícios no texto"}
    if idioma:
        res["idioma"] = {"valor": idioma, "confianca": 0.9, "detalhe": "detecção de idioma da etapa de qualidade"}
    return res


# ---------- armazenamento ----------

def caminho(pasta_projeto: Path) -> Path:
    return pasta_projeto / ARQUIVO


def carregar(pasta_projeto: Path) -> dict:
    c = caminho(pasta_projeto)
    if c.is_file():
        try:
            d = json.loads(c.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("documentos"), dict):
                return d
        except ValueError:
            pass
    return {"versao": VERSAO, "documentos": {}, "indice": None}


def salvar(pasta_projeto: Path, dados: dict) -> None:
    dados["versao"] = VERSAO
    caminho(pasta_projeto).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def _entrada(dados: dict, arquivo: str) -> dict:
    return dados["documentos"].setdefault(arquivo, {"candidatos": {}, "manual": {}, "grupo_sugerido": None})


def definir_candidato(entrada: dict, campo: str, origem: str, valor, confianca: float, detalhe: str = "") -> None:
    if valor in (None, "", []):
        return
    lista = [c for c in entrada["candidatos"].setdefault(campo, []) if c["origem"] != origem]
    lista.append({"origem": origem, "valor": valor, "confianca": round(float(confianca), 2), "detalhe": detalhe})
    entrada["candidatos"][campo] = lista


def limpar_origem(entrada: dict, origem: str) -> None:
    for campo, lista in list(entrada["candidatos"].items()):
        entrada["candidatos"][campo] = [c for c in lista if c["origem"] != origem]


# ---------- resolução e conflitos ----------

def _norm_valor(campo: str, v) -> str:
    if campo == "autores":
        return "|".join(sorted(_chave_titulo(a.split(",")[0]) for a in v))
    if campo in ("palavras_chave", "afiliacoes"):
        return "|".join(sorted(_chave_titulo(x) for x in v))
    if campo == "doi":
        return str(v).lower().strip()
    if campo == "ano":
        return str(v)
    return _chave_titulo(str(v))


def _concordam(campo: str, a, b) -> bool:
    if campo in ("resumo", "afiliacoes", "palavras_chave", "idioma", "tipo_documento", "fonte", "editora", "url"):
        return True  # só entram em conflito os campos de identificação (ver CAMPOS_CONFLITO)
    na, nb = _norm_valor(campo, a), _norm_valor(campo, b)
    if na == nb:
        return True
    if campo in ("titulo",):
        ta, tb = set(na.split()), set(nb.split())
        return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.8
    if campo == "autores":
        sa = {w for a in a for w in _chave_titulo(a).split() if len(w) >= 3}
        sb = {w for a in b for w in _chave_titulo(a).split() if len(w) >= 3}
        return bool(sa & sb) and len(sa & sb) / min(len(sa), len(sb)) >= 0.6
    return False


CAMPOS_CONFLITO = ("titulo", "autores", "ano", "doi")


def resolver(entrada: dict | None) -> dict:
    """Valor efetivo de cada campo: ``{campo: {"valor", "origem", "confianca", "detalhe", "alternativas", "conflito"}}``."""
    entrada = entrada or {"candidatos": {}, "manual": {}}
    saida: dict = {}
    for campo in CAMPOS:
        manual = (entrada.get("manual") or {}).get(campo)
        cands = sorted(entrada["candidatos"].get(campo, []), key=lambda c: -c["confianca"])
        if manual not in (None, "", []):
            escolhido = {"valor": manual, "origem": "manual", "confianca": 1.0, "detalhe": "editado pelo usuário"}
            alternativas = cands
        elif cands:
            ordem = {o: i for i, o in enumerate(("online", "indice", "texto"))}
            cands = sorted(cands, key=lambda c: (-(c["confianca"]), ordem.get(c["origem"], 9)))
            escolhido, alternativas = dict(cands[0]), cands[1:]
        else:
            continue
        conflito = campo in CAMPOS_CONFLITO and any(not _concordam(campo, escolhido["valor"], a["valor"]) for a in alternativas)
        saida[campo] = {**escolhido, "alternativas": alternativas, "conflito": bool(conflito)}
    return saida


def valores(entrada: dict | None, confianca_minima: float = 0.0) -> dict:
    """Só os valores efetivos (``{campo: valor}``); descarta os de confiança menor que ``confianca_minima``."""
    return {c: v["valor"] for c, v in resolver(entrada).items() if v["confianca"] >= confianca_minima}


def conflitos(dados: dict) -> list[dict]:
    lista = []
    for arquivo, entrada in dados["documentos"].items():
        for campo, v in resolver(entrada).items():
            if v["conflito"]:
                lista.append({"arquivo": arquivo, "campo": campo, "escolhido": {k: v[k] for k in ("valor", "origem", "confianca")},
                              "alternativas": [{k: a[k] for k in ("valor", "origem", "confianca")} for a in v["alternativas"]]})
    return lista


def editar_manual(dados: dict, arquivo: str, alteracoes: dict) -> dict:
    """PATCH manual: ``{campo: valor}``; valor vazio/None remove a edição manual. Devolve o valor efetivo atualizado."""
    entrada = _entrada(dados, arquivo)
    for campo, valor in alteracoes.items():
        if campo not in CAMPOS:
            raise ValueError(f"Campo desconhecido: {campo}. Use: {', '.join(CAMPOS)}.")
        if campo in CAMPOS_LISTA and isinstance(valor, str):
            valor = [p.strip() for p in re.split(r"\s*;\s*|\n", valor) if p.strip()]
        if campo == "ano" and valor not in (None, ""):
            valor = int(valor)
        if valor in (None, "", []):
            entrada["manual"].pop(campo, None)
        else:
            entrada["manual"][campo] = valor
    return resolver(entrada)
