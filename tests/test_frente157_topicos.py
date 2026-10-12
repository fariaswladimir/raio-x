"""15.7 (e 7.4) Tópicos: LSA, NMF e LDA, coerência (UMass, NPMI, C_v), perplexidade, API e etapa.

Funções puras contra cálculo à mão (corpus de brinquedo) e propriedades conhecidas (Eckart-Young na LSA, recuperação
de tópicos plantados no NMF e no LDA, determinismo com semente); API e etapa com o corpus sintético da 6.3."""
import math
from collections import Counter

import numpy as np
import pytest
import scipy.sparse as sp

from app.services.analises import dados, topicos as T
from tests.test_frente63_64 import PLANO, TOPICOS, _executar, _get, _snapshots, corpus63, projeto63  # noqa: F401


# ---------- apoio ----------

def _plantado(n_por=40, topicos=3, voc=15, tokens=80, mistura=0.15, semente=3):
    """Documentos com um tópico dominante (85%) e 15% de outro tópico; vocabulários disjuntos."""
    rng = np.random.default_rng(semente)
    contagens, verdade = [], []
    for t in range(topicos):
        for _ in range(n_por):
            outro = (t + 1 + rng.integers(0, topicos - 1)) % topicos
            n_outro = int(round(mistura * tokens))
            ws = [f"t{t}w{j}" for j in rng.integers(0, voc, tokens - n_outro)] + \
                 [f"t{outro}w{j}" for j in rng.integers(0, voc, n_outro)]
            contagens.append(Counter(ws))
            verdade.append(t)
    return contagens, np.array(verdade)


def _pureza(prop, verdade):
    atrib = prop.argmax(axis=1)
    return sum(max(Counter(verdade[atrib == c]).values()) for c in set(atrib)) / len(verdade)


def _palavras_puras(pesos, vocab, n=10):
    """Fração dos tópicos cujas top-n palavras vêm todas de um único tópico plantado."""
    ok = 0
    for linha in pesos:
        tops = {vocab[i].split("w")[0] for i in np.argsort(-linha)[:n]}
        ok += len(tops) == 1
    return ok / len(pesos)


# ---------- matriz e TF-IDF ----------

def test_dtm_min_df_max_df_e_tfidf():
    c = [Counter({"a": 2, "b": 1, "c": 1}), Counter({"a": 1, "b": 3}), Counter({"a": 1, "d": 1}), Counter({"a": 1, "b": 1})]
    X, vocab = T.matriz_dtm(c, min_df=2, max_df=0.9)
    assert vocab == ["b"]  # a: df 4/4 > 0,9; c, d: df 1 < 2
    X, vocab = T.matriz_dtm(c, min_df=1, max_df=1.0)
    assert vocab == ["a", "b", "c", "d"] and X.toarray()[1].tolist() == [1, 3, 0, 0]
    Tm, idf = T.tfidf(X)
    df = np.array([4, 3, 1, 1])
    assert idf == pytest.approx(np.log(5 / (1 + df)) + 1)
    linha = np.array([1 + math.log(2), 1, 1, 0]) * idf
    assert Tm.toarray()[0] == pytest.approx(linha / np.linalg.norm(linha))


# ---------- LSA ----------

def test_lsa_reconstrucao_eckart_young_e_sinal():
    rng = np.random.default_rng(0)
    X = sp.csr_matrix(rng.poisson(1.0, (12, 30)).astype(float))
    U, S, Vt = T.svd_truncada(X, 12)
    assert np.allclose((U * S) @ Vt, X.toarray(), atol=1e-10)  # posto completo: reconstrução exata
    _, s_todos, _ = np.linalg.svd(X.toarray())
    for k in (2, 5):
        U, S, Vt = T.svd_truncada(X, k)
        erro = np.linalg.norm(X.toarray() - (U * S) @ Vt)
        assert erro == pytest.approx(math.sqrt((s_todos[k:] ** 2).sum()), rel=1e-9)  # Eckart-Young
        assert all(Vt[j, np.argmax(np.abs(Vt[j]))] > 0 for j in range(k))  # sinal determinístico
    # caminho esparso (svds) dá o mesmo subespaço e os mesmos sinais
    Xg = sp.random(300, 15000, density=0.002, random_state=1, format="csr")
    U1, S1, V1 = T.svd_truncada(Xg, 4)
    U2, S2, V2 = np.linalg.svd(Xg.toarray(), full_matrices=False)
    assert S1 == pytest.approx(S2[:4], rel=1e-8)
    assert np.allclose(np.abs(V1), np.abs(V2[:4]), atol=1e-6)


# ---------- NMF ----------

def test_nmf_nndsvd_e_recuperacao_de_topicos_plantados():
    c, verdade = _plantado()
    X, vocab = T.matriz_dtm(c, min_df=2, max_df=1.0)
    W0, H0 = T.nndsvd(T.tfidf(X)[0], 3, "a")
    assert (W0 > 0).all() and (H0 > 0).all()
    aj = T.ajustar(X, "nmf", 3)
    assert _pureza(aj["proporcoes"], verdade) >= 0.9
    assert _palavras_puras(aj["pesos_termos"], vocab) == 1.0
    assert np.allclose(aj["proporcoes"].sum(axis=1), 1) and np.allclose(aj["pesos_termos"].sum(axis=1), 1)
    aj2 = T.ajustar(X, "nmf", 3)
    assert np.array_equal(aj["pesos_termos"], aj2["pesos_termos"])  # determinístico


def test_nmf_reduz_o_erro():
    rng = np.random.default_rng(5)
    X = np.abs(rng.normal(size=(20, 12)))
    W, H = T.nndsvd(X, 3, "a")
    e0 = np.linalg.norm(X - W @ H)
    m = T.nmf(X, 3, iteracoes=300)
    assert m["erro_frobenius"] < e0 and m["erro_frobenius"] == pytest.approx(np.linalg.norm(X - m["W"] @ m["H"]), rel=1e-6)


# ---------- LDA ----------

def test_lda_recupera_topicos_plantados_e_e_deterministico():
    c, verdade = _plantado()
    X, vocab = T.matriz_dtm(c, min_df=2, max_df=1.0)
    m = T.lda_gibbs(X, 3, iteracoes=200, semente=42)
    assert _pureza(m["theta"], verdade) >= 0.9
    assert _palavras_puras(m["phi"], vocab) == 1.0
    assert np.allclose(m["phi"].sum(axis=1), 1) and np.allclose(m["theta"].sum(axis=1), 1)
    assert m["alpha"] == pytest.approx(50 / 3) and m["beta"] == 0.01 and m["amostras"] == 10
    # contagens consistentes com o total de tokens
    assert m["ndk"].sum() == X.sum() and np.array_equal(m["ndk"].sum(axis=0), m["nkw"].sum(axis=1))
    m2 = T.lda_gibbs(X, 3, iteracoes=200, semente=42)
    assert np.array_equal(m["phi"], m2["phi"]) and np.array_equal(m["theta"], m2["theta"])
    m3 = T.lda_gibbs(X, 3, iteracoes=200, semente=7)
    assert not np.array_equal(m["phi"], m3["phi"])
    # log p(w|z) cresce do início para o fim
    assert m["traco"][-1]["log_p_w_z"] > m["traco"][0]["log_p_w_z"]


def test_lda_gibbs_sequencial_exato_tambem_recupera():
    c, verdade = _plantado(n_por=15, tokens=40)
    X, _ = T.matriz_dtm(c, min_df=2, max_df=1.0)
    m = T.lda_gibbs(X, 3, alpha=0.5, iteracoes=60, burn_in=30, semente=1, bloco=1)
    assert m["bloco"] == 1 and _pureza(m["theta"], verdade) >= 0.9


def test_log_verossimilhanca_confere_com_formula_direta():
    nkw = np.array([[3, 0, 1], [0, 2, 2]], dtype=float)
    b = 0.1
    V = 3
    direto = sum(math.lgamma(V * b) - V * math.lgamma(b) + sum(math.lgamma(x + b) for x in linha) - math.lgamma(linha.sum() + V * b)
                 for linha in nkw)
    assert T.log_verossimilhanca(nkw, b) == pytest.approx(direto, rel=1e-12)


def test_perplexidade_lda_razoavel():
    c, _ = _plantado(n_por=20)
    docs = list(range(len(c)))
    p = T.perplexidade_lda(c, docs, 3, iteracoes=100, semente=42)
    # 45 palavras equiprováveis no corpus: o unigrama dá ~45; a mistura verdadeira (85% de 15 palavras + 15% de outras
    # 15) tem entropia exp(0,85·ln(15/0,85) + 0,15·ln(15/0,15)) ~ 22,9, um piso aproximado
    assert p["documentos_teste"] == 12 and 20 < p["valor"] < 40
    p1 = T.perplexidade_lda(c, docs, 1, iteracoes=50, semente=42)
    assert p1["valor"] > p["valor"]  # 1 tópico (unigrama) explica pior
    assert T.perplexidade_lda(c[:2], [0, 1], 2) is None


# ---------- coerência: brinquedo calculado à mão ----------

def test_umass_a_mao():
    docs = [["a", "b", "c"], ["a", "b"], ["b", "c"], ["a", "d"]]
    X, vocab = T.matriz_dtm([Counter(d) for d in docs], min_df=1, max_df=1.0)
    pos = {t: j for j, t in enumerate(vocab)}
    # topo [a, b, c]: (b|a) log((2+1)/3) = 0 ; (c|a) log((1+1)/3) ; (c|b) log((2+1)/3) = 0
    esperado = (0 + math.log(2 / 3) + 0) / 3
    assert T.umass([[pos["a"], pos["b"], pos["c"]]], X)[0] == pytest.approx(esperado, rel=1e-12)
    # ordem importa: [c, a]: log((D(a,c)+1)/D(c)) = log(2/2) = 0
    assert T.umass([[pos["c"], pos["a"]]], X)[0] == pytest.approx(0.0, abs=1e-12)
    # suavização do gensim (epsilon em probabilidade = 1e-12 * N nas contagens)
    assert T.umass([[pos["a"], pos["d"], pos["c"]]], X, suavizacao=1e-12 * 4)[0] == pytest.approx(
        # (d|a): D(a,d) = 1, D(a) = 3; (c|a): D(a,c) = 1; (c|d): D(c,d) = 0, D(d) = 1
        (math.log((1 + 4e-12) / 3) + math.log((1 + 4e-12) / 3) + math.log(4e-12 / 1)) / 3, rel=1e-9)


def test_janelas_npmi_e_cv_a_mao():
    seqs = [["a", "b", "c", "a"], ["d"]]
    n, cont, conj = T.contagens_janela(seqs, ["a", "b", "c", "d"], janela=2)
    # janelas: [a b] [b c] [c a] e o documento curto [d]
    assert n == 4 and cont.tolist() == [2, 2, 2, 1]
    assert conj[0, 1] == 1 and conj[1, 2] == 1 and conj[0, 2] == 1 and conj[0, 3] == 0 and conj[0, 0] == 2
    M = T.matriz_npmi(n, cont, conj)
    x = math.log((1 / 4) / (2 / 4) ** 2) / -math.log(1 / 4)
    assert M[0, 1] == pytest.approx(x, abs=1e-9) and M[0, 0] == pytest.approx(1.0, abs=1e-9)
    assert M[0, 3] < -0.9  # nunca juntos: perto de -1 (com o epsilon de 1e-12)
    sub = M[:3, :3]
    assert T.coerencia_npmi(sub) == pytest.approx(x, abs=1e-9)
    cv = (1 + 2 * x) / (math.sqrt(3) * math.sqrt(1 + 2 * x * x))
    assert T.coerencia_cv(sub) == pytest.approx(cv, abs=1e-9)


def test_janela_confere_com_forca_bruta():
    rng = np.random.default_rng(2)
    seqs = [[f"w{i}" for i in rng.integers(0, 12, L)] for L in (5, 40, 130, 7)]
    pal = [f"w{i}" for i in range(8)]
    for janela in (3, 10, 110):
        n, cont, conj = T.contagens_janela(seqs, pal, janela)
        n2, c2, j2 = 0, np.zeros(8), np.zeros((8, 8))
        for s in seqs:
            jans = [s] if len(s) <= janela else [s[i:i + janela] for i in range(len(s) - janela + 1)]
            for jn in jans:
                n2 += 1
                pres = [i for i, p in enumerate(pal) if p in jn]
                for i in pres:
                    c2[i] += 1
                    for j in pres:
                        j2[i, j] += 1
        assert n == n2 and np.array_equal(cont, c2) and np.array_equal(conj, j2)


def test_coerencia_maior_em_topico_plantado_que_em_misturado():
    c, _ = _plantado()
    X, vocab = T.matriz_dtm(c, min_df=1, max_df=1.0)
    seqs = [list(cc.elements()) for cc in c]
    bom = [f"t0w{j}" for j in range(10)]
    ruim = [f"t{j % 3}w{j}" for j in range(10)]
    cb, cr = T.coerencias([bom, ruim], vocab, X, seqs, janela=110)
    assert cb["umass"] > cr["umass"] and cb["npmi"] > cr["npmi"] and cb["cv"] > cr["cv"]


# ---------- API, CSV e etapa (corpus sintético da 6.3: 9 documentos, 3 tópicos) ----------

def test_api_topicos_lda_nmf_lsa_por_documento_e_segmento(client, projeto63):
    for modelo in ("lda", "nmf"):
        r = _get(client, projeto63, "topicos", modelo=modelo, k=3, iteracoes=200).json()
        assert r["modelo"] == modelo and r["k"] == 3 and len(r["topicos"]) == 3 and r["n_documentos"] == 9
        assert {round(sum(d["pesos"]), 3) for d in r["documentos"]} == {1.0}
        # cada tópico plantado domina um tópico estimado
        dominante = {}
        for d in r["documentos"]:
            arq = next(a for a in PLANO if a.startswith(d["rotulo"][:3]))
            dominante.setdefault(PLANO[arq][0], set()).add(int(np.argmax(d["pesos"])))
        assert all(len(v) == 1 for v in dominante.values()) and len(set.union(*dominante.values())) == 3
        for t in r["topicos"]:
            assert len(t["palavras"]) == 10 and set(t["coerencia"]) == {"umass", "npmi", "cv"}
            assert t["trechos"] and all(x["pagina"] in (1, 2) and x["texto"] for x in t["trechos"])
        assert r["por_grupo"]["partes"] == ["academica", "cinzenta"] and len(r["por_ano"]["matriz"]) == 3
        assert "não STM" in r["nota_agregacao"] or "não\nSTM" in r["nota_agregacao"] or "STM" in r["nota_agregacao"]
    r = _get(client, projeto63, "topicos", modelo="lsa", k=3).json()
    assert r["pesos_sao_proporcoes"] is False and "palavras_negativas" in r["topicos"][0]
    r = _get(client, projeto63, "topicos", modelo="lda", k=3, unidade="segmento", iteracoes=100).json()
    assert r["unidade"] == "segmento" and r["n_unidades"] > 9 and r["n_documentos"] == 9
    rr = client.get(f"/api/projetos/{projeto63}/analises/topicos", params={"k": 30})
    assert rr.status_code == 422 and "pequeno demais" in rr.text
    assert client.get(f"/api/projetos/{projeto63}/analises/topicos", params={"modelo": "xyz"}).status_code == 422


def test_api_varredura_e_csvs(client, projeto63):
    r = _get(client, projeto63, "topicos/varredura", modelo="lda", k_min=2, k_max=4, iteracoes=60).json()
    assert [l["k"] for l in r["linhas"]] == [2, 3, 4]
    assert all(l["cv"] is not None and l["perplexidade"] is not None for l in r["linhas"])
    r = _get(client, projeto63, "topicos/varredura", modelo="nmf", k_min=2, k_max=3).json()
    assert all(l["perplexidade"] is None for l in r["linhas"])
    csv = _get(client, projeto63, "topicos/palavras.csv", modelo="nmf", k=3).content.decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("topico;posicao;termo;peso") and len(csv.splitlines()) == 31
    csv = _get(client, projeto63, "topicos/documentos.csv", modelo="nmf", k=3).content.decode("utf-8-sig")
    assert len(csv.splitlines()) == 10
    csv = _get(client, projeto63, "topicos/varredura.csv", modelo="nmf", k_min=2, k_max=3).content.decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("k;umass;npmi;cv;perplexidade")


def test_etapa_topicos_grava_instantaneo_com_parametros_do_projeto(client, projeto63, monkeypatch):
    assert _snapshots(projeto63, "topicos") == []  # padrão K = 8 com 9 documentos: pequeno demais, nada gravado
    p = client.get(f"/api/projetos/{projeto63}/parametros").json()
    p["topicos"] = {"modelo": "nmf", "k": 3, "unidade": "documento", "semente": 42, "iteracoes": 200}
    assert client.put(f"/api/projetos/{projeto63}/parametros", json=p).status_code == 200
    etapas = _executar(client, projeto63)
    assert etapas["topicos"]["ok"] == 1 and etapas["topicos"]["erro"] == 0
    snaps = _snapshots(projeto63, "topicos")
    assert len(snaps) == 1 and '"modelo": "nmf"' in snaps[0].parametros_json and '"k": 3' in snaps[0].parametros_json
    # sem parâmetros na URL, a API devolve o instantâneo (sem recalcular) enquanto a assinatura valer
    T._RESULTADOS._d.clear()

    def proibido(*a, **k):
        raise AssertionError("não devia recalcular")

    monkeypatch.setattr(T, "ajustar", proibido)
    r = _get(client, projeto63, "topicos").json()
    assert r["modelo"] == "nmf" and r["k"] == 3 and r["assinatura"]
    dados.limpar_caches()
