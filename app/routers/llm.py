"""Frente 14 - LLM opcional: configuração global (14.1), modelos de parágrafo (14.2) e geração com LLM (14.3).

A configuração é global (fora dos projetos). A chave de API só entra por PUT e nunca volta: a API devolve só a máscara.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services import paragrafos
from app.services.exportar.comum import SemDados
from app.services.llm import config, gerador
from app.services.llm.provedores import ErroLLM, ProvedorOllama, provedor_configurado

router_config = APIRouter(prefix="/api/config/llm", tags=["llm"])
router = APIRouter(prefix="/api/projetos/{slug}", tags=["paragrafos"])

PROMPT_TESTE = ("Você é um assistente de teste de conexão.", "Responda apenas com a palavra: ok")


# ---------- 14.1 configuração ----------

class ConfigIn(BaseModel):
    habilitado: bool | None = None
    provedor: str | None = None
    ollama: dict | None = None
    anthropic: dict | None = None
    openai_compativel: dict | None = None
    chaves: dict[str, str] | None = Field(None, description="Chave por provedor; vazia mantém a guardada")
    remover_chaves: list[str] = []


@router_config.get("")
def ler_config():
    return config.como_publico()


@router_config.put("")
def gravar_config(dados: ConfigIn):
    try:
        for prov in dados.remover_chaves:
            if prov not in config.PROVEDORES_COM_CHAVE:
                raise config.ConfigInvalida(f"Provedor sem chave: {prov}.")
        config.salvar(dados.model_dump(exclude={"chaves", "remover_chaves"}, exclude_none=True))
        for prov, chave in (dados.chaves or {}).items():
            if prov not in config.PROVEDORES_COM_CHAVE:
                raise config.ConfigInvalida(f"Provedor sem chave: {prov}.")
            if chave and chave.strip():  # chave vazia = manter a guardada
                config.gravar_chave(prov, chave)
        for prov in dados.remover_chaves:
            config.remover_chave(prov)
    except config.ConfigInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return config.como_publico()


@router_config.post("/testar")
def testar_conexao():
    """Testa o provedor salvo com um pedido mínimo. Para o Ollama, devolve também os modelos instalados."""
    cfg = config.carregar()
    if cfg["provedor"] == "nenhum":
        raise HTTPException(status_code=409, detail="Nenhum provedor escolhido: selecione um e salve antes de testar.")
    chave = config.ler_chave(cfg["provedor"]) if cfg["provedor"] in config.PROVEDORES_COM_CHAVE else None
    inicio = time.time()
    resposta: dict = {"provedor": cfg["provedor"]}
    try:
        prov = provedor_configurado(cfg)
        if isinstance(prov, ProvedorOllama):
            resposta["modelos"] = prov.listar_modelos()
            if not prov.modelo:
                resposta.update(ok=True, mensagem=f"Ollama acessível: {len(resposta['modelos'])} modelo(s) instalado(s). Escolha um e salve.")
                resposta["latencia_ms"] = round((time.time() - inicio) * 1000)
                return resposta
        r = prov.gerar(*PROMPT_TESTE)
        resposta.update(ok=True, mensagem=f"Conexão ok com {r['modelo']}.", modelo=r["modelo"], uso=r.get("uso"))
    except ErroLLM as exc:
        resposta.update(ok=False, mensagem=config.ocultar(str(exc), chave), categoria=exc.categoria)
    resposta["latencia_ms"] = round((time.time() - inicio) * 1000)
    return resposta


# ---------- 14.2 modelos de parágrafo ----------

class ModelosIn(BaseModel):
    modelos: list[dict]


class GerarIn(BaseModel):
    instrucoes: str | None = Field(None, max_length=1000)


@router.get("/modelos-paragrafo")
def listar_modelos(slug: str, db: Session = Depends(get_db)):
    pasta = pasta_do_projeto(slug)
    try:
        modelos = paragrafos.listar(pasta)
    except paragrafos.ModeloInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"modelos": modelos, "analises": list(paragrafos.ANALISES_PARAGRAFO), "estilos": list(paragrafos.ESTILOS_SUGERIDOS),
            "campos": {a: list(c) for a, c in paragrafos.PLACEHOLDERS.items()}, "llm_habilitado": config.carregar()["habilitado"]}


@router.put("/modelos-paragrafo")
def salvar_modelos(slug: str, dados: ModelosIn, db: Session = Depends(get_db)):
    """Substitui a lista de modelos do projeto (os padrões não mudam). Lista vazia = volta aos padrões."""
    try:
        modelos = paragrafos.salvar_do_projeto(pasta_do_projeto(slug), dados.modelos)
    except paragrafos.ModeloInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"modelos": modelos}


def _modelo_ou_404(pasta, modelo_id: str) -> dict:
    try:
        return paragrafos.buscar(pasta, modelo_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Modelo de parágrafo '{modelo_id}' não encontrado.")
    except paragrafos.ModeloInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/modelos-paragrafo/{modelo_id}/previa")
def previa(slug: str, modelo_id: str, db: Session = Depends(get_db)):
    """Preenche o modelo com os dados atuais do projeto, SEM LLM (determinístico). Devolve o texto e as métricas usadas."""
    pasta = pasta_do_projeto(slug)
    modelo = _modelo_ou_404(pasta, modelo_id)
    try:
        dados = paragrafos.coletar(db, pasta, modelo["analise"])
        texto = paragrafos.preencher(modelo, dados["metricas"])
    except SemDados as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except paragrafos.AnaliseIndisponivel as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except paragrafos.ModeloInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    usados = {k: dados["metricas"][k] for k in sorted(paragrafos.campos_do_texto(modelo["texto_modelo"])) if k in dados["metricas"]}
    return {"modelo": modelo, "texto": texto, "metricas_usadas": usados, "evidencias": dados["evidencias"], "llm": False}


# ---------- 14.3 gerar com LLM ----------

@router.post("/modelos-paragrafo/{modelo_id}/gerar")
def gerar_com_llm(slug: str, modelo_id: str, dados: GerarIn | None = None, db: Session = Depends(get_db)):
    """Gera uma versão adaptada com o LLM configurado. Entra como comentário "sugerido" (ou "revisar") de origem LLM."""
    pasta = pasta_do_projeto(slug)
    _modelo_ou_404(pasta, modelo_id)
    try:
        return gerador.gerar_paragrafo(db, pasta, modelo_id, dados.instrucoes if dados else None)
    except gerador.LLMDesligado as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (SemDados, paragrafos.AnaliseIndisponivel) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ErroLLM as exc:
        raise HTTPException(status_code=502, detail=config.ocultar(str(exc), config.ler_chave("anthropic"), config.ler_chave("openai_compativel")))
