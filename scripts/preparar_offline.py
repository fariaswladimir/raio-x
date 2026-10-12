"""EAP 11.2: prepara o pacote de instalação TOTALMENTE OFFLINE do Raio-X.

Rode em um computador COM internet (Windows, o mesmo Python 3.12 do Raio-X):

    .venv\\Scripts\\python scripts\\preparar_offline.py

Passos:
1. baixa as rodas (wheels) de requirements.txt + requirements-spacy.txt + requirements-docling.txt para
   dist\\offline\\wheels, para Windows / CPython 3.12 / win_amd64 (``pip download --only-binary=:all:``). O PyTorch vem
   do índice CPU (https://download.pytorch.org/whl/cpu), como em instalar_docling.bat;
2. baixa os modelos do spaCy (en_core_web_sm e pt_core_news_sm) como rodas;
3. baixa os modelos do Docling (layout, tabelas e OCR RapidOCR) com ``docling-tools models download`` para
   dist\\offline\\modelos\\docling (é o ``artifacts_path`` que o Raio-X usa no modo offline);
4. confere se os dados do simplemma vêm dentro da roda (não há download em tempo de execução);
5. monta dist\\raio-x-offline-<versao>-<AAAAMMDD>.zip (código como em empacotar.py + wheels + modelos +
   instalar_offline.bat) e, com --variante-sem-docling, também dist\\raio-x-offline-sem-docling-...zip (sem Docling/PyTorch).

Dados do usuário e segredos ficam de fora exatamente como em empacotar.py (mesmas listas de exclusão e a mesma conferência final).
Opções: --pular-download (reaproveita o que já está em dist\\offline), --sem-docling (não baixa o Docling), --variante-sem-docling.
"""
import argparse
import datetime
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import empacotar  # noqa: E402

RAIZ = empacotar.RAIZ
PASTA_OFFLINE = empacotar.PASTA_DIST / "offline"
PLATAFORMA = "win_amd64"
PYTHON_VERSAO = "3.12"
ABI = "cp312"
INDICE_TORCH_CPU = "https://download.pytorch.org/whl/cpu"

REQ_BASE = RAIZ / "requirements.txt"
REQ_SPACY = RAIZ / "requirements-spacy.txt"
REQ_DOCLING = RAIZ / "requirements-docling.txt"

# Modelos do spaCy: não estão no PyPI; vêm das releases do projeto (3.8.0 combina com spacy>=3.8,<4).
VERSAO_MODELO_SPACY = "3.8.0"
MODELOS_SPACY = ("en_core_web_sm", "pt_core_news_sm")
URL_MODELO_SPACY = "https://github.com/explosion/spacy-models/releases/download/{n}-{v}/{n}-{v}-py3-none-any.whl"

# Docling: os modelos usados pelo Raio-X (layout + tabelas + OCR). code_formula e picture_classifier não são usados.
MODELOS_DOCLING = ("layout", "tableformer", "rapidocr")
IDIOMAS_OCR = ("en", "pt", "es")  # idiomas do parâmetro `idioma`

LEIAME_OFFLINE = """Raio-X, pacote offline (EAP 11.2)

1. Extraia este .zip inteiro em uma pasta local (ex.: C:\\Raio-X), sem usar o OneDrive.
2. Instale o Python 3.12 (64 bits) marcando "Add python.exe to PATH" (instalador baixado antes, em outro computador).
3. Dois cliques em instalar_offline.bat: cria o .venv e instala tudo a partir das pastas wheels\\ e modelos\\, sem internet.
4. Dois cliques em iniciar.bat. O selo "Offline" aparece no topo da tela.

Detalhes: docs\\offline.md e docs\\instalacao.md.
"""


def _base_pip_download(destino: Path) -> list[str]:
    return [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--platform", PLATAFORMA,
            "--python-version", PYTHON_VERSAO, "--implementation", "cp", "--abi", ABI, "-d", str(destino)]


def pip_download(arquivos_req: list[Path], destino: Path, encontrar: Path | None = None) -> list[str]:
    """Comando ``pip download`` para Windows/CPython 3.12, só com rodas binárias."""
    cmd = _base_pip_download(destino)
    if encontrar:
        cmd += ["--find-links", str(encontrar)]
    for req in arquivos_req:
        cmd += ["-r", str(req)]
    return cmd


def pip_download_torch_cpu(destino: Path) -> list[str]:
    """Comando de instalar_docling.bat (índice do PyTorch CPU), trocando install por download."""
    return _base_pip_download(destino) + ["torch", "torchvision", "--index-url", INDICE_TORCH_CPU]


def pip_download_spacy_modelos(destino: Path) -> list[list[str]]:
    base = [sys.executable, "-m", "pip", "download", "--no-deps", "-d", str(destino)]
    return [base + [URL_MODELO_SPACY.format(n=n, v=VERSAO_MODELO_SPACY)] for n in MODELOS_SPACY]


def comando_modelos_docling(destino: Path) -> list[str]:
    cmd = [sys.executable, "-c", "from docling.cli.tools import app; app()", "models", "download", "--output-dir", str(destino)]
    cmd += list(MODELOS_DOCLING)
    for idioma in IDIOMAS_OCR:
        cmd += ["--rapidocr-backend-lang", f"onnxruntime:{idioma}"]
    return cmd


def executar(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def tamanho_pasta(pasta: Path) -> int:
    return sum(f.stat().st_size for f in pasta.rglob("*") if f.is_file()) if pasta.is_dir() else 0


def mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def baixar_rodas(com_docling: bool) -> tuple[Path, Path]:
    """Devolve (pasta com todas as rodas, pasta só com as rodas da variante sem Docling)."""
    todas = PASTA_OFFLINE / "wheels"
    sem_docling = PASTA_OFFLINE / "wheels-sem-docling"
    todas.mkdir(parents=True, exist_ok=True)
    sem_docling.mkdir(parents=True, exist_ok=True)
    print("[1/4] Rodas do núcleo + spaCy + modelos do spaCy ...")
    executar(pip_download([REQ_BASE, REQ_SPACY], sem_docling))
    for cmd in pip_download_spacy_modelos(sem_docling):
        executar(cmd)
    for arq in sem_docling.glob("*.whl"):  # a pasta completa tem tudo da variante sem Docling
        if not (todas / arq.name).exists():
            shutil.copy2(arq, todas / arq.name)
    if com_docling:
        print("[2/4] PyTorch CPU e Docling ...")
        executar(pip_download_torch_cpu(todas))
        executar(pip_download([REQ_DOCLING], todas, encontrar=todas))
    return todas, sem_docling


def baixar_modelos_docling() -> Path:
    destino = PASTA_OFFLINE / "modelos" / "docling"
    destino.mkdir(parents=True, exist_ok=True)
    print("[3/4] Modelos do Docling (layout, tabelas, OCR) ...")
    executar(comando_modelos_docling(destino))
    return destino


def conferir_simplemma() -> str:
    """O simplemma 2.x traz os dicionários dentro da roda: não há download em tempo de execução."""
    for roda in (PASTA_OFFLINE / "wheels").glob("simplemma-*.whl"):
        with zipfile.ZipFile(roda) as zf:
            dados = [n for n in zf.namelist() if "dictionaries" in n]
        if dados:
            return f"{roda.name}: {len(dados)} arquivos de dados dentro da roda (sem download em tempo de execução)"
        raise RuntimeError(f"{roda.name} não traz os dicionários: o simplemma tentaria baixar dados.")
    raise RuntimeError("Roda do simplemma não encontrada em dist/offline/wheels.")


def _compactar(nome: str) -> int:
    return zipfile.ZIP_STORED if nome.lower().endswith((".whl", ".zip", ".onnx", ".safetensors", ".pt", ".bin")) else zipfile.ZIP_DEFLATED


def montar_zip(destino: Path, rodas: Path, modelos: Path | None) -> int:
    """Zip = código (empacotar.coletar_arquivos) + wheels/ + modelos/ + LEIA-ME_OFFLINE.txt + projetos/LEIAME.txt."""
    itens = empacotar.coletar_arquivos()
    with zipfile.ZipFile(destino, "w") as zf:
        for caminho, nome in itens:
            zf.write(caminho, nome, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("projetos/LEIAME.txt", empacotar.LEIAME.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("LEIA-ME_OFFLINE.txt", LEIAME_OFFLINE.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        for arq in sorted(rodas.glob("*.whl")):
            zf.write(arq, f"wheels/{arq.name}", compress_type=zipfile.ZIP_STORED)
        if modelos is not None and modelos.is_dir():
            base = modelos.parent.parent  # dist/offline
            for arq in sorted(modelos.rglob("*")):
                if arq.is_file():
                    zf.write(arq, arq.relative_to(base).as_posix(), compress_type=_compactar(arq.name))
    verificar_zip_offline(destino)
    return destino.stat().st_size


def verificar_zip_offline(destino: Path) -> None:
    """Mesma conferência do empacotar.py (sem dados do usuário nem segredos) + itens obrigatórios do modo offline."""
    empacotar.verificar_zip(destino)
    with zipfile.ZipFile(destino) as zf:
        nomes = set(zf.namelist())
    faltando = [n for n in ("instalar_offline.bat", "requirements.txt", "requirements-spacy.txt", "app/offline.py",
                            "scripts/verificar_offline.py") if n not in nomes]
    if faltando:
        raise RuntimeError("Faltam no pacote offline: " + ", ".join(faltando))
    if "raiox_offline.flag" in nomes:
        raise RuntimeError("raiox_offline.flag não pode viajar no pacote (é criado por instalar_offline.bat).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepara o pacote offline do Raio-X (precisa de internet).")
    ap.add_argument("--pular-download", action="store_true", help="reaproveita dist/offline já baixado")
    ap.add_argument("--sem-docling", action="store_true", help="não baixa Docling/PyTorch/modelos (gera só a variante sem Docling)")
    ap.add_argument("--variante-sem-docling", action="store_true", help="gera também o zip sem Docling")
    args = ap.parse_args()

    inicio = time.time()
    versao = empacotar.ler_versao()
    data = datetime.date.today().strftime("%Y%m%d")
    com_docling = not args.sem_docling
    empacotar.PASTA_DIST.mkdir(exist_ok=True)
    PASTA_OFFLINE.mkdir(parents=True, exist_ok=True)

    if args.pular_download:
        todas, sem_docling = PASTA_OFFLINE / "wheels", PASTA_OFFLINE / "wheels-sem-docling"
    else:
        todas, sem_docling = baixar_rodas(com_docling)
    modelos = PASTA_OFFLINE / "modelos" / "docling"
    if com_docling and not args.pular_download:
        modelos = baixar_modelos_docling()

    print("[4/4] Conferências e zip ...")
    print("  simplemma:", conferir_simplemma())
    print(f"  rodas: {len(list(todas.glob('*.whl')))} arquivos, {mb(tamanho_pasta(todas))}; modelos Docling: {mb(tamanho_pasta(modelos))}")

    saidas = []
    if com_docling:
        destino = empacotar.PASTA_DIST / f"raio-x-offline-{versao}-{data}.zip"
        saidas.append((destino, montar_zip(destino, todas, modelos)))
    if args.variante_sem_docling or args.sem_docling:
        destino = empacotar.PASTA_DIST / f"raio-x-offline-sem-docling-{versao}-{data}.zip"
        saidas.append((destino, montar_zip(destino, sem_docling, None)))

    print("Pacotes gerados:")
    for caminho, tam in saidas:
        print(f"  {caminho}  {mb(tam)} ({tam} bytes)")
    print(f"Tempo total: {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    main()
