"""Frente 17 - Coleta guiada por protocolo: protocolo (17.1), coleta automática (17.2), revisão, exportação e concordância (17.3).

Tudo sob ``/api/projetos/{slug}/coleta``. Regras e formatos: ``app/services/coleta/`` (docstrings de ``protocolo.py``, ``motor.py``, ``llm_coleta.py``,
``trabalho.py``, ``revisao.py``, ``exportacao.py`` e ``concordancia_coleta.py``).
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services import execucao_bg
from app.services.coleta import concordancia_coleta as CC
from app.services.coleta import exportacao as EX
from app.services.coleta import modelos as MO
from app.services.coleta import protocolo as PR
from app.services.coleta import revisao as RV
from app.services.coleta import trabalho as TR
from app.services.corpus import partes as P
from app.services.llm import config as cfg_llm
from app.services.llm.provedores import ErroLLM

router = APIRouter(prefix="/api/projetos/{slug}/coleta", tags=["coleta"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _422(exc: PR.ProtocoloInvalido):
    raise HTTPException(status_code=422, detail={"mensagem": "Protocolo com erro: " + PR.resumo_erros(exc.erros), "erros": exc.erros})


# ---------- 17.1 protocolo ----------

class ProtocoloIn(BaseModel):
    itens: list[dict] = Field(..., max_length=500)
    nome: str | None = None


@router.get("/protocolo")
def ler_protocolo(slug: str, db: Session = Depends(get_db)):
    p = PR.carregar(pasta_do_projeto(slug))
    return {**p, "tipos": [{"id": t, "rotulo": PR.ROTULO_TIPO[t]} for t in PR.TIPOS], "secoes": list(PR.SECOES_VALIDAS),
            "partes_planilha": [{"chave": k, "rotulo": r} for k, r, _m, _t in P.PARTES], "regra_frases": PR.regra_das_frases()}


@router.put("/protocolo")
def salvar_protocolo(slug: str, corpo: ProtocoloIn, db: Session = Depends(get_db)):
    """Valida (definição com no máximo 2 frases etc.) e grava; conteúdo diferente sobe a versão. 422 com ``detail.erros`` (e sugestão de corte) se houver erro."""
    try:
        return PR.salvar(pasta_do_projeto(slug), corpo.itens, corpo.nome)
    except PR.ProtocoloInvalido as exc:
        _422(exc)


@router.post("/protocolo/validar")
def validar_protocolo(slug: str, corpo: ProtocoloIn, db: Session = Depends(get_db)):
    itens, problemas = PR.validar_itens(corpo.itens)
    return {"itens": itens, "problemas": problemas, "erros": PR.so_erros(problemas), "avisos": [p for p in problemas if p["gravidade"] == "aviso"]}


@router.get("/protocolo/regra-frases")
def regra_frases(slug: str, db: Session = Depends(get_db)):
    return PR.regra_das_frases()


@router.get("/protocolo/modelos")
def listar_modelos(slug: str, db: Session = Depends(get_db)):
    return {"modelos": MO.listar()}


@router.get("/protocolo/modelos/{modelo_id}")
def ver_modelo(slug: str, modelo_id: str, db: Session = Depends(get_db)):
    try:
        return MO.obter(modelo_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))


def _combinar(atual: list[dict], novos: list[dict], modo: str) -> list[dict]:
    if modo == "substituir":
        return novos
    por_id = {i["id"]: k for k, i in enumerate(atual)}
    saida = list(atual)
    for n in novos:
        if n["id"] in por_id:
            saida[por_id[n["id"]]] = n
        else:
            saida.append(n)
    return saida


@router.post("/protocolo/modelos/{modelo_id}/carregar")
def carregar_modelo(slug: str, modelo_id: str, aplicar: bool = Query(False, description="Grava no projeto (nova versão); senão só devolve os itens para a tela"),
                    modo: Literal["substituir", "anexar"] = "substituir", db: Session = Depends(get_db)):
    try:
        m = MO.obter(modelo_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))
    pasta = pasta_do_projeto(slug)
    itens = _combinar(PR.carregar(pasta)["itens"], m["itens"], modo)
    if not aplicar:
        return {"modelo": m["nome"], "itens": itens, "aplicado": False}
    try:
        p = PR.salvar(pasta, itens, m["nome"] if modo == "substituir" else None, modelo_origem=modelo_id)
    except PR.ProtocoloInvalido as exc:
        _422(exc)
    return {"modelo": m["nome"], "aplicado": True, **p}


@router.post("/protocolo/importar")
async def importar_protocolo(slug: str, request: Request, formato: Literal["auto", "csv", "xlsx", "markdown"] = "auto", nome: str | None = None,
                             aplicar: bool = Query(False, description="Grava no projeto se não houver nenhum erro"), modo: Literal["substituir", "anexar"] = "substituir",
                             db: Session = Depends(get_db)):
    """Corpo bruto = arquivo CSV/XLSX/Markdown. Devolve os itens normalizados e os problemas (definição com mais de 2 frases vem com sugestão de corte)."""
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    try:
        r = PR.importar(conteudo, formato, nome)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    r["aplicado"] = False
    if aplicar:
        if r["erros"]:
            raise HTTPException(status_code=422, detail={"mensagem": "Importação com erro: " + PR.resumo_erros(r["erros"]), "erros": r["erros"]})
        pasta = pasta_do_projeto(slug)
        try:
            p = PR.salvar(pasta, _combinar(PR.carregar(pasta)["itens"], r["itens"], modo), None)
        except PR.ProtocoloInvalido as exc:
            _422(exc)
        r.update({"aplicado": True, "versao_protocolo": p["versao_protocolo"]})
    return r


@router.get("/protocolo/exportar.csv")
def exportar_protocolo_csv(slug: str, db: Session = Depends(get_db)):
    itens = PR.carregar(pasta_do_projeto(slug))["itens"]
    return Response(content=PR.exportar_csv(itens), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="protocolo_coleta.csv"'})


@router.get("/protocolo/exportar.xlsx")
def exportar_protocolo_xlsx(slug: str, db: Session = Depends(get_db)):
    itens = PR.carregar(pasta_do_projeto(slug))["itens"]
    return Response(content=PR.exportar_xlsx(itens), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="protocolo_coleta.xlsx"'})


@router.get("/protocolo/historico")
def historico(slug: str, db: Session = Depends(get_db)):
    return {"versoes": PR.listar_historico(pasta_do_projeto(slug))}


@router.get("/protocolo/historico/{versao}")
def ver_versao(slug: str, versao: int, db: Session = Depends(get_db)):
    try:
        return PR.ler_versao(pasta_do_projeto(slug), versao)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))


@router.post("/protocolo/historico/{versao}/restaurar")
def restaurar_versao(slug: str, versao: int, db: Session = Depends(get_db)):
    try:
        return PR.restaurar(pasta_do_projeto(slug), versao)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))
    except PR.ProtocoloInvalido as exc:
        _422(exc)


# ---------- 17.2 coleta ----------

class ExecutarIn(BaseModel):
    documento_ids: list[int] | None = None
    item_ids: list[str] | None = None
    llm: Literal["desligado", "faltantes", "todos"] = "desligado"
    forcar: bool = Field(False, description="Recalcula tudo (menos as células decididas pelo revisor)")
    itens_por_chamada: int | None = Field(None, ge=1, le=10)


def _preparar(slug: str, corpo: ExecutarIn) -> dict:
    pasta = pasta_do_projeto(slug)
    if not PR.carregar(pasta)["itens"]:
        raise HTTPException(status_code=409, detail="O protocolo de coleta está vazio: crie ou carregue um modelo antes de executar.")
    if corpo.llm != "desligado" and not cfg_llm.carregar()["habilitado"]:
        raise HTTPException(status_code=409, detail="A coleta com LLM está desligada: ligue \"Permitir geração com LLM\" em Configurações.")
    if execucao_bg.esta_rodando(slug) or TR.esta_rodando(slug):
        raise HTTPException(status_code=409, detail="Já existe uma execução em andamento neste projeto.")
    return corpo.model_dump(exclude_none=True)


def _executar(slug: str, corpo: ExecutarIn, sincrono: bool, db: Session, response: Response):
    opcoes = _preparar(slug, corpo)
    if sincrono:
        try:
            return TR.executar(db, pasta_do_projeto(slug), opcoes)
        except TR.LLMDesligado as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ErroLLM as exc:
            raise HTTPException(status_code=502, detail=cfg_llm.ocultar(str(exc), cfg_llm.ler_chave("anthropic"), cfg_llm.ler_chave("openai_compativel")))
    try:
        iniciada = TR.iniciar(slug, opcoes)
    except TR.ExecucaoEmAndamento:
        raise HTTPException(status_code=409, detail="Já existe uma coleta em andamento neste projeto.")
    response.status_code = 202
    return iniciada


@router.post("/executar", response_model=None)
def executar(slug: str, response: Response, corpo: ExecutarIn | None = None, sincrono: bool = False, db: Session = Depends(get_db)):
    """Coleta por regras (e, com ``llm`` ligado, também pelo LLM). Em segundo plano por padrão (202 + ``run_id``; acompanhe em ``/coleta/progresso``);
    ``?sincrono=1`` espera e devolve o resumo. Incremental: só recalcula células cujo documento ou item mudou; nunca sobrescreve células decididas."""
    return _executar(slug, corpo or ExecutarIn(), sincrono, db, response)


@router.post("/llm/executar", response_model=None)
def executar_com_llm(slug: str, response: Response, corpo: ExecutarIn | None = None, sincrono: bool = False, db: Session = Depends(get_db)):
    """Como ``/executar`` com o LLM (padrão: ``faltantes``). 409 se "Permitir geração com LLM" está desligado."""
    corpo = corpo or ExecutarIn()
    if corpo.llm == "desligado":
        corpo = corpo.model_copy(update={"llm": "faltantes"})
    return _executar(slug, corpo, sincrono, db, response)


@router.get("/progresso")
def progresso(slug: str, db: Session = Depends(get_db)):
    return TR.progresso(slug)


# ---------- 17.3 revisão ----------

@router.get("/matriz")
def matriz(slug: str, status: str | None = None, item: str | None = None, grupo: str | None = None, db: Session = Depends(get_db)):
    return RV.matriz(db, pasta_do_projeto(slug), status, item, grupo)


@router.get("/celula")
def celula(slug: str, documento_id: int, item: str, db: Session = Depends(get_db)):
    try:
        return RV.detalhe(db, pasta_do_projeto(slug), documento_id, item)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class DecisaoIn(BaseModel):
    documento_id: int
    item: str
    acao: Literal["aceitar", "editar", "rejeitar", "nao_se_aplica", "desfazer"]
    valor: str | float | int | list[str] | None = None
    nota: str | None = None


@router.post("/celula/decidir")
def decidir_celula(slug: str, corpo: DecisaoIn, db: Session = Depends(get_db)):
    try:
        return RV.decidir(db, pasta_do_projeto(slug), corpo.documento_id, corpo.item, corpo.acao, corpo.valor, corpo.nota)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class LoteIn(BaseModel):
    acao: Literal["aceitar", "rejeitar"] = "aceitar"
    item: str | None = None
    documento_id: int | None = None
    min_confianca: float | None = Field(None, ge=0, le=1)


@router.post("/decidir-lote")
def decidir_lote(slug: str, corpo: LoteIn, db: Session = Depends(get_db)):
    """Aceita (ou rejeita) todas as células **sugeridas** de um item ou de um documento; ambíguas e sem valor ficam de fora."""
    try:
        return RV.decidir_lote(db, pasta_do_projeto(slug), corpo.acao, corpo.item, corpo.documento_id, corpo.min_confianca)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------- exportação ----------

@router.get("/exportar")
def exportar(slug: str, formato: Literal["larga", "longa"] = "larga", extensao: Literal["xlsx", "csv"] = "xlsx", versao: Literal["final", "auditoria"] = "final",
             db: Session = Depends(get_db)):
    """Larga (uma linha por documento, valor + evidência por item) ou longa (documento x item x trecho); ``final`` = só aceitos/editados; ``auditoria`` = tudo."""
    pasta = pasta_do_projeto(slug)
    if not PR.carregar(pasta)["itens"]:
        raise HTTPException(status_code=409, detail="O protocolo de coleta está vazio.")
    nome = f"coleta_{formato}_{versao}.{extensao}"
    if extensao == "xlsx":
        return Response(content=EX.gerar_xlsx(db, pasta, formato, versao), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{nome}"'})
    return Response(content=EX.gerar_csv(db, pasta, formato, versao), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


class MlrIn(BaseModel):
    planilha_referencia: str | None = Field(None, description="Caminho da planilha de coleta do usuário (só leitura)")
    aba: str | None = None
    incluir_duplicados: bool = True
    itens: list[str] | None = None


@router.post("/exportar/mlr")
def exportar_para_mlr(slug: str, corpo: MlrIn | None = None, db: Session = Depends(get_db)):
    """Envia os trechos das células aceitas/editadas à planilha de coleta da MLR (9.5): arquivo novo, duplicatas marcadas contra a planilha do usuário."""
    from app.routers.coleta_mlr import MEDIA_XLSX
    from app.services.concordancia.importacao import PlanilhaInvalida

    corpo = corpo or MlrIn()
    try:
        conteudo, resumo = EX.enviar_para_mlr(db, pasta_do_projeto(slug), corpo.planilha_referencia, corpo.aba, corpo.incluir_duplicados, corpo.itens)
    except (PlanilhaInvalida, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(content=conteudo, media_type=MEDIA_XLSX, headers={
        "Content-Disposition": f'attachment; filename="coleta_raiox_{slug}.xlsx"',
        "X-Raiox-Resumo": json.dumps({k: v for k, v in resumo.items() if k != "duplicados"}, ensure_ascii=True)})


# ---------- concordância ----------

@router.post("/concordancia/segundo-codificador")
async def importar_segundo_codificador(slug: str, request: Request, nome: str | None = None, codificador: str | None = None, db: Session = Depends(get_db)):
    """Corpo bruto = CSV/XLSX com uma linha por documento e uma coluna por item (cabeçalho = id do item)."""
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    try:
        return CC.importar_segundo(db, pasta_do_projeto(slug), conteudo, nome, codificador)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/concordancia/segundo-codificador")
def remover_segundo_codificador(slug: str, db: Session = Depends(get_db)):
    return {"removido": CC.remover_segundo(pasta_do_projeto(slug))}


@router.get("/concordancia")
def concordancia(slug: str, fonte: Literal["revisao", "segundo"] = "revisao", bandas: str | None = Query(None, description="Cortes crescentes para faixas de números: 100,500,1000"),
                 db: Session = Depends(get_db)):
    try:
        cortes = [float(x.replace(",", ".")) for x in bandas.split(";" if ";" in bandas else ",") if x.strip()] if bandas else None
    except ValueError:
        raise HTTPException(status_code=422, detail="Faixas inválidas: use números separados por vírgula (ex.: 100,500,1000).")
    try:
        return CC.calcular(db, pasta_do_projeto(slug), fonte, cortes)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
