"""EAP 11.2: modo totalmente offline.

O modo offline fica ligado quando (nesta ordem de prioridade):
1. a variável de ambiente ``RAIOX_OFFLINE`` vale 1/true/sim (liga) ou 0/false/nao (desliga);
2. existe o arquivo ``raiox_offline.flag`` na raiz do Raio-X (criado por ``instalar_offline.bat``);
3. ``config_offline.json`` na pasta de configuração (``%APPDATA%/RaioX``) tem ``{"modo_offline": true}``.

Efeitos no modo offline:
- ``HF_HUB_OFFLINE`` e ``TRANSFORMERS_OFFLINE`` ligados **antes** de importar o Docling (nenhuma consulta ao Hugging Face);
- o Docling usa ``artifacts_path`` apontando para ``modelos/docling`` (layout, tabelas e OCR já baixados);
- consulta online de metadados (Crossref/OpenAlex) e provedores remotos de LLM (Anthropic, OpenAI-compatível)
  são recusados com mensagem clara; o Ollama (máquina local) continua permitido;
- a tela mostra o selo "Offline".

Este módulo só usa a biblioteca padrão e não importa o resto do app (é carregado antes do Docling).
"""
import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_FLAG = RAIZ / "raiox_offline.flag"
PASTA_MODELOS = RAIZ / "modelos"
PASTA_DOCLING = PASTA_MODELOS / "docling"

MSG_ONLINE = "Modo offline: a consulta online de metadados (Crossref/OpenAlex) está desativada."
MSG_LLM_REMOTO = ("Modo offline: provedores de LLM remotos (Anthropic, OpenAI-compatível) estão desativados. "
                  "Use o Ollama, que roda neste computador, ou deixe o LLM desligado.")

_LIGA = {"1", "true", "sim", "yes", "on"}
_DESLIGA = {"0", "false", "nao", "não", "no", "off"}


class ModoOffline(RuntimeError):
    """Recurso que precisa de internet foi pedido com o modo offline ligado (mensagem em português para a tela)."""


def _config_offline() -> bool:
    appdata = os.getenv("RAIOX_CONFIG_DIR") or ""
    base = Path(appdata) if appdata else (Path(os.getenv("APPDATA") or Path.home() / ".config") / "RaioX")
    try:
        return bool(json.loads((base / "config_offline.json").read_text(encoding="utf-8")).get("modo_offline"))
    except (OSError, ValueError, AttributeError):
        return False


def origem() -> str | None:
    """De onde vem o modo offline: "ambiente", "flag", "config" ou None (desligado). Lido a cada chamada (testes trocam o ambiente)."""
    valor = os.getenv("RAIOX_OFFLINE", "").strip().lower()
    if valor in _LIGA:
        return "ambiente"
    if valor in _DESLIGA:
        return None
    if ARQUIVO_FLAG.is_file():
        return "flag"
    if _config_offline():
        return "config"
    return None


def modo_offline() -> bool:
    return origem() is not None


def pasta_artefatos_docling() -> Path | None:
    """Pasta com os modelos do Docling para o ``artifacts_path``: ``DOCLING_ARTIFACTS_PATH`` ou ``modelos/docling`` (se existir).
    Só vale no modo offline; online o Docling baixa os modelos sozinho."""
    if not modo_offline():
        return None
    env = os.getenv("DOCLING_ARTIFACTS_PATH", "").strip()
    if env:
        return Path(env)
    return PASTA_DOCLING if PASTA_DOCLING.is_dir() else None


def aplicar_ambiente() -> bool:
    """Liga as variáveis que fazem Hugging Face/transformers/Docling não tocarem a rede. Chamar **antes** de importar o Docling.
    Devolve se o modo offline está ligado."""
    if not modo_offline():
        return False
    for chave in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[chave] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    pasta = pasta_artefatos_docling()
    if pasta is not None:
        os.environ.setdefault("DOCLING_ARTIFACTS_PATH", str(pasta))
    return True


def exigir_internet(mensagem: str = MSG_ONLINE) -> None:
    """Levanta ``ModoOffline`` se o modo offline estiver ligado."""
    if modo_offline():
        raise ModoOffline(mensagem)


def estado() -> dict:
    pasta = pasta_artefatos_docling()
    return {"offline": modo_offline(), "origem": origem(),
            "modelos_docling": str(pasta) if pasta else None,
            "modelos_docling_presentes": bool(pasta and pasta.is_dir())}
