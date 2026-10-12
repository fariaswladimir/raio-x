"""15.11 - Classificação zero-shot/few-shot por LLM (aba Codificação > Classificação).

Mesmas regras da 15.1: o LLM é opcional (409 se desligado), o lote roda em segundo plano com progresso e cancelamento, e o
resultado é revisável (aceitar/rejeitar por item) e comparável com os rótulos humanos (percentual, kappa, alfa).
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto, sessao_do_projeto
from app.routers.codificacao import _arred, _csv
from app.services.concordancia import classificador as clf
from app.services.concordancia import estatisticas
from app.services.llm import config
from app.services.llm.provedores import ErroLLM

router = APIRouter(prefix="/api/projetos/{slug}/classificacao", tags=["classificacao"])

NOTA_PAPEL = ("A classificação por LLM é uma sugestão para triagem e para checar o esquema de categorias: revise item a item "
              "(aceitar ou rejeitar). Zero-shot usa só as definições; few-shot acrescenta exemplos codificados por humanos, escolhidos "
              "de forma determinística, que ficam fora da avaliação.")
FILTROS = "^(todos|classificado|erro|exemplo|pendente_revisao|aceito|rejeitado|concordam|discordam)$"


class ClassificarIn(BaseModel):
    origem: str = "trechos"
    modo: str = "zero_shot"
    rotulos: list[dict] | str | None = None  # None = dicionário do projeto; texto "rótulo: definição" por linha
    k: int = 3
    multirrotulo: bool = False
    limite: int | None = None
    documento_id: int | None = None


def _erro(exc: Exception):
    if isinstance(exc, (clf.LLMDesligado, clf.ConfigInvalida)):
        raise HTTPException(status_code=409 if isinstance(exc, clf.LLMDesligado) else 422, detail=str(exc))
    if isinstance(exc, ErroLLM):
        raise HTTPException(status_code=409 if exc.categoria == "config" else 502,
                            detail=config.ocultar(str(exc), config.ler_chave("anthropic"), config.ler_chave("openai_compativel")))
    raise exc


@router.get("/rotulos")
def rotulos(slug: str, _db: Session = Depends(get_db)):
    """Rótulos disponíveis no dicionário do projeto e a configuração da última execução."""
    pasta = pasta_do_projeto(slug)
    return {"dicionario": clf.rotulos_do_dicionario(pasta), "ultima_config": clf.ler_config_salva(pasta), "origens": list(clf.ORIGENS),
            "modos": list(clf.MODOS), "nota": NOTA_PAPEL}


@router.post("/estimativa")
def estimativa(slug: str, dados: ClassificarIn, db: Session = Depends(get_db)):
    try:
        return clf.estimativa(db, pasta_do_projeto(slug), dados.model_dump())
    except clf.ConfigInvalida as exc:
        _erro(exc)


@router.post("/executar", response_model=None)
def executar(slug: str, response: Response, dados: ClassificarIn, sincrono: bool = False):
    """Classifica em segundo plano (202; acompanhe em /progresso); ``sincrono=1`` espera terminar (testes)."""
    pasta = pasta_do_projeto(slug)
    if dados.limite is not None and dados.limite < 1:
        raise HTTPException(status_code=422, detail="limite deve ser >= 1.")
    try:
        if sincrono:
            if clf.progresso(slug).get("rodando"):
                raise HTTPException(status_code=409, detail="Já existe uma classificação em andamento neste projeto.")
            return clf.executar(slug, lambda: sessao_do_projeto(slug), pasta, dados.model_dump())
        r = clf.iniciar(slug, lambda: sessao_do_projeto(slug), pasta, dados.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (clf.LLMDesligado, clf.ConfigInvalida, ErroLLM) as exc:
        _erro(exc)
    response.status_code = 202
    return r


@router.get("/progresso")
def progresso(slug: str, _db: Session = Depends(get_db)):
    return clf.progresso(slug)


@router.post("/cancelar")
def cancelar(slug: str, _db: Session = Depends(get_db)):
    return {"cancelando": clf.cancelar(slug)}


def _concorda(it) -> bool | None:
    p = clf.par_humano_llm(it)
    return None if p is None else p[0] == p[1]


def _out(it) -> dict:
    return {"id": it.id, "origem": it.origem, "ref": it.ref, "documento_id": it.documento_id, "documento": it.rotulo_doc, "pagina": it.pagina,
            "texto": it.texto, "rotulos": clf.rotulos_do_item(it), "rotulo_humano": it.rotulo_humano, "justificativa": it.justificativa,
            "confianca": it.confianca, "status": it.status, "revisao": it.revisao, "modelo": it.modelo, "concorda": _concorda(it)}


def _filtrar(itens, filtro: str, rotulo: str | None, busca: str | None):
    if filtro in ("classificado", "erro", "exemplo"):
        itens = [i for i in itens if i.status == filtro]
    elif filtro == "pendente_revisao":
        itens = [i for i in itens if i.status == "classificado" and i.revisao == "pendente"]
    elif filtro in ("aceito", "rejeitado"):
        itens = [i for i in itens if i.revisao == filtro]
    elif filtro in ("concordam", "discordam"):
        alvo = filtro == "concordam"
        itens = [i for i in itens if _concorda(i) is alvo]
    if rotulo:
        itens = [i for i in itens if rotulo in clf.rotulos_do_item(i) or i.rotulo_humano == rotulo]
    if busca:
        b = busca.lower()
        itens = [i for i in itens if b in i.texto.lower() or b in (i.rotulo_doc or "").lower()]
    return itens


def _todos(db: Session):
    return list(db.scalars(select(clf.ClassificacaoItem).order_by(clf.ClassificacaoItem.id)))


@router.get("/itens")
def itens(slug: str, filtro: str = Query("todos", pattern=FILTROS), rotulo: str | None = None, busca: str | None = None,
          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=2000), db: Session = Depends(get_db)):
    todos = _todos(db)
    cont = {"total": len(todos), "classificado": sum(i.status == "classificado" for i in todos), "erro": sum(i.status == "erro" for i in todos),
            "exemplo": sum(i.status == "exemplo" for i in todos), "aceito": sum(i.revisao == "aceito" for i in todos),
            "rejeitado": sum(i.revisao == "rejeitado" for i in todos),
            "pendente_revisao": sum(i.status == "classificado" and i.revisao == "pendente" for i in todos),
            "concordam": sum(_concorda(i) is True for i in todos), "discordam": sum(_concorda(i) is False for i in todos)}
    sel = _filtrar(todos, filtro, rotulo, busca)
    return {"contagens": cont, "n": len(sel), "itens": [_out(i) for i in sel[offset:offset + limit]],
            "config": clf.ler_config_salva(pasta_do_projeto(slug)), "nota": NOTA_PAPEL}


class RevisaoIn(BaseModel):
    revisao: str


@router.post("/itens/{item_id}/revisao")
def revisar(slug: str, item_id: int, dados: RevisaoIn, db: Session = Depends(get_db)):
    if dados.revisao not in ("pendente", "aceito", "rejeitado"):
        raise HTTPException(status_code=422, detail="revisao deve ser pendente, aceito ou rejeitado.")
    it = db.get(clf.ClassificacaoItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    if it.status != "classificado":
        raise HTTPException(status_code=409, detail="Só itens classificados podem ser revisados.")
    it.revisao = dados.revisao
    db.commit()
    return _out(it)


class RevisaoLoteIn(BaseModel):
    revisao: str
    ids: list[int] | None = None
    confianca_minima: float | None = None


@router.post("/revisar-lote")
def revisar_lote(slug: str, dados: RevisaoLoteIn, db: Session = Depends(get_db)):
    """Aceita/rejeita vários itens classificados de uma vez (por ids ou por confiança mínima)."""
    if dados.revisao not in ("pendente", "aceito", "rejeitado"):
        raise HTTPException(status_code=422, detail="revisao deve ser pendente, aceito ou rejeitado.")
    n = 0
    for it in _todos(db):
        if it.status != "classificado":
            continue
        if dados.ids is not None and it.id not in dados.ids:
            continue
        if dados.confianca_minima is not None and (it.confianca is None or it.confianca < dados.confianca_minima):
            continue
        it.revisao = dados.revisao
        n += 1
    db.commit()
    return {"alterados": n}


@router.delete("")
def limpar(slug: str, db: Session = Depends(get_db)):
    if clf.progresso(slug).get("rodando"):
        raise HTTPException(status_code=409, detail="Há uma classificação em andamento.")
    n = db.execute(delete(clf.ClassificacaoItem)).rowcount
    db.commit()
    return {"itens": n}


@router.get("/itens.csv")
def itens_csv(slug: str, filtro: str = Query("todos", pattern=FILTROS), rotulo: str | None = None, busca: str | None = None,
              db: Session = Depends(get_db)):
    sel = _filtrar(_todos(db), filtro, rotulo, busca)
    cab = ["id", "origem", "ref", "documento", "pagina", "texto", "rotulos_llm", "rotulo_humano", "concorda", "confianca", "justificativa",
           "status", "revisao", "modelo"]
    linhas = [[i.id, i.origem, i.ref, i.rotulo_doc, i.pagina, i.texto, "|".join(clf.rotulos_do_item(i)), i.rotulo_humano,
               {True: "sim", False: "não", None: ""}[_concorda(i)], i.confianca, i.justificativa, i.status, i.revisao, i.modelo] for i in sel]
    return _csv("classificacao_itens.csv", cab, linhas)


@router.get("/concordancia")
def concordancia(slug: str, bootstrap: int = Query(1000, ge=0, le=10000), semente: int = 42,
                 somente: str = Query("todos", pattern="^(todos|nao_rejeitados|aceitos)$"), db: Session = Depends(get_db)):
    """Concordância (15.1: percentual, kappa de Cohen, alfa de Krippendorff, por rótulo, confusão) entre o rótulo humano e o
    do LLM, nos itens que têm os dois. ``somente``: restringe aos itens não rejeitados ou só aos aceitos na revisão."""
    h, l = [], []
    for it in _todos(db):
        if somente == "aceitos" and it.revisao != "aceito":
            continue
        if somente == "nao_rejeitados" and it.revisao == "rejeitado":
            continue
        p = clf.par_humano_llm(it)
        if p:
            h.append(p[0])
            l.append(p[1])
    if not h:
        raise HTTPException(status_code=409, detail="Nenhum item com rótulo humano e classificação válida: use a origem \"trechos\" "
                                                    "(codificação humana importada) e rode a classificação.")
    r = estatisticas.resumo(h, l, bootstrap=bootstrap, semente=semente)
    cfg = clf.ler_config_salva(pasta_do_projeto(slug)) or {}
    return _arred({"n_itens": len(h), "somente": somente, **r, "modo": cfg.get("modo"), "multirrotulo": cfg.get("multirrotulo"),
                   "nota": NOTA_PAPEL + (" No modo multirrótulo, o acerto vale se o rótulo humano está entre os do LLM."
                                         if cfg.get("multirrotulo") else "")})
