"""Frente 5: resumo (MATTR, TF-IDF), frequências, tendências, KWIC, etapa descritivo e CSV. Sem Docling."""
import json
import os
import random
import time

import pytest

from app import database
from app.models import Analise
from app.services.analises import dados, resumo
from app.services.analises.resumo import mattr, termos_distintivos

EN = (
    "The agents solve tasks for the founders of the company, and the entrepreneurs use the models of the "
    "agentic systems in the study. "
)
EN2 = "Entrepreneurs build startups with agents and data; the platform helps teams to ship products. "
PT = (
    "As empresas usam os agentes para o desempenho das equipes, e o estudo mostra que os modelos são úteis "
    "para os fundadores. "
)
REFS = "\n".join(f"- Zebra, A. et al. ({2000 + i}). Zebra studies of agents. arXiv:2512.0000{i}." for i in range(8))


def _md(*paginas: str) -> str:
    return "<!-- Fonte: x.pdf | Conversão: Docling -->\n" + "".join(f"\n\n<!-- página {i + 1} -->\n\n{t}" for i, t in enumerate(paginas))


# ---------- 5.1 MATTR e TF-IDF (funções puras) ----------

def test_mattr_em_entrada_conhecida():
    assert mattr(list("abab"), 2) == (1.0, False)  # janelas ab, ba, ab: 2 tipos / 2
    valor, ttr = mattr(list("aabb"), 3)  # janelas aab, abb: 2 tipos / 3
    assert (round(valor, 6), ttr) == (round(2 / 3, 6), False)
    valor, ttr = mattr(list("aaaa"), 2)
    assert (valor, ttr) == (0.5, False)


def test_mattr_igual_a_forca_bruta_em_sequencia_aleatoria():
    rnd = random.Random(7)
    formas = [rnd.choice("abcdefghij") for _ in range(300)]
    j = 40
    esperado = sum(len(set(formas[i:i + j])) / j for i in range(len(formas) - j + 1)) / (len(formas) - j + 1)
    valor, ttr = mattr(formas, j)
    assert ttr is False and valor == pytest.approx(esperado)


def test_mattr_com_menos_tokens_que_a_janela_cai_para_ttr():
    assert mattr(["a", "b", "a"], 500) == (pytest.approx(2 / 3), True)
    assert mattr([], 500) == (None, True)
    assert mattr(["x"] * 499, 500) == (pytest.approx(1 / 499), True)
    assert mattr(["x"] * 500, 500)[1] is False


def test_termos_distintivos_tfidf():
    # 4 documentos; "comum" está em todos (idf 0), "raro" em 1, "medio" em 2
    df = {"comum": 4, "raro": 1, "medio": 2, "pouco": 1}
    contagem = {"comum": 50, "raro": 5, "medio": 5, "pouco": 2}
    r = termos_distintivos(contagem, tokens_doc=100, df=df, n_docs=4)
    assert [t["termo"] for t in r] == ["raro", "medio"]  # "comum" idf 0; "pouco" abaixo da frequência mínima 3
    assert r[0]["tfidf"] == pytest.approx(5 / 100 * 1.386294, abs=1e-4) and r[0]["freq"] == 5
    assert r[1]["tfidf"] == pytest.approx(5 / 100 * 0.693147, abs=1e-4)
    assert termos_distintivos(contagem, 100, df, n_docs=4, limite=1)[0]["termo"] == "raro"


# ---------- corpus sintético ----------

@pytest.fixture()
def corpus5(tmp_path):
    pasta = tmp_path / "corpus5"
    pasta.mkdir()
    (pasta / "001_2026_Kim_Ingles.md").write_text(_md(
        "## Abstract\n\n" + EN * 30 + "\n\nThe last word of the page is zephyr.",
        "Quasar opens the second page, and founders, however, rely on agents; the agent's tools (see Smith et al.) "
        "matter. " + "quokka " * 60 + "\n\n## 2 Method\n\n" + EN * 5 + "\n\n## References\n\n" + REFS),
        encoding="utf-8")
    (pasta / "002_2025_Silva_Portugues.md").write_text(_md(
        "## Resumo\n\n" + PT * 12, "## Método\n\n" + PT * 6 + "\n\n## Referências\n\n" + REFS), encoding="utf-8")
    (pasta / "003_2025_Lee_Terceiro.md").write_text(_md(
        "## Abstract\n\n" + EN2 * 15, "## Results\n\n" + EN2 * 8 + "zorblax " * 40), encoding="utf-8")
    return pasta


@pytest.fixture()
def projeto5(client, corpus5):
    r = client.post("/api/projetos", json={"nome": "Projeto F5", "pasta_origem": str(corpus5)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200 and r.json()["erros"] == 0, r.text
    docs = {d["arquivo"]: d for d in client.get(f"/api/projetos/{slug}/documentos").json()}
    for arq, grupo in (("001_2026_Kim_Ingles.md", "academica"), ("002_2025_Silva_Portugues.md", "cinzenta"),
                       ("003_2025_Lee_Terceiro.md", "cinzenta")):
        assert client.patch(f"/api/projetos/{slug}/documentos/{docs[arq]['id']}", json={"grupo": grupo}).status_code == 200
    assert client.post(f"/api/projetos/{slug}/executar?sincrono=1").status_code == 200  # o descritivo vê o grupo editado
    dados.limpar_caches()
    return slug


@pytest.fixture()
def ids(client, projeto5):
    docs = {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{projeto5}/documentos").json()}
    return {"A": docs["001_2026_Kim_Ingles.md"], "B": docs["002_2025_Silva_Portugues.md"], "C": docs["003_2025_Lee_Terceiro.md"]}


def _get(client, slug, caminho, **params):
    r = client.get(f"/api/projetos/{slug}/analises/{caminho}", params=params)
    assert r.status_code == 200, r.text
    return r


def _tokens(projetos_dir, slug, doc_id):
    return json.loads((projetos_dir / slug / "cache" / "tokens" / f"{doc_id}.json").read_text(encoding="utf-8"))


def _contar_lema(t, lema):
    return sum(1 for l, i in zip(t["lema"], t["incluir"]) if i and l == lema)


# ---------- 5.1 resumo ----------

def test_resumo_do_corpus_confere_com_os_tokens(client, projeto5, projetos_dir, ids):
    r = _get(client, projeto5, "resumo").json()
    c, docs = r["corpus"], {d["documento_id"]: d for d in r["documentos"]}
    assert c["n_documentos"] == 3 and set(docs) == set(ids.values())
    soma_corpo = soma_total = 0
    for doc_id, d in docs.items():
        t = _tokens(projetos_dir, projeto5, doc_id)
        corpo = [n for n, i in zip(t["norm"], t["incluir"]) if i]
        assert d["tokens"] == len(corpo) and d["tokens_total"] == t["n"]
        assert d["tipos_forma"] == len(set(corpo))
        assert d["tipos_lema"] == len({l for l, i in zip(t["lema"], t["incluir"]) if i})
        assert d["densidade"] == pytest.approx(len(set(corpo)) / len(corpo), abs=1e-4)
        soma_corpo += d["tokens"]
        soma_total += d["tokens_total"]
    assert c["tokens"] == soma_corpo and c["tokens_total"] == soma_total
    assert docs[ids["A"]]["tokens_total"] > docs[ids["A"]]["tokens"]  # referências fora do corpo
    assert docs[ids["C"]]["tokens_total"] == docs[ids["C"]]["tokens"]  # sem referências
    assert c["tipos_lema"] <= c["tipos_forma"]
    assert c["media_tokens"] == pytest.approx(soma_corpo / 3, abs=0.1)
    assert c["mediana_tokens"] == sorted(d["tokens"] for d in docs.values())[1]
    assert [x["documento_id"] for x in c["mais_longos"]][0] == max(docs, key=lambda i: docs[i]["tokens"])
    assert [x["documento_id"] for x in c["mais_curtos"]][0] == min(docs, key=lambda i: docs[i]["tokens"])
    assert len(c["mais_longos"]) == len(c["mais_curtos"]) == 3  # no máximo 5, o corpus só tem 3
    assert c["documentos_por_ano"] == [{"ano": "2025", "documentos": 2}, {"ano": "2026", "documentos": 1}]
    assert c["documentos_por_grupo"] == [{"grupo": "academica", "documentos": 1}, {"grupo": "cinzenta", "documentos": 2}]
    termos = [t["termo"] for t in c["top_termos"]]
    assert len(termos) == 15 and "agent" in termos
    assert not {"the", "of", "and", "et", "al"} & set(termos)  # palavras vazias fora
    assert c["mattr_janela"] == 500


def test_resumo_mattr_e_fallback_ttr(client, projeto5, ids):
    r = _get(client, projeto5, "resumo").json()
    docs = {d["documento_id"]: d for d in r["documentos"]}
    a = docs[ids["A"]]
    assert a["tokens"] >= 500 and a["mattr_ttr"] is False and 0 < a["mattr"] < 1
    assert docs[ids["B"]]["tokens"] < 500 and docs[ids["B"]]["mattr_ttr"] is True
    # só documentos com janela completa entram nos rankings de MATTR e na média
    assert [x["documento_id"] for x in r["corpus"]["maior_mattr"]] == [ids["A"]]
    assert r["corpus"]["mattr_documentos_comparaveis"] == 1 and r["corpus"]["mattr_media"] == a["mattr"]
    assert "Covington" in r["metodologia"]["mattr"] and "TF-IDF" in r["metodologia"]["termos_distintivos"]
    assert "não é keyness" in r["metodologia"]["termos_distintivos"]


def test_resumo_termos_distintivos_tfidf(client, projeto5, ids):
    r = _get(client, projeto5, "resumo").json()
    docs = {d["documento_id"]: d for d in r["documentos"]}
    distintos_a = [t["termo"] for t in docs[ids["A"]]["termos_distintivos"]]
    distintos_c = [t["termo"] for t in docs[ids["C"]]["termos_distintivos"]]
    assert "quokka" in distintos_a and "quokka" not in distintos_c
    assert "zorblax" in distintos_c and "zorblax" not in distintos_a
    for d in docs.values():
        assert len(d["termos_distintivos"]) <= 10
        assert not {"the", "of", "and"} & {t["termo"] for t in d["termos_distintivos"]}
        assert all(t["freq"] >= 3 for t in d["termos_distintivos"])
    quokka = next(t for t in docs[ids["A"]]["termos_distintivos"] if t["termo"] == "quokka")
    assert quokka["freq"] == 60 and quokka["tfidf"] > 0


def test_resumo_por_documento_e_metadados_editados_valem_sem_reexecutar(client, projeto5, ids):
    d = _get(client, projeto5, f"resumo/documentos/{ids['A']}").json()
    assert d["documento_id"] == ids["A"] and d["rotulo"] == "001 · Kim 2026" and d["paginas"] == 2
    assert d["pct_corpo"] is not None and 0 < d["pct_corpo"] < 100 and "metodologia" in d
    assert client.get(f"/api/projetos/{projeto5}/analises/resumo/documentos/9999").status_code == 404
    # editar o ano muda o resumo na hora
    assert client.patch(f"/api/projetos/{projeto5}/documentos/{ids['C']}", json={"ano": 2030}).status_code == 200
    anos = _get(client, projeto5, "resumo").json()["corpus"]["documentos_por_ano"]
    assert {a["ano"] for a in anos} == {"2025", "2026", "2030"}


# ---------- 5.2 frequências ----------

def test_frequencias_por_escopo(client, projeto5, projetos_dir, ids):
    t = {k: _tokens(projetos_dir, projeto5, i) for k, i in ids.items()}
    por_doc = {k: _contar_lema(t[k], "agent") for k in t}
    assert por_doc["A"] == 37  # 30 + 5 do corpo + "agents" + "agent's"; as 8 das referências ficam de fora

    def item(r, termo):
        return next((x for x in r["itens"] if x["termo"] == termo), None)

    corpus = _get(client, projeto5, "frequencias", limite=500).json()
    assert corpus["escopo"] == "corpus" and corpus["documentos"] == 3
    assert item(corpus, "agent")["freq"] == sum(por_doc.values())
    assert item(corpus, "agent")["docs"] == 2  # A e C; o PT usa "agente"
    assert item(corpus, "the") is None  # palavras vazias filtradas na consulta
    assert item(_get(client, projeto5, "frequencias", limite=500, vazias="manter").json(), "the") is not None

    doc = _get(client, projeto5, "frequencias", limite=500, escopo="documento", valor=ids["A"]).json()
    assert doc["documentos"] == 1 and item(doc, "agent")["freq"] == 37 and item(doc, "agent")["docs"] == 1
    assert item(doc, "zorblax") is None
    cinz = _get(client, projeto5, "frequencias", limite=500, escopo="grupo", valor="cinzenta").json()
    assert cinz["documentos"] == 2 and item(cinz, "agent")["freq"] == por_doc["C"]
    assert item(cinz, "quokka") is None and item(cinz, "zorblax")["freq"] == 40
    ano = _get(client, projeto5, "frequencias", limite=500, escopo="ano", valor="2025").json()
    assert ano["documentos"] == 2 and item(ano, "agent")["freq"] == por_doc["C"]
    assert ano["tokens"] == corpus["tokens"] - _get(client, projeto5, "frequencias", escopo="documento", valor=ids["A"]).json()["tokens"]
    # por 10 mil e ordenação
    assert item(corpus, "agent")["por_10k"] == pytest.approx(item(corpus, "agent")["freq"] / corpus["tokens"] * 10000, abs=0.01)
    freqs = [x["freq"] for x in corpus["itens"]]
    assert freqs == sorted(freqs, reverse=True)


def test_frequencias_lema_forma_curinga_e_filtro(client, projeto5):
    lema = _get(client, projeto5, "frequencias", filtro="agent*", limite=50).json()
    termos = {x["termo"] for x in lema["itens"]}
    assert {"agent", "agentic", "agente"} <= termos  # curinga: agent*, agentic, agente (PT)
    assert "task" not in termos and lema["tipos"] == len(termos)
    forma = _get(client, projeto5, "frequencias", por="forma", filtro="agent*", limite=50).json()
    formas = {x["termo"] for x in forma["itens"]}
    assert {"agents", "agentic", "agentes", "agent's"} <= formas and "agent" not in formas
    # sem curinga: trecho do termo
    assert {x["termo"] for x in _get(client, projeto5, "frequencias", filtro="zorb").json()["itens"]} == {"zorblax"}
    # exigências do escopo
    assert client.get(f"/api/projetos/{projeto5}/analises/frequencias", params={"escopo": "grupo"}).status_code == 422
    assert client.get(f"/api/projetos/{projeto5}/analises/frequencias", params={"escopo": "documento", "valor": 9999}).status_code == 404


def test_vocabulario_antigo_continua_funcionando(client, projeto5, ids):
    r = client.get(f"/api/projetos/{projeto5}/vocabulario", params={"limite": 5}).json()
    assert set(r) == {"por", "filtradas", "documentos", "tokens", "tipos", "itens"} and len(r["itens"]) == 5
    nova = _get(client, projeto5, "frequencias", limite=5).json()
    assert r["itens"] == nova["itens"] and r["tokens"] == nova["tokens"]
    um = client.get(f"/api/projetos/{projeto5}/vocabulario", params={"documento_id": ids["B"]}).json()
    assert um["documentos"] == 1


def test_tendencias_por_documento_ano_e_grupo(client, projeto5, projetos_dir, ids):
    t = {k: _tokens(projetos_dir, projeto5, i) for k, i in ids.items()}
    voc = json.loads((projetos_dir / projeto5 / "cache" / "vocabulario.json").read_text(encoding="utf-8"))
    tokens = {k: voc["documentos"][str(i)]["tokens"] for k, i in ids.items()}
    agent = {k: _contar_lema(t[k], "agent") for k in t}

    r = _get(client, projeto5, "tendencias", termos="agent, quokka", agrupar="documento").json()
    assert [c["rotulo"] for c in r["categorias"]] == ["001 · Kim 2026", "002 · Silva 2025", "003 · Lee 2025"]  # ordem do arquivo
    s = {x["termo"]: x for x in r["series"]}
    assert s["agent"]["brutos"] == [agent["A"], 0, agent["C"]]
    assert s["agent"]["rel"][0] == pytest.approx(agent["A"] / tokens["A"] * 10000, abs=0.01)
    assert s["agent"]["valores"] == s["agent"]["rel"] and s["quokka"]["brutos"] == [60, 0, 0]
    bruta = _get(client, projeto5, "tendencias", termos="agent", agrupar="documento", metrica="bruta").json()
    assert bruta["series"][0]["valores"] == [agent["A"], 0, agent["C"]] and bruta["metrica"] == "bruta"

    ano = _get(client, projeto5, "tendencias", termos="agent", agrupar="ano").json()
    assert [c["rotulo"] for c in ano["categorias"]] == ["2025", "2026"]
    assert ano["series"][0]["brutos"] == [agent["C"], agent["A"]]
    assert ano["categorias"][0]["tokens"] == tokens["B"] + tokens["C"]
    assert ano["series"][0]["rel"][0] == pytest.approx(agent["C"] / (tokens["B"] + tokens["C"]) * 10000, abs=0.01)

    grupo = _get(client, projeto5, "tendencias", termos="agent", agrupar="grupo", metrica="bruta").json()
    assert [c["rotulo"] for c in grupo["categorias"]] == ["academica", "cinzenta"]
    assert grupo["series"][0]["valores"] == [agent["A"], agent["C"]]


def test_tendencias_curinga_forma_e_limite_de_6_termos(client, projeto5):
    r = _get(client, projeto5, "tendencias", termos="agent*", por="lema", agrupar="grupo", metrica="bruta").json()
    cinz = r["series"][0]["brutos"][1]
    r2 = _get(client, projeto5, "tendencias", termos="agent", por="lema", agrupar="grupo", metrica="bruta").json()
    assert cinz > r2["series"][0]["brutos"][1]  # agent* soma agent + agentic + agente
    forma = _get(client, projeto5, "tendencias", termos="agents", por="forma", agrupar="documento", metrica="bruta").json()
    assert forma["series"][0]["brutos"][0] > 0
    assert _get(client, projeto5, "tendencias", termos="agents", por="lema", agrupar="documento", metrica="bruta").json()["series"][0]["brutos"] == [0, 0, 0]
    muitos = _get(client, projeto5, "tendencias", termos="a1,b2,c3,d4,e5,f6,g7,h8").json()
    assert len(muitos["series"]) == 6
    assert client.get(f"/api/projetos/{projeto5}/analises/tendencias", params={"termos": " , "}).status_code == 422


# ---------- 5.3 KWIC ----------

def test_kwic_lema_acha_formas_flexionadas_e_traz_pagina_e_texto_original(client, projeto5, ids):
    r = _get(client, projeto5, "kwic", q="agent", escopo="documento", valor=ids["A"], janela=3, limit=2000).json()
    termos = {x["termo"] for x in r["itens"]}
    assert {"agents", "agent's"} <= termos and "agent" not in termos  # lema agent: formas do texto
    assert r["total"] == len(r["itens"]) == 37 and r["documentos_com_ocorrencias"] == 1
    linha = next(x for x in r["itens"] if x["termo"] == "agent's")
    assert linha["pagina"] == 2 and linha["rotulo"] == "001 · Kim 2026" and linha["secao"]
    assert linha["documento_id"] == ids["A"] and linha["arquivo"] == "001_2026_Kim_Ingles.md"
    # pontuação preservada: "agents; the agent's tools (see"
    assert linha["esquerda"].endswith("agents; the") and linha["direita"].startswith("tools (see")
    ponto_e_virgula = next(x for x in r["itens"] if x["termo"] == "agents" and x["pagina"] == 2 and "rely" in x["esquerda"])
    assert ponto_e_virgula["direita"].startswith("; the agent's")
    # página 1 para as ocorrências da primeira página
    assert {x["pagina"] for x in r["itens"]} == {1, 2}
    # por forma: só a forma exata
    f = _get(client, projeto5, "kwic", q="agents", por="forma", escopo="documento", valor=ids["A"], limit=2000).json()
    assert {x["termo"] for x in f["itens"]} == {"agents"} and f["total"] == 36
    # lema não acha pela forma flexionada
    assert _get(client, projeto5, "kwic", q="agents", por="lema").json()["total"] == 0


def test_kwic_consulta_com_virgulas_e_curinga(client, projeto5, ids):
    r = _get(client, projeto5, "kwic", q="quokka, zorblax", limit=500).json()
    assert r["total"] == 100 and r["documentos_com_ocorrencias"] == 2
    assert [x["rotulo"] for x in r["itens"]][:1] == ["001 · Kim 2026"]  # ordem do corpus
    w = _get(client, projeto5, "kwic", q="agent*", escopo="documento", valor=ids["B"], limit=500).json()
    assert w["total"] > 0 and {x["termo"] for x in w["itens"]} == {"agentes"}  # curinga no lema PT: "agente"
    assert {f["forma"] for f in _get(client, projeto5, "kwic", q="agent*", limit=1).json()["formas"]} >= {"agent", "agentic", "agente"}


def test_kwic_marca_fronteira_de_bloco(client, projeto5, ids):
    r = _get(client, projeto5, "kwic", q="zephyr", janela=5).json()
    assert r["total"] == 1
    linha = r["itens"][0]
    assert linha["pagina"] == 1 and linha["termo"] == "zephyr"
    assert linha["esquerda"].endswith("of the page is")
    # a janela da direita atravessa a quebra de página (bloco): marcada com " … ", sem juntar as frases
    assert linha["direita"] == ". … Quasar opens the second page"
    inicio = _get(client, projeto5, "kwic", q="quasar", janela=5).json()["itens"][0]
    assert inicio["pagina"] == 2 and inicio["esquerda"].endswith("zephyr. …")
    # janela pequena que não atravessa: sem marca
    assert " … " not in _get(client, projeto5, "kwic", q="zorblax", janela=2, limit=1).json()["itens"][0]["direita"]


def test_kwic_secoes_excluidas_ficam_fora_por_padrao(client, projeto5, ids):
    padrao = _get(client, projeto5, "kwic", q="zebra", por="forma").json()
    assert padrao["total"] == 0  # só aparece nas referências
    todas = _get(client, projeto5, "kwic", q="zebra", por="forma", incluir_excluidas="true", limit=100).json()
    assert todas["total"] == 32 and all  # 2 por linha de referência, nos documentos A e B(not x["corpo"] and x["secao"] == "referencias" for x in todas["itens"])
    ag = _get(client, projeto5, "kwic", q="agent", escopo="documento", valor=ids["A"], incluir_excluidas="true", limit=1).json()
    assert ag["total"] == 37 + 8  # as 8 "agents" das referências
    # com as excluídas desligadas, o contexto do corpo não invade as referências
    estudo = _get(client, projeto5, "kwic", q="study", escopo="documento", valor=ids["A"], janela=100, limit=2000).json()
    assert any(x["pagina"] == 2 for x in estudo["itens"])
    for x in _get(client, projeto5, "kwic", q="study", escopo="documento", valor=ids["A"], janela=100, limit=2000).json()["itens"]:
        assert "Zebra" not in x["direita"] and "arXiv" not in x["direita"]


def test_kwic_ordenacao(client, projeto5):
    base = _get(client, projeto5, "kwic", q="founders", por="forma", janela=3, limit=2000).json()["itens"]
    esq = _get(client, projeto5, "kwic", q="founders", por="forma", janela=3, ordem="esquerda", limit=2000).json()["itens"]
    dire = _get(client, projeto5, "kwic", q="founders", por="forma", janela=3, ordem="direita", limit=2000).json()["itens"]
    assert len(base) == len(esq) == len(dire) > 0
    assert sorted(x["posicao"] for x in base) == sorted(x["posicao"] for x in esq)

    def ultima(txt):
        return txt.split()[-1].lower().strip(",.;()") if txt.split() else ""

    def primeira(txt):
        return txt.split()[0].lower().strip(",.;()") if txt.split() else ""

    esquerdas = [ultima(x["esquerda"]) for x in esq]
    direitas = [primeira(x["direita"]) for x in dire]
    assert esquerdas == sorted(esquerdas) and direitas == sorted(direitas)
    # corpus: ordem de documento e posição
    pares = [(x["documento_id"], x["posicao"]) for x in base]
    assert pares == sorted(pares)


def test_kwic_paginacao_e_total(client, projeto5):
    todas = _get(client, projeto5, "kwic", q="agent", limit=2000).json()
    assert todas["total"] == len(todas["itens"]) == 60  # 37 (A) + 23 (C)
    p1 = _get(client, projeto5, "kwic", q="agent", limit=10, offset=0).json()
    p2 = _get(client, projeto5, "kwic", q="agent", limit=10, offset=10).json()
    assert p1["total"] == p2["total"] == todas["total"] and len(p1["itens"]) == len(p2["itens"]) == 10
    assert p1["itens"] + p2["itens"] == todas["itens"][:20]
    ultima = _get(client, projeto5, "kwic", q="agent", limit=10, offset=todas["total"] - 3).json()
    assert len(ultima["itens"]) == 3 and ultima["offset"] == todas["total"] - 3
    assert _get(client, projeto5, "kwic", q="agent", limit=10, offset=10**6).json()["itens"] == []
    assert client.get(f"/api/projetos/{projeto5}/analises/kwic", params={"q": "agent", "limit": 99999}).status_code == 422


def test_kwic_janela_padrao_vem_dos_parametros(client, projeto5, ids):
    p = client.get(f"/api/projetos/{projeto5}/parametros").json()
    p.pop("hash_parametros"); p.pop("versao_parametros")
    p["kwic_janela"] = 4
    assert client.put(f"/api/projetos/{projeto5}/parametros", json=p).status_code == 200
    r = _get(client, projeto5, "kwic", q="zorblax", limit=1).json()
    assert r["janela"] == 4
    assert len(r["itens"][0]["esquerda"].split()) <= 4 and len(r["itens"][0]["direita"].split()) <= 4
    assert _get(client, projeto5, "kwic", q="zorblax", limit=1, janela=2).json()["janela"] == 2


def test_kwic_contexto_ampliado_e_citacao(client, projeto5, ids):
    linha = _get(client, projeto5, "kwic", q="zephyr", janela=3).json()["itens"][0]
    r = _get(client, projeto5, "kwic/contexto", documento_id=linha["documento_id"], posicao=linha["posicao"]).json()
    assert r["termo"] == "zephyr" and r["pagina"] == 1 and r["janela"] == 60
    assert r["citacao"] == "(001 · Kim 2026, p. 1)"
    assert len(r["esquerda"]) > len(linha["esquerda"]) and "The last word of the page is" in r["esquerda"]
    assert " … Quasar opens" in r["direita"] or "Quasar opens" in r["direita"]
    assert r["trecho"].count("zephyr") == 1 and r["citacao_completa"].endswith("(001 · Kim 2026, p. 1)")
    assert r["trecho"] in r["citacao_completa"]
    # outra página
    q = _get(client, projeto5, "kwic", q="zorblax", limit=1).json()["itens"][0]
    c = _get(client, projeto5, "kwic/contexto", documento_id=q["documento_id"], posicao=q["posicao"], janela=10).json()
    assert c["citacao"] == "(003 · Lee 2025, p. 2)" and c["termo"] == "zorblax"
    assert client.get(f"/api/projetos/{projeto5}/analises/kwic/contexto", params={"documento_id": 9999, "posicao": 0}).status_code == 404
    assert client.get(f"/api/projetos/{projeto5}/analises/kwic/contexto",
                      params={"documento_id": ids["A"], "posicao": 10**7}).status_code == 404


# ---------- CSV ----------

def test_csv_de_frequencias_e_kwic(client, projeto5):
    r = client.get(f"/api/projetos/{projeto5}/analises/frequencias.csv", params={"limite": 20})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and "frequencias.csv" in r.headers["content-disposition"]
    assert r.content.startswith("﻿".encode("utf-8"))
    linhas = r.content.decode("utf-8-sig").strip().split("\r\n")
    assert linhas[0] == "posicao;termo;frequencia;por_10_mil;documentos" and len(linhas) == 21
    assert linhas[1].split(";")[0] == "1" and "," in linhas[1].split(";")[3]  # decimal com vírgula

    k = client.get(f"/api/projetos/{projeto5}/analises/kwic.csv", params={"q": "zorblax"})
    assert k.status_code == 200 and k.content.startswith("﻿".encode("utf-8"))
    linhas = k.content.decode("utf-8-sig").strip().split("\r\n")
    assert linhas[0] == "documento;arquivo;pagina;secao;esquerda;termo;direita" and len(linhas) == 41  # 40 ocorrências + cabeçalho
    assert linhas[1].startswith("003 · Lee 2025;003_2025_Lee_Terceiro.md;2;")
    assert ";zorblax;" in linhas[1]


def test_consultas_sem_pipeline_dao_404(client, projeto):
    for caminho in ("resumo", "frequencias", "tendencias?termos=a", "kwic?q=a", "kwic.csv?q=a", "frequencias.csv"):
        assert client.get(f"/api/projetos/{projeto}/analises/{caminho}").status_code == 404, caminho


# ---------- etapa descritivo ----------

def _analises(slug):
    db = database.sessao_do_projeto(slug)
    try:
        # só os instantâneos do descritivo (keyness e similaridade têm etapas próprias: test_frente61 e test_frente63_64)
        linhas = db.query(Analise).filter(Analise.tipo.in_(("resumo", "frequencias"))).order_by(Analise.id).all()
        return {a.tipo: a for a in linhas}, len(linhas)
    finally:
        db.close()


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return {e["etapa"]: e for e in r.json()["etapas"]}


def test_etapa_descritivo_grava_analises(client, projeto5):
    por_tipo, total = _analises(projeto5)
    assert total == 2 and set(por_tipo) == {"resumo", "frequencias"}
    res, fre = por_tipo["resumo"], por_tipo["frequencias"]
    assert res.ferramenta_equivalente == "Voyant Summary / IRaMuTeQ estatísticas"
    assert fre.ferramenta_equivalente == "Voyant Terms/Cirrus, AntConc Word list"
    pr = json.loads(res.parametros_json)
    assert pr["lematizacao"]["ativa"] is True and pr["mattr_janela"] == 500 and "palavras_vazias" in pr
    assert "kwic_janela" not in pr
    pf = json.loads(fre.parametros_json)
    assert (pf["por"], pf["escopo"], pf["limite"]) == ("lema", "corpus", 500)
    r = json.loads(res.resultado_json)
    assert r["corpus"]["n_documentos"] == 3 and len(r["documentos"]) == 3
    f = json.loads(fre.resultado_json)
    assert f["itens"][0]["freq"] >= f["itens"][-1]["freq"] and len(f["itens"]) <= 500
    # o instantâneo coincide com a consulta feita na hora
    assert r == _get(client, projeto5, "resumo").json()
    assert f["itens"][:20] == _get(client, projeto5, "frequencias", limite=20).json()["itens"]


def test_descritivo_substitui_linhas_na_reexecucao_e_respeita_o_cache(client, projeto5):
    antes, _ = _analises(projeto5)
    ids_antes = {t: a.id for t, a in antes.items()}
    etapas = _executar(client, projeto5)
    assert etapas["descritivo"]["pulado"] == 1  # nada mudou: cache
    assert {t: a.id for t, a in _analises(projeto5)[0].items()} == ids_antes

    p = client.get(f"/api/projetos/{projeto5}/parametros").json()
    p.pop("hash_parametros"); p.pop("versao_parametros")
    p["kwic_janela"] = 25  # não é relevante para o descritivo
    assert client.put(f"/api/projetos/{projeto5}/parametros", json=p).status_code == 200
    etapas = _executar(client, projeto5)
    assert etapas["descritivo"]["pulado"] == 1 and etapas["vocabulario"]["pulado"] == 1

    p["palavras_vazias"]["proprias"] = ["quokka"]  # relevante: reexecuta e substitui as linhas
    assert client.put(f"/api/projetos/{projeto5}/parametros", json=p).status_code == 200
    etapas = _executar(client, projeto5)
    assert etapas["descritivo"]["ok"] == 1 and etapas["vocabulario"]["pulado"] == 1  # vocabulário não depende das vazias
    depois, total = _analises(projeto5)
    assert total == 2 and all(depois[t].criado_em > antes[t].criado_em for t in depois)  # substituídas, não acumuladas
    termos = {t["termo"] for t in json.loads(depois["frequencias"].resultado_json)["itens"]}
    assert "quokka" not in termos
    assert "quokka" not in {t["termo"] for d in json.loads(depois["resumo"].resultado_json)["documentos"] for t in d["termos_distintivos"]}
    assert json.loads(depois["resumo"].parametros_json)["palavras_vazias"]["proprias"] == ["quokka"]


def test_descritivo_reexecuta_quando_a_lematizacao_muda_e_quando_os_metadados_mudam(client, projeto5, ids):
    p = client.get(f"/api/projetos/{projeto5}/parametros").json()
    p.pop("hash_parametros"); p.pop("versao_parametros")
    p["lematizacao"]["ativa"] = False
    assert client.put(f"/api/projetos/{projeto5}/parametros", json=p).status_code == 200
    etapas = _executar(client, projeto5)
    assert etapas["linguistica"]["ok"] == 3 and etapas["vocabulario"]["ok"] == 1 and etapas["descritivo"]["ok"] == 1
    termos = {t["termo"] for t in json.loads(_analises(projeto5)[0]["frequencias"].resultado_json)["itens"]}
    assert "agents" in termos and "agent" not in termos  # sem lematização: lema = forma

    assert client.patch(f"/api/projetos/{projeto5}/documentos/{ids['B']}", json={"grupo": "outro"}).status_code == 200
    etapas = _executar(client, projeto5)
    assert etapas["descritivo"]["ok"] == 1 and etapas["vocabulario"]["pulado"] == 1  # metadado editado: só o descritivo
    grupos = json.loads(_analises(projeto5)[0]["resumo"].resultado_json)["corpus"]["documentos_por_grupo"]
    assert {g["grupo"] for g in grupos} == {"academica", "cinzenta", "outro"}


# ---------- cache em processo ----------

def test_cache_de_tokens_e_indice_por_mtime(projeto5, projetos_dir, ids):
    pasta = projetos_dir / projeto5
    dados.limpar_caches()
    t1 = dados.carregar_tokens(pasta, ids["A"])
    assert dados.carregar_tokens(pasta, ids["A"]) is t1
    idx = dados.indice_do_documento(t1)
    assert dados.indice_do_documento(t1) is idx
    assert idx["lema"]["agent"] == [i for i, l in enumerate(t1["lema"]) if l == "agent"]
    assert idx["norm"]["agents"] == [i for i, n in enumerate(t1["norm"]) if n == "agents"]
    assert all(isinstance(x, str) for x in t1["forma"][:5])
    # mudou o arquivo (pipeline reexecutado): o cache é invalidado pelo mtime
    caminho = pasta / "cache" / "tokens" / f"{ids['A']}.json"
    os.utime(caminho, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
    t2 = dados.carregar_tokens(pasta, ids["A"])
    assert t2 is not t1 and t2["n"] == t1["n"]
    assert dados.carregar_blocos(pasta, ids["A"]) is dados.carregar_blocos(pasta, ids["A"])
    assert dados.carregar_tokens(pasta, 99999) is None


def test_consulta_com_curinga_compilada():
    itens = dados.compilar_consulta("Agent*, *ing, a*b, exato, **, ")
    assert [i["texto"] for i in itens] == ["agent*", "*ing", "a*b", "exato"]
    chaves = {"agent": 1, "agents": 1, "learning": 1, "ab": 1, "axxb": 1, "exato": 1, "exatos": 1}
    assert set(dados.chaves_que_casam(itens, chaves)) == {"agent", "agents", "learning", "ab", "axxb", "exato"}
    assert dados.termos_da_lista("a, B , a, c*,d,e,f,g") == ["a", "b", "c*", "d", "e", "f"]
