"""Raio-x descritivo (Frente 5), comparativo (6.1–6.4), textometria (6.2, 7.3) e temático (7.1 Reinert, 7.2 similitude + 15.2).

Todas as consultas leem o cache do pipeline (vocabulário, tokens, texto limpo) e aplicam na hora o filtro
de palavras vazias e o escopo (corpus | documento | grupo | ano). Os CSV saem em UTF-8 com BOM e ``;``.
"""
import csv
import io
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services import parametros as svc_parametros
from app.services import segmentacao
from app.services import termos_compostos as svc_termos
from app.services import vocabulario as svc_vocabulario
from app.services import dicionario as svc_dicionario
from app.services.analises import afc, colocacoes, dados, dicionario, especificidades, frequencias, keyness, kwic, ngramas, resumo, similaridade
from app.services.analises import reinert, similitude
from app.services.etapas.tematico import parametros_reinert, parametros_similitude
from app.services.etapas.termos_compostos import hash_relevante
from app.services.exportar.planilhas import _n, csv_bytes
from app.services.palavras_vazias import filtro_palavras_vazias

router = APIRouter(prefix="/api/projetos/{slug}/analises", tags=["analises"])

Escopo = Literal["corpus", "documento", "grupo", "ano"]
Por = Literal["lema", "forma", "termo"]
MAX_LINHAS_CSV = 100000


def _contexto(slug: str, db: Session) -> tuple:
    """(pasta, parâmetros, vocabulário, documentos do corpus)."""
    pasta = pasta_do_projeto(slug)
    voc = svc_vocabulario.ler_vocabulario(pasta)
    if voc is None:
        raise HTTPException(status_code=404, detail="Vocabulário não encontrado: execute o pipeline primeiro.")
    return pasta, svc_parametros.carregar(pasta), voc, dados.documentos_do_corpus(db, pasta)


def voc_por(pasta, voc: dict, por: str) -> tuple[dict, str]:
    """Vocabulário e unidade interna para ``por``. Com "termo" (4.3) devolve a visão por termo (ver
    services/termos_compostos.py) lida como "lema"; as respostas devem repor ``por`` = "termo"."""
    if por != "termo":
        return voc, por
    tc = svc_termos.ler_termos_corpus(pasta)
    if tc is None:
        raise HTTPException(status_code=409, detail="Termos compostos não calculados: execute o pipeline (etapa termos_compostos).")
    return svc_termos.visao_vocabulario(voc, tc, str(pasta), (id(voc), svc_termos.marca_termos_corpus(pasta))), "lema"


def _exige_termos(pasta, por: str) -> None:
    if por == "termo" and svc_termos.marca_termos_corpus(pasta) is None:
        raise HTTPException(status_code=409, detail="Termos compostos não calculados: execute o pipeline (etapa termos_compostos).")


def _escopo(metas: list[dict], escopo: str, valor: str | None) -> list[dict]:
    if escopo != "corpus" and not valor:
        raise HTTPException(status_code=422, detail=f"Escopo '{escopo}' exige o parâmetro 'valor'.")
    docs = dados.filtrar_escopo(metas, escopo, valor)
    if escopo == "documento" and not docs:
        raise HTTPException(status_code=404, detail=f"Documento {valor} sem análise (não processado ou com problema).")
    return docs


def _csv(nome: str, cabecalho: list[str], linhas) -> Response:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    return Response(
        content=("﻿" + saida.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


def _decimal(x: float) -> str:
    return str(x).replace(".", ",")  # Excel em pt-BR


# ---------- 5.1 resumo ----------

def _resumo(slug: str, db: Session) -> dict:
    pasta, params, _voc, metas = _contexto(slug, db)
    res = resumo.resumo_do_projeto(pasta, metas, params)
    if res is None:
        raise HTTPException(status_code=404, detail="Vocabulário não encontrado: execute o pipeline primeiro.")
    return res


@router.get("/resumo")
def resumo_do_corpus(slug: str, db: Session = Depends(get_db)):
    """Resumo do corpus e de cada documento (tokens, tipos, densidade, MATTR, termos distintivos TF-IDF)."""
    return _resumo(slug, db)


@router.get("/resumo/documentos/{documento_id}")
def resumo_do_documento(slug: str, documento_id: int, db: Session = Depends(get_db)):
    res = _resumo(slug, db)
    for d in res["documentos"]:
        if d["documento_id"] == documento_id:
            return {"metodologia": res["metodologia"], **d}
    raise HTTPException(status_code=404, detail=f"Documento {documento_id} sem resumo (não processado ou com problema).")


# ---------- 5.2 frequências e tendências ----------

def _frequencias(slug, db, por, vazias, escopo, valor, limite, filtro):
    pasta, params, voc, metas = _contexto(slug, db)
    docs = _escopo(metas, escopo, valor)
    voc, interno = voc_por(pasta, voc, por)
    r = frequencias.listar(voc, docs, filtro_palavras_vazias(params), por=interno, filtrar=(vazias == "filtrar"),
                           limite=limite, filtro_texto=filtro)
    return {**r, "por": por, "escopo": escopo, "valor": valor}


@router.get("/frequencias")
def listar_frequencias(
    slug: str,
    por: Por = "lema",
    vazias: Literal["filtrar", "manter"] = "filtrar",
    escopo: Escopo = "corpus",
    valor: str | None = None,
    limite: int = Query(200, ge=1, le=5000),
    filtro: str = "",
    db: Session = Depends(get_db),
):
    """Termos por frequência (freq, por 10 mil, nº de documentos). ``filtro``: trecho do termo ou curinga ``*``."""
    return _frequencias(slug, db, por, vazias, escopo, valor, limite, filtro)


@router.get("/frequencias.csv")
def frequencias_csv(
    slug: str,
    por: Por = "lema",
    vazias: Literal["filtrar", "manter"] = "filtrar",
    escopo: Escopo = "corpus",
    valor: str | None = None,
    limite: int = Query(5000, ge=1, le=100000),
    filtro: str = "",
    db: Session = Depends(get_db),
):
    r = _frequencias(slug, db, por, vazias, escopo, valor, limite, filtro)
    linhas = ([i + 1, t["termo"], t["freq"], _decimal(t["por_10k"]), t["docs"]] for i, t in enumerate(r["itens"]))
    return _csv("frequencias.csv", ["posicao", "termo", "frequencia", "por_10_mil", "documentos"], linhas)


@router.get("/tendencias")
def tendencias(
    slug: str,
    termos: str = Query(..., min_length=1, description="Até 6 termos separados por vírgula; curinga *"),
    por: Por = "lema",
    agrupar: Literal["documento", "ano", "grupo"] = "documento",
    metrica: Literal["rel", "bruta"] = "rel",
    db: Session = Depends(get_db),
):
    """Distribuição de termos por documento (ordem do arquivo), ano ou grupo (``rel`` = por 10 mil tokens da unidade)."""
    pasta, _params, voc, metas = _contexto(slug, db)
    lista = dados.termos_da_lista(termos)
    if not lista:
        raise HTTPException(status_code=422, detail="Informe ao menos um termo.")
    voc, interno = voc_por(pasta, voc, por)
    return {**frequencias.distribuicao(voc, metas, lista, por=interno, agrupar=agrupar, metrica=metrica), "por": por}


# ---------- 5.3 KWIC ----------

def _kwic(slug, db, q, por, escopo, valor, janela, ordem, offset, limit, incluir_excluidas, quebrar=True):
    pasta, params, _voc, metas = _contexto(slug, db)
    docs = _escopo(metas, escopo, valor)
    _exige_termos(pasta, por)
    if janela is None:
        janela = int(params.get("kwic_janela") or 10)
    try:
        return kwic.buscar(pasta, docs, q, por=por, janela=janela, ordem=ordem, offset=offset, limit=limit,
                           incluir_excluidas=incluir_excluidas, quebrar=quebrar)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/kwic")
def concordancia(
    slug: str,
    q: str = Query(..., min_length=1, description='Termos separados por vírgula; curinga *; entre aspas ("human oversight") = frase'),
    por: Por = "lema",
    escopo: Escopo = "corpus",
    valor: str | None = None,
    janela: int | None = Query(None, ge=1, le=100, description="Palavras de cada lado (padrão: parâmetro kwic_janela)"),
    ordem: Literal["corpus", "esquerda", "direita"] = "corpus",
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    incluir_excluidas: bool = False,
    quebrar: bool = Query(True, description="Frase entre aspas: pontuação entre as palavras quebra a sequência (como nos n-gramas)"),
    db: Session = Depends(get_db),
):
    """Concordância paginada (``total`` = todas as ocorrências). Cada linha traz página, seção e a posição do token."""
    return _kwic(slug, db, q, por, escopo, valor, janela, ordem, offset, limit, incluir_excluidas, quebrar)


@router.get("/kwic/contexto")
def contexto_da_ocorrencia(
    slug: str,
    documento_id: int,
    posicao: int = Query(..., ge=0),
    janela: int = Query(60, ge=1, le=300),
    incluir_excluidas: bool = False,
    db: Session = Depends(get_db),
):
    """Contexto ampliado (±60 palavras) de uma ocorrência, com a citação "(rótulo, p. N)"."""
    pasta, _params, _voc, metas = _contexto(slug, db)
    docs = dados.filtrar_escopo(metas, "documento", documento_id)
    if not docs:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} sem análise (não processado ou com problema).")
    r = kwic.contexto_ampliado(pasta, docs[0], posicao, janela, incluir_excluidas)
    if r is None:
        raise HTTPException(status_code=404, detail=f"Posição {posicao} fora do documento {documento_id}.")
    return r


@router.get("/kwic.csv")
def concordancia_csv(
    slug: str,
    q: str = Query(..., min_length=1),
    por: Por = "lema",
    escopo: Escopo = "corpus",
    valor: str | None = None,
    janela: int | None = Query(None, ge=1, le=100),
    ordem: Literal["corpus", "esquerda", "direita"] = "corpus",
    incluir_excluidas: bool = False,
    quebrar: bool = True,
    db: Session = Depends(get_db),
):
    r = _kwic(slug, db, q, por, escopo, valor, janela, ordem, 0, MAX_LINHAS_CSV, incluir_excluidas, quebrar)
    linhas = ([i["rotulo"], i["arquivo"], i["pagina"] if i["pagina"] is not None else "", i["secao"],
               i["esquerda"], i["termo"], i["direita"]] for i in r["itens"])
    return _csv("kwic.csv", ["documento", "arquivo", "pagina", "secao", "esquerda", "termo", "direita"], linhas)


# ---------- 5.4 colocados ----------

def _colocacoes(slug, db, q, por, escopo, valor, esquerda, direita, vazias, min_freq, min_freq_colocado, ordem,
                limite, fronteira, repulsao):
    pasta, params, _voc, metas = _contexto(slug, db)
    docs = _escopo(metas, escopo, valor)
    padrao = int(params.get("colocacao_janela") or 5)
    esquerda = min(padrao, colocacoes.JANELA_MAXIMA) if esquerda is None else esquerda
    direita = min(padrao, colocacoes.JANELA_MAXIMA) if direita is None else direita
    _exige_termos(pasta, por)
    if esquerda + direita == 0:
        raise HTTPException(status_code=422, detail="A janela precisa de ao menos 1 posição (esquerda + direita > 0).")
    r = colocacoes.calcular(pasta, docs, q, por=por, esquerda=esquerda, direita=direita,
                            filtro=filtro_palavras_vazias(params), filtrar=(vazias == "filtrar"), min_freq=min_freq,
                            min_freq_colocado=min_freq_colocado, ordem=ordem, limite=limite, fronteira=fronteira,
                            repulsao=repulsao)
    r["parametros"].update({"escopo": escopo, "valor": valor})
    return r


def _params_colocacoes(
    q: str = Query(..., min_length=1, description="Nó: termo(s) separados por vírgula; curinga *"),
    por: Por = "lema",
    escopo: Escopo = "corpus",
    valor: str | None = None,
    esquerda: int | None = Query(None, ge=0, le=20, description="Posições à esquerda (padrão: colocacao_janela)"),
    direita: int | None = Query(None, ge=0, le=20, description="Posições à direita (padrão: colocacao_janela)"),
    vazias: Literal["filtrar", "manter"] = "filtrar",
    min_freq: int = Query(3, ge=1, description="Mínimo de coocorrências (O11)"),
    min_freq_colocado: int = Query(5, ge=1, description="Mínimo de ocorrências do colocado no escopo (C1)"),
    ordem: Literal["ll", "mi", "freq", "logdice", "t"] = "ll",
    fronteira: Literal["bloco", "documento"] = "bloco",
    repulsao: bool = False,
) -> dict:
    return dict(q=q, por=por, escopo=escopo, valor=valor, esquerda=esquerda, direita=direita, vazias=vazias,
                min_freq=min_freq, min_freq_colocado=min_freq_colocado, ordem=ordem, fronteira=fronteira,
                repulsao=repulsao)


@router.get("/colocacoes")
def listar_colocacoes(
    slug: str,
    p: dict = Depends(_params_colocacoes),
    limite: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Colocados do nó com LL (G² com sinal), p, MI, t, logDice e perfil por posição (ver ``colocacoes.py``)."""
    return _colocacoes(slug, db, limite=limite, **p)


@router.get("/colocacoes.csv")
def colocacoes_csv(
    slug: str,
    p: dict = Depends(_params_colocacoes),
    limite: int = Query(1000, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    r = _colocacoes(slug, db, limite=limite, **p)
    rels = [*range(-r["parametros"]["esquerda"], 0), *range(1, r["parametros"]["direita"] + 1)]
    cab = ["posicao", "colocado", "o11", "c1", "e11", "ll", "p", "mi", "t", "logdice", "pares",
           *[f"E{-x}" if x < 0 else f"D{x}" for x in rels]]
    linhas = ([i + 1, c["termo"], c["o11"], c["c1"], _decimal(c["e11"]), _decimal(c["ll"]), f"{c['p']:.3e}".replace(".", ","),
               _decimal(c["mi"]), _decimal(c["t"]), _decimal(c["logdice"]), c["pares"],
               *[c["posicoes"][str(x)] for x in rels]] for i, c in enumerate(r["colocados"]))
    return _csv("colocacoes.csv", cab, linhas)


# ---------- 6.1 keyness entre grupos ----------

def _keyness(slug, db, particao, a, b, por, vazias, min_freq, min_docs_a, min_docs_b, p, bonferroni, ordem, limite):
    pasta, params, voc, metas = _contexto(slug, db)
    voc, interno = voc_por(pasta, voc, por)
    try:
        r = keyness.calcular(voc, metas, filtro_palavras_vazias(params), particao=particao, a=a, b=b, por=interno,
                             filtrar=(vazias == "filtrar"), min_freq=min_freq, min_docs_a=min_docs_a,
                             min_docs_b=min_docs_b, p=p, bonferroni=bonferroni, ordem=ordem, limite=limite)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    r["por"] = r["parametros"]["por"] = por
    return r


def _params_keyness(
    particao: Literal["grupo", "ano"] = "grupo",
    a: str = Query(..., min_length=1, description="Lado A: grupo(s) ou ano(s), separados por vírgula"),
    b: str = Query("resto", description='Lado B: grupo(s)/ano(s) ou "resto" (todos os demais documentos)'),
    por: Por = "lema",
    vazias: Literal["filtrar", "manter"] = "filtrar",
    min_freq: int = Query(5, ge=1, description="Frequência total mínima (a + b)"),
    min_docs_a: int = Query(2, ge=1, description="Dispersão: documentos de A em que a palavra-chave de A ocorre"),
    min_docs_b: int = Query(2, ge=1, description="Dispersão: documentos de B em que a palavra-chave de B ocorre"),
    p: float = Query(0.01, gt=0, le=1, description="Limiar de significância"),
    bonferroni: bool = False,
    ordem: Literal["ll", "logratio"] = "ll",
) -> dict:
    return dict(particao=particao, a=a, b=b, por=por, vazias=vazias, min_freq=min_freq, min_docs_a=min_docs_a,
                min_docs_b=min_docs_b, p=p, bonferroni=bonferroni, ordem=ordem)


@router.get("/grupos")
def grupos_e_anos(slug: str, db: Session = Depends(get_db)):
    """Grupos e anos do corpus com nº de documentos e de tokens (base da comparação entre grupos)."""
    _pasta, _params, voc, metas = _contexto(slug, db)
    return keyness.lados_disponiveis(voc, metas)


@router.get("/keyness")
def palavras_chave(
    slug: str,
    p: dict = Depends(_params_keyness),
    limite: int = Query(50, ge=1, le=1000, description="Palavras-chave de cada lado"),
    db: Session = Depends(get_db),
):
    """Palavras-chave de A contra B: G² de 2 células com sinal, p, Log Ratio, %DIFF, /10k e amplitude (ver ``keyness.py``)."""
    return _keyness(slug, db, limite=limite, **p)


@router.get("/keyness.csv")
def palavras_chave_csv(
    slug: str,
    p: dict = Depends(_params_keyness),
    limite: int = Query(1000, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    r = _keyness(slug, db, limite=limite, **p)
    linhas = ([lado, i + 1, k["termo"], k["a"], k["b"], _decimal(k["por_10k_a"]), _decimal(k["por_10k_b"]),
               _decimal(round(k["g2"], 4)), f"{k['p']:.3e}".replace(".", ","), f"{k['p_bonferroni']:.3e}".replace(".", ","),
               _decimal(round(k["log_ratio"], 4)), "" if k["pct_diff"] is None else _decimal(round(k["pct_diff"], 2)),
               k["docs_a"], k["docs_b"]]
              for lado, itens in (("A", r["positivas"]), ("B", r["negativas"])) for i, k in enumerate(itens))
    cab = ["lado", "posicao", "termo", "freq_a", "freq_b", "por_10k_a", "por_10k_b", "g2", "p", "p_bonferroni",
           "log_ratio", "pct_diff", "docs_a", "docs_b"]
    return _csv("keyness.csv", cab, linhas)


# ---------- 5.5 n-gramas ----------

def _ngramas(slug, db, por, n_min, n_max, stop, quebrar, min_freq, min_docs, contem, posicao, ordem, limite, offset,
             escopo, valor):
    pasta, params, _voc, metas = _contexto(slug, db)
    docs = _escopo(metas, escopo, valor)
    try:
        return {**ngramas.listar(pasta, docs, filtro_palavras_vazias(params), por=por, n_min=n_min, n_max=n_max, stop=stop,
                                 quebrar_pontuacao=quebrar, min_freq=min_freq, min_docs=min_docs, contem=contem,
                                 posicao=posicao, ordem=ordem, limite=limite, offset=offset),
                "escopo": escopo, "valor": valor}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/ngramas")
def listar_ngramas(
    slug: str,
    por: Literal["forma", "lema"] = "forma",
    n_min: int = Query(2, ge=2, le=6),
    n_max: int = Query(4, ge=2, le=6),
    stop: Literal["todas", "sem_bordas", "sem_vazias"] = "sem_bordas",
    quebrar: bool = Query(True, description="Pontuação de frase/oração e parágrafo quebram o n-grama"),
    min_freq: int = Query(3, ge=1),
    min_docs: int = Query(2, ge=1),
    contem: str = Query("", description="Só n-gramas que contêm o termo (vírgula = alternativas; curinga *)"),
    posicao: Literal["qualquer", "inicio", "fim"] = "qualquer",
    ordem: Literal["freq", "docs", "n"] = "freq",
    limite: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    escopo: Escopo = "corpus",
    valor: str | None = None,
    db: Session = Depends(get_db),
):
    """N-gramas (2 a 6 palavras) por forma ou lema: freq, por 10 mil, documentos (faixa) e concentração no documento
    principal. Equivale ao Clusters/N-Grams do AntConc e ao Phrases do Voyant; não é a lista de termos compostos (4.3)."""
    return _ngramas(slug, db, por, n_min, n_max, stop, quebrar, min_freq, min_docs, contem, posicao, ordem, limite,
                    offset, escopo, valor)


@router.get("/ngramas.csv")
def ngramas_csv(
    slug: str,
    por: Literal["forma", "lema"] = "forma",
    n_min: int = Query(2, ge=2, le=6),
    n_max: int = Query(4, ge=2, le=6),
    stop: Literal["todas", "sem_bordas", "sem_vazias"] = "sem_bordas",
    quebrar: bool = True,
    min_freq: int = Query(3, ge=1),
    min_docs: int = Query(2, ge=1),
    contem: str = "",
    posicao: Literal["qualquer", "inicio", "fim"] = "qualquer",
    ordem: Literal["freq", "docs", "n"] = "freq",
    limite: int = Query(5000, ge=1, le=MAX_LINHAS_CSV),
    escopo: Escopo = "corpus",
    valor: str | None = None,
    db: Session = Depends(get_db),
):
    r = _ngramas(slug, db, por, n_min, n_max, stop, quebrar, min_freq, min_docs, contem, posicao, ordem, limite, 0,
                 escopo, valor)
    linhas = ([i["ngrama"], i["n"], i["freq"], i["por_10k"], i["docs"], i["concentracao"]] for i in r["itens"])
    corpo = csv_bytes(["ngrama", "n", "frequencia", "por_10_mil", "documentos", "concentracao"], linhas)
    return Response(content=corpo, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="ngramas.csv"'})


# ---------- 4.3 termos compostos ----------

class TermosCompostosEdicao(BaseModel):
    """Edição da lista de termos compostos (sequências de lemas separadas por espaço, ex.: "agentic ai")."""

    aceitar: list[str] = []  # entra em ``lista`` (sobrevive a mudanças de limiar); sai de ``bloqueados``
    bloquear: list[str] = []  # entra em ``bloqueados``; sai de ``lista``
    remover_da_lista: list[str] = []
    desbloquear: list[str] = []


def _termos_validos(termos: list[str]) -> list[str]:
    saida = [svc_termos.normalizar_termo(t) for t in termos]
    ruins = [t for t in saida if len(t.split()) < 2]
    if ruins:
        raise HTTPException(status_code=422, detail=f"Termo composto precisa de ao menos 2 palavras: {', '.join(repr(t) for t in ruins)}.")
    return saida


@router.get("/termos-compostos")
def listar_termos_compostos(
    slug: str,
    origem: Literal["todos", "automatico", "lista"] = "todos",
    limite: int = Query(500, ge=1, le=5000),
):
    """Termos compostos efetivos (freq, documentos, escore, origem, ``aplicados`` = ocorrências marcadas), a lista e os
    bloqueados dos parâmetros ATUAIS. ``desatualizado`` = os parâmetros mudaram depois do último cálculo."""
    pasta = pasta_do_projeto(slug)
    tc = svc_termos.ler_termos_corpus(pasta)
    if tc is None:
        raise HTTPException(status_code=404, detail="Termos compostos não calculados: execute o pipeline primeiro.")
    params = svc_parametros.carregar(pasta)
    cfg = svc_termos.configuracao(params)
    itens = [c for c in tc["itens"] if origem == "todos" or c["origem"] == origem]
    return {"ativa": tc["ativa"], "total": len(itens), "itens": itens[:limite], "lista": cfg["lista"],
            "bloqueados": cfg["bloqueados"], "configuracao": {k: v for k, v in cfg.items() if k not in ("lista", "bloqueados")},
            "desatualizado": tc["hash"] != hash_relevante(params)}


@router.patch("/termos-compostos")
def editar_termos_compostos(slug: str, edicao: TermosCompostosEdicao):
    """Aceita/bloqueia termos: atualiza ``termos_compostos.lista``/``bloqueados`` em parametros.json (versionado) e
    pede nova execução do pipeline (só a etapa ``termos_compostos`` é refeita)."""
    pasta = pasta_do_projeto(slug)
    params = svc_parametros.carregar(pasta)
    cfg = svc_termos.configuracao(params)
    lista, bloqueados = list(cfg["lista"]), list(cfg["bloqueados"])
    aceitar, bloquear = _termos_validos(edicao.aceitar), _termos_validos(edicao.bloquear)
    tirar_lista, tirar_bloq = _termos_validos(edicao.remover_da_lista), _termos_validos(edicao.desbloquear)
    for t in aceitar:
        bloqueados = [x for x in bloqueados if x != t]
        lista.append(t)
    for t in bloquear:
        lista = [x for x in lista if x != t]
        bloqueados.append(t)
    lista = [x for x in dict.fromkeys(lista) if x not in tirar_lista]
    bloqueados = [x for x in dict.fromkeys(bloqueados) if x not in tirar_bloq]
    params["termos_compostos"] = {**params.get("termos_compostos", {}), "lista": lista, "bloqueados": bloqueados}
    novos = svc_parametros.salvar(pasta, params)
    return {"lista": lista, "bloqueados": bloqueados, "versao_parametros": novos["versao_parametros"],
            "reexecutar": True, "mensagem": "Parâmetros salvos. Execute o pipeline para aplicar (só a etapa de termos compostos é refeita)."}


# ---------- 4.4 segmentos ----------

FAIXAS_SEGMENTO = [(1, 10), (11, 20), (21, 30), (31, 40), (41, 50), (51, 60), (61, None)]
_FIM_DE_FRASE = re.compile(r"[.?!…][\"'”’)\]]*$")


@router.get("/segmentos/resumo")
def resumo_dos_segmentos(slug: str, db: Session = Depends(get_db)):
    """Segmentos do corpus: total, tamanho médio/mediano, distribuição de tamanhos e % que terminam em pontuação de frase."""
    pasta = pasta_do_projeto(slug)
    tamanhos: list[int] = []
    cortes: dict[str, int] = {}
    em_frase = 0
    por_documento = []
    alvo = None
    for m in dados.documentos_do_corpus(db, pasta):
        seg = segmentacao.ler_segmentos(pasta, m["id"])
        if seg is None:
            continue
        alvo = seg["alvo"]
        por_documento.append({"documento_id": m["id"], "rotulo": m["rotulo"], "segmentos": len(seg["segmentos"])})
        for s in seg["segmentos"]:
            tamanhos.append(s["n_tokens"])
            cortes[s["corte"]] = cortes.get(s["corte"], 0) + 1
            em_frase += bool(_FIM_DE_FRASE.search(s["texto"]))
    if not tamanhos:
        raise HTTPException(status_code=404, detail="Segmentos não encontrados: execute o pipeline primeiro.")
    ordenados = sorted(tamanhos)
    meio = len(ordenados) // 2
    mediana = ordenados[meio] if len(ordenados) % 2 else (ordenados[meio - 1] + ordenados[meio]) / 2
    distribuicao = [{"de": a, "ate": b, "segmentos": sum(1 for t in tamanhos if t >= a and (b is None or t <= b))}
                    for a, b in FAIXAS_SEGMENTO]
    return {"alvo": alvo, "segmentos": len(tamanhos), "documentos": len(por_documento),
            "media": round(sum(tamanhos) / len(tamanhos), 2), "mediana": mediana, "minimo": ordenados[0],
            "maximo": ordenados[-1], "distribuicao": distribuicao, "cortes": cortes,
            "pct_fim_de_frase": round(100 * em_frase / len(tamanhos), 1), "por_documento": por_documento}


# ---------- 6.3 similaridade entre documentos ----------

def _similaridade(slug, db, por, escopo, valor, metodo, k, min_df, max_df, sublinear):
    pasta, params, voc, metas = _contexto(slug, db)
    if escopo == "documento":
        raise HTTPException(status_code=422, detail="Similaridade compara vários documentos: use escopo corpus, grupo ou ano.")
    docs = _escopo(metas, escopo, valor)
    voc, interno = voc_por(pasta, voc, por)
    try:
        r = similaridade.calcular(voc, docs, filtro_palavras_vazias(params), por=interno, metodo=metodo, k=k, min_df=min_df,
                                  max_df=max_df, sublinear=sublinear)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    r["unidade"] = r["parametros"]["por"] = por
    return {**r, "escopo": escopo, "valor": valor}


def _params_similaridade(
    por: Por = "lema",
    escopo: Escopo = "corpus",
    valor: str | None = None,
    metodo: Literal["average", "ward"] = "ward",
    k: int | None = Query(None, ge=1, le=50, description="Número de grupos; omitido = automático (silhueta, 2 a 8)"),
    min_df: int = Query(2, ge=1, description="Termo em pelo menos N documentos"),
    max_df: float = Query(0.9, gt=0, le=1, description="Termo em no máximo esta fração dos documentos"),
    sublinear: bool = Query(True, description="tf = 1 + ln f"),
) -> dict:
    return dict(por=por, escopo=escopo, valor=valor, metodo=metodo, k=k, min_df=min_df, max_df=max_df, sublinear=sublinear)


@router.get("/similaridade")
def similaridade_entre_documentos(slug: str, p: dict = Depends(_params_similaridade), db: Session = Depends(get_db)):
    """Cosseno TF-IDF entre documentos, dendrograma (ligação média ou Ward), grupos (k ou automático), mapa 2D,
    vizinhos e termos característicos de cada grupo (ver ``similaridade.py``). Equivale ao Lexos e ao Orange."""
    return _similaridade(slug, db, **p)


@router.get("/similaridade.csv")
def similaridade_csv(slug: str, p: dict = Depends(_params_similaridade), db: Session = Depends(get_db)):
    """Matriz de similaridade (cosseno) com os rótulos dos documentos."""
    r = _similaridade(slug, db, **p)
    rotulos = [d["rotulo"] for d in r["documentos"]]
    linhas = ([rot, *[_decimal(v) for v in linha]] for rot, linha in zip(rotulos, r["similaridade"]))
    return _csv("similaridade.csv", ["documento", *rotulos], linhas)


@router.get("/agrupamentos.csv")
def agrupamentos_csv(slug: str, p: dict = Depends(_params_similaridade), db: Session = Depends(get_db)):
    """Grupo de cada documento, coordenadas do mapa 2D e vizinhos mais próximos."""
    r = _similaridade(slug, db, **p)
    n_viz = r["parametros"]["vizinhos"]
    cab = ["documento_id", "rotulo", "arquivo", "grupo", "ano", "cluster", "x", "y",
           *[c for i in range(1, n_viz + 1) for c in (f"vizinho_{i}", f"similaridade_{i}")]]
    linhas = []
    for d in r["documentos"]:
        viz = [c for v in d["vizinhos"] for c in (v["rotulo"], _decimal(v["similaridade"]))]
        linhas.append([d["id"], d["rotulo"], d["arquivo"], d["grupo"], d["ano"], d["cluster"], _decimal(d["x"]), _decimal(d["y"]),
                       *viz, *[""] * (2 * n_viz - len(viz))])
    return _csv("agrupamentos.csv", cab, linhas)


# ---------- 6.4 dicionário / codebook ----------

def _dicionario(slug, db, agrupar, por):
    pasta, _params, voc, metas = _contexto(slug, db)
    try:
        dic = svc_dicionario.carregar(pasta)
        return dicionario.calcular(pasta, voc, metas, dic, por=por, agrupar=agrupar)
    except svc_dicionario.DicionarioInvalido as exc:
        raise HTTPException(status_code=422, detail={"erros": exc.erros})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/dicionario")
def contagem_do_dicionario(
    slug: str,
    agrupar: Literal["grupo", "ano", "documento"] = "grupo",
    por: Literal["lema", "forma"] = "lema",
    db: Session = Depends(get_db),
):
    """Ocorrências de cada categoria do dicionário (/10k, documentos, por grupo/ano/documento, G² e Log Ratio contra o resto)."""
    return _dicionario(slug, db, agrupar, por)


@router.get("/dicionario.csv")
def dicionario_csv(
    slug: str,
    agrupar: Literal["grupo", "ano", "documento"] = "grupo",
    por: Literal["lema", "forma"] = "lema",
    db: Session = Depends(get_db),
):
    r = _dicionario(slug, db, agrupar, por)
    linhas = []
    for c in r["categorias"]:
        linhas.append([c["id"], c["nome"], c["tema"], "(corpus)", c["total"], _decimal(c["por_10k"]), c["docs"], r["documentos"], "", "", ""])
        for u in c["unidades"]:
            linhas.append([c["id"], c["nome"], c["tema"], u["rotulo"], u["n"], _decimal(u["por_10k"]), u["docs"], u["documentos"],
                           "" if u["g2"] is None else _decimal(round(u["g2"], 4)),
                           "" if u["p"] is None else f"{u['p']:.3e}".replace(".", ","),
                           "" if u["log_ratio"] is None else _decimal(round(u["log_ratio"], 4))])
    cab = ["categoria", "nome", "tema", agrupar, "ocorrencias", "por_10k", "documentos_com", "documentos", "g2", "p", "log_ratio"]
    return _csv("dicionario.csv", cab, linhas)


# ---------- 6.2 especificidades (modelo hipergeométrico) ----------

Particao = Literal["grupo", "ano", "documento", "classe"]


def _csv_seguro(nome: str, cabecalho: list[str], linhas) -> Response:
    return Response(content=csv_bytes(cabecalho, ([_n(v) for v in linha] for linha in linhas)),
                    media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _params_especificidades(
    particao: Particao = "ano",
    por: Por = "lema",
    vazias: Literal["filtrar", "manter"] = "filtrar",
    min_freq: int = Query(5, ge=1, description="Frequência mínima do termo no corpus (F)"),
    limiar: float = Query(especificidades.LIMIAR_PADRAO, gt=0, le=especificidades.TETO,
                          description="|score| abaixo disto = banal (2 = P > 0,01)"),
) -> dict:
    return dict(particao=particao, por=por, vazias=vazias, min_freq=min_freq, limiar=limiar)


def _tabela_classe(pasta, params, metas, particao, por, vazias):
    """Tabela termo × classe (partição "classe": classes da CHD com os parâmetros do projeto) ou None."""
    if particao != "classe":
        return None
    _exige_termos(pasta, por)
    filtro = filtro_palavras_vazias(params)
    try:
        r = reinert.calcular(pasta, metas, filtro, **parametros_reinert(params))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Partição 'classe' indisponível: {exc}")
    return reinert.tabela_por_classe(pasta, metas, filtro, r, por, vazias == "filtrar")


def _especificidades(slug, db, particao, por, vazias, min_freq, limiar, limite, termos=None):
    pasta, params, voc, metas = _contexto(slug, db)
    tabela = _tabela_classe(pasta, params, metas, particao, por, vazias)
    voc, interno = voc_por(pasta, voc, por) if tabela is None else (voc, por)
    try:
        r = especificidades.calcular(voc, metas, filtro_palavras_vazias(params), particao=particao, por=interno,
                                     filtrar=(vazias == "filtrar"), min_freq=min_freq, limiar=limiar, limite=limite,
                                     termos_matriz=termos, tabela=tabela)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    r["por"] = r["parametros"]["por"] = por
    return r


@router.get("/especificidades")
def especificidades_por_parte(
    slug: str,
    p: dict = Depends(_params_especificidades),
    limite: int = Query(20, ge=1, le=1000, description="Termos específicos positivos e negativos por parte"),
    termos: str = Query("", description="Termos da matriz parte × termo, separados por vírgula (vazio = 3 mais específicos de cada parte)"),
    db: Session = Depends(get_db),
):
    """Especificidades de Lafon (hipergeométrica) de cada parte: score = ±log10 da cauda, teto 50, banal se |score| < limiar."""
    lista = [t.strip().lower() for t in termos.split(",") if t.strip()] or None
    return _especificidades(slug, db, limite=limite, termos=lista, **p)


@router.get("/especificidades/termo")
def especificidades_do_termo(
    slug: str,
    termo: str = Query(..., min_length=1),
    p: dict = Depends(_params_especificidades),
    db: Session = Depends(get_db),
):
    """Score de especificidade de um termo em todas as partes (gráfico de especificidades do TXM)."""
    pasta, params, voc, metas = _contexto(slug, db)
    tabela = _tabela_classe(pasta, params, metas, p["particao"], p["por"], p["vazias"])
    voc, interno = voc_por(pasta, voc, p["por"]) if tabela is None else (voc, p["por"])
    try:
        r = especificidades.do_termo(voc, metas, filtro_palavras_vazias(params), termo, particao=p["particao"],
                                     por=interno, filtrar=(p["vazias"] == "filtrar"), limiar=p["limiar"], tabela=tabela)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    r["por"] = p["por"]
    return r


@router.get("/especificidades.csv")
def especificidades_csv(
    slug: str,
    p: dict = Depends(_params_especificidades),
    limite: int = Query(1000, ge=1, le=MAX_LINHAS_CSV),
    db: Session = Depends(get_db),
):
    r = _especificidades(slug, db, limite=limite, **p)
    linhas = ([parte["rotulo"], sinal, i + 1, k["termo"], k["f"], k["F"], k["esperada"], k["score"],
               "sim" if k["acima_do_teto"] else "não", parte["tokens"], k["por_10k"]]
              for parte in r["partes"] for sinal, itens in (("+", parte["positivas"]), ("-", parte["negativas"]))
              for i, k in enumerate(itens))
    cab = ["parte", "sinal", "posicao", "termo", "f_parte", "F_corpus", "esperada", "score", "acima_do_teto_50",
           "tokens_parte", "por_10k_parte"]
    return _csv_seguro("especificidades.csv", cab, linhas)


# ---------- 7.3 AFC (análise fatorial de correspondência) ----------

def _params_afc(
    particao: Particao = "ano",
    por: Por = "lema",
    vazias: Literal["filtrar", "manter"] = "filtrar",
    n_termos: int = Query(100, ge=2, le=afc.N_TERMOS_MAX, description="Termos (linhas) da tabela"),
    selecao: Literal["freq", "especificidade"] = "freq",
    eixos: int = Query(afc.EIXOS_MAX, ge=1, le=afc.EIXOS_MAX, description="Máximo de eixos devolvidos"),
    min_freq: int = Query(5, ge=1, description="Frequência mínima do termo no corpus"),
) -> dict:
    return dict(particao=particao, por=por, vazias=vazias, n_termos=n_termos, selecao=selecao, eixos=eixos, min_freq=min_freq)


def _afc(slug, db, particao, por, vazias, n_termos, selecao, eixos, min_freq):
    pasta, params, voc, metas = _contexto(slug, db)
    tabela = _tabela_classe(pasta, params, metas, particao, por, vazias)
    voc, interno = voc_por(pasta, voc, por) if tabela is None else (voc, por)
    try:
        r = afc.calcular(voc, metas, filtro_palavras_vazias(params), particao=particao, por=interno,
                         filtrar=(vazias == "filtrar"), n_termos=n_termos, selecao=selecao, eixos=eixos, min_freq=min_freq,
                         tabela=tabela)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    r["por"] = r["parametros"]["por"] = por
    return r


@router.get("/afc")
def analise_fatorial(slug: str, p: dict = Depends(_params_afc), db: Session = Depends(get_db)):
    """AFC da tabela termo × parte: autovalores, coordenadas principais, ctr e cos² de termos e partes (ver ``afc.py``)."""
    return _afc(slug, db, **p)


@router.get("/afc.csv")
def analise_fatorial_csv(slug: str, p: dict = Depends(_params_afc), db: Session = Depends(get_db)):
    """Coordenadas, ctr (%) e cos² de termos e partes por eixo (uma linha por termo/parte)."""
    r = _afc(slug, db, **p)
    k = r["k"]
    cab = ["tipo", "nome", "freq", "massa", "inercia_pct", "qualidade",
           *[c for e in range(1, k + 1) for c in (f"coord_{e}", f"ctr_{e}", f"cos2_{e}")]]

    def linha(tipo, nome, x):
        return [tipo, nome, x["freq"], x["massa"], x["inercia_pct"], x["qualidade"],
                *[v for e in range(k) for v in (x["coord"][e], x["ctr"][e], x["cos2"][e])]]

    linhas = [*(linha("parte", c["rotulo"], c) for c in r["colunas"]), *(linha("termo", t["termo"], t) for t in r["linhas"])]
    return _csv_seguro("afc.csv", cab, linhas)


# ---------- 7.1 CHD de Reinert ----------

def _params_reinert(
    classes: int | None = Query(None, ge=2, le=reinert.CLASSES_MAX, description="Classes terminais (padrão: parâmetros do projeto, 10)"),
    min_freq: int | None = Query(None, ge=1, description="Frequência mínima das formas ativas (padrão 3)"),
    dupla: bool | None = Query(None, description="Classificação dupla (dois tamanhos de UC)"),
    tamanho_a: int | None = Query(None, ge=5, le=1000, description="1º tamanho de UC em palavras (dupla; padrão 40)"),
    tamanho_b: int | None = Query(None, ge=5, le=1000, description="2º tamanho de UC em palavras (dupla; padrão 60)"),
    min_classe: int | None = Query(None, ge=0, description="Tamanho mínimo de classe em ST (0 = automático)"),
    max_formas: int | None = Query(None, ge=0, le=50000, description="Formas ativas mais frequentes (0 = todas)"),
) -> dict:
    return {k: v for k, v in dict(classes=classes, min_freq=min_freq, dupla=dupla, tamanho_a=tamanho_a,
                                  tamanho_b=tamanho_b, min_classe=min_classe, max_formas=max_formas).items() if v is not None}


def _reinert(slug, db, p: dict) -> tuple[dict, Path, list[dict]]:
    pasta, params, _voc, metas = _contexto(slug, db)
    q = parametros_reinert(params)
    tam = list(q["tamanhos"])
    if "tamanho_a" in p:
        tam[0] = p.pop("tamanho_a")
    if "tamanho_b" in p:
        tam[1] = p.pop("tamanho_b")
    q.update(p, tamanhos=tam)
    try:
        return reinert.calcular(pasta, metas, filtro_palavras_vazias(params), **q), pasta, metas
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/reinert")
def classificacao_reinert(slug: str, p: dict = Depends(_params_reinert), mapa: bool = False, db: Session = Depends(get_db)):
    """CHD de Reinert (IRaMuTeQ/ALCESTE) sobre os segmentos: dendrograma, classes (formas e variáveis por χ²),
    segmentos típicos, retenção e AFC das classes. ``mapa=1`` inclui a classe de cada segmento por documento."""
    r, _pasta, _metas = _reinert(slug, db, p)
    return r if mapa else {k: v for k, v in r.items() if k != "classes_por_documento"}


@router.get("/reinert/classes.csv")
def reinert_classes_csv(slug: str, p: dict = Depends(_params_reinert), db: Session = Depends(get_db)):
    """Formas e variáveis características de cada classe (χ² com sinal, p, frequências)."""
    r, _pasta, _metas = _reinert(slug, db, p)
    linhas = []
    for c in r["classes"]:
        for i, f in enumerate(c["formas"]):
            linhas.append([c["classe"], c["n_st"], c["pct"], "forma", i + 1, f["forma"], f["chi2"], f["p"],
                           f["freq_classe"], f["freq_total"], f["pct_classe"]])
        for var in reinert.VARIAVEIS:
            for i, v in enumerate(c["variaveis"][var]):
                linhas.append([c["classe"], c["n_st"], c["pct"], var, i + 1, v["modalidade"], v["chi2"], v["p"],
                               v["st_classe"], v["st_total"], v["pct_classe"]])
    cab = ["classe", "st_classe", "pct_classe_st", "tipo", "posicao", "item", "chi2", "p", "st_com_item_na_classe",
           "st_com_item_total", "pct_na_classe"]
    return _csv_seguro("reinert_classes.csv", cab, linhas)


@router.get("/reinert/segmentos.csv")
def reinert_segmentos_csv(slug: str, p: dict = Depends(_params_reinert), db: Session = Depends(get_db)):
    """Classe de cada segmento de texto (0 = não classificado), com documento, página e texto."""
    r, pasta, metas = _reinert(slug, db, p)
    linhas = []
    for m in metas:
        mapa = r["classes_por_documento"].get(str(m["id"]))
        seg = segmentacao.ler_segmentos(pasta, m["id"])
        if not mapa or not seg:
            continue
        for s, c in zip(seg["segmentos"], mapa):
            linhas.append([m["id"], m["rotulo"], s["seg"], s["pagina"], s["n_tokens"], c, s["texto"]])
    cab = ["documento_id", "documento", "segmento", "pagina", "palavras", "classe", "texto"]
    return _csv_seguro("reinert_segmentos.csv", cab, linhas)


# ---------- 7.2 similitude / rede de coocorrência + 15.2 comunidades e centralidade ----------

def _params_similitude(
    indice: Literal["coocorrencia", "jaccard", "cosseno", "pmi"] | None = None,
    n_formas: int | None = Query(None, ge=3, le=similitude.N_FORMAS_MAX, description="Formas mais frequentes (padrão 60)"),
    arvore: bool | None = Query(None, description="Árvore máxima (padrão) ou rede top-k"),
    comunidades: bool = Query(True, description="Calcula comunidades (Louvain)"),
    arestas_por_no: int = Query(3, ge=1, le=20, description="Rede: arestas mais fortes de cada forma"),
    limiar: float | None = Query(None, gt=0, description="Rede: em vez do top-k, todas as arestas com peso >= limiar"),
) -> dict:
    return dict(indice=indice, n_formas=n_formas, arvore=arvore, comunidades_on=comunidades,
                arestas_por_no=arestas_por_no, limiar=limiar)


def _similitude(slug, db, p: dict) -> dict:
    pasta, params, _voc, metas = _contexto(slug, db)
    q = parametros_similitude(params)
    q.update({k: v for k, v in p.items() if v is not None})
    try:
        return similitude.calcular(pasta, metas, filtro_palavras_vazias(params), **q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/similitude")
def analise_de_similitude(slug: str, p: dict = Depends(_params_similitude), db: Session = Depends(get_db)):
    """Similitude (árvore máxima, IRaMuTeQ) ou rede de coocorrência (KH Coder) por segmento, com comunidades
    (Louvain), centralidades e layout Fruchterman-Reingold calculados no servidor (semente fixa)."""
    return _similitude(slug, db, p)


@router.get("/similitude/arestas.csv")
def similitude_arestas_csv(slug: str, p: dict = Depends(_params_similitude), db: Session = Depends(get_db)):
    r = _similitude(slug, db, p)
    cab = ["forma_a", "forma_b", f"peso_{r['indice']}", "coocorrencias", "jaccard", "cosseno", "pmi", "comunidade"]
    linhas = ([a["a"], a["b"], a["peso"], a["coocorrencias"], a["jaccard"], a["cosseno"], a["pmi"], a["comunidade"]]
              for a in r["arestas"])
    return _csv_seguro("similitude_arestas.csv", cab, linhas)


@router.get("/similitude/nos.csv")
def similitude_nos_csv(slug: str, p: dict = Depends(_params_similitude), db: Session = Depends(get_db)):
    r = _similitude(slug, db, p)
    cab = ["forma", "freq", "segmentos", "comunidade", "grau", "grau_ponderado", "intermediacao", "pagerank", "x", "y"]
    linhas = ([n["forma"], n["freq"], n["n_st"], n["comunidade"], n["grau"], n["grau_ponderado"], n["intermediacao"],
               n["pagerank"], n["x"], n["y"]] for n in r["nos"])
    return _csv_seguro("similitude_nos.csv", cab, linhas)
