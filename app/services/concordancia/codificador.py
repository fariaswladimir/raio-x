"""15.1 - LLM como **segundo codificador** (checagem de confiabilidade, não substituto do humano).

- Usa o provedor da Frente 14 (``llm.provedores.provedor_configurado``); recusa se o LLM estiver desligado
  (``LLMDesligado`` -> 409 na API) ou se o projeto não tiver codebook (dicionário 6.4 vazio).
- **Às cegas:** o pedido leva só o codebook (código, rótulo, tema, regra de aplicação) e o trecho original. O código
  e o tema humanos, a tradução, a fonte e a página nunca são enviados.
- Resposta pedida em JSON ``{"codigo": "<código>" | "nenhum", "justificativa": "...", "confianca": 0-1}``; a leitura é
  tolerante (JSON dentro de texto/markdown, aspas simples, confiança em % ou por extenso, código citado no texto).
  Código fora do codebook vira erro de formato (status ``erro``), sem adivinhação.
- Lote em segundo plano, um trecho por vez, com progresso (feitos/total/erros) e cancelamento; cada chamada vai para
  ``saidas/llm_log.jsonl`` (provedor, modelo, uso de tokens, hash do pedido), como na 14.3.
"""
import datetime
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from sqlalchemy import select

from app.models import CodificacaoTrecho
from app.services import dicionario as svc_dic
from app.services.llm import cache_prompt, config, precos
from app.services.llm.provedores import ErroLLM, provedor_configurado

NENHUM = "nenhum"
VERSAO_PROMPT = "codificacao-v2"  # v2: codebook no system (em cache), trecho no usuário
ARQUIVO_LOG = "llm_log.jsonl"

SYSTEM = (
    "Você é um segundo codificador independente numa análise qualitativa de conteúdo. Sua tarefa é aplicar um codebook "
    "a um trecho de texto, seguindo as regras de aplicação de cada código. Escolha exatamente UM código do codebook, o "
    "que melhor se aplica ao trecho, ou \"nenhum\" se nenhum código se aplicar. Não invente códigos. Responda SOMENTE "
    "com um objeto JSON, sem texto antes ou depois, no formato: "
    "{\"codigo\": \"<código do codebook ou nenhum>\", \"justificativa\": \"<uma ou duas frases em português>\", "
    "\"confianca\": <número entre 0 e 1>}"
)


class LLMDesligado(Exception):
    pass


class SemCodebook(Exception):
    pass


def codebook(pasta: Path) -> list[dict]:
    return [c for c in svc_dic.carregar(pasta)["categorias"]]


def texto_codebook(cats: list[dict]) -> str:
    """Codebook em texto determinístico (ordenado por código, ordem natural): faz parte do prefixo em cache."""
    linhas = []
    for c in sorted(cats, key=lambda c: cache_prompt.chave_natural(c["id"])):
        tema = " ".join(x for x in (c.get("tema"), c.get("tema_nome")) if x)
        regra = " ".join((c.get("descricao") or "").split())
        linhas.append(f"- {c['id']} | {c.get('nome') or c['id']} | tema: {tema or '-'} | regra de aplicação: {regra or '-'}")
    return "\n".join(linhas)


def montar_system(cats: list[dict]) -> list[dict]:
    """Prefixo estável (instruções + codebook) em blocos, com ponto de cache no último: idêntico para todos os trechos."""
    return cache_prompt.blocos_system(SYSTEM, "CODEBOOK (código | rótulo | tema | regra de aplicação):\n" + texto_codebook(cats))


def montar_usuario(texto: str) -> str:
    """Parte variável (só o trecho), depois do ponto de cache."""
    return ('TRECHO A CODIFICAR:\n"""\n' + texto.strip() + '\n"""\n\nResponda só com o JSON pedido.')


# ---------- leitura robusta da resposta ----------

def _objetos_json(texto: str) -> list[str]:
    """Trechos {...} balanceados do texto (na ordem), ignorando chaves dentro de strings."""
    saida, pilha, ini, em_str, escape = [], 0, None, False, False
    for i, ch in enumerate(texto):
        if em_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                em_str = False
            continue
        if ch == '"' and pilha:
            em_str = True
        elif ch == "{":
            if pilha == 0:
                ini = i
            pilha += 1
        elif ch == "}" and pilha:
            pilha -= 1
            if pilha == 0:
                saida.append(texto[ini:i + 1])
    return saida


_PALAVRAS_CONF = {"muito alta": 0.95, "alta": 0.85, "media": 0.6, "média": 0.6, "moderada": 0.6, "baixa": 0.3, "muito baixa": 0.1,
                  "high": 0.85, "medium": 0.6, "low": 0.3}


def _confianca(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        s = str(v).strip().lower()
        if s in _PALAVRAS_CONF:
            return _PALAVRAS_CONF[s]
        m = re.search(r"-?\d+(?:[.,]\d+)?", s)
        if not m:
            return None
        x = float(m.group().replace(",", "."))
        if "%" in s:
            x /= 100
    if x > 1 and x <= 100:
        x /= 100
    return min(1.0, max(0.0, x))


def _normalizar_codigo(bruto, validos: dict[str, str]) -> str | None:
    if bruto is None:
        return None
    s = str(bruto).strip().strip("\"'`").strip()
    if s.lower() in (NENHUM, "none", "nenhum código", "nenhum codigo", "n/a", "null", ""):
        return NENHUM
    if s.lower() in validos:
        return validos[s.lower()]
    # "C1.1 - IA como cofundador" ou "Código C1.1"
    for tok in re.findall(r"[A-Za-z]*\d+(?:\.\d+)*[A-Za-z]?", s):
        if tok.lower() in validos:
            return validos[tok.lower()]
    return None


def interpretar(resposta: str, codigos: list[str]) -> dict:
    """{codigo, justificativa, confianca, ok, erro}. ``codigo`` é um dos ``codigos``, "nenhum" ou None (erro)."""
    validos = {c.lower(): c for c in codigos}
    dados = None
    for bloco in _objetos_json(resposta or ""):
        for tentativa in (bloco, bloco.replace("'", '"')):
            try:
                d = json.loads(tentativa)
            except ValueError:
                continue
            if isinstance(d, dict):
                dados = {str(k).lower(): v for k, v in d.items()}
                break
        if dados is not None:
            break
    if dados is not None:
        bruto = dados.get("codigo", dados.get("código", dados.get("code")))
        cod = _normalizar_codigo(bruto, validos)
        just = dados.get("justificativa", dados.get("justification", dados.get("motivo")))
        conf = _confianca(dados.get("confianca", dados.get("confiança", dados.get("confidence"))))
        if cod is None:
            return {"codigo": None, "justificativa": str(just or "")[:2000], "confianca": conf, "ok": False,
                    "erro": f"Código fora do codebook: {bruto!r}."}
        return {"codigo": cod, "justificativa": str(just or "")[:2000], "confianca": conf, "ok": True, "erro": None}
    # sem JSON: procura "codigo: X" e, por fim, um único código do codebook citado no texto
    m = re.search(r"c[oó]digo\"?\s*[:=]\s*\"?([^\"\n,}]+)", resposta or "", re.IGNORECASE)
    cod = _normalizar_codigo(m.group(1), validos) if m else None
    if cod is None:
        citados = {validos[t.lower()] for t in re.findall(r"[A-Za-z]*\d+(?:\.\d+)*[A-Za-z]?", resposta or "") if t.lower() in validos}
        if len(citados) == 1:
            cod = citados.pop()
    if cod is None:
        return {"codigo": None, "justificativa": None, "confianca": None, "ok": False,
                "erro": "Resposta sem JSON e sem um código do codebook reconhecível."}
    mc = re.search(r"confian[cç]a\"?\s*[:=]\s*\"?([^\"\n,}]+)", resposta, re.IGNORECASE)
    return {"codigo": cod, "justificativa": (resposta or "").strip()[:2000], "confianca": _confianca(mc.group(1)) if mc else None,
            "ok": True, "erro": None}


# ---------- estimativa, log e lote ----------

def estimativa(db, pasta: Path, apenas_pendentes: bool = True) -> dict:
    cats = codebook(pasta)
    trechos = _selecionar(db, None, apenas_pendentes)
    cfg = config.carregar()
    prefixo = cache_prompt.tokens_aprox(cache_prompt.system_como_texto(montar_system(cats)))
    var = (sum(cache_prompt.tokens_aprox(montar_usuario(t.texto)) for t in trechos) / len(trechos)) if trechos else 0
    modelo = cfg["anthropic"]["modelo"] if cfg["provedor"] == "anthropic" else None
    custo = precos.estimar(modelo, len(trechos), prefixo, var, 80) if modelo else None
    return {"trechos": len(trechos), "categorias": len(cats),
            "tokens_entrada_aprox": int(len(trechos) * (prefixo + var)),
            "tokens_saida_aprox": 80 * len(trechos), "prefixo_tokens_aprox": prefixo, "custo": custo,
            "provedor": cfg["provedor"], "habilitado": cfg["habilitado"],
            "remoto": cfg["provedor"] in ("anthropic", "openai_compativel"),
            "nota": "Estimativa grosseira (~4 caracteres por token). Provedores remotos cobram por token e recebem os trechos."}


def _registrar_log(pasta: Path, linha: dict) -> None:
    saidas = pasta / "saidas"
    saidas.mkdir(parents=True, exist_ok=True)
    with (saidas / ARQUIVO_LOG).open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def _selecionar(db, ids: list[int] | None, apenas_pendentes: bool, limite: int | None = None) -> list[CodificacaoTrecho]:
    q = select(CodificacaoTrecho).order_by(CodificacaoTrecho.id)
    if ids:
        q = q.where(CodificacaoTrecho.id.in_(ids))
    if apenas_pendentes:
        q = q.where(CodificacaoTrecho.status != "codificado")
    if limite:
        q = q.limit(limite)
    return list(db.scalars(q))


def codificar_trecho(db, pasta: Path, t: CodificacaoTrecho, cats: list[dict], prov, cfg: dict, system=None) -> dict:
    system = system or montar_system(cats)
    user = montar_usuario(t.texto)
    texto_system = cache_prompt.system_como_texto(system)
    h = hashlib.sha256((texto_system + "\n" + user).encode("utf-8")).hexdigest()[:16]
    base = {"em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "analise": "codificacao",
            "trecho_id": t.id, "provedor": cfg["provedor"], "prompt_hash": h, "versao_prompt": VERSAO_PROMPT}
    try:
        resp = prov.gerar(system, user)
    except ErroLLM as exc:
        t.status, t.codigo_llm, t.justificativa_llm, t.confianca = "erro", None, f"Erro do provedor: {exc}", None
        db.commit()
        _registrar_log(pasta, {**base, "erro": str(exc), "categoria": exc.categoria})
        return {"ok": False, "erro": str(exc), "categoria": exc.categoria}
    r = interpretar(resp["texto"], [c["id"] for c in cats])
    t.modelo = str(resp.get("modelo") or "")[:200]
    t.resposta_bruta = resp["texto"][:4000]
    t.confianca = r["confianca"]
    if r["ok"]:
        t.status, t.codigo_llm, t.justificativa_llm = "codificado", r["codigo"], r["justificativa"]
    else:
        t.status, t.codigo_llm, t.justificativa_llm = "erro", None, r["erro"]
    db.commit()
    _registrar_log(pasta, {**base, "modelo": resp.get("modelo"), "uso": resp.get("uso") or {}, "request_id": resp.get("request_id"),
                           **precos.anotar_uso(resp.get("modelo"), resp.get("uso"), cache_prompt.tokens_aprox(texto_system)),
                           "ok": r["ok"], "segundos": resp.get("segundos")})
    return r


_ESTADO: dict[str, dict] = {}
_TRAVA = threading.Lock()


def progresso(slug: str) -> dict:
    with _TRAVA:
        e = dict(_ESTADO.get(slug) or {"rodando": False, "feitos": 0, "total": 0, "erros": 0})
    e.pop("cancelar", None)
    return e


def cancelar(slug: str) -> bool:
    with _TRAVA:
        e = _ESTADO.get(slug)
        if e and e.get("rodando"):
            e["cancelar"] = True
            return True
    return False


def _preparar(db, pasta: Path, provedor=None):
    cfg = config.carregar()
    if not cfg["habilitado"]:
        raise LLMDesligado("O uso de LLM está desligado: ligue \"Permitir geração com LLM\" em Configurações.")
    cats = codebook(pasta)
    if not cats:
        raise SemCodebook("O projeto não tem codebook: importe a planilha com a aba Codebook ou preencha o dicionário.")
    return cfg, cats, provedor or provedor_configurado(cfg)


def executar(slug: str, sessao_factory, pasta: Path, ids: list[int] | None = None, limite: int | None = None,
             apenas_pendentes: bool = True, provedor=None) -> dict:
    """Codifica os trechos selecionados (síncrono). Levanta LLMDesligado/SemCodebook/ErroLLM (provedor mal configurado)."""
    db = sessao_factory()
    try:
        cfg, cats, prov = _preparar(db, pasta, provedor)
        trechos = _selecionar(db, ids, apenas_pendentes, limite)
        with _TRAVA:
            _ESTADO[slug] = {"rodando": True, "feitos": 0, "total": len(trechos), "erros": 0, "cancelado": False,
                             "iniciado_em": datetime.datetime.now().isoformat(timespec="seconds"), "finalizado_em": None,
                             "provedor": cfg["provedor"], "ultimo_erro": None}
        inicio = time.time()
        system = montar_system(cats)  # prefixo estável, montado uma vez: byte a byte igual em todas as chamadas
        for t in trechos:
            with _TRAVA:
                if _ESTADO[slug].get("cancelar"):
                    _ESTADO[slug]["cancelado"] = True
                    break
            r = codificar_trecho(db, pasta, t, cats, prov, cfg, system)
            with _TRAVA:
                _ESTADO[slug]["feitos"] += 1
                if not r["ok"]:
                    _ESTADO[slug]["erros"] += 1
                    _ESTADO[slug]["ultimo_erro"] = r.get("erro")
        with _TRAVA:
            _ESTADO[slug].update(rodando=False, finalizado_em=datetime.datetime.now().isoformat(timespec="seconds"),
                                 segundos=round(time.time() - inicio, 1))
            return {k: v for k, v in _ESTADO[slug].items() if k != "cancelar"}
    except Exception as exc:
        with _TRAVA:
            if slug in _ESTADO and _ESTADO[slug].get("rodando"):
                _ESTADO[slug].update(rodando=False, erro=str(exc))
        raise
    finally:
        db.close()


def iniciar(slug: str, sessao_factory, pasta: Path, **kw) -> dict:
    """Valida (LLM ligado, codebook) e roda ``executar`` numa thread. Levanta RuntimeError se já houver lote rodando."""
    with _TRAVA:
        if (_ESTADO.get(slug) or {}).get("rodando"):
            raise RuntimeError("Já existe uma codificação em andamento neste projeto.")
    db = sessao_factory()
    try:
        _preparar(db, pasta, kw.get("provedor"))
        n = len(_selecionar(db, kw.get("ids"), kw.get("apenas_pendentes", True), kw.get("limite")))
    finally:
        db.close()
    with _TRAVA:
        _ESTADO[slug] = {"rodando": True, "feitos": 0, "total": n, "erros": 0}

    def alvo():
        try:
            executar(slug, sessao_factory, pasta, **kw)
        except Exception as exc:  # erro já registrado no estado
            with _TRAVA:
                _ESTADO.setdefault(slug, {}).update(rodando=False, erro=str(exc))

    threading.Thread(target=alvo, name=f"codificacao-{slug}", daemon=True).start()
    return {"iniciado": True, "total": n}
