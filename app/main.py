from app import offline

offline.aplicar_ambiente()  # 11.2: antes de qualquer import que possa carregar Hugging Face/Docling

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import FRONTEND_DIR, SISTEMA, VERSAO
from app.routers import analises, comentarios, dicionario, documentos, exportacao, laudo, llm, metodologia, pipeline, projetos, vocabulario
from app.routers import codificacao as rotas_codificacao
from app.routers import corpus as rotas_corpus
from app.routers import topicos as rotas_topicos
from app.routers import analises_documento as rotas_documento_extra
from app.routers import estilometria as rotas_estilometria
from app.routers import lote_t1 as rotas_lote_t1
from app.routers import busca as rotas_busca
from app.routers import classificacao as rotas_classificacao
from app.routers import coleta_protocolo as rotas_coleta_protocolo
import app.services.etapas  # noqa: F401  (registra as etapas do pipeline)

# Não há banco global: cada projeto cria o próprio projeto.sqlite sob demanda
# (ver app/database.py). Quando o schema estabilizar, trocar create_all por Alembic.

app = FastAPI(
    title="Raio-X — API",
    description="Análise textual local de corpus. Frentes 1-8: fundação, conversão/qualidade, limpeza, linguística, raio-x descritivo/comparativo e comentários por regra com revisão.",
    version=VERSAO,
)

app.include_router(projetos.router)
app.include_router(pipeline.router)
app.include_router(documentos.router)
app.include_router(vocabulario.router)
app.include_router(analises.router)
app.include_router(rotas_topicos.router)
app.include_router(rotas_documento_extra.router)
app.include_router(rotas_estilometria.router)
app.include_router(dicionario.router)
app.include_router(comentarios.router)
app.include_router(exportacao.router)
app.include_router(laudo.router)
app.include_router(llm.router_config)
app.include_router(llm.router)
app.include_router(metodologia.router)
app.include_router(rotas_codificacao.router)
app.include_router(rotas_corpus.router)
app.include_router(rotas_corpus.router_config)
app.include_router(rotas_classificacao.router)  # 15.11
app.include_router(rotas_coleta_protocolo.router)  # 17 coleta guiada por protocolo
app.include_router(rotas_busca.router)  # 15.12/15.13
app.include_router(rotas_busca.router_config)  # preços do LLM
for _r in rotas_lote_t1.ROUTERS:
    app.include_router(_r)


@app.get("/api")
def raiz():
    return {"status": "ok", "sistema": SISTEMA, "versao": VERSAO, "offline": offline.modo_offline()}


@app.get("/api/offline")
def estado_offline():
    """Estado do modo offline (11.2): selo na tela e diagnóstico."""
    return offline.estado()


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
