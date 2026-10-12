"""15.13 - "Perguntar ao corpus": recuperação (BM25; híbrido BM25 + cosseno por RRF quando há embeddings) e, se o LLM
estiver ligado, resposta que só pode citar os trechos recuperados como (rótulo, p. N), conferida por ``verificar``.

- Sem LLM (padrão): devolve só os trechos recuperados, com documento e página.
- Com LLM: a resposta é gerada, conferida (números, citações, trechos entre aspas) e **mostrada com avisos** se falhar;
  nunca se responde sem trechos (sem resultado de busca não há chamada ao modelo).
- Cada consulta vai para ``saidas/busca_log.jsonl`` (pergunta, modo, ids recuperados, modelo, uso, conferência).
"""
import datetime
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from app.services.busca import bm25, embeddings
from app.services.busca import corpus as busca_corpus
from app.services.llm import config, precos
from app.services.llm.gerador import motivos_da_verificacao, verificar
from app.services.llm.provedores import ErroLLM, provedor_configurado

ARQUIVO_LOG = "busca_log.jsonl"
MAX_TRECHO_CHARS = 900
VERSAO_PROMPT = "rag-v1"

SYSTEM = (
    "Você responde perguntas sobre um corpus de documentos usando SOMENTE os trechos numerados fornecidos, que vêm "
    "com o rótulo do documento e a página. Regras: (1) cada afirmação deve terminar com a citação no formato "
    "(rótulo, p. N), copiando o rótulo e a página exatamente do cabeçalho do trecho que a sustenta; (2) não use "
    "conhecimento externo nem trechos não fornecidos; (3) não invente números nem aspas: se citar, copie literalmente "
    "do trecho; (4) se os trechos não bastarem, diga apenas que não há base suficiente nos trechos recuperados. "
    "Responda em português, em no máximo um parágrafo curto."
)


class LLMDesligado(Exception):
    pass


def _registrar_log(pasta: Path, linha: dict) -> None:
    saidas = pasta / "saidas"
    saidas.mkdir(parents=True, exist_ok=True)
    with (saidas / ARQUIVO_LOG).open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def ler_log(pasta: Path, limite: int = 50) -> list[dict]:
    caminho = pasta / "saidas" / ARQUIVO_LOG
    if not caminho.is_file():
        return []
    linhas = [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
    return linhas[-limite:][::-1]


def recuperar(db, pasta: Path, consulta: str, k: int = 8, modo: str = "auto", modelo_embedding: str | None = None,
              embed_consulta=None) -> dict:
    """Top-``k`` segmentos. ``modo``: ``bm25``, ``hibrido`` (exige embeddings) ou ``auto`` (híbrido se houver).

    ``embed_consulta(texto) -> vetor`` pode ser injetada (testes); por padrão usa o Ollama configurado.
    """
    segs, indice = busca_corpus.segmentos_e_indice(db, pasta)
    base = {"consulta": consulta, "k": k, "segmentos_no_corpus": len(segs)}
    if not segs:
        return {**base, "modo": "bm25", "itens": [], "aviso": "O projeto não tem segmentos: execute o pipeline primeiro."}
    lexical = indice.ranking(consulta, k=max(k * 5, 50))
    emb = None
    if modo in ("hibrido", "auto"):
        calc = embeddings.listar_calculados(pasta)
        escolha = next((m for m in calc if m["modelo"] == modelo_embedding), None) if modelo_embedding else (calc[0] if calc else None)
        if escolha:
            emb = embeddings.carregar(pasta, escolha["modelo"])
            if emb and emb[1]["ids"] != [s["id"] for s in segs]:
                emb = None  # segmentos mudaram depois do cálculo: recalcule
    if modo == "hibrido" and not emb:
        raise embeddings.ErroEmbeddings("Não há embeddings atualizados para este projeto: calcule-os em Similaridade semântica.", "sem_dados")
    usado = "bm25"
    itens = []
    if emb:
        matriz, meta = emb
        try:
            if embed_consulta is not None:
                vq = np.asarray(embed_consulta(consulta), dtype=np.float32)
                vq = vq / (np.linalg.norm(vq) or 1.0)
            else:
                cfg = config.carregar()
                vq = embeddings.embed_ollama(cfg["ollama"]["base_url"], meta["modelo"], [consulta], "consulta")[0]
            semantico = embeddings.mais_proximos(matriz, vq, k=max(k * 5, 50))
            fundido = bm25.rrf([[i for i, _ in lexical], [i for i, _ in semantico]])
            nota_lex, nota_sem = dict(lexical), dict(semantico)
            for i, nota in fundido[:k * 4]:
                itens.append({"indice": i, "nota": nota, "bm25": nota_lex.get(i), "cosseno": nota_sem.get(i)})
            usado = "hibrido"
        except embeddings.ErroEmbeddings:
            if modo == "hibrido":
                raise
            emb = None  # Ollama fora do ar: cai para BM25 e avisa
    if usado == "bm25":
        itens = [{"indice": i, "nota": n, "bm25": n, "cosseno": None} for i, n in lexical[:k * 4]]
    saida = []
    vistos: dict[str, dict] = {}
    for it in itens:
        s = segs[it["indice"]]
        chave = " ".join(s["texto"].split()).casefold()
        if chave in vistos:  # mesmo texto em outro documento (cópia/versão do mesmo trabalho): colapsa e avisa
            vistos[chave]["tambem_em"].append({"rotulo": s["rotulo"], "pagina": s["pagina"]})
            continue
        if len(saida) >= k:
            continue
        item = {"posicao": len(saida) + 1, "id": s["id"], "documento_id": s["documento_id"], "rotulo": s["rotulo"], "pagina": s["pagina"],
                "secao": s.get("secao"), "texto": s["texto"], "nota": round(it["nota"], 6),
                "bm25": None if it["bm25"] is None else round(it["bm25"], 4),
                "cosseno": None if it["cosseno"] is None else round(it["cosseno"], 4), "tambem_em": []}
        vistos[chave] = item
        saida.append(item)
    aviso = None
    if modo == "auto" and usado == "bm25" and embeddings.listar_calculados(pasta):
        aviso = "Há embeddings, mas não puderam ser usados (Ollama fora do ar ou segmentos mudaram): busca só lexical."
    return {**base, "modo": usado, "itens": saida, "aviso": aviso}


def montar_usuario(pergunta: str, itens: list[dict]) -> str:
    blocos = []
    for it in itens:
        cab = f"[{it['posicao']}] ({it['rotulo']}, p. {it['pagina']})" if it.get("pagina") is not None else f"[{it['posicao']}] ({it['rotulo']})"
        extra = "".join(f" | mesmo texto em ({o['rotulo']}, p. {o['pagina']})" for o in it.get("tambem_em", []) if o.get("pagina") is not None)
        blocos.append(cab + extra + "\n" + it["texto"][:MAX_TRECHO_CHARS])
    return f"PERGUNTA: {pergunta.strip()}\n\nTRECHOS RECUPERADOS:\n\n" + "\n\n".join(blocos) + "\n\nResponda citando só estes trechos."


def conferir_resposta(texto: str, itens: list[dict]) -> dict:
    """``verificar`` com os trechos recuperados como evidências + regra extra: precisa ter ao menos uma citação válida."""
    evid = [{"rotulo": it["rotulo"], "pagina": it["pagina"], "trecho": it["texto"]} for it in itens if it.get("pagina") is not None]
    evid += [{"rotulo": o["rotulo"], "pagina": o["pagina"], "trecho": it["texto"]} for it in itens for o in it.get("tambem_em", [])
             if o.get("pagina") is not None]  # o mesmo texto em outro documento também é citável
    v = verificar(texto, {"trechos": [it["texto"] for it in itens]}, evid)
    usadas = []
    validas = {(" ".join(e["rotulo"].split()).casefold(), int(e["pagina"])) for e in evid}
    for m in re.finditer(r"\(([^()]*\bp\.[^()]*)\)", texto):
        for parte in m.group(1).split(";"):
            c = re.match(r"^\s*(.+?),\s*p\.\s*(\d+)\s*$", parte)
            if c and (" ".join(c.group(1).split()).casefold(), int(c.group(2))) in validas:
                usadas.append(f"{c.group(1).strip()}, p. {c.group(2)}")
    v["citacoes_validas"] = list(dict.fromkeys(usadas))
    v["sem_citacao"] = not usadas
    if v["sem_citacao"]:
        v["ok"] = False
    return v


def perguntar(db, pasta: Path, pergunta: str, k: int = 8, modo: str = "auto", responder: bool = False,
              provedor=None, modelo_embedding: str | None = None, embed_consulta=None) -> dict:
    """Recupera e, se ``responder`` e o LLM estiver ligado, gera a resposta com citações conferidas."""
    pergunta = (pergunta or "").strip()
    if not pergunta:
        raise ValueError("Escreva uma pergunta.")
    cfg = config.carregar()
    if responder and (not cfg["habilitado"] or cfg["provedor"] == "nenhum") and provedor is None:
        raise LLMDesligado("O LLM está desligado: ligue em Configurações para gerar respostas (a busca funciona sem ele).")
    ret = recuperar(db, pasta, pergunta, k=k, modo=modo, modelo_embedding=modelo_embedding, embed_consulta=embed_consulta)
    base_log = {"em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "analise": "perguntar_ao_corpus",
                "pergunta": pergunta, "modo": ret["modo"], "ids": [it["id"] for it in ret["itens"]], "versao_prompt": VERSAO_PROMPT}
    resposta = None
    if responder and ret["itens"]:
        user = montar_usuario(pergunta, ret["itens"])
        prov = provedor or provedor_configurado(cfg)
        try:
            r = prov.gerar(SYSTEM, user)
        except ErroLLM as exc:
            _registrar_log(pasta, {**base_log, "erro": str(exc), "categoria": exc.categoria})
            raise
        texto = r["texto"].strip()
        ver = conferir_resposta(texto, ret["itens"])
        resposta = {"texto": texto, "modelo": r.get("modelo"), "provedor": prov.nome, "uso": r.get("uso") or {},
                    "verificacao": ver, "avisos": ([motivos_da_verificacao(ver)] if motivos_da_verificacao(ver) else [])
                    + (["A resposta não cita nenhum trecho recuperado: não use sem conferir."] if ver["sem_citacao"] else [])}
        _registrar_log(pasta, {**base_log, "provedor": prov.nome, "modelo": r.get("modelo"), "uso": r.get("uso") or {},
                               **precos.anotar_uso(r.get("modelo"), r.get("uso")), "verificacao_ok": ver["ok"],
                               "prompt_hash": hashlib.sha256((SYSTEM + "\n" + user).encode("utf-8")).hexdigest()[:16]})
    else:
        _registrar_log(pasta, {**base_log, "provedor": None, "resposta": False})
    return {**ret, "resposta": resposta,
            "nota": "As respostas só citam trechos recuperados; confira sempre a página. Sem trechos, não há resposta."}
