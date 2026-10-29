"""7.1 CHD de Reinert, 7.2 similitude/rede de coocorrência e 15.2 comunidades/centralidade/layout.
Funções puras contra cálculo independente (fórmula direta do χ², scipy, força bruta, valores à mão); API, CSV, etapas
e partição "classe" com o corpus sintético da 6.3/6.4 (3 tópicos plantados; fixtures de test_frente63_64)."""
import itertools
import json
import math
from collections import Counter

import networkx as nx
import numpy as np
import pytest
import scipy.sparse as sp
from scipy.stats import chi2_contingency

from app.services.analises import reinert as R, similitude as SM
from tests.test_frente63_64 import PLANO, TOPICOS, _executar, _get, _snapshots, corpus63, ids63, projeto63  # noqa: F401


# ---------- apoio ----------

def _plantado(n_por=60, topicos=3, voc=20, ruido=30, k=8, kr=2, semente=1):
    """Matriz binária com tópicos de vocabulário disjunto + palavras de ruído comuns; devolve (X, verdade)."""
    rng = np.random.default_rng(semente)
    linhas, verdade = [], []
    for t in range(topicos):
        for _ in range(n_por):
            cols = list(rng.choice(voc, k, replace=False) + t * voc) + list(rng.choice(ruido, kr, replace=False) + topicos * voc)
            linhas.append(sorted(cols))
            verdade.append(t)
    I, J = len(linhas), topicos * voc + ruido
    r = [i for i, c in enumerate(linhas) for _ in c]
    c = [j for cs in linhas for j in cs]
    return sp.csr_matrix((np.ones(len(r)), (r, c)), shape=(I, J)), np.array(verdade)


def _ari(a, b):
    """Índice de Rand ajustado (Hubert & Arabie 1985), implementação direta."""
    n = len(a)
    tab = Counter(zip(a, b))
    soma_ij = sum(math.comb(v, 2) for v in tab.values())
    soma_a = sum(math.comb(v, 2) for v in Counter(a).values())
    soma_b = sum(math.comb(v, 2) for v in Counter(b).values())
    esperado = soma_a * soma_b / math.comb(n, 2)
    maximo = (soma_a + soma_b) / 2
    return (soma_ij - esperado) / (maximo - esperado)


def _pureza(classe, verdade):
    ok = classe > 0
    return sum(max(Counter(verdade[(classe == c)]).values()) for c in set(classe[ok])) / ok.sum()


def _chi2_direto(X, mask):
    """χ² da tabela 2 × formas pelo scipy (independente da identidade com S usada no módulo)."""
    a = np.asarray(X[mask].sum(axis=0)).ravel()
    b = np.asarray(X[~mask].sum(axis=0)).ravel()
    ok = (a + b) > 0
    return chi2_contingency(np.vstack([a[ok], b[ok]]), correction=False)[0]


# ---------- 7.1 estatística ----------

def test_chi2_2xp_e_2x2_conferem_com_scipy():
    rng = np.random.default_rng(7)
    for _ in range(20):
        a, b = rng.integers(0, 30, 12), rng.integers(0, 30, 12)
        a[0] += 1
        b[1] += 1
        ok = (a + b) > 0
        assert R.chi2_tabela_2xp(a, b) == pytest.approx(chi2_contingency(np.vstack([a[ok], b[ok]]), correction=False)[0], rel=1e-10)
    for a, nl, nc, N in [(30, 50, 60, 200), (2, 50, 60, 200), (5, 5, 5, 100)]:
        x2, p = R.chi2_2x2(a, nl, nc, N)
        tab = np.array([[a, nl - a], [nc - a, N - nl - nc + a]])
        c2, p2, _, esp = chi2_contingency(tab, correction=False)
        assert abs(float(x2)) == pytest.approx(c2, rel=1e-10) and float(p) == pytest.approx(p2, rel=1e-8)
        assert (float(x2) > 0) == (a > esp[0, 0])


def test_corte_no_eixo_confere_com_calculo_direto_e_forca_bruta():
    X, _ = _plantado(n_por=4, topicos=2, voc=6, ruido=4, k=3, kr=1, semente=3)  # 8 linhas
    X = R.binaria(X)
    coords, lam = R.primeiro_fator(X)
    assert 0 < lam <= 1
    mask, chi, chis = R.melhor_corte(X, coords)
    ordem = np.lexsort((np.arange(X.shape[0]), coords))
    for k in range(1, X.shape[0]):  # χ² de cada corte = cálculo direto
        m = np.zeros(X.shape[0], bool)
        m[ordem[:k]] = True
        assert chis[k - 1] == pytest.approx(_chi2_direto(X, m), rel=1e-9)
    assert chi == pytest.approx(chis.max()) and chi == pytest.approx(_chi2_direto(X, mask), rel=1e-9)
    # força bruta sobre TODAS as bipartições: no exemplo plantado a CHD acha o ótimo global
    I = X.shape[0]
    melhor = max(_chi2_direto(X, np.array([(s >> i) & 1 for i in range(I)], bool))
                 for s in range(1, 2 ** (I - 1)))
    b = R.bipartir(X)
    assert b["chi2"] == pytest.approx(melhor, rel=1e-9)
    assert b["chi2"] >= b["chi2_corte"] - 1e-9


def test_realocacao_nunca_diminui_o_criterio_e_para_num_otimo_local():
    X, _ = _plantado(n_por=25, topicos=3, voc=10, ruido=10, k=5, kr=3, semente=11)
    X = R.binaria(X)
    rng = np.random.default_rng(0)
    for _ in range(5):
        inicial = rng.random(X.shape[0]) < 0.5
        g, hist, movidos = R.realocar(X, inicial)
        assert all(h2 >= h1 - 1e-9 for h1, h2 in zip(hist, hist[1:]))
        assert hist[0] == pytest.approx(_chi2_direto(X, inicial), rel=1e-9)
        assert hist[-1] == pytest.approx(_chi2_direto(X, g), rel=1e-9)
        assert movidos > 0 and hist[-1] > hist[0]
        for i in range(X.shape[0]):  # nenhuma troca isolada melhora
            g2 = g.copy()
            g2[i] = not g2[i]
            if g2.any() and (~g2).any():
                assert _chi2_direto(X, g2) <= hist[-1] * (1 + 1e-9)


def test_eixo_1_denso_e_esparso_coincidem():
    X, _ = _plantado(n_por=40, semente=5)
    X = R.binaria(X)
    F1, l1 = R.primeiro_fator(X, denso=True)
    F2, l2 = R.primeiro_fator(X, denso=False)
    assert l1 == pytest.approx(l2, rel=1e-8) and np.allclose(F1, F2, atol=1e-7)


def test_chd_recupera_topicos_plantados_e_e_deterministica():
    X, verdade = _plantado(n_por=60, topicos=3, semente=1)
    r = R.chd(X, classes=3, min_classe=5)
    assert r["k"] == 3 and (r["classe"] > 0).all()
    assert _pureza(r["classe"], verdade) >= 0.9 and _ari(r["classe"], verdade) >= 0.9
    r2 = R.chd(X, classes=3, min_classe=5)
    assert np.array_equal(r["classe"], r2["classe"]) and R.nos_publicos(r["nos"]) == R.nos_publicos(r2["nos"])
    # mais classes pedidas: cada classe continua pura (subdivide tópicos, não os mistura)
    r10 = R.chd(X, classes=10, min_classe=5)
    assert _pureza(r10["classe"], verdade) >= 0.95 and r10["k"] <= 10
    nos = R.nos_publicos(r10["nos"])
    assert nos[0]["n"] == X.shape[0] and all(n["n"] == sum(nos[f]["n"] for f in n["filhos"]) for n in nos if n["filhos"])


def test_classes_pequenas_sao_descartadas_e_corpus_minimo():
    X, _ = _plantado(n_por=30, topicos=2, semente=2)
    r = R.chd(X, classes=6, min_classe=25)
    tam = Counter(r["classe"][r["classe"] > 0])
    assert all(v >= 25 for v in tam.values())
    descartadas = [n for n in R.nos_publicos(r["nos"]) if n["descartada"]]
    assert sum(n["n"] for n in descartadas) == int((r["classe"] == 0).sum())
    um = R.chd(sp.csr_matrix(np.ones((1, 3))), classes=3)
    assert um["k"] == 0 and len(um["nos"]) == 1 and um["classe"].tolist() == [0]  # nada a dividir: não quebra
    with pytest.raises(ValueError):
        R.calcular(None, [], frozenset(), classes=1)
    assert R.min_classe_automatico(100) == 5 and R.min_classe_automatico(1000) == 25


def test_uc_e_cruzamento_da_classificacao_dupla():
    uc = R.agrupar_em_uc(["a"] * 5 + ["b"] * 2, [38, 41, 20, 22, 40, 39, 30], 60)
    assert uc.tolist() == [0, 0, 1, 1, 2, 3, 3]  # 38+41 (79 mais perto de 60 que 38); nunca atravessa documento
    assert R.agrupar_em_uc(["a"] * 3, [40, 40, 40], 40).tolist() == [0, 1, 2]
    a = np.array([1] * 40 + [2] * 40 + [3] * 20 + [0] * 5)
    b = np.array([2] * 38 + [1] * 2 + [1] * 39 + [3] + [3] * 10 + [1] * 10 + [2] * 5)
    cz = R.cruzar(a, b, min_classe=5)
    assert [(p["classe_a"], p["classe_b"], p["n"]) for p in cz["pares"]] == [(1, 2, 38), (2, 1, 39), (3, 3, 10)]
    assert cz["classe"].tolist() == [1] * 38 + [0] * 2 + [2] * 39 + [0] + [3] * 10 + [0] * 10 + [0] * 5
    assert np.array(cz["tabela"]).sum() == 100


# ---------- 7.2 / 15.2 estatística ----------

def test_indices_de_coocorrencia_conferem_com_formulas():
    B = np.array([[1, 1, 0], [1, 1, 1], [1, 0, 1], [0, 0, 1], [1, 1, 0]])  # N = 5; n = [4, 3, 3]
    for indice, esperado in [
        ("coocorrencia", {(0, 1): 3, (0, 2): 2, (1, 2): 1}),
        ("jaccard", {(0, 1): 3 / 4, (0, 2): 2 / 5, (1, 2): 1 / 5}),
        ("cosseno", {(0, 1): 3 / math.sqrt(12), (0, 2): 2 / math.sqrt(12), (1, 2): 1 / 3}),
    ]:
        W, C, n = SM.matriz_de_indices(B, indice)
        assert n.tolist() == [4, 3, 3]
        for (i, j), v in esperado.items():
            assert W[i, j] == pytest.approx(v) and W[j, i] == pytest.approx(v)
    W, *_ = SM.matriz_de_indices(B, "pmi")
    assert W[0, 1] == pytest.approx(math.log2(3 * 5 / 12))  # > 0
    assert np.isnan(W[0, 2]) and np.isnan(W[1, 2])  # PMI <= 0 não vira aresta (log2(10/12), log2(5/9))
    with pytest.raises(ValueError):
        SM.matriz_de_indices(B, "dice")


def test_arvore_maxima_igual_a_forca_bruta():
    rng = np.random.default_rng(4)
    for _ in range(6):
        m = 6
        W = np.full((m, m), np.nan)
        for i, j in itertools.combinations(range(m), 2):
            if rng.random() < 0.8:
                W[i, j] = W[j, i] = float(rng.integers(1, 9))  # pesos com empates
        arv = SM.arvore_maxima(W)
        G = nx.Graph()
        G.add_nodes_from(range(m))
        G.add_edges_from((i, j) for i, j, _ in arv)
        comps = nx.number_connected_components(G)
        assert nx.is_forest(G) and len(arv) == m - comps
        todas = [(i, j) for i, j in itertools.combinations(range(m), 2) if not np.isnan(W[i, j])]
        melhor = -1
        for sub in itertools.combinations(todas, m - comps):
            H = nx.Graph()
            H.add_nodes_from(range(m))
            H.add_edges_from(sub)
            if nx.is_forest(H) and nx.number_connected_components(H) == comps:
                melhor = max(melhor, sum(W[i, j] for i, j in sub))
        assert sum(w for *_, w in arv) == pytest.approx(melhor)
    assert SM.arvore_maxima(W) == SM.arvore_maxima(W.copy())  # determinística (empates pela ordem)


def test_rede_top_k_e_limiar():
    W = np.array([[np.nan, 5, 4, 1], [5, np.nan, 3, np.nan], [4, 3, np.nan, 2], [1, np.nan, 2, np.nan]], dtype=float)
    # mais forte de cada nó: 0→1, 1→0, 2→0, 3→2
    assert {(i, j) for i, j, _ in SM.rede_top_k(W, k=1)} == {(0, 1), (0, 2), (2, 3)}
    assert {(i, j) for i, j, _ in SM.rede_top_k(W, k=2)} == {(0, 1), (0, 2), (1, 2), (2, 3), (0, 3)}
    assert {(i, j) for i, j, _ in SM.rede_top_k(W, limiar=3.5)} == {(0, 1), (0, 2)}


def test_comunidades_em_duas_cliques_e_modularidade_a_mao():
    arestas = [(i, j, 1.0) for i, j in itertools.combinations(range(5), 2)]
    arestas += [(i, j, 1.0) for i, j in itertools.combinations(range(5, 10), 2)] + [(4, 5, 1.0)]
    G = SM.grafo(10, arestas)
    comms, q = SM.comunidades(G)
    assert comms == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
    m = 21  # Q = Σ_c [L_c/m − (d_c/2m)²], com L_c = 10 e d_c = 21
    assert q == pytest.approx(2 * (10 / m - (21 / (2 * m)) ** 2))
    assert SM.comunidades(G) == (comms, q)  # semente fixa


def test_centralidades_conferem_com_valores_a_mao():
    # estrela com centro 0 e 4 folhas, pesos 1
    G = SM.grafo(5, [(0, k, 1.0) for k in range(1, 5)])
    c = SM.centralidades(G)
    assert c["grau"] == {0: 4, 1: 1, 2: 1, 3: 1, 4: 1}
    assert c["intermediacao"][0] == pytest.approx(1.0) and c["intermediacao"][1] == 0
    # PageRank da estrela: centro = (1−d)/n + d·Σ(folhas) ; folha = (1−d)/n + d·centro/4
    d, n = 0.85, 5
    folha = ((1 - d) / n + d * ((1 - d) / n) / 4) / (1 - d * d)  # resolve o sistema 2 × 2
    centro = (1 - d) / n + d * 4 * folha
    assert c["pagerank"][0] == pytest.approx(centro, rel=1e-6) and c["pagerank"][1] == pytest.approx(folha, rel=1e-6)
    # caminho ponderado 0-1-2 com pesos 2 e 1: grau ponderado e intermediação do meio
    P = SM.grafo(3, [(0, 1, 2.0), (1, 2, 1.0)])
    cp = SM.centralidades(P)
    assert cp["grau_ponderado"] == {0: 2.0, 1: 3.0, 2: 1.0} and cp["intermediacao"][1] == pytest.approx(1.0)


def test_layout_deterministico_e_normalizado():
    G = SM.grafo(6, [(0, 1, 3.0), (1, 2, 2.0), (2, 0, 1.0), (3, 4, 1.0), (4, 5, 2.0), (2, 3, 0.5)])
    p1, p2 = SM.layout(G), SM.layout(G)
    assert p1 == p2
    xs = [v[0] for v in p1.values()]
    ys = [v[1] for v in p1.values()]
    assert min(xs + ys) >= -1e-9 and max(xs + ys) <= 1 + 1e-9
    assert max(max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx(1.0)


# ---------- API, CSV, etapas (corpus sintético com 3 tópicos) ----------

def _topico_do_doc(client, slug):
    docs = client.get(f"/api/projetos/{slug}/documentos").json()
    return {str(d["id"]): PLANO[d["arquivo"]][0] for d in docs if d["arquivo"] in PLANO}


def test_api_reinert_recupera_os_topicos_dos_documentos(client, projeto63):
    r = _get(client, projeto63, "reinert", classes=3, mapa=True).json()
    assert r["k"] == 3 and r["ferramenta_equivalente"].startswith("IRaMuTeQ")
    assert r["segmentos_classificados"] <= r["segmentos_classificaveis"] <= r["segmentos_total"]
    assert r["retencao_pct"] == pytest.approx(100 * r["segmentos_classificados"] / r["segmentos_total"], abs=0.01)
    topico = _topico_do_doc(client, projeto63)
    classe, verdade = [], []
    for doc, mapa in r["classes_por_documento"].items():
        for c in mapa:
            if c > 0 and doc in topico:
                classe.append(c)
                verdade.append(topico[doc])
    assert _pureza(np.array(classe), np.array(verdade)) >= 0.9
    for c in r["classes"]:
        assert c["formas"] and c["formas"][0]["chi2"] >= R.CHI2_CRITICO
        assert any(f["forma"] in TOPICOS[t] or f["forma"].rstrip("s") in TOPICOS[t] for t in TOPICOS for f in c["formas"][:3])
        assert c["segmentos"] and c["segmentos"][0]["texto"] and c["segmentos"][0]["pagina"] >= 1
        assert c["variaveis"]["documento"]
        f = c["formas"][0]
        assert f["pct_classe"] == pytest.approx(100 * f["freq_classe"] / f["freq_total"], abs=0.01)
    assert r["afc"]["k"] == 2 and len(r["afc"]["classes"]) == 3
    assert "classes_por_documento" not in _get(client, projeto63, "reinert", classes=3).json()
    assert _get(client, projeto63, "reinert", classes=3).json()["classes"] == r["classes"]  # determinística
    d = _get(client, projeto63, "reinert", classes=3, dupla=True, tamanho_a=20, tamanho_b=45, min_classe=3).json()
    assert d["dupla"] and len(d["dendrogramas"]) == 2 and d["cruzamento"]["pares"]
    assert client.get(f"/api/projetos/{projeto63}/analises/reinert", params={"classes": 1}).status_code == 422
    assert client.get(f"/api/projetos/{projeto63}/analises/reinert", params={"tamanho_a": 60}).status_code == 422


def test_api_reinert_csv_e_particao_classe(client, projeto63):
    csv = _get(client, projeto63, "reinert/classes.csv", classes=3).content.decode("utf-8-sig").splitlines()
    assert csv[0].startswith("classe;st_classe") and any(";forma;" in l for l in csv[1:]) and any(";documento;" in l for l in csv[1:])
    seg = _get(client, projeto63, "reinert/segmentos.csv", classes=3).content.decode("utf-8-sig").splitlines()
    assert seg[0] == "documento_id;documento;segmento;pagina;palavras;classe;texto" and len(seg) > 10
    # especificidades e AFC por classe usam a CHD com os parâmetros do projeto (10 classes pedidas)
    r = _get(client, projeto63, "reinert", mapa=True).json()
    es = _get(client, projeto63, "especificidades", particao="classe").json()
    assert [p["chave"] for p in es["partes"]] == [str(c["classe"]) for c in r["classes"]]
    assert es["particao"] == "classe" and es["partes"][0]["positivas"]
    af = _get(client, projeto63, "afc", particao="classe", n_termos=20).json()
    assert af["n_colunas"] == r["k"]
    t = _get(client, projeto63, "especificidades/termo", termo="risk", particao="classe").json()
    assert len(t["partes"]) == r["k"]


def test_api_similitude_arvore_rede_e_csv(client, projeto63):
    r = _get(client, projeto63, "similitude", n_formas=20).json()
    assert r["arvore"] and r["indice"] == "coocorrencia" and r["n_formas"] == 20
    assert r["n_arestas"] == 20 - r["componentes"]  # floresta geradora
    assert r["ferramenta_equivalente"] == "IRaMuTeQ análise de similitude"
    assert all(0 <= n["x"] <= 1 and 0 <= n["y"] <= 1 for n in r["nos"])
    assert r["modularidade"] is not None and r["comunidades"]
    # as palavras de cada tópico caem majoritariamente na mesma comunidade (rede Jaccard)
    j = _get(client, projeto63, "similitude", n_formas=20, indice="jaccard", arvore=False).json()
    assert not j["arvore"] and j["ferramenta_equivalente"] == "KH Coder co-occurrence network"
    com = {n["forma"]: n["comunidade"] for n in j["nos"]}
    for palavras in TOPICOS.values():
        presentes = [com[p] for p in palavras if p in com]
        if len(presentes) >= 3:
            assert Counter(presentes).most_common(1)[0][1] >= 0.8 * len(presentes)
    assert _get(client, projeto63, "similitude", n_formas=20, indice="jaccard", arvore=False).json() == j
    assert _get(client, projeto63, "similitude", n_formas=10, indice="pmi").json()["indice"] == "pmi"
    nos = _get(client, projeto63, "similitude/nos.csv", n_formas=20).content.decode("utf-8-sig").splitlines()
    assert nos[0].startswith("forma;freq;segmentos;comunidade") and len(nos) == 21
    ar = _get(client, projeto63, "similitude/arestas.csv", n_formas=20).content.decode("utf-8-sig").splitlines()
    assert ar[0].startswith("forma_a;forma_b;peso_coocorrencia") and len(ar) == r["n_arestas"] + 1
    assert client.get(f"/api/projetos/{projeto63}/analises/similitude", params={"indice": "dice"}).status_code == 422


def test_etapas_gravam_instantaneos_e_reagem_aos_parametros(client, projeto63):
    rei, sim = _snapshots(projeto63, "reinert"), _snapshots(projeto63, "similitude")
    assert len(rei) == 1 and len(sim) == 1
    res = json.loads(rei[0].resultado_json)
    assert json.loads(rei[0].parametros_json)["classes"] == 10 and res["k"] >= 2
    assert json.loads(sim[0].parametros_json)["indice"] == "coocorrencia"
    et = _executar(client, projeto63)
    assert et["reinert"]["pulado"] == 1 and et["similitude"]["pulado"] == 1
    p = client.get(f"/api/projetos/{projeto63}/parametros").json()
    p["similitude"]["indice"] = "jaccard"
    assert client.put(f"/api/projetos/{projeto63}/parametros", json=p).status_code == 200
    et = _executar(client, projeto63)
    assert et["similitude"]["pulado"] == 0 and et["reinert"]["pulado"] == 1
    assert json.loads(_snapshots(projeto63, "similitude")[0].parametros_json)["indice"] == "jaccard"
    assert len(_snapshots(projeto63, "similitude")) == 1


def test_exportacao_corpus_iramuteq(client, projeto63):
    r = client.get(f"/api/projetos/{projeto63}/exportar/corpus-iramuteq.txt")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    linhas = r.content.decode("utf-8").splitlines()
    cab = [l for l in linhas if l.startswith("****")]
    assert len(cab) == 10 and all(" *doc_" in l and " *grupo_" in l and " *ano_" in l for l in cab)
    assert any("*grupo_academica" in l and "*ano_2025" in l for l in cab)
    assert not any("*" in l for l in linhas if not l.startswith("****"))


def test_exportacao_corpus_iramuteq_doc_unico(client, projeto63, ids63):
    """12.2: *doc_ é único por texto. Antes, um documento sem id do estudo recebia o número do banco (ex.: 052), que
    podia coincidir com o id do estudo de outro documento, e o IRaMuTeQ juntaria os dois na mesma modalidade."""
    sem_id = ids63["001_2025_Alfa_Agentes.md"]
    assert client.patch(f"/api/projetos/{projeto63}/documentos/{sem_id}", json={"id_estudo": None}).status_code == 200
    # outro documento com id do estudo igual ao número do banco do primeiro, e um id do estudo repetido
    assert client.patch(f"/api/projetos/{projeto63}/documentos/{ids63['002_2025_Beta_Agentes.md']}",
                        json={"id_estudo": f"{sem_id:03d}"}).status_code == 200
    assert client.patch(f"/api/projetos/{projeto63}/documentos/{ids63['004_2026_Delta_Economia.md']}",
                        json={"id_estudo": "003"}).status_code == 200
    linhas = client.get(f"/api/projetos/{projeto63}/exportar/corpus-iramuteq.txt").content.decode("utf-8").splitlines()
    docs = [l.split()[1] for l in linhas if l.startswith("****")]
    assert len(docs) == 10 and len(set(docs)) == 10, docs
    assert f"*doc_id{sem_id:03d}" in docs and f"*doc_{sem_id:03d}" in docs
    assert "*doc_003" in docs and "*doc_003_2" in docs
