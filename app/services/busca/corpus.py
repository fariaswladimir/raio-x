"""15.12/15.13 - Segmentos do corpus (cache/segmentos, etapa 4.4) com rótulo do documento e página, e índice BM25 em memória.

Cada segmento: ``{id: "<documento>:<seg>", documento_id, rotulo, pagina, secao, texto}``. O índice BM25 é refeito só
quando os arquivos de segmentos mudam (assinatura por tamanho e data).
"""
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from app.services import segmentacao
from app.services.analises import dados
from app.services.busca.bm25 import IndiceBM25

_TRAVA = threading.Lock()
_CACHE: dict[str, tuple] = {}  # pasta -> (assinatura, segmentos, índice BM25)


def _assinatura(pasta: Path, metas: list[dict]) -> tuple:
    partes = []
    for m in metas:
        c = segmentacao.caminho_segmentos(pasta, m["id"])
        try:
            st = c.stat()
            partes.append((m["id"], st.st_size, int(st.st_mtime)))
        except OSError:
            partes.append((m["id"], 0, 0))
    return tuple(partes)


def carregar_segmentos(db: Session, pasta: Path) -> list[dict]:
    """Segmentos de todos os documentos ativos que têm segmentação, na ordem do corpus."""
    saida = []
    for m in dados.documentos_do_corpus(db, pasta):
        sg = segmentacao.ler_segmentos(pasta, m["id"])
        if not sg:
            continue
        for s in sg["segmentos"]:
            saida.append({"id": f"{m['id']}:{s['seg']}", "documento_id": m["id"], "rotulo": m["rotulo"], "pagina": s.get("pagina"),
                          "secao": s.get("secao"), "texto": s["texto"]})
    return saida


def segmentos_e_indice(db: Session, pasta: Path) -> tuple[list[dict], IndiceBM25]:
    metas = dados.documentos_do_corpus(db, pasta)
    ass = _assinatura(pasta, metas)
    chave = str(pasta)
    with _TRAVA:
        item = _CACHE.get(chave)
        if item and item[0] == ass:
            return item[1], item[2]
    segs = carregar_segmentos(db, pasta)
    indice = IndiceBM25([s["texto"] for s in segs])
    with _TRAVA:
        _CACHE[chave] = (ass, segs, indice)
    return segs, indice


def limpar_cache() -> None:
    with _TRAVA:
        _CACHE.clear()
