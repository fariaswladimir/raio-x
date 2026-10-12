"""EAP 11.2: modo totalmente offline.

Cobre o interruptor (flag/ambiente/config), as variáveis de ambiente do Hugging Face, o bloqueio de LLM remoto e da consulta
online, o selo na API, a guarda de rede, o empacotamento offline (mesmas exclusões do empacotar.py), o instalar_offline.bat e
o pipeline completo sob a guarda de rede (MD sempre; PDF só se os modelos do Docling estiverem em cache).
"""
import json
import os
import socket
import zipfile
from pathlib import Path

import pytest

from app import offline
from app.services.llm import config
from app.services.llm.provedores import ErroLLM, ProvedorAnthropic, ProvedorOpenAICompativel, provedor_configurado
from scripts import empacotar, preparar_offline
from tests.guarda_rede import GuardaRede, RedeBloqueada, host_local

RAIZ = Path(__file__).resolve().parent.parent
CORPUS = Path(__file__).resolve().parent / "corpus_referencia"


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch, tmp_path):
    """Sem flag, sem variável e com a pasta de configuração isolada; devolve variáveis do HF ao estado original."""
    monkeypatch.delenv("RAIOX_OFFLINE", raising=False)
    monkeypatch.setenv("RAIOX_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(offline, "ARQUIVO_FLAG", tmp_path / "raiox_offline.flag")
    for chave in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "DOCLING_ARTIFACTS_PATH"):
        monkeypatch.delenv(chave, raising=False)


# ---------- interruptor ----------

def test_modo_offline_desligado_por_padrao():
    assert offline.modo_offline() is False and offline.origem() is None
    assert offline.aplicar_ambiente() is False and "HF_HUB_OFFLINE" not in os.environ
    offline.exigir_internet()  # não levanta


def test_flag_liga_e_ambiente_decide_antes_da_flag(monkeypatch):
    offline.ARQUIVO_FLAG.write_text("x", encoding="utf-8")
    assert offline.modo_offline() and offline.origem() == "flag"
    monkeypatch.setenv("RAIOX_OFFLINE", "0")
    assert not offline.modo_offline()
    monkeypatch.setenv("RAIOX_OFFLINE", "sim")
    assert offline.origem() == "ambiente"


def test_config_offline_json_liga(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config_offline.json").write_text(json.dumps({"modo_offline": True}), encoding="utf-8")
    assert offline.origem() == "config"


def test_aplicar_ambiente_liga_hf_e_artifacts_path(monkeypatch, tmp_path):
    pasta = tmp_path / "modelos" / "docling"
    pasta.mkdir(parents=True)
    monkeypatch.setattr(offline, "PASTA_DOCLING", pasta)
    monkeypatch.setenv("RAIOX_OFFLINE", "1")
    assert offline.aplicar_ambiente() is True
    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["DOCLING_ARTIFACTS_PATH"] == str(pasta)
    assert offline.pasta_artefatos_docling() == pasta
    # a variável do usuário tem prioridade sobre a pasta padrão
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", str(tmp_path / "outra"))
    assert offline.pasta_artefatos_docling() == tmp_path / "outra"


def test_docling_recebe_artifacts_path_no_modo_offline(monkeypatch, tmp_path):
    from app.services.etapas import conversao

    capturado = {}

    class Opcoes:
        def __init__(self, artifacts_path=None):
            capturado["artifacts_path"] = artifacts_path
            self.table_structure_options = type("T", (), {})()

    class Conversor:
        def __init__(self, format_options):
            capturado["conversor"] = True

    d = {"PdfPipelineOptions": Opcoes, "DocumentConverter": Conversor, "PdfFormatOption": lambda pipeline_options: pipeline_options,
         "InputFormat": type("IF", (), {"PDF": "pdf"}), "TableFormerMode": type("TM", (), {"FAST": "fast"}),
         "OcrMode": None, "RapidOcrOptions": None}
    monkeypatch.setattr(conversao, "_importar_docling", lambda: d)
    monkeypatch.setattr(conversao, "_conversores", {})
    pasta = tmp_path / "docling"
    pasta.mkdir()
    monkeypatch.setenv("RAIOX_OFFLINE", "1")
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", str(pasta))
    conversao._obter_conversor(False)
    assert capturado["artifacts_path"] == pasta and capturado["conversor"]


# ---------- recursos que precisam de internet ----------

def test_llm_remoto_recusado_e_ollama_permitido(monkeypatch):
    config.salvar({"provedor": "anthropic"})
    assert isinstance(provedor_configurado(), ProvedorAnthropic)  # online: ok
    monkeypatch.setenv("RAIOX_OFFLINE", "1")
    for prov in ("anthropic", "openai_compativel"):
        with pytest.raises(ErroLLM) as e:
            provedor_configurado(config.salvar({"provedor": prov}))
        assert e.value.categoria == "offline" and "offline" in str(e.value).lower()
    with pytest.raises(ErroLLM):
        ProvedorAnthropic("sk-teste-0000000000").gerar("s", "u")
    with pytest.raises(ErroLLM):
        ProvedorOpenAICompativel("https://x.example/v1", "m", "k").gerar("s", "u")
    assert provedor_configurado(config.salvar({"provedor": "ollama", "ollama": {"modelo": "m"}})).nome == "ollama"


def test_api_informa_offline_e_bloqueia_config_remota(client, monkeypatch):
    assert client.get("/api").json()["offline"] is False
    assert client.get("/api/offline").json()["offline"] is False
    monkeypatch.setenv("RAIOX_OFFLINE", "1")
    assert client.get("/api").json()["offline"] is True
    st = client.get("/api/offline").json()
    assert st["offline"] is True and st["origem"] == "ambiente"
    cfg = client.get("/api/config/llm").json()
    assert cfg["modo_offline"] is True and "offline" in cfg["aviso_offline"].lower()
    r = client.post("/api/config/llm/testar")
    assert r.status_code in (200, 409)  # sem provedor escolhido: 409; remoto escolhido: ok=False/categoria offline


def test_consulta_online_de_metadados_recusada(client, projeto, monkeypatch):
    monkeypatch.setenv("RAIOX_OFFLINE", "1")
    r = client.post(f"/api/projetos/{projeto}/metadados/extrair", params={"online": "true"})
    assert r.status_code == 409 and "offline" in r.json()["detail"].lower()
    r = client.post(f"/api/projetos/{projeto}/metadados/consultar-online", json={"fonte": "crossref"})
    assert r.status_code == 409 and "offline" in r.json()["detail"].lower()
    from app.services.corpus import online
    with pytest.raises(offline.ModoOffline):
        online.consultar("10.1000/xyz", email="a@b.c")


def test_frontend_tem_selo_offline():
    html = (RAIZ / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (RAIZ / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'id="selo-offline"' in html and "selo-offline" in js and "i.offline" in js


# ---------- guarda de rede ----------

def test_guarda_bloqueia_externo_e_libera_loopback():
    assert host_local("127.0.0.1") and host_local("::1") and host_local("localhost") and not host_local("8.8.8.8")
    assert not host_local("huggingface.co")
    original = socket.socket.connect
    with GuardaRede() as guarda:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            with pytest.raises(RedeBloqueada):
                s.connect(("93.184.216.34", 80))
            with pytest.raises(RedeBloqueada):
                socket.create_connection(("example.com", 443), timeout=0.2)
            with pytest.raises(RedeBloqueada):
                socket.getaddrinfo("huggingface.co", 443)
            s.connect_ex(("127.0.0.1", 9))  # loopback não é barrado (pode ser recusado pelo sistema, mas não levanta RedeBloqueada)
        finally:
            s.close()
        assert len(guarda.tentativas) == 3
    # fora do contexto, as funções originais voltam
    assert socket.socket.connect is original


# ---------- empacotamento offline ----------

def test_zip_offline_usa_as_mesmas_exclusoes(tmp_path):
    rodas = tmp_path / "wheels"
    rodas.mkdir()
    (rodas / "pacote-1.0-py3-none-any.whl").write_bytes(b"PK")
    modelos = tmp_path / "offline" / "modelos" / "docling"
    (modelos / "layout").mkdir(parents=True)
    (modelos / "layout" / "model.onnx").write_bytes(b"onnx")
    destino = tmp_path / "pacote.zip"
    preparar_offline.montar_zip(destino, rodas, modelos)
    with zipfile.ZipFile(destino) as zf:
        nomes = zf.namelist()
    assert "wheels/pacote-1.0-py3-none-any.whl" in nomes and "modelos/docling/layout/model.onnx" in nomes
    assert {"instalar_offline.bat", "scripts/preparar_offline.py", "scripts/verificar_offline.py", "app/offline.py",
            "projetos/LEIAME.txt", "LEIA-ME_OFFLINE.txt"} <= set(nomes)
    assert not any(n.startswith("projetos/") and n != "projetos/LEIAME.txt" for n in nomes)
    assert not any(n.endswith((".sqlite", "config_llm.json", "segredos.json", "llm_log.jsonl", "raiox_offline.flag")) for n in nomes)
    assert not any(n.startswith((".venv/", "dist/", ".git/")) or "__pycache__" in n for n in nomes)


def test_zip_offline_barra_segredos_e_flag(tmp_path):
    ruim = tmp_path / "ruim.zip"
    with zipfile.ZipFile(ruim, "w") as zf:
        zf.writestr("app/segredos.json", "{}")
    with pytest.raises(RuntimeError):
        preparar_offline.verificar_zip_offline(ruim)
    assert empacotar._arquivo_excluido("raiox_offline.flag")
    nomes = [n for _c, n in empacotar.coletar_arquivos()]
    assert "instalar_offline.bat" in nomes and "instalar_spacy.bat" in nomes and "requirements-spacy.txt" in nomes


def test_comandos_de_download_sao_para_windows_python312():
    cmd = preparar_offline.pip_download([preparar_offline.REQ_BASE, preparar_offline.REQ_DOCLING], Path("dest"))
    texto = " ".join(cmd)
    assert "--only-binary=:all:" in cmd and "--platform win_amd64" in texto and "--python-version 3.12" in texto
    assert "requirements.txt" in texto and "requirements-docling.txt" in texto
    torch = " ".join(preparar_offline.pip_download_torch_cpu(Path("dest")))
    assert "https://download.pytorch.org/whl/cpu" in torch and "torch torchvision" in torch
    docling = preparar_offline.comando_modelos_docling(Path("m"))
    assert "--output-dir" in docling and "layout" in docling and "rapidocr" in docling and "onnxruntime:pt" in docling
    assert all("en_core_web_sm" in c or "pt_core_news_sm" in c for c in
               [" ".join(x) for x in preparar_offline.pip_download_spacy_modelos(Path("d"))])


def test_instalar_offline_bat_nao_usa_internet():
    bruto = (RAIZ / "instalar_offline.bat").read_bytes()
    assert b"\r\n" in bruto and bruto.isascii()
    bat = bruto.decode("ascii")
    # todo pip install é sem índice
    for linha in bat.splitlines():
        if "pip install" in linha:
            assert "--no-index" in linha and "--find-links" in linha, linha
    assert "--index-url" not in bat and "http://" not in bat and "curl" not in bat.lower()
    assert "raiox_offline.flag" in bat and "Python nao encontrado" in bat and "mais antigo que a versao 3.11" in bat
    iniciar = (RAIZ / "iniciar.bat").read_bytes().decode("ascii")
    assert "raiox_offline.flag" in iniciar and "goto iniciar_servidor" in iniciar


# ---------- pipeline completo sem rede ----------

def test_pipeline_md_completo_sob_guarda_de_rede(client, modo_offline):
    r = client.post("/api/projetos", json={"nome": "Offline MD", "pasta_origem": str(CORPUS)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200 and r.json()["erros"] == 0, r.text
    assert client.get("/api").json()["offline"] is True
    r = client.get(f"/api/projetos/{slug}/analises/resumo")
    assert r.status_code == 200
    assert modo_offline.tentativas == []


def _pdf_minimo(paginas: list[str]) -> bytes:
    """PDF de texto escrito à mão (Helvetica), sem dependências."""
    objetos: list[bytes] = []

    def novo(corpo: bytes) -> int:
        objetos.append(corpo)
        return len(objetos)

    novo(b"<< /Type /Catalog /Pages 2 0 R >>")
    novo(b"")  # Pages (preenchido depois)
    fonte = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    ids = []
    for texto in paginas:
        linhas = [texto[i:i + 85] for i in range(0, len(texto), 85)]
        fluxo = b"BT /F1 11 Tf 14 TL 50 780 Td " + b" ".join(
            b"(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1") + b") Tj T*" for l in linhas) + b" ET"
        c = novo(b"<< /Length %d >>\nstream\n" % len(fluxo) + fluxo + b"\nendstream")
        ids.append(novo(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                        b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (c, fonte)))
    objetos[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % i for i in ids) + b"] /Count %d >>" % len(ids)
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for i, corpo in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for pos in posicoes:
        saida += b"%010d 00000 n \n" % pos
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)
    return bytes(saida)


def _modelos_docling_disponiveis() -> str | None:
    """None se der para converter PDF sem internet; senão o motivo de pular."""
    try:
        import docling  # noqa: F401
    except ImportError:
        return "Docling não instalado (rode instalar_docling.bat)"
    pasta = RAIZ / "modelos" / "docling"
    if os.getenv("DOCLING_ARTIFACTS_PATH") or pasta.is_dir():
        return None
    cache = Path(os.getenv("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    if list(cache.glob("models--docling-project--docling-layout*")) and list(cache.glob("models--docling-project--docling-models*")):
        return None
    return "modelos do Docling não estão em cache (nem em modelos/docling): converta um PDF com internet uma vez ou rode preparar_offline.py"


def test_pipeline_pdf_pequeno_sob_guarda_de_rede(client, modo_offline, tmp_path, monkeypatch):
    motivo = _modelos_docling_disponiveis()
    if motivo:
        pytest.skip(motivo)
    try:  # constantes do huggingface_hub são lidas na importação: reforça o modo offline no processo atual
        from huggingface_hub import constants
        monkeypatch.setattr(constants, "HF_HUB_OFFLINE", True)
    except Exception:  # noqa: BLE001
        pass
    pasta = tmp_path / "pdfs"
    pasta.mkdir()
    frase = "The analysis of the data shows that the results of the study are consistent with the hypothesis. "
    (pasta / "001_2026_Teste_Offline.pdf").write_bytes(_pdf_minimo([frase * 6, frase * 6]))
    r = client.post("/api/projetos", json={"nome": "Offline PDF", "pasta_origem": str(pasta)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200 and r.json()["erros"] == 0, r.text
    docs = client.get(f"/api/projetos/{slug}/documentos").json()
    assert len(docs) == 1
    assert modo_offline.tentativas == []
