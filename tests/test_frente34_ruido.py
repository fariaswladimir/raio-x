"""3.4 Detector de segmentos de ruído: listas de autores, tabelas de regressão, cláusulas repetidas e texto normal."""
import json

import pytest

from app.services import ruido as R

AUTORES = ("Maria J. Silva, John A. Smith, Wei Zhang, Ana B. Costa, Pedro H. Souza, Linda M. Brown, Carlos E. Lima, "
           "Sofia R. Alves and Robert K. Miller, Department of Economics, University of Cambridge, Cambridge, UK; "
           "Institute of Technology, Massachusetts, USA")
REGRESSAO = ("Intercept 0.123 (0.045) 2.73 0.006 *** Age -0.021 (0.008) -2.62 0.009 ** Income 0.350 (0.101) 3.47 0.001 *** "
             "Education 0.044 (0.032) 1.38 0.168 R2 0.412 N 1,204 F 18.3 p<0.01")
NORMAL = ("Os resultados indicam que as empresas que adotaram agentes de inteligência artificial relataram ganhos de "
          "produtividade em 2023, embora a evidência seja heterogênea entre setores e dependa do tamanho da organização.")
NORMAL_EN = ("The analysis suggests that firms adopting autonomous agents reported productivity gains in 2023, although "
             "the evidence remains heterogeneous across sectors and depends on organisational size and governance.")


UNICOS = {
    1: "Farmers in the northern provinces adopted drip irrigation slowly because credit was scarce and extension services were weak.",
    2: "Hospitals reorganised their nursing shifts after the pandemic, and staff turnover declined during the following winter months.",
    3: "The orchestra premiered a commissioned symphony inspired by migration, drawing unusually large audiences across several cities.",
    4: "Regulators proposed stricter disclosure rules for algorithmic trading firms, citing recurrent flash crashes in thin markets.",
}


def _seg(i, texto):
    return {"seg": i, "texto": texto, "inicio_token": i * 10, "fim_token": i * 10 + 9, "n_tokens": 10, "pagina": 1}


def test_autores_regressao_e_texto_normal():
    p = R.parametros_do_ruido({})
    assert R.classificar_segmento(AUTORES, p) == "autores"
    assert R.classificar_segmento(REGRESSAO, p) == "tabela"
    assert R.classificar_segmento(NORMAL, p) is None
    assert R.classificar_segmento(NORMAL_EN, p) is None
    # parágrafo com alguns números e siglas continua texto
    assert R.classificar_segmento("In 2020, 45% of the 1,200 firms (n = 540) reported using AI tools in at least 2 "
                                  "departments, and 12% planned to expand them by 2025 according to the survey.", p) is None
    # título em caixa de título, sem lista
    assert R.classificar_segmento("Generative Artificial Intelligence Agents and the Future of Entrepreneurial Work", p) is None


def test_tabela_por_barras_e_texto_repetitivo():
    p = R.parametros_do_ruido({})
    assert R.classificar_segmento("Variável | Média | DP | Mín | Máx | N", p) == "tabela"
    assert R.classificar_segmento("yes no yes no yes no yes no yes no yes no yes no yes no", p) == "repetitivo"


def test_clausula_repetida_entre_documentos_e_limiar_de_docs():
    clausula = ("This work is licensed under a Creative Commons Attribution International License and any reuse requires "
                "explicit credit to the original authors")
    segs = {d: [_seg(0, clausula), _seg(1, UNICOS[d])] for d in range(1, 5)}
    r = R.detectar(segs, {})
    assert all([m["seg"] for m in r[d]] == [0] and r[d][0]["motivo"] == "clausula_repetida" for d in segs)
    # com menos documentos que o mínimo (4) nada é marcado
    r3 = R.detectar({d: segs[d] for d in (1, 2, 3)}, {})
    assert all(r3[d] == [] for d in r3)
    r3b = R.detectar({d: segs[d] for d in (1, 2, 3)}, {"limpeza": {"ruido": {"repeticao_min_docs": 3}}})
    assert all(len(r3b[d]) == 1 for d in r3b)


def test_subtrair_intervalos_e_motivo_do_token():
    ruido = [(10, 14, "tabela"), (30, 35, "autores")]
    assert R.subtrair_intervalos([(0, 50)], ruido) == [(0, 10), (15, 30), (36, 50)]
    assert R.subtrair_intervalos([(12, 13)], ruido) == []
    assert R.subtrair_intervalos([(0, 5), (20, 25)], ruido) == [(0, 5), (20, 25)]
    assert R.subtrair_intervalos([(0, 5)], []) == [(0, 5)]
    assert R.motivo_do_token(ruido, 12) == "tabela" and R.motivo_do_token(ruido, 15) is None
    assert R.motivo_do_token(ruido, 35) == "autores" and R.motivo_do_token([], 1) is None


def test_frase_aviso():
    assert R.frase_aviso({"segmentos": 0, "tokens": 0, "por_motivo": {}}) is None
    f = R.frase_aviso({"segmentos": 3, "tokens": 120, "por_motivo": {"tabela": 2, "autores": 1}})
    assert "3 segmentos de ruído" in f and "tabela ou números 2" in f and "autores/afiliações 1" in f


# ---------- pipeline ----------

_POOL = ("market firm growth policy labour capital skill energy health school trade income risk model data cost price "
         "region sector worker owner family bank credit rule law court city river farm crop seed water soil climate "
         "forest road rail port ship cargo music film art book story myth ritual game sport team coach league fan "
         "study trial survey sample panel cohort effect trend cycle shock gap tax fee grant loan debt asset stock "
         "fund trust board manager client buyer seller maker tool code chip cloud network signal device sensor").split()


def _prosa(semente: int, frases: int = 14) -> str:
    """Prosa variada e determinística (sem repetição de sequências): os testes não dependem de texto repetitivo."""
    import random
    r = random.Random(semente)
    return " ".join("The " + " ".join(r.choice(_POOL) for _ in range(5)) + " was " + " ".join(r.choice(_POOL) for _ in range(6))
                    + " because " + " ".join(r.choice(_POOL) for _ in range(5)) + "." for _ in range(frases))


def _doc(extra: str) -> str:
    semente = sum(map(ord, extra[:20]))
    return _prosa(semente) + "\n\n" + extra + "\n\n" + _prosa(semente + 1)


@pytest.fixture()
def projeto_ruido(client, tmp_path):
    pasta = tmp_path / "artigos_ruido"
    pasta.mkdir()
    (pasta / "001_2026_Kim_Autores.md").write_text(_doc((AUTORES + " ") * 2), encoding="utf-8")
    (pasta / "002_2026_Lee_Tabela.md").write_text(_doc((REGRESSAO + " ") * 2), encoding="utf-8")
    (pasta / "003_2026_Paz_Normal.md").write_text(_doc(NORMAL_EN * 3), encoding="utf-8")
    slug = client.post("/api/projetos", json={"nome": "Ruido", "pasta_origem": str(pasta)}).json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code in (200, 202), r.text
    return slug


def test_etapa_marca_pendencia_e_exclui_da_chd_e_dos_ngramas(client, projeto_ruido, projetos_dir):
    slug = projeto_ruido
    pend = {p["arquivo"].split("/")[-1][:3]: p["avisos"] for p in client.get(f"/api/projetos/{slug}/pendencias").json()}
    assert any("segmento" in a and "ruído" in a for a in pend.get("001", [])), pend
    assert any("ruído" in a and "tabela" in a for a in pend.get("002", [])), pend
    assert not any("ruído" in a for a in pend.get("003", [])), pend
    # n-gramas: "department of economics" (só na lista de autores) some com a exclusão e volta com ela desligada
    def ngramas():
        r = client.get(f"/api/projetos/{slug}/analises/ngramas", params={"n_min": 2, "n_max": 3, "min_freq": 1, "min_docs": 1,
                                                                        "contem": "cambridge", "limite": 50})
        assert r.status_code == 200, r.text
        return r.json()["total"]
    assert ngramas() == 0
    from app.services import parametros
    pasta = projetos_dir / slug
    p = parametros.carregar(pasta)
    p["limpeza"]["excluir_ruido"] = False
    parametros.salvar(pasta, p)
    assert ngramas() > 0
    # KWIC continua mostrando a ocorrência, com a marca
    r = client.get(f"/api/projetos/{slug}/analises/kwic", params={"q": "cambridge", "por": "forma"}).json()
    assert r["total"] >= 1
    p["limpeza"]["excluir_ruido"] = True
    parametros.salvar(pasta, p)
    r = client.get(f"/api/projetos/{slug}/analises/kwic", params={"q": "cambridge", "por": "forma"}).json()
    assert r["total"] >= 1 and all(i["ruido"] == "autores" for i in r["itens"] if "Cambridge" in i["termo"])


def test_reinert_ignora_segmentos_de_ruido(projeto_ruido, projetos_dir):
    from app.services.analises import reinert
    from app.services import parametros
    pasta = projetos_dir / projeto_ruido
    metas = [{"id": i, "rotulo": str(i), "ano": None, "grupo": None, "arquivo": f"{i}", "paginas": None, "pct_corpo": None}
             for i in (1, 2, 3)]
    u1 = reinert.carregar_unidades(pasta, metas, frozenset())
    assert u1["ruido"]["segmentos"] >= 2
    p = parametros.carregar(pasta)
    p["limpeza"]["excluir_ruido"] = False
    parametros.salvar(pasta, p)
    u2 = reinert.carregar_unidades(pasta, metas, frozenset())
    assert u2["ruido"]["segmentos"] == 0
    assert len(u2["st"]) == len(u1["st"]) + u1["ruido"]["segmentos"]
