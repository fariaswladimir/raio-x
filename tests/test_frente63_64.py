"""6.3 Similaridade entre documentos (TF-IDF, cosseno, agrupamento, mapa 2D) e 6.4 Dicionário/codebook por grupo.
Funções puras com matrizes de brinquedo; API, CSV, etapas e importação do codebook com um corpus sintético. Sem Docling."""
import io
import json
import math
import random
import re
from collections import Counter

import numpy as np
import openpyxl
import pytest

from app import database
from app.database import pasta_do_projeto
from app.models import Analise
from app.services import dicionario as svc_dic
from app.services import vocabulario as svc_voc
from app.services.analises import dados, dicionario, keyness, similaridade
from app.services.palavras_vazias import filtro_palavras_vazias

SEM_VAZIAS = frozenset()


# ---------- apoio: vocabulário de brinquedo ----------

def _voc(docs: dict[int, dict[str, int]]) -> dict:
    return {"documentos": {str(i): {"tokens": sum(c.values()), "lema": dict(c), "norma": dict(c),
                                    "pares": [[t, t, f] for t, f in c.items()]} for i, c in docs.items()}}


def _metas(ids, grupos=None):
    grupos = grupos or {}
    return [{"id": i, "rotulo": f"D{i}", "arquivo": f"{i}.md", "grupo": grupos.get(i), "ano": 2025} for i in ids]


def _brinquedo_3_topicos(n_por_topico=3, semente=63):
    rnd = random.Random(semente)
    docs, i = {}, 0
    for t in range(3):
        for _ in range(n_por_topico):
            i += 1
            c = {f"t{t}w{j}": rnd.randint(3, 10) for j in range(6)}
            c.update({f"comum{j}": 5 for j in range(3)})  # em todos: cai no max_df
            c[f"unico{i}"] = 2  # df = 1: cai no min_df
            docs[i] = c
    return docs


# ---------- 6.3 TF-IDF e cosseno ----------

def test_tfidf_formula_em_matriz_de_brinquedo():
    f = np.array([[2, 1, 0], [0, 1, 3], [1, 0, 0]], dtype=float)
    n, df = 3, [2, 2, 1]
    idf = [math.log((1 + n) / (1 + d)) + 1 for d in df]
    assert idf[0] == pytest.approx(1.2876820724517808) and idf[2] == pytest.approx(1.6931471805599454)

    def esperado(sublinear):
        saida = []
        for linha in f:
            v = [((1 + math.log(x)) if sublinear else x) * w if x > 0 else 0.0 for x, w in zip(linha, idf)]
            norma = math.sqrt(sum(a * a for a in v))
            saida.append([a / norma for a in v])
        return np.array(saida)

    for sub in (False, True):
        assert similaridade.tfidf(f, sublinear=sub) == pytest.approx(esperado(sub))
    x = similaridade.tfidf(f, sublinear=False)
    assert np.allclose((x ** 2).sum(axis=1), 1.0)  # normalização L2
    # à mão: o documento 2 só tem o termo 0 -> vetor unitário (1, 0, 0)
    assert x[2] == pytest.approx([1.0, 0.0, 0.0])
    # à mão: documento 1 = (0, idf1, 3 idf2) / norma
    v = np.array([0.0, idf[1], 3 * idf[2]])
    assert x[1] == pytest.approx(v / np.linalg.norm(v))


def test_tfidf_n_do_idf_pode_ser_informado_e_linha_nula_continua_nula():
    f = np.array([[1, 0], [1, 1], [0, 0]], dtype=float)
    x = similaridade.tfidf(f, sublinear=False, n_documentos=3)
    assert x[2].tolist() == [0.0, 0.0]
    idf = [math.log(4 / 3) + 1, math.log(4 / 2) + 1]
    assert x[1] == pytest.approx(np.array(idf) / np.linalg.norm(idf))


def test_cosseno_simetrico_com_diagonal_1():
    rnd = np.random.default_rng(5)
    x = similaridade.tfidf(rnd.integers(0, 6, size=(7, 12)))
    s = similaridade.cosseno(x)
    assert np.allclose(s, s.T) and np.allclose(np.diag(s), 1.0)
    assert s.min() >= 0 and s.max() <= 1.0
    ortogonais = similaridade.cosseno(np.array([[1.0, 0.0], [0.0, 1.0]]))
    assert ortogonais[0, 1] == 0.0


# ---------- 6.3 matriz, exclusões e escopo ----------

def test_matriz_aplica_min_df_max_df_e_exclui_documentos_vazios():
    docs = {1: {"aa": 2, "bb": 1, "comum": 3, "raro": 1}, 2: {"aa": 1, "bb": 4, "comum": 2},
            3: {"bb": 1, "aa": 1, "comum": 1, "cc": 1}, 4: {"comum": 2, "cc": 1}, 5: {"de": 40, "do": 10}}  # 5 só tem vazias
    voc = _voc(docs)
    filtro = frozenset({"de", "do"})
    mat, validos, termos, excluidos = similaridade.matriz_contagens(voc, _metas(docs), filtro, "lema", min_df=2, max_df=0.9)
    assert [m["id"] for m in validos] == [1, 2, 3, 4]
    assert [e["id"] for e in excluidos] == [5]
    # N = 4: max_df 0,9 -> df <= 3,6: "comum" (df 4) cai; "raro" (df 1) cai pelo min_df
    assert termos == ["aa", "bb", "cc"]
    assert mat.tolist() == [[2, 1, 0], [1, 4, 0], [1, 1, 1], [0, 0, 1]]


def test_calcular_exclui_documento_sem_nenhum_termo_apos_df():
    docs = _brinquedo_3_topicos()
    docs[10] = {"so_meu": 5}  # df = 1: o vetor fica nulo e o documento sai
    r = similaridade.calcular(_voc(docs), _metas(docs), SEM_VAZIAS)
    assert r["n_documentos"] == 9 and [e["id"] for e in r["excluidos"]] == [10]
    assert 10 not in [d["id"] for d in r["documentos"]]
    assert len(r["similaridade"]) == 9


def test_vocabulario_vazio_e_poucos_documentos_levantam_valor_erro():
    with pytest.raises(ValueError, match="min_df"):
        similaridade.calcular(_voc({1: {"aa": 1}, 2: {"bb": 1}}), _metas([1, 2]), SEM_VAZIAS)
    with pytest.raises(ValueError, match="ao menos 2"):
        similaridade.calcular(_voc({1: {"aa": 1}}), _metas([1]), SEM_VAZIAS, min_df=1, max_df=1.0)
    with pytest.raises(ValueError, match="Método"):
        similaridade.calcular(_voc(_brinquedo_3_topicos()), _metas(range(1, 10)), SEM_VAZIAS, metodo="single")


# ---------- 6.3 agrupamento, mapa 2D, vizinhos e termos ----------

@pytest.mark.parametrize("metodo", ["average", "ward"])
def test_agrupamento_recupera_os_topicos_e_e_deterministico(metodo):
    docs = _brinquedo_3_topicos()
    voc, metas = _voc(docs), _metas(docs)
    r1 = similaridade.calcular(voc, metas, SEM_VAZIAS, metodo=metodo)
    r2 = similaridade.calcular(voc, metas, SEM_VAZIAS, metodo=metodo)
    assert r1 == r2  # sem aleatoriedade
    assert r1["k_automatico"] and r1["k"] == 3 and 2 <= r1["k"] <= 8
    assert [s["k"] for s in r1["silhuetas"]] == list(range(2, 9))
    por_topico = {}
    for d in r1["documentos"]:
        por_topico.setdefault((d["id"] - 1) // 3, set()).add(d["cluster"])
    assert all(len(c) == 1 for c in por_topico.values())  # cada tópico cai num só grupo
    assert len({next(iter(c)) for c in por_topico.values()}) == 3
    # numeração pela ordem das folhas: o primeiro documento da ordem está no grupo 1
    primeiro = r1["dendrograma"]["ordem_folhas"][0]
    assert r1["documentos"][primeiro]["cluster"] == 1
    dend = r1["dendrograma"]
    assert len(dend["fusoes"]) == 8 and dend["fusoes"][-1]["tamanho"] == 9
    assert sorted(dend["ordem_folhas"]) == list(range(9))
    assert dend["altura_corte"] is not None and dend["altura_corte"] < dend["fusoes"][-1]["altura"]
    alturas = [f["altura"] for f in dend["fusoes"]]
    assert alturas == sorted(alturas)  # monotônico (average e ward)


def test_k_informado_e_k_automatico_dentro_do_intervalo():
    docs = _brinquedo_3_topicos(n_por_topico=4)
    voc, metas = _voc(docs), _metas(docs)
    r5 = similaridade.calcular(voc, metas, SEM_VAZIAS, k=5)
    assert r5["k"] == 5 and not r5["k_automatico"] and sorted({d["cluster"] for d in r5["documentos"]}) == [1, 2, 3, 4, 5]
    assert similaridade.calcular(voc, metas, SEM_VAZIAS, k=1)["k"] == 1
    rnd = random.Random(3)
    aleatorio = {i: {f"w{j}": rnd.randint(1, 9) for j in range(30) if rnd.random() < 0.5} for i in range(1, 13)}
    r = similaridade.calcular(_voc(aleatorio), _metas(aleatorio), SEM_VAZIAS, max_df=1.0)
    assert 2 <= r["k"] <= 8


def test_silhueta_confere_com_um_exemplo_a_mao():
    # 4 pontos em 1D: 0, 1 | 10, 11 ; distâncias absolutas
    pts = np.array([0.0, 1.0, 10.0, 11.0])
    dist = np.abs(pts[:, None] - pts[None, :])
    s = similaridade.silhueta(dist, np.array([0, 0, 1, 1]))
    # ponto 0: a = 1, b = (10 + 11)/2 = 10,5 -> 0,90476; ponto 1: a = 1, b = 9,5 -> 0,89474 (simétricos nos outros)
    esperado = (2 * (1 - 1 / 10.5) + 2 * (1 - 1 / 9.5)) / 4
    assert s == pytest.approx(esperado)
    assert similaridade.silhueta(dist, np.array([0, 0, 0, 0])) == 0.0


def test_mds_reproduz_distancias_euclidianas_e_tem_sinal_deterministico():
    pts = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0], [2.0, 1.5]])
    dist = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
    c1, expl = similaridade.mds_classico(dist)
    c2, _ = similaridade.mds_classico(dist.copy())
    assert np.array_equal(c1, c2)
    recon = np.linalg.norm(c1[:, None, :] - c1[None, :, :], axis=2)
    assert recon == pytest.approx(dist, abs=1e-9)  # configuração plana: reprodução exata
    for d in range(2):
        col = c1[:, d]
        assert col[int(np.argmax(np.abs(col)))] > 0  # sinal fixado: a maior coordenada em módulo é positiva
    assert expl[0] >= expl[1] > 0 and sum(expl) == pytest.approx(1.0)
    # inverter o sinal da entrada (reflexão dos pontos) dá o mesmo mapa
    refletidos = pts * np.array([-1.0, 1.0])
    dist_r = np.linalg.norm(refletidos[:, None, :] - refletidos[None, :, :], axis=2)
    assert similaridade.mds_classico(dist_r)[0] == pytest.approx(c1, abs=1e-9)


def test_vizinhos_e_termos_caracteristicos_dos_grupos():
    docs = _brinquedo_3_topicos()
    r = similaridade.calcular(_voc(docs), _metas(docs), SEM_VAZIAS)
    por_id = {d["id"]: d for d in r["documentos"]}
    for d in r["documentos"]:
        assert len(d["vizinhos"]) == 5 and d["id"] not in [v["id"] for v in d["vizinhos"]]
        sims = [v["similaridade"] for v in d["vizinhos"]]
        assert sims == sorted(sims, reverse=True)
        topico = (d["id"] - 1) // 3
        assert {(v["id"] - 1) // 3 for v in d["vizinhos"][:2]} == {topico}  # os 2 mais parecidos são do mesmo tópico
    # vizinho confere com a matriz
    d0 = por_id[1]
    idx = {d["id"]: i for i, d in enumerate(r["documentos"])}
    for v in d0["vizinhos"]:
        assert v["similaridade"] == pytest.approx(r["similaridade"][idx[1]][idx[v["id"]]], abs=1e-4)
    for g in r["grupos"]:
        topicos = {(i - 1) // 3 for i in g["ids"]}
        assert len(topicos) == 1 and g["documentos"] == 3
        t = topicos.pop()
        assert len(g["termos"]) == 6  # só as 6 palavras do tópico têm diferença positiva (comuns e únicas somem)
        assert all(x["termo"].startswith(f"t{t}w") for x in g["termos"])
        difs = [x["diferenca"] for x in g["termos"]]
        assert difs == sorted(difs, reverse=True) and all(x > 0 for x in difs)
        assert all(x["docs_no_grupo"] == 3 for x in g["termos"])


def test_termos_do_grupo_igual_a_media_do_grupo_menos_media_geral():
    docs = _brinquedo_3_topicos()
    voc, metas = _voc(docs), _metas(docs)
    mat, validos, termos, _ = similaridade.matriz_contagens(voc, metas, SEM_VAZIAS, "lema", 2, 0.9)
    x = similaridade.tfidf(mat)
    r = similaridade.calcular(voc, metas, SEM_VAZIAS, n_termos=3)
    g = r["grupos"][0]
    pos = [i for i, m in enumerate(validos) if m["id"] in g["ids"]]
    dif = x[pos].mean(axis=0) - x.mean(axis=0)
    melhores = sorted(range(len(termos)), key=lambda j: (-dif[j], termos[j]))[:3]
    assert [t["termo"] for t in g["termos"]] == [termos[j] for j in melhores]
    assert [t["diferenca"] for t in g["termos"]] == pytest.approx([dif[j] for j in melhores], abs=1e-5)


# ---------- corpus sintético com pipeline (API, etapas, CSV) ----------

_SILABAS = [c + v for c in "bdfgklmnprstvz" for v in "aeiou"]
TOPICOS = {
    "agentes": ["benchmark", "evaluation", "planning", "agents", "tool", "task"],
    "economia": ["entrepreneur", "startup", "market", "labour", "wage", "productivity"],
    "governanca": ["risk", "regulation", "safety", "policy", "accountability", "audit"],
}
# arquivo -> (tópico, grupo)
PLANO = {
    "001_2025_Alfa_Agentes.md": ("agentes", "academica"), "002_2025_Beta_Agentes.md": ("agentes", "academica"),
    "003_2025_Gama_Agentes.md": ("agentes", "academica"),
    "004_2026_Delta_Economia.md": ("economia", "academica"), "005_2026_Eps_Economia.md": ("economia", "cinzenta"),
    "006_2026_Zeta_Economia.md": ("economia", "cinzenta"),
    "007_2026_Eta_Governanca.md": ("governanca", "cinzenta"), "008_2026_Teta_Governanca.md": ("governanca", "cinzenta"),
    "009_2026_Iota_Governanca.md": ("governanca", "cinzenta"),
}
FRASES_FIXAS = {
    "agentes": "Human oversight of agents is limited. Agents use tools and human oversight is rare. ",
    "economia": "Productivity gains help founders; efficiency of the market improves. Productive teams grow. ",
    "governanca": "Prompt injection is a risk for agents. Risks and risk controls need audit. Risk matters. ",
}


def _texto_do_documento(topico: str, semente: int) -> str:
    rnd = random.Random(semente)
    palavras = TOPICOS[topico]
    partes = ["## Abstract\n\n" + FRASES_FIXAS[topico] * 2]
    for _ in range(14):
        partes.append(" ".join(rnd.choice(palavras) for _ in range(14)) + ".")
    return "\n\n".join(partes)


def _md(*paginas: str) -> str:
    return "<!-- Fonte: x.pdf | Conversão: Docling -->\n" + "".join(f"\n\n<!-- página {i + 1} -->\n\n{t}" for i, t in enumerate(paginas))


@pytest.fixture()
def corpus63(tmp_path):
    pasta = tmp_path / "corpus63"
    pasta.mkdir()
    for i, (arq, (topico, _g)) in enumerate(PLANO.items()):
        corpo = _texto_do_documento(topico, 100 + i)
        metade = len(corpo) // 2
        corte = corpo.index("\n\n", metade)
        (pasta / arq).write_text(_md(corpo[:corte], corpo[corte:].strip()), encoding="utf-8")
    # documento só com palavras vazias: sai da similaridade por não ter termos
    (pasta / "010_2026_Vazio_Stop.md").write_text(_md("the of and is " * 80), encoding="utf-8")
    return pasta


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return {e["etapa"]: e for e in r.json()["etapas"]}


@pytest.fixture()
def projeto63(client, corpus63):
    r = client.post("/api/projetos", json={"nome": "Projeto F63", "pasta_origem": str(corpus63)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    _executar(client, slug)
    docs = {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{slug}/documentos").json()}
    for arq, grupo in [*((a, g) for a, (_t, g) in PLANO.items()), ("010_2026_Vazio_Stop.md", "cinzenta")]:
        assert client.patch(f"/api/projetos/{slug}/documentos/{docs[arq]}", json={"grupo": grupo}).status_code == 200
    _executar(client, slug)
    dados.limpar_caches()
    return slug


@pytest.fixture()
def ids63(client, projeto63):
    return {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{projeto63}/documentos").json()}


def _get(client, slug, caminho, **params):
    r = client.get(f"/api/projetos/{slug}/analises/{caminho}", params=params)
    assert r.status_code == 200, r.text
    return r


def _snapshots(slug, tipo):
    db = database.sessao_do_projeto(slug)
    try:
        return list(db.query(Analise).filter(Analise.tipo == tipo).order_by(Analise.id))
    finally:
        db.close()


def test_api_similaridade_agrupa_por_topico_e_exclui_documento_vazio(client, projeto63, ids63):
    r = _get(client, projeto63, "similaridade").json()
    assert r["n_documentos"] == 9 and r["unidade"] == "lema" and r["metodo"] == "ward"
    assert [e["id"] for e in r["excluidos"]] == [ids63["010_2026_Vazio_Stop.md"]]
    por_topico = {}
    for d in r["documentos"]:
        topico = PLANO[d["arquivo"]][0]
        por_topico.setdefault(topico, set()).add(d["cluster"])
    assert r["k"] == 3 and all(len(c) == 1 for c in por_topico.values()) and len({*map(next, map(iter, por_topico.values()))}) == 3
    for g in r["grupos"]:
        topico = PLANO[next(d["arquivo"] for d in r["documentos"] if d["id"] == g["ids"][0])][0]
        assert g["termos"]  # cada grupo tem termos característicos
        assert any(t["termo"] in TOPICOS[topico] or t["termo"].rstrip("s") in TOPICOS[topico] for t in g["termos"][:5])
    n = r["n_documentos"]
    assert len(r["similaridade"]) == n and all(len(l) == n for l in r["similaridade"])
    ward = _get(client, projeto63, "similaridade", metodo="ward", k=3).json()
    assert ward["metodo"] == "ward" and ward["k"] == 3 and not ward["k_automatico"]
    assert _get(client, projeto63, "similaridade", por="forma").json()["unidade"] == "forma"


def test_api_similaridade_escopo_por_grupo_e_erros(client, projeto63):
    r = _get(client, projeto63, "similaridade", escopo="grupo", valor="academica", max_df=1.0).json()
    # os 3 de agentes dividem vocabulário; o de economia (004) não tem termo em comum com eles e sai por vetor nulo
    assert r["n_documentos"] == 3 and r["escopo"] == "grupo" and r["valor"] == "academica"
    assert all(d["grupo"] == "academica" for d in r["documentos"]) and len(r["excluidos"]) == 1
    url = f"/api/projetos/{projeto63}/analises/similaridade"
    assert client.get(url, params={"escopo": "grupo"}).status_code == 422  # falta o valor
    assert client.get(url, params={"escopo": "documento", "valor": "1"}).status_code == 422
    assert client.get(url, params={"escopo": "grupo", "valor": "inexistente"}).status_code == 422  # 0 documentos
    assert client.get(url, params={"metodo": "single"}).status_code == 422
    assert client.get(url, params={"max_df": 0}).status_code == 422


def test_api_similaridade_csv_e_agrupamentos_csv(client, projeto63):
    r = client.get(f"/api/projetos/{projeto63}/analises/similaridade.csv")
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")
    linhas = r.content.decode("utf-8-sig").strip().split("\r\n")
    assert len(linhas) == 10 and linhas[0].startswith("documento;") and len(linhas[0].split(";")) == 10
    diag = [float(linhas[i + 1].split(";")[i + 1].replace(",", ".")) for i in range(9)]
    assert diag == [1.0] * 9
    r = client.get(f"/api/projetos/{projeto63}/analises/agrupamentos.csv")
    linhas = r.content.decode("utf-8-sig").strip().split("\r\n")
    cab = linhas[0].split(";")
    assert cab[:8] == ["documento_id", "rotulo", "arquivo", "grupo", "ano", "cluster", "x", "y"] and "vizinho_5" in cab
    assert len(linhas) == 10 and {l.split(";")[5] for l in linhas[1:]} == {"1", "2", "3"}


def test_etapa_similaridade_grava_substitui_e_invalida(client, projeto63):
    linhas = _snapshots(projeto63, "similaridade")
    assert len(linhas) == 1
    a = linhas[0]
    snap = json.loads(a.resultado_json)
    assert snap["k"] == 3 and snap["n_documentos"] == 9 and json.loads(a.parametros_json)["metodo"] == "ward"
    assert a.ferramenta_equivalente == similaridade.FERRAMENTA_EQUIVALENTE
    assert _executar(client, projeto63)["similaridade"]["pulado"] == 1  # nada mudou: cache
    docs = {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{projeto63}/documentos").json()}
    assert client.patch(f"/api/projetos/{projeto63}/documentos/{docs['001_2025_Alfa_Agentes.md']}", json={"grupo": "outro"}).status_code == 200
    et = _executar(client, projeto63)
    assert et["similaridade"]["pulado"] == 0
    novas = _snapshots(projeto63, "similaridade")
    assert len(novas) == 1 and novas[0].id != a.id


# ---------- 6.4 dicionário: arquivo, validação e importação ----------

def test_dicionario_yaml_valida_normaliza_e_marca_sem_termos(tmp_path):
    texto = """
categorias:
  - id: autonomia
    nome: Autonomia
    tema: T4
    termos: ["Agent*", "human   oversight", "agent*"]
  - id: vazia
    nome: Sem termos
"""
    dic = svc_dic.ler_texto(texto)
    c0, c1 = dic["categorias"]
    assert c0["termos"] == ["agent*", "human oversight"]  # minúsculas, espaços colapsados, sem repetição
    assert c1["termos"] == [] and c1["tema"] == ""
    marcado = svc_dic.com_marcas(dic)["categorias"]
    assert marcado[1]["sem_termos"] is True and marcado[1]["aviso"] == "sem termos — preencha" and not marcado[0]["sem_termos"]
    assert [c["id"] for c in svc_dic.categorias_com_termos(dic)] == ["autonomia"]
    svc_dic.salvar(tmp_path, dic)
    assert svc_dic.carregar(tmp_path) == dic and svc_dic.hash_do_arquivo(tmp_path) != ""
    assert svc_dic.carregar(tmp_path / "nada") == {"versao": 1, "categorias": []}
    assert svc_dic.ler_texto(json.dumps({"categorias": [{"id": "x", "termos": "a, b*"}]}))["categorias"][0]["termos"] == ["a", "b*"]


@pytest.mark.parametrize("ruim,trecho", [
    ({"categorias": [{"nome": "sem id"}]}, "'id' é obrigatório"),
    ({"categorias": [{"id": "a"}, {"id": "a"}]}, "id repetido"),
    ({"categorias": [{"id": "a", "termos": ["*"]}]}, "padrão inválido"),
    ({"categorias": [{"id": "a", "termos": ["um dois tres quatro cinco seis sete"]}]}, "mais de 6 palavras"),
    ({"categorias": "x"}, "deve ser uma lista"),
    (["x"], "objeto"),
])
def test_dicionario_invalido_lista_os_erros(ruim, trecho):
    with pytest.raises(svc_dic.DicionarioInvalido) as e:
        svc_dic.validar(ruim)
    assert trecho in str(e.value)


def _xlsx(cabecalho, linhas, aba="Codebook", antes=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aba
    for linha in antes:
        ws.append(linha)
    ws.append(cabecalho)
    for linha in linhas:
        ws.append(linha)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CAB_CODEBOOK = ["Código", "Rótulo", "Tema", "Tema de ordem superior", "QP", "Regra de aplicação", "Nº sentenças (F + T)"]
LINHAS_CODEBOOK = [
    ["C1.1", "IA como cofundador", "T1 Conceituação", "Natureza e papel da IA", "QP1", "Metáfora explícita de co-founder", 32],
    ["C4.1", "Nível de autonomia", "T4 Governança sociotécnica", "Governança", "QP4", "Sugere / executa com aprovação", 58],
    ["C2.1", "emergente (definir)", "Emergente", None, None, "Consolidar ou criar código", 17],
    [None, None, None, None, None, None, None],
]


def test_importa_codebook_sem_coluna_de_palavras_chave():
    dic, rel = svc_dic.importar_codebook(_xlsx(CAB_CODEBOOK, LINHAS_CODEBOOK))
    assert rel["aba"] == "Codebook" and rel["tem_coluna_termos"] is False and rel["categorias_importadas"] == 3
    assert rel["colunas"] == {"id": "Código", "nome": "Rótulo", "tema": "Tema", "descricao": "Regra de aplicação"}
    assert rel["sem_termos"] == 3 and "nenhum termo foi inventado" in rel["aviso"]
    c = {x["id"]: x for x in dic["categorias"]}
    assert c["C1.1"]["tema"] == "T1" and c["C1.1"]["tema_nome"] == "Conceituação" and c["C1.1"]["descricao"].startswith("Metáfora")
    assert c["C2.1"]["tema"] == "Emergente" and all(x["termos"] == [] for x in c.values())


def test_importa_codebook_com_coluna_de_palavras_chave_e_mescla_com_o_existente():
    cab = [*CAB_CODEBOOK[:6], "Palavras-chave"]
    linhas = [["C1.1", "IA como cofundador", "T1 Conceituação", None, "QP1", "regra", "co-founder*; digital employee"],
              ["C4.1", "Nível de autonomia", "T4 Governança", None, "QP4", "regra", None]]
    dic, rel = svc_dic.importar_codebook(_xlsx(cab, linhas, antes=[["Codebook da MLR"], []]))  # título antes do cabeçalho
    assert rel["tem_coluna_termos"] is True and rel["linha_cabecalho"] == 3 and rel["aviso"] is None
    assert {c["id"]: c["termos"] for c in dic["categorias"]} == {"C1.1": ["co-founder*", "digital employee"], "C4.1": []}
    existente = svc_dic.validar({"categorias": [{"id": "C4.1", "termos": ["autonom*"]}, {"id": "X9", "nome": "meu", "termos": ["a"]}]})
    mesclado, rel2 = svc_dic.importar_codebook(_xlsx(cab, linhas), existente)
    por_id = {c["id"]: c for c in mesclado["categorias"]}
    assert por_id["C4.1"]["termos"] == ["autonom*"] and "X9" in por_id and rel2["novas"] == 1 and rel2["atualizadas"] == 1
    substituido, _ = svc_dic.importar_codebook(_xlsx(cab, linhas), existente, modo="substituir")
    assert [c["id"] for c in substituido["categorias"]] == ["C1.1", "C4.1"] and substituido["categorias"][1]["termos"] == []


def test_importa_codebook_erros():
    with pytest.raises(svc_dic.DicionarioInvalido, match="Não foi possível ler"):
        svc_dic.importar_codebook(b"isto nao e xlsx")
    with pytest.raises(svc_dic.DicionarioInvalido, match="colunas de código e rótulo"):
        svc_dic.importar_codebook(_xlsx(["A", "B"], [[1, 2]]))
    with pytest.raises(svc_dic.DicionarioInvalido, match="Aba 'X'"):
        svc_dic.importar_codebook(_xlsx(CAB_CODEBOOK, LINHAS_CODEBOOK), aba="X")


# ---------- 6.4 casamento: curinga e frases contra força bruta ----------

def _tokens_e_blocos(slug, doc_id):
    pasta = pasta_do_projeto(slug) / "cache"
    tk = json.loads((pasta / "tokens" / f"{doc_id}.json").read_text(encoding="utf-8"))
    blocos = json.loads((pasta / "limpo" / f"{doc_id}.json").read_text(encoding="utf-8"))["blocos"]
    return tk, blocos


def _casa_palavra(padrao, s):
    return re.fullmatch(".*".join(map(re.escape, padrao.split("*"))), s, flags=re.S) is not None


def _bruta_categoria(tk, blocos, padroes, campo="lema"):
    """Posições iniciais (sem repetição) que casam com algum padrão, recontadas token a token."""
    inc, norm, unid = tk["incluir"], tk["norm"], tk[campo]
    achadas = set()
    for padrao in padroes:
        palavras = padrao.split()
        for p in range(tk["n"]):
            if p + len(palavras) > tk["n"]:
                break
            ok = True
            for j, w in enumerate(palavras):
                q = p + j
                if not (inc[q] and len(norm[q]) >= 2 and _casa_palavra(w, unid[q])):
                    ok = False
                    break
                if j > 0:
                    gap = blocos[tk["bloco"][q]]["texto"][tk["fim"][q - 1]:tk["inicio"][q]] if tk["bloco"][q] == tk["bloco"][q - 1] else None
                    if gap is None or gap.strip(" -") != "" or "\n" in gap:
                        ok = False
                        break
            if ok:
                achadas.add(p)
    return achadas


DIC_DEMO = {"categorias": [
    {"id": "autonomia", "nome": "Autonomia", "tema": "T4", "termos": ["agent*", "human oversight"]},
    {"id": "produtividade", "nome": "Produtividade", "tema": "T3", "termos": ["productiv*", "efficien*"]},
    {"id": "risco", "nome": "Risco", "tema": "T4", "termos": ["risk*", "prompt injection"]},
    {"id": "vazia", "nome": "Sem termos", "tema": "T5", "termos": []},
]}


def test_casamento_por_curinga_e_frase_confere_com_forca_bruta(client, projeto63, ids63):
    dic = svc_dic.validar(DIC_DEMO)
    cats = dicionario.compilar_categorias(dic)
    assert [c["id"] for c in cats] == ["autonomia", "produtividade", "risco"]  # categoria sem termos fica de fora
    total_visto = 0
    for arq, doc_id in ids63.items():
        tk, blocos = _tokens_e_blocos(projeto63, doc_id)
        for campo, por in (("lema", "lema"), ("norm", "forma")):
            obtido = dicionario.ocorrencias_no_documento(tk, blocos, cats, por)
            for c in dic["categorias"][:3]:
                esperado = _bruta_categoria(tk, blocos, c["termos"], campo)
                assert set(obtido[c["id"]]) == esperado, (arq, c["id"], por)
                total_visto += len(esperado) if por == "lema" else 0
    assert total_visto > 50  # o corpus tem ocorrências de verdade (o teste não é vazio)
    # as frases entram: "human oversight" e "prompt injection" aparecem nos textos de agentes/governança
    tk, blocos = _tokens_e_blocos(projeto63, ids63["001_2025_Alfa_Agentes.md"])
    ocorr = dicionario.ocorrencias_no_documento(tk, blocos, cats, "lema")["autonomia"]
    assert "human oversight" in set(ocorr.values()) and any(v.startswith("agent") for v in ocorr.values())


def test_frase_prevalece_sobre_palavra_no_mesmo_inicio_e_nao_conta_duas_vezes():
    tk = {"norm": ["human", "oversight", "agent", "agents"], "lema": ["human", "oversight", "agent", "agent"],
          "incluir": [1, 1, 1, 1], "bloco": [0] * 4, "inicio": [0, 6, 16, 22], "fim": [5, 15, 21, 28], "n": 4}
    blocos = [{"texto": "human oversight agent agents"}]
    cat = {"id": "c", "padroes": [dicionario.compilar_padrao(p) for p in ("human*", "human oversight", "agent*", "agent agent")]}
    r = dicionario.ocorrencias_no_documento(tk, blocos, [cat], "lema")["c"]
    assert set(r) == {0, 2, 3}  # "human*" e a frase começam no token 0: uma ocorrência, com o texto da frase
    assert r[0] == "human oversight" and r[2] == "agent agent" and r[3] == "agent"


# ---------- 6.4 agregação por grupo/ano, G² e Log Ratio ----------

def _agrega_bruto(slug, ids63, dic, agrupar_por):
    """{categoria: {unidade: ocorrências}} e tokens por unidade, a partir dos tokens, independente do módulo."""
    cats = [c for c in dic["categorias"] if c["termos"]]
    contagem = {c["id"]: Counter() for c in cats}
    tokens = Counter()
    for arq, doc_id in ids63.items():
        tk, blocos = _tokens_e_blocos(slug, doc_id)
        un = agrupar_por(arq)
        tokens[un] += sum(1 for n, i in zip(tk["norm"], tk["incluir"]) if i and len(n) >= 2)
        for c in cats:
            contagem[c["id"]][un] += len(_bruta_categoria(tk, blocos, c["termos"]))
    return contagem, tokens


def test_agregacao_por_grupo_e_ano_confere_e_reutiliza_g2_e_log_ratio(client, projeto63, ids63):
    dic = svc_dic.validar(DIC_DEMO)
    pasta = pasta_do_projeto(projeto63)
    voc = svc_voc.ler_vocabulario(pasta)
    db = database.sessao_do_projeto(projeto63)
    try:
        metas = dados.documentos_do_corpus(db, pasta)
    finally:
        db.close()
    grupo_de = {m["arquivo"]: m["grupo"] for m in metas}
    ano_de = {m["arquivo"]: str(m["ano"]) for m in metas}
    for agrupar, mapa in (("grupo", grupo_de), ("ano", ano_de)):
        r = dicionario.calcular(pasta, voc, metas, dic, agrupar=agrupar)
        bruto, tokens = _agrega_bruto(projeto63, ids63, dic, lambda arq: mapa[arq])
        assert [u["chave"] for u in r["unidades"]] == sorted(tokens) and r["comparacao"] is True
        assert r["tokens"] == sum(tokens.values()) and [s["id"] for s in r["sem_termos"]] == ["vazia"]
        for c in r["categorias"]:
            assert c["total"] == sum(bruto[c["id"]].values())
            assert c["por_10k"] == pytest.approx(c["total"] / r["tokens"] * 10000, abs=0.01)
            assert c["media_por_doc"] == pytest.approx(c["total"] / r["documentos"], abs=0.001)
            for u in c["unidades"]:
                a, ct = bruto[c["id"]][u["chave"]], tokens[u["chave"]]
                b, d = c["total"] - a, r["tokens"] - ct
                assert u["n"] == a and u["por_10k"] == pytest.approx(a / ct * 10000, abs=0.01)
                assert u["g2"] == pytest.approx(keyness.log_likelihood(a, b, ct, d))  # mesma função da 6.1
                assert u["log_ratio"] == pytest.approx(keyness.log_ratio(a, b, ct, d))
                assert u["p"] == pytest.approx(keyness.valor_p(u["g2"]))
            assert c["consulta_kwic"] == ", ".join(f'"{t}"' if " " in t else t for t in c["termos"])
            assert 0 <= c["docs"] <= r["documentos"] and c["termos_top"]
    por_doc = dicionario.calcular(pasta, voc, metas, dic, agrupar="documento")
    assert por_doc["comparacao"] is False and len(por_doc["unidades"]) == 10
    assert all(u["g2"] is None for c in por_doc["categorias"] for u in c["unidades"])
    assert sum(u["n"] for u in por_doc["categorias"][0]["unidades"]) == por_doc["categorias"][0]["total"]
    forma = dicionario.calcular(pasta, voc, metas, dic, por="forma")
    assert forma["por"] == "forma" and forma["categorias"][0]["total"] > 0
    with pytest.raises(ValueError, match="Agrupamento"):
        dicionario.calcular(pasta, voc, metas, dic, agrupar="mes")


def test_grupo_com_unidade_unica_nao_compara(client, projeto63):
    pasta = pasta_do_projeto(projeto63)
    voc = svc_voc.ler_vocabulario(pasta)
    metas = [{"id": int(i), "rotulo": i, "arquivo": f"{i}.md", "grupo": "so", "ano": 2025} for i in list(voc["documentos"])[:3]]
    r = dicionario.calcular(pasta, voc, metas, svc_dic.validar(DIC_DEMO))
    assert r["comparacao"] is False and all(u["g2"] is None for c in r["categorias"] for u in c["unidades"])


# ---------- 6.4 API e etapa ----------

def _put(client, slug, dic, tipo="json"):
    corpo = json.dumps(dic) if tipo == "json" else dic
    return client.put(f"/api/projetos/{slug}/dicionario", content=corpo.encode("utf-8"),
                      headers={"Content-Type": "application/json" if tipo == "json" else "text/yaml"})


def test_api_dicionario_put_get_yaml_json_e_erros(client, projeto63):
    base = f"/api/projetos/{projeto63}/dicionario"
    vazio = client.get(base).json()
    assert vazio["total"] == 0 and vazio["categorias"] == []
    r = _put(client, projeto63, DIC_DEMO)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 4 and r.json()["sem_termos"] == 1
    assert (pasta_do_projeto(projeto63) / "dicionario.yaml").is_file()
    g = client.get(base).json()
    assert [c["id"] for c in g["categorias"]] == ["autonomia", "produtividade", "risco", "vazia"]
    assert g["categorias"][3]["aviso"] == "sem termos — preencha"
    y = client.get(base, params={"formato": "yaml"})
    assert y.headers["content-type"].startswith("text/yaml") and "human oversight" in y.text
    r = _put(client, projeto63, "categorias:\n  - id: so_yaml\n    termos: [alfa*]\n", tipo="yaml")  # YAML puro
    assert r.status_code == 200 and [c["id"] for c in r.json()["categorias"]] == ["so_yaml"]
    r = _put(client, projeto63, {"categorias": [{"id": "a"}, {"id": "a"}, {"nome": "x"}]})
    assert r.status_code == 422 and len(r.json()["detail"]["erros"]) == 2
    assert [c["id"] for c in client.get(base).json()["categorias"]] == ["so_yaml"]  # o inválido não gravou nada
    assert _put(client, projeto63, "a: [", tipo="yaml").status_code == 422


def test_api_importar_codebook_cria_categorias_sem_termos_e_aceita_upload(client, projeto63):
    base = f"/api/projetos/{projeto63}/dicionario"
    r = client.post(f"{base}/importar-codebook", content=_xlsx(CAB_CODEBOOK, LINHAS_CODEBOOK))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["relatorio"]["tem_coluna_termos"] is False and corpo["relatorio"]["categorias_importadas"] == 3
    assert corpo["dicionario"]["sem_termos"] == 3 and all(c["termos"] == [] for c in corpo["dicionario"]["categorias"])
    # o usuário preenche termos de uma categoria e reimporta: os termos sobrevivem (modo mesclar)
    dic = client.get(base).json()
    for c in dic["categorias"]:
        if c["id"] == "C4.1":
            c["termos"] = ["autonom*"]
    assert _put(client, projeto63, dic).status_code == 200
    r = client.post(f"{base}/importar-codebook", content=_xlsx(CAB_CODEBOOK, LINHAS_CODEBOOK))
    assert {c["id"]: c["termos"] for c in r.json()["dicionario"]["categorias"]}["C4.1"] == ["autonom*"]
    assert client.post(f"{base}/importar-codebook", content=b"").status_code == 400
    assert client.post(f"{base}/importar-codebook", content=b"lixo").status_code == 422
    assert client.post(f"{base}/importar-codebook", params={"modo": "x"}, content=b"lixo").status_code == 422


def test_api_analises_dicionario_e_csv(client, projeto63):
    assert _put(client, projeto63, DIC_DEMO).status_code == 200
    r = _get(client, projeto63, "dicionario").json()
    assert r["agrupar"] == "grupo" and r["por"] == "lema" and r["comparacao"] is True
    assert {c["id"] for c in r["categorias"]} == {"autonomia", "produtividade", "risco"} and r["sem_termos"][0]["id"] == "vazia"
    aut = next(c for c in r["categorias"] if c["id"] == "autonomia")
    assert aut["total"] > 0 and {u["chave"] for u in aut["unidades"]} == {"academica", "cinzenta"}
    assert "human oversight" in {t["termo"] for t in aut["termos_top"]}
    assert _get(client, projeto63, "dicionario", agrupar="ano").json()["agrupar"] == "ano"
    assert len(_get(client, projeto63, "dicionario", agrupar="documento").json()["unidades"]) == 10
    assert client.get(f"/api/projetos/{projeto63}/analises/dicionario", params={"agrupar": "mes"}).status_code == 422
    csv = client.get(f"/api/projetos/{projeto63}/analises/dicionario.csv")
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf")
    linhas = csv.content.decode("utf-8-sig").strip().split("\r\n")
    assert linhas[0] == "categoria;nome;tema;grupo;ocorrencias;por_10k;documentos_com;documentos;g2;p;log_ratio"
    assert len(linhas) == 1 + 3 * 3  # (corpus) + academica + cinzenta, para cada categoria com termos
    assert any(l.startswith("autonomia;Autonomia;T4;(corpus);") for l in linhas)


def test_kwic_aceita_a_consulta_do_dicionario_com_palavras_e_frases(client, projeto63):
    dic = svc_dic.validar(DIC_DEMO)
    consulta = dicionario.consulta_kwic(dic["categorias"][0]["termos"])
    assert consulta == 'agent*, "human oversight"'
    r = _get(client, projeto63, "kwic", q=consulta, por="lema", limit=2000).json()
    pasta = pasta_do_projeto(projeto63)
    cats = dicionario.compilar_categorias(dic)[:1]
    esperado = 0
    for d in client.get(f"/api/projetos/{projeto63}/documentos").json():
        if d["arquivo"].startswith("010"):
            continue
        tk, blocos = _tokens_e_blocos(projeto63, d["id"])
        esperado += len(dicionario.ocorrencias_no_documento(tk, blocos, cats, "lema")["autonomia"])
    assert r["total"] == esperado > 0
    assert _get(client, projeto63, "kwic", q='"human oversight"', por="lema").json()["total"] > 0  # frase simples continua igual


def _dic_snapshots(slug):
    return _snapshots(slug, "dicionario")


def test_etapa_dicionario_grava_so_com_termos_e_put_invalida_o_instantaneo(client, projeto63):
    assert _dic_snapshots(projeto63) == []  # sem dicionário: nada gravado
    sem_termos = {"categorias": [{"id": "a", "nome": "só rótulo"}]}
    assert _put(client, projeto63, sem_termos).status_code == 200
    et = _executar(client, projeto63)
    assert _dic_snapshots(projeto63) == [] and "dicionario" in et and et["dicionario"].get("erro", 0) == 0

    assert _put(client, projeto63, DIC_DEMO).status_code == 200
    et = _executar(client, projeto63)
    assert et["dicionario"]["pulado"] == 0
    linhas = _dic_snapshots(projeto63)
    assert len(linhas) == 1
    snap = json.loads(linhas[0].resultado_json)
    assert snap["agrupar"] == "grupo" and {c["id"] for c in snap["categorias"]} == {"autonomia", "produtividade", "risco"}
    assert json.loads(linhas[0].parametros_json)["hash_dicionario"] == svc_dic.hash_do_arquivo(pasta_do_projeto(projeto63))
    assert linhas[0].ferramenta_equivalente == dicionario.FERRAMENTA_EQUIVALENTE
    assert _executar(client, projeto63)["dicionario"]["pulado"] == 1  # nada mudou: cache e mesma linha
    assert [x.id for x in _dic_snapshots(projeto63)] == [linhas[0].id]

    # PUT com outro conteúdo: o instantâneo antigo some na hora e a próxima execução recalcula
    novo = {"categorias": [{"id": "so_risco", "nome": "Risco", "termos": ["risk*"]}]}
    assert _put(client, projeto63, novo).status_code == 200
    assert _dic_snapshots(projeto63) == []
    et = _executar(client, projeto63)
    assert et["dicionario"]["pulado"] == 0
    refeito = _dic_snapshots(projeto63)
    assert len(refeito) == 1 and [c["id"] for c in json.loads(refeito[0].resultado_json)["categorias"]] == ["so_risco"]

    # dicionário sem nenhuma categoria com termos: a linha antiga é removida
    assert _put(client, projeto63, sem_termos).status_code == 200
    _executar(client, projeto63)
    assert _dic_snapshots(projeto63) == []


def test_editar_o_grupo_invalida_o_instantaneo_do_dicionario(client, projeto63):
    assert _put(client, projeto63, DIC_DEMO).status_code == 200
    _executar(client, projeto63)
    antes = _dic_snapshots(projeto63)
    docs = {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{projeto63}/documentos").json()}
    assert client.patch(f"/api/projetos/{projeto63}/documentos/{docs['004_2026_Delta_Economia.md']}", json={"grupo": "terceiro"}).status_code == 200
    assert _executar(client, projeto63)["dicionario"]["pulado"] == 0
    depois = _dic_snapshots(projeto63)
    assert len(depois) == 1 and depois[0].id != antes[0].id
    assert {u["chave"] for u in json.loads(depois[0].resultado_json)["unidades"]} == {"academica", "cinzenta", "terceiro"}
