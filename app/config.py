"""Configuração do Raio-X."""
import os
from pathlib import Path

VERSAO = "0.1.0-dev"
SISTEMA = "Raio-X"

RAIZ = Path(__file__).resolve().parent.parent
FRONTEND_DIR = RAIZ / "frontend"

# Extensões de documento aceitas na varredura (comparação sem diferenciar maiúsculas).
EXTENSOES_SUPORTADAS = {".pdf", ".docx", ".md", ".txt", ".markdown"}


def projetos_dir() -> Path:
    """Pasta onde ficam os projetos (projetos/<slug>/).

    Lida a cada chamada para que os testes possam trocar RAIOX_PROJETOS_DIR.
    """
    return Path(os.getenv("RAIOX_PROJETOS_DIR") or (RAIZ / "projetos")).resolve()
