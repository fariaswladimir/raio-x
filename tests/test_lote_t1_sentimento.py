"""15.10 Sentimento por léxico: formatos de léxico (genérico, OpLexicon, SentiLex-PT), negação simples, normalização, VADER (EN),
importação na pasta de configuração do usuário (não no projeto) e API com um corpus sintético EN + PT (léxico sintético)."""
import json
import math

import pytest

from app.services.analises import sentimento as s


@pytest.fixture()
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIOX_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"


def test_ler_lexico_formatos():
    assert s.ler_lexico("bom;1\nruim;-1\nneutro;0\n") == {"bom": 1, "ruim": -1, "neutro": 0}
    op = s.ler_lexico("bonito,adj,1,A\nfeio,adj,-1,A\na favor,prp,1,M\n")
    assert op == {"bonito": 1, "feio": -1}  # multipalavra ignorada
    sl = s.ler_lexico("abafado.PoS=Adj;TG=HUM:N0;POL:N0=-1;ANOT=MAN\nabafada,abafado.PoS=Adj;TG=HUM:N0;POL:N0=-1;ANOT=MAN\nbelo.PoS=Adj;TG=HUM:N0;POL:N0=1;ANOT=MAN\n")
    assert sl == {"abafado": -1, "abafada": -1, "belo": 1}
    assert s.ler_lexico("x;1\nx;-1\ny;0.5\n") == {"x": 0, "y": 0.5}
    with pytest.raises(s.LexicoInvalido):
        s.ler_lexico("lixo sem numero\n")


def test_pontuacao_a_mao_e_negacao():
    termos = {"bom": 1.0, "ruim": -1.0}
    r = s.pontuar_frase_lexico("O resultado é bom.", termos, "pt")
    assert r["termos"] == 1 and r["escore"] == pytest.approx(1 / math.sqrt(1 + 15), abs=1e-4)
    neg = s.pontuar_frase_lexico("O resultado não é bom.", termos, "pt")  # negador a 2 palavras: inverte
    assert neg["escore"] == pytest.approx(-r["escore"])
    longe = s.pontuar_frase_lexico("Não houve nenhuma discussão sobre o resultado bom.", termos, "pt")
    assert longe["escore"] > 0  # negador fora da janela de 3 palavras
    dois = s.pontuar_frase_lexico("bom bom ruim", termos, "pt")
    assert dois["escore"] == pytest.approx(1 / math.sqrt(1 + 15), abs=1e-4)
    assert s.pontuar_frase_lexico("Nada aqui.", termos, "pt") == {"escore": 0.0, "termos": 0}
    assert s.classe(0.05) == "positivo" and s.classe(-0.05) == "negativo" and s.classe(0.04) == "neutro"


def test_vader_en():
    assert s.vader_disponivel()
    assert s.pontuar_frase_vader("This is a great and wonderful result.")["escore"] > 0.5
    assert s.pontuar_frase_vader("This is a terrible, awful failure.")["escore"] < -0.5
    assert abs(s.pontuar_frase_vader("The sample contains 20 firms.")["escore"]) < 0.05


def test_importar_lexico_fica_na_config(config):
    m = s.importar_lexico("Meu PT", "pt", "bom;1\nruim;-1\n", "teste")
    assert m["termos"] == 2 and (config / "lexicos" / "meu-pt.json").is_file()
    assert [x["id"] for x in s.listar_lexicos()] == ["meu-pt"]
    assert s.lexico_do_idioma("pt")["termos"]["bom"] == 1 and s.lexico_do_idioma("es") is None
    with pytest.raises(s.LexicoInvalido):
        s.importar_lexico("", "pt", "bom;1")
    with pytest.raises(s.LexicoInvalido):
        s.importar_lexico("x", "fr", "bom;1")
    with pytest.raises(s.LexicoInvalido):
        s.remover_lexico("../x")
    assert s.remover_lexico("meu-pt") and not s.remover_lexico("meu-pt")


PALAVRAS = ["alpha", "beta", "gamma", "delta", "kappa", "sigma", "omega", "theta", "lambda", "zeta"]


@pytest.fixture()
def corpus_sent(client, tmp_path, config, projetos_dir):
    pasta = tmp_path / "corpus"
    pasta.mkdir()
    def gerar(modelo: str, n: int) -> str:
        return " ".join(modelo.format(k=PALAVRAS[k % len(PALAVRAS)], j=k) for k in range(n)) + "\n\n"

    en_pos = gerar("The {k} results number {j} are excellent and the approach is wonderful.", 30)
    en_neg = gerar("The {k} failure number {j} was terrible and the outcome was awful.", 30)
    neutro = gerar("The sample {j} contains forty firms from the {k} region.", 30)
    pt = (gerar("O resultado {k} número {j} foi bom e a abordagem é ótima.", 20) + gerar("O processo {k} número {j} não é bom e o risco é péssimo.", 20)
          + gerar("A amostra {k} reúne quarenta empresas de três regiões do país, caso {j}.", 20))
    (pasta / "001_2025_Alfa_Um.md").write_text("# Study\n\n" + en_pos + neutro, encoding="utf-8")
    (pasta / "002_2025_Beta_Dois.md").write_text("# Study\n\n" + en_neg + neutro, encoding="utf-8")
    (pasta / "003_2024_Gama_Tres.md").write_text("# Estudo\n\n" + pt, encoding="utf-8")
    slug = client.post("/api/projetos", json={"nome": "sent", "pasta_origem": str(pasta)}).json()["slug"]
    arq = projetos_dir / slug / "parametros.json"  # frases-modelo repetidas seriam descartadas como ruído (3.4)
    par = json.loads(arq.read_text(encoding="utf-8"))
    par["limpeza"] = {**par.get("limpeza", {}), "excluir_ruido": False}
    arq.write_text(json.dumps(par), encoding="utf-8")
    assert client.post(f"/api/projetos/{slug}/executar?sincrono=1").status_code == 200
    return slug


def test_api_sentimento(client, corpus_sent):
    base = f"/api/projetos/{corpus_sent}"
    r = client.get(f"{base}/analises/sentimento")
    assert r.status_code == 200, r.text
    j = r.json()
    en = [d for d in j["documentos"] if d["idioma"] == "en"]
    pt = [d for d in j["documentos"] if d["idioma"] == "pt"]
    assert len(en) == 2
    # sem léxico PT importado: o documento em português é listado como ignorado
    assert not pt and any("léxico" in i["motivo"] for i in j["ignorados"])
    pos, neg = sorted(en, key=lambda d: d["media"], reverse=True)
    assert pos["media"] > 0 and neg["media"] < pos["media"] and j["aviso"]
    assert j["mais_positivas"][0]["escore"] > 0.5
    assert j["mais_negativas"][0]["escore"] < -0.5 and j["mais_negativas"][0]["texto"]
    assert j["por_ano"] and j["por_grupo"] and j["por_grupo"][0]["frases"] > 0
    # importa léxico PT sintético
    assert client.post("/api/config/sentimento/lexicos", json={"nome": "Sintético", "idioma": "pt", "conteudo": "bom;1\nótima;1\nótimo;1\nrisco;-1\npéssimo;-1\n"}).status_code == 201
    j = client.get(f"{base}/analises/sentimento").json()
    pt = [d for d in j["documentos"] if d["idioma"] == "pt"]
    assert len(pt) == 1 and pt[0]["metodo"] == "Sintético" and pt[0]["cobertura"] > 0
    assert pt[0]["positivo"] > 0 and pt[0]["negativo"] > 0 and pt[0]["neutro"] > 0  # neutra: a frase da amostra
    assert not j["ignorados"]
    csv = client.get(f"{base}/analises/sentimento.csv")
    assert csv.status_code == 200 and "escore_medio" in csv.text
    assert client.get("/api/config/sentimento/lexicos").json()["vader"] is True
    assert client.post("/api/config/sentimento/lexicos", json={"nome": "x", "idioma": "pt", "conteudo": "sem polaridade"}).status_code == 422
    assert client.delete("/api/config/sentimento/lexicos/sintetico").status_code == 204
