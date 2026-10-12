"""4.2 - Vocabulário do corpus: agregação (etapa ``vocabulario``) e ranking com palavras vazias na consulta.

Arquivo ``cache/vocabulario.json`` (a Frente 5 lê daqui). Só tokens com ``incluir = 1`` e com
``norm`` de >= 2 letras entram. Palavras vazias NÃO são removidas aqui:

    {
      "formato": 1,
      "parametros": {...},                     # parâmetros que definem o conteúdo (lematização, idioma, exclusão)
      "corpus": {
        "documentos": 51, "tokens": 437000,    # tokens contados (inclui palavras vazias)
        "tipos_lema": 21000, "tipos_norma": 26000,
        "lema":  {"agent": 5120, ...},         # frequência total por lema
        "norma": {"agents": 2300, ...},        # frequência total por forma normalizada (minúscula)
        "df_lema": {"agent": 47, ...},         # em quantos documentos aparece
        "df_norma": {"agents": 40, ...}
      },
      "documentos": {
        "<id>": {
          "arquivo": "001_...md", "idioma": "en",
          "tokens": 8000, "tipos_lema": 1900, "tipos_norma": 2300,
          "lema": {...}, "norma": {...},
          "pares": [["agents", "agent", 12], ...]   # (norm, lema, freq): permite filtrar por norm E lema
        }
      }
    }

O ranking (``ranking``) aplica o filtro de palavras vazias sobre os pares (norm, lema): o token
sai se qualquer um dos dois estiver no filtro. ``por_10k`` = frequência / tokens contados * 10 mil
(denominador inclui palavras vazias, como no Voyant).
"""
import json
from collections import Counter
from pathlib import Path

from app.services.palavras_vazias import COMPRIMENTO_MINIMO, token_vazio

FORMATO = 1
PARAMETROS_DO_CONTEUDO = ("lematizacao", "idioma", "excluir_referencias", "excluir_secoes")


def caminho_vocabulario(pasta_projeto: Path) -> Path:
    return pasta_projeto / "cache" / "vocabulario.json"


def contar_documento(tokens: dict) -> dict:
    """Contagens de um documento a partir dos arrays de cache/tokens/<id>.json."""
    pares: Counter = Counter()
    for norm, lema, inc in zip(tokens["norm"], tokens["lema"], tokens["incluir"]):
        if inc and len(norm) >= COMPRIMENTO_MINIMO:
            pares[(norm, lema)] += 1
    por_lema: Counter = Counter()
    por_norma: Counter = Counter()
    for (norm, lema), c in pares.items():
        por_lema[lema] += c
        por_norma[norm] += c
    return {
        "idioma": tokens.get("idioma"),
        "tokens": sum(pares.values()),
        "tipos_lema": len(por_lema),
        "tipos_norma": len(por_norma),
        "lema": dict(por_lema),
        "norma": dict(por_norma),
        "pares": [[n, l, c] for (n, l), c in pares.items()],
    }


def construir(docs: dict[int, dict], parametros: dict) -> dict:
    """``docs``: {documento_id: {"arquivo": str, **contar_documento(...)}} -> estrutura do vocabulario.json."""
    lema: Counter = Counter()
    norma: Counter = Counter()
    df_lema: Counter = Counter()
    df_norma: Counter = Counter()
    for d in docs.values():
        lema.update(d["lema"])
        norma.update(d["norma"])
        df_lema.update(d["lema"].keys())
        df_norma.update(d["norma"].keys())
    return {
        "formato": FORMATO,
        "parametros": {k: parametros.get(k) for k in PARAMETROS_DO_CONTEUDO},
        "corpus": {
            "documentos": len(docs),
            "tokens": sum(d["tokens"] for d in docs.values()),
            "tipos_lema": len(lema),
            "tipos_norma": len(norma),
            "lema": dict(lema),
            "norma": dict(norma),
            "df_lema": dict(df_lema),
            "df_norma": dict(df_norma),
        },
        "documentos": {str(i): d for i, d in sorted(docs.items())},
    }


_CACHE_LEITURA: dict[str, tuple[int, dict]] = {}


def ler_vocabulario(pasta_projeto: Path) -> dict | None:
    """Lê cache/vocabulario.json (com memória por data de modificação: o arquivo é grande)."""
    caminho = caminho_vocabulario(pasta_projeto)
    if not caminho.is_file():
        return None
    estado = caminho.stat()
    marca = (estado.st_mtime_ns, estado.st_size)
    guardado = _CACHE_LEITURA.get(str(caminho))
    if guardado and guardado[0] == marca:
        return guardado[1]
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    _CACHE_LEITURA[str(caminho)] = (marca, dados)
    return dados


def ranking(voc: dict, filtro, por: str = "lema", filtrar: bool = True, limite: int = 200,
            documento_id: int | None = None) -> dict:
    """Termos mais frequentes. ``por``: "lema" ou "forma" (norm). Devolve também totais do escopo."""
    if documento_id is None:
        docs = list(voc["documentos"].values())
    else:
        d = voc["documentos"].get(str(documento_id))
        docs = [d] if d else []
    total_tokens = sum(d["tokens"] for d in docs)
    freq: Counter = Counter()
    df: Counter = Counter()
    for d in docs:
        local: Counter = Counter()
        for norm, lema, c in d["pares"]:
            if filtrar and token_vazio(norm, lema, filtro):
                continue
            local[lema if por == "lema" else norm] += c
        freq.update(local)
        df.update(local.keys())
    ordenados = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    itens = [
        {"termo": t, "freq": c, "por_10k": round(c / total_tokens * 10000, 2) if total_tokens else 0.0, "docs": df[t]}
        for t, c in ordenados[: max(0, limite)]
    ]
    return {"por": por, "filtradas": filtrar, "documentos": len(docs), "tokens": total_tokens,
            "tipos": len(freq), "itens": itens}
