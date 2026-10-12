"""15.1 - Codificação por LLM (segundo codificador) e concordância com a codificação humana.

O LLM entra como **segundo codificador para checar a confiabilidade** do codebook e da codificação, não como
substituto do pesquisador. Importação da planilha (.xlsx, corpo bruto), lote de codificação com progresso, tabela de
trechos com filtros, estatísticas (percentual, kappa de Cohen, alfa de Krippendorff, por código, matriz de confusão) e
CSV (UTF-8 com BOM, ``;``).
"""
import json
import re
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto, sessao_do_projeto
from app.models import CodificacaoTrecho, Documento
from app.services.analises.dados import rotulo_do_documento
from app.services.concordancia import codificador, estatisticas, importacao
from app.services.exportar.planilhas import _n, csv_bytes
from app.services.llm import config
from app.services.llm.provedores import ErroLLM

router = APIRouter(prefix="/api/projetos/{slug}/codificacao", tags=["codificacao"])

NOTA_PAPEL = ("O LLM atua como segundo codificador, às cegas (não recebe o código humano), para checar a confiabilidade "
              "do codebook e da codificação. Ele não substitui a codificação humana: divergências apontam trechos e "
              "códigos para rever, não erros do pesquisador.")


def _csv(nome: str, cabecalho: list[str], linhas) -> Response:
    return Response(content=csv_bytes(cabecalho, ([_n(v) for v in linha] for linha in linhas)),
                    media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# ---------- importação ----------

def _mapeamento(texto: str | None) -> dict | None:
    if not texto:
        return None
    try:
        m = json.loads(texto)
    except ValueError:
        raise HTTPException(status_code=422, detail="mapeamento deve ser um JSON {papel: coluna}.")
    if not isinstance(m, dict):
        raise HTTPException(status_code=422, detail="mapeamento deve ser um JSON {papel: coluna}.")
    return m


@router.post("/inspecionar")
async def inspecionar_planilha(slug: str, request: Request, mapeamento: str | None = None, db: Session = Depends(get_db)):
    """Abas com colunas de trecho e código reconhecidas (para conferir o mapeamento antes de importar)."""
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    try:
        abas = importacao.ler_planilha(conteudo)
        info = importacao.inspecionar(abas, _mapeamento(mapeamento))
        sugerida = importacao.escolher_abas(info, None) if info else []
    except importacao.PlanilhaInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"abas": info, "todas_as_abas": list(abas), "sugerida": sugerida[0] if sugerida else None,
            "papeis": list(importacao.PAPEIS)}


@router.post("/importar")
async def importar_planilha(slug: str, request: Request, aba: str | None = None,
                            modo: str = Query("substituir", pattern="^(substituir|acrescentar)$"),
                            codebook: bool | None = None, mapeamento: str | None = None, db: Session = Depends(get_db)):
    """Importa os trechos codificados (corpo = .xlsx). ``aba`` = nome, ``*`` (todas) ou vazio (detecção);
    ``mapeamento`` = JSON {papel: coluna} para corrigir a detecção. A planilha só é lida."""
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    if codificador.progresso(slug).get("rodando"):
        raise HTTPException(status_code=409, detail="Há uma codificação em andamento: espere terminar ou cancele.")
    try:
        return importacao.importar(db, pasta_do_projeto(slug), conteudo, aba=aba, mapeamento=_mapeamento(mapeamento),
                                   modo=modo, codebook=codebook)
    except importacao.PlanilhaInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------- trechos ----------

def _concordam(t: CodificacaoTrecho) -> bool | None:
    if t.codigo_humano is None or t.codigo_llm is None:
        return None
    return t.codigo_humano.strip().lower() == t.codigo_llm.strip().lower()


def _trecho_out(t: CodificacaoTrecho, rotulos: dict) -> dict:
    return {"id": t.id, "registro": t.registro, "fonte": t.fonte, "fonte_rotulo": t.fonte_rotulo, "aba": t.aba,
            "documento_id": t.documento_id, "documento": rotulos.get(t.documento_id), "pagina": t.pagina, "secao": t.secao,
            "texto": t.texto, "traducao": t.traducao, "codigo_humano": t.codigo_humano, "tema_humano": t.tema_humano,
            "codigo_llm": t.codigo_llm, "justificativa_llm": t.justificativa_llm, "confianca": t.confianca,
            "modelo": t.modelo, "status": t.status, "concorda": _concordam(t)}


def _rotulos(db: Session) -> dict:
    return {d.id: rotulo_do_documento(d) for d in db.scalars(select(Documento))}


def _filtrar(trechos, filtro: str, codigo: str | None, busca: str | None):
    if filtro == "concordam":
        trechos = [t for t in trechos if _concordam(t) is True]
    elif filtro == "discordam":
        trechos = [t for t in trechos if _concordam(t) is False]
    elif filtro in ("pendente", "erro", "codificado"):
        trechos = [t for t in trechos if t.status == filtro]
    if codigo:
        trechos = [t for t in trechos if codigo in (t.codigo_humano, t.codigo_llm)]
    if busca:
        b = busca.lower()
        trechos = [t for t in trechos if b in t.texto.lower() or b in (t.fonte_rotulo or "").lower()]
    return trechos


@router.get("/trechos")
def listar_trechos(slug: str, filtro: str = Query("todos", pattern="^(todos|concordam|discordam|pendente|erro|codificado)$"),
                   codigo: str | None = None, busca: str | None = None, offset: int = Query(0, ge=0),
                   limit: int = Query(100, ge=1, le=2000), db: Session = Depends(get_db)):
    todos = list(db.scalars(select(CodificacaoTrecho).order_by(CodificacaoTrecho.id)))
    cont = {"total": len(todos), "pendente": sum(t.status == "pendente" for t in todos),
            "codificado": sum(t.status == "codificado" for t in todos), "erro": sum(t.status == "erro" for t in todos),
            "concordam": sum(_concordam(t) is True for t in todos), "discordam": sum(_concordam(t) is False for t in todos),
            "com_documento": sum(t.documento_id is not None for t in todos)}
    sel = _filtrar(todos, filtro, codigo, busca)
    rot = _rotulos(db)
    return {"contagens": cont, "n": len(sel), "itens": [_trecho_out(t, rot) for t in sel[offset:offset + limit]],
            "nota": NOTA_PAPEL}


@router.get("/trechos.csv")
def trechos_csv(slug: str, filtro: str = Query("todos", pattern="^(todos|concordam|discordam|pendente|erro|codificado)$"),
                codigo: str | None = None, busca: str | None = None, db: Session = Depends(get_db)):
    sel = _filtrar(list(db.scalars(select(CodificacaoTrecho).order_by(CodificacaoTrecho.id))), filtro, codigo, busca)
    rot = _rotulos(db)
    cab = ["id", "registro", "fonte", "fonte_rotulo", "documento", "pagina", "texto", "codigo_humano", "tema_humano",
           "codigo_llm", "concorda", "confianca", "justificativa_llm", "modelo", "status"]
    linhas = [[t.id, t.registro, t.fonte, t.fonte_rotulo, rot.get(t.documento_id), t.pagina, t.texto, t.codigo_humano,
               t.tema_humano, t.codigo_llm, {True: "sim", False: "não", None: ""}[_concordam(t)], t.confianca,
               t.justificativa_llm, t.modelo, t.status] for t in sel]
    return _csv("codificacao_trechos.csv", cab, linhas)


@router.post("/limpar-llm")
def limpar_codificacao_llm(slug: str, db: Session = Depends(get_db)):
    """Apaga a codificação do LLM (mantém a humana): todos os trechos voltam a ``pendente``."""
    if codificador.progresso(slug).get("rodando"):
        raise HTTPException(status_code=409, detail="Há uma codificação em andamento.")
    n = db.execute(update(CodificacaoTrecho).values(codigo_llm=None, justificativa_llm=None, confianca=None, modelo=None,
                                                    resposta_bruta=None, status="pendente")).rowcount
    db.commit()
    return {"trechos": n}


# ---------- codificação pelo LLM ----------

class CodificarIn(BaseModel):
    ids: list[int] | None = None
    limite: int | None = None
    apenas_pendentes: bool = True


@router.get("/estimativa")
def estimativa(slug: str, apenas_pendentes: bool = True, db: Session = Depends(get_db)):
    """Tamanho do lote, tokens aproximados e se o provedor é remoto (para o aviso de custo e privacidade)."""
    return {**codificador.estimativa(db, pasta_do_projeto(slug), apenas_pendentes), "nota_papel": NOTA_PAPEL}


def _erro_llm(exc: Exception):
    if isinstance(exc, codificador.LLMDesligado):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, codificador.SemCodebook):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ErroLLM):
        raise HTTPException(status_code=409 if exc.categoria == "config" else 502,
                            detail=config.ocultar(str(exc), config.ler_chave("anthropic"), config.ler_chave("openai_compativel")))
    raise exc


@router.post("/codificar", response_model=None)
def codificar(slug: str, response: Response, dados: CodificarIn | None = None, sincrono: bool = False,
              db: Session = Depends(get_db)):
    """Codifica os trechos com o LLM configurado (409 se o LLM estiver desligado ou sem codebook). Por padrão em segundo
    plano (202; acompanhe em /progresso); ``sincrono=1`` espera terminar (usado nos testes)."""
    d = dados or CodificarIn()
    if d.limite is not None and d.limite < 1:
        raise HTTPException(status_code=422, detail="limite deve ser >= 1.")
    pasta = pasta_do_projeto(slug)
    kw = {"ids": d.ids, "limite": d.limite, "apenas_pendentes": d.apenas_pendentes}
    try:
        if sincrono:
            if codificador.progresso(slug).get("rodando"):
                raise HTTPException(status_code=409, detail="Já existe uma codificação em andamento neste projeto.")
            return codificador.executar(slug, lambda: sessao_do_projeto(slug), pasta, **kw)
        r = codificador.iniciar(slug, lambda: sessao_do_projeto(slug), pasta, **kw)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (codificador.LLMDesligado, codificador.SemCodebook, ErroLLM) as exc:
        _erro_llm(exc)
    response.status_code = 202
    return r


@router.get("/progresso")
def progresso(slug: str, _db: Session = Depends(get_db)):
    return codificador.progresso(slug)


@router.post("/cancelar")
def cancelar(slug: str, _db: Session = Depends(get_db)):
    return {"cancelando": codificador.cancelar(slug)}


# ---------- concordância ----------

_TEMA = re.compile(r"^\s*(T\d+)\b", re.IGNORECASE)


def _tema_de(valor: str | None) -> str | None:
    if valor is None:
        return None
    m = _TEMA.match(valor)
    return m.group(1).upper() if m else valor.strip()


def pares(db: Session, pasta, nivel: str) -> tuple[list, list, dict]:
    """(humano, llm) por trecho com código humano; LLM sem resposta válida = faltante (None)."""
    trechos = [t for t in db.scalars(select(CodificacaoTrecho).order_by(CodificacaoTrecho.id)) if t.codigo_humano]
    if nivel == "codigo":
        return [t.codigo_humano for t in trechos], [t.codigo_llm for t in trechos], {"trechos": len(trechos)}
    # tema de cada código: o mais frequente na codificação humana importada (o codebook pode marcar códigos como
    # "Emergente" que a planilha põe num tema T1-T5); sem uso humano, o tema do codebook. O mesmo mapa vale para os
    # dois codificadores, então só há discordância de tema quando os códigos caem em temas diferentes.
    tema_do_codigo = {c["id"]: _tema_de(c.get("tema")) for c in codificador.codebook(pasta)}
    usos: dict[str, Counter] = {}
    for t in trechos:
        if t.tema_humano:
            usos.setdefault(t.codigo_humano, Counter())[_tema_de(t.tema_humano)] += 1
    tema_do_codigo.update({c: cont.most_common(1)[0][0] for c, cont in usos.items()})
    h = [_tema_de(t.tema_humano) or tema_do_codigo.get(t.codigo_humano) for t in trechos]
    l = [None if t.codigo_llm is None else (codificador.NENHUM if t.codigo_llm == codificador.NENHUM
                                            else tema_do_codigo.get(t.codigo_llm, t.codigo_llm)) for t in trechos]
    return h, l, {"trechos": len(trechos)}


def _arred(x, casas=4):
    if isinstance(x, float):
        return round(x, casas)
    if isinstance(x, dict):
        return {k: _arred(v, casas) for k, v in x.items()}
    if isinstance(x, list):
        return [_arred(v, casas) for v in x]
    return x


@router.get("/concordancia")
def concordancia(slug: str, nivel: str = Query("codigo", pattern="^(codigo|tema)$"), bootstrap: int = Query(1000, ge=0, le=10000),
                 semente: int = 42, db: Session = Depends(get_db)):
    """Percentual, kappa de Cohen (IC assintótico e bootstrap), alfa de Krippendorff nominal (IC bootstrap), por código
    (kappa um-contra-o-resto, precisão, revocação, F1) e matriz de confusão, sobre os trechos com código humano e
    resposta válida do LLM."""
    h, l, info = pares(db, pasta_do_projeto(slug), nivel)
    if not any(x is not None for x in l):
        raise HTTPException(status_code=409, detail="Nenhum trecho codificado pelo LLM ainda: rode a codificação primeiro.")
    r = estatisticas.resumo(h, l, bootstrap=bootstrap, semente=semente)
    return _arred({"nivel": nivel, **info, "faltantes_llm": sum(x is None for x in l), **r, "nota": NOTA_PAPEL,
                   "faixas": {"kappa": "Landis & Koch (1977)", "alfa": "Krippendorff: >= 0,800 confiável; >= 0,667 provisório"}})


@router.get("/concordancia.csv")
def concordancia_csv(slug: str, nivel: str = Query("codigo", pattern="^(codigo|tema)$"), db: Session = Depends(get_db)):
    h, l, _ = pares(db, pasta_do_projeto(slug), nivel)
    if not any(x is not None for x in l):
        raise HTTPException(status_code=409, detail="Nenhum trecho codificado pelo LLM ainda.")
    linhas = [[c["codigo"], c["suporte_humano"], c["atribuidos_llm"], c["vp"], c["fp"], c["fn"], c["kappa"], c["precisao"],
               c["revocacao"], c["f1"]] for c in estatisticas.por_codigo(*estatisticas._presentes(h, l))]
    return _csv(f"concordancia_por_{nivel}.csv",
                [nivel, "suporte_humano", "atribuidos_llm", "vp", "fp", "fn", "kappa", "precisao", "revocacao", "f1"], linhas)
