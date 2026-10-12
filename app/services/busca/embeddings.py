"""15.12 - Embeddings opcionais via Ollama (nada sai da máquina).

- Só com o provedor **ollama** e um modelo de embeddings instalado (ex.: ``nomic-embed-text``, ``mxbai-embed-large``,
  ``bge-m3``). Usa ``POST /api/embed`` (Ollama >= 0.3: ``{"model", "input": [...]}`` -> ``{"embeddings": [[...]]}``) e,
  se o servidor for antigo (404), ``POST /api/embeddings`` (um texto por chamada, ``{"model", "prompt"}``).
- Vetores dos segmentos normalizados (L2) em ``cache/embeddings/<modelo>/segmentos.npy`` (float32) + ``meta.json``
  (ids dos segmentos, modelo, dimensão, assinatura dos textos). O vetor de um documento = média dos vetores dos seus
  segmentos, renormalizada. Similaridade = cosseno (produto interno de vetores unitários).
- ``nomic-embed-text`` pede prefixos de tarefa ("search_document: " / "search_query: "); são aplicados automaticamente.
- ``embed_fn(textos) -> matriz`` pode ser injetada (testes).
"""
import datetime
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import httpx
import numpy as np

from app.services.busca import corpus as busca_corpus

LOTE = 32
PADROES_EMBEDDING = ("embed", "bge", "minilm", "e5-", "gte-", "snowflake-arctic", "granite-embedding")
_ESTADO: dict[str, dict] = {}
_TRAVA = threading.Lock()


class ErroEmbeddings(Exception):
    def __init__(self, mensagem: str, categoria: str = "erro"):
        super().__init__(mensagem)
        self.categoria = categoria


COMO_HABILITAR = ("Para usar a similaridade semântica: (1) instale o Ollama (ollama.com); (2) rode `ollama pull nomic-embed-text` "
                  "(ou mxbai-embed-large); (3) em Configurações escolha o provedor Ollama; (4) calcule os embeddings aqui. "
                  "Tudo roda na sua máquina: nenhum texto é enviado para fora.")


def _cliente(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, trust_env=False)


def _eh_embedding(m: dict) -> bool:
    caps = m.get("capabilities")
    if isinstance(caps, list) and caps:
        return "embedding" in caps
    nome = str(m.get("name", "")).lower()
    return any(p in nome for p in PADROES_EMBEDDING)


def status_ollama(base_url: str) -> dict:
    """Ollama no ar? modelos de embeddings instalados? (Falha de conexão vira ``disponivel: False``.)"""
    base = (base_url or "http://127.0.0.1:11434").rstrip("/")
    try:
        with _cliente(5.0) as c:
            r = c.get(f"{base}/api/tags")
        r.raise_for_status()
        modelos = r.json().get("models", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"disponivel": False, "base_url": base, "modelos": [], "modelos_embedding": [],
                "erro": f"Não consegui falar com o Ollama em {base} ({type(exc).__name__}).", "como_habilitar": COMO_HABILITAR}
    nomes = sorted(m["name"] for m in modelos)
    emb = sorted(m["name"] for m in modelos if _eh_embedding(m))
    return {"disponivel": True, "base_url": base, "modelos": nomes, "modelos_embedding": emb, "erro": None,
            "como_habilitar": None if emb else COMO_HABILITAR}


def _prefixo(modelo: str, tarefa: str) -> str:
    if "nomic-embed-text" in modelo:
        return "search_query: " if tarefa == "consulta" else "search_document: "
    return ""


def embed_ollama(base_url: str, modelo: str, textos: list[str], tarefa: str = "documento") -> np.ndarray:
    """Matriz (n, d) float32 normalizada (L2) com os embeddings dos ``textos``."""
    base = (base_url or "http://127.0.0.1:11434").rstrip("/")
    pref = _prefixo(modelo, tarefa)
    entrada = [pref + t for t in textos]
    try:
        with _cliente(300.0) as c:
            r = c.post(f"{base}/api/embed", json={"model": modelo, "input": entrada})
            if r.status_code == 404 and not r.text.lstrip().startswith("{"):  # sem JSON = rota inexistente (Ollama antigo)
                vetores = []
                for t in entrada:  # Ollama antigo: /api/embeddings, um por chamada
                    r2 = c.post(f"{base}/api/embeddings", json={"model": modelo, "prompt": t})
                    r2.raise_for_status()
                    vetores.append(r2.json()["embedding"])
                return _normalizar(np.array(vetores, dtype=np.float32))
    except httpx.TimeoutException as exc:
        raise ErroEmbeddings("O Ollama demorou demais para responder.", "timeout") from exc
    except httpx.HTTPError as exc:
        raise ErroEmbeddings(f"Não consegui falar com o Ollama em {base}: ele está rodando? ({type(exc).__name__})", "conexao") from exc
    if r.status_code == 404:
        raise ErroEmbeddings(f"Modelo '{modelo}' não encontrado no Ollama (rode `ollama pull {modelo}`).", "modelo")
    if r.status_code >= 400:
        raise ErroEmbeddings(f"O Ollama respondeu com erro {r.status_code}: {r.text[:200]}", "erro")
    try:
        return _normalizar(np.array(r.json()["embeddings"], dtype=np.float32))
    except (KeyError, ValueError, TypeError) as exc:
        raise ErroEmbeddings("Resposta do Ollama fora do formato esperado (/api/embed).", "formato") from exc


def _normalizar(m: np.ndarray) -> np.ndarray:
    if m.ndim != 2:
        raise ErroEmbeddings("Embeddings com formato inesperado.", "formato")
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (m / n).astype(np.float32)


# ---------- armazenamento ----------

def _slug_modelo(modelo: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", modelo)


def pasta_embeddings(pasta_projeto: Path, modelo: str) -> Path:
    return pasta_projeto / "cache" / "embeddings" / _slug_modelo(modelo)


def _assinatura_textos(segs: list[dict]) -> str:
    h = hashlib.sha256()
    for s in segs:
        h.update(s["id"].encode())
        h.update(b"\0")
        h.update(s["texto"].encode("utf-8"))
        h.update(b"\1")
    return h.hexdigest()[:16]


def listar_calculados(pasta_projeto: Path) -> list[dict]:
    raiz = pasta_projeto / "cache" / "embeddings"
    saida = []
    if raiz.is_dir():
        for d in sorted(raiz.iterdir()):
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (d / "segmentos.npy").is_file():
                saida.append(meta)
    return saida


def carregar(pasta_projeto: Path, modelo: str) -> tuple[np.ndarray, dict] | None:
    d = pasta_embeddings(pasta_projeto, modelo)
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        return np.load(d / "segmentos.npy"), meta
    except (OSError, ValueError):
        return None


def calcular(db, pasta_projeto: Path, modelo: str, embed_fn=None, base_url: str | None = None, slug: str | None = None,
             forcar: bool = False) -> dict:
    """Calcula (ou reaproveita, se os segmentos não mudaram) os embeddings dos segmentos do corpus. Síncrono."""
    segs = busca_corpus.carregar_segmentos(db, pasta_projeto)
    if not segs:
        raise ErroEmbeddings("O projeto não tem segmentos: execute o pipeline (etapa de segmentos) primeiro.", "sem_dados")
    assinatura = _assinatura_textos(segs)
    ja = carregar(pasta_projeto, modelo)
    if ja and not forcar and ja[1].get("assinatura") == assinatura:
        return {**ja[1], "reaproveitado": True}
    embed_fn = embed_fn or (lambda ts: embed_ollama(base_url or "", modelo, ts, "documento"))
    chave = slug or str(pasta_projeto)
    with _TRAVA:
        _ESTADO[chave] = {"rodando": True, "feitos": 0, "total": len(segs), "modelo": modelo, "erro": None, "cancelar": False}
    inicio = time.time()
    partes = []
    try:
        for i in range(0, len(segs), LOTE):
            with _TRAVA:
                if _ESTADO[chave].get("cancelar"):
                    _ESTADO[chave].update(rodando=False, cancelado=True)
                    raise ErroEmbeddings("Cálculo cancelado.", "cancelado")
            partes.append(np.asarray(embed_fn([s["texto"] for s in segs[i:i + LOTE]]), dtype=np.float32))
            with _TRAVA:
                _ESTADO[chave]["feitos"] = min(len(segs), i + LOTE)
        matriz = _normalizar(np.vstack(partes))
    except Exception as exc:
        with _TRAVA:
            _ESTADO[chave].update(rodando=False, erro=str(exc))
        raise
    d = pasta_embeddings(pasta_projeto, modelo)
    d.mkdir(parents=True, exist_ok=True)
    np.save(d / "segmentos.npy", matriz)
    meta = {"modelo": modelo, "n": int(matriz.shape[0]), "dim": int(matriz.shape[1]), "ids": [s["id"] for s in segs],
            "assinatura": assinatura, "segundos": round(time.time() - inicio, 1),
            "criado_em": datetime.datetime.now().isoformat(timespec="seconds")}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    with _TRAVA:
        _ESTADO[chave].update(rodando=False, feitos=len(segs), finalizado_em=meta["criado_em"])
    return {**{k: v for k, v in meta.items() if k != "ids"}, "reaproveitado": False}


def iniciar(db_factory, slug: str, pasta_projeto: Path, modelo: str, base_url: str, forcar: bool = False) -> None:
    """Dispara ``calcular`` numa thread (a tela acompanha em ``progresso``)."""
    with _TRAVA:
        if (_ESTADO.get(slug) or {}).get("rodando"):
            raise RuntimeError("Já existe um cálculo de embeddings em andamento neste projeto.")
        _ESTADO[slug] = {"rodando": True, "feitos": 0, "total": 0, "modelo": modelo, "erro": None, "cancelar": False}

    def alvo():
        db = db_factory()
        try:
            calcular(db, pasta_projeto, modelo, base_url=base_url, slug=slug, forcar=forcar)
        except Exception as exc:  # noqa: BLE001 - o erro fica no estado para a tela
            with _TRAVA:
                _ESTADO.setdefault(slug, {}).update(rodando=False, erro=str(exc))
        finally:
            db.close()

    threading.Thread(target=alvo, name=f"embeddings-{slug}", daemon=True).start()


def progresso(slug: str) -> dict:
    with _TRAVA:
        e = dict(_ESTADO.get(slug) or {"rodando": False, "feitos": 0, "total": 0})
    e.pop("cancelar", None)
    return e


def cancelar(slug: str) -> bool:
    with _TRAVA:
        e = _ESTADO.get(slug)
        if e and e.get("rodando"):
            e["cancelar"] = True
            return True
    return False


# ---------- consultas ----------

def vetores_dos_documentos(matriz: np.ndarray, meta: dict) -> tuple[list[int], np.ndarray]:
    """(ids dos documentos, matriz (n_docs, d) das médias renormalizadas dos segmentos)."""
    docs: dict[int, list[int]] = {}
    for i, ident in enumerate(meta["ids"]):
        docs.setdefault(int(ident.split(":")[0]), []).append(i)
    ids = sorted(docs)
    medias = np.vstack([matriz[docs[d]].mean(axis=0) for d in ids])
    return ids, _normalizar(medias)


def similaridade_documentos(matriz: np.ndarray, meta: dict) -> tuple[list[int], np.ndarray]:
    ids, v = vetores_dos_documentos(matriz, meta)
    return ids, np.clip(v @ v.T, -1.0, 1.0)


def mais_proximos(matriz: np.ndarray, vetor: np.ndarray, k: int = 10, excluir: set[int] | None = None) -> list[tuple[int, float]]:
    """[(índice do segmento, cosseno)] dos ``k`` mais próximos de ``vetor`` (já normalizado). Empate: índice menor."""
    notas = matriz @ vetor
    ordem = sorted((i for i in range(len(notas)) if not excluir or i not in excluir), key=lambda i: (-float(notas[i]), i))
    return [(i, float(notas[i])) for i in ordem[:k]]
