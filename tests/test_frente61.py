"""6.1 - Keyness entre grupos (G² de 2 células, Log Ratio, %DIFF): exemplos à mão, força bruta, scipy, etapa e API."""
import json
import math
import random
from collections import Counter

import pytest

from app import database
from app.models import Analise
from app.services import vocabulario
from app.services.analises import keyness
from app.services.palavras_vazias import token_vazio
from tests.test_frente5 import _get, _tokens, corpus5, ids, projeto5  # noqa: F401  (fixtures reaproveitadas)
from tests.test_frente54 import VAZIAS, _doc_tokens

# ---------- exemplo calculado à mão ----------
# a=30, b=10, c=1000, d=2000  ->  E1 = 1000*40/3000 = 13,3333; E2 = 2000*40/3000 = 26,6667
# G² = 2*(30*ln(30/13,3333) + 10*ln(10/26,6667)) = 2*(30*0,810930 + 10*(-0,980829)) = 2*14,51962 = 29,03923
A, B, C, D = 30, 10, 1000, 2000
G2_A_MAO = 29.03923
# Log Ratio = log2((30/1000)/(10/2000)) = log2(6) = 2,584963 ; %DIFF = (0,03-0,005)/0,005*100 = 500


def test_g2_de_2_celulas_calculado_a_mao():
    assert keyness.log_likelihood(A, B, C, D) == pytest.approx(G2_A_MAO, abs=1e-4)
    # p = erfc(sqrt(29,03923/2)) ~ 7,1e-8
    assert keyness.valor_p(G2_A_MAO) == pytest.approx(7.1e-8, rel=0.05)


def test_sinal_positivo_em_a_e_negativo_em_b_e_zero_se_iguais():
    assert keyness.log_likelihood(A, B, C, D) > 0
    assert keyness.log_likelihood(B, A, D, C) == pytest.approx(-G2_A_MAO, abs=1e-4)  # trocar os lados inverte o sinal
    g2_neg = keyness.log_likelihood(10, 30, 1000, 2000)  # 1% em A contra 1,5% em B
    assert g2_neg < 0
    assert abs(g2_neg) == pytest.approx(keyness.log_likelihood(30, 10, 2000, 1000))  # simétrico ao trocar os lados
    assert keyness.log_likelihood(10, 20, 1000, 2000) == 0.0  # mesma frequência relativa


def test_zero_ln_zero_e_p_de_g2_nulo():
    # b = 0: G² = 2*a*ln(a/E1), com E1 = c*a/(c+d)
    a, c, d = 12, 1000, 2000
    assert keyness.log_likelihood(a, 0, c, d) == pytest.approx(2 * a * math.log((c + d) / c))
    assert keyness.valor_p(0.0) == 1.0


def test_2_celulas_difere_do_g2_de_4_celulas():
    """O G² de 4 células soma também as células de complemento; aqui os valores são distintos e o usado é o de 2."""
    a, b, c, d = 300, 100, 1000, 2000
    e = [c * (a + b) / (c + d), d * (a + b) / (c + d), c * (c + d - a - b) / (c + d), d * (c + d - a - b) / (c + d)]
    quatro = 2 * (a * math.log(a / e[0]) + b * math.log(b / e[1]) + (c - a) * math.log((c - a) / e[2])
                  + (d - b) * math.log((d - b) / e[3]))
    dois = keyness.log_likelihood(a, b, c, d)
    assert dois == pytest.approx(2 * (a * math.log(a / e[0]) + b * math.log(b / e[1])))
    assert abs(dois - quatro) > 1.0


def test_p_confere_com_o_scipy():
    stats = pytest.importorskip("scipy.stats")
    for g2 in (0.5, 3.84, G2_A_MAO, 120.0):
        assert keyness.valor_p(g2) == pytest.approx(stats.chi2.sf(g2, 1), rel=1e-9)
    # termo muito raro: o G² de 2 células aproxima o de 4 do scipy só em parte; confere o valor de 4 células à parte
    g2_4, _p, _, _ = stats.chi2_contingency([[A, C - A], [B, D - B]], correction=False, lambda_="log-likelihood")
    assert g2_4 != pytest.approx(keyness.log_likelihood(A, B, C, D), abs=1e-3)


def test_log_ratio_e_tratamento_de_zero():
    assert keyness.log_ratio(A, B, C, D) == pytest.approx(math.log2(6))
    # b = 0 -> 0,5 no lugar do zero: (5/1000)/(0,5/2000) = 20
    assert keyness.log_ratio(5, 0, C, D) == pytest.approx(math.log2(20))
    # a = 0 -> (0,5/1000)/(5/2000) = 0,2
    assert keyness.log_ratio(0, 5, C, D) == pytest.approx(math.log2(0.2))
    assert keyness.log_ratio(10, 20, 1000, 2000) == pytest.approx(0.0)


def test_pct_diff_e_nulo_quando_b_e_zero():
    assert keyness.pct_diff(A, B, C, D) == pytest.approx(500.0)
    assert keyness.pct_diff(5, 0, C, D) is None
    assert keyness.pct_diff(0, 5, C, D) == pytest.approx(-100.0)
    m = keyness.medidas(5, 0, C, D)
    assert m["pct_diff"] is None and m["so_em_a"] is True and m["so_em_b"] is False
    assert keyness.medidas(0, 5, C, D)["so_em_b"] is True


# ---------- corpus sintético com grupos, em memória ----------

PALAVRAS = ["agent", "agents", "task", "tasks", "model", "the", "of", "and", "is", "x", "human", "data", "zeta",
            "beta", "tool", "report", "policy", "survey", "firm", "gamma"]
LEMAS = {"agents": "agent", "tasks": "task"}


def _montar(docs: dict[int, str]):
    """docs: {id: texto} -> (vocabulário, tokens por id). Todo token do texto entra (incluir = 1)."""
    tokens = {}
    for i, texto in docs.items():
        t = _doc_tokens([(texto, 1)])
        t["lema"] = [LEMAS.get(n, n) for n in t["norm"]]
        tokens[i] = t
    voc = vocabulario.construir({i: {"arquivo": f"{i}.md", **vocabulario.contar_documento(t)} for i, t in tokens.items()}, {})
    return voc, tokens


@pytest.fixture()
def sintetico():
    rnd = random.Random(61)
    pesos = {"alfa": [5, 5, 1], "beta": [1, 1, 5]}  # grupo alfa favorece o início da lista; beta, o fim
    docs, metas = {}, []
    plano = [("alfa", 2023), ("alfa", 2023), ("alfa", 2024), ("beta", 2024), ("beta", 2025), (None, 2025), (None, None)]
    for i, (grupo, ano) in enumerate(plano, start=1):
        p = pesos.get(grupo, [1, 1, 1])
        texto = " ".join(rnd.choices(PALAVRAS, weights=[p[0]] * 7 + [p[1]] * 7 + [p[2]] * 6)[0] for _ in range(rnd.randint(80, 160)))
        docs[i] = texto
        metas.append({"id": i, "grupo": grupo, "ano": ano})
    voc, tokens = _montar(docs)
    return voc, tokens, metas


def _bruta(tokens, ids_lado, filtro, por="lema", filtrar=True):
    """Recontagem independente a partir dos arrays de tokens: (freq por termo, docs por termo, tokens do lado)."""
    freq, df, total = Counter(), Counter(), 0
    for i in ids_lado:
        t = tokens[i]
        local = Counter()
        for n, l, inc in zip(t["norm"], t["lema"], t["incluir"]):
            if inc and len(n) >= 2:
                total += 1
                if filtrar and token_vazio(n, l, filtro):
                    continue
                local[l if por == "lema" else n] += 1
        freq.update(local)
        df.update(local.keys())
    return freq, df, total


def _calc(voc, metas, **kw):
    base = dict(filtro=VAZIAS, particao="grupo", a="alfa", b="resto", min_freq=1, min_docs_a=1, min_docs_b=1, p=1.0,
                limite=10**6)
    base.update(kw)
    return keyness.calcular(voc, metas, base.pop("filtro"), **base)


def _todos(r):
    return {i["termo"]: i for i in r["positivas"] + r["negativas"]}


@pytest.mark.parametrize("por", ["lema", "forma"])
def test_abcd_igual_a_recontagem_por_forca_bruta(sintetico, por):
    voc, tokens, metas = sintetico
    r = _calc(voc, metas, por=por)
    ids_a = [m["id"] for m in metas if m["grupo"] == "alfa"]
    ids_b = [m["id"] for m in metas if m["grupo"] != "alfa"]  # "resto": beta + sem grupo
    fa, dfa, c = _bruta(tokens, ids_a, VAZIAS, por)
    fb, dfb, d = _bruta(tokens, ids_b, VAZIAS, por)
    assert (r["lado_a"]["tokens"], r["lado_b"]["tokens"]) == (c, d)
    assert (r["lado_a"]["documentos"], r["lado_b"]["documentos"]) == (len(ids_a), len(ids_b))
    todos = _todos(r)
    assert set(todos) == {t for t in set(fa) | set(fb) if keyness.log_likelihood(fa[t], fb[t], c, d) != 0}
    for t, i in todos.items():
        assert (i["a"], i["b"], i["docs_a"], i["docs_b"]) == (fa[t], fb[t], dfa[t], dfb[t])
        e1, e2 = c * (fa[t] + fb[t]) / (c + d), d * (fa[t] + fb[t]) / (c + d)
        g2 = 2 * ((fa[t] * math.log(fa[t] / e1) if fa[t] else 0) + (fb[t] * math.log(fb[t] / e2) if fb[t] else 0))
        assert abs(i["g2"]) == pytest.approx(g2)
        assert (i["g2"] > 0) == (fa[t] / c > fb[t] / d)
        assert i["por_10k_a"] == pytest.approx(fa[t] / c * 1e4, abs=0.006)
    assert all(i["g2"] > 0 for i in r["positivas"]) and all(i["g2"] < 0 for i in r["negativas"])
    gs = [abs(i["g2"]) for i in r["positivas"]]
    assert gs == sorted(gs, reverse=True)


def test_palavras_vazias_so_saem_da_lista_e_nao_do_tamanho(sintetico):
    voc, _tokens_, metas = sintetico
    filtrado, mantido = _calc(voc, metas), _calc(voc, metas, filtrar=False)
    assert not ({"the", "of", "and", "is"} & set(_todos(filtrado)))
    assert {"the", "of", "and", "is"} & set(_todos(mantido))
    assert filtrado["lado_a"]["tokens"] == mantido["lado_a"]["tokens"]  # c e d contam todos os tokens


def test_ordenar_por_log_ratio(sintetico):
    voc, _t, metas = sintetico
    r = _calc(voc, metas, ordem="logratio")
    lr = [abs(i["log_ratio"]) for i in r["positivas"]]
    assert lr == sorted(lr, reverse=True) and r["parametros"]["ordem"] == "logratio"
    with pytest.raises(ValueError):
        _calc(voc, metas, ordem="xyz")


def test_dispersao_exclui_palavra_chave_de_um_documento_so():
    voc, _t = _montar({
        1: "solo " * 30 + "comum " * 10 + "fundo " * 20,
        2: "comum " * 10 + "fundo " * 20,
        3: "fundo " * 30 + "comum " * 2,
        4: "fundo " * 30 + "comum " * 2,
    })
    metas = [{"id": 1, "grupo": "a", "ano": 2020}, {"id": 2, "grupo": "a", "ano": 2020},
             {"id": 3, "grupo": "b", "ano": 2021}, {"id": 4, "grupo": "b", "ano": 2021}]
    kw = dict(a="a", b="b", min_freq=5, p=0.01, filtro=frozenset())
    livre = keyness.calcular(voc, metas, kw.pop("filtro"), particao="grupo", min_docs_a=1, **kw)
    assert {"solo", "comum"} <= {i["termo"] for i in livre["positivas"]}
    estrito = keyness.calcular(voc, metas, frozenset(), particao="grupo", min_docs_a=2, **kw)
    termos = {i["termo"] for i in estrito["positivas"]}
    assert "solo" not in termos and "comum" in termos  # "solo" só ocorre no documento 1
    assert estrito["parametros"]["min_docs_a_efetivo"] == 2
    # o mínimo é limitado ao nº de documentos do lado
    um = keyness.calcular(voc, metas[:1] + metas[2:], frozenset(), particao="grupo", min_docs_a=5, **kw)
    assert um["parametros"]["min_docs_a_efetivo"] == 1 and "solo" in {i["termo"] for i in um["positivas"]}


def test_bonferroni_aperta_o_limiar(sintetico):
    voc, _t, metas = sintetico
    plano = _calc(voc, metas, p=0.05, min_freq=5)
    bonf = _calc(voc, metas, p=0.05, min_freq=5, bonferroni=True)
    m = plano["termos_testados"]
    assert m > 1 and bonf["limiar_p"] == pytest.approx(0.05 / m) and plano["limiar_p"] == 0.05
    assert {i["termo"] for i in bonf["positivas"] + bonf["negativas"]} <= {i["termo"] for i in plano["positivas"] + plano["negativas"]}
    assert all(i["p"] < 0.05 / m for i in bonf["positivas"] + bonf["negativas"])
    assert all(i["p_bonferroni"] == pytest.approx(min(1.0, i["p"] * m)) for i in plano["positivas"])
    assert len(bonf["positivas"]) < len(plano["positivas"])


def test_min_freq_e_limite(sintetico):
    voc, _t, metas = sintetico
    r = _calc(voc, metas, min_freq=40, limite=3)
    assert all(i["a"] + i["b"] >= 40 for i in r["positivas"] + r["negativas"])
    assert len(r["positivas"]) <= 3 and r["total_positivas"] >= len(r["positivas"])


def test_particao_por_ano(sintetico):
    voc, tokens, metas = sintetico
    r = _calc(voc, metas, particao="ano", a="2023", b="resto")
    ids_a = [m["id"] for m in metas if m["ano"] == 2023]
    ids_b = [m["id"] for m in metas if m["ano"] != 2023]  # inclui o documento sem ano
    fa, _, c = _bruta(tokens, ids_a, VAZIAS)
    fb, _, d = _bruta(tokens, ids_b, VAZIAS)
    assert (r["lado_a"]["tokens"], r["lado_b"]["tokens"]) == (c, d)
    t = next(iter(_todos(r)))
    assert (_todos(r)[t]["a"], _todos(r)[t]["b"]) == (fa[t], fb[t])
    varios = _calc(voc, metas, particao="ano", a="2023,2024", b="2025")
    assert varios["lado_a"]["documentos"] == 4 and varios["lado_b"]["documentos"] == 2  # 2025: docs 5 e 6
    sem = _calc(voc, metas, particao="ano", a="s/ano", b="resto")
    assert sem["lado_a"]["documentos"] == 1


def test_b_resto_contra_b_especifico(sintetico):
    voc, tokens, metas = sintetico
    resto = _calc(voc, metas, a="alfa", b="resto")
    beta = _calc(voc, metas, a="alfa", b="beta")
    assert resto["lado_b"]["documentos"] == 4 and beta["lado_b"]["documentos"] == 2  # resto inclui os sem grupo
    ids_beta = [m["id"] for m in metas if m["grupo"] == "beta"]
    _, _, d = _bruta(tokens, ids_beta, VAZIAS)
    assert beta["lado_b"]["tokens"] == d and beta["lado_b"]["valor"] == "beta"
    assert beta["lado_b"]["tokens"] != resto["lado_b"]["tokens"]
    sem_grupo = _calc(voc, metas, a="sem grupo", b="alfa")
    assert sem_grupo["lado_a"]["documentos"] == 2


def test_lados_invalidos(sintetico):
    voc, _t, metas = sintetico
    with pytest.raises(ValueError, match="sobrepõem"):
        _calc(voc, metas, a="alfa", b="alfa")
    with pytest.raises(ValueError, match="lado A"):
        _calc(voc, metas, a="nao-existe")
    with pytest.raises(ValueError, match="lado B"):
        _calc(voc, metas, a="alfa", b="nao-existe")
    with pytest.raises(ValueError, match="Partição"):
        _calc(voc, metas, particao="documento")
    with pytest.raises(ValueError, match="lado A"):
        _calc(voc, metas, a="")


def test_metadados_da_resposta(sintetico):
    voc, _t, metas = sintetico
    r = _calc(voc, metas)
    assert r["ferramenta_equivalente"] == "AntConc Keyword List, Wmatrix, quanteda textstat_keyness (G²)"
    assert r["nao_equivalente"] == "Voyant 'termos distintivos' (TF-IDF, sem teste)"
    assert "2 células" in r["metodologia"] and r["parametros"]["min_freq"] == 1
    lados = keyness.lados_disponiveis(voc, metas)
    assert {g["valor"]: g["documentos"] for g in lados["grupos"]} == {"alfa": 3, "beta": 2, "sem grupo": 2}
    assert lados["grupos_definidos"] == 2 and "s/ano" in {a["valor"] for a in lados["anos"]}
    assert sum(g["tokens"] for g in lados["grupos"]) == voc["corpus"]["tokens"]


# ---------- etapa comparativo (instantâneo em analise) ----------

def _keyness_linhas(slug):
    db = database.sessao_do_projeto(slug)
    try:
        return [a for a in db.query(Analise).filter(Analise.tipo == "keyness").order_by(Analise.id)]
    finally:
        db.close()


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return {e["etapa"]: e for e in r.json()["etapas"]}


def _definir_grupo(client, slug, arquivo, grupo):
    docs = {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{slug}/documentos").json()}
    assert client.patch(f"/api/projetos/{slug}/documentos/{docs[arquivo]}", json={"grupo": grupo}).status_code == 200


def test_etapa_comparativo_grava_substitui_e_invalida(client, projeto5):
    linhas = _keyness_linhas(projeto5)
    assert len(linhas) == 1  # a fixture já executou com 2 grupos (academica, cinzenta)
    a = linhas[0]
    assert a.ferramenta_equivalente == keyness.FERRAMENTA_EQUIVALENTE
    r = json.loads(a.resultado_json)
    assert r["grupos"] == ["academica", "cinzenta"] and [c["lado_a"]["valor"] for c in r["comparacoes"]] == r["grupos"]
    assert all(c["lado_b"]["valor"] == "resto" for c in r["comparacoes"])
    assert json.loads(a.parametros_json)["b"] == "resto"

    et = _executar(client, projeto5)
    assert et["comparativo"]["pulado"] == 1  # nada mudou: cache
    assert [x.id for x in _keyness_linhas(projeto5)] == [a.id]

    # editar o grupo invalida a etapa; a linha é substituída (uma só), agora com 3 grupos
    _definir_grupo(client, projeto5, "003_2025_Lee_Terceiro.md", "terceiro")
    et = _executar(client, projeto5)
    assert et["comparativo"]["pulado"] == 0 and et["descritivo"]["pulado"] == 0
    novas = _keyness_linhas(projeto5)
    assert len(novas) == 1 and novas[0].id != a.id
    assert json.loads(novas[0].resultado_json)["grupos"] == ["academica", "cinzenta", "terceiro"]


def test_etapa_comparativo_sem_dois_grupos_nao_grava(client, projeto5):
    for arq in ("002_2025_Silva_Portugues.md", "003_2025_Lee_Terceiro.md"):
        _definir_grupo(client, projeto5, arq, "academica")
    et = _executar(client, projeto5)
    assert et["comparativo"]["pulado"] == 0 and et["comparativo"].get("erro", 0) == 0
    assert _keyness_linhas(projeto5) == []  # a linha antiga foi removida; nada novo
    lados = _get(client, projeto5, "grupos").json()
    assert lados["grupos_definidos"] == 1
    # a consulta na hora continua possível com A e B explícitos (ano, por exemplo)
    r = _get(client, projeto5, "keyness", particao="ano", a="2025", min_freq=1, min_docs_a=1, min_docs_b=1, p=1).json()
    assert r["lado_a"]["documentos"] == 2


# ---------- API ----------

def test_api_grupos_e_keyness(client, projeto5, projetos_dir, ids):
    g = _get(client, projeto5, "grupos").json()
    assert {x["valor"]: x["documentos"] for x in g["grupos"]} == {"academica": 1, "cinzenta": 2}
    assert g["grupos_definidos"] == 2 and {a["valor"] for a in g["anos"]} == {"2025", "2026"}

    q = dict(a="cinzenta", b="academica", min_freq=1, min_docs_a=1, min_docs_b=1, p=1, limite=500)
    r = _get(client, projeto5, "keyness", **q).json()
    ta, tb = _tokens(projetos_dir, projeto5, ids["A"]), [_tokens(projetos_dir, projeto5, ids[k]) for k in "BC"]
    contados = lambda t: sum(1 for n, i in zip(t["norm"], t["incluir"]) if i and len(n) >= 2)  # noqa: E731
    assert r["lado_a"]["tokens"] == sum(contados(t) for t in tb) and r["lado_b"]["tokens"] == contados(ta)
    assert r["lado_a"]["documentos"] == 2 and r["lado_b"]["documentos"] == 1
    # "tasks"/"agents" etc. por lema: conferido por recontagem
    agent_a = sum(1 for l, i in zip(ta["lema"], ta["incluir"]) if i and l == "agent")
    todos = {i["termo"]: i for i in r["positivas"] + r["negativas"]}
    assert todos["agent"]["b"] == agent_a  # B = academica
    assert r["parametros"]["particao"] == "grupo" and r["ferramenta_equivalente"].startswith("AntConc")

    padrao = _get(client, projeto5, "keyness", a="cinzenta").json()  # B = resto, filtros padrão
    assert padrao["parametros"]["b"] == "resto" and padrao["parametros"]["min_freq"] == 5

    assert client.get(f"/api/projetos/{projeto5}/analises/keyness", params={"a": "nao-existe"}).status_code == 422
    assert client.get(f"/api/projetos/{projeto5}/analises/keyness", params={"a": "cinzenta", "b": "cinzenta"}).status_code == 422
    assert client.get(f"/api/projetos/{projeto5}/analises/keyness").status_code == 422  # falta o lado A


def test_api_keyness_csv(client, projeto5):
    q = dict(a="cinzenta", b="academica", min_freq=1, min_docs_a=1, min_docs_b=1, p=1)
    r = _get(client, projeto5, "keyness.csv", **q)
    assert r.headers["content-type"].startswith("text/csv") and "keyness.csv" in r.headers["content-disposition"]
    assert r.content.startswith("﻿".encode("utf-8"))
    linhas = r.content.decode("utf-8-sig").splitlines()
    assert linhas[0] == ("lado;posicao;termo;freq_a;freq_b;por_10k_a;por_10k_b;g2;p;p_bonferroni;log_ratio;"
                         "pct_diff;docs_a;docs_b")
    j = _get(client, projeto5, "keyness", **q).json()
    assert len(linhas) - 1 == len(j["positivas"]) + len(j["negativas"]) > 0
    primeira = linhas[1].split(";")
    assert primeira[0] == "A" and primeira[2] == j["positivas"][0]["termo"]
    assert "," in primeira[7]  # decimal pt-BR
