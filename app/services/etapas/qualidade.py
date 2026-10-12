"""Etapas 25 e 26 - Controle de qualidade do texto convertido (entregável 2.5).

``qualidade`` (por documento, lê o MD de cache/md):
- vazio: menos de 200 palavras no documento todo -> com_problema, "documento sem texto".
- escaneado: >= 50% das páginas com < 30 caracteres (só se houver marcadores de página)
  -> com_problema, "provável PDF escaneado — reconverter com OCR".
- paginas_quase_vazias: números das páginas com < 30 caracteres (apenas aviso).
- idioma: detector simples por proporção de palavras vazias (en/pt/es), em qualidade_json.idioma;
  aviso se não estiver na lista ``idioma`` dos parâmetros.

``qualidade_duplicados`` (corpus): mesmo sha256 de outro documento ativo -> aviso
"duplicado de <arquivo>" no documento que vem depois (ordem alfabética do caminho).
Fica em etapa própria porque depende dos outros documentos, não só do arquivo;
não usa cache (é barata e precisa enxergar renomeações).
Também marca, em ``qualidade_json.similar_titulo``, o **título normalizado idêntico** (primeiro título do MD, minúsculas,
sem acentos nem pontuação, ao menos 4 palavras para não casar "Introduction"/"Abstract"): aviso "provável duplicata
de <arquivo> (mesmo título)" no documento que vem depois. A duplicata por **texto** (cosseno TF-IDF >= 0,95 sobre os
lemas) precisa do vocabulário e fica na etapa ``duplicatas_proximas`` (47, ``etapas/duplicatas.py``), em
``qualidade_json.similar_texto``. Nenhuma das duas exclui o documento: o usuário decide (``excluido`` ou
``com_problema`` pelo PATCH). Documentos ``excluido`` não participam das comparações.

Documentos com_problema saem das etapas seguintes (STATUS_IGNORADOS no orquestrador).
"""
import re
import unicodedata

from sqlalchemy import select

from app.models import Documento
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.texto import contar_caracteres, gravar_qualidade, ler_qualidade, paginar, palavras, texto_visivel

MIN_PALAVRAS = 200
MIN_CARACTERES_PAGINA = 30
FRACAO_ESCANEADO = 0.5
LIMIAR_IDIOMA = 0.10  # abaixo disso (proporção de palavras vazias) o idioma fica indeterminado
VERSAO_ETAPA = "1"

PALAVRAS_VAZIAS = {
    "en": (
        "the of and to in is that for it as was with be by on not he this are or his from at which but have an had "
        "they you were their one all we can her has there been if more when will would who so than these our also "
        "such may other its them into only over then what about between those both"
    ),
    "pt": (
        "de que do da em um para é com não uma os no se na por mais as dos como mas foi ao ele das tem seu sua ou ser "
        "quando muito há nos já está também só pelo pela até isso ela entre era depois sem mesmo aos ter seus quem "
        "nas esse eles estão você tinha foram essa num nem suas meu às minha têm numa pelos elas havia seja qual "
        "será nós lhe deles sobre cada onde"
    ),
    "es": (
        "de la que el en y los del se las por un para con una su al lo como más pero sus le ya este sí porque esta "
        "entre cuando muy sin sobre también hasta hay donde quien desde todo nos durante todos uno les ni contra "
        "otros ese eso ante ellos esto antes algunos qué unos yo otro otras otra él tanto esa estos mucho quienes "
        "nada muchos cual poco ella estar estas son fue ha ser es está"
    ),
}
_VAZIAS = {lang: frozenset(t.split()) for lang, t in PALAVRAS_VAZIAS.items()}


def detectar_idioma(tokens: list[str]) -> str | None:
    """'en', 'pt' ou 'es' pela maior proporção de palavras vazias; None se indeterminado."""
    if not tokens:
        return None
    pontos = {lang: sum(1 for t in tokens if t in vazias) / len(tokens) for lang, vazias in _VAZIAS.items()}
    melhor = max(pontos, key=pontos.get)
    return melhor if pontos[melhor] >= LIMIAR_IDIOMA else None


def avaliar_texto(md: str, idiomas_esperados: list[str]) -> dict:
    """Aplica as regras de qualidade a um MD. Devolve problemas, avisos, idioma e páginas quase vazias."""
    problemas, avisos = [], []
    tokens = palavras(md)
    paginas = paginar(md)

    quase_vazias = []
    if paginas is not None:
        quase_vazias = [n for n, t in paginas if contar_caracteres(t) < MIN_CARACTERES_PAGINA]

    if len(tokens) < MIN_PALAVRAS:
        problemas.append("documento sem texto")
    elif paginas and len(quase_vazias) / len(paginas) >= FRACAO_ESCANEADO:
        problemas.append("provável PDF escaneado — reconverter com OCR")
    if quase_vazias and not problemas:
        avisos.append(f"páginas quase vazias: {', '.join(map(str, quase_vazias))}")

    idioma = detectar_idioma(tokens) if len(tokens) >= MIN_PALAVRAS else None
    if idioma and idiomas_esperados and idioma not in idiomas_esperados:
        avisos.append(f"idioma '{idioma}' fora dos esperados ({', '.join(idiomas_esperados)})")
    return {
        "problemas": problemas,
        "avisos": avisos,
        "idioma": idioma,
        "paginas_quase_vazias": quase_vazias,
        "palavras": len(tokens),
    }


def avaliar(ctx: ContextoExecucao, doc: Documento):
    if not doc.caminho_md or not (ctx.pasta_projeto / doc.caminho_md).is_file():
        raise FileNotFoundError("Markdown convertido não encontrado: a conversão precisa rodar antes da qualidade.")
    md = (ctx.pasta_projeto / doc.caminho_md).read_text(encoding="utf-8")
    resultado = avaliar_texto(md, ctx.parametros.get("idioma") or [])

    q = ler_qualidade(doc)
    q["problemas"] = resultado["problemas"]
    q["avisos"] = resultado["avisos"]
    q["idioma"] = resultado["idioma"]
    q["paginas_quase_vazias"] = resultado["paginas_quase_vazias"]
    q["palavras"] = resultado["palavras"]
    gravar_qualidade(doc, q)
    if resultado["problemas"]:
        doc.status = "com_problema"
    ctx.db.commit()
    return {"problemas": resultado["problemas"], "idioma": resultado["idioma"]}


MIN_PALAVRAS_TITULO = 4
_TITULO_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def titulo_normalizado(md: str) -> str | None:
    """Primeiro título do MD em minúsculas, sem acentos nem pontuação; None se curto demais para comparar."""
    m = _TITULO_MD.search(texto_visivel(md))
    if not m:
        return None
    t = unicodedata.normalize("NFKD", m.group(1).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    palavras_t = re.findall(r"[a-z0-9]+", t)
    return " ".join(palavras_t) if len(palavras_t) >= MIN_PALAVRAS_TITULO else None


def _definir(q: dict, chave: str, valor) -> bool:
    """Grava/remove ``q[chave]``; True se mudou."""
    if valor is None:
        return q.pop(chave, None) is not None
    if q.get(chave) == valor:
        return False
    q[chave] = valor
    return True


def marcar_duplicados(ctx: ContextoExecucao):
    docs = list(
        ctx.db.scalars(select(Documento).where(Documento.status != "removido").order_by(Documento.arquivo))
    )
    primeiro_por_hash: dict[str, str] = {}
    primeiro_por_titulo: dict[str, str] = {}
    duplicados = parecidos = 0
    for doc in docs:
        q = ler_qualidade(doc)
        mudou = False
        if doc.excluido:  # decisão do usuário: não entra nas comparações (as marcas ficam como estavam)
            continue
        original = primeiro_por_hash.get(doc.hash_sha256) if doc.hash_sha256 else None
        if original:
            duplicados += 1
        elif doc.hash_sha256:
            primeiro_por_hash[doc.hash_sha256] = doc.arquivo
        mudou |= _definir(q, "duplicado_de", original)

        titulo = None
        if not original and doc.caminho_md and (ctx.pasta_projeto / doc.caminho_md).is_file():
            titulo = titulo_normalizado((ctx.pasta_projeto / doc.caminho_md).read_text(encoding="utf-8"))
        parecido = primeiro_por_titulo.get(titulo) if titulo else None
        if parecido:
            parecidos += 1
        elif titulo:
            primeiro_por_titulo[titulo] = doc.arquivo
        mudou |= _definir(q, "similar_titulo", {"arquivo": parecido} if parecido else None)
        if mudou:
            gravar_qualidade(doc, q)
    ctx.db.commit()
    return {"duplicados": duplicados, "mesmo_titulo": parecidos}


registrar_etapa(Etapa(nome="qualidade", ordem=25, escopo="documento", funcao=avaliar, versao=VERSAO_ETAPA,
                       parametros_relevantes=["idioma"], depende_de=["conversao"]))
registrar_etapa(Etapa(nome="qualidade_duplicados", ordem=26, escopo="corpus", funcao=marcar_duplicados, versao=VERSAO_ETAPA, cacheavel=False))
