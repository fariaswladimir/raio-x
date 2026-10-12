"""EAP 11.2: confere se o Raio-X funciona SEM internet.

Uso (a partir da pasta raio-x, com o .venv):

    .venv\\Scripts\\python scripts\\verificar_offline.py --rapido
    .venv\\Scripts\\python scripts\\verificar_offline.py --corpus tests\\corpus_referencia [--pdf arquivo.pdf]

--rapido: só confere as bibliotecas e os modelos instalados (usado por instalar_offline.bat).
Sem --rapido: liga o modo offline (RAIOX_OFFLINE=1, HF_HUB_OFFLINE=1), instala a guarda de rede (qualquer conexão fora
do loopback vira erro e é contada) e roda o pipeline completo em um projeto de teste ("teste-off") sobre a pasta
--corpus (.md/.txt) e, se houver, sobre o --pdf (copiado para uma pasta temporária; o original só é lido).
O projeto de teste é apagado ao fim (só ele). Sai com código 1 se algo falhar ou se houve tentativa de acesso à rede.
"""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

os.environ["RAIOX_OFFLINE"] = "1"  # antes de importar o app (e, por consequência, o Docling)

from app import offline  # noqa: E402

offline.aplicar_ambiente()


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def conferir_instalacao() -> list[str]:
    """Bibliotecas e modelos locais. Devolve a lista de problemas (vazia = tudo certo)."""
    problemas: list[str] = []

    def tentar(nome, fn):
        try:
            _ok(f"{nome}: {fn()}")
        except Exception as exc:  # noqa: BLE001 - diagnóstico para a tela
            problemas.append(f"{nome}: {type(exc).__name__}: {exc}")
            print(f"  [FALHA] {nome}: {type(exc).__name__}: {exc}")

    def nucleo():
        import fastapi, sqlalchemy, numpy, scipy, networkx  # noqa: E401,F401
        return "fastapi, sqlalchemy, numpy, scipy, networkx"

    def lematizador():
        import simplemma
        return f"simplemma lematiza 'studies' -> {simplemma.lemmatize('studies', lang='en')} (dados na roda)"

    def spacy_modelos():
        import spacy
        for modelo in ("en_core_web_sm", "pt_core_news_sm"):
            spacy.load(modelo)
        return f"spaCy {spacy.__version__} com en_core_web_sm e pt_core_news_sm"

    tentar("núcleo", nucleo)
    tentar("simplemma", lematizador)
    tentar("spaCy", spacy_modelos)

    pasta = offline.pasta_artefatos_docling()
    try:
        import docling  # noqa: F401
        tem_docling = True
    except ImportError:
        tem_docling = False
    if not tem_docling:
        print("  [--] Docling não instalado (variante sem Docling): .md e .txt funcionam; PDF e DOCX não.")
    else:
        def modelos_docling():
            if pasta is None or not pasta.is_dir():
                raise FileNotFoundError("pasta modelos\\docling não encontrada (DOCLING_ARTIFACTS_PATH)")
            esperados = [n for n in os.listdir(pasta)]
            if not any("layout" in n for n in esperados):
                raise FileNotFoundError(f"modelo de layout ausente em {pasta}")
            return f"{pasta} ({', '.join(sorted(esperados))})"
        tentar("modelos do Docling", modelos_docling)
        tentar("RapidOCR", lambda: __import__("rapidocr").__name__ + " e onnxruntime " + __import__("onnxruntime").__version__)
    return problemas


def _executar_projeto(client, nome: str, origem: Path) -> dict:
    r = client.post("/api/projetos", json={"nome": nome, "pasta_origem": str(origem)})
    if r.status_code != 201:
        raise RuntimeError(f"criar projeto: {r.status_code} {r.text}")
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    if r.status_code != 200:
        raise RuntimeError(f"executar: {r.status_code} {r.text[:500]}")
    resumo = r.json()
    docs = client.get(f"/api/projetos/{slug}/documentos").json()
    return {"slug": slug, "resumo": resumo, "documentos": docs}


def rodar_pipeline(corpus: Path | None, pdf: Path | None, nome: str, manter: bool) -> list[str]:
    from fastapi.testclient import TestClient

    from app import database
    from app.config import projetos_dir
    from app.main import app
    from tests.guarda_rede import GuardaRede

    problemas: list[str] = []
    temporarios: list[Path] = []
    slugs: list[str] = []
    with GuardaRede() as guarda, TestClient(app) as client:
        info = client.get("/api").json()
        if not info.get("offline"):
            problemas.append("o app não está em modo offline")
        _ok(f"/api informa offline={info.get('offline')} ({offline.origem()})")
        alvos = []
        if corpus:
            alvos.append(("corpus", corpus))
        if pdf:
            pasta = Path(tempfile.mkdtemp(prefix="raiox_pdf_", dir=RAIZ))
            temporarios.append(pasta)
            shutil.copy2(pdf, pasta / Path(pdf).name)  # o original só é lido
            alvos.append(("pdf", pasta))
        for rotulo, pasta in alvos:
            try:
                r = _executar_projeto(client, f"{nome}-{rotulo}", pasta)
                slugs.append(r["slug"])
                erros = r["resumo"].get("erros", 0)
                docs = r["documentos"]
                convertidos = [d for d in docs if d.get("caminho_md") and d.get("convertido_em")]
                paginas = sum(d.get("paginas") or 0 for d in docs)
                _ok(f"{rotulo}: {len(docs)} documento(s), {len(convertidos)} convertido(s), {paginas} página(s), "
                    f"idioma {sorted({d.get('idioma') or '?' for d in docs})}, {erros} erro(s) no pipeline")
                if erros or not docs or len(convertidos) != len(docs):
                    problemas.append(f"{rotulo}: pipeline com erro, sem documentos ou com documento não convertido: {r['resumo']}")
            except Exception as exc:  # noqa: BLE001
                problemas.append(f"{rotulo}: {type(exc).__name__}: {exc}")
                print(f"  [FALHA] {rotulo}: {type(exc).__name__}: {exc}")
        if guarda.tentativas:
            problemas.append("tentativas de acesso à rede barradas: " + "; ".join(guarda.tentativas))
        else:
            _ok("nenhuma tentativa de acesso à rede (guarda ligada)")
    # limpeza: só os projetos de teste criados aqui
    for engine in list(database._engines.values()):
        engine.dispose()
    database._engines.clear()
    if not manter:
        for slug in slugs:
            alvo = projetos_dir() / slug
            if alvo.is_dir() and slug.startswith(nome):
                shutil.rmtree(alvo, ignore_errors=True)
    for pasta in temporarios:
        shutil.rmtree(pasta, ignore_errors=True)
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description="Confere o modo offline do Raio-X.")
    ap.add_argument("--rapido", action="store_true", help="só bibliotecas e modelos (sem rodar o pipeline)")
    ap.add_argument("--corpus", type=Path, help="pasta com .md/.txt para o pipeline")
    ap.add_argument("--pdf", type=Path, help="um PDF (só lido) para o pipeline com Docling")
    ap.add_argument("--nome", default="teste-off", help="nome do projeto de teste (apagado ao fim)")
    ap.add_argument("--manter", action="store_true", help="não apaga o projeto de teste")
    args = ap.parse_args()

    print("Raio-X: verificação do modo offline")
    print(f"  HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')} TRANSFORMERS_OFFLINE={os.environ.get('TRANSFORMERS_OFFLINE')} "
          f"DOCLING_ARTIFACTS_PATH={os.environ.get('DOCLING_ARTIFACTS_PATH')}")
    problemas = conferir_instalacao()
    if not args.rapido and (args.corpus or args.pdf):
        problemas += rodar_pipeline(args.corpus, args.pdf, args.nome, args.manter)
    if problemas:
        print("\nPROBLEMAS:")
        for p in problemas:
            print("  -", p)
        return 1
    print("\nTudo certo: o Raio-X roda sem internet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
