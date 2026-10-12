"""15.12 (embeddings via Ollama, similaridade semântica) e 15.13 ("Perguntar ao corpus", RAG com citação de página).

Também expõe a tabela de preços editável do LLM (``/api/config/llm/precos``, item 0).
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto, sessao_do_projeto
from app.services.busca import embeddings, rag
from app.services.analises.dados import documentos_do_corpus
from app.services.llm import config, precos
from app.services.llm.provedores import ErroLLM

router = APIRouter(prefix="/api/projetos/{slug}", tags=["busca"])
router_config = APIRouter(prefix="/api/config/llm", tags=["llm"])


# ---------- preços ----------

@router_config.get("/precos")
def ler_precos():
    return {"modelos": precos.tabela(), "unidade": "US$ por milhão de tokens", "escrita_cache": f"{precos.MULT_ESCRITA_CACHE}x a entrada",
            "arquivo": str(precos._arquivo()), "nota": "Edite via PUT ou no arquivo; a leitura do cache e o mínimo de tokens variam por modelo."}


@router_config.put("/precos")
def gravar_precos(dados: dict = Body(...)):
    try:
        return {"modelos": precos.salvar(dados)}
    except config.ConfigInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------- 15.12 embeddings ----------

def _ollama_url() -> str:
    return config.carregar()["ollama"]["base_url"]


@router.get("/semantica/status")
def status_semantica(slug: str, db: Session = Depends(get_db)):
    """Ollama no ar? modelos de embeddings instalados? embeddings já calculados? (Só com o provedor Ollama.)"""
    cfg = config.carregar()
    st = embeddings.status_ollama(cfg["ollama"]["base_url"])
    return {**st, "provedor_ollama": cfg["provedor"] == "ollama", "modelo_chat": cfg["ollama"]["modelo"],
            "documentos": [{"id": m["id"], "rotulo": m["rotulo"]} for m in documentos_do_corpus(db, pasta_do_projeto(slug))],
            "calculados": embeddings.listar_calculados(pasta_do_projeto(slug)), "progresso": embeddings.progresso(slug),
            "nota": "Roda só no Ollama local; nenhum texto sai da máquina."}


class CalcularIn(BaseModel):
    modelo: str
    forcar: bool = False


@router.post("/semantica/calcular", status_code=202)
def calcular_semantica(slug: str, dados: CalcularIn, db: Session = Depends(get_db)):
    cfg = config.carregar()
    if cfg["provedor"] != "ollama":
        raise HTTPException(status_code=409, detail="Os embeddings só funcionam com o provedor Ollama (local): escolha-o em Configurações. "
                                                    + embeddings.COMO_HABILITAR)
    st = embeddings.status_ollama(cfg["ollama"]["base_url"])
    if not st["disponivel"]:
        raise HTTPException(status_code=409, detail=st["erro"] + " " + embeddings.COMO_HABILITAR)
    if dados.modelo not in st["modelos"]:
        raise HTTPException(status_code=409, detail=f"O modelo '{dados.modelo}' não está instalado no Ollama. " + embeddings.COMO_HABILITAR)
    try:
        embeddings.iniciar(lambda: sessao_do_projeto(slug), slug, pasta_do_projeto(slug), dados.modelo, cfg["ollama"]["base_url"], dados.forcar)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"iniciado": True}


@router.get("/semantica/progresso")
def progresso_semantica(slug: str, _db: Session = Depends(get_db)):
    return embeddings.progresso(slug)


@router.post("/semantica/cancelar")
def cancelar_semantica(slug: str, _db: Session = Depends(get_db)):
    return {"cancelando": embeddings.cancelar(slug)}


def _carregados(slug: str, modelo: str | None):
    pasta = pasta_do_projeto(slug)
    calc = embeddings.listar_calculados(pasta)
    escolha = next((m for m in calc if m["modelo"] == modelo), None) if modelo else (calc[0] if calc else None)
    if not escolha:
        raise HTTPException(status_code=409, detail="Nenhum embedding calculado para este projeto. " + embeddings.COMO_HABILITAR)
    matriz, meta = embeddings.carregar(pasta, escolha["modelo"])
    return pasta, matriz, meta


@router.get("/semantica/similaridade")
def similaridade_semantica(slug: str, documento_id: int | None = None, modelo: str | None = None, k: int = 10,
                           db: Session = Depends(get_db)):
    """Cosseno entre documentos (média dos embeddings dos segmentos). Com ``documento_id``: vizinhos desse documento;
    sem: os pares mais parecidos do corpus."""
    pasta, matriz, meta = _carregados(slug, modelo)
    ids, sim = embeddings.similaridade_documentos(matriz, meta)
    rot = {m["id"]: m["rotulo"] for m in documentos_do_corpus(db, pasta)}
    base = {"modelo": meta["modelo"], "documentos": len(ids), "segmentos": meta["n"], "dim": meta["dim"],
            "metodo": "cosseno entre a média (renormalizada) dos embeddings dos segmentos de cada documento"}
    if documento_id is not None:
        if documento_id not in ids:
            raise HTTPException(status_code=404, detail="Documento sem embeddings.")
        i = ids.index(documento_id)
        viz = sorted((j for j in range(len(ids)) if j != i), key=lambda j: (-float(sim[i, j]), ids[j]))[:k]
        return {**base, "documento_id": documento_id, "rotulo": rot.get(documento_id),
                "vizinhos": [{"documento_id": ids[j], "rotulo": rot.get(ids[j]), "similaridade": round(float(sim[i, j]), 4)} for j in viz]}
    pares = [(float(sim[i, j]), ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    pares.sort(key=lambda p: (-p[0], p[1], p[2]))
    return {**base, "pares": [{"a": a, "rotulo_a": rot.get(a), "b": b, "rotulo_b": rot.get(b), "similaridade": round(s, 4)}
                              for s, a, b in pares[:k]]}


@router.get("/semantica/segmentos")
def segmentos_proximos(slug: str, consulta: str, modelo: str | None = None, k: int = 10, db: Session = Depends(get_db)):
    """Segmentos mais próximos (cosseno) de um texto de consulta, com documento e página."""
    pasta, matriz, meta = _carregados(slug, modelo)
    try:
        vq = embeddings.embed_ollama(_ollama_url(), meta["modelo"], [consulta], "consulta")[0]
    except embeddings.ErroEmbeddings as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    from app.services.busca import corpus as busca_corpus
    segs, _ = busca_corpus.segmentos_e_indice(db, pasta)
    por_id = {s["id"]: s for s in segs}
    itens = []
    for i, nota in embeddings.mais_proximos(matriz, vq, k=k):
        s = por_id.get(meta["ids"][i])
        if s:
            itens.append({"id": s["id"], "rotulo": s["rotulo"], "pagina": s["pagina"], "texto": s["texto"], "cosseno": round(nota, 4)})
    return {"modelo": meta["modelo"], "consulta": consulta, "itens": itens}


# ---------- 15.13 perguntar ao corpus ----------

class PerguntarIn(BaseModel):
    pergunta: str
    k: int = 8
    modo: str = "auto"  # auto | bm25 | hibrido
    responder: bool = False  # gerar resposta com o LLM (exige LLM ligado)
    modelo_embedding: str | None = None


@router.post("/perguntar")
def perguntar(slug: str, dados: PerguntarIn, db: Session = Depends(get_db)):
    if dados.modo not in ("auto", "bm25", "hibrido"):
        raise HTTPException(status_code=422, detail="modo deve ser auto, bm25 ou hibrido.")
    if not 1 <= dados.k <= 30:
        raise HTTPException(status_code=422, detail="k deve estar entre 1 e 30.")
    try:
        return rag.perguntar(db, pasta_do_projeto(slug), dados.pergunta, k=dados.k, modo=dados.modo, responder=dados.responder,
                             modelo_embedding=dados.modelo_embedding)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except rag.LLMDesligado as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except embeddings.ErroEmbeddings as exc:
        raise HTTPException(status_code=409 if exc.categoria == "sem_dados" else 502, detail=str(exc))
    except ErroLLM as exc:
        raise HTTPException(status_code=409 if exc.categoria == "config" else 502,
                            detail=config.ocultar(str(exc), config.ler_chave("anthropic"), config.ler_chave("openai_compativel")))


@router.get("/perguntar/log")
def log_perguntas(slug: str, limite: int = 30, _db: Session = Depends(get_db)):
    return {"consultas": rag.ler_log(pasta_do_projeto(slug), limite)}
