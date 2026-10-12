"""15.8 Keyness contra corpus de referência: leitura da lista (separadores, cabeçalho, milhar, total), lematização da lista,
contagem de pasta de textos, cálculo conferido à mão (G² de 2 células), OOV, API e CSV com um corpus sintético."""
import math

import pytest

from app.services.analises import keyness
from app.services.analises import keyness_referencia as kr


def test_ler_lista_separadores_cabecalho_e_milhar():
    f, total = kr.ler_lista("termo;frequencia\nThe;1.234\nagent;50\n# total: 10.000\n", None)
    assert f == {"the": 1234, "agent": 50} and total == 10000
    f, _ = kr.ler_lista("the\t10\nof\t5\n", None)
    assert f == {"the": 10, "of": 5}
    f, _ = kr.ler_lista("the,10\nThe,5\n", None)  # repetidos somam depois de normalizar
    assert f == {"the": 15}
    f, total = kr.ler_lista("a;3\n", 99)
    assert total == 99


def test_ler_lista_invalida():
    with pytest.raises(kr.ReferenciaInvalida):
        kr.ler_lista("", None)
    with pytest.raises(kr.ReferenciaInvalida):
        kr.ler_lista("so um texto\noutro texto\n", None)
    with pytest.raises(kr.ReferenciaInvalida):
        kr.ler_lista("a;x\nb;y\nc;z\n", None)


def test_lematizar_lista_soma_formas():
    r = kr.lematizar_lista({"agents": 10, "agent": 5, "running": 3}, "en")
    assert r["agent"] == 15


def test_importar_lista_e_textos(tmp_path):
    pasta = tmp_path / "proj"
    pasta.mkdir()
    m = kr.importar_lista(pasta, "Lista X", "the;100\nagents;20\nagent;10\n", "en", fonte="teste", total=1000)
    assert m["id"] == "lista-x" and m["tokens"] == 1000 and m["total_declarado"] and m["tipos_lema"] == 2
    m2 = kr.importar_lista(pasta, "Lista X", "the;1\n", "en")
    assert m2["id"] == "lista-x-2" and m2["tokens"] == 1 and not m2["total_declarado"]
    assert sorted(x["id"] for x in kr.listar(pasta)) == ["lista-x", "lista-x-2"]
    with pytest.raises(kr.ReferenciaInvalida):
        kr.importar_lista(pasta, "Y", "the;100\n", "en", total=10)  # total menor que a soma
    with pytest.raises(kr.ReferenciaInvalida):
        kr.importar_lista(pasta, "Y", "the;1\n", "fr")
    assert kr.remover(pasta, "lista-x") and not kr.remover(pasta, "lista-x")
    with pytest.raises(kr.ReferenciaInvalida):
        kr.remover(pasta, "../fora")  # identificador não pode sair da pasta

    txt = tmp_path / "textos"
    txt.mkdir()
    (txt / "a.txt").write_text("Agents run. The agents plan and the agent acts.", encoding="utf-8")
    (txt / "b.md").write_text("Planning is hard.", encoding="utf-8")
    mt = kr.importar_textos(pasta, "Pasta", txt, "en")
    ref = kr.carregar(pasta, mt["id"])
    assert mt["tipo"] == "textos" and mt["arquivos"] == 2 and ref["formas"]["agents"] == 2
    assert ref["lemas"]["agent"] == 3 and mt["tokens"] == sum(ref["formas"].values())


def _voc(docs):
    """Vocabulário mínimo: {id: {lema: n}} (lema = forma)."""
    voc = {"documentos": {}}
    for i, mapa in docs.items():
        pares = [[t, t, n] for t, n in mapa.items()]
        voc["documentos"][str(i)] = {"tokens": sum(mapa.values()), "lema": dict(mapa), "norma": dict(mapa), "pares": pares}
    return voc


def test_calculo_a_mao_e_oov():
    voc = _voc({1: {"agent": 25, "zeta": 10, "the": 50, "outro": 415}, 2: {"agent": 25, "zeta": 10, "the": 50, "outro": 415}})
    metas = [{"id": 1}, {"id": 2}]
    ref = {"meta": {"id": "r", "nome": "R", "tokens": 100000, "total_declarado": True, "tipo": "lista"},
           "formas": {"agent": 10, "the": 5000, "outro": 40000, "raro": 3000}, "lemas": {"agent": 10, "the": 5000, "outro": 40000, "raro": 3000}}
    r = kr.calcular(voc, metas, frozenset(), ref, por="lema", min_freq=5, min_docs=2, p=0.01, limite=10)
    c, d = 1000, 100000
    a, b = 50, 10
    esperado = keyness.log_likelihood(a, b, c, d)
    agent = next(k for k in r["positivas"] if k["termo"] == "agent")
    assert agent["g2"] == pytest.approx(esperado)
    e1, e2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
    assert esperado == pytest.approx(2 * (a * math.log(a / e1) + b * math.log(b / e2)))
    assert agent["log_ratio"] == pytest.approx(math.log2((50 / 1000) / (10 / 100000))) and not agent["oov"]
    zeta = next(k for k in r["positivas"] if k["termo"] == "zeta")
    assert zeta["oov"] and zeta["b"] == 0 and zeta["log_ratio"] == pytest.approx(math.log2((20 / 1000) / (0.5 / 100000)))
    assert r["oov_testados"] == 1 and r["ocorrencias_oov"] == 20
    raro = next(k for k in r["negativas"] if k["termo"] == "raro")  # só na referência: sub-representado no corpus
    assert raro["so_em_b"] and raro["a"] == 0
    assert r["referencia"]["nome"] == "R" and r["corpus"]["tokens"] == 1000 and r["aviso_comparavel"]
    sem = kr.calcular(voc, metas, frozenset(), ref, por="lema", oov="excluir", limite=10)
    assert all(not k["oov"] for k in sem["positivas"])
    vz = kr.calcular(voc, metas, frozenset({"agent"}), ref, por="lema", limite=10)  # palavras vazias saem da consulta
    assert all(k["termo"] != "agent" for k in vz["positivas"])
    with pytest.raises(kr.ReferenciaInvalida):
        kr.calcular(voc, metas, frozenset(), {"meta": ref["meta"], "formas": {"a": 1}, "lemas": None}, por="lema")


def test_referencia_menor_gera_aviso():
    voc = _voc({1: {"a": 1000, "b": 1000}})
    ref = {"meta": {"id": "r", "nome": "R", "tokens": 10, "total_declarado": False, "tipo": "lista"}, "formas": {"a": 10}, "lemas": {"a": 10}}
    r = kr.calcular(voc, [{"id": 1}], frozenset(), ref, por="forma", min_freq=1)
    assert len(r["avisos"]) == 2


@pytest.fixture()
def corpus_ref(client, tmp_path):
    pasta = tmp_path / "corpus"
    pasta.mkdir()
    for i in (1, 2, 3):
        corpo = ("The agentic startup uses agents for founders. " * 15 + f"Founders build agents with zorblax{i} tools. " * 10) * 2
        (pasta / f"{i:03d}_2025_Autor{i}_Titulo.md").write_text("# Study\n\n" + corpo, encoding="utf-8")
    slug = client.post("/api/projetos", json={"nome": "kr", "pasta_origem": str(pasta)}).json()["slug"]
    assert client.post(f"/api/projetos/{slug}/executar?sincrono=1").status_code == 200
    return slug


def test_api_keyness_referencia(client, corpus_ref):
    slug = corpus_ref
    base = f"/api/projetos/{slug}"
    assert client.get(f"{base}/referencias").json()["itens"] == []
    assert client.get(f"{base}/analises/keyness-referencia", params={"referencia": "nada"}).status_code == 404
    lista = "termo;frequencia\nthe;60000\nuses;300\nfor;20000\nwith;15000\nbuild;100\nfounders;3\nagents;4\nof;50000\n"
    r = client.post(f"{base}/referencias", json={"nome": "Sintética", "idioma": "en", "fonte": "teste", "conteudo": lista, "total": 1000000})
    assert r.status_code == 201, r.text
    ref_id = r.json()["id"]
    assert client.post(f"{base}/referencias", json={"nome": "Z", "idioma": "en"}).status_code == 422
    assert client.post(f"{base}/referencias", json={"nome": "Z", "idioma": "en", "caminho": "pasta_que_nao_existe"}).status_code == 422
    assert [x["id"] for x in client.get(f"{base}/referencias").json()["itens"]] == [ref_id]
    r = client.get(f"{base}/analises/keyness-referencia", params={"referencia": ref_id, "min_freq": 5, "min_docs": 2})
    assert r.status_code == 200, r.text
    j = r.json()
    termos = {k["termo"]: k for k in j["positivas"]}
    assert j["referencia"]["nome"] == "Sintética" and j["referencia"]["tokens"] == 1000000
    assert "founder" in termos and "agent" in termos  # contagem por lema
    assert j["aviso_comparavel"] and j["oov_testados"] >= 1
    f = client.get(f"{base}/analises/keyness-referencia", params={"referencia": ref_id, "por": "forma", "oov": "excluir"}).json()
    assert all(not k["oov"] for k in f["positivas"])
    assert client.get(f"{base}/analises/keyness-referencia", params={"referencia": ref_id, "escopo": "grupo", "valor": "inexistente"}).status_code == 422
    csv = client.get(f"{base}/analises/keyness-referencia.csv", params={"referencia": ref_id})
    assert csv.status_code == 200 and "freq_corpus" in csv.text and "# referencia;Sintética" in csv.text
    assert client.delete(f"{base}/referencias/{ref_id}").status_code == 204
    assert client.delete(f"{base}/referencias/{ref_id}").status_code == 404
