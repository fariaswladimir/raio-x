"""5.5 N-gramas (frequência por forma/lema, faixa de documentos, clusters, KWIC por frase) e o ajuste de ruído da 4.3
(lista de palavras internas, excluir_regex, concentração, exibição pela forma original). Sem Docling."""
import os
import random
import re
import time
from collections import Counter, defaultdict

import pytest

from app.database import pasta_do_projeto
from app.services import parametros as svc_parametros
from app.services import termos_compostos as tc
from app.services.analises import dados, ngramas
from app.services.palavras_vazias import filtro_palavras_vazias, token_vazio
from app.services.tokenizacao import Lematizador, tokenizar_blocos

_SILABAS = [c + v for c in "bdfgklmnprstvz" for v in "aeiou"]


def _filler(rnd: random.Random, n: int) -> str:
    return " ".join("".join(rnd.choice(_SILABAS) for _ in range(3)) for _ in range(n))


def _md(*paginas: str) -> str:
    return "<!-- Fonte: x.pdf | Conversão: Docling -->\n" + "".join(f"\n\n<!-- página {i + 1} -->\n\n{t}" for i, t in enumerate(paginas))


T1 = "{} human oversight of agents, human oversight matters. "  # "human oversight" 2x; vírgula quebra
T2 = "{} alpha beta\n\ngamma delta; epsilon zeta {}. "  # parágrafo e ";" quebram (";" só com quebrar)
T3 = "{} human agents act. "
T4 = "{} human agent acts. "
T5 = "{} agent - based systems {}. "  # hífen entre espaços liga

# (T1, T3, T4, T2, T5) por documento; o 1º também tem T1 em "Referências" (seção excluída)
CONTAGENS = [(6, 3, 2, 4, 3), (3, 1, 2, 4, 3), (1, 0, 1, 4, 0)]


@pytest.fixture()
def corpus55(tmp_path):
    pasta = tmp_path / "corpus55"
    pasta.mkdir()
    rnd = random.Random(55)
    for i, (a, b, c, d, e) in enumerate(CONTAGENS):
        ano = 2025 if i == 0 else 2026
        p1 = "## Abstract\n\n" + "".join(T1.format(_filler(rnd, 3)) for _ in range(a)) + "".join(
            T3.format(_filler(rnd, 3)) for _ in range(b)) + "".join(T4.format(_filler(rnd, 3)) for _ in range(c)) + "".join(
            T2.format(_filler(rnd, 3), _filler(rnd, 3)) for _ in range(d)) + _filler(rnd, 3) + " zorro lefty"
        p2 = "righty zorro " + "".join(T5.format(_filler(rnd, 3), _filler(rnd, 3)) for _ in range(e)) + _filler(rnd, 230) + "."
        if i == 0:
            p2 += "\n\n## References\n\n" + "\n".join(f"- Zebra, A. ({2000 + k}). human oversight of agents, human oversight." for k in range(5))
        (pasta / f"00{i + 1}_{ano}_Autor{i}_Titulo.md").write_text(_md(p1, p2), encoding="utf-8")
    return pasta


@pytest.fixture()
def projeto55(client, corpus55):
    r = client.post("/api/projetos", json={"nome": "Projeto F55", "pasta_origem": str(corpus55)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200 and r.json()["erros"] == 0, r.text
    for d in client.get(f"/api/projetos/{slug}/documentos").json():
        grupo = "A" if d["arquivo"][:3] in ("001", "002") else "B"
        assert client.patch(f"/api/projetos/{slug}/documentos/{d['id']}", json={"grupo": grupo}).status_code == 200
    ngramas.limpar_cache()
    return slug


def _get(client, slug, rota, **params):
    r = client.get(f"/api/projetos/{slug}/analises/{rota}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _ng(client, slug, **kw):
    kw.setdefault("min_freq", 1)
    kw.setdefault("min_docs", 1)
    kw.setdefault("limite", 5000)
    return _get(client, slug, "ngramas", **kw)


def _mapa(r):
    return {i["ngrama"]: i for i in r["itens"]}


# ---------- referência por força bruta (independente de termos_compostos.sequencias) ----------

def _referencia(slug, por, n, stop, quebrar):
    pasta = pasta_do_projeto(slug)
    filtro = filtro_palavras_vazias(svc_parametros.carregar(pasta))
    total: Counter = Counter()
    por_doc: dict = defaultdict(Counter)
    for entrada in sorted((pasta / "cache" / "tokens").glob("*.json")):
        doc_id = int(entrada.stem)
        tk = dados.carregar_tokens(pasta, doc_id)
        blocos = dados.carregar_blocos(pasta, doc_id)
        N = tk["n"]
        ok = [bool(tk["incluir"][i]) and len(tk["norm"][i]) >= 2 for i in range(N)]

        def liga(i):
            if not (ok[i - 1] and ok[i]) or tk["bloco"][i] != tk["bloco"][i - 1]:
                return False
            gap = blocos[tk["bloco"][i]]["texto"][tk["fim"][i - 1]:tk["inicio"][i]]
            if gap.count("\n") >= 2:
                return False
            return True if not quebrar else re.fullmatch(r"\s*[-‐‑]?\s*", gap) is not None

        unidade = tk["norm"] if por == "forma" else tk["lema"]
        vazia = [token_vazio(tk["norm"][i], tk["lema"][i], filtro) for i in range(N)]
        for i in range(N - n + 1):
            janela = range(i, i + n)
            if not all(ok[j] for j in janela) or not all(liga(j) for j in range(i + 1, i + n)):
                continue
            if stop == "sem_bordas" and (vazia[i] or vazia[i + n - 1]):
                continue
            if stop == "sem_vazias" and any(vazia[j] for j in janela):
                continue
            g = " ".join(unidade[i:i + n])
            total[g] += 1
            por_doc[g][doc_id] += 1
    return {g: (f, len(por_doc[g]), max(por_doc[g].values())) for g, f in total.items()}


@pytest.mark.parametrize("por", ["forma", "lema"])
@pytest.mark.parametrize("stop", ["todas", "sem_bordas", "sem_vazias"])
@pytest.mark.parametrize("quebrar", [True, False])
def test_contagens_batem_com_a_forca_bruta(client, projeto55, por, stop, quebrar):
    for n_min, n_max in ((2, 2), (2, 4), (3, 6)):
        r = _ng(client, projeto55, por=por, stop=stop, quebrar=quebrar, n_min=n_min, n_max=n_max)
        assert r["total"] <= 5000
        esperado = {}
        for n in range(n_min, n_max + 1):
            esperado.update(_referencia(projeto55, por, n, stop, quebrar))
        obtido = {k: (v["freq"], v["docs"], round(v["concentracao"] * v["freq"])) for k, v in _mapa(r).items()}
        assert obtido == esperado, (por, stop, quebrar, n_min, n_max)
        assert esperado  # o corpus sintético tem n-gramas em todas as configurações


# ---------- exemplos explícitos ----------

def test_pontuacao_paragrafo_bloco_e_hifen(client, projeto55):
    m = _mapa(_ng(client, projeto55, por="forma", stop="todas", n_max=3))
    assert m["human oversight"]["freq"] == 20  # 12 + 6 + 2; as 5 ocorrências em "Referências" não contam
    assert "beta gamma" not in m and "agents human" not in m  # parágrafo e vírgula quebram
    assert "delta epsilon" not in m  # ";" quebra com o padrão
    assert "lefty righty" not in m and "lefty zorro" not in m  # fronteira de bloco (página)
    assert m["agent based"]["freq"] == 6 and m["agent based systems"]["freq"] == 6  # hífen entre espaços liga
    solto = _mapa(_ng(client, projeto55, por="forma", stop="todas", n_max=3, quebrar=False))
    assert solto["delta epsilon"]["freq"] == 12 and solto["agents human"]["freq"] == 10  # ";" e "," ignorados
    assert "beta gamma" not in solto and "lefty righty" not in solto  # parágrafo e bloco continuam quebrando


def test_opcoes_de_palavras_vazias(client, projeto55):
    todas = _mapa(_ng(client, projeto55, stop="todas", n_min=2, n_max=3))
    bordas = _mapa(_ng(client, projeto55, stop="sem_bordas", n_min=2, n_max=3))
    vazias = _mapa(_ng(client, projeto55, stop="sem_vazias", n_min=2, n_max=3))
    assert "oversight of" in todas and "of agents" in todas and "oversight of agents" in todas
    assert "oversight of" not in bordas and "of agents" not in bordas
    assert bordas["oversight of agents"]["freq"] == 10  # palavra vazia só no meio: fica em sem_bordas
    assert "oversight of agents" not in vazias and "human oversight" in vazias
    assert set(vazias) <= set(bordas) <= set(todas)


def test_forma_e_lema(client, projeto55):
    forma = _mapa(_ng(client, projeto55, por="forma", stop="sem_bordas", n_max=2))
    lema = _mapa(_ng(client, projeto55, por="lema", stop="sem_bordas", n_max=2))
    assert forma["human agents"]["freq"] == 4 and forma["human agent"]["freq"] == 5
    assert "human agents" not in lema and lema["human agent"]["freq"] == 9  # agents/agent -> agent
    assert lema["human agent"]["docs"] == 3


def test_contem_posicao_e_curinga(client, projeto55):
    base = dict(stop="todas", n_min=2, n_max=3)
    qualquer = _mapa(_ng(client, projeto55, contem="oversight", **base))
    assert qualquer and all("oversight" in g.split() for g in qualquer)
    assert {"human oversight", "oversight of", "oversight of agents", "human oversight of"} <= set(qualquer)
    inicio = _mapa(_ng(client, projeto55, contem="oversight", posicao="inicio", **base))
    assert inicio and all(g.split()[0] == "oversight" for g in inicio) and "human oversight" not in inicio
    fim = _mapa(_ng(client, projeto55, contem="oversight", posicao="fim", **base))
    assert fim and all(g.split()[-1] == "oversight" for g in fim) and "human oversight" in fim
    curinga = _mapa(_ng(client, projeto55, contem="agent*", posicao="fim", **base))
    assert "human agents" in curinga and "human agent" in curinga and "agent based" not in curinga
    alternativas = _mapa(_ng(client, projeto55, contem="alpha, zeta", **base))
    assert "alpha beta" in alternativas and "epsilon zeta" in alternativas
    # por lema: "agent" acha agents e agent
    lema = _mapa(_ng(client, projeto55, contem="agent", por="lema", posicao="fim", **base))
    assert lema["human agent"]["freq"] == 9
    sem = _ng(client, projeto55, contem="inexistente", **base)
    assert sem["total"] == 0 and sem["itens"] == []


def test_min_freq_min_docs(client, projeto55):
    base = dict(stop="todas", n_min=2, n_max=2)
    assert "agent based" in _mapa(_ng(client, projeto55, min_freq=6, **base))
    assert "agent based" not in _mapa(_ng(client, projeto55, min_freq=7, **base))
    assert "agent based" in _mapa(_ng(client, projeto55, min_docs=2, **base))  # 2 documentos
    assert "agent based" not in _mapa(_ng(client, projeto55, min_docs=3, **base))
    assert "human oversight" in _mapa(_ng(client, projeto55, min_docs=3, **base))
    assert all(i["freq"] >= 3 for i in _get(client, projeto55, "ngramas", n_max=2, limite=5000)["itens"])  # padrões: 3 e 2


def test_dispersao_faixa_e_concentracao(client, projeto55):
    i = _mapa(_ng(client, projeto55, stop="todas", n_max=2))["human oversight"]
    assert (i["freq"], i["docs"], i["concentracao"]) == (20, 3, 0.6)  # 12 de 20 ocorrências no documento principal
    assert i["por_10k"] == round(20 / _ng(client, projeto55, stop="todas", n_max=2)["tokens"] * 10000, 2)
    j = _mapa(_ng(client, projeto55, stop="todas", n_max=2))["agent based"]
    assert (j["docs"], j["concentracao"]) == (2, 0.5)


def test_escopos(client, projeto55):
    ids = {d["arquivo"][:3]: d["id"] for d in client.get(f"/api/projetos/{projeto55}/documentos").json()}
    base = dict(stop="todas", n_max=2)
    doc = _mapa(_ng(client, projeto55, escopo="documento", valor=ids["001"], **base))["human oversight"]
    assert (doc["freq"], doc["docs"], doc["concentracao"]) == (12, 1, 1.0)
    grupo = _mapa(_ng(client, projeto55, escopo="grupo", valor="A", **base))["human oversight"]
    assert (grupo["freq"], grupo["docs"], grupo["concentracao"]) == (18, 2, round(12 / 18, 3))
    ano = _mapa(_ng(client, projeto55, escopo="ano", valor="2026", **base))["human oversight"]
    assert (ano["freq"], ano["docs"]) == (8, 2)
    corpus = _ng(client, projeto55, **base)
    assert _ng(client, projeto55, escopo="grupo", valor="A", **base)["tokens"] < corpus["tokens"]
    assert client.get(f"/api/projetos/{projeto55}/analises/ngramas", params={"escopo": "grupo"}).status_code == 422
    assert client.get(f"/api/projetos/{projeto55}/analises/ngramas", params={"escopo": "documento", "valor": 9999}).status_code == 404


def test_ordem_e_paginacao(client, projeto55):
    por_freq = _ng(client, projeto55, stop="todas", n_min=2, n_max=3)["itens"]
    freqs = [i["freq"] for i in por_freq]
    assert freqs == sorted(freqs, reverse=True)
    por_docs = _ng(client, projeto55, stop="todas", n_min=2, n_max=3, ordem="docs")["itens"]
    assert [i["docs"] for i in por_docs] == sorted((i["docs"] for i in por_docs), reverse=True)
    por_n = _ng(client, projeto55, stop="todas", n_min=2, n_max=3, ordem="n")["itens"]
    assert [i["n"] for i in por_n] == sorted((i["n"] for i in por_n), reverse=True) and por_n[0]["n"] == 3
    p1 = _ng(client, projeto55, stop="todas", n_min=2, n_max=3, limite=7, offset=0)
    p2 = _ng(client, projeto55, stop="todas", n_min=2, n_max=3, limite=7, offset=7)
    assert p1["itens"] == por_freq[:7] and p2["itens"] == por_freq[7:14]
    assert p1["total"] == p2["total"] == len(por_freq) and p1["total_por_n"]["2"] + p1["total_por_n"]["3"] == p1["total"]


def test_validacao(client, projeto55):
    rota = f"/api/projetos/{projeto55}/analises/ngramas"
    assert client.get(rota, params={"n_max": 7}).status_code == 422
    assert client.get(rota, params={"n_min": 1}).status_code == 422
    assert client.get(rota, params={"n_min": 4, "n_max": 3}).status_code == 422
    assert client.get(rota, params={"stop": "x"}).status_code == 422
    assert client.get(rota, params={"por": "termo"}).status_code == 422
    assert _get(client, projeto55, "ngramas", n_min=2, n_max=6)["n_max"] == 6


def test_cache_por_escopo_e_invalidacao_por_mtime(client, projeto55):
    ngramas.limpar_cache()
    _ng(client, projeto55, n_min=2, n_max=3)
    assert len(ngramas._CACHE) == 2  # um por tamanho
    _ng(client, projeto55, n_min=3, n_max=3, contem="human")  # contem/ordem/paginação não criam entrada nova
    assert len(ngramas._CACHE) == 2
    _ng(client, projeto55, n_min=2, n_max=2, por="lema")
    assert len(ngramas._CACHE) == 3
    pasta = pasta_do_projeto(projeto55)
    arq = next((pasta / "cache" / "tokens").glob("*.json"))
    st = arq.stat()
    os.utime(arq, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))  # o pipeline foi reexecutado
    _ng(client, projeto55, n_min=2, n_max=3)
    assert len(ngramas._CACHE) == 5  # chave nova: o resultado antigo não é reutilizado


def test_desempenho_do_cache_quente(client, projeto55):
    ngramas.limpar_cache()
    _ng(client, projeto55, n_min=2, n_max=4, por="lema", stop="todas")
    t0 = time.perf_counter()
    for _ in range(5):
        _ng(client, projeto55, n_min=2, n_max=4, por="lema", stop="todas")
    assert (time.perf_counter() - t0) / 5 < 2.0


# ---------- API: CSV e KWIC por frase ----------

def test_csv_com_bom_e_ponto_e_virgula(client, projeto55):
    r = client.get(f"/api/projetos/{projeto55}/analises/ngramas.csv", params={"min_freq": 3, "n_max": 2, "stop": "todas"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "ngramas.csv" in r.headers["content-disposition"]
    assert r.content.startswith("﻿".encode("utf-8"))
    linhas = r.content.decode("utf-8-sig").splitlines()
    assert linhas[0] == "ngrama;n;frequencia;por_10_mil;documentos;concentracao"
    esperado = _get(client, projeto55, "ngramas", n_max=2, stop="todas", limite=5000)
    assert len(linhas) == 1 + len(esperado["itens"])
    assert any(l.startswith("human oversight;2;20;") for l in linhas)


def test_kwic_por_frase_acha_as_mesmas_ocorrencias_do_ngrama(client, projeto55):
    for quebrar in (True, False):
        for por, frase in (("forma", "human oversight"), ("forma", "agents human"), ("lema", "human agent"),
                           ("forma", "agent based systems"), ("forma", "delta epsilon")):
            r = _get(client, projeto55, "kwic", q=f'"{frase}"', por=por, quebrar=quebrar, janela=3)
            n = len(frase.split())
            linha = _mapa(_ng(client, projeto55, por=por, n_min=n, n_max=n, stop="todas", quebrar=quebrar)).get(frase)
            assert r["total"] == (linha["freq"] if linha else 0), (frase, por, quebrar)
            assert r["documentos_com_ocorrencias"] == (linha["docs"] if linha else 0)
    r = _get(client, projeto55, "kwic", q='"human oversight"', por="forma", janela=3)
    assert r["total"] == 20 and all(i["termo"].lower() == "human oversight" and i["corpo"] for i in r["itens"])
    assert all(i["pagina"] == 1 for i in r["itens"]) and r["formas"] == [{"forma": "human oversight", "freq": 20}]
    assert r["itens"][0]["esquerda"] and r["itens"][0]["direita"]
    # curinga por palavra, paginação e ordenação pela palavra à direita
    c = _get(client, projeto55, "kwic", q='"human agent*"', por="forma", ordem="direita", limit=3)
    assert c["total"] == 9 and len(c["itens"]) == 3
    # sem aspas continua sendo consulta por palavra
    assert _get(client, projeto55, "kwic", q="oversight", por="forma")["total"] == 20
    # frase com uma palavra só em aspas = palavra
    assert _get(client, projeto55, "kwic", q='"oversight"', por="forma")["total"] == 20
    assert client.get(f"/api/projetos/{projeto55}/analises/kwic", params={"q": '"human oversight"', "por": "termo"}).status_code in (409, 422)
    csv = client.get(f"/api/projetos/{projeto55}/analises/kwic.csv", params={"q": '"human oversight"', "por": "forma"})
    assert csv.status_code == 200 and len(csv.content.decode("utf-8-sig").splitlines()) == 21


# ---------- 4.3: redução de ruído ----------

VAZIAS = frozenset({"the", "on", "of", "to", "and", "in", "with", "that", "use"})


def _tokens(*textos):
    blocos = [{"texto": t, "pagina": i + 1, "secao": "corpo", "incluir": True} for i, t in enumerate(textos)]
    return tokenizar_blocos(blocos, Lematizador("en", ativa=False)), blocos


def _docs(*textos_por_doc):
    docs = []
    for t in textos_por_doc:
        tk, blocos = _tokens(t)
        docs.append({"tokens": tk, "blocos": blocos})
    return docs


def _termos(docs, filtro=frozenset(), **kw):
    cfg = tc.configuracao({"termos_compostos": {"min_freq": 5, "min_docs": 2, **kw}})
    return {c["termo"]: c for c in tc.detectar(docs, filtro, cfg)}


def _espalhado(rnd, frase, vezes=(6, 6)):
    return [" ".join(f"{_filler(rnd, 8)} {frase}. " for _ in range(v)) for v in vezes]


def test_ruido_a_palavra_interna_so_da_lista_permitida():
    rnd = random.Random(21)
    docs = _docs(*[" ".join(_espalhado(rnd, "cost of capital", (3,)) + _espalhado(rnd, "run that tool", (3,))
                            + _espalhado(rnd, "number and ai", (3,))) for _ in range(2)])
    t = _termos(docs, filtro=VAZIAS)
    assert "cost of capital" in t  # "of" está na lista padrão
    assert "run that tool" not in t and "number and ai" not in t  # "that"/"and" não estão
    assert "cost of capital" not in _termos(docs, filtro=VAZIAS, internas_permitidas=[])
    assert "run that tool" in _termos(docs, filtro=VAZIAS, internas_permitidas=["That"])  # configurável (normalizada)
    # padrão da lista: of on for in to de da do
    assert tc.configuracao({})["internas_permitidas"] == ["of", "on", "for", "in", "to", "de", "da", "do"]


def test_ruido_b_regex_de_residuo_de_tabela_e_tokens_curtos():
    rnd = random.Random(22)
    docs = _docs(*[" ".join(_espalhado(rnd, "fe yes yes", (4,)) + _espalhado(rnd, "ab cd ef", (4,))
                            + _espalhado(rnd, "alpha beta", (4,))) for _ in range(2)])
    t = _termos(docs)
    assert "alpha beta" in t
    assert "fe yes yes" not in t and "yes yes" not in t and "fe yes" not in t  # repetida em sequência; o recorte "fe yes" é arrastado
    assert not [x for x in t if all(len(p) <= 2 for p in x.split())]  # só palavras de 1-2 letras
    liberado = _termos(docs, excluir_regex=[])
    assert "fe yes yes" in liberado and "ab cd ef" in liberado  # sem regex, só os "todos iguais" caem
    outro = _termos(docs, excluir_regex=[r"^alpha"])
    assert "alpha beta" not in outro


def test_ruido_b_concentracao_num_unico_documento():
    rnd = random.Random(23)
    docs = _docs(" ".join(_espalhado(rnd, "alpha beta", (9,)) + _espalhado(rnd, "gamma delta", (5,))),
                 " ".join(_espalhado(rnd, "alpha beta", (1,)) + _espalhado(rnd, "gamma delta", (5,))))
    t = _termos(docs, min_freq=5)
    assert "gamma delta" in t  # 50% em cada documento
    assert "alpha beta" not in t  # 9 de 10 (90%) num só documento
    assert "alpha beta" in _termos(docs, min_freq=5, max_concentracao=0.95)
    assert "alpha beta" in _termos(docs, min_freq=5, max_concentracao=1.0)  # 100%: só cai o que está todo num documento
    um = _docs(" ".join(_espalhado(rnd, "alpha beta", (9,))))
    assert "alpha beta" in _termos(um, min_freq=5, min_docs=1)  # min_docs = 1: o usuário aceitou um documento só
    assert tc.configuracao({})["max_concentracao"] == 0.8


def test_ruido_c_exibicao_pela_forma_original_mais_frequente():
    tk, blocos = _tokens("The United States leads. The united states trail. United States again. Some United States.")
    ocorrencias = tc.marcar(tk, blocos, {"united states"})
    formas = tc.formas_do_termo(tk, ocorrencias)
    assert formas["united states"] == {"United States": 3, "united states": 1}
    assert tc.melhor_exibicao(formas["united states"], "united states") == "United States"
    assert tc.melhor_exibicao(None, "unite state") == "unite state"
    assert tc.melhor_exibicao(Counter({"B c": 1, "A c": 1}), "x") == "A c"  # empate: determinístico


def test_ruido_c_etapa_grava_exibicao_e_api_devolve(client, tmp_path):
    pasta = tmp_path / "c55"
    pasta.mkdir()
    rnd = random.Random(24)
    for i in range(3):
        corpo = _filler(rnd, 230) + ". " + "".join(f"{_filler(rnd, 3)}, agentic AI, to automate. {_filler(rnd, 4)}, human capital, {_filler(rnd, 3)}. " for _ in range(5))
        (pasta / f"00{i + 1}_2026_Autor{i}_Titulo.md").write_text(_md("## Abstract\n\n" + corpo), encoding="utf-8")
    slug = client.post("/api/projetos", json={"nome": "C55", "pasta_origem": str(pasta)}).json()["slug"]
    p = client.get(f"/api/projetos/{slug}/parametros").json()
    for k in ("versao_parametros", "hash_parametros"):
        p.pop(k)
    p["termos_compostos"].update(min_freq=5, min_docs=2)
    assert client.put(f"/api/projetos/{slug}/parametros", json=p).status_code == 200
    assert client.post(f"/api/projetos/{slug}/executar?sincrono=1").json()["erros"] == 0
    itens = {i["termo"]: i for i in _get(client, slug, "termos-compostos")["itens"]}
    assert itens["agentic ai"]["exibicao"] == "agentic AI"  # chave = lema, exibição = forma original mais frequente
    assert all(i["exibicao"] for i in itens.values())
    assert p["termos_compostos"]["max_concentracao"] == 0.8 and "excluir_regex" in p["termos_compostos"]
