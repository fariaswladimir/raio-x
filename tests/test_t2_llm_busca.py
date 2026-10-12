"""Lote T2 (12/10/2026): cache de prompt (item 0), classificação por LLM (15.11), embeddings via Ollama (15.12) e
"Perguntar ao corpus" (15.13). Sem chamadas reais: SDK da Anthropic, Ollama e embeddings são simulados."""
import json
import math
from types import SimpleNamespace

import anthropic
import numpy as np
import pytest

from app.database import pasta_do_projeto
from app.services.busca import bm25, embeddings, rag
from app.services.concordancia import classificador as clf
from app.services.concordancia import codificador
from app.services.llm import cache_prompt, config, precos
from app.services.llm.provedores import ProvedorAnthropic
from tests.test_frente151_codificacao import CODEBOOK, ProvedorFalso, _planilha, cfg_llm, proj_cod  # noqa: F401


# ---------- item 0: cache de prompt ----------

def test_blocos_system_so_o_ultimo_leva_cache_control():
    b = cache_prompt.blocos_system("instruções", "", "codebook")
    assert [x["text"] for x in b] == ["instruções", "codebook"]
    assert "cache_control" not in b[0] and b[1]["cache_control"] == {"type": "ephemeral"}
    assert cache_prompt.system_como_texto(b) == "instruções\n\ncodebook" and cache_prompt.system_como_texto("x") == "x"
    assert cache_prompt.json_estavel({"b": 1, "a": [2, 1]}) == '{"a":[2,1],"b":1}'
    assert sorted(["C1.10", "C1.2", "C1.1"], key=cache_prompt.chave_natural) == ["C1.1", "C1.2", "C1.10"]


def test_codebook_serializado_de_forma_deterministica():
    cats = [{"id": "C1.10", "nome": "b", "descricao": "regra  com\nquebra"}, {"id": "C1.2", "nome": "a", "descricao": "x"}]
    assert codificador.texto_codebook(cats) == codificador.texto_codebook(list(reversed(cats)))
    assert codificador.texto_codebook(cats).splitlines()[0].startswith("- C1.2 |") and "regra com quebra" in codificador.texto_codebook(cats)


class ClienteSdk:
    """Faz as vezes de anthropic.Anthropic: registra os pedidos e devolve uso com tokens de cache."""
    chamadas: list = []

    def __init__(self, **kw):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: self._criar("beta", k)))
        self.messages = SimpleNamespace(create=lambda **k: self._criar("messages", k))

    def _criar(self, via, kw):
        n = len(ClienteSdk.chamadas)
        ClienteSdk.chamadas.append((via, kw))
        uso = SimpleNamespace(input_tokens=50, output_tokens=20, cache_creation_input_tokens=1000 if n == 0 else 0,
                              cache_read_input_tokens=0 if n == 0 else 1000)
        texto = json.dumps({"codigo": "C1.1", "justificativa": "ok", "confianca": 0.9})
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], _request_id=f"req_{n}", usage=uso, stop_details=None,
                               content=[SimpleNamespace(type="text", text=texto)])


def test_codificacao_com_anthropic_envia_prefixo_identico_com_cache_e_registra_uso(client, proj_cod, cfg_llm, monkeypatch):  # noqa: F811
    url = f"/api/projetos/{proj_cod}/codificacao"
    client.post(f"{url}/importar", content=_planilha())
    config.salvar({"habilitado": True, "provedor": "anthropic", "anthropic": {"modelo": "claude-sonnet-5-5"}})
    ClienteSdk.chamadas = []
    monkeypatch.setattr(anthropic, "Anthropic", ClienteSdk)
    monkeypatch.setattr(codificador, "provedor_configurado", lambda cfg=None: ProvedorAnthropic("sk-teste-1234567890", "claude-sonnet-5-5"))
    r = client.post(f"{url}/codificar", params={"sincrono": 1}, json={"limite": 4})
    assert r.status_code == 200 and r.json()["feitos"] == 4
    ch = ClienteSdk.chamadas
    assert len(ch) == 4 and all(via == "beta" for via, _ in ch)
    systems = [json.dumps(kw["system"], ensure_ascii=False, sort_keys=False) for _, kw in ch]
    assert len(set(systems)) == 1  # byte a byte igual em todos os trechos
    blocos = ch[0][1]["system"]
    assert isinstance(blocos, list) and len(blocos) == 2
    assert "cache_control" not in blocos[0] and blocos[1]["cache_control"] == {"type": "ephemeral"}
    assert "Metáfora explícita" in blocos[1]["text"] and "R001" not in blocos[1]["text"]
    users = [kw["messages"][0]["content"] for _, kw in ch]
    assert len(set(users)) >= 3 and all("CODEBOOK" not in u and "Metáfora" not in u for u in users)  # só o trecho varia
    log = [json.loads(l) for l in (pasta_do_projeto(proj_cod) / "saidas" / "llm_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [l["cache_criado"] for l in log] == [1000, 0, 0, 0] and [l["cache_lido"] for l in log] == [0, 1000, 1000, 1000]
    assert log[0]["uso"]["cache_creation_input_tokens"] == 1000 and log[1]["custo_usd"] == pytest.approx((50 * 2 + 20 * 10 + 1000 * 0.2) / 1e6)
    assert all("aviso_cache" not in l for l in log)
    est = client.get(f"{url}/estimativa").json()
    assert est["custo"]["modelo"] == "claude-sonnet-5-5" and est["custo"]["custo_com_cache_usd"] <= est["custo"]["custo_sem_cache_usd"]


def test_ollama_e_openai_recebem_o_system_achatado():
    from app.services.llm import provedores
    b = cache_prompt.blocos_system("A", "B")
    assert provedores.system_como_texto(b) == "A\n\nB"


def test_estimativa_de_custo_com_e_sem_cache_confere_com_calculo_manual():
    e = precos.estimar("claude-sonnet-5-5", 100, 2000, 100, 80)
    assert e["custo_sem_cache_usd"] == pytest.approx((100 * 2100 * 2 + 100 * 80 * 10) / 1e6, abs=1e-4)  # 0,5
    esperado = (2000 * 2 * 1.25 + 99 * 2000 * 0.20 + 100 * 100 * 2 + 100 * 80 * 10) / 1e6  # 0,1446
    assert e["custo_com_cache_usd"] == pytest.approx(esperado, abs=1e-4) and e["cache_aplicavel"] and e["economia_pct"] == pytest.approx(71.1, abs=0.1)
    curto = precos.estimar("claude-sonnet-5-5", 100, 300, 100, 80)  # abaixo do mínimo de 512: sem cache
    assert not curto["cache_aplicavel"] and curto["custo_com_cache_usd"] == curto["custo_sem_cache_usd"]
    assert precos.estimar("gemma2:2b", 10, 100, 50, 10)["custo_sem_cache_usd"] is None
    # Opus e Haiku
    assert precos.custo_de_uso("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(24.0)
    assert precos.custo_de_uso("claude-haiku-5-5", {"input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000}) == pytest.approx(0.1 + 0.125)
    aviso = precos.anotar_uso("claude-opus-5-5", {"input_tokens": 100, "output_tokens": 5}, 300)
    assert "abaixo do mínimo" in aviso["aviso_cache"] and "aviso_cache" not in precos.anotar_uso("claude-opus-5-5", {"input_tokens": 1, "cache_read_input_tokens": 300}, 300)


def test_tabela_de_precos_editavel(client, cfg_llm):  # noqa: F811
    assert client.get("/api/config/llm/precos").json()["modelos"]["claude-opus-5-5"]["entrada"] == 4.0
    r = client.put("/api/config/llm/precos", json={"claude-opus-5-5": {"entrada": 5.0}})
    assert r.status_code == 200 and precos.precos_do_modelo("claude-opus-5-5")["entrada"] == 5.0 and precos.precos_do_modelo("claude-opus-5-5")["saida"] == 20.0
    assert client.put("/api/config/llm/precos", json={"claude-opus-5-5": {"entrada": -1}}).status_code == 422


# ---------- 15.13: BM25 e RRF ----------

def test_bm25_confere_com_valores_calculados_a_mao():
    idx = bm25.IndiceBM25(["cat cat dog", "dog bird", "bird bird bird fish"])
    assert idx.n == 3 and idx.avgdl == pytest.approx(3.0)
    assert idx.idf("cat") == pytest.approx(math.log(8 / 3)) and idx.idf("dog") == pytest.approx(math.log(1.6))
    n = idx.pontuar("cat")
    assert n[0] == pytest.approx(math.log(8 / 3) * 2 * 2.5 / (2 + 1.5)) and n[1] == n[2] == 0  # ≈ 1,4012
    d = idx.pontuar("dog")
    assert d[0] == pytest.approx(math.log(1.6) * 2.5 / 2.5) and d[1] == pytest.approx(math.log(1.6) * 2.5 / (1 + 1.125))  # dl=2: norma 1,5*(0,25+0,75*2/3)
    assert [i for i, _ in idx.ranking("dog")] == [1, 0]  # o documento menor ganha com o mesmo tf
    assert idx.ranking("zebra") == [] and idx.pontuar("") == [0, 0, 0]
    assert idx.pontuar("cat cat") == n  # termos da consulta contam uma vez


def test_termos_normalizam_acento_plural_e_palavras_vazias():
    assert bm25.termos("The Limitations of Autonomous Agents") == ["limitation", "autonomous", "agent"]
    assert bm25.termos("Supervisão humana é essencial") == ["supervisao", "humana", "essencial"]


def test_rrf_confere_com_valores_calculados_a_mao():
    r = bm25.rrf([["a", "b", "c"], ["b", "c", "a"]])
    assert [i for i, _ in r] == ["b", "a", "c"]
    d = dict(r)
    assert d["a"] == pytest.approx(1 / 61 + 1 / 63) and d["b"] == pytest.approx(1 / 62 + 1 / 61) and d["c"] == pytest.approx(1 / 63 + 1 / 62)
    assert dict(bm25.rrf([["x", "y"], ["z"]]))["z"] == pytest.approx(1 / 61)  # ausente de um ranking: sem parcela dele


# ---------- 15.13: citação, RAG sem e com LLM ----------

ITENS = [{"posicao": 1, "id": "1:0", "rotulo": "001 · Kim 2026", "pagina": 3, "texto": "Human oversight reduced errors by 40 percent."},
         {"posicao": 2, "id": "1:1", "rotulo": "002 · Silva 2025", "pagina": 7, "texto": "Small firms adopt agents slowly."}]


def test_conferir_resposta_valida_e_invalida():
    ok = rag.conferir_resposta("A supervisão humana reduziu erros em 40 (001 · Kim 2026, p. 3).", ITENS)
    assert ok["ok"] and ok["citacoes_validas"] == ["001 · Kim 2026, p. 3"]
    ruim = rag.conferir_resposta("Reduziu erros (001 · Kim 2026, p. 99) em 73%.", ITENS)
    assert not ruim["ok"] and ruim["citacoes_invalidas"] == ["(001 · Kim 2026, p. 99)"] and "73" in ruim["numeros_nao_encontrados"]
    sem = rag.conferir_resposta("Reduziu erros.", ITENS)
    assert not sem["ok"] and sem["sem_citacao"]
    assert rag.conferir_resposta('Diz "Small firms adopt agents slowly" (002 · Silva 2025, p. 7).', ITENS)["ok"]
    assert not rag.conferir_resposta('Diz "Firms never adopt" (002 · Silva 2025, p. 7).', ITENS)["ok"]


class ProvedorRag:
    nome = "falso"

    def __init__(self, texto):
        self.texto = texto
        self.chamadas = []

    def gerar(self, system, user):
        self.chamadas.append((system, user))
        return {"texto": self.texto, "modelo": "falso-1", "uso": {"input_tokens": 10, "output_tokens": 5}}


FILLER = "The analysis of the data shows that the results of the study are consistent across many cases. " * 14


@pytest.fixture()
def proj_busca(client, tmp_path):
    """Projeto com 3 documentos com marcador de página (<!-- página N -->), como o corpus Docling."""
    pasta = tmp_path / "docs_paginas"
    pasta.mkdir()
    textos = {
        "001_2026_Kim_Hyunso_Supervisao.md": ("Human oversight of autonomous agents reduced errors by 40 percent in small firms.",
                                              "Limitations of autonomous agents include hallucination and weak accountability."),
        "002_2025_Silva_Ana_Empresas.md": ("The one-person company emerged as a new organizational form with generative AI.",
                                           "Solo founders delegate marketing and coding tasks to AI assistants."),
        "003_2024_Souza_Rui_Regulacao.md": ("Regulation of artificial intelligence requires transparency and audit trails.",
                                            "Policy makers discuss liability for automated decisions.")}
    for nome, (p1, p2) in textos.items():
        (pasta / nome).write_text(f"<!-- página 1 -->\n\n{p1} {FILLER}\n\n<!-- página 2 -->\n\n{p2} {FILLER}\n", encoding="utf-8")
    r = client.post("/api/projetos", json={"nome": "Busca T2", "pasta_origem": str(pasta)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    assert client.post(f"/api/projetos/{slug}/executar?sincrono=1").status_code == 200
    return slug


def test_perguntar_sem_llm_devolve_so_recuperacao_e_registra_log(client, proj_busca):
    url = f"/api/projetos/{proj_busca}"
    r = client.post(f"{url}/perguntar", json={"pergunta": "human oversight of autonomous agents", "k": 3})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["modo"] == "bm25" and j["resposta"] is None and 1 <= len(j["itens"]) <= 3
    top = j["itens"][0]
    assert "Kim" in top["rotulo"] and top["pagina"] == 1 and "oversight" in top["texto"]
    assert top["rotulo"] and top["pagina"] is not None and top["texto"] and top["bm25"] > 0 and top["posicao"] == 1
    notas = [i["nota"] for i in j["itens"]]
    assert notas == sorted(notas, reverse=True)
    # pedir resposta com o LLM desligado: 409 (a busca em si continua disponível)
    r = client.post(f"{url}/perguntar", json={"pergunta": "analysis", "responder": True})
    assert r.status_code == 409 and "desligado" in r.json()["detail"]
    assert client.post(f"{url}/perguntar", json={"pergunta": "  "}).status_code == 422
    assert client.post(f"{url}/perguntar", json={"pergunta": "x", "modo": "hibrido"}).status_code == 409  # sem embeddings
    log = client.get(f"{url}/perguntar/log").json()["consultas"]
    assert any(c["pergunta"] == "human oversight of autonomous agents" and c["ids"] == [i["id"] for i in j["itens"]] for c in log)


def test_perguntar_com_llm_confere_citacoes_e_mostra_avisos(client, proj_busca, cfg_llm, monkeypatch):  # noqa: F811
    db = pasta_do_projeto(proj_busca)
    from app.database import sessao_do_projeto
    s = sessao_do_projeto(proj_busca)
    try:
        ret = rag.recuperar(s, db, "limitations autonomous agents", k=2)
        it = ret["itens"][0]
        boa = ProvedorRag(f"Os resultados são consistentes ({it['rotulo']}, p. {it['pagina']}).")
        r = rag.perguntar(s, db, "limitations autonomous agents", k=2, responder=True, provedor=boa)
        assert r["resposta"]["verificacao"]["ok"] and r["resposta"]["avisos"] == [] and len(boa.chamadas) == 1
        assert f"({it['rotulo']}, p. {it['pagina']})" in boa.chamadas[0][1] and "SOMENTE" in boa.chamadas[0][0]
        ruim = ProvedorRag("Resultados ótimos (Fantasma 2030, p. 5).")
        r = rag.perguntar(s, db, "limitations autonomous agents", k=2, responder=True, provedor=ruim)
        assert not r["resposta"]["verificacao"]["ok"] and r["resposta"]["avisos"] and r["resposta"]["texto"]  # mostrada, com aviso
        # sem trechos recuperados: não chama o modelo
        nada = ProvedorRag("qualquer coisa")
        r = rag.perguntar(s, db, "zzzzqqq", k=2, responder=True, provedor=nada)
        assert r["itens"] == [] and r["resposta"] is None and nada.chamadas == []
    finally:
        s.close()
    linhas = [json.loads(l) for l in (db / "saidas" / "busca_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(linhas) == 3 and linhas[0]["verificacao_ok"] is True and linhas[1]["verificacao_ok"] is False and linhas[2]["resposta"] is False


# ---------- 15.12: embeddings (função de embedding falsa) ----------

def _embed_falso(textos):
    """Saco de palavras com hash determinístico em 32 dimensões (só para testar o encanamento)."""
    m = np.zeros((len(textos), 32), dtype=np.float32)
    for i, t in enumerate(textos):
        for w in bm25.termos(t):
            m[i, sum(ord(c) for c in w) % 32] += 1.0
    return m


def test_embeddings_calcular_armazenar_reaproveitar_e_similaridade(client, proj_busca):
    from app.database import sessao_do_projeto
    pasta = pasta_do_projeto(proj_busca)
    s = sessao_do_projeto(proj_busca)
    try:
        r = embeddings.calcular(s, pasta, "modelo-falso:1", embed_fn=_embed_falso)
        assert not r["reaproveitado"] and r["n"] > 0 and r["dim"] == 32
        arq = pasta / "cache" / "embeddings" / "modelo-falso_1" / "segmentos.npy"
        assert arq.is_file()
        matriz, meta = embeddings.carregar(pasta, "modelo-falso:1")
        assert matriz.shape == (meta["n"], 32) and np.allclose(np.linalg.norm(matriz, axis=1), 1.0, atol=1e-5)
        assert embeddings.calcular(s, pasta, "modelo-falso:1", embed_fn=lambda t: 1 / 0)["reaproveitado"]  # não recalcula
        ids, sim = embeddings.similaridade_documentos(matriz, meta)
        assert sim.shape == (len(ids), len(ids)) and np.allclose(np.diag(sim), 1.0, atol=1e-5) and np.allclose(sim, sim.T, atol=1e-6)
        # a média dos segmentos é renormalizada: documento idêntico a si mesmo = 1; vizinho mais próximo ordenado
        vq = _embed_falso(["analysis of the data"])[0]
        vq = vq / np.linalg.norm(vq)
        prox = embeddings.mais_proximos(matriz, vq, k=3)
        assert [n for _, n in prox] == sorted([n for _, n in prox], reverse=True)
        # busca híbrida (BM25 + cosseno por RRF) com a consulta falsa
        ret = rag.recuperar(s, pasta, "analysis of the data", k=3, modo="hibrido", embed_consulta=lambda t: _embed_falso([t])[0])
        assert ret["modo"] == "hibrido" and ret["itens"] and ret["itens"][0]["cosseno"] is not None and ret["itens"][0]["bm25"] is not None
        auto = rag.recuperar(s, pasta, "analysis of the data", k=3, embed_consulta=lambda t: _embed_falso([t])[0])
        assert auto["modo"] == "hibrido" and rag.recuperar(s, pasta, "analysis", k=3, modo="bm25")["modo"] == "bm25"
    finally:
        s.close()
    # API: similaridade entre documentos a partir do que está em cache
    url = f"/api/projetos/{proj_busca}/semantica"
    j = client.get(f"{url}/similaridade", params={"k": 5}).json()
    assert j["modelo"] == "modelo-falso:1" and j["documentos"] >= 3 and j["pares"][0]["similaridade"] >= j["pares"][-1]["similaridade"]
    d = j["pares"][0]["a"]
    v = client.get(f"{url}/similaridade", params={"documento_id": d}).json()
    assert v["rotulo"] and all(x["documento_id"] != d for x in v["vizinhos"])
    assert client.get(f"{url}/similaridade", params={"documento_id": 99999}).status_code == 404


def test_semantica_sem_ollama_mostra_como_habilitar(client, proj_busca, cfg_llm):  # noqa: F811
    url = f"/api/projetos/{proj_busca}/semantica"
    config.salvar({"provedor": "ollama", "ollama": {"base_url": "http://127.0.0.1:9", "modelo": "x"}})
    st = client.get(f"{url}/status").json()
    assert st["disponivel"] is False and "ollama pull" in st["como_habilitar"] and st["calculados"] == []
    r = client.post(f"{url}/calcular", json={"modelo": "nomic-embed-text"})
    assert r.status_code == 409 and "Ollama" in r.json()["detail"]
    config.salvar({"provedor": "nenhum"})
    assert client.post(f"{url}/calcular", json={"modelo": "nomic-embed-text"}).status_code == 409
    assert client.get(f"{url}/similaridade").status_code == 409  # nada calculado


def test_embed_ollama_usa_api_embed_e_prefixos(monkeypatch):
    chamadas = []

    class RespFalsa:
        status_code = 200
        text = "{}"

        def json(self):
            return {"embeddings": [[3.0, 4.0], [0.0, 2.0]]}

    class ClienteFalso:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json=None):
            chamadas.append((url, json))
            return RespFalsa()

    monkeypatch.setattr(embeddings.httpx, "Client", ClienteFalso)
    m = embeddings.embed_ollama("http://x:1/", "nomic-embed-text", ["a", "b"], "consulta")
    assert chamadas[0][0] == "http://x:1/api/embed" and chamadas[0][1]["input"] == ["search_query: a", "search_query: b"]
    assert np.allclose(m, [[0.6, 0.8], [0.0, 1.0]])
    assert embeddings._eh_embedding({"name": "mxbai-embed-large:latest"}) and not embeddings._eh_embedding({"name": "gemma2:2b", "capabilities": ["completion"]})


# ---------- 15.11: classificação ----------

class ProvedorClassifica(ProvedorFalso):
    """Responde com o rótulo humano conhecido do trecho (ou o que estiver em ``respostas``)."""

    def __init__(self, respostas=None, multi=False):
        super().__init__(respostas)
        self.multi = multi

    def gerar(self, system, user):
        self.pedidos.append(user)
        self.systems.append(system)
        trecho = user.split('"""')[1].strip()
        cod = (self.respostas or {}).get(trecho, "C1.1")
        rot = cod if isinstance(cod, list) else [cod]
        return {"texto": json.dumps({"rotulos": rot, "justificativa": "porque sim", "confianca": 0.8}), "modelo": "falso-1",
                "uso": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}


def test_interpretar_resposta_de_classificacao():
    ids = ["C1.1", "C1.2"]
    r = clf.interpretar('{"rotulos": ["c1.2"], "justificativa": "j", "confianca": "80%"}', ids, False)
    assert r["ok"] and r["rotulos"] == ["C1.2"] and r["confianca"] == 0.8
    assert clf.interpretar('texto {"rotulo": "nenhum"} fim', ids, False)["rotulos"] == ["nenhum"]
    assert not clf.interpretar('{"rotulos": ["C9.9"]}', ids, False)["ok"]  # fora da lista: erro, sem adivinhar
    assert not clf.interpretar('{"rotulos": ["C1.1", "C1.2"]}', ids, False)["ok"]  # dois no modo de rótulo único
    m = clf.interpretar('{"rotulos": ["C1.1", "C1.2", "nenhum"]}', ids, True)
    assert m["ok"] and m["rotulos"] == ["C1.1", "C1.2"]
    assert not clf.interpretar("sem json", ids, True)["ok"]


def test_rotulos_em_texto_e_escolha_deterministica_de_exemplos():
    assert clf.interpretar_rotulos_texto("Risco: algo ruim\n\nOportunidade\n") == [
        {"id": "Risco", "nome": "Risco", "definicao": "algo ruim"}, {"id": "Oportunidade", "nome": "Oportunidade", "definicao": ""}]
    with pytest.raises(clf.ConfigInvalida):
        clf.interpretar_rotulos_texto("a: x\nA: y")
    T = lambda i, c: SimpleNamespace(id=i, codigo_humano=c, texto=f"texto longo de exemplo numero {i} para o rotulo")  # noqa: E731
    trechos = [T(i, "A" if i % 2 else "B") for i in range(1, 11)]
    rot = [{"id": "A"}, {"id": "B"}]
    e1 = clf.escolher_exemplos(trechos, rot, 2)
    assert [t.id for t in e1] == [t.id for t in clf.escolher_exemplos(list(reversed(trechos)), rot, 2)]  # independe da ordem de entrada
    assert len(e1) == 4 and sorted(t.codigo_humano for t in e1) == ["A", "A", "B", "B"]


def test_classificacao_zero_shot_revisao_e_concordancia(client, proj_cod, cfg_llm, monkeypatch):  # noqa: F811
    url = f"/api/projetos/{proj_cod}/classificacao"
    client.post(f"/api/projetos/{proj_cod}/codificacao/importar", content=_planilha())
    r = client.post(f"{url}/executar", params={"sincrono": 1}, json={"origem": "trechos"})
    assert r.status_code == 409 and "desligado" in r.json()["detail"]
    config.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "falso"}})
    assert client.get(f"{url}/rotulos").json()["dicionario"][0]["id"] == "C1.1"
    prov = ProvedorClassifica({"ChatGPT suggests and the founder executes.": "C1.2", "Business entry rose by 40 percent.": "nenhum"})
    monkeypatch.setattr(clf, "provedor_configurado", lambda cfg=None: prov)
    est = client.post(f"{url}/estimativa", json={"origem": "trechos"}).json()
    assert est["unidades"] == 5 and est["rotulos"] == 3 and est["exemplos"] == 0 and est["com_humano"] == 5
    r = client.post(f"{url}/executar", params={"sincrono": 1}, json={"origem": "trechos"})
    assert r.status_code == 200 and r.json()["feitos"] == 5 and r.json()["erros"] == 0
    # prefixo idêntico (instruções + rótulos), só o último bloco com cache_control; unidade só no usuário
    assert all(sy == prov.systems[0] for sy in prov.systems) and len(prov.systems[0]) == 2
    assert "cache_control" not in prov.systems[0][0] and prov.systems[0][1]["cache_control"] == {"type": "ephemeral"}
    assert all("Entrada de negócios" not in u and "UNIDADE A CLASSIFICAR" in u for u in prov.pedidos)
    it = client.get(f"{url}/itens").json()
    assert it["contagens"]["classificado"] == 5 and it["contagens"]["pendente_revisao"] == 5
    # humano: C1.1, C1.2, C3.1, C1.2, C3.1 | LLM: C1.1, C1.2, nenhum, C1.1, C1.1
    assert it["contagens"]["concordam"] == 2 and it["contagens"]["discordam"] == 3
    primeiro = it["itens"][0]
    assert primeiro["rotulos"] == ["C1.1"] and primeiro["rotulo_humano"] == "C1.1" and primeiro["justificativa"] == "porque sim" and primeiro["confianca"] == 0.8
    # revisão por item e em lote
    assert client.post(f"{url}/itens/{primeiro['id']}/revisao", json={"revisao": "aceito"}).json()["revisao"] == "aceito"
    assert client.post(f"{url}/itens/{it['itens'][2]['id']}/revisao", json={"revisao": "rejeitado"}).json()["revisao"] == "rejeitado"
    assert client.post(f"{url}/itens/{primeiro['id']}/revisao", json={"revisao": "talvez"}).status_code == 422
    assert client.post(f"{url}/revisar-lote", json={"revisao": "aceito", "confianca_minima": 0.7, "ids": [it["itens"][1]["id"]]}).json()["alterados"] == 1
    c = client.get(f"{url}/itens", params={"filtro": "aceito"}).json()
    assert c["n"] == 2 and client.get(f"{url}/itens", params={"filtro": "pendente_revisao"}).json()["n"] == 2
    # concordância com o humano (15.1): os mesmos números do teste de codificação
    j = client.get(f"{url}/concordancia", params={"bootstrap": 100}).json()
    assert j["n_itens"] == 5 and j["percentual"] == pytest.approx(0.4) and j["kappa"]["kappa"] is not None
    assert client.get(f"{url}/concordancia", params={"somente": "aceitos", "bootstrap": 0}).json()["n_itens"] == 2
    assert client.get(f"{url}/concordancia", params={"somente": "nao_rejeitados", "bootstrap": 0}).json()["n_itens"] == 4
    assert client.get(f"{url}/itens.csv").content.decode("utf-8-sig").splitlines()[0].startswith("id;origem")
    log = [json.loads(l) for l in (pasta_do_projeto(proj_cod) / "saidas" / "llm_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(log) == 5 and all(l["analise"] == "classificacao" and l["versao_prompt"] == "classificacao-v1" for l in log)
    assert client.delete(url).json()["itens"] == 5 and client.get(f"{url}/concordancia").status_code == 409


def test_classificacao_few_shot_exclui_exemplos_da_avaliacao(client, proj_cod, cfg_llm, monkeypatch):  # noqa: F811
    url = f"/api/projetos/{proj_cod}/classificacao"
    client.post(f"/api/projetos/{proj_cod}/codificacao/importar", content=_planilha())
    config.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "falso"}})
    prov = ProvedorClassifica()
    monkeypatch.setattr(clf, "provedor_configurado", lambda cfg=None: prov)
    corpo = {"origem": "trechos", "modo": "few_shot", "k": 1}
    est = client.post(f"{url}/estimativa", json=corpo).json()
    assert est["exemplos"] == 3 and est["unidades"] == 2  # 1 exemplo por rótulo (3) saem da avaliação
    r = client.post(f"{url}/executar", params={"sincrono": 1}, json=corpo)
    assert r.json()["total"] == 2 and len(prov.pedidos) == 2
    sistema = "".join(b["text"] for b in prov.systems[0])
    assert sistema.count("EXEMPLO (rótulo:") == 3 and all(sy == prov.systems[0] for sy in prov.systems)
    it = client.get(f"{url}/itens").json()
    assert it["contagens"]["exemplo"] == 3 and it["contagens"]["classificado"] == 2
    # os exemplos não aparecem entre as unidades classificadas
    usados = {t for t in sistema.split("EXEMPLO (rótulo:")[1:]}
    assert len(usados) == 3
    # determinístico: repetir dá os mesmos exemplos
    prov2 = ProvedorClassifica()
    monkeypatch.setattr(clf, "provedor_configurado", lambda cfg=None: prov2)
    client.post(f"{url}/executar", params={"sincrono": 1}, json=corpo)
    assert prov2.systems[0] == prov.systems[0]


def test_classificacao_multirrotulo_lista_propria_e_segmentos(client, proj_cod, cfg_llm, monkeypatch):  # noqa: F811
    url = f"/api/projetos/{proj_cod}/classificacao"
    config.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "falso"}})
    prov = ProvedorClassifica()
    monkeypatch.setattr(clf, "provedor_configurado", lambda cfg=None: prov)
    # sem codebook nem lista: 422 claro
    assert client.post(f"{url}/executar", params={"sincrono": 1}, json={"origem": "segmentos"}).status_code == 422

    class Multi(ProvedorClassifica):
        def gerar(self, system, user):
            self.pedidos.append(user)
            self.systems.append(system)
            return {"texto": json.dumps({"rotulos": ["Dados", "Resultado"], "justificativa": "dois temas", "confianca": 0.6}), "modelo": "m", "uso": {}}

    multi = Multi()
    monkeypatch.setattr(clf, "provedor_configurado", lambda cfg=None: multi)
    corpo = {"origem": "segmentos", "rotulos": "Dados: fala de dados\nResultado: fala de resultados", "multirrotulo": True, "limite": 3}
    r = client.post(f"{url}/executar", params={"sincrono": 1}, json=corpo)
    assert r.status_code == 200 and r.json()["feitos"] == 3
    j = client.get(f"{url}/itens").json()
    assert j["n"] == 3 and j["itens"][0]["rotulos"] == ["Dados", "Resultado"] and j["itens"][0]["documento"]
    assert "TODOS os rótulos" in multi.systems[0][0]["text"] and "Dados | Dados | definição: fala de dados" in multi.systems[0][1]["text"]
    assert j["config"]["multirrotulo"] is True and j["config"]["fonte_rotulos"] == "lista"
    # documentos como unidade
    r = client.post(f"{url}/executar", params={"sincrono": 1}, json={"origem": "documentos", "rotulos": "Dados: x", "limite": 2})
    assert r.status_code == 200 and client.get(f"{url}/itens").json()["itens"][0]["origem"] == "documentos"
    # sem humano: concordância indisponível
    assert client.get(f"{url}/concordancia").status_code == 409


def test_recuperacao_colapsa_textos_identicos_de_documentos_diferentes(client, proj_busca):
    from app.database import sessao_do_projeto
    s = sessao_do_projeto(proj_busca)
    try:
        r = rag.recuperar(s, pasta_do_projeto(proj_busca), "analysis data results consistent cases", k=3)
    finally:
        s.close()
    textos = [" ".join(i["texto"].split()).casefold() for i in r["itens"]]
    assert len(textos) == len(set(textos)) and any(i["tambem_em"] for i in r["itens"])  # o filler existe nos 3 documentos
    assert all({"rotulo", "pagina"} <= set(o) for i in r["itens"] for o in i["tambem_em"])
    ver = rag.conferir_resposta(f"Consistente ({r['itens'][0]['tambem_em'][0]['rotulo']}, p. {r['itens'][0]['tambem_em'][0]['pagina']}).", r["itens"])
    assert ver["citacoes_validas"]  # o mesmo texto em outro documento também é citável
