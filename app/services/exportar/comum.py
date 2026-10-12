"""Contexto e consultas compartilhados pelo laudo (9.1) e pelas planilhas (9.2)."""
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.services import parametros as svc_parametros
from app.services import vocabulario as svc_vocabulario
from app.services.analises import colocacoes, dados
from app.services.palavras_vazias import filtro_palavras_vazias

STATUS_NO_LAUDO = ("aceito", "editado")
STATUS_PENDENTES = ("sugerido", "revisar")
MAX_TERMOS_COLOCACOES = 15
_TERMO = re.compile(r"\|termo=([^|]+)")


class SemDados(Exception):
    """O pipeline ainda não gerou o vocabulário: não há o que exportar."""


def contexto(db: Session, pasta: Path) -> dict:
    voc = svc_vocabulario.ler_vocabulario(pasta)
    if voc is None:
        raise SemDados("Vocabulário não encontrado: execute o pipeline primeiro.")
    params = svc_parametros.carregar(pasta)
    return {"voc": voc, "params": params, "filtro": filtro_palavras_vazias(params),
            "metas": dados.documentos_do_corpus(db, pasta)}


def termo_da_chave(chave: str | None) -> str | None:
    achado = _TERMO.search(chave or "")
    return achado.group(1) if achado else None


def termos_dos_comentarios(comentarios, analises: tuple[str, ...] | None = None) -> list[str]:
    """Termos (lemas) citados nas chaves dos comentários, na ordem dos comentários, sem repetição."""
    vistos: list[str] = []
    for c in comentarios:
        if analises is not None and c.analise_tipo not in analises:
            continue
        t = termo_da_chave(c.chave)
        if t and t not in vistos:
            vistos.append(t)
    return vistos[:MAX_TERMOS_COLOCACOES]


def colocados_dos_termos(pasta: Path, ctx: dict, termos: list[str], limite: int = 50) -> list[tuple[str, dict]]:
    """Colocados (padrões da API: janela dos parâmetros, LL, fronteira = bloco) de cada termo, com ``colocacoes.calcular``."""
    j = min(int(ctx["params"].get("colocacao_janela") or 5), colocacoes.JANELA_MAXIMA)
    saida = []
    for t in termos:
        r = colocacoes.calcular(pasta, ctx["metas"], t, por="lema", esquerda=j, direita=j, filtro=ctx["filtro"],
                                filtrar=True, min_freq=3, min_freq_colocado=5, ordem="ll", limite=limite)
        saida.append((t, r))
    return saida
