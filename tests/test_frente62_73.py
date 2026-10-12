"""6.2 Especificidades (modelo hipergeométrico de Lafon) e 7.3 AFC (análise de correspondência).
Funções puras contra cálculo exato independente (math.comb), scipy e o exemplo de Greenacre; API, CSV e etapas com o
corpus sintético da 6.3/6.4 (fixtures importadas de test_frente63_64). Sem Docling."""
import json
import math
import random
from fractions import Fraction

import numpy as np
import pytest
from scipy.stats import chi2_contingency, hypergeom

from app.services.analises import afc, especificidades as esp
from tests.test_frente63_64 import _executar, _get, _snapshots, corpus63, ids63, projeto63  # noqa: F401

SEM_VAZIAS = frozenset()


# ---------- apoio: hipergeométrica exata com inteiros ----------

def _cauda_exata(f, F, t, T, superior):
    """P(X >= f) ou P(X <= f) exata (Fraction), X ~ Hipergeométrica(T, F, t)."""
    lo, hi = max(0, t - (T - F)), min(F, t)
    xs = range(max(f, lo), hi + 1) if superior else range(lo, min(f, hi) + 1)
    return Fraction(sum(math.comb(F, x) * math.comb(T - F, t - x) for x in xs), math.comb(T, t))


def _score_exato(f, F, t, T):
    sup = f >= Fraction(F * t, T)
    p = _cauda_exata(f, F, t, T, sup)
    lg = math.log10(p.numerator) - math.log10(p.denominator)  # log10 de inteiros grandes, sem estouro
    return -lg if sup else lg


# ---------- 6.2 estatística ----------

def test_score_confere_com_calculo_exato_em_grade_pequena():
    T = 40
    for F in (1, 3, 7, 15):
        for t in (5, 12, 25):
            lo, hi = max(0, t - (T - F)), min(F, t)
            for f in range(lo, hi + 1):
                assert esp.score(f, F, t, T) == pytest.approx(_score_exato(f, F, t, T), abs=1e-9), (f, F, t)


def test_score_extremo_usa_escala_log_e_confere_com_inteiros():
    # P(X >= 200) = 1 / C(2000, 200) ~ 1e-280: abaixo de 1e-250, passa pelo logsf
    T, F, t = 2000, 200, 200
    assert hypergeom.sf(199, T, F, t) < esp.P_MINIMO_DIRETO
    assert esp.score(200, F, t, T) == pytest.approx(_score_exato(200, F, t, T), rel=1e-9)
    assert esp.score(0, F, 1500, T) == pytest.approx(_score_exato(0, F, 1500, T), rel=1e-9)  # cauda inferior minúscula
    assert esp.score(200, F, t, T) > esp.TETO
    s = esp.scores([200, 0, 30], [F, F, F], [t, 1500, 300], T)
    assert np.isfinite(s).all() and s[0] > 250 and s[1] < -50


def test_score_confere_com_scipy_e_probabilidades_somam_1():
    rnd = random.Random(62)
    for _ in range(300):
        T = rnd.randint(500, 50000)
        F = rnd.randint(1, 300)
        t = rnd.randint(1, T - 1)
        lo, hi = max(0, t - (T - F)), min(F, t)
        f = rnd.randint(lo, hi)
        esperada = F * t / T
        s = esp.score(f, F, t, T)
        if f >= esperada:
            p = hypergeom.sf(f - 1, T, F, t)
            assert s >= 0 and 10 ** (-s) == pytest.approx(p, rel=1e-7)
            assert p + hypergeom.cdf(f - 1, T, F, t) == pytest.approx(1.0, abs=1e-12)  # caudas complementares
        else:
            p = hypergeom.cdf(f, T, F, t)
            assert s <= 0 and 10 ** s == pytest.approx(p, rel=1e-7)
            assert p + hypergeom.sf(f, T, F, t) == pytest.approx(1.0, abs=1e-12)
    # a pmf exata soma 1 (Vandermonde)
    assert sum(_cauda_exata(x, 7, 12, 40, True) - _cauda_exata(x + 1, 7, 12, 40, True) for x in range(0, 8)) == 1


def test_simetria_de_sinal():
    T = 1000
    for f, F, t in [(10, 20, 100), (0, 30, 200), (25, 40, 300), (2, 50, 400)]:
        # termo × complemento na mesma parte: P(X >= f) = P(t − X <= t − f)
        assert esp.score(f, F, t, T) == pytest.approx(-esp.score(t - f, T - F, t, T), abs=1e-9)
        # 2 partes: o que sobra numa sobra para a outra, com sinal oposto
        a, b = esp.score(f, F, t, T), esp.score(F - f, F, T - t, T)
        assert a * b < 0 or a == b == 0


def test_entre_moda_e_media_o_score_e_banal():
    """Justifica no docstring: TXM decide o lado pela moda; aqui pela média. Onde diferem, |score| < 0,5."""
    for T in (50, 200, 1000):
        for F in range(1, 40, 3):
            for t in range(1, T, max(1, T // 25)):
                moda = math.floor((t + 1) * (F + 1) / (T + 2))
                media = F * t / T
                for f in {moda, math.floor(media), math.ceil(media)}:
                    if min(moda, media) <= f <= max(moda, media) and max(0, t - (T - F)) <= f <= min(F, t):
                        assert abs(esp.score(f, F, t, T)) < 0.5, (f, F, t, T)


def test_teto_e_zero_sem_sinal():
    assert esp.com_teto(120.0) == (esp.TETO, True) and esp.com_teto(-75.0) == (-esp.TETO, True)
    assert esp.com_teto(3.2) == (3.2, False)
    s = esp.scores([5], [10], [500], 1000)[0]  # f = esperada: P(X >= 5) > 0,5
    assert 0 <= s < 0.5 and str(esp.scores([0], [0], [10], 100)[0]) == "0.0"


def test_tabela_de_especificidades_listas_limiar_min_freq_e_matriz():
    termos = ["a", "b", "c", "raro"]
    cont = np.array([[60, 5, 5], [5, 60, 5], [20, 20, 20], [3, 0, 0]])
    tam = np.array([1000, 1000, 1000])
    partes = [{"chave": k, "rotulo": k, "documentos": 1, "tokens": 1000} for k in ("p1", "p2", "p3")]
    r = esp.tabela_de_especificidades(termos, cont, tam, partes, min_freq=5, limiar=2, limite=10)
    assert r["T"] == 3000 and r["termos_testados"] == 3  # "raro" (F = 3) fica fora
    p1 = r["partes"][0]
    assert [i["termo"] for i in p1["positivas"]] == ["a"] and [i["termo"] for i in p1["negativas"]] == ["b"]
    a = p1["positivas"][0]
    assert a["f"] == 60 and a["F"] == 70 and a["esperada"] == pytest.approx(70 / 3, abs=1e-3)
    assert a["score"] == pytest.approx(esp.score(60, 70, 1000, 3000), abs=1e-3)
    assert all(not i["termo"] == "c" for p in r["partes"] for i in p["positivas"] + p["negativas"])  # c é banal
    assert r["matriz"]["termos"] == ["a", "b"] and len(r["matriz"]["scores"]) == 3
    assert r["matriz"]["scores"][0][0] == pytest.approx(a["score"], abs=1e-3)
    # o score de p1 + p2 + p3 tem sinais coerentes com a sobre/sub-representação
    assert r["matriz"]["scores"][1][0] < 0 and r["matriz"]["scores"][1][1] > 0


# ---------- 7.3 AFC: exemplo de Greenacre e propriedades ----------

# Greenacre (2017, cap. 3–4), dados "smoke": 5 categorias de funcionários × 4 níveis de fumo
SMOKE = [[4, 2, 3, 2], [4, 3, 7, 4], [25, 10, 12, 4], [18, 24, 33, 13], [10, 6, 7, 2]]
SMOKE_F = [[0.066, 0.194], [0.259, 0.243], [0.381, 0.011], [0.233, 0.058], [0.201, 0.079]]  # |coord. principais|
SMOKE_G = [[0.393, 0.030], [0.099, 0.141], [0.196, 0.007], [0.294, 0.198]]


def test_afc_reproduz_o_exemplo_de_greenacre():
    r = afc.analise_de_correspondencia(SMOKE)
    assert r["k"] == 3
    assert r["autovalores"] == pytest.approx([0.07476, 0.01002, 0.00041], abs=5e-6)
    assert r["inercia_total"] == pytest.approx(0.08519, abs=5e-6)
    assert r["chi2"] == pytest.approx(chi2_contingency(SMOKE, correction=False)[0], rel=1e-10)
    assert np.abs(r["F"][:, :2]) == pytest.approx(np.array(SMOKE_F), abs=6e-4)
    assert np.abs(r["G"][:, :2]) == pytest.approx(np.array(SMOKE_G), abs=6e-4)
    pct = r["autovalores"] / r["inercia_total"] * 100
    assert pct == pytest.approx([87.76, 11.76, 0.48], abs=0.01)
    # convenção de sinal: a coluna de maior |coordenada| é positiva ("none" no eixo 1, "heavy" no eixo 2)
    assert r["G"][0, 0] > 0 and r["G"][3, 1] > 0


def _tabela_aleatoria(i, j, semente):
    rnd = np.random.default_rng(semente)
    return rnd.integers(0, 30, size=(i, j)) + (rnd.random((i, j)) < 0.3) * rnd.integers(0, 80, size=(i, j)) + 1


@pytest.mark.parametrize("forma", [(12, 5), (6, 9), (30, 3)])
def test_afc_propriedades(forma):
    N = _tabela_aleatoria(*forma, semente=sum(forma))
    r = afc.analise_de_correspondencia(N)
    I, J = forma
    k = min(I - 1, J - 1, afc.EIXOS_MAX)
    assert r["k"] == k
    assert r["autovalores"].sum() == pytest.approx(r["inercia_total"], rel=1e-10)
    assert r["inercia_total"] == pytest.approx(chi2_contingency(N, correction=False)[0] / N.sum(), rel=1e-10)
    # autovalores por um caminho independente: autovalores de SᵀS
    P = N / N.sum(); rr, cc = P.sum(1), P.sum(0)
    S = (P - np.outer(rr, cc)) / np.sqrt(np.outer(rr, cc))
    ev = np.sort(np.linalg.eigvalsh(S.T @ S))[::-1][:k]
    assert r["autovalores"][:k] == pytest.approx(ev, abs=1e-12)
    assert r["ctr_linhas"].sum(axis=0) == pytest.approx([100.0] * k)
    assert r["ctr_colunas"].sum(axis=0) == pytest.approx([100.0] * k)
    assert (r["cos2_linhas"] <= 1 + 1e-12).all() and (r["cos2_linhas"].sum(axis=1) <= 1 + 1e-9).all()
    assert (r["cos2_colunas"].sum(axis=1) <= 1 + 1e-9).all()
    lam = r["autovalores"][:k]
    # fórmulas de transição (baricentros)
    assert r["F"] == pytest.approx((P / rr[:, None]) @ r["G"] / np.sqrt(lam), abs=1e-10)
    assert r["G"] == pytest.approx((P / cc[None, :]).T @ r["F"] / np.sqrt(lam), abs=1e-10)
    # inércia do eixo = soma ponderada dos quadrados das coordenadas
    assert (rr[:, None] * r["F"] ** 2).sum(axis=0) == pytest.approx(lam, rel=1e-9)
    if k == min(I, J) - 1:  # todos os eixos: cos² somam 1 e d² = soma dos quadrados
        assert r["cos2_linhas"].sum(axis=1) == pytest.approx(np.ones(I), abs=1e-9)
        assert r["d2_linhas"] == pytest.approx((r["F"] ** 2).sum(axis=1), rel=1e-9)
    # transposta: linhas e colunas trocam de papel (mesmos autovalores, coordenadas iguais a menos do sinal)
    t = afc.analise_de_correspondencia(N.T)
    assert t["autovalores"] == pytest.approx(r["autovalores"], abs=1e-12)
    assert np.abs(t["G"]) == pytest.approx(np.abs(r["F"]), abs=1e-9)


def test_afc_duas_colunas_tem_um_eixo_e_erros():
    r = afc.analise_de_correspondencia([[10, 2], [3, 9], [5, 5]])
    assert r["k"] == 1 and r["ctr_linhas"][:, 0].sum() == pytest.approx(100)
    assert r["cos2_linhas"][:, 0] == pytest.approx([1, 1, 1])  # uma dimensão: tudo no eixo
    with pytest.raises(ValueError):
        afc.analise_de_correspondencia([[1, 2, 3]])
    with pytest.raises(ValueError):
        afc.analise_de_correspondencia([[1, 0], [2, 0]])
    perfis_iguais = afc.analise_de_correspondencia([[2, 4], [1, 2], [3, 6]])
    assert perfis_iguais["k"] == 0 and perfis_iguais["inercia_total"] == pytest.approx(0, abs=1e-15)


# ---------- API, CSV e etapas (corpus sintético da 6.3) ----------

def test_api_especificidades_por_grupo_confere_com_o_calculo_puro(client, projeto63):
    r = _get(client, projeto63, "especificidades", particao="grupo").json()
    assert r["ferramenta_equivalente"] == esp.FERRAMENTA_EQUIVALENTE and r["nao_equivalente"] == esp.NAO_EQUIVALENTE
    partes = {p["chave"]: p for p in r["partes"]}
    assert set(partes) == {"academica", "cinzenta"}
    T = r["T"]
    assert T == sum(p["tokens"] for p in r["partes"])
    ac, ci = partes["academica"], partes["cinzenta"]
    termos_ac = [i["termo"] for i in ac["positivas"]]
    assert {"benchmark", "evaluation"} & set(termos_ac)  # tópico "agentes" só na acadêmica
    assert {"risk", "regulation", "safety"} & {i["termo"] for i in ci["positivas"]}
    for item in ac["positivas"] + ac["negativas"]:
        assert item["score"] == pytest.approx(max(-50, min(50, esp.score(item["f"], item["F"], ac["tokens"], T))), abs=1e-3)
        assert abs(item["score"]) >= 2
    # com 2 partes os específicos de uma são os negativos da outra
    assert set(termos_ac) == {i["termo"] for i in ci["negativas"]} or len(termos_ac) >= r["parametros"]["limite"]
    freq = _get(client, projeto63, "frequencias", escopo="grupo", valor="academica", limite=5000).json()
    por_termo = {i["termo"]: i["freq"] for i in freq["itens"]}
    assert all(por_termo[i["termo"]] == i["f"] for i in ac["positivas"])
    # mesma direção da keyness (6.1)
    k = _get(client, projeto63, "keyness", particao="grupo", a="academica").json()
    assert termos_ac[0] in {i["termo"] for i in k["positivas"]}


def test_api_especificidades_termo_documento_e_erros(client, projeto63, ids63):
    r = _get(client, projeto63, "especificidades/termo", termo="Benchmark", particao="documento").json()
    assert r["termo"] == "benchmark" and len(r["partes"]) == 10
    assert sum(p["f"] for p in r["partes"]) == r["F"]
    por_id = {p["chave"]: p for p in r["partes"]}
    assert por_id[str(ids63["001_2025_Alfa_Agentes.md"])]["score"] > 2
    assert por_id[str(ids63["007_2026_Eta_Governanca.md"])]["score"] < 0
    assert all(p["banal"] == (abs(p["score"]) < 2) for p in r["partes"])
    lista = _get(client, projeto63, "especificidades", particao="documento", termos="benchmark,risk").json()
    assert lista["matriz"]["termos"] == ["benchmark", "risk"]
    j = lista["matriz"]["partes"].index(str(ids63["001_2025_Alfa_Agentes.md"]))
    assert lista["matriz"]["scores"][j][0] == pytest.approx(por_id[str(ids63["001_2025_Alfa_Agentes.md"])]["score"], abs=1e-3)
    base = f"/api/projetos/{projeto63}/analises/especificidades"
    assert client.get(base + "/termo", params={"termo": "inexistentex"}).status_code == 404
    assert client.get(base, params={"particao": "qp"}).status_code == 422
    assert client.get(base, params={"limiar": 0}).status_code == 422
    assert _get(client, projeto63, "especificidades", particao="ano", por="termo").json()["por"] == "termo"
    csv = _get(client, projeto63, "especificidades.csv", particao="grupo").content.decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("parte;sinal;posicao;termo;f_parte;F_corpus;esperada;score")
    assert ";benchmark;" in csv or ";evaluation;" in csv


def test_api_afc_por_documento_grupo_e_selecao(client, projeto63, ids63):
    r = _get(client, projeto63, "afc", particao="documento", n_termos=30).json()
    assert r["ferramenta_equivalente"] == afc.FERRAMENTA_EQUIVALENTE and r["nao_equivalente"] == "PCA"
    assert r["n_linhas"] == 30 and r["n_colunas"] == 9 and r["k"] == 5
    assert [e["motivo"] for e in r["partes_excluidas"]] == ["nenhuma ocorrência dos termos escolhidos"]  # 010 só vazias
    assert sum(e["pct"] for e in r["eixos"]) == pytest.approx(100, abs=1e-3)
    for e in range(r["k"]):
        assert sum(t["ctr"][e] for t in r["linhas"]) == pytest.approx(100, abs=0.01)
        assert sum(c["ctr"][e] for c in r["colunas"]) == pytest.approx(100, abs=0.01)
    # documentos do mesmo tópico ficam do mesmo lado nos 2 primeiros eixos (perto entre si)
    pos = {c["chave"]: np.array(c["coord"][:2]) for c in r["colunas"]}
    a1, a2, g1 = (pos[str(ids63[x])] for x in ("001_2025_Alfa_Agentes.md", "002_2025_Beta_Agentes.md", "007_2026_Eta_Governanca.md"))
    assert np.linalg.norm(a1 - a2) < np.linalg.norm(a1 - g1)
    g = _get(client, projeto63, "afc", particao="grupo").json()
    assert g["k"] == 1 and "único eixo" in g["mensagem"]
    s = _get(client, projeto63, "afc", particao="documento", selecao="especificidade", n_termos=10).json()
    assert s["n_linhas"] == 10 and s["parametros"]["selecao"] == "especificidade"
    base = f"/api/projetos/{projeto63}/analises/afc"
    assert client.get(base, params={"n_termos": 501}).status_code == 422
    assert client.get(base, params={"eixos": 6}).status_code == 422
    csv = _get(client, projeto63, "afc.csv", particao="documento", n_termos=20).content.decode("utf-8-sig").splitlines()
    assert csv[0].startswith("tipo;nome;freq;massa;inercia_pct;qualidade;coord_1;ctr_1;cos2_1")
    assert len(csv) == 1 + 9 + 20


def test_etapas_gravam_instantaneos_substituem_e_invalidam(client, projeto63):
    e = _snapshots(projeto63, "especificidades")
    a = _snapshots(projeto63, "afc")
    assert len(e) == 1 and len(a) == 1
    assert json.loads(e[0].parametros_json)["particao"] == "grupo"  # 2 grupos
    assert json.loads(a[0].parametros_json)["particao"] == "documento"  # 2 grupos e 2 anos (< 3)
    assert json.loads(a[0].resultado_json)["n_colunas"] == 9
    assert e[0].ferramenta_equivalente == esp.FERRAMENTA_EQUIVALENTE
    et = _executar(client, projeto63)
    assert et["especificidades"]["pulado"] == 1 and et["afc"]["pulado"] == 1
    docs = {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{projeto63}/documentos").json()}
    assert client.patch(f"/api/projetos/{projeto63}/documentos/{docs['007_2026_Eta_Governanca.md']}", json={"grupo": "terceiro"}).status_code == 200
    et = _executar(client, projeto63)
    assert et["especificidades"]["pulado"] == 0 and et["afc"]["pulado"] == 0
    novas = _snapshots(projeto63, "afc")
    assert len(novas) == 1 and novas[0].id != a[0].id
    assert json.loads(novas[0].parametros_json)["particao"] == "grupo"  # agora 3 grupos
    assert len(_snapshots(projeto63, "especificidades")) == 1
