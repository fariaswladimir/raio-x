"""15.8 Keyness contra corpus de referência externo: importação da referência (por projeto), lista e cálculo.

Rotas em /api/projetos/{slug}/referencias* e /api/projetos/{slug}/analises/keyness-referencia*. A lógica está em
services/analises/keyness_referencia.py (formato aceito, OOV, unidade, comparabilidade). Nenhum corpus de referência
acompanha o Raio-X: o usuário importa o dele. CSV em UTF-8 com BOM e ``;``.
"""
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.routers.analises import _contexto
from app.services.analises import keyness_referencia as kr
from app.services.exportar.planilhas import _n, csv_bytes
from app.services.palavras_vazias import filtro_palavras_vazias

router = APIRouter(prefix="/api/projetos/{slug}", tags=["keyness-referencia"])


class ReferenciaIn(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    idioma: Literal["en", "pt", "es"]
    fonte: str = Field("", max_length=500, description="De onde vem a lista (corpus, versão, licença)")
    # Uma das duas formas: texto da lista (CSV/TSV lido no navegador) ou caminho local (arquivo da lista ou pasta de .txt).
    conteudo: str | None = Field(None, description="Texto da lista 'termo;frequência'")
    caminho: str | None = Field(None, description="Arquivo da lista ou pasta de .txt/.md no computador do usuário")
    total: int | None = Field(None, ge=1, description="Total de tokens da referência (recomendado quando a lista é truncada)")


def _excecoes(slug: str) -> dict | None:
    from app.services import parametros as svc_parametros
    return (svc_parametros.carregar(pasta_do_projeto(slug)).get("lematizacao") or {}).get("excecoes")


@router.get("/referencias")
def listar_referencias(slug: str, _db: Session = Depends(get_db)):
    """Referências importadas no projeto (metadados) e o aviso de comparabilidade."""
    return {"itens": kr.listar(pasta_do_projeto(slug)), "aviso": kr.AVISO_COMPARAVEL}


@router.post("/referencias", status_code=201)
def importar_referencia(slug: str, corpo: ReferenciaIn, _db: Session = Depends(get_db)):
    pasta = pasta_do_projeto(slug)
    try:
        if corpo.conteudo is not None:
            return kr.importar_lista(pasta, corpo.nome, corpo.conteudo, corpo.idioma, corpo.fonte, corpo.total, _excecoes(slug))
        if not corpo.caminho:
            raise kr.ReferenciaInvalida("Envie o texto da lista (conteudo) ou o caminho de um arquivo/pasta (caminho).")
        alvo = Path(corpo.caminho)
        if alvo.is_dir():
            return kr.importar_textos(pasta, corpo.nome, alvo, corpo.idioma, corpo.fonte, _excecoes(slug))
        if alvo.is_file():
            texto = alvo.read_text(encoding="utf-8-sig", errors="replace")
            return kr.importar_lista(pasta, corpo.nome, texto, corpo.idioma, corpo.fonte or alvo.name, corpo.total, _excecoes(slug))
        raise kr.ReferenciaInvalida(f"Caminho não encontrado: {corpo.caminho}")
    except kr.ReferenciaInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/referencias/{ref_id}", status_code=204)
def remover_referencia(slug: str, ref_id: str, _db: Session = Depends(get_db)):
    try:
        if not kr.remover(pasta_do_projeto(slug), ref_id):
            raise HTTPException(status_code=404, detail="Referência não encontrada.")
    except kr.ReferenciaInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _params(
    referencia: str = Query(..., min_length=1, description="Identificador da referência importada"),
    escopo: Literal["corpus", "grupo", "ano"] = "corpus",
    valor: str | None = Query(None, description="Grupo ou ano, quando o escopo não é o corpus inteiro"),
    por: Literal["lema", "forma"] = "lema",
    vazias: Literal["filtrar", "manter"] = "filtrar",
    min_freq: int = Query(5, ge=1),
    min_docs: int = Query(2, ge=1, description="Dispersão: documentos do corpus em que a palavra-chave ocorre"),
    p: float = Query(0.01, gt=0, le=1),
    bonferroni: bool = False,
    ordem: Literal["ll", "logratio"] = "ll",
    oov: Literal["incluir", "excluir"] = "incluir",
) -> dict:
    return dict(referencia=referencia, escopo=escopo, valor=valor, por=por, vazias=vazias, min_freq=min_freq,
                min_docs=min_docs, p=p, bonferroni=bonferroni, ordem=ordem, oov=oov)


def _calcular(slug: str, db: Session, limite: int, referencia, escopo, valor, por, vazias, min_freq, min_docs, p,
              bonferroni, ordem, oov) -> dict:
    pasta, params, voc, metas = _contexto(slug, db)
    try:
        ref = kr.carregar(pasta, referencia)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Referência não encontrada: importe uma lista de frequências.")
    except kr.ReferenciaInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        sel, rotulo = kr.escopo_metas(metas, escopo, valor)
        return kr.calcular(voc, sel, filtro_palavras_vazias(params), ref, por=por, filtrar=(vazias == "filtrar"),
                           min_freq=min_freq, min_docs=min_docs, p=p, bonferroni=bonferroni, ordem=ordem, oov=oov,
                           limite=limite, rotulo_corpus=rotulo)
    except (ValueError, kr.ReferenciaInvalida) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/analises/keyness-referencia")
def keyness_contra_referencia(slug: str, p: dict = Depends(_params), limite: int = Query(50, ge=1, le=1000),
                              db: Session = Depends(get_db)):
    """Palavras-chave do corpus (ou grupo/ano) contra a referência importada, com os metadados da referência."""
    return _calcular(slug, db, limite, **p)


@router.get("/analises/keyness-referencia.csv")
def keyness_contra_referencia_csv(slug: str, p: dict = Depends(_params), limite: int = Query(1000, ge=1, le=100000),
                                  db: Session = Depends(get_db)):
    r = _calcular(slug, db, limite, **p)
    ref = r["referencia"]
    cab = ["lado", "posicao", "termo", "freq_corpus", "freq_referencia", "por_10k_corpus", "por_10k_referencia", "g2", "p",
           "p_bonferroni", "log_ratio", "pct_diff", "docs_corpus", "fora_da_referencia"]
    linhas = ([lado, i + 1, k["termo"], k["a"], k["b"], k["por_10k_a"], k["por_10k_b"], round(k["g2"], 4), f"{k['p']:.3e}",
               f"{k['p_bonferroni']:.3e}", round(k["log_ratio"], 4), "" if k["pct_diff"] is None else round(k["pct_diff"], 2),
               k["docs_a"], k["oov"]]
              for lado, itens in (("corpus", r["positivas"]), ("referencia", r["negativas"])) for i, k in enumerate(itens))
    meta = [["# referencia", ref["nome"]], ["# fonte", ref["fonte"]], ["# idioma", ref["idioma"]],
            ["# tokens_referencia", ref["tokens"]], ["# corpus", r["corpus"]["valor"]], ["# tokens_corpus", r["corpus"]["tokens"]],
            ["# unidade", r["por"]], ["# aviso", r["aviso_comparavel"]]]
    corpo = csv_bytes(cab, ([_n(v) for v in linha] for linha in linhas))
    prefixo = "".join(f"{a};{b}\r\n" for a, b in meta).encode("utf-8")
    return Response(content=corpo[:3] + prefixo + corpo[3:], media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="keyness_referencia_{ref["id"]}.csv"'})
