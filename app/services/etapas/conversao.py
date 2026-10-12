"""Etapa 20 - Conversão para Markdown com marcador de página (entregável 2.4).

Saída: projetos/<slug>/cache/md/<documento_id>.md (nunca na pasta de origem).

- .md / .markdown / .txt: lidos como UTF-8 (alternativa cp1252, depois errors=replace),
  quebras de linha normalizadas, copiados como estão (marcadores ``<!-- página N -->``
  de uma conversão anterior são mantidos).
- .pdf / .docx: Docling, importado sob demanda (instalação opcional: instalar_docling.bat).
  Sem OCR por padrão (parâmetro ``conversao.ocr``), TableFormer no modo FAST, um
  ``<!-- página N -->`` antes de cada página. Lógica baseada no script do skill docling-corpus.

OCR (entregável 2.6)
--------------------
Motor: RapidOCR com onnxruntime (modelos PP-OCR dentro do pacote, funciona offline em CPU/Windows; instalado por
``instalar_docling.bat`` / ``requirements-docling.txt``). Idioma: o primeiro de ``idioma`` dos parâmetros (RapidOCR roda um
idioma por vez; en/pt/es usam o mesmo reconhecedor latino).
O OCR efetivo de cada documento é ``documento.ocr`` (override: True/False) ou, se for None, ``conversao.ocr`` do projeto.
Modo de página: com OCR **ligado só pelo projeto**, o Docling usa o modo padrão (OCR apenas nas regiões da página sem camada
de texto; páginas com texto não são reconhecidas de novo). Com o override **forçado no documento (True)** o OCR é de
**página inteira** em todas as páginas: é o caso de PDFs cuja camada de texto existe mas é inútil (fontes sem mapeamento,
texto vetorizado) e por isso o Docling não extrai nada. O override entra na chave de cache só desse documento
(``Etapa.entrada_doc``); o MD só é refeito se o OCR efetivo ou o modo mudou (``_md_ja_convertido``).

A etapa grava em ``documento.qualidade_json``: paginas, chars_por_pagina, caracteres,
estrutura (títulos com página, nº de tabelas e figuras) e conversao (origem da conversão).
"""
import datetime
import re
import time
from pathlib import Path
from threading import Lock

from app.models import Documento
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.texto import MARCADOR_PAGINA, contar_caracteres, gravar_qualidade, ler_qualidade, paginar

EXTENSOES_TEXTO = {".md", ".markdown", ".txt"}
EXTENSOES_DOCLING = {".pdf", ".docx"}
MSG_SEM_DOCLING = "Docling não instalado — rode instalar_docling.bat"
VERSAO_ETAPA = "2"


MSG_SEM_OCR = "OCR não instalado (RapidOCR/onnxruntime) — rode instalar_docling.bat"


class DoclingIndisponivel(RuntimeError):
    """Docling não está instalado neste ambiente."""


class OcrIndisponivel(RuntimeError):
    """O motor de OCR (RapidOCR + onnxruntime) não está instalado."""


# ---------- Docling (importação sob demanda, conversor único por processo) ----------

_conversores: dict[tuple, object] = {}
_trava_conversor = Lock()


def _importar_docling():
    """Importa o Docling. Isolado em função para os testes simularem a ausência dele."""
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import OcrMode, PdfPipelineOptions, RapidOcrOptions, TableFormerMode
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import PictureItem, SectionHeaderItem, TableItem
    except ImportError as exc:
        raise DoclingIndisponivel(MSG_SEM_DOCLING) from exc
    return {
        "InputFormat": InputFormat,
        "PdfPipelineOptions": PdfPipelineOptions,
        "OcrMode": OcrMode,
        "RapidOcrOptions": RapidOcrOptions,
        "TableFormerMode": TableFormerMode,
        "DocumentConverter": DocumentConverter,
        "PdfFormatOption": PdfFormatOption,
        "SectionHeaderItem": SectionHeaderItem,
        "TableItem": TableItem,
        "PictureItem": PictureItem,
    }


def _obter_conversor(ocr: bool, pagina_inteira: bool = False, idioma: str = "en"):
    """Conversor Docling em cache (carregar os modelos é caro): um por combinação de OCR, modo e idioma."""
    chave = (bool(ocr), bool(ocr and pagina_inteira), idioma if ocr else None)
    with _trava_conversor:
        if chave not in _conversores:
            d = _importar_docling()
            try:  # mesmo limite de threads do script de referência
                import torch

                torch.set_num_threads(4)
            except Exception:
                pass
            opcoes = d["PdfPipelineOptions"]()
            opcoes.do_ocr = bool(ocr)
            if ocr:
                opcoes.ocr_options = d["RapidOcrOptions"](
                    lang=[f"iso:{idioma}"],
                    mode=d["OcrMode"].FULL_PAGE if pagina_inteira else d["OcrMode"].DEFAULT,
                )
            opcoes.do_table_structure = True
            opcoes.table_structure_options.mode = d["TableFormerMode"].FAST
            _conversores[chave] = d["DocumentConverter"](
                format_options={d["InputFormat"].PDF: d["PdfFormatOption"](pipeline_options=opcoes)}
            )
        return _conversores[chave]


def _versao_docling() -> str:
    try:
        from importlib.metadata import version

        return version("docling")
    except Exception:
        return "?"


def _converter_com_docling(origem: Path, ocr: bool, pagina_inteira: bool = False, idioma: str = "en") -> tuple[str, dict]:
    d = _importar_docling()
    resultado = _obter_conversor(ocr, pagina_inteira, idioma).convert(str(origem))
    doc = resultado.document
    n = len(doc.pages)
    paginacao = n > 0  # DOCX não tem páginas no Docling: vira uma página só
    total = n if paginacao else 1
    if paginacao:
        corpo = "".join(
            f"\n\n<!-- página {pg} -->\n\n{doc.export_to_markdown(page_no=pg)}" for pg in range(1, total + 1)
        )
    else:
        corpo = f"\n\n<!-- página 1 -->\n\n{doc.export_to_markdown()}"
    cabecalho = (
        f"<!-- Fonte: {origem.name} | Conversão: Docling {_versao_docling()} "
        f"(OCR: {('sim, ' + ('página inteira' if pagina_inteira else 'regiões sem texto') + ', ' + idioma) if ocr else 'não'}, "
        f"tabelas: FAST) | páginas: {total} -->\n"
    )
    titulos, tabelas, figuras = [], 0, 0
    for item, _ in doc.iterate_items():
        if isinstance(item, d["SectionHeaderItem"]):
            titulos.append({"titulo": item.text[:150], "pagina": item.prov[0].page_no if item.prov else None})
        elif isinstance(item, d["TableItem"]):
            tabelas += 1
        elif isinstance(item, d["PictureItem"]):
            figuras += 1
    estrutura = {"titulos": titulos, "tabelas": tabelas, "figuras": figuras, "paginacao": paginacao}
    return cabecalho + corpo, estrutura


# ---------- texto simples / Markdown ----------

def ler_texto(caminho: Path) -> str:
    bruto = caminho.read_bytes()
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            texto = bruto.decode("cp1252")
        except UnicodeDecodeError:
            texto = bruto.decode("utf-8", errors="replace")
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def estrutura_do_markdown(md: str) -> dict:
    """Títulos (com página), tabelas e figuras de um MD já pronto."""
    titulos, pagina = [], None
    tabelas = figuras = 0
    em_tabela = False
    for linha in md.split("\n"):
        m = MARCADOR_PAGINA.search(linha)
        if m:
            pagina = int(m.group(1))
        titulo = re.match(r"#{1,6}\s+(.+)", linha)
        if titulo:
            titulos.append({"titulo": titulo.group(1).strip()[:150], "pagina": pagina})
        if linha.lstrip().startswith("|"):
            if not em_tabela:
                tabelas += 1
            em_tabela = True
        else:
            em_tabela = False
        figuras += linha.count("<!-- image -->") + len(re.findall(r"!\[[^\]]*\]\(", linha))
    return {"titulos": titulos, "tabelas": tabelas, "figuras": figuras, "paginacao": bool(MARCADOR_PAGINA.search(md))}


# ---------- etapa ----------

def _marcar_problema(doc: Documento, problema: str, retentar: bool = False) -> None:
    q = ler_qualidade(doc)
    q["problemas"] = [problema]
    q["retentar"] = retentar
    gravar_qualidade(doc, q)
    doc.status = "com_problema"


def ocr_efetivo(doc: Documento, parametros: dict) -> tuple[bool, bool, str]:
    """(ocr, página inteira, idioma) deste documento: o override ``documento.ocr`` vence ``conversao.ocr`` do projeto."""
    do_projeto = bool(parametros.get("conversao", {}).get("ocr", False))
    ocr = do_projeto if doc.ocr is None else bool(doc.ocr)
    idiomas = parametros.get("idioma") or []
    idioma = idiomas[0] if idiomas and isinstance(idiomas[0], str) else "en"
    return ocr, bool(ocr and doc.ocr is True), idioma


def _entrada_doc(doc: Documento) -> str:
    """Parte da chave de cache própria do documento: o override de OCR (None / True / False)."""
    return f"ocr={doc.ocr}"


def _md_ja_convertido(ctx: ContextoExecucao, doc: Documento, ocr: bool, pagina_inteira: bool = False) -> bool:
    """Mudou só um parâmetro que não afeta a conversão? Reaproveita o MD (Docling é lento)."""
    info = ler_qualidade(doc).get("conversao") or {}
    return bool(
        doc.caminho_md
        and (ctx.pasta_projeto / doc.caminho_md).is_file()
        and info.get("hash_origem") == doc.hash_sha256
        and info.get("ocr") == ocr
        and bool(info.get("ocr_pagina_inteira")) == bool(pagina_inteira)
        and info.get("versao_etapa") == VERSAO_ETAPA
    )


def converter(ctx: ContextoExecucao, doc: Documento):
    origem = ctx.pasta_origem / doc.arquivo
    ext = origem.suffix.lower()
    ocr, pagina_inteira, idioma_ocr = ocr_efetivo(doc, ctx.parametros)
    destino_rel = f"cache/md/{doc.id}.md"
    destino = ctx.pasta_projeto / destino_rel

    if ext in EXTENSOES_DOCLING and _md_ja_convertido(ctx, doc, ocr, pagina_inteira):
        return {"reaproveitado": True, "md": destino_rel}

    inicio = time.time()
    if ext in EXTENSOES_TEXTO:
        md = ler_texto(origem)
        estrutura = estrutura_do_markdown(md)
        metodo = "copia"
    elif ext in EXTENSOES_DOCLING:
        try:
            md, estrutura = _converter_com_docling(origem, ocr, pagina_inteira, idioma_ocr)
        except DoclingIndisponivel:
            _marcar_problema(doc, MSG_SEM_DOCLING, retentar=True)
            ctx.db.commit()
            raise  # vira "erro" na execução (que não é cacheada): refeita depois de instalar o Docling
        except Exception as exc:
            if ocr and any(n in str(exc).lower() for n in ("rapidocr", "onnxruntime")):
                _marcar_problema(doc, MSG_SEM_OCR, retentar=True)
                ctx.db.commit()
                raise OcrIndisponivel(MSG_SEM_OCR) from exc  # "erro" não é cacheado: refeito depois de instalar
            _marcar_problema(doc, f"Falha na conversão:{type(exc).__name__}: {exc}")
            return {"problema": str(exc)}
        metodo = "docling"
    else:
        _marcar_problema(doc, f"Extensão sem conversor: {ext}")
        return {"problema": "extensão sem conversor"}

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(md, encoding="utf-8", newline="\n")

    paginas = paginar(md)
    q = ler_qualidade(doc)
    for chave in ("problemas", "avisos", "retentar", "idioma", "duplicado_de", "similar_titulo", "similar_texto", "limpeza"):
        q.pop(chave, None)  # resultados de uma conversão anterior ficam obsoletos
    q["paginas"] = len(paginas) if paginas is not None else None
    q["chars_por_pagina"] = [contar_caracteres(t) for _, t in paginas] if paginas is not None else None
    q["caracteres"] = contar_caracteres(md)
    q["estrutura"] = estrutura
    q["conversao"] = {
        "metodo": metodo,
        "hash_origem": doc.hash_sha256,
        "ocr": ocr,
        "ocr_pagina_inteira": pagina_inteira,
        "ocr_idioma": idioma_ocr if ocr else None,
        "versao_etapa": VERSAO_ETAPA,
        "segundos": round(time.time() - inicio, 1),
    }
    gravar_qualidade(doc, q)
    doc.caminho_md = destino_rel
    doc.convertido_em = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    ctx.db.commit()
    return {"md": destino_rel, "paginas": q["paginas"], "metodo": metodo}


registrar_etapa(Etapa(nome="conversao", ordem=20, escopo="documento", funcao=converter, versao=VERSAO_ETAPA,
                       parametros_relevantes=["conversao"], entrada_doc=_entrada_doc))
