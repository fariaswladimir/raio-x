"""14.1 - Configuração global do LLM (fora de qualquer projeto) e guarda da chave de API.

- Configuração sem segredo: arquivo config_llm.json na pasta %APPDATA%/RaioX (``RAIOX_CONFIG_DIR`` troca a pasta, usado nos testes).
- Chave de API: cofre de credenciais do Windows, via ``keyring`` (serviço "RaioX", usuário = nome do provedor).
  Sem ``keyring`` utilizável, cai para ``segredos.json`` na mesma pasta de configuração (fora de ``projetos/``), e a tela avisa.
- A chave só entra por ``salvar``; ``como_publico`` devolve apenas a máscara ("••••1234"). Nunca vai para log,
  resposta da API, projeto, exportação ou pacote (``scripts/empacotar.py`` nunca lê esta pasta).
"""
import json
import os
from pathlib import Path

PROVEDORES = ("nenhum", "ollama", "anthropic", "openai_compativel")
MODELOS_ANTHROPIC = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
ESFORCOS = ("low", "medium", "high")
SERVICO_KEYRING = "RaioX"
PROVEDORES_COM_CHAVE = ("anthropic", "openai_compativel")

PADRAO = {
    "habilitado": False,
    "provedor": "nenhum",
    "ollama": {"base_url": "http://127.0.0.1:11434", "modelo": ""},
    "anthropic": {"modelo": "claude-opus-5-5", "esforco": "medium"},
    "openai_compativel": {"base_url": "https://openrouter.ai/api/v1", "modelo": ""},
}


class ConfigInvalida(ValueError):
    """Valor de configuração inválido (mensagem em português para a tela)."""


def pasta_config() -> Path:
    base = os.getenv("RAIOX_CONFIG_DIR")
    if base:
        return Path(base)
    appdata = os.getenv("APPDATA")
    return (Path(appdata) if appdata else Path.home() / ".config") / "RaioX"


def _arquivo_config() -> Path:
    return pasta_config() / "config_llm.json"


def _arquivo_segredos() -> Path:
    return pasta_config() / "segredos.json"


# ---------- configuração sem segredo ----------

def carregar() -> dict:
    cfg = json.loads(json.dumps(PADRAO))
    try:
        lido = json.loads(_arquivo_config().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(lido, dict):
        return cfg
    for chave, valor in lido.items():
        if chave in ("ollama", "anthropic", "openai_compativel") and isinstance(valor, dict):
            cfg[chave].update({k: v for k, v in valor.items() if k in cfg[chave]})
        elif chave in ("habilitado", "provedor"):
            cfg[chave] = valor
    return cfg


def validar(cfg: dict) -> None:
    if cfg["provedor"] not in PROVEDORES:
        raise ConfigInvalida(f"Provedor inválido: {cfg['provedor']}. Use: {', '.join(PROVEDORES)}.")
    if cfg["anthropic"]["modelo"] not in MODELOS_ANTHROPIC:
        raise ConfigInvalida(f"Modelo Anthropic inválido. Use: {', '.join(MODELOS_ANTHROPIC)}.")
    if cfg["anthropic"]["esforco"] not in ESFORCOS:
        raise ConfigInvalida(f"Esforço inválido. Use: {', '.join(ESFORCOS)}.")
    for prov in ("ollama", "openai_compativel"):
        url = str(cfg[prov]["base_url"] or "").strip()
        if url and not url.lower().startswith(("http://", "https://")):
            raise ConfigInvalida("A URL base deve começar com http:// ou https://.")
        cfg[prov]["base_url"] = url.rstrip("/")


def salvar(atualizacao: dict) -> dict:
    """Mescla ``atualizacao`` (sem segredos) na configuração salva e devolve a configuração nova."""
    cfg = carregar()
    for chave in ("habilitado", "provedor"):
        if chave in atualizacao and atualizacao[chave] is not None:
            cfg[chave] = atualizacao[chave]
    for prov in ("ollama", "anthropic", "openai_compativel"):
        if isinstance(atualizacao.get(prov), dict):
            cfg[prov].update({k: v for k, v in atualizacao[prov].items() if k in cfg[prov] and v is not None})
    cfg["habilitado"] = bool(cfg["habilitado"])
    validar(cfg)
    pasta_config().mkdir(parents=True, exist_ok=True)
    _arquivo_config().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


# ---------- segredo ----------

def _keyring():
    """Módulo ``keyring`` se houver um cofre utilizável; senão None (os testes trocam esta função)."""
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001 - qualquer falha do cofre cai para o arquivo
        return None


def armazenamento() -> str:
    return "keyring" if _keyring() is not None else "arquivo"


def _ler_arquivo() -> dict:
    try:
        d = json.loads(_arquivo_segredos().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def ler_chave(provedor: str) -> str | None:
    kr = _keyring()
    if kr is not None:
        try:
            valor = kr.get_password(SERVICO_KEYRING, provedor)
            if valor:
                return valor
        except Exception:  # noqa: BLE001
            pass
    return _ler_arquivo().get(provedor) or None


def gravar_chave(provedor: str, chave: str) -> None:
    if provedor not in PROVEDORES_COM_CHAVE:
        raise ConfigInvalida("Este provedor não usa chave de API.")
    chave = chave.strip()
    if not chave:
        raise ConfigInvalida("Chave vazia.")
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICO_KEYRING, provedor, chave)
            return
        except Exception:  # noqa: BLE001
            pass
    pasta_config().mkdir(parents=True, exist_ok=True)
    dados = _ler_arquivo()
    dados[provedor] = chave
    _arquivo_segredos().write_text(json.dumps(dados), encoding="utf-8")


def remover_chave(provedor: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICO_KEYRING, provedor)
        except Exception:  # noqa: BLE001 - não havia chave no cofre
            pass
    dados = _ler_arquivo()
    if provedor in dados:
        del dados[provedor]
        _arquivo_segredos().write_text(json.dumps(dados), encoding="utf-8")


def mascarar(chave: str | None) -> str | None:
    if not chave:
        return None
    return "••••" + chave[-4:] if len(chave) > 8 else "••••"


def ocultar(texto: str, *chaves: str | None) -> str:
    """Remove qualquer chave conhecida de uma mensagem de erro antes de mostrá-la ou gravá-la."""
    for c in chaves:
        if c and len(c) >= 6:
            texto = texto.replace(c, "••••")
    return texto


def como_publico() -> dict:
    """Configuração para a API: sem chaves, só a máscara de cada uma."""
    cfg = carregar()
    cfg["chaves"] = {p: mascarar(ler_chave(p)) for p in PROVEDORES_COM_CHAVE}
    cfg["armazenamento_chave"] = armazenamento()
    cfg["modelos_anthropic"] = list(MODELOS_ANTHROPIC)
    return cfg
