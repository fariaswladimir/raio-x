"""4.5 Classes gramaticais e entidades (spaCy opcional): atalhos de classes, comportamento SEM spaCy (etapa, lematização "spacy",
status e consultas) e, quando o spaCy e os modelos estão instalados, anotação alinhada, arquivo lateral, lematização "spacy",
frequências por classe, NER e filtros de classe na CHD e nos termos compostos. Os testes com spaCy são pulados se ele faltar."""
import json

import pytest

from app.services import spacy_nlp as sn

TEM_SPACY = sn.modelo_instalado("en")
precisa_spacy = pytest.mark.skipif(not TEM_SPACY, reason="spaCy ou en_core_web_sm não instalado (instalar_spacy.bat)")

EMPRESAS = ["OpenAI", "Google", "Microsoft", "Anthropic", "Amazon"]
CIDADES = ["London", "Paris", "Berlin", "Tokyo", "Boston"]


def test_expandir_classes():
    assert sn.expandir_classes(["substantivos"]) == {"NOUN", "PROPN"}
    assert sn.expandir_classes(["verbos", "adj"]) == {"VERB", "ADJ"}
    assert sn.expandir_classes(["plenas"]) == {"NOUN", "PROPN", "ADJ", "VERB"}
    assert sn.expandir_classes([]) == frozenset()
    with pytest.raises(ValueError):
        sn.expandir_classes(["artigos"])


def _texto(i: int) -> str:
    frases = []
    for k in range(40):
        e, c = EMPRESAS[(i + k) % 5], CIDADES[(k + 2 * i) % 5]
        frases.append(f"In case {i}{k}, the founders at {e} built useful agentic tools in {c} and reported better results for small startups.")
    return "# Study\n\n" + "\n\n".join(" ".join(frases[j:j + 4]) for j in range(0, 40, 4))


@pytest.fixture()
def pasta_corpus(tmp_path):
    pasta = tmp_path / "corpus"
    pasta.mkdir()
    for i in (1, 2, 3):
        (pasta / f"{i:03d}_2025_Autor{i}_Titulo.md").write_text(_texto(i), encoding="utf-8")
    return pasta


def _criar(client, pasta, nome, projetos_dir, parametros=None):
    slug = client.post("/api/projetos", json={"nome": nome, "pasta_origem": str(pasta)}).json()["slug"]
    arq = projetos_dir / slug / "parametros.json"
    par = json.loads(arq.read_text(encoding="utf-8"))
    par["limpeza"] = {**par.get("limpeza", {}), "excluir_ruido": False}  # frases-modelo repetidas virariam ruído (3.4)
    par.update(parametros or {})
    arq.write_text(json.dumps(par), encoding="utf-8")
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return slug, r.json()


def _etapa(exec_, nome):
    return next(e for e in exec_["etapas"] if e["etapa"] == nome)


# ---------- sem spaCy ----------

def test_sem_spacy_tudo_segue(client, pasta_corpus, projetos_dir, monkeypatch):
    monkeypatch.setattr(sn, "spacy_instalado", lambda: False)
    monkeypatch.setattr(sn, "modelo_instalado", lambda idioma: False)
    slug, exec_ = _criar(client, pasta_corpus, "sem-spacy", projetos_dir, {"lematizacao": {"ativa": True, "metodo": "spacy", "excecoes": {}}})
    e = _etapa(exec_, "spacy")
    assert e["erro"] == 0 and any("não instalado" in m for m in e["mensagens"])
    assert not (projetos_dir / slug / "cache" / "spacy").exists()
    tk = json.loads((projetos_dir / slug / "cache" / "tokens" / "1.json").read_text(encoding="utf-8"))
    assert tk["lematizacao"]["metodo"] == "simplemma" and tk["lematizacao"]["solicitado"] == "spacy" and "não instalado" in tk["lematizacao"]["motivo"]
    st = client.get("/api/spacy/status").json()
    assert st["instalado"] is False and "não instalado" in st["mensagem"]
    r = client.get(f"/api/projetos/{slug}/analises/classes-gramaticais", params={"classes": "substantivos"}).json()
    assert r["itens"] == [] and len(r["sem_classes"]) == 3
    assert client.get(f"/api/projetos/{slug}/analises/classes-gramaticais", params={"classes": "artigos"}).status_code == 422
    ents = client.get(f"/api/projetos/{slug}/analises/entidades").json()
    assert ents["itens"] == [] and len(ents["sem_ner"]) == 3 and ents["aviso"]


def test_opcao_pos_ner_desligada(client, pasta_corpus, projetos_dir):
    _slug, exec_ = _criar(client, pasta_corpus, "desligado", projetos_dir, {"spacy": {"pos_ner": False}})
    assert any("desligados" in m for m in _etapa(exec_, "spacy")["mensagens"])


# ---------- com spaCy ----------

@precisa_spacy
def test_anotar_alinha_pos_lema_e_entidades():
    from app.services.tokenizacao import Lematizador, tokenizar_blocos
    blocos = [{"texto": "The founders built agentic tools at OpenAI in London. Multi-agent systems improved results.", "pagina": 2,
               "secao": "corpo", "incluir": True}]
    tk = tokenizar_blocos(blocos, Lematizador("en"))
    tk["idioma"] = "en"
    ann = sn.anotar(blocos, tk, "en")
    pos = sn.classes_do_documento(ann)
    por_forma = dict(zip(tk["forma"], pos))
    assert por_forma["founders"] == "NOUN" and por_forma["built"] == "VERB" and por_forma["OpenAI"] in ("PROPN", "NOUN")
    assert por_forma["Multi-agent"] in ("NOUN", "ADJ", "PROPN")  # token do Raio-X cobre vários do spaCy: classe do último
    tipos = {(e["texto"], e["tipo"]) for e in ann["ents"]}
    assert ("London", "GPE") in tipos
    assert ann["lema"][tk["forma"].index("founders")] == "founder" and ann["lema"][tk["forma"].index("built")] == "build"
    assert ann["lema"][tk["forma"].index("Multi-agent")] == ""  # sem coincidência exata: mantém a simplemma
    assert all(e["pagina"] == 2 for e in ann["ents"]) and ann["assinatura"] == sn.assinatura("en_core_web_sm", tk)


@precisa_spacy
def test_pipeline_com_spacy_sidecar_lematizacao_e_consultas(client, pasta_corpus, projetos_dir):
    slug, exec_ = _criar(client, pasta_corpus, "com-spacy", projetos_dir)
    e = _etapa(exec_, "spacy")
    assert e["erro"] == 0 and e["ok"] == 3
    pasta = projetos_dir / slug
    ann = json.loads((pasta / "cache" / "spacy" / "1.json").read_text(encoding="utf-8"))
    tk = json.loads((pasta / "cache" / "tokens" / "1.json").read_text(encoding="utf-8"))
    assert ann["n"] == tk["n"] and "pos" not in tk and ann["modelo"] == "en_core_web_sm"  # tokens intactos
    assert tk["lematizacao"]["metodo"] == "simplemma"
    st = client.get("/api/spacy/status").json()
    assert st["instalado"] and st["modelos"]["en"]["instalado"]
    base = f"/api/projetos/{slug}/analises"
    r = client.get(f"{base}/classes-gramaticais", params={"classes": "substantivos", "limite": 50}).json()
    termos = {t["termo"]: t for t in r["itens"]}
    assert "founder" in termos and termos["founder"]["classe"] == "NOUN" and r["documentos"] == 3 and not r["sem_classes"]
    assert "build" not in termos and "useful" not in termos  # verbo e adjetivo ficam fora do filtro de substantivos
    v = {t["termo"] for t in client.get(f"{base}/classes-gramaticais", params={"classes": "verbos"}).json()["itens"]}
    a = {t["termo"] for t in client.get(f"{base}/classes-gramaticais", params={"classes": "adjetivos"}).json()["itens"]}
    assert "build" in v and "useful" in a and "founder" not in v
    assert "posicao" in client.get(f"{base}/classes-gramaticais.csv", params={"classes": "plenas"}).text
    ents = client.get(f"{base}/entidades", params={"tipos": "ORG,GPE,PERSON"}).json()
    textos = {(x["texto"], x["tipo"]) for x in ents["itens"]}
    assert any(t == "GPE" and x in CIDADES for x, t in textos)
    london = next(x for x in ents["itens"] if x["texto"] == "London")
    assert london["freq"] >= 3 and london["docs"] == 3 and london["kwic"] == "london"
    um = client.get(f"{base}/entidades", params={"documento_id": 1}).json()
    assert [d["id"] for d in um["por_documento"]] == [1]
    assert "consulta_kwic" in client.get(f"{base}/entidades.csv").text
    # a consulta KWIC sugerida acha o trecho
    k = client.get(f"{base}/kwic", params={"q": london["kwic"], "por": "forma"}).json()
    assert k["total"] >= 3


@precisa_spacy
def test_lematizacao_spacy_e_filtros_de_classe(client, pasta_corpus, projetos_dir):
    slug, exec_ = _criar(client, pasta_corpus, "lema-spacy", projetos_dir, {
        "lematizacao": {"ativa": True, "metodo": "spacy", "excecoes": {}},
        "termos_compostos": {"min_freq": 3, "min_docs": 2, "classes": ["substantivos", "adjetivos"]},
        "reinert": {"formas_ativas": "classes", "classes_ativas": ["substantivos"], "min_freq": 3}})
    pasta = projetos_dir / slug
    tk = json.loads((pasta / "cache" / "tokens" / "1.json").read_text(encoding="utf-8"))
    assert tk["lematizacao"]["metodo"] == "spacy" and tk["lematizacao"]["lemas_trocados"] >= 0
    i = tk["norm"].index("founders")
    assert tk["lema"][i] == "founder"
    e = _etapa(exec_, "spacy")
    assert e["erro"] == 0 and any("reaproveitado" in m and "true" in m.lower() for m in e["mensagens"])  # sidecar da linguística reaproveitado
    # termos compostos só com substantivos/adjetivos: nada com verbo ("built") nem advérbio
    tc = json.loads((pasta / "cache" / "termos_compostos.json").read_text(encoding="utf-8"))
    assert tc["configuracao"]["classes"] == ["ADJ", "NOUN", "PROPN"]
    for item in tc["itens"]:
        assert "build" not in item["termo"].split()
    # Reinert com formas ativas só substantivos
    from app.services.analises import dados, reinert
    metas = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert reinert.classes_ativas(pasta) == {"NOUN", "PROPN"}
    u = reinert.carregar_unidades(pasta, metas, frozenset())
    assert u["classes_ativas"] == ["NOUN", "PROPN"] and not u["sem_classes"]
    assert "founder" in u["freq"] and "build" not in u["freq"] and "useful" not in u["freq"]
    assert dados is not None


def test_reinert_sem_opcao_mantem_todas_as_formas(tmp_path):
    from app.services.analises import reinert
    assert reinert.classes_ativas(tmp_path) is None


def test_aplicar_lemas_regras_sem_depender_do_modelo():
    from app.services.tokenizacao import Lematizador
    tk = {"forma": ["Models", "founders", "API", "multi-agent", "Tasks"], "norm": ["models", "founders", "api", "multi-agent", "tasks"],
          "lema": ["model", "founder", "api", "multi-agent", "task"]}
    ann = {"pos_tabela": ["PROPN", "NOUN"], "pos": [0, 1, 1, 1, 1], "lema": ["models", "founderx", "apix", "multi-agentx", "tasksx"]}
    mudou = sn.aplicar_lemas(tk, ann, Lematizador("en"))
    assert tk["lema"][0] == "model"  # PROPN sem lematização do spaCy: fica a simplemma
    assert tk["lema"][1] == "founderx" and mudou == 2  # troca onde o spaCy lematizou (founders e tasks)
    assert tk["lema"][2] == "api" and tk["lema"][3] == "multi-agent"  # exceção/sigla e composto com hífen seguem a 4.1
