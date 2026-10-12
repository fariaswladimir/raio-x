"""15.3 Legibilidade (sílabas EN/PT conferidas à mão, fórmulas, frases), 15.4 palavras-chave (RAKE, YAKE, TextRank),
15.5 sumarização extrativa (TextRank, LexRank, MMR) e 15.9 agrupamento (k-means, espectral, PCA, ARI), com textos e
matrizes de brinquedo; API, CSV e etapa com um corpus sintético. Sem Docling."""
import json
import math
import random

import numpy as np
import pytest

from app import database
from app.database import pasta_do_projeto
from app.models import Analise
from app.services.analises import agrupamento, dados, legibilidade, palavras_chave, silabas, similaridade, sumarizacao, texto_documento
from app.services.palavras_vazias import filtro_palavras_vazias

# ---------- listas de sílabas conferidas à mão (contagem de dicionário) ----------
# "desenvolvimento": as regras foram afinadas olhando as listas de desenvolvimento; as listas "cegas" foram escritas antes de afinar
# e a 1ª passada acertou 43/46 (EN) e 45/45 (PT, depois de corrigir 2 contagens manuais minhas); ver o relatório do lote.

EN_DESENV = {
    "the": 1, "make": 1, "makes": 1, "table": 2, "little": 2, "people": 2, "created": 3, "creating": 3, "entrepreneur": 4,
    "entrepreneurial": 6, "generative": 4, "artificial": 4, "intelligence": 4, "productivity": 5, "particularly": 5, "analysis": 4,
    "quality": 3, "business": 2, "different": 3, "experience": 4, "media": 3, "radio": 3, "video": 3, "science": 2, "scientific": 4,
    "organization": 5, "technology": 4, "evaluation": 5, "evidence": 3, "reduced": 2, "judged": 1, "wanted": 2, "learned": 1,
    "used": 1, "uses": 2, "places": 2, "growth": 1, "simple": 2, "model": 2, "models": 2, "area": 3, "idea": 3, "create": 2,
    "real": 1, "agent": 2, "agentic": 3, "autonomy": 4, "beautiful": 3, "queue": 1, "paper": 2, "language": 2, "beyond": 2,
    "various": 3, "organism": 4, "previous": 3,
}
EN_CEGA = {
    "complexity": 4, "however": 3, "framework": 2, "algorithm": 3, "automation": 4, "decision": 3, "research": 2, "knowledge": 2,
    "digital": 3, "significant": 4, "performance": 3, "variable": 4, "economic": 4, "approach": 2, "founder": 2, "startup": 2,
    "market": 2, "outcomes": 2, "tasks": 1, "learning": 2, "systems": 2, "decisions": 3, "measured": 2, "analyzed": 3,
    "generated": 4, "automatically": 6, "participants": 4, "methodology": 5, "interaction": 4, "communication": 5,
    "relationship": 4, "criteria": 4, "hypothesis": 4, "environment": 4, "development": 4, "management": 3, "resource": 2,
    "strategy": 3, "efficient": 3, "individual": 5, "employees": 3, "unique": 2, "continue": 3, "continuous": 4, "ability": 4,
    "possible": 3,
}
PT_DESENV = {
    "casa": 2, "história": 3, "família": 3, "água": 2, "língua": 2, "muito": 2, "cuidado": 3, "ruim": 2, "juiz": 2, "saída": 3,
    "país": 2, "mais": 1, "empreendedor": 5, "empreendedorismo": 7, "inteligência": 5, "artificial": 4, "organização": 5,
    "tecnologia": 5, "pesquisa": 3, "resultado": 4, "não": 1, "então": 2, "coração": 3, "relação": 3, "ideia": 3, "vazio": 3,
    "poeta": 3, "teatro": 3, "coordenação": 5, "empresário": 4, "estratégia": 4, "saúde": 3, "ainda": 3, "fazia": 3, "quatro": 2,
    "queijo": 2, "frequência": 3, "pessoas": 3, "gratuito": 3, "constituir": 4, "viu": 1, "papéis": 2, "herói": 2, "mãe": 1,
    "também": 2, "análise": 4, "agente": 3, "sociedade": 5, "cenário": 3, "trabalhar": 3, "inovação": 4, "exemplo": 3,
    "rainha": 3, "baixo": 2, "leitura": 3, "negócio": 3, "produtividade": 6, "continua": 4, "ambiente": 4, "piano": 3,
}
PT_CEGA = {
    "pesquisador": 4, "desenvolvimento": 6, "conhecimento": 5, "aprendizagem": 5, "mercado": 3, "cliente": 3, "projeto": 3,
    "processo": 3, "metodologia": 6, "literatura": 5, "científico": 5, "geração": 3, "automação": 4, "decisão": 3,
    "organizações": 5, "tarefas": 3, "autonomia": 5, "experiência": 5, "variáveis": 4, "econômico": 5, "criação": 3,
    "sistema": 3, "sistemas": 3, "aprendizado": 5, "gestão": 2, "equipe": 3, "ferramenta": 4, "usuário": 4, "negociação": 5,
    "avaliação": 5, "empresa": 3, "empresas": 3, "fundador": 3, "dados": 2, "qualidade": 4, "pequenas": 3, "serviços": 3,
    "desafio": 4, "tendência": 3, "resultados": 4, "importante": 4, "diferença": 4, "reduzir": 3, "ruído": 3, "viagem": 3,
}


def _acuracia(lista, f):
    erros = {w: (esperado, f(w)) for w, esperado in lista.items() if f(w) != esperado}
    return 1 - len(erros) / len(lista), erros


@pytest.mark.parametrize("nome,lista,f,minimo", [
    ("EN desenvolvimento", EN_DESENV, silabas.silabas_en, 0.95),
    ("EN cega", EN_CEGA, silabas.silabas_en, 0.90),
    ("PT desenvolvimento", PT_DESENV, silabas.silabas_pt, 0.95),
    ("PT cega", PT_CEGA, silabas.silabas_pt, 0.90),
])
def test_silabas_contra_listas_conferidas(nome, lista, f, minimo):
    assert len(lista) >= 30
    acc, erros = _acuracia(lista, f)
    print(f"\n{nome}: {acc:.1%} de {len(lista)} palavras; erros: {erros}")
    assert acc >= minimo, erros


def test_silabas_casos_e_limites():
    assert silabas.contar_silabas("don't", "en") == 1
    assert silabas.contar_silabas("state-of-the-art", "en") == 4
    assert silabas.contar_silabas("co-criação", "pt") == 4
    assert silabas.contar_silabas("validación", "es") == 4
    assert silabas.contar_silabas("123", "en") == 0 and silabas.contar_silabas("", "pt") == 0
    assert silabas.contar_silabas("ia", "pt") >= 1
    pyphen = pytest.importorskip("pyphen")  # opcional: padrões de hifenização, menos precisos que as regras
    assert pyphen and silabas.contar_silabas("generative", "en", "pyphen") >= 1


# ---------- frases ----------

def test_divisao_em_frases_abreviacoes_numeros_e_titulos():
    texto = ("Introduction\n\nWe follow Smith et al. (2020) and J. Doe in Fig. 3. The value was 3.5 percent! Was it large? "
             "Yes, it was.\n\nthis line continues\n\nin the next paragraph without a full stop. Final sentence here.")
    frases = [f for _o, f in texto_documento.dividir_frases(texto)]
    assert "Introduction" not in frases  # título (sem pontuação final, < 4 palavras)
    assert frases[0].startswith("We follow Smith et al. (2020) and J. Doe in Fig. 3.")
    assert "The value was 3.5 percent!" in frases and "Was it large?" in frases
    assert any(f.startswith("this line continues in the next paragraph") for f in frases)  # linha quebrada: a frase continua
    assert frases[-1] == "Final sentence here."


def test_divisao_preserva_deslocamentos():
    texto = "First sentence is here.\n\nsecond part of it\n\ncontinues here. Another one follows now."
    achados = texto_documento.dividir_frases(texto)
    for off, f in achados:
        assert texto[off:off + 5] == f[:5]


# ---------- 15.3 fórmulas e faixas ----------

def test_formulas_de_legibilidade():
    assert legibilidade.flesch_en(10, 1.5) == pytest.approx(206.835 - 10.15 - 126.9)
    assert legibilidade.flesch_pt(10, 1.5) == pytest.approx(248.835 - 10.15 - 126.9)
    assert legibilidade.flesch_pt(10, 1.5) - legibilidade.flesch_en(10, 1.5) == pytest.approx(42.0)
    assert legibilidade.flesch_kincaid(10, 1.5) == pytest.approx(0.39 * 10 + 11.8 * 1.5 - 15.59)
    assert legibilidade.gunning_fog(10, 10) == pytest.approx(8.0)
    assert legibilidade.coleman_liau(500, 100, 5) == pytest.approx(0.0588 * 500 - 0.296 * 5 - 15.8)
    assert legibilidade.smog(30, 30) == pytest.approx(1.0430 * math.sqrt(30) + 3.1291)
    assert legibilidade.smog(15, 15) == pytest.approx(legibilidade.smog(30, 30))  # escala para 30 frases


def test_faixas_de_interpretacao():
    assert legibilidade.faixa_flesch_en(95) == "muito fácil" and legibilidade.faixa_flesch_en(65) == "padrão"
    assert legibilidade.faixa_flesch_en(10).startswith("muito difícil") and legibilidade.faixa_flesch_en(-5) == "extremamente difícil"
    assert legibilidade.faixa_flesch_pt(80).startswith("fácil") and legibilidade.faixa_flesch_pt(10).startswith("muito difícil")
    assert legibilidade.faixa_serie(5) == "fundamental I" and legibilidade.faixa_serie(14) == "universitário"


FACIL = "The cat sat on the mat. " * 40
DIFICIL = ("Interdisciplinary entrepreneurship researchers systematically operationalized heterogeneous organizational "
           "characteristics notwithstanding methodological considerations. ") * 40


def _frases(texto):
    return [f for _o, f in texto_documento.dividir_frases(texto)]


def test_texto_facil_x_dificil_em_ingles():
    f = legibilidade.analisar_texto(_frases(FACIL), "en")
    d = legibilidade.analisar_texto(_frases(DIFICIL), "en")
    assert f["frases"] == 40 and f["palavras"] == 240 and f["silabas_por_palavra"] == 1.0
    assert f["principal"]["id"] == "flesch_en" and f["principal"]["valor"] == pytest.approx(206.835 - 1.015 * 6 - 84.6, abs=0.01)
    assert f["principal"]["faixa"] == "muito fácil" and f["confiavel"] is False  # ASL = 6: abaixo de 8, aviso de frases curtas
    assert d["principal"]["valor"] < 0 and d["indices"]["gunning_fog"]["valor"] > f["indices"]["gunning_fog"]["valor"]
    assert d["indices"]["smog"]["valor"] > f["indices"]["smog"]["valor"]


def test_idioma_escolhe_formula_principal_e_avisa():
    pt = ("O gato subiu no telhado ontem à noite para observar a lua cheia. " * 35)
    r = legibilidade.analisar_texto(_frases(pt), "pt")
    assert r["formula_principal"] == "flesch_pt" and r["principal"]["id"] == "flesch_pt"
    assert r["indices"]["flesch_pt"]["valor"] - r["indices"]["flesch_en"]["valor"] == pytest.approx(42.0, abs=0.05)
    es = legibilidade.analisar_texto(_frases(pt), "es")
    assert es["principal"] is None and any("idioma" in a for a in es["avisos"])


def test_aviso_de_poucas_frases_e_divisao_suspeita():
    curto = legibilidade.analisar_texto(_frases("The cat sat on the old mat today. " * 5), "en")
    assert curto["confiavel"] is False and any("apenas 5 frases" in a for a in curto["avisos"])
    sem_ponto = legibilidade.analisar_texto(["word " * 100 for _ in range(40)], "en")
    assert not sem_ponto["confiavel"] and any("sem pontuação final" in a for a in sem_ponto["avisos"])
    assert legibilidade.analisar_texto([], "en")["indices"] == {}


def test_gunning_fog_exclui_nomes_proprios_compostos_e_ed():
    c = legibilidade.contar_frases(["Today Alexandria University announced state-of-the-art learned developments."], "en")
    # complexas: só "developments" (4); "Alexandria" e "University" são nomes próprios no meio da frase, "state-of-the-art" é composto e
    # "announced"/"learned" têm 2 e 1 sílaba (sem o -ed)
    assert c["palavras_complexas"] == 1
    assert c["polissilabos"] >= 3


# ---------- 15.4 palavras-chave ----------

TOY = ("Solo entrepreneurs use generative AI tools to launch products faster. Generative AI tools lower the cost of building a product prototype. "
       "Many solo entrepreneurs adopt generative AI tools for customer research. The weather was pleasant on the day of the survey. "
       "Entrepreneurs report that generative AI tools save time. Team ventures still outperform solo entrepreneurs in quality outcomes. "
       "Solo entrepreneurs rely on generative AI tools for marketing copy. Venture capital firms evaluate the quality of every product prototype. "
       "The cost of a product prototype fell after generative AI tools arrived. Customer research with generative AI tools is cheap and fast.")


def _toy_frases():
    return [{"i": i, "texto": f, "pagina": 1 + i // 4, "secao": "corpo", "titulo_secao": None}
            for i, (_o, f) in enumerate(texto_documento.dividir_frases(TOY))]


PARAMS_MIN2 = {"documento_extra": {"rake": {"min_freq": 2}, "yake": {"min_freq": 2}, "textrank": {"min_freq": 2}}}


def test_rake_no_texto_de_brinquedo():
    r = palavras_chave.calcular(_toy_frases(), "en", "rake", PARAMS_MIN2, 5)
    # conferido à mão: "generative", "ai" e "tools" aparecem em 4 candidatas ("... tools lower", "... tools" x2, "... tools arrived";
    # as de 5-6 palavras são descartadas), deg = 4 + 3 + 3 + 4 = 14, score = 14/4 = 3,5 por palavra -> 10,5
    assert r[0]["frase"] == "generative ai tools" and r[0]["frequencia"] == 2 and r[0]["pontuacao"] == 10.5
    assert all(x["pontuacao"] >= y["pontuacao"] for x, y in zip(r, r[1:]))  # maior é melhor
    assert all(len(x["frase"].split()) <= 4 for x in r)


def test_rake_pontuacao_formula():
    # "solo": freq 2, deg 2·2 = 4 -> 2; "entrepreneurs" idem -> 2; "solo entrepreneurs" = 4; "market" e "founders": freq 1, deg 1 -> 1
    frases = [{"i": i, "texto": f, "pagina": 1, "secao": "c"} for i, (_o, f) in enumerate(texto_documento.dividir_frases(
        "Solo entrepreneurs and the market grow. Solo entrepreneurs and the founders win."))]
    r = palavras_chave.rake(frases, palavras_chave.trechos(frases), frozenset({"and", "the", "grow", "win"}), 4, 1, 10)
    por = {x["frase"]: x["pontuacao"] for x in r}
    assert por == {"solo entrepreneurs": 4.0, "market": 1.0, "founders": 1.0}
    assert r[0]["frase"] == "solo entrepreneurs" and r[0]["frequencia"] == 2


def test_yake_no_texto_de_brinquedo():
    r = palavras_chave.calcular(_toy_frases(), "en", "yake", PARAMS_MIN2, 6)
    termos = [x["frase"] for x in r]
    assert termos[0] in ("ai", "generative ai", "ai tools", "generative ai tools")
    assert "generative ai" in termos or "generative ai tools" in termos
    assert all(x["pontuacao"] <= y["pontuacao"] for x, y in zip(r, r[1:]))  # menor é melhor
    # desduplicação: nenhuma dupla com razão de similaridade >= 0,8
    import difflib
    for i, a in enumerate(termos):
        for b in termos[:i]:
            assert difflib.SequenceMatcher(None, a, b).ratio() < 0.8


def test_textrank_no_texto_de_brinquedo():
    r = palavras_chave.calcular(_toy_frases(), "en", "textrank", PARAMS_MIN2, 5)
    assert r[0]["frase"] == "generative ai tools"
    assert any(x["frase"] == "solo entrepreneurs" for x in r)
    assert r[0]["paginas"] and all(1 <= p <= 3 for x in r for p in x["paginas"])


def test_palavras_chave_deterministicas_e_validacoes():
    a = palavras_chave.calcular_todos(_toy_frases(), "en", PARAMS_MIN2)
    b = palavras_chave.calcular_todos(_toy_frases(), "en", PARAMS_MIN2)
    assert a == b
    with pytest.raises(ValueError):
        palavras_chave.calcular(_toy_frases(), "en", "tfidf")
    with pytest.raises(ValueError):
        palavras_chave.calcular(_toy_frases(), "en", "textrank", {"documento_extra": {"textrank": {"janela": 1}}})
    assert palavras_chave.calcular([], "en", "yake") == [] and palavras_chave.calcular([], "en", "rake") == []


# ---------- 15.5 sumarização ----------

SENTENCAS = [
    "Solar panels reduce household energy costs across many regions every year.",          # 0 (p.1) tema A
    "Solar panels cut household energy costs across many regions every year.",             # 1 (p.1) quase igual a 0
    "Wind turbines generate electricity from moving air along coastal areas and plains.",  # 2 (p.2) tema B
    "Wind turbines produce electricity from moving air along coastal plains and areas.",   # 3 (p.2) quase igual a 2
    "The committee scheduled a long meeting about the annual budget next month.",          # 4 (p.3) isolada
    "Battery storage lets households keep solar energy for the evening hours.",            # 5 (p.3) liga A
    "Grid operators balance wind and solar electricity with large storage batteries.",     # 6 (p.4) liga A e B
    "Short one.",                                                                          # 7 inelegível (curta)
    "See https://example.org/data for the complete dataset of all measurements here.",     # 8 inelegível (URL)
]


def _frases_resumo():
    return [{"i": i, "texto": t, "pagina": 1 + i // 2, "secao": "corpo", "titulo_secao": None} for i, t in enumerate(SENTENCAS)]


@pytest.mark.parametrize("metodo", sumarizacao.METODOS)
def test_resumo_ordem_original_pagina_e_determinismo(metodo):
    fr = _frases_resumo()
    r = sumarizacao.resumir(fr, "en", metodo, None, 3)
    assert r["n_candidatas"] == 7 and len(r["frases"]) == 3
    idx = [f["i"] for f in r["frases"]]
    assert idx == sorted(idx)  # ordem original
    assert 7 not in idx and 8 not in idx  # frases curta e com URL ficam de fora
    for f in r["frases"]:
        assert f["pagina"] == fr[f["i"]]["pagina"] and f["secao"] == "corpo" and f["texto"] == fr[f["i"]]["texto"]
    assert sorted(f["classificacao"] for f in r["frases"]) == [1, 2, 3]
    assert r == sumarizacao.resumir(_frases_resumo(), "en", metodo, None, 3)


def test_mmr_evita_redundancia_e_lexrank_nao():
    mmr = sumarizacao.resumir(_frases_resumo(), "en", "mmr", None, 3)
    idx = {f["i"] for f in mmr["frases"]}
    assert len({0, 1} & idx) <= 1 and len({2, 3} & idx) <= 1  # uma de cada par quase duplicado
    lex = sumarizacao.resumir(_frases_resumo(), "en", "lexrank", None, 4)
    assert {0, 1} <= {f["i"] for f in lex["frases"]} or {2, 3} <= {f["i"] for f in lex["frases"]}


def test_mmr_lambda_um_e_so_relevancia_e_pagerank_soma_um():
    contagens = sumarizacao._conjuntos(_frases_resumo()[:7], "en", palavras_chave.vazias("en"))
    x = sumarizacao.matriz_tfidf(contagens)
    ordem, _ = sumarizacao.selecionar_mmr(x, 3, 1.0)
    centro = x.mean(axis=0)
    relevancia = x @ (centro / np.linalg.norm(centro))
    assert ordem == sorted(range(7), key=lambda i: (-relevancia[i], i))[:3]
    r = sumarizacao.pagerank(np.array([[0, 1, 1], [1, 0, 0], [1, 0, 0]], dtype=float))
    assert r.sum() == pytest.approx(1.0) and r[0] > r[1] == pytest.approx(r[2])
    assert sumarizacao.notas_lexrank(x).sum() == pytest.approx(1.0) and sumarizacao.notas_textrank(contagens).sum() == pytest.approx(1.0)


def test_frases_de_legenda_e_sumario_nao_sao_elegiveis():
    ok = "Solar panels reduce household energy costs across many regions every year."
    assert sumarizacao.elegivel(ok)
    assert not sumarizacao.elegivel("Source: OECD survey on how SMEs use generative AI to address skill and labour needs, 2024.")
    assert not sumarizacao.elegivel("Note: SMEs using generative AI were asked whether it helped their company compensate for worker shortages.")
    assert not sumarizacao.elegivel("Table 3 shows that solar panels reduce household energy costs across many regions every year.")
    assert not sumarizacao.elegivel("29 Generative AI helps SMEs compensate for labour shortages 33 Generative AI reduces staff workload 34 Yet it has little effect.")


def test_resumo_validacoes():
    with pytest.raises(ValueError):
        sumarizacao.resumir(_frases_resumo(), "en", "luhn")
    with pytest.raises(ValueError):
        sumarizacao.resumir(_frases_resumo(), "en", "mmr", None, 0)
    assert sumarizacao.resumir([], "en", "mmr")["frases"] == []
    assert len(sumarizacao.resumir(_frases_resumo(), "en", "textrank", None, 50)["frases"]) == 7  # n > candidatas


# ---------- 15.9 agrupamento ----------

def _voc(docs):
    return {"documentos": {str(i): {"tokens": sum(c.values()), "lema": dict(c), "norma": dict(c),
                                    "pares": [[t, t, f] for t, f in c.items()]} for i, c in docs.items()}}


def _metas(ids, grupos=None):
    return [{"id": i, "rotulo": f"D{i}", "arquivo": f"{i}.md", "grupo": (grupos or {}).get(i), "ano": 2025} for i in ids]


def _plantado(n_por=5, topicos=3, semente=15):
    rnd = random.Random(semente)
    docs, i = {}, 0
    for t in range(topicos):
        for _ in range(n_por):
            i += 1
            c = {f"t{t}w{j}": rnd.randint(4, 12) for j in range(8)}
            c.update({f"ruido{rnd.randint(0, 40)}": rnd.randint(1, 2) for _ in range(5)})
            c.update({f"comum{j}": 3 for j in range(3)})
            docs[i] = c
    return docs, [t for t in range(topicos) for _ in range(n_por)]


def test_ari_formula():
    assert agrupamento.ari([0, 0, 1, 1], [5, 5, 9, 9]) == pytest.approx(1.0)       # invariante a rótulos
    assert agrupamento.ari([0, 0, 1, 1], [0, 1, 0, 1]) == pytest.approx(-0.5)      # valor conferido à mão
    assert agrupamento.ari([0, 0, 0, 1, 1, 1], [0, 0, 1, 1, 2, 2]) == pytest.approx(0.2424, abs=1e-3)
    assert agrupamento.ari([1, 1, 1, 1], [1, 1, 1, 1]) == 1.0
    rnd = np.random.default_rng(3)
    assert abs(agrupamento.ari(rnd.integers(0, 3, 600), rnd.integers(0, 3, 600))) < 0.05  # acordo ao acaso ~ 0


def test_kmeans_e_espectral_recuperam_grupos_plantados():
    docs, verdade = _plantado()
    voc, metas = _voc(docs), _metas(list(docs))
    for metodo in agrupamento.METODOS:
        r = agrupamento.calcular(voc, metas, frozenset(), metodo=metodo, k=3, min_df=2, max_df=0.95)
        previsto = [d["cluster"] for d in r["documentos"]]
        assert agrupamento.ari(previsto, verdade) == pytest.approx(1.0), metodo
        assert r["k"] == 3 and r["ari_ward"] == pytest.approx(1.0)
        auto = agrupamento.calcular(voc, metas, frozenset(), metodo=metodo, min_df=2, max_df=0.95)
        assert auto["k"] == 3 and auto["k_automatico"] and auto["silhueta"] == max(s["silhueta"] for s in auto["silhuetas"])


def test_agrupamento_deterministico_e_numeracao():
    docs, _ = _plantado()
    voc, metas = _voc(docs), _metas(list(docs))
    a = agrupamento.calcular(voc, metas, frozenset(), metodo="kmeans", k=3, max_df=0.95)
    b = agrupamento.calcular(voc, metas, frozenset(), metodo="kmeans", k=3, max_df=0.95)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert [d["cluster"] for d in a["documentos"]][0] == 1  # grupos numerados pelo menor índice de documento
    x, *_ = agrupamento.preparar(voc, metas, frozenset(), max_df=0.95)
    r1, _ = agrupamento.kmeans(x, 3, 42)
    r2, _ = agrupamento.kmeans(x, 3, 42)
    assert (r1 == r2).all()
    assert agrupamento.ari(agrupamento.espectral(similaridade.cosseno(x), 3), agrupamento.espectral(similaridade.cosseno(x), 3)) == 1.0


def test_pca_variancia_soma_um_e_eixos_ortogonais():
    docs, _ = _plantado()
    x, *_ = agrupamento.preparar(_voc(docs), _metas(list(docs)), frozenset(), max_df=0.95)
    coords, var = agrupamento.pca(x, 2)
    assert sum(var) == pytest.approx(1.0) and all(v >= -1e-12 for v in var) and var == sorted(var, reverse=True)
    assert coords.shape == (15, 2) and coords[:, 0].mean() == pytest.approx(0, abs=1e-9)
    assert float(coords[:, 0] @ coords[:, 1]) == pytest.approx(0, abs=1e-9)
    # a variância explicada pelos 2 primeiros eixos é a razão das somas dos quadrados
    centrado = x - x.mean(axis=0)
    assert (coords ** 2).sum() / (centrado ** 2).sum() == pytest.approx(var[0] + var[1])
    r = agrupamento.calcular(_voc(docs), _metas(list(docs)), frozenset(), k=3, max_df=0.95)
    assert r["pca"]["soma_eixos"] == pytest.approx(round(var[0], 4) + round(var[1], 4), abs=1e-3)


def test_agrupamento_validacoes():
    docs, _ = _plantado()
    voc, metas = _voc(docs), _metas(list(docs))
    with pytest.raises(ValueError):
        agrupamento.calcular(voc, metas, frozenset(), metodo="dbscan")
    with pytest.raises(ValueError):
        agrupamento.calcular(voc, metas, frozenset(), k=1)
    with pytest.raises(ValueError):
        agrupamento.calcular(voc, metas[:2], frozenset())
    with pytest.raises(ValueError):
        agrupamento.kmeans(np.zeros((3, 2)), 5)


# ---------- API, CSV e etapa (corpus sintético) ----------

PALAVRAS_TEMA = {
    0: "solar energy panels renewable electricity battery storage grid",
    1: "genome protein sequencing cellular molecular biology laboratory",
    2: "museum painting sculpture gallery artist exhibition canvas",
}


def _texto_tema(tema: int, i: int) -> str:
    rnd = random.Random(100 * tema + i)
    ws = PALAVRAS_TEMA[tema].split()
    frases = []
    for _ in range(40):
        frases.append("The " + " and ".join(rnd.sample(ws, 3)) + " are discussed in this study of " + rnd.choice(ws) + " and " + rnd.choice(ws) + ".")
    return "# Study\n\n" + "\n\n".join(" ".join(frases[k:k + 5]) for k in range(0, 40, 5))


@pytest.fixture()
def corpus3(client, tmp_path):
    pasta = tmp_path / "temas"
    pasta.mkdir()
    n = 0
    for tema in range(3):
        for i in range(4):
            n += 1
            (pasta / f"{n:03d}_2025_Autor{n}_Titulo_{tema}_{i}.md").write_text(_texto_tema(tema, i), encoding="utf-8")
    r = client.post("/api/projetos", json={"nome": "temas", "pasta_origem": str(pasta)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return slug, r.json()


def test_api_legibilidade_palavras_chave_resumo(client, corpus3):
    slug, execucao = corpus3
    etapa = next(e for e in execucao["etapas"] if e["etapa"] == "documento_extra")
    assert etapa["ok"] == 1 and etapa["erro"] == 0
    base = f"/api/projetos/{slug}/analises"
    leg = client.get(f"{base}/legibilidade").json()
    assert len(leg["documentos"]) == 12 and "en" in leg["por_idioma"]
    d = leg["documentos"][0]
    assert d["formula_principal"] == "flesch_en" and set(d["indices"]) == {"flesch_en", "flesch_pt", "flesch_kincaid", "gunning_fog", "coleman_liau", "smog"}
    assert d["frases"] >= 5
    csv = client.get(f"{base}/legibilidade.csv")
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf") and b"flesch_en" in csv.content
    pk = client.get(f"{base}/palavras-chave", params={"documento_id": d["documento_id"]}).json()
    assert set(pk["metodos"]) == {"rake", "yake", "textrank"} and pk["tfidf"]
    top5 = {w for x in pk["metodos"]["yake"][:5] for w in x["frase"].split()}
    assert top5 & set(PALAVRAS_TEMA[0].split())  # 001 é do tema 0: o vocabulário do tema aparece entre as 5 primeiras palavras-chave
    um = client.get(f"{base}/palavras-chave", params={"documento_id": d["documento_id"], "metodo": "rake", "n": 3}).json()
    assert list(um["metodos"]) == ["rake"] and len(um["metodos"]["rake"]) <= 3
    assert client.get(f"{base}/palavras-chave", params={"documento_id": d["documento_id"], "metodo": "xx"}).status_code == 422
    assert client.get(f"{base}/palavras-chave", params={"documento_id": 9999}).status_code == 404
    assert client.get(f"{base}/palavras-chave.csv", params={"documento_id": d["documento_id"]}).status_code == 200
    res = client.get(f"{base}/sumarizacao", params={"documento_id": d["documento_id"], "metodo": "textrank", "n": 4}).json()
    assert len(res["frases"]) == 4 and all("pagina" in f and f["secao"] for f in res["frases"])  # corpus de .md sem marcador de página: pagina = None
    assert [f["i"] for f in res["frases"]] == sorted(f["i"] for f in res["frases"])
    assert client.get(f"{base}/sumarizacao.csv", params={"documento_id": d["documento_id"]}).status_code == 200
    assert client.get(f"{base}/sumarizacao", params={"documento_id": d["documento_id"], "metodo": "luhn"}).status_code == 422
    tudo = client.get(f"{base}/documento-extra/{d['documento_id']}").json()
    assert set(tudo["resumos"]) == {"textrank", "lexrank", "mmr"} and tudo["legibilidade"]["frases"] == d["frases"]


def test_instantaneo_da_etapa_documento_extra(client, corpus3):
    slug, _ = corpus3
    db = database.sessao_do_projeto(slug)
    try:
        linhas = db.query(Analise).filter(Analise.tipo == "documento_extra").all()
        assert len(linhas) == 1
        r = json.loads(linhas[0].resultado_json)
        assert len(r["documentos"]) == 12
        d = r["documentos"][0]
        assert d["legibilidade"]["principal"]["id"] == "flesch_en" and len(d["resumos"]["mmr"]["frases"]) == 5
        assert set(d["palavras_chave"]) == {"rake", "yake", "textrank"}
    finally:
        db.close()


def test_api_agrupamento_recupera_temas_e_csv(client, corpus3):
    slug, _ = corpus3
    base = f"/api/projetos/{slug}/analises/agrupamento"
    for metodo in ("kmeans", "espectral"):
        r = client.get(base, params={"metodo": metodo, "k": 3, "max_df": 0.95}).json()
        assert r["n_documentos"] == 12 and r["k"] == 3
        previsto = [d["cluster"] for d in r["documentos"]]
        verdade = [(d["id"] - 1) // 4 for d in r["documentos"]]  # ids 1..12 em ordem de arquivo: 4 documentos por tema
        assert agrupamento.ari(previsto, verdade) == pytest.approx(1.0), metodo
        assert r["ari_ward"] == pytest.approx(1.0)
        assert sum(r["pca"]["variancia_explicada"]) <= 1.0 + 1e-6 and [x["k"] for x in r["silhuetas"]] == list(range(2, 9))
    csv = client.get(base + ".csv", params={"metodo": "kmeans", "k": 3, "max_df": 0.95})
    assert csv.status_code == 200 and b"cluster_ward" in csv.content
    assert client.get(base, params={"metodo": "dbscan"}).status_code == 422
    assert client.get(base, params={"k": 40}).status_code == 422
    assert client.get(base, params={"por": "termo"}).status_code in (200, 409)


def test_api_sem_pipeline_devolve_404(client, projeto):
    base = f"/api/projetos/{projeto}/analises"
    assert client.get(f"{base}/legibilidade").status_code == 404
    assert client.get(f"{base}/agrupamento").status_code == 404
    assert client.get(f"{base}/sumarizacao", params={"documento_id": 1}).status_code == 404


def test_parametros_padrao_do_documento_extra():
    from app.services import parametros as svc
    p = svc.parametros_padrao()["documento_extra"]
    assert p["resumo_frases"] == 5 and p["rake"]["max_palavras"] == 4 and p["yake"]["ngrama_max"] == 3 and p["textrank"]["janela"] == 4
    assert sumarizacao.parametros({"documento_extra": {"resumo_frases": 7}})["n"] == 7
    assert palavras_chave.parametros({"documento_extra": {"n_palavras_chave": 12, "yake": {"dedup": 0.9}}})["yake"]["dedup"] == 0.9
