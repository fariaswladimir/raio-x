"""9.4 - Texto de Métodos pronto para o artigo, determinístico (sem LLM).

Monta, a partir do catálogo único (``catalogo.yaml``) e dos parâmetros e resultados do **projeto**, os parágrafos de uma
seção "Métodos": corpus (documentos, palavras, período, grupos, exclusões e motivos), pré-processamento (conversão,
limpeza, exclusão de referências, lematização, palavras vazias, termos compostos, segmentação, filtro de ruído), cada
análise realmente usada (com os parâmetros do projeto e as ferramentas equivalentes), a declaração de uso de LLM (só se
um comentário redigido por LLM foi aceito) e a lista de referências (ABNT ou APA). As citações "(Autor, ano)" vêm das
referências do catálogo. O mesmo projeto e o mesmo catálogo geram sempre o mesmo texto.

Idiomas: ``pt`` (completo) e ``en`` (parágrafos de corpus, pré-processamento e LLM traduzidos; as análises levam o nome em
inglês, os parâmetros e as citações, sem a explicação detalhada do catálogo, que está em português).
"""
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Analise, Comentario, Documento
from app.services import metodologia as svc
from app.services import parametros as svc_parametros
from app.services.analises import dados, resumo
from app.services.metodologia import formatos
from app.services.texto import ler_qualidade

ORDEM_ANALISES = (
    "frequencias", "diversidade_lexical", "kwic", "colocacoes", "ngramas", "keyness", "especificidades",
    "dicionario_codebook", "similaridade_documentos", "afc", "chd_reinert", "similitude", "rede_coocorrencia",
    "rede_comunidades_centralidade", "comentarios_regras",
)
PRE_PROCESSAMENTO = ("conversao_docling", "limpeza_estrutura", "qualidade_duplicatas", "lematizacao", "palavras_vazias",
                     "termos_compostos", "segmentacao", "segmentos_ruido")
NOMES_EN = {
    "frequencias": "word frequencies", "diversidade_lexical": "lexical diversity (MATTR)", "kwic": "concordance (KWIC)",
    "colocacoes": "collocations", "ngramas": "n-grams (lexical bundles)", "keyness": "keyness between groups",
    "especificidades": "specificity analysis", "dicionario_codebook": "dictionary/codebook category counts",
    "similaridade_documentos": "document similarity (TF-IDF, cosine)", "afc": "correspondence analysis",
    "chd_reinert": "Reinert's descending hierarchical classification", "similitude": "similarity analysis",
    "rede_coocorrencia": "co-occurrence network", "rede_comunidades_centralidade": "community detection and centrality",
    "comentarios_regras": "rule-based commentary",
}


def _fmt(n, casas: int = 0, idioma: str = "pt") -> str:
    if n is None:
        return "—"
    s = f"{n:,.{casas}f}"
    return s if idioma == "en" else s.replace(",", "X").replace(".", ",").replace("X", ".")


def citacao(ref: dict) -> str:
    """"Sobrenome, ano" / "A & B, ano" / "A et al., ano" (sem parênteses)."""
    sobrenomes = [formatos._partes_nome(a)[0] for a in ref["autores"]]
    nomes = sobrenomes[0] if len(sobrenomes) == 1 else (f"{sobrenomes[0]} & {sobrenomes[1]}" if len(sobrenomes) == 2
                                                         else f"{sobrenomes[0]} et al.")
    return f"{nomes}, {ref['ano']}"


def citacoes(refs: list[dict]) -> str:
    return "(" + "; ".join(citacao(r) for r in sorted(refs, key=lambda r: (r["ano"], r["chave"]))) + ")" if refs else ""


# ---------- coleta do projeto ----------

def analises_usadas(db: Session, pasta: Path, params: dict) -> list[dict]:
    tipos = set(db.execute(select(Analise.tipo).distinct()).scalars())
    contagens = {"comentario": db.execute(text("SELECT COUNT(*) FROM comentario")).scalar() or 0}
    cat = svc.marcar_uso_no_projeto(svc.listar(), pasta, params, tipos, contagens)
    return [a for a in cat if a["usada_no_projeto"]]


def _corpus_dados(db: Session, pasta: Path, params: dict) -> dict:
    metas = dados.documentos_do_corpus(db, pasta)
    anos = [m["ano"] for m in metas if m.get("ano")]
    try:
        res = resumo.resumo_do_projeto(pasta, metas, params)
    except Exception:  # noqa: BLE001  (sem pipeline: texto com o que houver)
        res = None
    c = (res or {}).get("corpus") or {}
    excluidos = []
    exts = Counter()
    for d in db.scalars(select(Documento).where(Documento.status != "removido")):
        exts[d.arquivo.rsplit(".", 1)[-1].lower()] += 1
        if d.excluido or d.status == "com_problema":
            q = ler_qualidade(d)
            motivo = " | ".join(q.get("problemas") or []) or ("excluído pelo usuário" if d.excluido else "problema de conversão")
            excluidos.append((d.arquivo, motivo))
    ruido = Counter()
    pasta_ruido = pasta / "cache" / "ruido"
    if pasta_ruido.is_dir():
        for f in pasta_ruido.glob("*.json"):
            r = json.loads(f.read_text(encoding="utf-8"))
            ruido["segmentos"] += r["resumo"]["segmentos"]
            ruido["palavras"] += r["resumo"]["tokens"]
            ruido["total"] += r["n_segmentos"]
    return {"n_docs": c.get("n_documentos", len(metas)), "tokens": c.get("tokens"), "tokens_total": c.get("tokens_total"),
            "periodo": (min(anos), max(anos)) if anos else None,
            "grupos": [(g["grupo"], g["documentos"]) for g in c.get("documentos_por_grupo", [])],
            "excluidos": excluidos, "extensoes": exts, "ruido": ruido}


def _llm_usado(db: Session) -> list[str]:
    from app.services.exportar.laudo_html import modelos_llm
    aceitos = list(db.scalars(select(Comentario).where(Comentario.status.in_(("aceito", "editado")), Comentario.origem == "llm")))
    return modelos_llm(aceitos)


# ---------- parágrafos ----------

def _p_corpus(d: dict, pt: bool) -> str:
    n, tok = _fmt(d["n_docs"], 0, "pt" if pt else "en"), _fmt(d["tokens"], 0, "pt" if pt else "en")
    per = f"{d['periodo'][0]}–{d['periodo'][1]}" if d["periodo"] else None
    grupos = ", ".join(f"{g} (n = {q})" for g, q in d["grupos"])
    if pt:
        t = f"O corpus é composto por {n} documentos, com {tok} palavras no corpo do texto (referências e seções excluídas não contadas)"
        t += f", publicados entre {per}" if per else ", sem ano de publicação informado"
        t += f". Os documentos foram organizados nos grupos {grupos}." if grupos else "."
        if d["excluidos"]:
            motivos = Counter(m for _, m in d["excluidos"])
            t += (f" {len(d['excluidos'])} documento(s) ficaram fora das análises ("
                  + "; ".join(f"{q} por: {m}" for m, q in motivos.most_common(4)) + ").")
        return t
    t = f"The corpus comprises {n} documents totalling {tok} words of body text (references and excluded sections not counted)"
    t += f", published between {per}" if per else ", with no publication year recorded"
    t += f". Documents were organised into the groups {grupos}." if grupos else "."
    if d["excluidos"]:
        motivos = Counter(m for _, m in d["excluidos"])
        t += f" {len(d['excluidos'])} document(s) were left out of the analyses (" + "; ".join(f"{q}: {m}" for m, q in motivos.most_common(4)) + ")."
    return t


def _p_preproc(d: dict, params: dict, ids_usados: set[str], pt: bool) -> str:
    lem = params.get("lematizacao") or {}
    vaz = params.get("palavras_vazias") or {}
    langs = [k.upper() for k in ("en", "pt", "es") if vaz.get(k)]
    tc = params.get("termos_compostos") or {}
    limp = params.get("limpeza") or {}
    pdfs = d["extensoes"].get("pdf", 0)
    r = d["ruido"]
    secoes = ", ".join(params.get("excluir_secoes") or [])
    if pt:
        partes = []
        conv = (f"Os {pdfs} PDF foram convertidos para Markdown com o Docling, preservando o marcador de página para citação exata. "
                if pdfs else "")
        partes.append("O texto foi limpo (remoção de cabeçalhos e rodapés repetidos, números de página, URLs e e-mails, e junção de palavras hifenizadas no fim da linha)")
        if params.get("excluir_referencias"):
            partes.append(f"as seções excluídas da contagem foram: {secoes}")
        partes.append("a lematização usou " + (f"o {lem.get('metodo', 'simplemma')}" if lem.get("ativa") else "nenhum lematizador (formas)")
                      + f" e as palavras vazias foram as listas {', '.join(langs)}" + (" e a lista acadêmica" if vaz.get("academico") else ""))
        if tc.get("ativa"):
            partes.append(f"termos compostos foram detectados por log-likelihood (até {tc.get('n_max')} palavras, frequência mínima {tc.get('min_freq')} em ao menos {tc.get('min_docs')} documentos)")
        partes.append(f"o texto foi segmentado em unidades de cerca de {params.get('segmento_palavras')} palavras, sem atravessar página ou seção")
        if limp.get("excluir_ruido", True) and r["total"]:
            partes.append(f"segmentos de ruído (listas de autores, tabelas e texto repetido) foram identificados por regras e excluídos da classificação, da similitude e dos n-gramas ({r['segmentos']} de {r['total']} segmentos)")
        return conv + "; ".join(partes) + "."
    partes = []
    if pdfs:
        partes.append(f"The {pdfs} PDF files were converted to Markdown with Docling, keeping page markers for exact citation")
    partes.append("text was cleaned (repeated headers and footers, page numbers, URLs and e-mails removed; end-of-line hyphenation joined)")
    if params.get("excluir_referencias"):
        partes.append(f"sections excluded from counts: {secoes}")
    partes.append("lemmatisation used " + (lem.get("metodo", "simplemma") if lem.get("ativa") else "no lemmatiser (surface forms)")
                  + f" and stopword lists were {', '.join(langs)}" + (" plus an academic list" if vaz.get("academico") else ""))
    if tc.get("ativa"):
        partes.append(f"compound terms were detected by log-likelihood (up to {tc.get('n_max')} words, minimum frequency {tc.get('min_freq')} in at least {tc.get('min_docs')} documents)")
    partes.append(f"text was segmented into units of about {params.get('segmento_palavras')} words, never crossing a page or section boundary")
    if limp.get("excluir_ruido", True) and r["total"]:
        partes.append(f"noise segments (author lists, tables and repeated text) were rule-flagged and excluded from classification, similarity analysis and n-grams ({r['segmentos']} of {r['total']} segments)")
    return "Pre-processing: " + "; ".join(partes) + "."


def _p_analise(a: dict, pt: bool) -> str:
    cit = citacoes(a["referencias"])
    params = "; ".join(f"{p['nome']}: {p.get('valor_projeto') if p.get('valor_projeto') not in (None, '') and not isinstance(p.get('valor_projeto'), (dict, list)) else p['valor']}"
                       for p in a["parametros_padrao"][:6])
    if pt:
        t = f"{a['o_que_mede']} {a['metrica']}"
        t = t.rstrip(".") + "."
        if cit:
            t += f" {cit}."
        t += f" Parâmetros: {params}. Equivale a: {a['equivale_a'].rstrip('.')}."
        return t
    nome = NOMES_EN.get(a["id"], a["nome"])
    return f"The {nome} was computed" + (f" {cit}" if cit else "") + f" with the project parameters ({params})."


def _p_llm(modelos: list[str], pt: bool) -> str:
    if pt:
        return ("Parte dos comentários do relatório foi redigida com auxílio de modelo de linguagem (" + "; ".join(modelos) + "). "
                "O modelo recebeu apenas as métricas calculadas, um parágrafo-modelo e até cinco trechos do corpus, com instrução de não acrescentar números, "
                "fontes nem afirmações causais; cada texto passou por conferência automática de números, citações e trechos e foi revisado por um humano antes de ser incluído.")
    return ("Part of the report commentary was drafted with a language model (" + "; ".join(modelos) + "). The model received only the computed metrics, a template "
            "paragraph and up to five corpus excerpts, and was instructed not to add numbers, sources or causal claims; every text was automatically checked "
            "(numbers, citations, excerpts) and reviewed by a human before inclusion.")


def montar(db: Session, pasta: Path, idioma: str = "pt", estilo: str = "abnt") -> dict:
    """``{"paragrafos": [{"titulo", "texto"}], "referencias": [str], "texto", "markdown", ...}`` do projeto."""
    if idioma not in ("pt", "en") or estilo not in ("abnt", "apa"):
        raise ValueError("idioma deve ser pt ou en; estilo, abnt ou apa.")
    pt = idioma == "pt"
    params = svc_parametros.carregar(pasta)
    usadas = analises_usadas(db, pasta, params)
    por_id = {a["id"]: a for a in usadas}
    d = _corpus_dados(db, pasta, params)
    paragrafos = [
        {"titulo": "Corpus" if pt else "Corpus", "texto": _p_corpus(d, pt)},
        {"titulo": "Pré-processamento" if pt else "Pre-processing", "texto": _p_preproc(d, params, set(por_id), pt)},
    ]
    refs_ids = [i for i in PRE_PROCESSAMENTO if i in por_id]
    pre_refs = [r for i in refs_ids for r in por_id[i]["referencias"]]
    if pre_refs:
        unicas = {r["chave"]: r for r in pre_refs}
        paragrafos[1]["texto"] += (" Referências do pré-processamento: " if pt else " Pre-processing references: ") + citacoes(list(unicas.values())) + "."
    ids_analises = [i for i in ORDEM_ANALISES if i in por_id]
    for i in ids_analises:
        paragrafos.append({"titulo": por_id[i]["nome"] if pt else NOMES_EN.get(i, por_id[i]["nome"]).capitalize(),
                           "texto": _p_analise(por_id[i], pt)})
    modelos = _llm_usado(db)
    if modelos:
        paragrafos.append({"titulo": "Uso de modelo de linguagem" if pt else "Use of a language model", "texto": _p_llm(modelos, pt)})
        ids_analises.append("redacao_paragrafos_llm") if "redacao_paragrafos_llm" in {a["id"] for a in svc.listar()} else None
    ids_refs = [*refs_ids, *ids_analises]
    refs = svc.referencias_de(ids_refs) if ids_refs else []
    lista = [formatos.formatar(r, estilo) for r in refs]
    titulo = "Métodos" if pt else "Methods"
    md = [f"## {titulo}", ""]
    for p in paragrafos:
        md += [f"**{p['titulo']}.** {p['texto']}", ""]
    md += ["### Referências" if pt else "### References", ""] + [f"- {x}" for x in lista]
    corpo = "\n\n".join(f"{p['titulo']}. {p['texto']}" for p in paragrafos)
    return {"idioma": idioma, "estilo": estilo, "titulo": titulo, "paragrafos": paragrafos, "referencias": lista,
            "analises": ids_analises, "llm": modelos, "texto": corpo + "\n\n" + ("Referências\n" if pt else "References\n") + "\n".join(lista),
            "markdown": "\n".join(md) + "\n"}


def para_docx(m: dict, destino: Path) -> int:
    from docx import Document
    doc = Document()
    doc.add_heading(m["titulo"], level=1)
    for p in m["paragrafos"]:
        par = doc.add_paragraph()
        par.add_run(p["titulo"] + ". ").bold = True
        par.add_run(p["texto"])
    doc.add_heading("Referências" if m["idioma"] == "pt" else "References", level=2)
    for r in m["referencias"]:
        doc.add_paragraph(r)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(destino))
    return destino.stat().st_size
