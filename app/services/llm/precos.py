"""Item 0 - Tabela de preços editável e estimativa de custo (com e sem cache de prompt).

Preços em US$ por milhão de tokens (MTok), de 12/10/2026. Para editar sem mexer no código, crie
``precos_llm.json`` na pasta de configuração do Raio-X (``%APPDATA%/RaioX``) com o mesmo formato de ``PRECOS_PADRAO``
(só os modelos/campos que mudam) ou use ``PUT /api/config/llm/precos``. ``leitura_cache`` é o preço da leitura do cache
(Opus 5.5: 0,05x a entrada; Sonnet 5.5 e Haiku 5.5: 0,1x); a escrita no cache custa 1,25x a entrada (TTL de 5 min).
``minimo_cache`` é o menor prefixo (em tokens) que a API guarda nesses modelos; abaixo disso o ponto de cache é
ignorado em silêncio (conferir na documentação de caching antes de confiar).
"""
import json

from app.services.llm import config

PRECOS_PADRAO = {
    "claude-opus-5-5": {"entrada": 4.0, "saida": 20.0, "leitura_cache": 0.20, "minimo_cache": 512},
    "claude-sonnet-5-5": {"entrada": 2.0, "saida": 10.0, "leitura_cache": 0.20, "minimo_cache": 512},
    "claude-haiku-5-5": {"entrada": 0.10, "saida": 0.50, "leitura_cache": 0.01, "minimo_cache": 512},
}
MULT_ESCRITA_CACHE = 1.25
CAMPOS = ("entrada", "saida", "leitura_cache", "minimo_cache")


def _arquivo():
    return config.pasta_config() / "precos_llm.json"


def tabela() -> dict:
    t = json.loads(json.dumps(PRECOS_PADRAO))
    try:
        lido = json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return t
    if isinstance(lido, dict):
        for modelo, campos in lido.items():
            if isinstance(campos, dict):
                alvo = t.setdefault(str(modelo), {})
                for k, v in campos.items():
                    if k in CAMPOS and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                        alvo[k] = v
    return t


def salvar(atualizacao: dict) -> dict:
    """Mescla preços informados (validados) no arquivo editável e devolve a tabela efetiva."""
    try:
        atual = json.loads(_arquivo().read_text(encoding="utf-8"))
        atual = atual if isinstance(atual, dict) else {}
    except (OSError, ValueError):
        atual = {}
    for modelo, campos in (atualizacao or {}).items():
        if not isinstance(campos, dict):
            raise config.ConfigInvalida("Formato inválido: use {modelo: {entrada, saida, leitura_cache, minimo_cache}}.")
        for k, v in campos.items():
            if k not in CAMPOS or not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                raise config.ConfigInvalida(f"Valor inválido em {modelo}.{k}: use números >= 0.")
            atual.setdefault(modelo, {})[k] = v
    config.pasta_config().mkdir(parents=True, exist_ok=True)
    _arquivo().write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    return tabela()


def precos_do_modelo(modelo: str | None) -> dict | None:
    return tabela().get(modelo or "")


def custo_de_uso(modelo: str | None, uso: dict | None) -> float | None:
    """Custo em US$ de uma chamada a partir de ``usage`` (entrada, saída, criação e leitura de cache). None sem preço."""
    p = precos_do_modelo(modelo)
    if not p or not uso:
        return None
    ent = uso.get("input_tokens") or 0
    sai = uso.get("output_tokens") or 0
    cri = uso.get("cache_creation_input_tokens") or 0
    lei = uso.get("cache_read_input_tokens") or 0
    return (ent * p["entrada"] + sai * p["saida"] + cri * p["entrada"] * MULT_ESCRITA_CACHE + lei * p["leitura_cache"]) / 1e6


def anotar_uso(modelo: str | None, uso: dict | None, prefixo_tokens: int | None = None) -> dict:
    """Campos extras para o log de geração: tokens de cache, custo e aviso se o prefixo ficou abaixo do mínimo."""
    uso = uso or {}
    cri = uso.get("cache_creation_input_tokens") or 0
    lei = uso.get("cache_read_input_tokens") or 0
    extra = {"cache_criado": cri, "cache_lido": lei, "custo_usd": custo_de_uso(modelo, uso)}
    p = precos_do_modelo(modelo)
    if p and prefixo_tokens is not None and uso and cri == 0 and lei == 0 and prefixo_tokens < p["minimo_cache"]:
        extra["aviso_cache"] = (f"Prefixo de ~{prefixo_tokens} tokens abaixo do mínimo de {p['minimo_cache']} do modelo: "
                                "o cache não foi usado.")
    return extra


def estimar(modelo: str | None, n_chamadas: int, prefixo_tokens: int, variavel_tokens_medio: float,
            saida_tokens_medio: float) -> dict:
    """Estimativa de custo de um lote de ``n_chamadas`` com o mesmo prefixo estável, com e sem cache.

    Com cache: a 1ª chamada escreve o prefixo (1,25x) e as demais o leem (preço de leitura), supondo chamadas em
    sequência a menos de 5 minutos uma da outra. Se o prefixo for menor que o mínimo, o cache não vale (custo igual).
    """
    p = precos_do_modelo(modelo)
    saida = {"modelo": modelo, "chamadas": n_chamadas, "prefixo_tokens": prefixo_tokens,
             "variavel_tokens_medio": round(variavel_tokens_medio), "saida_tokens_medio": round(saida_tokens_medio),
             "preco_conhecido": p is not None}
    entrada_total = n_chamadas * (prefixo_tokens + variavel_tokens_medio)
    saida_total = n_chamadas * saida_tokens_medio
    saida.update(tokens_entrada_sem_cache=round(entrada_total), tokens_saida=round(saida_total))
    if not p:
        saida.update(custo_sem_cache_usd=None, custo_com_cache_usd=None, cache_aplicavel=False,
                     nota="Sem preço para este modelo (local ou fora da tabela): custo não estimado.")
        return saida
    cs = (entrada_total * p["entrada"] + saida_total * p["saida"]) / 1e6
    aplicavel = prefixo_tokens >= p["minimo_cache"] and n_chamadas >= 1
    if aplicavel:
        leituras = max(0, n_chamadas - 1)
        entrada_cache = (prefixo_tokens * p["entrada"] * MULT_ESCRITA_CACHE + leituras * prefixo_tokens * p["leitura_cache"]
                         + n_chamadas * variavel_tokens_medio * p["entrada"])
        cc = (entrada_cache + saida_total * p["saida"]) / 1e6
        saida.update(tokens_cache_escrita=prefixo_tokens, tokens_cache_leitura=leituras * prefixo_tokens)
    else:
        cc = cs
    saida.update(custo_sem_cache_usd=round(cs, 4), custo_com_cache_usd=round(cc, 4), cache_aplicavel=aplicavel,
                 economia_pct=round(100 * (1 - cc / cs), 1) if cs else 0.0,
                 precos_usd_por_mtok={k: p[k] for k in ("entrada", "saida", "leitura_cache")},
                 nota="Estimativa grosseira (~4 caracteres por token). "
                      + ("" if aplicavel else f"Prefixo abaixo do mínimo de {p['minimo_cache']} tokens: sem cache. ")
                      + "O custo real aparece no log (tokens de cache).")
    return saida
