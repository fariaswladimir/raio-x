"""Raio-x do documento (15.3 legibilidade, 15.4 palavras-chave, 15.5 resumo): cálculo por documento com memória em processo.

Reúne ``legibilidade.py``, ``palavras_chave.py`` e ``sumarizacao.py`` sobre as frases do corpo de ``texto_documento.py``.
A chave da memória inclui o ``mtime`` dos arquivos de limpeza, tokens e ruído do documento e os parâmetros efetivos, então
reexecutar o pipeline ou mudar parâmetros invalida sozinho.
"""
import json
import threading
from collections import OrderedDict
from pathlib import Path

from app.services import ruido as svc_ruido
from app.services.analises import dados, legibilidade, palavras_chave, sumarizacao, texto_documento
from app.services.etapas.limpeza import caminho_limpo
from app.services.etapas.linguistica import caminho_tokens

PARTES = ("legibilidade", "palavras_chave", "resumos")
_MEMO: OrderedDict = OrderedDict()
_MEMO_MAX = 128
_TRAVA = threading.Lock()


def excluir_ruido(parametros: dict | None) -> bool:
    return svc_ruido.excluir_ruido(parametros)


def metodo_silabas(parametros: dict | None) -> str:
    v = ((parametros or {}).get("documento_extra") or {}).get("silabas_en", "heuristica")
    return v if v in ("heuristica", "pyphen") else "heuristica"


def _marca(caminho: Path):
    if not caminho.is_file():
        return None
    e = caminho.stat()
    return (e.st_mtime_ns, e.st_size)


def _memo(chave, fabricar):
    with _TRAVA:
        achado = _MEMO.get(chave)
        if achado is not None:
            _MEMO.move_to_end(chave)
            return achado
    valor = fabricar()
    with _TRAVA:
        _MEMO[chave] = valor
        while len(_MEMO) > _MEMO_MAX:
            _MEMO.popitem(last=False)
    return valor


def _chave(pasta: Path, documento_id: int, parametros: dict | None, *extra):
    pe = json.dumps((parametros or {}).get("documento_extra"), sort_keys=True, default=str)
    return (str(pasta), documento_id, _marca(caminho_limpo(pasta, documento_id)), _marca(caminho_tokens(pasta, documento_id)),
            svc_ruido.marca_do_arquivo(pasta, documento_id), excluir_ruido(parametros), pe,
            json.dumps((parametros or {}).get("palavras_vazias"), sort_keys=True, default=str), *extra)


def frases(pasta: Path, documento_id: int, parametros: dict | None) -> tuple[list[dict], str | None] | None:
    """``(frases, idioma)`` do corpo do documento (``None`` sem texto limpo)."""
    def fabricar():
        fr = texto_documento.frases_do_documento(pasta, documento_id, excluir_ruido(parametros))
        if fr is None:
            return None
        return fr, (dados.carregar_tokens(pasta, documento_id) or {}).get("idioma")
    return _memo(_chave(pasta, documento_id, parametros, "frases"), fabricar)


def legibilidade_do_documento(pasta: Path, documento_id: int, parametros: dict | None) -> dict | None:
    def fabricar():
        fi = frases(pasta, documento_id, parametros)
        if fi is None:
            return None
        return legibilidade.analisar_texto([f["texto"] for f in fi[0]], fi[1], metodo_silabas(parametros))
    return _memo(_chave(pasta, documento_id, parametros, "legibilidade"), fabricar)


def palavras_chave_do_documento(pasta: Path, documento_id: int, parametros: dict | None, metodo: str, n: int | None = None) -> list[dict] | None:
    def fabricar():
        fi = frases(pasta, documento_id, parametros)
        if fi is None:
            return None
        return palavras_chave.calcular(fi[0], fi[1], metodo, parametros, n)
    return _memo(_chave(pasta, documento_id, parametros, "pk", metodo, n), fabricar)


def resumo_do_documento(pasta: Path, documento_id: int, parametros: dict | None, metodo: str, n: int | None = None) -> dict | None:
    def fabricar():
        fi = frases(pasta, documento_id, parametros)
        if fi is None:
            return None
        return sumarizacao.resumir(fi[0], fi[1], metodo, parametros, n)
    return _memo(_chave(pasta, documento_id, parametros, "resumo", metodo, n), fabricar)


def calcular_documento(pasta: Path, documento_id: int, parametros: dict | None) -> dict | None:
    """Tudo de um documento: legibilidade, palavras-chave (3 métodos) e resumos (3 métodos)."""
    leg = legibilidade_do_documento(pasta, documento_id, parametros)
    if leg is None:
        return None
    return {
        "documento_id": documento_id, "idioma": leg["idioma"],
        "legibilidade": leg,
        "palavras_chave": {m: palavras_chave_do_documento(pasta, documento_id, parametros, m) for m in palavras_chave.METODOS},
        "resumos": {m: resumo_do_documento(pasta, documento_id, parametros, m) for m in sumarizacao.METODOS},
    }
