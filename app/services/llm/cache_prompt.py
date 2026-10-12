"""Item 0 (12/10/2026) - Prompt caching: ``system`` como lista de blocos com um ponto de cache no último bloco estável.

Regras (a Anthropic faz *prefix match*: qualquer byte diferente no prefixo invalida o cache daí para a frente):
- O prefixo estável (instruções + codebook/definições) vai em ``system``; o conteúdo que muda a cada chamada (o trecho)
  vai na mensagem do usuário, depois do ponto de cache.
- Nada de data/hora, IDs de execução ou JSON sem ordenar no prefixo: use ``json_estavel`` e listas ordenadas.
- Ollama e endpoints compatíveis com OpenAI recebem o mesmo conteúdo achatado em texto (sem cache).
"""
import json
import re


def blocos_system(*partes_estaveis: str) -> list[dict]:
    """Blocos de texto do ``system``; só o último leva ``cache_control`` (ponto de cache do prefixo inteiro)."""
    partes = [p for p in partes_estaveis if p]
    blocos = [{"type": "text", "text": p} for p in partes]
    if blocos:
        blocos[-1]["cache_control"] = {"type": "ephemeral"}
    return blocos


def system_como_texto(system) -> str:
    """``system`` (texto ou lista de blocos) como um texto só, para provedores sem cache."""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system or [] if isinstance(b, dict))


def json_estavel(obj) -> str:
    """JSON determinístico (chaves ordenadas, separadores fixos) para entrar no prefixo em cache."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chave_natural(s: str):
    """Ordem natural ("C1.2" < "C1.10") para ordenar códigos de forma determinística."""
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in re.split(r"(\d+)", str(s)) if t != ""]


def tokens_aprox(texto: str) -> int:
    """Estimativa grosseira (~4 caracteres por token); a contagem real vem de ``usage`` na resposta."""
    return max(1, round(len(texto) / 4)) if texto else 0
