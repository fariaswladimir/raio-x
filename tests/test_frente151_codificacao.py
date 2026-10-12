"""15.1 Codificação por LLM + concordância (kappa de Cohen, alfa de Krippendorff).

Estatística contra exemplos publicados (Krippendorff 2011: 4 codificadores × 12 unidades, alfa nominal 0,743; kappa
2 × 2 de 0,40) e contra o método delta numérico; leitura robusta da resposta do LLM; importação de uma planilha no
formato da planilha de coleta (gerada no teste); lote com provedor simulado (sem chamadas reais) e às cegas."""
import io
import json
import math

import numpy as np
import openpyxl
import pytest

from app.database import pasta_do_projeto
from app.services.concordancia import codificador, estatisticas as E
from app.services.llm import config

N = None
# Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability", exemplo C: 4 observadores × 12 unidades, com faltantes
KRIPP = [[1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N],
         [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3],
         [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N],
         [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N]]


def _de_tabela(M, cats=("s", "n")):
    a, b = [], []
    for i, ci in enumerate(cats):
        for j, cj in enumerate(cats):
            a += [ci] * M[i][j]
            b += [cj] * M[i][j]
    return a, b


# ---------- alfa de Krippendorff ----------

def test_alfa_exemplo_publicado_de_krippendorff_2011():
    esperado = {"nominal": 0.743, "ordinal": 0.815, "intervalar": 0.849, "razao": 0.797}
    for metrica, alfa in esperado.items():
        r = E.krippendorff_alfa(KRIPP, metrica)
        assert round(r["alfa"], 3) == alfa, metrica
    r = E.krippendorff_alfa(KRIPP)
    # unidade 12 tem um só valor: não pareável; n = 40 valores pareáveis (o exemplo publicado)
    assert r["unidades_pareaveis"] == 11 and r["n_valores_pareaveis"] == pytest.approx(40)
    O, vals = E.coincidencias(KRIPP)
    assert vals == [1, 2, 3, 4, 5] and np.allclose(O, O.T)
    # n_c = contagem direta dos valores nas 11 unidades pareáveis (1: 9, 2: 13, 3: 10, 4: 5, 5: 3)
    assert O.sum(axis=1).tolist() == pytest.approx([9, 13, 10, 5, 3])


def test_alfa_casos_limite():
    assert E.krippendorff_alfa([[1, 2, 3, 1], [1, 2, 3, 1]])["alfa"] == pytest.approx(1.0)
    sem_var = E.krippendorff_alfa([["a", "a", "a"], ["a", "a", "a"]])
    assert sem_var["alfa"] is None and "variação" in sem_var["nota"]
    # faltantes: unidades com um só valor não mudam o alfa
    base = E.krippendorff_alfa([[1, 2, 2, 1, 3], [1, 2, 1, 1, 3]])["alfa"]
    com = E.krippendorff_alfa([[1, 2, 2, 1, 3, 2, N], [1, 2, 1, 1, 3, N, 1]])["alfa"]
    assert com == pytest.approx(base)
    assert E.krippendorff_alfa([[1, N], [N, 2]])["alfa"] is None  # nada pareável


def test_alfa_bootstrap_deterministico_e_cobre_a_estimativa():
    r1 = E.krippendorff_alfa(KRIPP, bootstrap=500, semente=1)
    r2 = E.krippendorff_alfa(KRIPP, bootstrap=500, semente=1)
    assert r1["bootstrap"] == r2["bootstrap"]
    lo, hi = r1["bootstrap"]["ic95"]
    assert lo < r1["alfa"] < hi and 0 <= r1["bootstrap"]["p_abaixo_0667"] <= 1


# ---------- kappa de Cohen ----------

def test_kappa_exemplos_2x2_conhecidos():
    # 50 unidades: 20 sim/sim, 5 sim/não, 10 não/sim, 15 não/não -> p_o 0,70, p_e 0,50, kappa 0,40
    a, b = _de_tabela([[20, 5], [10, 15]])
    r = E.cohen_kappa(a, b)
    assert r["p_o"] == pytest.approx(0.70) and r["p_e"] == pytest.approx(0.50) and r["kappa"] == pytest.approx(0.40)
    assert r["faixa"] == "razoável"
    # "paradoxo" com mesmo p_o = 0,60 e marginais diferentes: 0,1304 e 0,2593
    assert E.cohen_kappa(*_de_tabela([[45, 15], [25, 15]]))["kappa"] == pytest.approx(0.1304, abs=5e-5)
    assert E.cohen_kappa(*_de_tabela([[25, 35], [5, 35]]))["kappa"] == pytest.approx(0.2593, abs=5e-5)


def _kappa_de_p(p):
    r, c = p.sum(axis=1), p.sum(axis=0)
    pe = r @ c
    return (np.trace(p) - pe) / (1 - pe)


def test_ep_assintotico_confere_com_metodo_delta_numerico():
    for M in ([[20, 5], [10, 15]], [[30, 4, 2], [6, 25, 3], [1, 5, 24]], [[12, 3, 0, 1], [2, 9, 4, 0], [0, 1, 15, 2], [3, 0, 2, 11]]):
        M = np.array(M, dtype=float)
        n = M.sum()
        p = M / n
        g = np.zeros_like(p)
        h = 1e-6
        for i in range(p.shape[0]):
            for j in range(p.shape[1]):
                e = np.zeros_like(p)
                e[i, j] = h
                g[i, j] = (_kappa_de_p(p + e) - _kappa_de_p(p - e)) / (2 * h)
        gv, pv = g.ravel(), p.ravel()
        var = gv @ (np.diag(pv) - np.outer(pv, pv)) @ gv / n
        r = E.kappa_da_tabela(M)
        assert r["ep"] == pytest.approx(math.sqrt(var), rel=1e-5)


def test_kappa_casos_limite_e_bootstrap():
    r = E.cohen_kappa(["a", "b", "c", "a"], ["a", "b", "c", "a"])
    assert r["kappa"] == pytest.approx(1.0) and r["ep"] == pytest.approx(0.0, abs=1e-12) and r["faixa"] == "quase perfeita"
    sem = E.cohen_kappa(["a"] * 5, ["a"] * 5)
    assert sem["kappa"] is None and "variação" in sem["nota"]
    # faltantes saem do par
    r = E.cohen_kappa(["a", "b", None, "a"], ["a", "b", "b", None])
    assert r["n"] == 2 and r["kappa"] == pytest.approx(1.0)
    a, b = _de_tabela([[20, 5], [10, 15]])
    r = E.cohen_kappa(a, b, bootstrap=800, semente=3)
    lo, hi = r["bootstrap"]["ic95"]
    assert lo < 0.4 < hi and abs((hi - lo) - (r["ic95"][1] - r["ic95"][0])) < 0.15  # perto do IC assintótico
    assert E.faixa_kappa(-0.1) == "pobre" and E.faixa_kappa(0.15) == "leve" and E.faixa_kappa(0.55) == "moderada"
    assert E.faixa_kappa(0.7) == "substancial" and E.faixa_alfa(0.81).startswith("confiável") and E.faixa_alfa(0.7).startswith("só")


def test_por_codigo_e_confusao_a_mao():
    h = ["A", "A", "A", "B", "B", "C"]
    l = ["A", "A", "B", "B", "C", "C"]
    pc = {c["codigo"]: c for c in E.por_codigo(h, l)}
    assert (pc["A"]["vp"], pc["A"]["fp"], pc["A"]["fn"]) == (2, 0, 1)
    assert pc["A"]["precisao"] == 1.0 and pc["A"]["revocacao"] == pytest.approx(2 / 3) and pc["A"]["f1"] == pytest.approx(0.8)
    assert pc["C"]["precisao"] == 0.5 and pc["C"]["revocacao"] == 1.0
    # kappa um-contra-o-resto de A: tabela [[2, 1], [0, 3]] -> p_o 5/6, p_e = 0,5·(2/6) + 0,5·(4/6) = 0,5
    assert pc["A"]["kappa"] == pytest.approx((5 / 6 - 0.5) / 0.5)
    m = E.matriz_confusao(h, l)
    assert m["categorias"] == ["A", "B", "C"] and m["matriz"] == [[2, 1, 0], [0, 1, 1], [0, 0, 1]]


# ---------- leitura da resposta do LLM ----------

def test_interpretar_resposta_robusta():
    cods = ["C1.1", "C1.2", "C3.10"]
    r = codificador.interpretar('```json\n{"codigo": "C1.2", "justificativa": "assistente", "confianca": 0.8}\n```', cods)
    assert r["ok"] and r["codigo"] == "C1.2" and r["confianca"] == 0.8
    r = codificador.interpretar("Resposta: {'codigo': 'c1.1', 'justificativa': 'x', 'confianca': '85%'}", cods)
    assert r["codigo"] == "C1.1" and r["confianca"] == pytest.approx(0.85)
    r = codificador.interpretar('{"código": "C3.10 - Produtividade", "confiança": "alta"}', cods)
    assert r["codigo"] == "C3.10" and r["confianca"] == 0.85
    assert codificador.interpretar('{"codigo": "nenhum", "confianca": 40}', cods)["codigo"] == "nenhum"
    r = codificador.interpretar('{"codigo": "C9.9"}', cods)
    assert not r["ok"] and r["codigo"] is None and "fora do codebook" in r["erro"]
    assert codificador.interpretar("O código mais adequado é C1.2, com confiança média.", cods)["codigo"] == "C1.2"
    assert not codificador.interpretar("Não sei.", cods)["ok"]
    assert not codificador.interpretar("Pode ser C1.1 ou C1.2.", cods)["ok"]  # ambíguo: não adivinha


# ---------- importação + lote com provedor simulado ----------

CODEBOOK = [("C1.1", "IA como cofundador", "T1 Conceituação", "Natureza", "QP1", "Metáfora explícita de co-founder"),
            ("C1.2", "Assistente conversacional", "T1 Conceituação", "Natureza", "QP1", "IA que sugere; humano executa"),
            ("C3.1", "Entrada de negócios", "T3 Resultados", "Efeitos", "QP3", "Criação de empresas")]
TRECHOS = [("R001-T-01", "R001", "Kim et al. (2026)", "2", "AI acts as a co-founder for solo founders.", "C1.1", "T1 Conceituação"),
           ("R001-T-02", "R001", "Kim et al. (2026)", "p. 3", "ChatGPT suggests and the founder executes.", "C1.2", "T1 Conceituação"),
           ("R002-T-01", "R002", "Silva (2025)", "10", "Business entry rose by 40 percent.", "C3.1", "T3 Resultados"),
           ("R002-T-02", "R002", "Silva (2025)", "11", "AI acts as a co-founder for solo founders.", "C1.2", "T1 Conceituação"),
           ("R009-T-01", "R009", "Fantasma (2024)", "1", "A source that is not in the corpus.", "C3.1", "T3 Resultados")]


def _planilha() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "0_LEIA-ME"
    ws.append(["Planilha de teste"])
    f0 = wb.create_sheet("F0_Identificacao")
    f0.append(["ID fonte", "Título", "Arquivo Docling"])
    f0.append(["R001", "Um", "001_2026_Kim_Hyunso_Titulo_Um"])
    f0.append(["R002", "Dois", "002_2025_QP1_Silva_Titulo_Dois.md"])
    t = wb.create_sheet("T_Trechos_Tematicos")
    t.append(["ID registro", "ID fonte", "Fonte (autor, ano)", "Trilha", "Página", "Seção", "Trecho original (sentença)",
              "Trecho traduzido (PT-BR)", "Código", "Rótulo do código", "Tema", "Tema de ordem superior", "QP", "Códigos secundários"])
    for reg, fonte, rot, pag, texto, cod, tema in TRECHOS:
        t.append([reg, fonte, rot, "Branca", pag, "1 Intro", texto, "tradução " + texto, cod, "rótulo", tema, "x", "QP1", "C9.9"])
    t.append([None] * 14)
    cb = wb.create_sheet("Codebook")
    cb.append(["Código", "Rótulo", "Tema", "Tema de ordem superior", "QP", "Regra de aplicação", "Nº sentenças (F + T)"])
    for linha in CODEBOOK:
        cb.append([*linha, 1])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def cfg_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIOX_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "_keyring", lambda: None)
    return config


class ProvedorFalso:
    nome = "falso"

    def __init__(self, respostas=None):
        self.pedidos = []
        self.systems = []
        self.respostas = respostas

    def gerar(self, system, user):
        self.pedidos.append(user)
        self.systems.append(system)
        trecho = user.split('"""')[1].strip()
        cod = (self.respostas or {}).get(trecho, "C1.1")
        return {"texto": json.dumps({"codigo": cod, "justificativa": "porque sim", "confianca": 0.7}), "modelo": "falso-1",
                "uso": {"input_tokens": 100, "output_tokens": 20}, "request_id": None}


@pytest.fixture()
def proj_cod(client, projeto):
    assert client.post(f"/api/projetos/{projeto}/executar?sincrono=1").status_code == 200
    return projeto


def test_importar_planilha_mapeia_colunas_documentos_e_codebook(client, proj_cod):
    url = f"/api/projetos/{proj_cod}/codificacao"
    r = client.post(f"{url}/inspecionar", content=_planilha())
    assert r.status_code == 200 and r.json()["sugerida"] == "T_Trechos_Tematicos"
    cols = next(a for a in r.json()["abas"] if a["aba"] == "T_Trechos_Tematicos")["colunas"]
    assert cols["texto"] == "Trecho original (sentença)" and cols["codigo"] == "Código" and cols["traducao"].startswith("Trecho traduzido")
    assert cols["fonte"] == "ID fonte" and cols["fonte_rotulo"] == "Fonte (autor, ano)" and cols["pagina"] == "Página"
    rel = client.post(f"{url}/importar", content=_planilha()).json()
    assert rel["trechos_importados"] == 5 and rel["codigos_distintos"] == 3 and rel["fontes"] == 3 and rel["fontes_casadas"] == 2
    assert rel["metodo_casamento"] == {"arquivo": 2, "id_estudo": 0} and rel["fontes_sem_documento"] == ["R009"]
    assert rel["codebook"]["importado"] and rel["codebook"]["categorias_importadas"] == 3
    itens = client.get(f"{url}/trechos").json()["itens"]
    assert [i["pagina"] for i in itens] == [2, 3, 10, 11, 1] and itens[0]["documento"] and itens[4]["documento_id"] is None
    assert itens[0]["traducao"].startswith("tradução") and itens[0]["status"] == "pendente"
    # mapeamento manual e modo acrescentar (registros repetidos pulados)
    rel = client.post(f"{url}/importar", params={"modo": "acrescentar"}, content=_planilha()).json()
    assert rel["trechos_importados"] == 0 and rel["repetidos_pulados"] == 5
    m = json.dumps({"codigo": "Códigos secundários"})
    rel = client.post(f"{url}/importar", params={"mapeamento": m}, content=_planilha()).json()
    assert rel["codigos_distintos"] == 1
    assert client.post(f"{url}/importar", params={"mapeamento": json.dumps({"codigo": "Inexistente"})}, content=_planilha()).status_code == 422
    assert client.post(f"{url}/importar", content=b"nao e xlsx").status_code == 422


def test_codificacao_llm_recusa_desligado_e_e_as_cegas(client, proj_cod, cfg_llm, monkeypatch):
    url = f"/api/projetos/{proj_cod}/codificacao"
    client.post(f"{url}/importar", content=_planilha())
    r = client.post(f"{url}/codificar", params={"sincrono": 1})
    assert r.status_code == 409 and "desligado" in r.json()["detail"]
    config.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "falso"}})
    prov = ProvedorFalso({"ChatGPT suggests and the founder executes.": "C1.2", "Business entry rose by 40 percent.": "nenhum"})
    monkeypatch.setattr(codificador, "provedor_configurado", lambda cfg=None: prov)
    est = client.get(f"{url}/estimativa").json()
    assert est["trechos"] == 5 and est["categorias"] == 3 and est["remoto"] is False
    r = client.post(f"{url}/codificar", params={"sincrono": 1}, json={"limite": 4})
    assert r.status_code == 200 and r.json()["feitos"] == 4 and r.json()["erros"] == 0
    # às cegas: nada do humano (código atribuído, tema, tradução, fonte) vai no pedido; o mesmo texto com códigos
    # humanos diferentes (R001-T-01 = C1.1 e R002-T-02 = C1.2) gera exatamente o mesmo pedido
    assert len(prov.pedidos) == 4 and prov.pedidos[0] == prov.pedidos[3]
    assert all("tradução" not in p and "Kim" not in p and "R001" not in p for p in prov.pedidos)
    # o codebook vai no system (prefixo em cache), idêntico em todas as chamadas; o usuário leva só o trecho
    assert "Metáfora explícita de co-founder" in "".join(b["text"] for b in prov.systems[0]) and "Metáfora" not in prov.pedidos[0]
    assert all(sy == prov.systems[0] for sy in prov.systems)
    assert all("tradução" not in b["text"] and "Kim" not in b["text"] for sy in prov.systems for b in sy)
    r = client.post(f"{url}/codificar", params={"sincrono": 1})
    assert r.json()["total"] == 1  # só o pendente
    tr = client.get(f"{url}/trechos", params={"filtro": "discordam"}).json()
    assert tr["contagens"]["codificado"] == 5 and tr["n"] == 3  # R002-T-02 (C1.2 × C1.1), R002-T-01 (C3.1 × nenhum), R009 (C3.1 × C1.1)
    log = pasta_do_projeto(proj_cod) / "saidas" / "llm_log.jsonl"
    linhas = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert len(linhas) == 5 and all(l["analise"] == "codificacao" and l["uso"]["input_tokens"] == 100 for l in linhas)
    c = client.get(f"{url}/concordancia", params={"bootstrap": 200}).json()
    assert c["n_pares"] == 5 and c["percentual"] == pytest.approx(0.4)
    assert set(c["confusao"]["categorias"]) == {"C1.1", "C1.2", "C3.1", "nenhum"}
    h, l = ["C1.1", "C1.2", "C3.1", "C1.2", "C3.1"], ["C1.1", "C1.2", "nenhum", "C1.1", "C1.1"]
    assert c["kappa"]["kappa"] == pytest.approx(E.cohen_kappa(h, l)["kappa"], abs=1e-4)
    t = client.get(f"{url}/concordancia", params={"nivel": "tema", "bootstrap": 0}).json()
    assert t["percentual"] == pytest.approx(0.6)  # T1/T1, T1/T1, T3/nenhum, T1/T1, T3/T1
    csv = client.get(f"{url}/concordancia.csv").content.decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("codigo;suporte_humano")
    assert client.get(f"{url}/trechos.csv", params={"filtro": "concordam"}).content.decode("utf-8-sig").count("\n") == 3
    assert client.post(f"{url}/limpar-llm").json()["trechos"] == 5
    assert client.get(f"{url}/concordancia").status_code == 409


def test_codificacao_sem_codebook_e_resposta_invalida(client, proj_cod, cfg_llm, monkeypatch):
    url = f"/api/projetos/{proj_cod}/codificacao"
    config.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "falso"}})
    client.post(f"{url}/importar", params={"codebook": "false"}, content=_planilha())
    r = client.post(f"{url}/codificar", params={"sincrono": 1})
    assert r.status_code == 409 and "codebook" in r.json()["detail"]
    client.post(f"{url}/importar", content=_planilha())

    class Ruim(ProvedorFalso):
        def gerar(self, system, user):
            return {"texto": "talvez C7.7", "modelo": "x", "uso": {}}

    monkeypatch.setattr(codificador, "provedor_configurado", lambda cfg=None: Ruim())
    r = client.post(f"{url}/codificar", params={"sincrono": 1}).json()
    assert r["erros"] == 5
    assert client.get(f"{url}/trechos", params={"filtro": "erro"}).json()["n"] == 5
