import hashlib
import json

import pytest
from sqlalchemy import inspect, select

from app import database
from app.models import Documento, Execucao
from app.services import orquestrador, parametros
from app.services.etapas.varredura import parse_nome
from tests.conftest import texto_longo


def _instantaneo(pasta):
    """Nome -> (conteúdo, mtime) de tudo na pasta, para provar que nada mudou."""
    return {
        p.relative_to(pasta).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in pasta.rglob("*")
        if p.is_file()
    }


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return r.json()


def _status_docs(client, slug):
    return {d["arquivo"]: d["status"] for d in client.get(f"/api/projetos/{slug}/documentos").json()}


# ---------- 1.2 criação do projeto e tabelas ----------

def test_criar_projeto_cria_estrutura_e_tabelas(client, projetos_dir, pasta_origem):
    r = client.post("/api/projetos", json={"nome": "Corpus Ação", "pasta_origem": str(pasta_origem)})
    assert r.status_code == 201
    slug = r.json()["slug"]
    assert slug == "corpus-acao"
    raiz = projetos_dir / slug
    assert (raiz / "projeto.sqlite").is_file()
    assert (raiz / "parametros.json").is_file()
    assert (raiz / "cache").is_dir() and (raiz / "saidas").is_dir()
    tabelas = set(inspect(database.engine_do_projeto(slug)).get_table_names())
    assert {"projeto", "documento", "execucao", "analise", "evidencia", "comentario", "comentario_evidencia"} <= tabelas


def test_criar_projeto_validacoes(client, projeto, pasta_origem, tmp_path):
    assert client.post("/api/projetos", json={"nome": "Meu Projeto", "pasta_origem": str(pasta_origem)}).status_code == 409
    assert client.post("/api/projetos", json={"nome": "X", "pasta_origem": str(tmp_path / "nao_existe")}).status_code == 400
    assert client.post("/api/projetos", json={"nome": "!!!", "pasta_origem": str(pasta_origem)}).status_code == 400


# ---------- 2.1 / 2.2 varredura ----------

def test_varredura_novos_sem_mudanca_alterado_removido(client, projeto, pasta_origem):
    antes = _instantaneo(pasta_origem)

    _executar(client, projeto)
    status = _status_docs(client, projeto)
    assert status == {
        "001_2026_Kim_Hyunso_Titulo_Um.md": "novo",
        "002_2025_QP1_Silva_Titulo_Dois.md": "novo",
        "sub/relatorio_sem_padrao.TXT": "novo",
    }

    _executar(client, projeto)
    assert set(_status_docs(client, projeto).values()) == {"sem_mudanca"}

    (pasta_origem / "002_2025_QP1_Silva_Titulo_Dois.md").write_text(texto_longo("Texto editado."), encoding="utf-8")
    depois_edicao = _instantaneo(pasta_origem)
    _executar(client, projeto)
    status = _status_docs(client, projeto)
    assert status["002_2025_QP1_Silva_Titulo_Dois.md"] == "alterado"
    assert status["001_2026_Kim_Hyunso_Titulo_Um.md"] == "sem_mudanca"

    (pasta_origem / "sub" / "relatorio_sem_padrao.TXT").unlink()
    _executar(client, projeto)
    assert _status_docs(client, projeto)["sub/relatorio_sem_padrao.TXT"] == "removido"

    # a varredura nunca escreve na pasta de origem
    final = _instantaneo(pasta_origem)
    assert final == {k: v for k, v in depois_edicao.items() if k in final}
    assert set(antes) - set(final) == {"sub/relatorio_sem_padrao.TXT"}


def test_varredura_novo_arquivo_e_metadados(client, projeto, pasta_origem):
    _executar(client, projeto)
    (pasta_origem / "003_2024_Souza_Outro.md").write_text(texto_longo("novo"), encoding="utf-8")
    _executar(client, projeto)
    docs = {d["arquivo"]: d for d in client.get(f"/api/projetos/{projeto}/documentos").json()}
    assert docs["003_2024_Souza_Outro.md"]["status"] == "novo"
    assert docs["001_2026_Kim_Hyunso_Titulo_Um.md"]["status"] == "sem_mudanca"
    d1 = docs["001_2026_Kim_Hyunso_Titulo_Um.md"]
    assert (d1["id_estudo"], d1["ano"], d1["autor"]) == ("001", 2026, "Kim")
    d2 = docs["002_2025_QP1_Silva_Titulo_Dois.md"]
    assert (d2["id_estudo"], d2["ano"], d2["autor"]) == ("002", 2025, "Silva")


def test_parse_nome():
    assert parse_nome("001_2026_Kim_Hyunso_Title.md") == {"id_estudo": "001", "ano": 2026, "autor": "Kim"}
    assert parse_nome("pasta/relatorio_livre.md") == {"id_estudo": None, "ano": None, "autor": None}


# ---------- 1.3 orquestrador ----------

@pytest.fixture()
def etapa_falsa():
    chamadas = []

    def funcao(ctx, doc):
        chamadas.append(doc.arquivo)
        return {"ok": True}

    orquestrador.registrar_etapa(orquestrador.Etapa(nome="falsa", ordem=50, escopo="documento", funcao=funcao))
    yield chamadas
    orquestrador.remover_etapa("falsa")


def _resumo_etapa(resumo, nome):
    return next(e for e in resumo["etapas"] if e["etapa"] == nome)


def test_orquestrador_pula_etapa_em_cache_e_invalida_com_parametro(client, projeto, etapa_falsa):
    r1 = _executar(client, projeto)
    assert _resumo_etapa(r1, "falsa")["ok"] == 3 and len(etapa_falsa) == 3

    r2 = _executar(client, projeto)
    assert _resumo_etapa(r2, "falsa")["pulado"] == 3 and len(etapa_falsa) == 3

    params = client.get(f"/api/projetos/{projeto}/parametros").json()
    params["kwic_janela"] = 15
    assert client.put(f"/api/projetos/{projeto}/parametros", json=params).status_code == 200
    r3 = _executar(client, projeto)
    assert _resumo_etapa(r3, "falsa")["ok"] == 3 and len(etapa_falsa) == 6

    r4 = _executar(client, projeto)
    assert _resumo_etapa(r4, "falsa")["pulado"] == 3 and len(etapa_falsa) == 6

    db = database.sessao_do_projeto(projeto)
    try:
        assert {e.status for e in db.scalars(select(Execucao).where(Execucao.etapa == "falsa"))} == {"ok", "pulado"}
    finally:
        db.close()


def test_orquestrador_reexecuta_so_o_documento_alterado(client, projeto, pasta_origem, etapa_falsa):
    _executar(client, projeto)
    etapa_falsa.clear()
    (pasta_origem / "001_2026_Kim_Hyunso_Titulo_Um.md").write_text(texto_longo("mudou"), encoding="utf-8")
    _executar(client, projeto)
    assert etapa_falsa == ["001_2026_Kim_Hyunso_Titulo_Um.md"]


def test_orquestrador_arquivos_identicos_nao_compartilham_cache(client, projeto, pasta_origem, etapa_falsa):
    original = pasta_origem / "001_2026_Kim_Hyunso_Titulo_Um.md"
    (pasta_origem / "copia.md").write_bytes(original.read_bytes())
    _executar(client, projeto)
    assert {"001_2026_Kim_Hyunso_Titulo_Um.md", "copia.md"} <= set(etapa_falsa)


def test_orquestrador_registra_erro_sem_derrubar_pipeline(client, projeto):
    def quebra(ctx, doc):
        raise RuntimeError("falhou")

    orquestrador.registrar_etapa(orquestrador.Etapa(nome="quebra", ordem=60, escopo="documento", funcao=quebra))
    try:
        r = _executar(client, projeto)
    finally:
        orquestrador.remover_etapa("quebra")
    assert _resumo_etapa(r, "quebra")["erro"] == 3
    assert r["erros"] == 3


def test_orquestrador_etapa_de_corpus_usa_hashes_dos_documentos(client, projeto, pasta_origem):
    chamadas = []
    orquestrador.registrar_etapa(
        orquestrador.Etapa(nome="corpus_falso", ordem=70, escopo="corpus", funcao=lambda ctx: chamadas.append(1))
    )
    try:
        _executar(client, projeto)
        _executar(client, projeto)
        assert len(chamadas) == 1
        (pasta_origem / "novo.md").write_text(texto_longo("x"), encoding="utf-8")
        _executar(client, projeto)
        assert len(chamadas) == 2
    finally:
        orquestrador.remover_etapa("corpus_falso")


# ---------- 1.4 parâmetros ----------

def test_parametros_padrao_e_versionamento(client, projeto, projetos_dir):
    p = client.get(f"/api/projetos/{projeto}/parametros").json()
    assert p["versao_parametros"] == 1
    assert p["idioma"] == ["en", "pt"] and p["kwic_janela"] == 10 and p["segmento_palavras"] == 40

    # salvar o mesmo conteúdo não muda a versão
    assert client.put(f"/api/projetos/{projeto}/parametros", json=p).json()["versao_parametros"] == 1

    p["kwic_janela"] = 12
    r = client.put(f"/api/projetos/{projeto}/parametros", json=p).json()
    assert r["versao_parametros"] == 2 and r["kwic_janela"] == 12

    p["lematizacao"]["ativa"] = False
    assert client.put(f"/api/projetos/{projeto}/parametros", json=p).json()["versao_parametros"] == 3

    historico = projetos_dir / projeto / "parametros_historico"
    assert sorted(f.name for f in historico.iterdir()) == ["parametros_v1.json", "parametros_v2.json"]
    assert json.loads((historico / "parametros_v1.json").read_text(encoding="utf-8"))["kwic_janela"] == 10
    assert json.loads((historico / "parametros_v2.json").read_text(encoding="utf-8"))["kwic_janela"] == 12


def test_hash_parametros_estavel_e_sensivel_ao_conteudo(tmp_path):
    a = parametros.parametros_padrao()
    b = dict(reversed(list(parametros.parametros_padrao().items())))  # outra ordem de chaves
    assert parametros.hash_parametros(a) == parametros.hash_parametros(b)
    b["kwic_janela"] = 11
    assert parametros.hash_parametros(a) != parametros.hash_parametros(b)


# ---------- API ----------

def test_api_raiz(client):
    assert client.get("/api").json() == {"status": "ok", "sistema": "Raio-X", "versao": "0.1.0-dev", "offline": False}


def test_api_projetos_listar_obter_404(client, projeto):
    lista = client.get("/api/projetos").json()
    assert [p["slug"] for p in lista] == [projeto]
    assert client.get(f"/api/projetos/{projeto}").json()["nome"] == "Meu Projeto"
    assert client.get("/api/projetos/nao-existe").status_code == 404
    assert client.get("/api/projetos/nao-existe/documentos").status_code == 404
    assert client.post("/api/projetos/nao-existe/executar?sincrono=1").status_code == 404


def test_api_execucoes_e_documentos(client, projeto):
    _executar(client, projeto)
    execs = client.get(f"/api/projetos/{projeto}/execucoes").json()
    assert execs and execs[0]["etapa"] == "comentarios"  # a mais recente (ordem 70)
    varredura = [e for e in execs if e["etapa"] == "varredura"]
    assert len(varredura) == 1 and varredura[0]["status"] == "ok"
    novos = client.get(f"/api/projetos/{projeto}/documentos", params={"status": "novo"}).json()
    assert len(novos) == 3


def test_orquestrador_parametro_ida_e_volta_reexecuta(client, projeto, etapa_falsa):
    """A → B → A: a volta para A precisa rodar de novo (os arquivos em cache são os de B)."""
    _executar(client, projeto)
    params = client.get(f"/api/projetos/{projeto}/parametros").json()
    original = params["kwic_janela"]
    for valor in (original + 5, original):
        params["kwic_janela"] = valor
        assert client.put(f"/api/projetos/{projeto}/parametros", json=params).status_code == 200
        _executar(client, projeto)
    assert len(etapa_falsa) == 9  # 3 docs × (inicial, B, volta para A)
    _executar(client, projeto)
    assert len(etapa_falsa) == 9  # sem mudança: pula
