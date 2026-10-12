"""Frente 10.1: execução em segundo plano e progresso por etapa."""
import threading
import time

import pytest

from app.services import execucao_bg, orquestrador


def _esperar(client, slug, limite=60):
    fim = time.time() + limite
    while time.time() < fim:
        p = client.get(f"/api/projetos/{slug}/progresso").json()
        if not p["rodando"]:
            return p
        time.sleep(0.05)
    raise AssertionError("a execução não terminou")


@pytest.fixture()
def etapa_lenta():
    """Etapa por documento que espera um evento: segura a execução para testar o 409."""
    liberar = threading.Event()
    orquestrador.registrar_etapa(orquestrador.Etapa(
        nome="lenta", ordem=999, escopo="corpus", cacheavel=False, funcao=lambda ctx: liberar.wait(20) and None))
    yield liberar
    liberar.set()
    orquestrador.remover_etapa("lenta")


def test_progresso_sem_execucao(client, projeto):
    p = client.get(f"/api/projetos/{projeto}/progresso").json()
    assert p["rodando"] is False and p["etapas"] == [] and p["resumo"] is None
    assert client.get("/api/projetos/nao-existe/progresso").status_code == 404


def test_executar_em_segundo_plano_e_progresso_consistente(client, projeto):
    r = client.post(f"/api/projetos/{projeto}/executar")
    assert r.status_code == 202
    assert r.json()["run_id"]
    p = _esperar(client, projeto)
    assert p["run_id"] == r.json()["run_id"]
    assert p["rodando"] is False and p["etapa_atual"] is None
    assert p["iniciado_em"] and p["finalizado_em"]
    assert p["erro"] is None and p["resumo"]["erros"] == 0
    nomes = [e["nome"] for e in p["etapas"]]
    assert nomes == [e.nome for e in orquestrador.etapas_registradas()]
    por_resumo = {e["etapa"]: e for e in p["resumo"]["etapas"]}
    for e in p["etapas"]:
        assert e["status"] == "concluida"
        assert e["feitos"] == e["total"] or e["nome"] == "varredura"
        assert e["feitos"] == por_resumo[e["nome"]]["ok"] + por_resumo[e["nome"]]["pulado"] + por_resumo[e["nome"]]["erro"]
        assert e["pulados"] == por_resumo[e["nome"]]["pulado"] and e["erros"] == 0
    assert sum(1 for d in client.get(f"/api/projetos/{projeto}/documentos").json()) == 3


def test_segunda_execucao_pula_tudo(client, projeto):
    client.post(f"/api/projetos/{projeto}/executar")
    _esperar(client, projeto)
    client.post(f"/api/projetos/{projeto}/executar")
    p = _esperar(client, projeto)
    docs = [e for e in p["etapas"] if e["escopo"] == "documento"]
    assert docs and all(e["pulados"] == e["feitos"] == e["total"] for e in docs if e["total"])


def test_409_quando_ja_esta_rodando(client, projeto, etapa_lenta):
    assert client.post(f"/api/projetos/{projeto}/executar").status_code == 202
    fim = time.time() + 30
    while time.time() < fim and client.get(f"/api/projetos/{projeto}/progresso").json()["etapa_atual"] != "lenta":
        time.sleep(0.05)
    p = client.get(f"/api/projetos/{projeto}/progresso").json()
    assert p["rodando"] is True and p["etapa_atual"] == "lenta"
    assert client.post(f"/api/projetos/{projeto}/executar").status_code == 409
    assert client.post(f"/api/projetos/{projeto}/executar?sincrono=1").status_code == 409
    etapa_lenta.set()
    assert _esperar(client, projeto)["rodando"] is False
    assert client.post(f"/api/projetos/{projeto}/executar").status_code == 202  # liberado de novo
    _esperar(client, projeto)


def test_erro_em_etapa_aparece_no_progresso(client, projeto):
    def quebra(ctx, doc):
        raise RuntimeError("falha de teste")

    orquestrador.registrar_etapa(orquestrador.Etapa(nome="quebra10", ordem=998, escopo="documento", funcao=quebra))
    try:
        client.post(f"/api/projetos/{projeto}/executar")
        p = _esperar(client, projeto)
    finally:
        orquestrador.remover_etapa("quebra10")
    e = next(x for x in p["etapas"] if x["nome"] == "quebra10")
    assert e["status"] == "com_erros" and e["erros"] == 3 and e["feitos"] == 3
    assert p["resumo"]["erros"] == 3
    execs = client.get(f"/api/projetos/{projeto}/execucoes").json()
    assert any(x["etapa"] == "quebra10" and "falha de teste" in x["mensagem"] for x in execs)


def test_falha_fatal_e_registrada(client, projeto, monkeypatch):
    def explode(*a, **k):
        raise ValueError("projeto quebrado")

    monkeypatch.setattr(orquestrador, "executar_pipeline", explode)
    assert client.post(f"/api/projetos/{projeto}/executar").status_code == 202
    p = _esperar(client, projeto)
    assert p["rodando"] is False and "projeto quebrado" in p["erro"] and p["resumo"] is None


def test_callback_de_progresso_opcional_e_inofensivo(client, projeto):
    from app.database import pasta_do_projeto, sessao_do_projeto

    db = sessao_do_projeto(projeto)
    try:
        eventos = []
        r = orquestrador.executar_pipeline(db, pasta_do_projeto(projeto), progresso=lambda ev: eventos.append(ev))
        assert r["erros"] == 0 and {e["evento"] for e in eventos} == {"etapa", "item"}
        r2 = orquestrador.executar_pipeline(db, pasta_do_projeto(projeto), progresso=lambda ev: 1 / 0)  # callback que quebra
        assert r2["erros"] == 0
    finally:
        db.close()
    assert execucao_bg.esta_rodando(projeto) is False
