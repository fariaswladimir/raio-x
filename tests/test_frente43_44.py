"""4.3 Termos compostos e 4.4 Segmentos de ~40 palavras: funções puras, etapas, cache e API. Sem Docling."""
import json
import random

import pytest

from app.database import pasta_do_projeto
from app.services import segmentacao
from app.services import termos_compostos as tc
from app.services.analises import dados
from app.services.analises.colocacoes import log_likelihood
from app.services.tokenizacao import Lematizador, tokenizar_blocos

VAZIAS = frozenset({"the", "on", "of", "to", "and", "in", "with"})
_SILABAS = [c + v for c in "bdfgklmnprstvz" for v in "aeiou"]


def _filler(rnd: random.Random, n: int) -> str:
    return " ".join("".join(rnd.choice(_SILABAS) for _ in range(3)) for _ in range(n))


def _tokens(*textos: str, incluir: bool | list[bool] = True) -> tuple[dict, list[dict]]:
    """Um documento: arrays de tokens (sem lematização: lema = norm) e blocos, um bloco por texto."""
    flags = incluir if isinstance(incluir, list) else [incluir] * len(textos)
    blocos = [{"texto": t, "pagina": i + 1, "secao": "corpo", "incluir": f} for i, (t, f) in enumerate(zip(textos, flags))]
    tk = tokenizar_blocos(blocos, Lematizador("en", ativa=False))
    return tk, blocos


def _docs(*textos_por_doc) -> list[dict]:
    docs = []
    for t in textos_por_doc:
        tk, blocos = _tokens(*([t] if isinstance(t, str) else t))
        docs.append({"tokens": tk, "blocos": blocos})
    return docs


def _cfg(**kw) -> dict:
    return tc.configuracao({"termos_compostos": {"min_freq": 5, "min_docs": 1, **kw}})


def _termos(docs, filtro=frozenset(), **kw) -> dict[str, dict]:
    return {c["termo"]: c for c in tc.detectar(docs, filtro, _cfg(**kw))}


# ---------- 4.3: detecção ----------

def test_pontuacao_quebra_e_hifen_e_quebra_de_linha_ligam():
    rnd = random.Random(1)
    partes = []
    for _ in range(12):
        partes.append(f"{_filler(rnd, 8)} alpha beta, gamma. delta. epsilon {_filler(rnd, 8)}")  # vírgula e ponto quebram
        partes.append(f"{_filler(rnd, 8)} zeta - eta {_filler(rnd, 8)} kappa\nlambda {_filler(rnd, 8)}")  # hífen e \n ligam
        partes.append(f"{_filler(rnd, 8)} theta — iota {_filler(rnd, 8)} mu\n\nnu {_filler(rnd, 8)}")  # travessão e §
        partes.append(f"{_filler(rnd, 8)} omicron (pi) {_filler(rnd, 8)}")
    t = _termos(_docs(" ".join(partes)))
    assert "alpha beta" in t and "zeta eta" in t and "kappa lambda" in t
    for ruim in ("beta gamma", "gamma delta", "delta epsilon", "theta iota", "mu nu", "omicron pi"):
        assert ruim not in t, ruim
    # alpha beta, gamma: nada atravessa a vírgula, nem como trigrama
    assert "alpha beta gamma" not in t


def test_hifen_quebrando_linha_e_bloco_diferente_nao_ligam():
    rnd = random.Random(2)
    # "multi-\nagent": o hífen interno vira dois tokens ligados; blocos distintos (páginas) nunca se ligam
    docs = _docs(tuple(f"{_filler(rnd, 8)} multi-\nagent {_filler(rnd, 8)} fim" for _ in range(12)))
    docs2 = _docs(tuple(f"{_filler(rnd, 8)} um\n\n" if i % 2 else f"{_filler(rnd, 8)} um" for i in range(12)))
    assert "multi agent" in _termos(docs)
    # o último token de um bloco e o primeiro do seguinte ("um" + filler) não formam termo
    assert not [x for x in _termos(docs2) if x.startswith("um ")]
    docs3 = _docs(tuple("sigma" if i % 2 == 0 else "tau" for i in range(24)))  # 1 palavra por bloco
    assert _termos(docs3) == {}


def test_palavras_vazias_nas_bordas_e_no_meio():
    rnd = random.Random(3)
    partes = [f"{_filler(rnd, 8)} return on investment {_filler(rnd, 8)} the alpha beta of {_filler(rnd, 8)} "
              f"big return on investment {_filler(rnd, 8)}" for _ in range(12)]
    t = _termos(_docs(" ".join(partes)), filtro=VAZIAS, n_max=4)
    assert "return on investment" in t  # vazia no meio, só em trigramas
    assert "big return on investment" not in t  # 4-grama com vazia no meio
    assert "alpha beta" in t
    for ruim in ("the alpha", "beta of", "the alpha beta", "alpha beta of", "return on", "on investment"):
        assert ruim not in t, ruim


def test_todos_iguais_nao_e_candidato():
    rnd = random.Random(4)
    t = _termos(_docs(" ".join(f"{_filler(rnd, 8)} ha ha {_filler(rnd, 8)}" for _ in range(12))))
    assert "ha ha" not in t


def test_min_freq_e_min_docs():
    rnd = random.Random(5)
    corpo = " ".join(f"{_filler(rnd, 8)} alpha beta {_filler(rnd, 8)}" for _ in range(6))
    docs = _docs(corpo, _filler(rnd, 30))  # 6 ocorrências, todas em 1 documento
    assert "alpha beta" in _termos(docs, min_freq=6, min_docs=1)
    assert "alpha beta" not in _termos(docs, min_freq=7, min_docs=1)
    assert "alpha beta" not in _termos(docs, min_freq=1, min_docs=2)
    docs = _docs(corpo, " ".join(f"{_filler(rnd, 8)} alpha beta {_filler(rnd, 8)}" for _ in range(2)))
    achado = _termos(docs, min_freq=8, min_docs=2)["alpha beta"]
    assert (achado["freq"], achado["docs"]) == (8, 2)


def test_log_likelihood_ordena_e_trigrama_usa_o_minimo():
    rnd = random.Random(6)
    forte = " ".join(f"{_filler(rnd, 6)} alpha beta. " for _ in range(20))  # sempre juntas
    fraca = " ".join(f"{_filler(rnd, 6)} gamma delta. " for _ in range(20))
    soltas = " ".join(f"{_filler(rnd, 4)} gamma. {_filler(rnd, 3)} delta. " for _ in range(100))
    t = _termos(_docs(forte + fraca + soltas))
    assert t["alpha beta"]["score"] > t["gamma delta"]["score"] > 0
    ordem = [c["termo"] for c in tc.detectar(_docs(forte + fraca + soltas), frozenset(), _cfg())]
    assert ordem.index("alpha beta") < ordem.index("gamma delta")

    # trigrama: mínimo do G² dos dois bigramas internos (conferido com contagens independentes)
    rnd = random.Random(7)
    corpo = " ".join(f"{_filler(rnd, 6)} alpha beta. " for _ in range(20)) \
        + " ".join(f"{_filler(rnd, 6)} alpha beta gamma. " for _ in range(10)) \
        + " ".join(f"{_filler(rnd, 6)} beta gamma. " for _ in range(15))
    docs = _docs(corpo)
    t = _termos(docs)
    assert t["alpha beta gamma"]["freq"] == 10
    assert t["alpha beta gamma"]["score"] == pytest.approx(min(t["alpha beta"]["score"], t["beta gamma"]["score"]))
    tk = docs[0]["tokens"]
    pares = {}
    for a, b in tc.sequencias(tk, docs[0]["blocos"]):
        for k in range(a, b - 1):
            pares[(tk["lema"][k], tk["lema"][k + 1])] = pares.get((tk["lema"][k], tk["lema"][k + 1]), 0) + 1
    total = sum(pares.values())
    r1 = sum(c for (x, _), c in pares.items() if x == "alpha")
    c1 = sum(c for (_, y), c in pares.items() if y == "beta")
    assert t["alpha beta"]["score"] == pytest.approx(log_likelihood(pares[("alpha", "beta")], r1, c1, total))


def test_termos_aninhados_so_o_mais_longo_quando_cobre_quase_tudo():
    rnd = random.Random(8)
    corpo = " ".join(f"{_filler(rnd, 8)} large language model. " for _ in range(20))
    t = _termos(_docs(corpo))
    assert "large language model" in t
    assert "large language" not in t and "language model" not in t  # sempre dentro do trigrama


def test_lista_bloqueados_e_maximo():
    rnd = random.Random(9)
    corpo = " ".join(f"{_filler(rnd, 8)} alpha beta. gamma delta. epsilon zeta." for _ in range(12))
    docs = _docs(corpo + " rare words here. four word list term.")
    cfg = _cfg(bloqueados=["Alpha  Beta"], lista=["rare words", "four word list term"], max_automaticos=1)
    assert cfg["bloqueados"] == ["alpha beta"]
    auto = tc.detectar(docs, frozenset(), cfg)
    assert len(auto) == 1 and auto[0]["termo"] != "alpha beta"  # bloqueado sai antes do corte
    extras = tc.contar_lista(docs, cfg["lista"])
    assert extras["rare words"] == {"freq": 1, "docs": 1} and extras["four word list term"]["freq"] == 1
    itens = {c["termo"]: c for c in tc.montar_lista(auto, extras, cfg)}
    assert itens["rare words"]["origem"] == "lista" and itens["rare words"]["score"] is None
    assert itens[auto[0]["termo"]]["origem"] == "automatico" and "alpha beta" not in itens
    # a lista vence o bloqueio automático? não: bloqueado sai mesmo se estiver na lista
    cfg2 = _cfg(bloqueados=["rare words"], lista=["rare words"])
    assert "rare words" not in {c["termo"] for c in tc.montar_lista([], extras, cfg2)}
    assert tc.detectar(docs, frozenset(), _cfg(automaticos=False)) == []


def test_marcacao_longest_match_da_esquerda_para_a_direita():
    tk, blocos = _tokens("large language model. language model. large language. large. language model large language")
    termos = {"large language", "large language model", "language model"}
    ocorrencias = tc.marcar(tk, blocos, termos)
    assert ocorrencias == [[0, 3, "large language model"], [3, 2, "language model"], [5, 2, "large language"],
                           [8, 2, "language model"], [10, 2, "large language"]]  # "large" sozinho (7) não casa
    termo = tc.array_termo(tk, ocorrencias)
    assert termo[0] == "large language model" and termo[1] == termo[2] == ""
    assert termo[3] == "language model" and termo[4] == ""
    assert termo[7] == "large" and termo[8] == "language model" and termo[9] == "" and termo[10] == "large language"
    assert tc.fim_do_termo(termo, 0) == 2 and tc.fim_do_termo(termo, 7) == 7
    assert tc.marcar(tk, blocos, set()) == []


def test_marcacao_nao_atravessa_pontuacao_nem_bloco():
    tk, blocos = _tokens("large. language model", "large", "language model")
    assert tc.marcar(tk, blocos, {"large language"}) == []
    assert tc.marcar(tk, blocos, {"language model"}) == [[1, 2, "language model"], [4, 2, "language model"]]


def test_contagens_do_documento_e_visao_por_termo():
    tk, blocos = _tokens("agentic ai helps. agentic systems. ai works")
    oc = tc.marcar(tk, blocos, {"agentic ai"})
    cont = tc.contagens_do_documento(tk, oc)
    assert cont["compostos"] == {"agentic ai": 1}
    assert sorted(cont["cobertos"]) == [["agentic", "agentic", 1], ["ai", "ai", 1]]
    voc = {"documentos": {"1": {"arquivo": "a", "tokens": 7, "lema": {}, "norma": {}, "pares": [
        ["agentic", "agentic", 2], ["ai", "ai", 2], ["helps", "helps", 1]]}}}
    visao = tc.visao_vocabulario(voc, {"documentos": {"1": cont}})
    d = visao["documentos"]["1"]
    assert d["lema"] == {"agentic": 1, "ai": 1, "helps": 1, "agentic ai": 1} and d["tokens"] == 7
    # sem entrada para o documento: contagem por lema inalterada
    assert tc.visao_vocabulario(voc, {"documentos": {}})["documentos"]["1"]["lema"]["agentic"] == 2


# ---------- 4.4: segmentos (funções puras) ----------

def _palavras(n: int, inicio: int = 1) -> list[str]:
    return [f"w{i}" for i in range(inicio, inicio + n)]


def _seg(texto, alvo=40, **kw):
    tk, blocos = _tokens(*([texto] if isinstance(texto, str) else texto), **kw)
    return tk, blocos, segmentacao.segmentar(tk, blocos, alvo)


def test_segmentos_perto_do_alvo_cortando_em_fim_de_frase():
    texto = " ".join(" ".join(f"S{i}w{j}" for j in range(12)) + "." for i in range(10))  # 10 frases de 12 palavras
    tk, _, s = _seg(texto)
    tams = [x["n_tokens"] for x in s["segmentos"]]
    assert tams == [36, 36, 48] and sum(tams) == tk["n"] == 120  # o resto (48 <= 1,25·40) fecha o bloco de uma vez
    assert all(x["corte"] == "forte" for x in s["segmentos"][:-1]) and s["segmentos"][-1]["corte"] == "fim_bloco"
    assert all(x["texto"].endswith(".") for x in s["segmentos"])


def _com_pontuacao(n: int, marcas: dict[int, str]) -> str:
    """n palavras 'Wk'; ``marcas[k]`` é a pontuação logo depois da palavra k (1-based)."""
    return " ".join(f"W{k}{marcas.get(k, '')}" for k in range(1, n + 1))


def test_prioridade_da_pontuacao():
    # ponto (forte) em 45 vence vírgula em 40 e ';' em 35, desde que a janela [30, 50] os contenha
    tk, _, s = _seg(_com_pontuacao(100, {35: ";", 40: ",", 45: "."}))
    assert s["segmentos"][0]["n_tokens"] == 45 and s["segmentos"][0]["corte"] == "forte"
    # ';' vence ','
    _, _, s = _seg(_com_pontuacao(100, {33: ";", 40: ","}))
    assert s["segmentos"][0]["n_tokens"] == 33 and s["segmentos"][0]["corte"] == "media"
    # só vírgulas: a mais perto do alvo
    _, _, s = _seg(_com_pontuacao(100, {32: ",", 42: ",", 48: ","}))
    assert s["segmentos"][0]["n_tokens"] == 42 and s["segmentos"][0]["corte"] == "fraca"
    # empate de prioridade e de distância: o menor
    _, _, s = _seg(_com_pontuacao(100, {37: ",", 43: ","}))
    assert s["segmentos"][0]["n_tokens"] == 37
    # ponto seguido de minúscula (et al. em, Fig. 3) não é fim de frase
    texto = _com_pontuacao(100, {35: ","}).replace("W40 ", "W40. ").replace("W41", "w41")
    _, _, s = _seg(texto)
    assert s["segmentos"][0]["n_tokens"] == 35 and s["segmentos"][0]["corte"] == "fraca"


def test_sem_pontuacao_estende_ate_1_5_e_corta_duro():
    _, _, s = _seg(_com_pontuacao(130, {}))
    assert [x["n_tokens"] for x in s["segmentos"]] == [60, 60, 10]
    assert [x["corte"] for x in s["segmentos"]] == ["duro", "duro", "fim_bloco"]
    # pontuação só depois da janela principal (55): usada antes do corte duro
    _, _, s = _seg(_com_pontuacao(120, {55: "!"}))
    assert s["segmentos"][0]["n_tokens"] == 55 and s["segmentos"][0]["corte"] == "forte"


def test_cauda_pequena_e_fundida_com_o_segmento_anterior_do_mesmo_bloco():
    _, _, s = _seg(_com_pontuacao(125, {}))  # 60 + 60 + 5: a cauda (< 25% de 40) volta ao anterior
    assert [x["n_tokens"] for x in s["segmentos"]] == [60, 65]
    assert s["segmentos"][-1]["fim_token"] == 124 and s["segmentos"][-1]["corte"] == "fim_bloco"
    # bloco curto sozinho (sem anterior no bloco) fica como segmento pequeno
    tk, _, s = _seg([" ".join(_palavras(60)), "Titulo curto aqui"])
    assert [x["n_tokens"] for x in s["segmentos"]] == [60, 3]


def test_segmento_nunca_atravessa_bloco_e_tem_pagina_e_texto():
    tk, blocos, s = _seg([" ".join(_palavras(20)) + ".", "Outra   pagina\ncom   espacos."])
    assert [x["n_tokens"] for x in s["segmentos"]] == [20, 4]
    a, b = s["segmentos"]
    assert (a["pagina"], b["pagina"]) == (1, 2) and (a["bloco"], b["bloco"]) == (0, 1)
    assert b["texto"] == "Outra pagina com espacos."  # espaços colapsados, com a pontuação final
    assert a["texto"].endswith("w20.") and (a["inicio_token"], a["fim_token"], b["inicio_token"]) == (0, 19, 20)
    assert s["seg"] == [0] * 20 + [1] * 4


def test_seg_menos_um_para_tokens_excluidos():
    tk, _, s = _seg([" ".join(_palavras(10)), "Zebra et al referencias", " ".join(_palavras(10, 50))],
                    incluir=[True, False, True])
    assert s["seg"] == [0] * 10 + [-1] * 4 + [1] * 10
    assert [x["n_tokens"] for x in s["segmentos"]] == [10, 10]
    assert all("Zebra" not in x["texto"] for x in s["segmentos"])


def test_alvo_configuravel():
    _, _, s = _seg(_com_pontuacao(60, {20: ".", 40: "."}), alvo=20)
    assert [x["n_tokens"] for x in s["segmentos"]][:2] == [20, 20]


# ---------- pipeline: corpus sintético ----------

# Os termos ficam entre vírgulas (contextos variados): senão o trigrama com a vizinhança fixa cobriria o bigrama.
S1 = "{}, agentic AI, to automate. "
S2 = "{}, large language models, {}, and human capital, {}. "
S3 = "Entrepreneurs measure outcomes with surveys, and the teams review them carefully. "


def _md(*paginas: str) -> str:
    return "<!-- Fonte: x.pdf | Conversão: Docling -->\n" + "".join(f"\n\n<!-- página {i + 1} -->\n\n{t}" for i, t in enumerate(paginas))


@pytest.fixture()
def corpus43(tmp_path):
    pasta = tmp_path / "corpus43"
    pasta.mkdir()
    rnd = random.Random(11)
    for i in range(4):
        com_s2 = "".join(S2.format(*(_filler(rnd, 2) for _ in range(3))) for _ in range(6)) if i < 2 else ""
        corpo1 = "".join(S1.format(_filler(rnd, 3).capitalize()) + _filler(rnd, 9).capitalize() + ". " for _ in range(6))
        (pasta / f"00{i + 1}_2026_Autor{i}_Titulo.md").write_text(_md(
            "## Abstract\n\n" + corpo1 + com_s2,
            "## Method\n\n" + (S3 + _filler(rnd, 9).capitalize() + ". ") * 12 + "\n\n## References\n\n"
            + "\n".join(f"- Zebra, A. et al. ({2000 + k}). Agentic AI studies. arXiv:2512.0000{k}." for k in range(8))),
            encoding="utf-8")
    return pasta


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200 and r.json()["erros"] == 0, r.text
    return {e["etapa"]: e for e in r.json()["etapas"]}


def _definir_parametros(client, slug, **tcomp):
    p = client.get(f"/api/projetos/{slug}/parametros").json()
    for k in ("versao_parametros", "hash_parametros"):
        p.pop(k)
    p["termos_compostos"].update(tcomp)
    r = client.put(f"/api/projetos/{slug}/parametros", json=p)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def projeto43(client, corpus43):
    r = client.post("/api/projetos", json={"nome": "Projeto F43", "pasta_origem": str(corpus43)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    _definir_parametros(client, slug, min_freq=5, min_docs=2)
    etapas = _executar(client, slug)
    assert etapas["termos_compostos"]["ok"] == 1 and etapas["segmentos"]["ok"] == 4
    for d in client.get(f"/api/projetos/{slug}/documentos").json():
        grupo = "A" if d["arquivo"][:3] in ("001", "002") else "B"
        assert client.patch(f"/api/projetos/{slug}/documentos/{d['id']}", json={"grupo": grupo}).status_code == 200
    _executar(client, slug)  # o descritivo/comparativo veem os grupos editados
    return slug


def _get(client, slug, rota, **params):
    r = client.get(f"/api/projetos/{slug}/analises/{rota}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _freq(client, slug, por, termo):
    itens = _get(client, slug, "frequencias", por=por, limite=5000, vazias="manter")["itens"]
    return next((i["freq"] for i in itens if i["termo"] == termo), 0)


def test_etapa_grava_lista_com_freq_docs_score_e_origem(client, projeto43):
    r = _get(client, projeto43, "termos-compostos")
    itens = {c["termo"]: c for c in r["itens"]}
    assert {"agentic ai", "large language model", "human capital"} <= set(itens)
    a = itens["agentic ai"]
    assert a["origem"] == "automatico" and a["freq"] == 24 and a["docs"] == 4 and a["score"] > 0 and a["aplicados"] == 24
    assert r["desatualizado"] is False and r["lista"] == [] and r["bloqueados"] == []
    pasta = pasta_do_projeto(projeto43)
    assert (pasta / "cache" / "termos_compostos.json").is_file()
    assert len(list((pasta / "cache" / "termos").glob("*.json"))) == 4
    # o arquivo de tokens não é reescrito: não tem `termo` nem `seg`
    tk = json.loads(next((pasta / "cache" / "tokens").glob("*.json")).read_text(encoding="utf-8"))
    assert "termo" not in tk and "seg" not in tk
    assert [c["termo"] for c in _get(client, projeto43, "termos-compostos", origem="lista")["itens"]] == []


def test_por_termo_em_frequencias_tendencias_kwic_colocacoes_keyness(client, projeto43):
    # agentic AI aparece 24x; por termo conta 1 por trecho e as palavras cobertas somem das contagens soltas
    assert _freq(client, projeto43, "termo", "agentic ai") == 24
    assert _freq(client, projeto43, "termo", "agentic") == 0 and _freq(client, projeto43, "lema", "agentic") >= 24
    r = _get(client, projeto43, "frequencias", por="termo", filtro="agentic*")
    assert r["por"] == "termo" and r["itens"][0]["termo"] == "agentic ai"
    t = _get(client, projeto43, "tendencias", termos="agentic ai, human capital", por="termo", agrupar="grupo", metrica="bruta")
    assert t["por"] == "termo" and [s["brutos"] for s in t["series"]] == [[12, 12], [12, 0]]

    k = _get(client, projeto43, "kwic", q="agentic ai", por="termo", janela=3)
    assert k["total"] == 24 and k["por"] == "termo"
    linha = k["itens"][0]
    assert linha["termo"] == "agentic AI"  # o trecho inteiro, com a caixa original
    assert linha["esquerda"].endswith(",") and linha["direita"].startswith(", to automate")
    assert "agentic" not in linha["esquerda"] and not linha["direita"].startswith("AI")
    ordenado = _get(client, projeto43, "kwic", q="agentic ai", por="termo", janela=3, ordem="direita")
    assert ordenado["total"] == 24

    c = _get(client, projeto43, "colocacoes", q="agentic ai", por="termo", esquerda=2, direita=3, min_freq=3,
             min_freq_colocado=3, vazias="manter")
    termos = {x["termo"] for x in c["colocados"]}
    assert "automate" in termos and "agentic" not in termos and "ai" not in termos
    assert c["no"]["formas"][0] == {"termo": "agentic ai", "freq": 24}
    c2 = _get(client, projeto43, "colocacoes", q="automate", por="termo", esquerda=3, direita=1, min_freq=3,
              min_freq_colocado=3, vazias="manter")
    assert "agentic ai" in {x["termo"] for x in c2["colocados"]}

    kn = _get(client, projeto43, "keyness", por="termo", a="A", b="B", min_freq=5, min_docs_a=2, min_docs_b=1)
    assert kn["por"] == "termo" and "human capital" in {x["termo"] for x in kn["positivas"]}


def test_por_lema_e_por_forma_nao_mudam_com_termos_compostos(client, projeto43):
    """Regressão: com a etapa ligada ou desligada, lema/forma dão exatamente os mesmos resultados."""
    def instantaneo():
        saida = {}
        for por in ("lema", "forma"):
            saida[por] = (
                _get(client, projeto43, "frequencias", por=por, limite=5000),
                _get(client, projeto43, "frequencias", por=por, limite=5000, vazias="manter"),
                _get(client, projeto43, "tendencias", termos="agent*, ai", por=por, agrupar="grupo"),
                _get(client, projeto43, "kwic", q="ai", por=por, janela=4),
                _get(client, projeto43, "colocacoes", q="ai", por=por, min_freq=2, min_freq_colocado=2),
                _get(client, projeto43, "keyness", por=por, a="A", b="B", min_freq=3, min_docs_a=1, min_docs_b=1),
            )
        return saida

    antes = instantaneo()
    _definir_parametros(client, projeto43, ativa=False)
    etapas = _executar(client, projeto43)
    assert etapas["termos_compostos"]["ok"] == 1 and etapas["linguistica"]["ok"] == 0
    assert _get(client, projeto43, "termos-compostos")["itens"] == []
    assert _freq(client, projeto43, "termo", "agentic ai") == 0  # desligado: por termo = por lema
    assert _freq(client, projeto43, "termo", "agentic") == _freq(client, projeto43, "lema", "agentic")
    assert instantaneo() == antes


def test_patch_bloquear_e_aceitar_persistem_versionam_e_exigem_reexecucao(client, projeto43):
    pasta = pasta_do_projeto(projeto43)
    v0 = client.get(f"/api/projetos/{projeto43}/parametros").json()["versao_parametros"]
    r = client.patch(f"/api/projetos/{projeto43}/analises/termos-compostos",
                     json={"bloquear": ["Agentic  AI"], "aceitar": ["human capital"]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["bloqueados"] == ["agentic ai"] and corpo["lista"] == ["human capital"]
    assert corpo["versao_parametros"] == v0 + 1 and corpo["reexecutar"] is True
    assert (pasta / "parametros_historico" / f"parametros_v{v0}.json").is_file()
    salvo = json.loads((pasta / "parametros.json").read_text(encoding="utf-8"))["termos_compostos"]
    assert salvo["lista"] == ["human capital"] and salvo["bloqueados"] == ["agentic ai"]
    assert salvo["min_freq"] == 5  # o resto da configuração fica

    r = _get(client, projeto43, "termos-compostos")
    assert r["desatualizado"] is True and r["bloqueados"] == ["agentic ai"]
    etapas = _executar(client, projeto43)
    assert etapas["termos_compostos"]["ok"] == 1 and etapas["segmentos"]["pulado"] == 4  # só a etapa de termos refaz
    r = _get(client, projeto43, "termos-compostos")
    itens = {c["termo"]: c for c in r["itens"]}
    assert r["desatualizado"] is False and "agentic ai" not in itens and itens["human capital"]["origem"] == "lista"
    assert _freq(client, projeto43, "termo", "agentic ai") == 0 and _freq(client, projeto43, "termo", "human capital") == 12
    # repetir a mesma edição não muda nada (sem nova versão)
    r = client.patch(f"/api/projetos/{projeto43}/analises/termos-compostos", json={"bloquear": ["agentic ai"]})
    assert r.json()["versao_parametros"] == v0 + 1
    # desbloquear e tirar da lista
    r = client.patch(f"/api/projetos/{projeto43}/analises/termos-compostos",
                     json={"desbloquear": ["agentic ai"], "remover_da_lista": ["human capital"]})
    assert r.json()["lista"] == [] and r.json()["bloqueados"] == [] and r.json()["versao_parametros"] == v0 + 2
    _executar(client, projeto43)
    assert _freq(client, projeto43, "termo", "agentic ai") == 24
    itens = {c["termo"]: c for c in _get(client, projeto43, "termos-compostos")["itens"]}
    assert itens["human capital"]["origem"] == "automatico"


def test_patch_valida_termo_de_uma_palavra(client, projeto43):
    r = client.patch(f"/api/projetos/{projeto43}/analises/termos-compostos", json={"aceitar": ["sozinha"]})
    assert r.status_code == 422


def test_cache_invalida_quando_a_lista_muda_e_o_lru_do_dados_acompanha(client, projeto43):
    pasta = pasta_do_projeto(projeto43)
    doc_id = int(next((pasta / "cache" / "termos").glob("*.json")).stem)
    tk = dados.carregar_tokens(pasta, doc_id, termos=True)
    assert "agentic ai" in tk["termo"] and "termo" not in dados.carregar_tokens(pasta, doc_id)
    assert dados.carregar_tokens(pasta, doc_id, termos=True) is tk  # cache LRU
    assert len(tk["termo"]) == tk["n"] and tk["termo"].count("agentic ai") == 6 and "" in tk["termo"]
    # segunda execução sem mudanças: tudo em cache
    etapas = _executar(client, projeto43)
    assert etapas["termos_compostos"]["pulado"] == 1 and etapas["segmentos"]["pulado"] == 4
    # mudar a lista e reexecutar troca o arquivo lateral: o LRU não devolve o array antigo
    client.patch(f"/api/projetos/{projeto43}/analises/termos-compostos", json={"bloquear": ["agentic ai"]})
    _executar(client, projeto43)
    novo = dados.carregar_tokens(pasta, doc_id, termos=True)
    assert novo is not tk and "agentic ai" not in novo["termo"]
    # parâmetro que a etapa não lê (kwic_janela) não a reexecuta
    p = client.get(f"/api/projetos/{projeto43}/parametros").json()
    p["kwic_janela"] = 12
    for k in ("versao_parametros", "hash_parametros"):
        p.pop(k)
    client.put(f"/api/projetos/{projeto43}/parametros", json=p)
    assert _executar(client, projeto43)["termos_compostos"]["pulado"] == 1


def test_por_termo_sem_a_etapa_responde_409(client, projeto43):
    pasta = pasta_do_projeto(projeto43)
    (pasta / "cache" / "termos_compostos.json").unlink()
    r = client.get(f"/api/projetos/{projeto43}/analises/frequencias", params={"por": "termo"})
    assert r.status_code == 409
    assert client.get(f"/api/projetos/{projeto43}/analises/kwic", params={"q": "ai", "por": "termo"}).status_code == 409
    assert client.get(f"/api/projetos/{projeto43}/analises/termos-compostos").status_code == 404


def test_parametros_antigos_sem_termos_compostos_recebem_o_padrao(tmp_path):
    from app.services import parametros
    pasta = tmp_path / "antigo"
    pasta.mkdir()
    (pasta / "parametros.json").write_text(json.dumps({"versao_parametros": 3, "kwic_janela": 7}), encoding="utf-8")
    p = parametros.carregar(pasta)
    assert p["termos_compostos"] == {"ativa": True, "automaticos": True, "n_max": 3, "min_freq": 10, "min_docs": 3,
                                     "max_automaticos": 200, "lista": [], "bloqueados": [],
                                     "internas_permitidas": ["of", "on", "for", "in", "to", "de", "da", "do"],
                                     "excluir_regex": [r"\b(\w+) \1\b", r"^(\w{1,2} )+\w{1,2}$"], "max_concentracao": 0.8}
    assert tc.configuracao(p)["min_freq"] == 10


# ---------- 4.4: API e etapa ----------

def test_api_segmentos_do_documento_paginada(client, projeto43):
    docs = client.get(f"/api/projetos/{projeto43}/documentos").json()
    d = docs[0]["id"]
    r = client.get(f"/api/projetos/{projeto43}/documentos/{d}/segmentos", params={"limit": 5})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["alvo"] == 40 and len(corpo["itens"]) == 5 and corpo["total"] > 5
    s0 = corpo["itens"][0]
    assert {"seg", "pagina", "secao", "inicio_token", "fim_token", "n_tokens", "texto"} <= set(s0)
    assert s0["pagina"] == 1 and s0["inicio_token"] == 0 and s0["fim_token"] == s0["n_tokens"] - 1
    seguinte = client.get(f"/api/projetos/{projeto43}/documentos/{d}/segmentos", params={"offset": 5, "limit": 5}).json()
    assert seguinte["itens"][0]["seg"] == 5
    # referências (incluir=0) não são segmentadas
    todos = client.get(f"/api/projetos/{projeto43}/documentos/{d}/segmentos", params={"limit": 500}).json()["itens"]
    assert all("Zebra" not in s["texto"] for s in todos) and all(s["secao"] != "referencias" for s in todos)
    assert client.get(f"/api/projetos/{projeto43}/documentos/9999/segmentos").status_code == 404
    # tokens do corpo cobertos exatamente uma vez
    pasta = pasta_do_projeto(projeto43)
    seg = segmentacao.ler_segmentos(pasta, d)
    tk = json.loads((pasta / "cache" / "tokens" / f"{d}.json").read_text(encoding="utf-8"))
    assert sum(x["n_tokens"] for x in seg["segmentos"]) == sum(tk["incluir"])
    assert [i for i, v in enumerate(seg["seg"]) if v == -1] == [i for i, v in enumerate(tk["incluir"]) if not v]


def test_api_resumo_dos_segmentos_e_parametro_segmento_palavras(client, projeto43):
    r = _get(client, projeto43, "segmentos/resumo")
    assert r["alvo"] == 40 and r["documentos"] == 4 and r["segmentos"] > 20
    assert 25 <= r["media"] <= 60 and r["minimo"] >= 1 and r["maximo"] <= 120
    assert sum(f["segmentos"] for f in r["distribuicao"]) == r["segmentos"]
    assert 0 <= r["pct_fim_de_frase"] <= 100 and r["pct_fim_de_frase"] > 50  # o corpus tem pontuação de frase
    assert sum(r["cortes"].values()) == r["segmentos"]
    # mudar segmento_palavras reexecuta só a etapa de segmentos
    p = client.get(f"/api/projetos/{projeto43}/parametros").json()
    p["segmento_palavras"] = 20
    for k in ("versao_parametros", "hash_parametros"):
        p.pop(k)
    assert client.put(f"/api/projetos/{projeto43}/parametros", json=p).status_code == 200
    etapas = _executar(client, projeto43)
    assert etapas["segmentos"]["ok"] == 4 and etapas["linguistica"]["pulado"] == 4 and etapas["limpeza"]["pulado"] == 4
    r2 = _get(client, projeto43, "segmentos/resumo")
    assert r2["alvo"] == 20 and r2["segmentos"] > r["segmentos"] * 1.5
