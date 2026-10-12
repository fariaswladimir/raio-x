import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


def texto_longo(inicio: str) -> str:
    """Texto com mais de 200 palavras: o controle de qualidade (Frente 2) reprova documentos menores."""
    return inicio + " " + "The analysis of the data shows that the results of the study are consistent. " * 20


@pytest.fixture()
def projetos_dir(tmp_path, monkeypatch):
    """Pasta de projetos isolada por teste (RAIOX_PROJETOS_DIR)."""
    pasta = tmp_path / "projetos"
    monkeypatch.setenv("RAIOX_PROJETOS_DIR", str(pasta))
    yield pasta
    for engine in list(database._engines.values()):
        engine.dispose()
    database._engines.clear()


@pytest.fixture()
def pasta_origem(tmp_path):
    """Pasta de artigos falsa, com alguns .md/.txt (e um arquivo ignorado)."""
    pasta = tmp_path / "artigos"
    (pasta / "sub").mkdir(parents=True)
    (pasta / "001_2026_Kim_Hyunso_Titulo_Um.md").write_text(texto_longo("# Um\n\nTexto do primeiro artigo."), encoding="utf-8")
    (pasta / "002_2025_QP1_Silva_Titulo_Dois.md").write_text(texto_longo("Texto do segundo artigo."), encoding="utf-8")
    (pasta / "sub" / "relatorio_sem_padrao.TXT").write_text(texto_longo("Texto livre."), encoding="utf-8")
    (pasta / "ignorado.csv").write_text("a,b", encoding="utf-8")
    return pasta


@pytest.fixture()
def client(projetos_dir):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def projeto(client, pasta_origem):
    """Projeto criado pela API; devolve o slug."""
    r = client.post("/api/projetos", json={"nome": "Meu Projeto", "pasta_origem": str(pasta_origem)})
    assert r.status_code == 201, r.text
    return r.json()["slug"]


@pytest.fixture()
def sem_rede():
    """EAP 11.2: qualquer conexão para fora do loopback levanta ``RedeBloqueada``; ``sem_rede.tentativas`` lista as barradas."""
    from tests.guarda_rede import GuardaRede

    with GuardaRede() as guarda:
        yield guarda


@pytest.fixture()
def modo_offline(monkeypatch, sem_rede):
    """Modo offline ligado (RAIOX_OFFLINE=1) e rede bloqueada."""
    monkeypatch.setenv("RAIOX_OFFLINE", "1")
    return sem_rede
