"""Frente 4: tokenização, lematização, palavras vazias, vocabulário, chaves de cache por parâmetro. Sem Docling."""
import json

import pytest

from app.services import parametros as svc_parametros
from app.services import vocabulario as svc_vocabulario
from app.services.orquestrador import Etapa, etapas_registradas
from app.services.palavras_vazias import eh_vazia, filtro_palavras_vazias, token_vazio
from app.services.tokenizacao import Lematizador, normalizar, tokenizar, tokenizar_blocos


def formas(texto: str) -> list[str]:
    return [f for f, _, _ in tokenizar(texto)]


def lema_de(forma: str, idioma: str = "en", **kw) -> str:
    return Lematizador(idioma, **kw).lema(forma, normalizar(forma))


# ---------- 4.1 tokenizador ----------

def test_tokenizador_apostrofos_e_hifens_internos():
    assert formas("Don't stop the multi-agent system's d’água.") == ["Don't", "stop", "the", "multi-agent", "system's", "d’água"]
    # apóstrofo/hífen soltos nas pontas não entram na palavra
    assert formas("agents' 'quoted' -dash- end-") == ["agents", "quoted", "dash", "end"]
    assert normalizar("D’Água") == "d'água"


def test_tokenizador_exclui_numeros_e_mantem_acentos_pt_es():
    assert formas("em 2024, 3.5 vezes e 100%") == ["em", "vezes", "e"]
    assert formas("Gestão não é ação; año, niño, más") == ["Gestão", "não", "é", "ação", "año", "niño", "más"]
    assert formas("GPT4 e COVID-19") == ["GPT4", "e", "COVID"]  # começa por letra: "GPT4" fica; "-19" é número


def test_normalizar_ligaduras_de_pdf():
    assert normalizar("ﬁnancial") == "financial"


# ---------- 4.1 lematização ----------

@pytest.mark.parametrize("forma,esperado", [
    ("agents", "agent"), ("tasks", "task"), ("models", "model"), ("founders", "founder"),
    ("entrepreneurs", "entrepreneur"), ("data", "data"), ("agentic", "agentic"),
    ("Companies", "company"), ("agent's", "agent"),
])
def test_lemas_en_do_corpus(forma, esperado):
    assert lema_de(forma, "en") == esperado


@pytest.mark.parametrize("forma,esperado", [("empresas", "empresa"), ("agentes", "agente"), ("modelos", "modelo")])
def test_lemas_pt(forma, esperado):
    assert lema_de(forma, "pt") == esperado


def test_lemas_es_e_termo_em_ingles_dentro_de_texto_pt():
    assert lema_de("empresas", "es") == "empresa"
    assert lema_de("agents", "pt") == "agent"  # termo inglês em texto PT: tenta o inglês


def test_excecoes_padrao_e_do_projeto():
    assert lema_de("ai") == "ai"  # simplemma devolveria "be"
    assert lema_de("ia", "pt") == "ia"  # simplemma devolveria "ir"
    assert lema_de("llms") == "llm"
    assert lema_de("GPTs") == "gpt"
    assert lema_de("agentic") == "agentic" and lema_de("GenAI") == "genai"
    # exceções do projeto vencem as padrão e a simplemma
    assert lema_de("agents", excecoes={"agents": "agente"}) == "agente"
    assert lema_de("llms", excecoes={"LLMs": "modelo de linguagem"}) == "modelo de linguagem"


def test_siglas_em_caixa_alta_viram_minuscula_sem_lematizar():
    assert lema_de("SMEs") == "sme" and lema_de("ONGs", "pt") == "ong"  # sigla no plural
    assert lema_de("ERP") == "erp" and lema_de("SaaS") == "saas" and lema_de("OKRS") == "okrs"
    # título em caixa alta é palavra comum: lematiza
    assert lema_de("MODELS") == "model" and lema_de("RESULTS") == "result"


def test_composto_com_hifen_so_reduz_plural_do_ultimo_elemento():
    assert lema_de("multi-agents") == "multi-agent"
    assert lema_de("one-person") == "one-person"
    assert lema_de("human-AI") == "human-ai" and lema_de("llm-based") == "llm-based"  # não vira human-be / llm-base
    assert lema_de("AI's") == "ai" and lema_de("llm's") == "llm"  # possessivo respeita as exceções
    assert lema_de("start-ups") == "startup"


def test_composto_com_cliticos_pt_vira_o_verbo():
    assert lema_de("verificou-se", "pt") == "verificar" and lema_de("observa-se", "pt") == "observar"


def test_erros_conhecidos_da_simplemma_estao_nas_excecoes_padrao():
    # a simplemma 2.0 devolve "growe", "develope", "thinke"... ; learning/reasoning não devem virar verbos
    for forma, esperado in [("growing", "grow"), ("developed", "develop"), ("thinking", "think"), ("fixed", "fix"),
                            ("learning", "learning"), ("reasoning", "reasoning"), ("planning", "planning"),
                            ("training", "training"), ("based", "based"), ("Google", "google")]:
        assert lema_de(forma) == esperado, forma
    assert lema_de("google", "pt") == "google"


def test_lematizacao_desligada_lema_igual_norm():
    lem = Lematizador("en", ativa=False, excecoes={"agents": "x"})
    assert lem.lema("Agents", "agents") == "agents"
    assert lem.lema("LLMs", "llms") == "llms"
    assert lem.lema("AI", "ai") == "ai"


# ---------- 4.1 tokens: offsets, página, incluir ----------

BLOCOS = [
    {"pagina": 1, "secao": "resumo", "titulo_secao": "Abstract", "texto": "AI agents solve tasks.\n\nFounders' tools.", "incluir": True},
    {"pagina": 2, "secao": "metodos", "titulo_secao": "Method", "texto": "We built multi-agent systems in 2024.", "incluir": True},
    {"pagina": 3, "secao": "referencias", "titulo_secao": "References", "texto": "Smith, J. (2020). Agents et al.", "incluir": False},
    {"pagina": None, "secao": "outro", "titulo_secao": None, "texto": "Sem página.", "incluir": True},
]


def test_offsets_pagina_e_incluir_acompanham_os_blocos():
    t = tokenizar_blocos(BLOCOS, Lematizador("en"))
    n = t["n"]
    assert n == len(t["forma"]) == len(t["norm"]) == len(t["lema"]) == len(t["inicio"]) == len(t["incluir"])
    for i in range(n):
        texto = BLOCOS[t["bloco"][i]]["texto"]
        assert texto[t["inicio"][i]:t["fim"][i]] == t["forma"][i]
        assert t["pagina"][i] == BLOCOS[t["bloco"][i]]["pagina"]
        assert bool(t["incluir"][i]) == BLOCOS[t["bloco"][i]]["incluir"]
        assert t["secoes"][t["secao"][i]] == BLOCOS[t["bloco"][i]]["secao"]
    assert "2024" not in t["forma"]
    pos = t["forma"].index("agents")
    assert (t["norm"][pos], t["lema"][pos], t["pagina"][pos], t["incluir"][pos]) == ("agents", "agent", 1, 1)
    ref = [i for i in range(n) if t["secoes"][t["secao"][i]] == "referencias"]
    assert ref and all(t["incluir"][i] == 0 and t["pagina"][i] == 3 for i in ref)
    assert t["pagina"][t["forma"].index("Sem")] is None


# ---------- 4.2 palavras vazias ----------

def test_listas_com_termos_academicos_obrigatorios():
    filtro = filtro_palavras_vazias({})
    for w in ("et", "al", "fig", "figure", "table", "doi", "arxiv", "https", "http", "www", "pp", "vol", "ibid", "eq",
              "section", "appendix", "cid", "glyph", "preprint", "journal", "e.g", "i.e"):
        assert w in filtro, w


def test_filtro_por_idioma_e_academico_e_proprias():
    p = svc_parametros.parametros_padrao()
    assert {"the", "de", "el", "et"} <= filtro_palavras_vazias(p)
    p["palavras_vazias"].update(en=False)
    f = filtro_palavras_vazias(p)
    assert "the" not in f and "de" in f and "el" in f
    p["palavras_vazias"].update(pt=False, es=False, academico=False)
    assert filtro_palavras_vazias(p) == frozenset()
    p["palavras_vazias"]["proprias"] = ["Agent", " LLM ", ""]
    assert filtro_palavras_vazias(p) == frozenset({"agent", "llm"})


def test_filtro_compativel_com_parametros_antigos():
    assert "the" in filtro_palavras_vazias({"palavras_vazias": {}})  # chaves ausentes = ligadas
    assert "et" in filtro_palavras_vazias({"palavras_vazias": {"en": False}})
    assert "et" not in filtro_palavras_vazias({"palavras_vazias": {"acad": False, "academico": None}})
    assert "the" in filtro_palavras_vazias(None)


def test_eh_vazia_compara_norm_e_lema_e_descarta_1_letra():
    filtro = frozenset({"the", "be", "agent"})
    assert eh_vazia("the", filtro) and eh_vazia("The", filtro) and not eh_vazia("task", filtro)
    assert eh_vazia("x", filtro) and eh_vazia("a", filtro)  # < 2 letras
    assert eh_vazia("was", filtro, lema="be") and not eh_vazia("was", filtro)  # lema na lista
    assert token_vazio("was", "be", filtro) and token_vazio("agents", "agent", filtro)  # lema vazio
    assert token_vazio("agent", "xyz", filtro) and not token_vazio("tasks", "task", filtro)  # norm vazio


# ---------- cache por parâmetros relevantes (orquestrador) ----------

def test_etapas_declaram_parametros_relevantes():
    por_nome = {e.nome: e for e in etapas_registradas()}
    assert por_nome["conversao"].parametros_relevantes == ["conversao"]
    assert por_nome["qualidade"].parametros_relevantes == ["idioma"]
    assert por_nome["limpeza"].parametros_relevantes == ["excluir_referencias", "excluir_secoes"]
    assert por_nome["linguistica"].parametros_relevantes == ["lematizacao", "idioma"]
    assert por_nome["vocabulario"].parametros_relevantes == ["lematizacao", "idioma", "excluir_referencias", "excluir_secoes"]
    assert (por_nome["linguistica"].ordem, por_nome["linguistica"].escopo) == (40, "documento")
    assert (por_nome["vocabulario"].ordem, por_nome["vocabulario"].escopo) == (45, "corpus")
    assert Etapa(nome="x", ordem=1, escopo="corpus", funcao=lambda c: None).parametros_relevantes is None


def test_hash_por_chaves_so_enxerga_as_chaves_pedidas():
    a = svc_parametros.parametros_padrao()
    b = svc_parametros.parametros_padrao()
    b["kwic_janela"] = 25
    b["palavras_vazias"]["proprias"] = ["x"]
    assert svc_parametros.hash_parametros(a) != svc_parametros.hash_parametros(b)
    assert svc_parametros.hash_parametros(a, ["lematizacao"]) == svc_parametros.hash_parametros(b, ["lematizacao"])
    b["lematizacao"]["ativa"] = False
    assert svc_parametros.hash_parametros(a, ["lematizacao"]) != svc_parametros.hash_parametros(b, ["lematizacao"])


# ---------- integração ----------

EN = (
    "The agents solve tasks for the founders of the company, and the entrepreneurs use the models of the "
    "agentic systems in the study. "
)
PT = (
    "As empresas usam os agentes para o desempenho das equipes, e o estudo mostra que os modelos são úteis "
    "para os fundadores. "
)
REFS = "\n".join(f"- Zebra, A. et al. ({2000 + i}). Zebra studies of agents. arXiv:2512.0000{i}." for i in range(8))


def _md(*paginas: str) -> str:
    return "<!-- Fonte: x.pdf | Conversão: Docling -->\n" + "".join(f"\n\n<!-- página {i + 1} -->\n\n{t}" for i, t in enumerate(paginas))


@pytest.fixture()
def corpus4(tmp_path):
    pasta = tmp_path / "corpus4"
    pasta.mkdir()
    (pasta / "001_2026_Kim_Ingles.md").write_text(
        _md("## Abstract\n\n" + EN * 8 + "\n\n## 1 Introduction\n\n" + EN * 6,
            "## 2 Method\n\n" + EN * 8 + "AI is not LLMs; see Smith et al. (2020).\n\n## References\n\n" + REFS),
        encoding="utf-8")
    (pasta / "002_2025_Silva_Portugues.md").write_text(
        _md("## Resumo\n\n" + PT * 10 + "\n\n## Introdução\n\n" + PT * 6,
            "## Método\n\n" + PT * 8 + "\n\n## Referências\n\n" + REFS),
        encoding="utf-8")
    return pasta


@pytest.fixture()
def projeto4(client, corpus4):
    r = client.post("/api/projetos", json={"nome": "Projeto F4", "pasta_origem": str(corpus4)})
    assert r.status_code == 201, r.text
    return r.json()["slug"]


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return r.json()


def _ok(resumo) -> dict:
    return {e["etapa"]: e["ok"] for e in resumo["etapas"] if e["etapa"] in
            ("conversao", "qualidade", "limpeza", "linguistica", "vocabulario")}


def _params(client, slug) -> dict:
    p = client.get(f"/api/projetos/{slug}/parametros").json()
    p.pop("hash_parametros"); p.pop("versao_parametros")
    return p


def _salvar(client, slug, p):
    assert client.put(f"/api/projetos/{slug}/parametros", json=p).status_code == 200


def _docs(client, slug):
    return {d["arquivo"]: d for d in client.get(f"/api/projetos/{slug}/documentos").json()}


def test_pipeline_gera_tokens_e_vocabulario(client, projeto4, projetos_dir):
    r = _executar(client, projeto4)
    assert r["erros"] == 0
    assert _ok(r) == {"conversao": 2, "qualidade": 2, "limpeza": 2, "linguistica": 2, "vocabulario": 1}
    docs = _docs(client, projeto4)
    en, pt = docs["001_2026_Kim_Ingles.md"], docs["002_2025_Silva_Portugues.md"]
    assert (en["idioma"], pt["idioma"]) == ("en", "pt")

    t_en = json.loads((projetos_dir / projeto4 / "cache" / "tokens" / f"{en['id']}.json").read_text(encoding="utf-8"))
    t_pt = json.loads((projetos_dir / projeto4 / "cache" / "tokens" / f"{pt['id']}.json").read_text(encoding="utf-8"))
    assert t_en["idioma"] == "en" and t_pt["idioma"] == "pt" and t_en["formato"] == 1
    mapa_en = dict(zip(t_en["norm"], t_en["lema"]))
    mapa_pt = dict(zip(t_pt["norm"], t_pt["lema"]))
    assert (mapa_en["agents"], mapa_en["tasks"], mapa_en["founders"], mapa_en["models"]) == ("agent", "task", "founder", "model")
    assert mapa_en["agentic"] == "agentic"
    assert mapa_en["ai"] == "ai" and mapa_en["llms"] == "llm"
    assert (mapa_pt["empresas"], mapa_pt["agentes"], mapa_pt["fundadores"]) == ("empresa", "agente", "fundador")

    # os tokens das referências existem, mas com incluir = 0, e as páginas batem com os blocos do texto limpo
    limpo = json.loads((projetos_dir / projeto4 / "cache" / "limpo" / f"{en['id']}.json").read_text(encoding="utf-8"))
    for i in range(t_en["n"]):
        bloco = limpo["blocos"][t_en["bloco"][i]]
        assert bloco["texto"][t_en["inicio"][i]:t_en["fim"][i]] == t_en["forma"][i]
        assert t_en["pagina"][i] == bloco["pagina"] and bool(t_en["incluir"][i]) == bloco["incluir"]
    assert any(t_en["incluir"][i] == 0 and t_en["forma"][i] == "Zebra" for i in range(t_en["n"]))

    # segunda execução: tudo em cache
    assert set(_ok(_executar(client, projeto4)).values()) == {0}


def test_vocabulario_agregados_df_e_exclusao_de_referencias(client, projeto4, projetos_dir):
    _executar(client, projeto4)
    docs = _docs(client, projeto4)
    voc = svc_vocabulario.ler_vocabulario(projetos_dir / projeto4)
    assert voc["formato"] == 1 and voc["corpus"]["documentos"] == 2
    d_en = voc["documentos"][str(docs["001_2026_Kim_Ingles.md"]["id"])]
    d_pt = voc["documentos"][str(docs["002_2025_Silva_Portugues.md"]["id"])]

    c = voc["corpus"]
    assert c["tokens"] == d_en["tokens"] + d_pt["tokens"]
    assert c["lema"]["agent"] == d_en["lema"]["agent"] == 22  # 22 repetições do parágrafo EN (referências fora)
    assert d_en["lema"]["agent"] == d_en["norma"]["agents"]  # só a forma plural no EN
    assert c["df_lema"]["agent"] == 1 and c["df_lema"]["agente"] == 1
    assert "zebra" not in c["norma"]  # referências excluídas (incluir = 0)
    assert "et" in c["norma"]  # "et al" do corpo do texto continua contado (o filtro é da consulta)
    assert all(len(t) >= 2 for t in c["norma"])  # 1 letra fora das contagens
    # tipos e tokens por documento coerentes com os pares
    assert d_en["tipos_lema"] == len(d_en["lema"]) and d_en["tokens"] == sum(n for _, _, n in d_en["pares"])
    assert sum(d_en["lema"].values()) == sum(d_en["norma"].values()) == d_en["tokens"]
    # palavras comuns aparecem nos dois documentos? "the" só no EN; df = 1
    assert c["df_norma"]["the"] == 1 and c["norma"]["the"] == d_en["norma"]["the"]


def test_mudar_kwic_ou_palavras_vazias_nao_reexecuta_nada(client, projeto4):
    _executar(client, projeto4)
    p = _params(client, projeto4)
    p["kwic_janela"] = 25
    p["colocacao_janela"] = 9
    p["segmento_palavras"] = 50
    _salvar(client, projeto4, p)
    assert set(_ok(_executar(client, projeto4)).values()) == {0}
    p["palavras_vazias"]["en"] = False
    p["palavras_vazias"]["proprias"] = ["agent"]
    _salvar(client, projeto4, p)
    assert set(_ok(_executar(client, projeto4)).values()) == {0}


def test_mudar_lematizacao_reexecuta_so_linguistica_e_vocabulario(client, projeto4, projetos_dir):
    _executar(client, projeto4)
    p = _params(client, projeto4)
    p["lematizacao"]["ativa"] = False
    _salvar(client, projeto4, p)
    r = _executar(client, projeto4)
    assert _ok(r) == {"conversao": 0, "qualidade": 0, "limpeza": 0, "linguistica": 2, "vocabulario": 1}
    docs = _docs(client, projeto4)
    voc = svc_vocabulario.ler_vocabulario(projetos_dir / projeto4)
    assert voc["corpus"]["lema"] == voc["corpus"]["norma"]  # lema == norm com a lematização desligada
    assert "agents" in voc["corpus"]["lema"] and "agent" not in voc["corpus"]["lema"]
    assert docs  # (documentos continuam os mesmos)

    # exceção do projeto também re-roda só linguística e vocabulário
    p["lematizacao"] = {"ativa": True, "metodo": "simplemma", "excecoes": {"agents": "agente"}}
    _salvar(client, projeto4, p)
    assert _ok(_executar(client, projeto4)) == {"conversao": 0, "qualidade": 0, "limpeza": 0, "linguistica": 2, "vocabulario": 1}
    voc = svc_vocabulario.ler_vocabulario(projetos_dir / projeto4)
    assert voc["corpus"]["lema"]["agente"] >= 22


def test_mudar_idioma_reexecuta_qualidade_e_o_que_depende_dela(client, projeto4):
    _executar(client, projeto4)
    p = _params(client, projeto4)
    p["idioma"] = ["en"]
    _salvar(client, projeto4, p)
    r = _executar(client, projeto4)
    assert _ok(r) == {"conversao": 0, "qualidade": 2, "limpeza": 0, "linguistica": 2, "vocabulario": 1}


def test_mudar_secoes_excluidas_propaga_para_tokens_e_vocabulario(client, projeto4, projetos_dir):
    _executar(client, projeto4)
    voc = svc_vocabulario.ler_vocabulario(projetos_dir / projeto4)
    assert "zebra" not in voc["corpus"]["norma"]
    p = _params(client, projeto4)
    p["excluir_secoes"] = ["apendice"]  # referências passam a contar
    _salvar(client, projeto4, p)
    r = _executar(client, projeto4)
    assert _ok(r) == {"conversao": 0, "qualidade": 0, "limpeza": 2, "linguistica": 2, "vocabulario": 1}
    voc = svc_vocabulario.ler_vocabulario(projetos_dir / projeto4)
    assert voc["corpus"]["norma"]["zebra"] >= 8


def test_mudar_parametro_de_conversao_reexecuta_tudo_a_jusante(client, projeto4):
    _executar(client, projeto4)
    p = _params(client, projeto4)
    p["conversao"]["ocr"] = True
    _salvar(client, projeto4, p)
    assert _ok(_executar(client, projeto4)) == {"conversao": 2, "qualidade": 2, "limpeza": 2, "linguistica": 2, "vocabulario": 1}


# ---------- API ----------

def test_api_vocabulario_filtro_na_consulta_sem_reexecutar(client, projeto4):
    antes = client.get(f"/api/projetos/{projeto4}/vocabulario")
    assert antes.status_code == 404  # ainda não executou
    _executar(client, projeto4)

    r = client.get(f"/api/projetos/{projeto4}/vocabulario?por=lema&vazias=filtrar&limite=500").json()
    termos = {i["termo"]: i for i in r["itens"]}
    assert r["por"] == "lema" and r["filtradas"] and r["documentos"] == 2
    assert "the" not in termos and "et" not in termos and "de" not in termos
    assert termos["agent"]["freq"] >= 22 and termos["agent"]["docs"] == 1
    assert termos["agent"]["por_10k"] == round(termos["agent"]["freq"] / r["tokens"] * 10000, 2)
    assert [i["freq"] for i in r["itens"]] == sorted((i["freq"] for i in r["itens"]), reverse=True)

    mantidas = client.get(f"/api/projetos/{projeto4}/vocabulario?vazias=manter&limite=500").json()
    assert not mantidas["filtradas"] and "the" in {i["termo"] for i in mantidas["itens"]} and "et" in {i["termo"] for i in mantidas["itens"]}

    # por forma: plural separado do singular; por lema: reunidos
    forma = {i["termo"]: i["freq"] for i in client.get(f"/api/projetos/{projeto4}/vocabulario?por=forma&limite=500").json()["itens"]}
    assert "agents" in forma and "agent" not in forma
    assert termos["agent"]["freq"] >= forma["agents"]

    # limite
    assert len(client.get(f"/api/projetos/{projeto4}/vocabulario?limite=3").json()["itens"]) == 3
    assert client.get(f"/api/projetos/{projeto4}/vocabulario?por=xyz").status_code == 422

    # mudar palavras vazias muda a consulta na hora, sem reexecutar
    p = _params(client, projeto4)
    p["palavras_vazias"]["proprias"] = ["agent"]
    _salvar(client, projeto4, p)
    novo = {i["termo"] for i in client.get(f"/api/projetos/{projeto4}/vocabulario?limite=500").json()["itens"]}
    assert "agent" not in novo and "task" in novo
    p["palavras_vazias"].update(proprias=[], academico=False, es=False)  # "al" também está na lista ES
    _salvar(client, projeto4, p)
    com_et = {i["termo"] for i in client.get(f"/api/projetos/{projeto4}/vocabulario?limite=500").json()["itens"]}
    assert "et" in com_et and "al" in com_et


def test_api_vocabulario_por_documento(client, projeto4):
    _executar(client, projeto4)
    docs = _docs(client, projeto4)
    pt = docs["002_2025_Silva_Portugues.md"]["id"]
    r = client.get(f"/api/projetos/{projeto4}/vocabulario?documento_id={pt}&limite=500").json()
    termos = {i["termo"]: i for i in r["itens"]}
    assert r["documentos"] == 1 and "empresa" in termos and "agent" not in termos
    assert all(i["docs"] == 1 for i in r["itens"])
    assert client.get(f"/api/projetos/{projeto4}/vocabulario?documento_id=9999").status_code == 404


def test_api_tokens_paginado(client, projeto4, projetos_dir):
    _executar(client, projeto4)
    docs = _docs(client, projeto4)
    en = docs["001_2026_Kim_Ingles.md"]["id"]
    r = client.get(f"/api/projetos/{projeto4}/documentos/{en}/tokens?inicio=0&fim=5")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["n"] > 100 and corpo["inicio"] == 0 and corpo["fim"] == 5 and len(corpo["tokens"]) == 5
    assert corpo["idioma"] == "en" and corpo["lematizacao"] == {"ativa": True, "metodo": "simplemma"}
    primeiro = corpo["tokens"][0]
    assert set(primeiro) == {"i", "forma", "norm", "lema", "pagina", "secao", "incluir", "bloco", "offset_inicio", "offset_fim"}
    assert (primeiro["forma"], primeiro["pagina"], primeiro["incluir"]) == ("The", 1, True)

    segunda = client.get(f"/api/projetos/{projeto4}/documentos/{en}/tokens?inicio=5&fim=8").json()
    assert [t["i"] for t in segunda["tokens"]] == [5, 6, 7]
    # sem fim: 200 por padrão; fim além do total é cortado; início além do total devolve vazio
    assert len(client.get(f"/api/projetos/{projeto4}/documentos/{en}/tokens").json()["tokens"]) == 200
    assert client.get(f"/api/projetos/{projeto4}/documentos/{en}/tokens?inicio={corpo['n'] - 2}&fim=99999").json()["fim"] == corpo["n"]
    assert client.get(f"/api/projetos/{projeto4}/documentos/{en}/tokens?inicio={corpo['n'] + 10}").json()["tokens"] == []
    assert client.get(f"/api/projetos/{projeto4}/documentos/9999/tokens").status_code == 404
    # sem o arquivo de tokens (ex.: documento com problema): 404 explicativo
    (projetos_dir / projeto4 / "cache" / "tokens" / f"{en}.json").unlink()
    assert client.get(f"/api/projetos/{projeto4}/documentos/{en}/tokens").status_code == 404


def test_parametros_lematizacao_excecoes_via_api(client, projeto4):
    p = _params(client, projeto4)
    assert p["lematizacao"]["excecoes"] == {}
    p["lematizacao"]["excecoes"] = {"Agents": "agente"}
    _salvar(client, projeto4, p)
    assert client.get(f"/api/projetos/{projeto4}/parametros").json()["lematizacao"]["excecoes"] == {"Agents": "agente"}
