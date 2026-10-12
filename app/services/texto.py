"""Utilitários de texto compartilhados pelas etapas de conversão e qualidade."""
import json
import re

from app.models import Documento

MARCADOR_PAGINA = re.compile(r"<!--\s*página\s+(\d+)\s*-->", re.IGNORECASE)
COMENTARIO_HTML = re.compile(r"<!--.*?-->", re.DOTALL)
PALAVRA = re.compile(r"[^\W\d_]+", re.UNICODE)


def paginar(md: str) -> list[tuple[int, str]] | None:
    """Divide o MD pelos marcadores ``<!-- página N -->``.

    Devolve [(número, texto)] ou None se o documento não tem marcadores.
    """
    achados = list(MARCADOR_PAGINA.finditer(md))
    if not achados:
        return None
    paginas = []
    for i, m in enumerate(achados):
        fim = achados[i + 1].start() if i + 1 < len(achados) else len(md)
        paginas.append((int(m.group(1)), md[m.end():fim]))
    return paginas


def texto_visivel(trecho: str) -> str:
    """Texto sem comentários HTML (marcadores, cabeçalho de fonte, <!-- image -->)."""
    return COMENTARIO_HTML.sub("", trecho)


def contar_caracteres(trecho: str) -> int:
    return len(texto_visivel(trecho).strip())


def palavras(trecho: str) -> list[str]:
    return PALAVRA.findall(texto_visivel(trecho).lower())


def ler_qualidade(doc: Documento) -> dict:
    if not doc.qualidade_json:
        return {}
    try:
        dados = json.loads(doc.qualidade_json)
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def gravar_qualidade(doc: Documento, dados: dict) -> None:
    doc.qualidade_json = json.dumps(dados, ensure_ascii=False)


GRUPOS_NAO_ACADEMICOS = ("cinz", "gray", "grey", "nao_acad", "nao acad", "não acad", "non-acad", "non acad", "blog", "relat")
PALAVRAS_5_PAGINAS = 2500  # sem marcadores de página, ~5 páginas


def avisos_limpeza(limpeza: dict, paginas: int | None, grupo: str | None) -> list[str]:
    """Avisos da Frente 3, calculados na hora (o grupo pode ser editado depois da limpeza)."""
    if not limpeza:
        return []
    avisos = []
    total = limpeza.get("palavras_total") or 0
    grande = (paginas or 0) >= 5 or (paginas is None and total >= PALAVRAS_5_PAGINAS)
    cinzenta = any(t in (grupo or "").lower() for t in GRUPOS_NAO_ACADEMICOS)
    if not limpeza.get("referencias_detectadas") and grande and limpeza.get("parece_academico") and not cinzenta:
        avisos.append("referências não detectadas")
    if total >= 200 and not limpeza.get("palavras_corpo"):
        avisos.append("nenhum texto no corpo: tudo caiu em seções excluídas (apêndice, referências...): conferir as seções")
    if total and (limpeza.get("palavras_referencias") or 0) / total > 0.5:
        avisos.append(
            f"referências ocupam > 50% do texto ({limpeza['palavras_referencias'] / total:.0%}): conferir a detecção"
        )
    return avisos


def avisos_do_documento(qualidade: dict, grupo: str | None = None) -> list[str]:
    """Avisos próprios da qualidade + duplicado (outra etapa) + avisos da limpeza (Frente 3)."""
    avisos = list(qualidade.get("avisos") or [])
    if qualidade.get("duplicado_de"):
        avisos.append(f"duplicado de {qualidade['duplicado_de']}")
    elif qualidade.get("similar_texto"):
        s = qualidade["similar_texto"]
        sim = f"{s['similaridade']:.2f}".replace(".", ",")
        avisos.append(f"provável duplicata de {s['arquivo']} (similaridade {sim})")
    elif qualidade.get("similar_titulo"):
        avisos.append(f"provável duplicata de {qualidade['similar_titulo']['arquivo']} (mesmo título)")
    avisos.extend(avisos_limpeza(qualidade.get("limpeza") or {}, qualidade.get("paginas"), grupo))
    from app.services.ruido import frase_aviso
    aviso_ruido = frase_aviso(qualidade.get("ruido") or {})
    if aviso_ruido:
        avisos.append(aviso_ruido)
    return avisos
