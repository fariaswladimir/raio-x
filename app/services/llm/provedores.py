"""14.1/14.3 - Um provedor por classe, todos com ``gerar(system, user) -> {texto, modelo, uso, request_id}``.

Sem tentativas extras além das do próprio SDK da Anthropic (``max_retries`` padrão). Erros viram ``ErroLLM`` com
mensagem amigável em português; a chave nunca entra na mensagem (``config.ocultar``).
"""
import time

import anthropic
import httpx

from app import offline
from app.services.llm import config
from app.services.llm.cache_prompt import system_como_texto

MAX_TOKENS = 16000
BETA_FALLBACK = "server-side-fallback-2026-07-01"
MODELOS_COM_FALLBACK = ("claude-opus-5-5", "claude-sonnet-5-5")  # Haiku 5.5 não tem fallback no servidor
TIMEOUT_NUVEM = 180.0
TIMEOUT_LOCAL = 600.0


class ErroLLM(Exception):
    """Falha ao falar com o provedor, em linguagem de usuário. ``categoria`` ajuda a tela e os testes."""

    def __init__(self, mensagem: str, categoria: str = "erro"):
        super().__init__(mensagem)
        self.categoria = categoria


# ---------- Ollama (local) ----------

class ProvedorOllama:
    nome = "ollama"

    def __init__(self, base_url: str, modelo: str):
        self.base = (base_url or "http://127.0.0.1:11434").rstrip("/")
        self.modelo = modelo

    def _cliente(self, timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout, trust_env=False)  # 127.0.0.1: ignora proxies do sistema

    def listar_modelos(self) -> list[str]:
        try:
            with self._cliente(10.0) as c:
                r = c.get(f"{self.base}/api/tags")
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        except httpx.HTTPError as exc:
            raise ErroLLM(f"Não consegui falar com o Ollama em {self.base}: ele está rodando? ({type(exc).__name__})", "conexao") from exc

    def gerar(self, system: str, user: str) -> dict:
        if not self.modelo:
            raise ErroLLM("Escolha um modelo do Ollama.", "config")
        corpo = {"model": self.modelo, "stream": False, "options": {"temperature": 0.2},
                 "messages": [{"role": "system", "content": system_como_texto(system)}, {"role": "user", "content": user}]}
        try:
            with self._cliente(TIMEOUT_LOCAL) as c:
                r = c.post(f"{self.base}/api/chat", json=corpo)
        except httpx.TimeoutException as exc:
            raise ErroLLM("O Ollama demorou demais para responder.", "timeout") from exc
        except httpx.HTTPError as exc:
            raise ErroLLM(f"Não consegui falar com o Ollama em {self.base}: ele está rodando? ({type(exc).__name__})", "conexao") from exc
        if r.status_code == 404:
            raise ErroLLM(f"Modelo '{self.modelo}' não encontrado no Ollama (rode `ollama pull {self.modelo}`).", "modelo")
        if r.status_code >= 400:
            raise ErroLLM(f"O Ollama respondeu com erro {r.status_code}.", "erro")
        d = r.json()
        texto = ((d.get("message") or {}).get("content") or "").strip()
        if not texto:
            raise ErroLLM("O modelo devolveu texto vazio.", "vazio")
        return {"texto": texto, "modelo": self.modelo,
                "uso": {"input_tokens": d.get("prompt_eval_count"), "output_tokens": d.get("eval_count")}, "request_id": None}


# ---------- compatível com OpenAI (OpenRouter, Groq, ...) ----------

class ProvedorOpenAICompativel:
    nome = "openai_compativel"

    def __init__(self, base_url: str, modelo: str, chave: str | None):
        self.base = (base_url or "").rstrip("/")
        self.modelo = modelo
        self.chave = chave

    def gerar(self, system: str, user: str) -> dict:
        if offline.modo_offline():
            raise ErroLLM(offline.MSG_LLM_REMOTO, "offline")
        if not self.base or not self.modelo:
            raise ErroLLM("Informe a URL base e o nome do modelo.", "config")
        cab = {"Content-Type": "application/json"}
        if self.chave:
            cab["Authorization"] = f"Bearer {self.chave}"
        corpo = {"model": self.modelo, "temperature": 0.2,
                 "messages": [{"role": "system", "content": system_como_texto(system)}, {"role": "user", "content": user}]}
        try:
            with httpx.Client(timeout=TIMEOUT_NUVEM) as c:
                r = c.post(f"{self.base}/chat/completions", json=corpo, headers=cab)
        except httpx.TimeoutException as exc:
            raise ErroLLM("O provedor demorou demais para responder.", "timeout") from exc
        except httpx.HTTPError as exc:
            raise ErroLLM(f"Sem rede ou endereço inacessível ({type(exc).__name__}).", "conexao") from exc
        if r.status_code in (401, 403):
            raise ErroLLM("Chave de API inválida ou sem permissão.", "chave")
        if r.status_code == 404:
            raise ErroLLM("Endereço ou modelo não encontrado: confira a URL base e o nome do modelo.", "modelo")
        if r.status_code == 429:
            espera = r.headers.get("retry-after")
            raise ErroLLM("Limite de uso do provedor atingido" + (f"; tente de novo em {espera} s." if espera else "; tente mais tarde."), "limite")
        if r.status_code >= 500:
            raise ErroLLM("O provedor está com problemas: tente mais tarde.", "servidor")
        if r.status_code >= 400:
            raise ErroLLM(config.ocultar(f"O provedor recusou o pedido ({r.status_code}).", self.chave), "erro")
        d = r.json()
        try:
            texto = (d["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ErroLLM("Resposta fora do formato esperado (chat/completions).", "formato") from exc
        if not texto:
            raise ErroLLM("O modelo devolveu texto vazio.", "vazio")
        u = d.get("usage") or {}
        return {"texto": texto, "modelo": d.get("model") or self.modelo,
                "uso": {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}, "request_id": d.get("id")}


# ---------- Anthropic (SDK oficial) ----------

class ProvedorAnthropic:
    nome = "anthropic"

    def __init__(self, chave: str | None, modelo: str = "claude-opus-5-5", esforco: str = "medium"):
        if modelo not in config.MODELOS_ANTHROPIC:
            raise ErroLLM(f"Modelo inválido. Use: {', '.join(config.MODELOS_ANTHROPIC)}.", "modelo")
        self.chave = chave
        self.modelo = modelo
        self.esforco = esforco

    def _pedido(self, system, user: str) -> dict:
        # Sem temperature/top_p/top_k/thinking/budget_tokens (400 nesses modelos) e sem prefill.
        # ``system`` pode ser texto ou lista de blocos (com cache_control no último bloco estável, ver cache_prompt.py).
        return {"model": self.modelo, "max_tokens": MAX_TOKENS, "system": system, "messages": [{"role": "user", "content": user}]}

    def gerar(self, system: str, user: str) -> dict:
        if offline.modo_offline():
            raise ErroLLM(offline.MSG_LLM_REMOTO, "offline")
        if not self.chave:
            raise ErroLLM("Chave de API da Anthropic não configurada.", "chave")
        cliente = anthropic.Anthropic(api_key=self.chave, timeout=TIMEOUT_NUVEM)
        pedido = self._pedido(system, user)
        inicio = time.time()
        try:
            if self.modelo in MODELOS_COM_FALLBACK:
                # Fallback de recusa no servidor, ligado por padrão (a tela explica).
                resp = cliente.beta.messages.create(**pedido, betas=[BETA_FALLBACK], fallbacks="default",
                                                    output_config={"effort": self.esforco})
            else:
                resp = cliente.messages.create(**pedido)
        except anthropic.AuthenticationError as exc:
            raise ErroLLM("Chave de API inválida.", "chave") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ErroLLM("A chave não tem permissão para este modelo ou recurso.", "permissao") from exc
        except anthropic.NotFoundError as exc:
            raise ErroLLM(f"Modelo '{self.modelo}' não encontrado para esta chave.", "modelo") from exc
        except anthropic.RateLimitError as exc:
            espera = exc.response.headers.get("retry-after") if getattr(exc, "response", None) is not None else None
            raise ErroLLM("Limite de uso atingido" + (f"; tente de novo em {espera} s." if espera else "; tente mais tarde."), "limite") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ErroLLM(f"A Anthropic está com problemas ({exc.status_code}): tente mais tarde.", "servidor") from exc
            raise ErroLLM(config.ocultar(f"A API recusou o pedido ({exc.status_code}): {getattr(exc, 'message', '')}", self.chave), "erro") from exc
        except anthropic.APIConnectionError as exc:
            raise ErroLLM("Sem rede: não consegui falar com a Anthropic.", "conexao") from exc
        if resp.stop_reason == "refusal":
            det = getattr(resp, "stop_details", None)
            cat = getattr(det, "category", None) if det is not None else None
            raise ErroLLM("O modelo recusou o pedido" + (f" (categoria: {cat})." if cat else "."), "recusa")
        if resp.stop_reason == "max_tokens":
            raise ErroLLM("A resposta foi truncada (max_tokens); nada foi salvo.", "truncada")
        texto = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not texto:
            raise ErroLLM("O modelo devolveu texto vazio.", "vazio")
        u = resp.usage
        return {"texto": texto, "modelo": getattr(resp, "model", None) or self.modelo,
                "uso": {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None),
                        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None) or 0,
                        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None) or 0},
                "request_id": getattr(resp, "_request_id", None), "segundos": round(time.time() - inicio, 2)}


# ---------- fábrica ----------

def provedor_configurado(cfg: dict | None = None):
    """Instância do provedor escolhido na configuração (levanta ErroLLM se for "nenhum")."""
    cfg = cfg or config.carregar()
    p = cfg["provedor"]
    if p in ("anthropic", "openai_compativel") and offline.modo_offline():
        raise ErroLLM(offline.MSG_LLM_REMOTO, "offline")  # 11.2
    if p == "ollama":
        return ProvedorOllama(cfg["ollama"]["base_url"], cfg["ollama"]["modelo"])
    if p == "anthropic":
        return ProvedorAnthropic(config.ler_chave("anthropic"), cfg["anthropic"]["modelo"], cfg["anthropic"]["esforco"])
    if p == "openai_compativel":
        return ProvedorOpenAICompativel(cfg["openai_compativel"]["base_url"], cfg["openai_compativel"]["modelo"], config.ler_chave("openai_compativel"))
    raise ErroLLM("Nenhum provedor de LLM escolhido.", "config")
