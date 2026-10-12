"""16.4 (c) - Consulta opcional de metadados por DOI (Crossref e/ou OpenAlex). **Desligada por padrão.**

Privacidade: a consulta envia à API **apenas o DOI** (nunca o texto, o nome do arquivo ou o projeto) e o e-mail de contato
configurado, no cabeçalho ``User-Agent`` e no parâmetro ``mailto`` (convenção de "polite pool" das duas APIs). Só acontece quando o
usuário pede (parâmetro ``online`` da extração ou o botão da tela) **e** existe um e-mail de contato configurado: sem e-mail,
nada é chamado (``SemEmail``). O e-mail fica em ``%APPDATA%/RaioX/config_metadados.json`` (vazio por padrão; ``RAIOX_CONFIG_DIR`` o troca).

Cada chamada usa ``httpx`` com timeout de 15 s; falhas de rede ou DOI inexistente viram um item do relatório, nunca exceção.
Os valores entram como candidatos de origem ``online`` (confiança 0,9) e podem divergir do texto/índice (conflito listado).
"""
import html
import json
import re
from pathlib import Path

import httpx

from app import offline
from app.services.llm import config as cfg_llm

CROSSREF = "https://api.crossref.org/works/"
OPENALEX = "https://api.openalex.org/works/doi:"
TIMEOUT = 15.0
CONFIANCA = 0.9
AVISO_PRIVACIDADE = ("A consulta online envia à API (Crossref e/ou OpenAlex) somente o DOI de cada documento e o seu e-mail de contato; "
                     "nenhum texto do corpus sai do computador. Fica desligada, a menos que você a peça.")
TIPOS_CROSSREF = {"journal-article": "article", "proceedings-article": "conference paper", "posted-content": "preprint",
                  "report": "report", "book": "book", "monograph": "book", "book-chapter": "book chapter", "dissertation": "thesis",
                  "report-component": "report", "peer-review": "document"}
TIPOS_OPENALEX = {"article": "article", "preprint": "preprint", "book": "book", "book-chapter": "book chapter", "report": "report",
                  "dissertation": "thesis", "review": "article"}


class SemEmail(Exception):
    """Sem e-mail de contato configurado: a consulta online não é feita."""


def _arquivo_config() -> Path:
    return cfg_llm.pasta_config() / "config_metadados.json"


def carregar_config() -> dict:
    try:
        d = json.loads(_arquivo_config().read_text(encoding="utf-8"))
        return {"email_contato": str(d.get("email_contato") or "").strip()}
    except (OSError, ValueError):
        return {"email_contato": ""}


def salvar_config(email: str) -> dict:
    email = (email or "").strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("E-mail de contato inválido.")
    pasta = cfg_llm.pasta_config()
    pasta.mkdir(parents=True, exist_ok=True)
    _arquivo_config().write_text(json.dumps({"email_contato": email}, ensure_ascii=False), encoding="utf-8")
    return {"email_contato": email}


def _cliente(email: str) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": f"RaioX/0.3 (mailto:{email})", "Accept": "application/json"})


def _nome(autor_given: str, family: str) -> str:
    return f"{family}, {autor_given}".strip(", ") if family else autor_given


def _tira_tags(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def de_crossref(msg: dict) -> dict:
    campos: dict = {}
    if msg.get("title"):
        campos["titulo"] = _tira_tags(msg["title"][0])
    autores = [_nome(a.get("given", ""), a.get("family", "")) if a.get("family") else a.get("name", "") for a in msg.get("author") or []]
    autores = [a for a in autores if a]
    if autores:
        campos["autores"] = autores
    for chave in ("issued", "published-print", "published-online", "created"):
        partes = ((msg.get(chave) or {}).get("date-parts") or [[None]])[0]
        if partes and partes[0]:
            campos["ano"] = int(partes[0])
            break
    if msg.get("container-title"):
        campos["fonte"] = _tira_tags(msg["container-title"][0])
    for k_in, k_out in (("volume", "volume"), ("issue", "numero"), ("page", "paginas"), ("publisher", "editora"), ("URL", "url"), ("DOI", "doi")):
        if msg.get(k_in):
            campos[k_out] = str(msg[k_in])
    if msg.get("type") in TIPOS_CROSSREF:
        campos["tipo_documento"] = TIPOS_CROSSREF[msg["type"]]
    if msg.get("abstract"):
        campos["resumo"] = _tira_tags(msg["abstract"])
    if msg.get("subject"):
        campos["palavras_chave"] = [str(s) for s in msg["subject"]][:15]
    afs = []
    for a in msg.get("author") or []:
        for af in a.get("affiliation") or []:
            if af.get("name") and af["name"] not in afs:
                afs.append(af["name"])
    if afs:
        campos["afiliacoes"] = afs
    return campos


def _resumo_openalex(inv: dict | None) -> str | None:
    if not inv:
        return None
    pos = {}
    for palavra, lugares in inv.items():
        for p in lugares:
            pos[p] = palavra
    return " ".join(pos[k] for k in sorted(pos)) if pos else None


def de_openalex(obra: dict) -> dict:
    campos: dict = {}
    if obra.get("title"):
        campos["titulo"] = _tira_tags(obra["title"])
    autores, afs = [], []
    for a in obra.get("authorships") or []:
        nome = ((a.get("author") or {}).get("display_name") or "").strip()
        if nome:
            palavras = nome.split()
            autores.append(f"{palavras[-1]}, {' '.join(palavras[:-1])}".strip(", ") if len(palavras) > 1 else nome)
        for inst in a.get("institutions") or []:
            if inst.get("display_name") and inst["display_name"] not in afs:
                afs.append(inst["display_name"])
    if autores:
        campos["autores"] = autores
    if afs:
        campos["afiliacoes"] = afs
    if obra.get("publication_year"):
        campos["ano"] = int(obra["publication_year"])
    fonte = (((obra.get("primary_location") or {}).get("source")) or {})
    if fonte.get("display_name"):
        campos["fonte"] = fonte["display_name"]
    if fonte.get("host_organization_name"):
        campos["editora"] = fonte["host_organization_name"]
    bib = obra.get("biblio") or {}
    if bib.get("volume"):
        campos["volume"] = str(bib["volume"])
    if bib.get("issue"):
        campos["numero"] = str(bib["issue"])
    if bib.get("first_page"):
        campos["paginas"] = f"{bib['first_page']}-{bib['last_page']}" if bib.get("last_page") and bib["last_page"] != bib["first_page"] else str(bib["first_page"])
    if obra.get("type") in TIPOS_OPENALEX:
        campos["tipo_documento"] = TIPOS_OPENALEX[obra["type"]]
    resumo = _resumo_openalex(obra.get("abstract_inverted_index"))
    if resumo:
        campos["resumo"] = resumo
    kws = [k.get("display_name") or k.get("keyword") for k in obra.get("keywords") or [] if isinstance(k, dict)]
    kws = [k for k in kws if k]
    if kws:
        campos["palavras_chave"] = kws[:15]
    if obra.get("language"):
        campos["idioma"] = obra["language"]
    return campos


def consultar(doi: str, fonte: str = "crossref", email: str | None = None, cliente: httpx.Client | None = None) -> dict:
    """Metadados do DOI: ``{"campos": {...}, "fonte": "crossref"|"openalex", "erro": None|str}``. Sem e-mail: levanta ``SemEmail``."""
    offline.exigir_internet()  # 11.2
    email = (email if email is not None else carregar_config()["email_contato"]).strip()
    if not email:
        raise SemEmail("Configure um e-mail de contato (Crossref/OpenAlex pedem identificação) antes de usar a consulta online.")
    doi = doi.strip()
    proprio = cliente is None
    cli = cliente or _cliente(email)
    try:
        url = (CROSSREF if fonte == "crossref" else OPENALEX) + doi
        r = cli.get(url, params={"mailto": email})
        if r.status_code == 404:
            return {"campos": {}, "fonte": fonte, "erro": "DOI não encontrado"}
        r.raise_for_status()
        corpo = r.json()
        campos = de_crossref(corpo.get("message") or {}) if fonte == "crossref" else de_openalex(corpo)
        return {"campos": campos, "fonte": fonte, "erro": None}
    except (httpx.HTTPError, ValueError) as exc:
        return {"campos": {}, "fonte": fonte, "erro": f"{type(exc).__name__}: falha na consulta"}
    finally:
        if proprio:
            cli.close()
