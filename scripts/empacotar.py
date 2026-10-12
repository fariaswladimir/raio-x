"""EAP 11.1: gera o pacote do Raio-X para instalar em outro computador.

Uso (a partir da pasta raio-x):
    python scripts\\empacotar.py

Gera dist\\raio-x-<versao>-<AAAAMMDD>.zip, com app/, frontend/, scripts/, docs/ (.md, .html e .png),
tests/, os .bat, os requirements, README.md, EAP.md e uma pasta projetos/ vazia com LEIAME.txt.

Nunca entram: .venv, projetos/ (dados do usuário), __pycache__, .pytest_cache, *.pyc, dist/, _tmp*/
e qualquer arquivo *.sqlite (inclusive -wal, -shm e -journal), config_llm.json, segredos.json e llm_log.jsonl
(a configuração do LLM e a chave de API ficam em %APPDATA%/RaioX, fora da árvore do projeto).

Usa somente a biblioteca padrão. A pasta projetos/ do disco não é lida nem alterada.
"""
import datetime
import os
import re
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DIST = RAIZ / "dist"
VERSAO_PADRAO = "0.2.0-dev"

PASTAS = ["app", "frontend", "scripts", "tests"]
EXTENSOES_DOCS = {".md", ".html", ".png"}
ARQUIVOS_RAIZ = [
    "iniciar.bat",
    "instalar_docling.bat",
    "requirements.txt",
    "requirements-docling.txt",
    "README.md",
    "EAP.md",
]
PASTAS_EXCLUIDAS = {".venv", "__pycache__", ".pytest_cache", "dist", ".git"}

LEIAME = """Pasta de projetos do Raio-X

Cada projeto criado pela interface vira uma subpasta aqui (projetos\\<nome>\\), com o banco
projeto.sqlite, os parametros, o cache e as saidas. Os projetos sao criados nesta pasta automaticamente.

Esta pasta vem vazia no pacote: os projetos de quem usou o sistema antes nao sao distribuidos.
Pode apagar este LEIAME.txt sem problema.
"""


def ler_versao() -> str:
    """Lê VERSAO de app/config.py (importada por app/main.py). Se não achar, usa VERSAO_PADRAO."""
    for nome in ["app/main.py", "app/config.py"]:
        caminho = RAIZ / nome
        if not caminho.is_file():
            continue
        achado = re.search(r'VERSAO\s*=\s*["\']([^"\']+)["\']', caminho.read_text(encoding="utf-8"))
        if achado:
            return achado.group(1)
    return VERSAO_PADRAO


def _pasta_excluida(nome: str) -> bool:
    return nome in PASTAS_EXCLUIDAS or nome.startswith("_tmp")


# Gerados a partir do corpus do usuário (trechos de artigos): não vão para outras pessoas.
# Frente 14: configuração do LLM e segredos (chave de API) nunca vão no pacote, onde quer que estejam;
# llm_log.jsonl traz trechos do corpus do usuário.
ARQUIVOS_EXCLUIDOS = {"exemplo_laudo_mlr.html", "revisao_limpeza.md", "desempenho.md",
                      "config_llm.json", "segredos.json", "llm_log.jsonl"}


def _arquivo_excluido(nome: str) -> bool:
    if nome in ARQUIVOS_EXCLUIDOS:
        return True
    minusculo = nome.lower()
    return minusculo.endswith(".pyc") or ".sqlite" in minusculo


def coletar_arquivos() -> list[tuple[Path, str]]:
    """Devolve (caminho no disco, nome dentro do zip) de cada arquivo a incluir."""
    itens: list[tuple[Path, str]] = []

    for pasta in PASTAS:
        base = RAIZ / pasta
        if not base.is_dir():
            raise FileNotFoundError(f"Pasta obrigatória não encontrada: {base}")
        for atual, subpastas, arquivos in os.walk(base):
            subpastas[:] = [s for s in subpastas if not _pasta_excluida(s)]
            for nome in arquivos:
                if _arquivo_excluido(nome):
                    continue
                caminho = Path(atual) / nome
                itens.append((caminho, caminho.relative_to(RAIZ).as_posix()))

    base_docs = RAIZ / "docs"
    if not base_docs.is_dir():
        raise FileNotFoundError(f"Pasta obrigatória não encontrada: {base_docs}")
    for atual, subpastas, arquivos in os.walk(base_docs):
        subpastas[:] = [s for s in subpastas if not _pasta_excluida(s)]
        for nome in arquivos:
            caminho = Path(atual) / nome
            if caminho.suffix.lower() in EXTENSOES_DOCS and not _arquivo_excluido(nome):
                itens.append((caminho, caminho.relative_to(RAIZ).as_posix()))

    for nome in ARQUIVOS_RAIZ:
        caminho = RAIZ / nome
        if not caminho.is_file():
            raise FileNotFoundError(f"Arquivo obrigatório não encontrado: {caminho}")
        itens.append((caminho, nome))

    return sorted(itens, key=lambda item: item[1])


def verificar_zip(destino: Path) -> None:
    """Confere se nada proibido entrou no zip. Levanta erro se achar algo."""
    proibidos = []
    with zipfile.ZipFile(destino) as zf:
        for info in zf.infolist():
            partes = info.filename.split("/")
            if info.filename.startswith("projetos/") and info.filename != "projetos/LEIAME.txt":
                proibidos.append(info.filename)
            elif any(_pasta_excluida(p) for p in partes[:-1]):
                proibidos.append(info.filename)
            elif _arquivo_excluido(partes[-1]):
                proibidos.append(info.filename)
    if proibidos:
        raise RuntimeError("Itens proibidos no pacote: " + ", ".join(proibidos))


def formatar_tamanho(bytes_: int) -> str:
    if bytes_ >= 1024 * 1024:
        return f"{bytes_ / (1024 * 1024):.2f} MB"
    return f"{bytes_ / 1024:.1f} KB"


def main() -> None:
    versao = ler_versao()
    data = datetime.date.today().strftime("%Y%m%d")
    PASTA_DIST.mkdir(exist_ok=True)
    destino = PASTA_DIST / f"raio-x-{versao}-{data}.zip"

    itens = coletar_arquivos()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for caminho, nome in itens:
            zf.write(caminho, nome)
        zf.writestr("projetos/LEIAME.txt", LEIAME.encode("utf-8"))

    verificar_zip(destino)

    print(f"Versão: {versao}")
    print("Arquivos incluídos:")
    with zipfile.ZipFile(destino) as zf:
        infos = sorted(zf.infolist(), key=lambda i: i.filename)
        for info in infos:
            print(f"  {info.filename}  ({formatar_tamanho(info.file_size)})")
        total = len(infos)
    print(f"Total: {total} arquivos")
    print(f"Pacote: {destino}")
    print(f"Tamanho do zip: {formatar_tamanho(destino.stat().st_size)} ({destino.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
