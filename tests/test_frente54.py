"""5.4 - Colocados (LL, MI, t, logDice): conferência contra força bruta, scipy e exemplos à mão; API e exportação."""
import io
import json
import math
import random
import zipfile
from collections import Counter

import pytest

from app.services.analises import colocacoes, dados
from app.services.palavras_vazias import token_vazio
from tests.test_frente5 import _get, _tokens, corpus5, ids, projeto5  # noqa: F401  (fixtures reaproveitadas)

VAZIAS = frozenset({"the", "of", "and", "is"})
LEMAS = {"agents": "agent", "tasks": "task", "models": "model", "humans": "human"}


# ---------- corpus sintético em disco (sem pipeline) ----------

def _doc_tokens(blocos: list[tuple[str, int]]) -> dict:
    """Arrays de tokens no formato de cache/tokens a partir de [(texto, incluir)], um item por bloco."""
    t = {k: [] for k in ("forma", "norm", "lema", "pagina", "secao", "incluir", "bloco", "inicio", "fim")}
    for b, (texto, inc) in enumerate(blocos):
        pos = 0
        for w in texto.split():
            n = w.lower()
            t["forma"].append(w); t["norm"].append(n); t["lema"].append(LEMAS.get(n, n))
            t["pagina"].append(b + 1); t["secao"].append(0); t["incluir"].append(inc); t["bloco"].append(b)
            t["inicio"].append(pos); t["fim"].append(pos + len(w)); pos += len(w) + 1
    return {"formato": 1, "idioma": "en", "n": len(t["forma"]), "secoes": ["corpo"], **t}


def _gravar(pasta, docs: dict[int, list[tuple[str, int]]]) -> list[dict]:
    (pasta / "cache" / "tokens").mkdir(parents=True, exist_ok=True)
    for i, blocos in docs.items():
        (pasta / "cache" / "tokens" / f"{i}.json").write_text(json.dumps(_doc_tokens(blocos)), encoding="utf-8")
    dados.limpar_caches()
    return [{"id": i} for i in docs]


def _calc(pasta, metas, q, **kw):
    base = dict(filtro=VAZIAS, min_freq=1, min_freq_colocado=1, limite=10**6, repulsao=True)
    base.update(kw)
    return colocacoes.calcular(pasta, metas, q, **base)


def _por_termo(r):
    return {c["termo"]: c for c in r["colocados"]}


# ---------- referência por força bruta (laços ingênuos, formulação independente) ----------

def forca_bruta(pasta, metas, q, por="lema", esquerda=5, direita=5, filtro=VAZIAS, filtrar=True, fronteira="bloco"):
    """Para cada token contado j, verifica se ALGUMA ocorrência do nó i o cobre (|j-i| dentro do span, sem fronteira
    entre os dois). Devolve N, R1, f_no, O11/C1/pares/perfil por chave."""
    itens = dados.compilar_consulta(q)
    campo = "lema" if por == "lema" else "norm"
    n_total = r1 = f_no = 0
    o11, c1, pares, perfil = Counter(), Counter(), Counter(), Counter()
    for m in metas:
        tk = json.loads((pasta / "cache" / "tokens" / f"{m['id']}.json").read_text(encoding="utf-8"))
        cont = [i for i in range(tk["n"]) if tk["incluir"][i] and len(tk["norm"][i]) >= 2]
        n_total += len(cont)
        chave = [tk[campo][i] for i in cont]
        bloco = [tk["bloco"][i] for i in cont]
        cand = [not filtrar or not token_vazio(tk["norm"][i], tk["lema"][i], filtro) for i in cont]
        eh_no = [any(dados.casa(it, k) for it in itens) for k in chave]
        f_no += sum(eh_no)
        for j in range(len(cont)):
            if cand[j] and not eh_no[j]:
                c1[chave[j]] += 1
        for j in range(len(cont)):
            if eh_no[j]:
                continue
            cobridores = []
            for i in range(len(cont)):
                if not eh_no[i]:
                    continue
                rel = j - i
                if not (-esquerda <= rel <= direita) or rel == 0:
                    continue
                lo, hi = min(i, j), max(i, j)
                if fronteira == "bloco" and len(set(bloco[lo:hi + 1])) > 1:
                    continue
                cobridores.append(rel)
            if cobridores:
                r1 += 1
                if cand[j]:
                    o11[chave[j]] += 1
                    pares[chave[j]] += len(cobridores)
                    for rel in cobridores:
                        perfil[(chave[j], rel)] += 1
    return {"N": n_total, "R1": r1, "f_no": f_no, "o11": o11, "c1": c1, "pares": pares, "perfil": perfil}


def _g2_scipy(o11, r1, c1, n):
    stats = pytest.importorskip("scipy.stats")
    tab = [[o11, r1 - o11], [c1 - o11, n - r1 - c1 + o11]]
    g2, p, _, _ = stats.chi2_contingency(tab, correction=False, lambda_="log-likelihood")
    return g2, p


PALAVRAS = ["agent", "agents", "agentic", "task", "tasks", "model", "the", "of", "and", "a", "x", "human", "data",
            "zeta", "beta", "tool", "is"]


@pytest.fixture()
def corpus_aleatorio(tmp_path):
    rnd = random.Random(54)
    docs = {}
    for d in range(1, 5):
        blocos = []
        for _ in range(rnd.randint(2, 5)):
            texto = " ".join(rnd.choice(PALAVRAS) for _ in range(rnd.randint(5, 60)))
            blocos.append((texto, 0 if rnd.random() < 0.2 else 1))
        docs[d] = blocos
    pasta = tmp_path / "proj"
    return pasta, _gravar(pasta, docs)


CASOS = [
    dict(q="agent"), dict(q="agent", esquerda=0, direita=3), dict(q="agent", esquerda=4, direita=1),
    dict(q="agent", fronteira="documento"), dict(q="agent", filtrar=False), dict(q="agents", por="forma"),
    dict(q="agent*"), dict(q="task, human", esquerda=2, direita=2), dict(q="the", filtrar=False, esquerda=3, direita=3),
]


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()))
def test_igual_a_forca_bruta(corpus_aleatorio, caso):
    pasta, metas = corpus_aleatorio
    kw = {k: v for k, v in caso.items() if k != "q"}
    ref = forca_bruta(pasta, metas, caso["q"], **kw)
    r = _calc(pasta, metas, caso["q"], **kw)
    assert (r["N"], r["R1"], r["ocorrencias_no"]) == (ref["N"], ref["R1"], ref["f_no"])
    assert r["R1"] > 0 and r["N"] > r["R1"]
    got = _por_termo(r)
    assert set(got) == {k for k in ref["o11"] if ref["c1"][k] < ref["N"]}
    esquerda, direita = kw.get("esquerda", 5), kw.get("direita", 5)
    for termo, c in got.items():
        assert c["o11"] == ref["o11"][termo] and c["c1"] == ref["c1"][termo] and c["pares"] == ref["pares"][termo]
        assert c["o11"] <= c["c1"] and c["o11"] <= c["pares"]
        assert c["posicoes"] == {str(x): ref["perfil"][(termo, x)] for x in [*range(-esquerda, 0), *range(1, direita + 1)]}
        e11 = r["R1"] * c["c1"] / r["N"]
        assert c["e11"] == pytest.approx(e11, abs=1e-4)
        assert c["mi"] == pytest.approx(math.log2(c["o11"] / e11), abs=1e-4)
        g2, p = _g2_scipy(c["o11"], r["R1"], c["c1"], r["N"])
        assert abs(c["ll"]) == pytest.approx(g2, abs=1e-3)
        assert (c["ll"] < 0) == (c["o11"] < e11)
        assert c["p"] == pytest.approx(p, rel=1e-6, abs=1e-12)
        assert c["logdice"] == pytest.approx(14 + math.log2(2 * c["o11"] / (r["ocorrencias_no"] + c["c1"])), abs=1e-4)
        assert c["t"] == pytest.approx((c["o11"] - e11) / math.sqrt(c["o11"]), abs=1e-4)


# ---------- estatística: valores à mão e scipy ----------

def test_mi_e_ll_calculados_a_mao():
    # N = 1000, R1 = 50, C1 = 20, O11 = 10 -> E11 = 50*20/1000 = 1 -> MI = log2(10) = 3,3219
    m = colocacoes.medidas(10, 50, 20, 1000, f_no=10)
    assert m["e11"] == 1.0 and m["mi"] == pytest.approx(3.321928, abs=1e-6)
    # G² à mão: O = (10, 40, 10, 940), E = (1, 49, 19, 931)
    g2 = 2 * (10 * math.log(10 / 1) + 40 * math.log(40 / 49) + 10 * math.log(10 / 19) + 940 * math.log(940 / 931))
    assert m["ll"] == pytest.approx(g2, abs=1e-9) and g2 == pytest.approx(35.0661, abs=1e-3)
    assert m["p"] == pytest.approx(math.erfc(math.sqrt(g2 / 2)))
    assert m["t"] == pytest.approx(9 / math.sqrt(10)) and m["logdice"] == pytest.approx(14 + math.log2(20 / 30))
    # repulsão: O11 < E11 -> LL negativo, MI negativo
    r = colocacoes.medidas(1, 100, 200, 1000, f_no=20)  # E11 = 20
    assert r["ll"] < 0 and r["mi"] == pytest.approx(math.log2(1 / 20))
    # 0·ln 0 = 0: célula vazia não quebra (O12 = 0)
    assert colocacoes.log_likelihood(5, 5, 5, 100) > 0
    assert colocacoes.valor_p(0.0) == 1.0 and colocacoes.valor_p(3.841459) == pytest.approx(0.05, abs=1e-6)


def test_ll_contra_scipy_power_divergence():
    stats = pytest.importorskip("scipy.stats")
    np = pytest.importorskip("numpy")
    for o11, r1, c1, n in [(10, 50, 20, 1000), (3, 400, 30, 5000), (25, 900, 60, 437000), (1, 10, 1, 50), (7, 7, 9, 99)]:
        obs = np.array([o11, r1 - o11, c1 - o11, n - r1 - c1 + o11], dtype=float)
        exp = np.array([r1 * c1, r1 * (n - c1), (n - r1) * c1, (n - r1) * (n - c1)], dtype=float) / n
        g2 = stats.power_divergence(obs, exp, ddof=2, lambda_="log-likelihood").statistic  # ddof: 3-2 = 1 g.l.
        assert abs(colocacoes.log_likelihood(o11, r1, c1, n)) == pytest.approx(g2, rel=1e-9)
        assert colocacoes.valor_p(g2) == pytest.approx(stats.chi2.sf(g2, 1), rel=1e-9)


# ---------- regras da janela ----------

def test_fronteira_de_documento_e_de_bloco(tmp_path):
    pasta = tmp_path / "p"
    metas = _gravar(pasta, {
        1: [("zz yy agent", 1), ("beta ww", 1)],  # beta logo depois do nó, mas em outro bloco
        2: [("gamma vv uu", 1)],  # gamma logo depois do fim do documento 1
    })
    bloco = _por_termo(_calc(pasta, metas, "agent"))
    assert "beta" not in bloco and "gamma" not in bloco and set(bloco) == {"zz", "yy"}
    doc = _calc(pasta, metas, "agent", fronteira="documento")
    assert set(_por_termo(doc)) == {"zz", "yy", "beta", "ww"} and "gamma" not in _por_termo(doc)
    assert doc["R1"] == 4 and _calc(pasta, metas, "agent")["R1"] == 2


def test_secao_excluida_nao_ocupa_posicao_e_fronteira_bloco(tmp_path):
    pasta = tmp_path / "p"
    metas = _gravar(pasta, {1: [("agent", 1), ("ref1 ref2 ref3", 0), ("delta", 1)]})
    assert _calc(pasta, metas, "agent")["R1"] == 0
    doc = _calc(pasta, metas, "agent", fronteira="documento", esquerda=1, direita=1)
    assert set(_por_termo(doc)) == {"delta"} and _por_termo(doc)["delta"]["posicoes"] == {"-1": 0, "1": 1}
    assert doc["N"] == 2  # as referências não contam em N


def test_palavra_vazia_ocupa_posicao_e_token_de_uma_letra_nao(tmp_path):
    pasta = tmp_path / "p"
    metas = _gravar(pasta, {1: [("agent the of the of zeta", 1), ("agent a omega", 1)]})
    r5 = _por_termo(_calc(pasta, metas, "agent", esquerda=0, direita=5))
    assert r5["zeta"]["posicoes"]["5"] == 1 and "the" not in r5 and "of" not in r5
    assert "zeta" not in _por_termo(_calc(pasta, metas, "agent", esquerda=0, direita=4))  # vazias contam no span
    assert r5["omega"]["posicoes"]["1"] == 1  # "a" (1 letra) não existe para a análise
    manter = _calc(pasta, metas, "agent", esquerda=0, direita=5, filtrar=False)
    assert {"the", "of"} <= set(_por_termo(manter))
    # o filtro só esconde candidatos: R1 e N não mudam e os números dos demais colocados são os mesmos
    filtrar = _calc(pasta, metas, "agent", esquerda=0, direita=5)
    assert (manter["R1"], manter["N"]) == (filtrar["R1"], filtrar["N"]) == (6, 8)
    assert _por_termo(manter)["zeta"] == _por_termo(filtrar)["zeta"]


def test_janela_assimetrica(tmp_path):
    pasta = tmp_path / "p"
    metas = _gravar(pasta, {1: [("l3 l2 l1 agent r1 r2 r3", 1)]})
    r = _calc(pasta, metas, "agent", esquerda=0, direita=2)
    assert set(_por_termo(r)) == {"r1", "r2"} and r["R1"] == 2 and r["parametros"]["esquerda"] == 0
    r = _calc(pasta, metas, "agent", esquerda=3, direita=1)
    assert set(_por_termo(r)) == {"l3", "l2", "l1", "r1"} and set(_por_termo(r)["l3"]["posicoes"]) == {"-3", "-2", "-1", "1"}


def test_no_nao_e_colocado_de_si_mesmo_e_sobreposicao_unida(tmp_path):
    pasta = tmp_path / "p"
    metas = _gravar(pasta, {1: [("agent agent beta", 1), ("agent beta agent", 1)]})
    r = _calc(pasta, metas, "agent", esquerda=1, direita=1)
    assert "agent" not in _por_termo(r)
    beta = _por_termo(r)["beta"]
    # bloco 1: beta coberto 1 vez; bloco 2: beta coberto pelas duas ocorrências -> conta 1 vez em O11, 2 em pares
    assert r["R1"] == 2 and beta["o11"] == 2 and beta["pares"] == 3
    assert beta["posicoes"] == {"-1": 1, "1": 2} and r["ocorrencias_no"] == 4
    assert beta["o11"] <= beta["c1"] == 2  # com a união, O11 nunca passa de C1


def test_lema_forma_e_curinga(tmp_path):
    pasta = tmp_path / "p"
    metas = _gravar(pasta, {1: [("agents build tasks agent build models agentic build task", 1)]})
    lema = _calc(pasta, metas, "agent", esquerda=1, direita=1)
    assert lema["ocorrencias_no"] == 2 and _por_termo(lema)["task"]["o11"] == 1  # tasks -> task (lema)
    forma = _calc(pasta, metas, "agents", por="forma", esquerda=1, direita=1)
    assert forma["ocorrencias_no"] == 1 and set(_por_termo(forma)) == {"build"}
    curinga = _calc(pasta, metas, "agent*", esquerda=1, direita=1)
    assert curinga["ocorrencias_no"] == 3 and "agentic" not in _por_termo(curinga)
    assert {f["termo"] for f in curinga["no"]["formas"]} == {"agent", "agentic"}


def test_limiares_ordem_limite_e_repulsao(tmp_path):
    pasta = tmp_path / "p"
    # "common" é muito frequente fora da janela e aparece 1 vez perto do nó: repulsão
    texto = "agent rare agent rare agent rare agent common " + "common filler " * 200 + "rare"
    metas = _gravar(pasta, {1: [(texto, 1)]})
    todos = _calc(pasta, metas, "agent", esquerda=1, direita=1)
    assert _por_termo(todos)["common"]["ll"] < 0 and _por_termo(todos)["common"]["mi"] < 0
    padrao = colocacoes.calcular(pasta, metas, "agent", esquerda=1, direita=1, filtro=VAZIAS)
    assert padrao["colocados"] == []  # rare: O11 = 3 (ok), mas C1 = 4 < 5 (mínimo padrão do colocado)
    assert set(_por_termo(colocacoes.calcular(pasta, metas, "agent", esquerda=1, direita=1, filtro=VAZIAS, min_freq_colocado=4))) == {"rare"}
    assert "common" not in _por_termo(colocacoes.calcular(pasta, metas, "agent", esquerda=1, direita=1, filtro=VAZIAS,
                                                          min_freq=1, min_freq_colocado=1))  # só atração por padrão
    for ordem, chave in (("ll", "ll"), ("mi", "mi"), ("freq", "o11"), ("logdice", "logdice")):
        r = _calc(pasta, metas, "agent", esquerda=1, direita=1, ordem=ordem)
        valores = [c[chave] for c in r["colocados"]]
        assert valores == sorted(valores, reverse=True)
    um = _calc(pasta, metas, "agent", esquerda=1, direita=1, limite=1)
    assert len(um["colocados"]) == 1 and um["total_candidatos"] == len(todos["colocados"])


def test_desempenho_cache_da_estrutura(corpus_aleatorio):
    pasta, metas = corpus_aleatorio
    _calc(pasta, metas, "agent")
    tk = dados.carregar_tokens(pasta, metas[0]["id"])
    e = colocacoes.estrutura_do_documento(tk)
    assert colocacoes.estrutura_do_documento(tk) is e and e["n"] == sum(
        1 for n, i in zip(tk["norm"], tk["incluir"]) if i and len(n) >= 2)


# ---------- API (pipeline real sobre o corpus sintético da Frente 5) ----------

def test_api_colocacoes_confere_com_forca_bruta_e_com_os_paineis(client, projeto5, projetos_dir, ids):
    pasta = projetos_dir / projeto5
    r = _get(client, projeto5, "colocacoes", q="agent", min_freq=1, min_freq_colocado=1, limite=1000).json()
    assert r["ferramenta_equivalente"] == "AntConc/LancsBox Collocates (LL, MI)"
    assert r["nao_equivalente"] == "Voyant Collocates (só contagem)"
    assert (r["parametros"]["esquerda"], r["parametros"]["direita"]) == (5, 5)  # colocacao_janela
    metas = [{"id": i} for i in sorted(ids.values())]
    from app.services import parametros as svc_parametros
    from app.services.palavras_vazias import filtro_palavras_vazias
    filtro = filtro_palavras_vazias(svc_parametros.carregar(pasta))
    ref = forca_bruta(pasta, metas, "agent", filtro=filtro)
    assert (r["N"], r["R1"], r["ocorrencias_no"]) == (ref["N"], ref["R1"], ref["f_no"])
    for c in r["colocados"]:
        assert (c["o11"], c["c1"], c["pares"]) == (ref["o11"][c["termo"]], ref["c1"][c["termo"]], ref["pares"][c["termo"]])
    # N, C1 e frequência do nó batem com os painéis Frequências e KWIC
    freq = _get(client, projeto5, "frequencias", limite=5000).json()
    assert r["N"] == freq["tokens"]
    fmap = {x["termo"]: x["freq"] for x in freq["itens"]}
    assert all(c["c1"] == fmap[c["termo"]] for c in r["colocados"])
    assert r["ocorrencias_no"] == _get(client, projeto5, "kwic", q="agent", limit=1).json()["total"] == 60
    assert r["documentos_com_no"] == 2
    assert "agent" not in {c["termo"] for c in r["colocados"]}
    assert not {"the", "of", "and"} & {c["termo"] for c in r["colocados"]}


def test_api_escopo_parametros_e_erros(client, projeto5, ids):
    doc = _get(client, projeto5, "colocacoes", q="agent", escopo="documento", valor=ids["A"], min_freq=1).json()
    corpo = _get(client, projeto5, "colocacoes", q="agent", min_freq=1).json()
    assert doc["ocorrencias_no"] == 37 and doc["N"] < corpo["N"] and doc["parametros"]["escopo"] == "documento"
    cinz = _get(client, projeto5, "colocacoes", q="agent", escopo="grupo", valor="cinzenta", min_freq=1).json()
    assert cinz["ocorrencias_no"] == 23 and cinz["documentos"] == 2 and cinz["documentos_com_no"] == 1
    ano = _get(client, projeto5, "colocacoes", q="agent", escopo="ano", valor="2025", min_freq=1).json()
    assert ano["N"] == cinz["N"]
    assim = _get(client, projeto5, "colocacoes", q="agent", esquerda=0, direita=2, min_freq=1, min_freq_colocado=1).json()
    assert assim["colocados"] and all(set(c["posicoes"]) == {"1", "2"} for c in assim["colocados"])
    assert _get(client, projeto5, "colocacoes", q="agents", por="forma", escopo="documento", valor=ids["A"]).json()["ocorrencias_no"] == 36
    url = f"/api/projetos/{projeto5}/analises/colocacoes"
    assert client.get(url, params={"q": "agent", "esquerda": 0, "direita": 0}).status_code == 422
    assert client.get(url, params={"q": "agent", "esquerda": 21}).status_code == 422
    assert client.get(url, params={"q": "agent", "ordem": "xx"}).status_code == 422
    assert client.get(url, params={"q": "agent", "escopo": "grupo"}).status_code == 422
    # janela padrão vem dos parâmetros
    p = client.get(f"/api/projetos/{projeto5}/parametros").json()
    p.pop("hash_parametros"); p.pop("versao_parametros")
    p["colocacao_janela"] = 3
    assert client.put(f"/api/projetos/{projeto5}/parametros", json=p).status_code == 200
    assert _get(client, projeto5, "colocacoes", q="agent").json()["parametros"]["esquerda"] == 3


def test_api_csv_e_sem_pipeline(client, projeto5, projeto):
    r = client.get(f"/api/projetos/{projeto5}/analises/colocacoes.csv", params={"q": "agent", "min_freq": 1, "esquerda": 2, "direita": 1})
    assert r.status_code == 200 and r.content.startswith("﻿".encode("utf-8"))
    linhas = r.content.decode("utf-8-sig").strip().split("\r\n")
    assert linhas[0] == "posicao;colocado;o11;c1;e11;ll;p;mi;t;logdice;pares;E2;E1;D1"
    assert len(linhas) > 1 and linhas[1].startswith("1;")
    for caminho in ("colocacoes?q=a", "colocacoes.csv?q=a"):
        assert client.get(f"/api/projetos/{projeto}/analises/{caminho}").status_code == 404


def test_exportar_corpus_limpo_zip(client, projeto5, projetos_dir, ids):
    r = client.get(f"/api/projetos/{projeto5}/exportar/corpus-limpo.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nomes = set(z.namelist())
    assert {"textos/001_2026_Kim_Ingles.txt", "textos/002_2025_Silva_Portugues.txt", "textos/003_2025_Lee_Terceiro.txt",
            "stoplist.txt", "lemas.txt", "LEIAME.txt"} <= nomes
    a = z.read("textos/001_2026_Kim_Ingles.txt").decode("utf-8")
    assert "Quasar opens the second page" in a and "Zebra" not in a and "References" not in a  # corpo, texto original
    assert "\n\n" in a
    # os tokens contados do .txt (tokenizador do Raio-X, >= 2 letras) são exatamente os do corpo
    from app.services.tokenizacao import tokenizar, normalizar
    t = _tokens(projetos_dir, projeto5, ids["A"])
    esperado = [n for n, i in zip(t["norm"], t["incluir"]) if i and len(n) >= 2]
    assert [normalizar(f) for f, _, _ in tokenizar(a) if len(normalizar(f)) >= 2] == esperado
    stop = z.read("stoplist.txt").decode("utf-8").split()
    assert {"the", "et", "al"} <= set(stop) and stop == sorted(stop)
    lemas = z.read("lemas.txt").decode("utf-8")
    assert any(l.startswith("agent -> ") and "agents" in l for l in lemas.splitlines())
    assert client.get("/api/projetos/nao-existe/exportar/corpus-limpo.zip").status_code in (404, 422)
