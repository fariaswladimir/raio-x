"""Frente 16 - Metadados (16.4), planilha do corpus (16.1), extração por LLM (16.2) e exportação para o bibliometrix (16.3).

Tudo sob ``/api/projetos/{slug}``; a configuração do e-mail de contato da consulta online fica em ``/api/config/metadados``.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.models import Documento
from app.services import parametros as svc_parametros
from app.services import ruido as svc_ruido
from app.services.analises import dados as svc_dados
from app.services.corpus import bibtex as svc_bib
from app.services.corpus import llm_partes as svc_llm
from app.services.corpus import metadados as M
from app.services.corpus import online as svc_online
from app.services.corpus import partes as P
from app.services.corpus import planilha as svc_planilha
from app.services.corpus import projeto as svc_projeto
from app.services.llm.provedores import ErroLLM
from app.services.llm import config as cfg_llm

router = APIRouter(prefix="/api/projetos/{slug}", tags=["corpus"])
router_config = APIRouter(prefix="/api/config/metadados", tags=["corpus"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _doc_ou_404(db: Session, documento_id: int) -> Documento:
    doc = db.get(Documento, documento_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não existe.")
    return doc


# ---------- configuração da consulta online ----------

class ConfigMetadadosIn(BaseModel):
    email_contato: str = ""


@router_config.get("")
def ler_config_metadados():
    c = svc_online.carregar_config()
    return {**c, "configurado": bool(c["email_contato"]), "aviso_privacidade": svc_online.AVISO_PRIVACIDADE}


@router_config.put("")
def salvar_config_metadados(corpo: ConfigMetadadosIn):
    try:
        c = svc_online.salvar_config(corpo.email_contato)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**c, "configurado": bool(c["email_contato"]), "aviso_privacidade": svc_online.AVISO_PRIVACIDADE}


# ---------- 16.4 metadados ----------

@router.get("/metadados")
def metadados(slug: str, db: Session = Depends(get_db)):
    pasta = pasta_do_projeto(slug)
    linhas = svc_projeto.tabela(db, pasta)
    dados = M.carregar(pasta)
    cfg = svc_online.carregar_config()
    return {"documentos": linhas, "cobertura": svc_projeto.cobertura(linhas), "indice": dados.get("indice"),
            "campos": [{"chave": c, "rotulo": M.ROTULOS[c], "lista": c in M.CAMPOS_LISTA} for c in M.CAMPOS],
            "online": {"email_configurado": bool(cfg["email_contato"]), "aviso_privacidade": svc_online.AVISO_PRIVACIDADE}}


@router.get("/metadados/conflitos")
def conflitos(slug: str, db: Session = Depends(get_db)):
    return {"conflitos": M.conflitos(M.carregar(pasta_do_projeto(slug)))}


@router.post("/metadados/extrair")
def extrair_metadados(slug: str, online: bool = Query(False, description="Consulta também Crossref/OpenAlex pelo DOI (desligado por padrão)"),
                      fonte: str = Query("crossref", pattern="^(crossref|openalex|ambos)$"), db: Session = Depends(get_db)):
    """Extrai os metadados das primeiras páginas de cada documento (origem ``texto``). Com ``online=true``, consulta também o DOI
    (exige e-mail de contato configurado; 409 sem ele)."""
    pasta = pasta_do_projeto(slug)
    if online and not svc_online.carregar_config()["email_contato"]:
        raise HTTPException(status_code=409, detail="Configure um e-mail de contato (Crossref/OpenAlex) antes de usar a consulta online.")
    r = svc_projeto.extrair_textos(db, pasta)
    if online:
        fontes = ("crossref", "openalex") if fonte == "ambos" else (fonte,)
        r["online"] = svc_projeto.consultar_online(db, pasta, fontes)
    linhas = svc_projeto.tabela(db, pasta)
    return {**r, "cobertura": svc_projeto.cobertura(linhas)}


class OnlineIn(BaseModel):
    fonte: str = Field("crossref", pattern="^(crossref|openalex|ambos)$")
    documento_ids: list[int] | None = None


@router.post("/metadados/consultar-online")
def consultar_online(slug: str, corpo: OnlineIn | None = None, db: Session = Depends(get_db)):
    corpo = corpo or OnlineIn()
    fontes = ("crossref", "openalex") if corpo.fonte == "ambos" else (corpo.fonte,)
    try:
        return svc_projeto.consultar_online(db, pasta_do_projeto(slug), fontes, corpo.documento_ids)
    except svc_online.SemEmail as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/metadados/importar-indice")
async def importar_indice(slug: str, request: Request, nome: str | None = None, db: Session = Depends(get_db)):
    """Recebe o CSV do índice (corpo bruto), casa com os documentos pelo nome do arquivo e guarda os campos (origem ``indice``).
    A coluna de trilha vira só uma **sugestão** de grupo (``sugestoes_de_grupo``); nada é aplicado sozinho."""
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    try:
        return svc_projeto.importar_indice(db, pasta_do_projeto(slug), conteudo, nome)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class GruposIn(BaseModel):
    documento_ids: list[int] | None = None


@router.post("/metadados/grupos/confirmar")
def confirmar_grupos(slug: str, corpo: GruposIn | None = None, db: Session = Depends(get_db)):
    """Aplica a sugestão de grupo do índice aos documentos escolhidos (ou a todos, sem ``documento_ids``). Ação explícita do usuário."""
    return svc_projeto.aplicar_grupos(db, pasta_do_projeto(slug), corpo.documento_ids if corpo else None)


@router.patch("/metadados/{documento_id}")
def editar_metadados(slug: str, documento_id: int, alteracoes: dict, db: Session = Depends(get_db)):
    """Edição manual: ``{"titulo": "...", "autores": ["Sobrenome, N", ...] | "A; B", "ano": 2024, ...}``. Valor vazio remove a edição."""
    doc = _doc_ou_404(db, documento_id)
    pasta = pasta_do_projeto(slug)
    dados = M.carregar(pasta)
    try:
        res = M.editar_manual(dados, doc.arquivo, alteracoes)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    M.salvar(pasta, dados)
    return {"documento_id": documento_id, "arquivo": doc.arquivo, "campos": res}


# ---------- 16.1 planilha do corpus ----------

@router.get("/corpus/planilha")
def planilha_corpus(slug: str, db: Session = Depends(get_db)):
    """Tabela da planilha (mesmas colunas do .xlsx) + cobertura por parte (seção / padrão / LLM / não encontrado)."""
    return svc_planilha.montar(db, pasta_do_projeto(slug))


@router.get("/corpus/planilha/celula")
def celula_da_planilha(slug: str, documento_id: int, parte: str, db: Session = Depends(get_db)):
    """Trechos da célula (documento x parte) com página, seção, regra, método, nota e o link do contexto ampliado (KWIC)."""
    if parte not in P.CHAVES:
        raise HTTPException(status_code=404, detail=f"Parte inexistente. Use: {', '.join(P.CHAVES)}.")
    _doc_ou_404(db, documento_id)
    r = svc_planilha.celula(db, pasta_do_projeto(slug), documento_id, parte)
    if r is None:
        raise HTTPException(status_code=404, detail="Documento sem texto processado: execute o pipeline.")
    return r


@router.get("/exportar/planilha-corpus.xlsx")
def planilha_corpus_xlsx(slug: str, db: Session = Depends(get_db)):
    pasta = pasta_do_projeto(slug)
    dados = svc_planilha.montar(db, pasta)
    if not dados["linhas"]:
        raise HTTPException(status_code=409, detail="Nenhum documento processado: execute o pipeline primeiro.")
    return Response(content=svc_planilha.gerar_xlsx(dados, db, pasta), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="planilha-corpus.xlsx"'})


# ---------- 16.2 LLM ----------

class ExtrairLLMIn(BaseModel):
    documento_ids: list[int] | None = None
    partes: list[str] | None = None


@router.post("/corpus/planilha/llm/extrair")
def extrair_com_llm(slug: str, corpo: ExtrairLLMIn | None = None, db: Session = Depends(get_db)):
    """Pede ao LLM (Frente 14) as partes vazias/fracas; cada frase é conferida contra o texto; só entram sugestões que existem no documento."""
    corpo = corpo or ExtrairLLMIn()
    if not cfg_llm.carregar()["habilitado"]:
        raise HTTPException(status_code=409, detail="A extração com LLM está desligada: ligue \"Permitir geração com LLM\" em Configurações.")
    pasta = pasta_do_projeto(slug)
    params = svc_planilha.parametros_planilha(pasta)
    excluir = svc_ruido.excluir_ruido(svc_parametros.carregar(pasta))
    resultados, erros = [], []
    for doc in svc_projeto.documentos_ativos(db):
        if corpo.documento_ids is not None and doc.id not in corpo.documento_ids:
            continue
        analise = svc_planilha.analise_do_documento(pasta, doc.id, params, excluir)
        blocos = svc_dados.carregar_blocos(pasta, doc.id)
        if analise is None or blocos is None:
            continue
        frases = P.frases_elegiveis(pasta, doc.id, excluir)
        try:
            resultados.append(svc_llm.extrair_documento(pasta, doc.arquivo, doc.id, analise, blocos, frases or [], corpo.partes))
        except svc_llm.LLMDesligado as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ErroLLM as exc:
            erros.append({"documento_id": doc.id, "erro": cfg_llm.ocultar(str(exc), cfg_llm.ler_chave("anthropic"), cfg_llm.ler_chave("openai_compativel"))})
            if exc.categoria in ("config", "conexao", "autenticacao"):
                break
    return {"documentos": resultados, "erros": erros, "sugestoes": sum(r["sugestoes"] for r in resultados)}


class DecisaoIn(BaseModel):
    acao: str = Field(..., pattern="^(aceitar|rejeitar|limpar)$")
    indices: list[int] | None = None


@router.post("/corpus/planilha/llm/{documento_id}/{parte}")
def decidir_sugestao(slug: str, documento_id: int, parte: str, corpo: DecisaoIn, db: Session = Depends(get_db)):
    """Aceita (entra no .xlsx), rejeita ou devolve a "sugerida" as sugestões de LLM de uma célula."""
    doc = _doc_ou_404(db, documento_id)
    if parte not in P.CHAVES:
        raise HTTPException(status_code=404, detail="Parte inexistente.")
    try:
        lista = svc_llm.decidir(pasta_do_projeto(slug), doc.arquivo, parte, corpo.acao, corpo.indices)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))
    return {"sugestoes": lista}


# ---------- 16.3 bibliometrix ----------

@router.get("/exportar/bibliometrix.bib")
def bibliometrix_bib(slug: str, escape: str = Query("completo", pattern="^(completo|minimo)$"),
                     palavras_indexadas: str = Query("omitir", pattern="^(omitir|copiar)$"), db: Session = Depends(get_db)):
    """BibTeX no padrão Scopus para ``bibliometrix::convert2df(file, dbsource = "scopus", format = "bibtex")`` (UTF-8)."""
    pasta = pasta_do_projeto(slug)
    entradas = svc_bib.montar_entradas(db, pasta, palavras_indexadas)
    if not entradas:
        raise HTTPException(status_code=409, detail="Nenhum documento processado: execute o pipeline primeiro.")
    texto = svc_bib.para_bibtex(entradas, escape)
    return Response(content=texto.encode("utf-8"), media_type="application/x-bibtex; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="bibliometrix.bib"'})


@router.get("/corpus/referencias")
def resumo_das_referencias(slug: str, db: Session = Depends(get_db)):
    """Quantas referências citadas foram separadas e interpretadas em cada documento (conferência do .bib)."""
    entradas = svc_bib.montar_entradas(db, pasta_do_projeto(slug))
    return {"documentos": [{"documento_id": e["documento_id"], "arquivo": e["arquivo"], "referencias": e["n_referencias"],
                            "interpretadas": e["referencias_interpretadas"]} for e in entradas]}
