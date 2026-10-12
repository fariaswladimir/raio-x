"""Tela de metodologia: catálogo (fonte única), formatação ABNT/APA/BibTeX, API e uso no projeto."""
import copy
import re
import unicodedata
from pathlib import Path

import pytest
import yaml

from app import database
from app.config import RAIZ
from app.models import Analise
from app.services import metodologia as svc
from app.services import parametros as svc_parametros
from app.services.metodologia import formatos

EAP = RAIZ / "EAP.md"


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


# ---------------------------------------------------------------- catálogo
def test_catalogo_valida_e_tem_campos_obrigatorios():
    cat = svc.carregar()
    assert len(cat["analises"]) >= 30
    ids = [a["id"] for a in cat["analises"]]
    assert len(ids) == len(set(ids))
    for a in cat["analises"]:
        for campo in svc.CAMPOS_ANALISE:
            assert a.get(campo) not in (None, ""), f"{a['id']}: falta {campo}"
        assert a["status"] in svc.STATUS
        assert 1 <= len(a["cuidados"]) <= 3
        assert a["parametros_padrao"], a["id"]
        if a["status"] == "implementado" and a["familia"] != "Referências gerais":
            assert a["modulo"] and (RAIZ / a["modulo"]).exists(), a["id"]
        for r in a["referencias"]:
            assert r["autores"] and r["ano"] and r["titulo"], f"{a['id']}: referência incompleta {r['chave']}"


def test_catalogo_cobre_as_analises_pedidas():
    ids = {a["id"] for a in svc.carregar()["analises"]}
    esperados = {"conversao_docling", "limpeza_estrutura", "lematizacao", "palavras_vazias", "frequencias", "diversidade_lexical",
                 "kwic", "colocacoes", "ngramas", "termos_compostos", "segmentacao", "keyness", "especificidades",
                 "similaridade_documentos", "dicionario_codebook", "afc", "chd_reinert", "similitude", "rede_coocorrencia",
                 "rede_comunidades_centralidade", "topicos", "estilometria_delta", "legibilidade", "palavras_chave_documento",
                 "sumarizacao_extrativa", "agrupamento_kmeans_espectral_pca", "keyness_referencia_externa", "sentimento_lexico",
                 "redacao_paragrafos_llm", "codificacao_llm_concordancia", "comentarios_regras", "referencias_gerais"}
    assert esperados <= ids, esperados - ids


def test_status_segue_o_eap():
    """Os itens marcados ✅/🟨/⬜ no EAP têm o mesmo status no catálogo (para entregáveis de uma só análise)."""
    linhas = {}
    for linha in EAP.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(\d+\.\d+)\s*\|", linha)
        if m:
            marca = "✅" if "✅" in linha[-40:] else "🟨" if "🟨" in linha[-40:] else "⬜" if "⬜" in linha[-40:] else None
            linhas[m.group(1)] = marca
    mapa = {"✅": "implementado", "🟨": "parcial", "⬜": "planejado"}
    for id_, eap in (("colocacoes", "5.4"), ("especificidades", "6.2"), ("keyness", "6.1"), ("chd_reinert", "7.1"),
                     ("legibilidade", "15.3"), ("afc", "7.3"), ("kwic", "5.3")):
        a = svc.obter(id_)
        assert a["eap_id"] == eap
        assert mapa[linhas[eap]] == a["status"], f"{id_}: EAP {linhas[eap]} x catálogo {a['status']}"


def test_validacao_recusa_catalogo_ruim():
    base = yaml.safe_load(svc.CAMINHO.read_text(encoding="utf-8"))
    ruim = copy.deepcopy(base)
    ruim["analises"][1]["id"] = ruim["analises"][0]["id"]  # id duplicado
    ruim["analises"][2]["status"] = "pronto"
    ruim["analises"][3]["referencias"] = ["nao_existe"]
    del ruim["referencias"]["auer2024"]["titulo"]
    ruim["analises"][4]["cuidados"] = []
    with pytest.raises(svc.CatalogoInvalido) as exc:
        svc.validar(ruim)
    msg = str(exc.value)
    for trecho in ("id duplicado", "'status'", "nao_existe", "'titulo'", "'cuidados'"):
        assert trecho in msg


def test_notas_conferir_antes_de_citar_na_frente_15():
    cat = svc.carregar()["referencias"]
    for chave in ("burrows2002", "flesch1948", "rose2010", "deerwester1990", "blondel2008", "ward1963", "hutto2014", "cohen1960", "lewis2020"):
        assert cat[chave]["nota"] == svc.NOTA_CONFERIR, chave
    assert not cat["dunning1993"].get("nota")  # as da seção 11 do EAP não levam a nota


def _referencias_do_eap() -> list[tuple[str, int]]:
    texto = EAP.read_text(encoding="utf-8")
    secao = texto[texto.index("## 11. Referências por tipo de análise"):]
    pares = []
    for linha in secao.splitlines():
        m = re.match(r"^- ([^,;(]+?),.*?\((\d{4})\)", linha)
        if m:
            pares.append((m.group(1).strip(), int(m.group(2))))
    return pares


def test_todas_as_referencias_da_secao_11_do_eap_estao_no_catalogo():
    pares = _referencias_do_eap()
    assert len(pares) >= 40  # a seção 11 tem ~50 itens com ano
    no_catalogo = {(_sem_acento(formatos.sobrenome_primeiro_autor(r)), r["ano"]) for r in svc.carregar()["referencias"].values()}
    faltam = [(s, a) for s, a in pares if (_sem_acento(s), a) not in no_catalogo]
    assert not faltam, faltam


def test_todas_as_referencias_do_pool_sao_usadas_por_alguma_analise():
    cat = svc.carregar()
    usadas = {r["chave"] for a in cat["analises"] for r in a["referencias"]}
    assert set(cat["referencias"]) == usadas


# ---------------------------------------------------------------- formatadores
LIVRO = {"autores": ["Sinclair, J."], "ano": 1991, "titulo": "Corpus, Concordance, Collocation", "tipo": "livro",
         "detalhes": {"local": "Oxford", "editora": "Oxford University Press"}}
ARTIGO = {"autores": ["Covington, M. A.", "McFall, J. D."], "ano": 2010,
          "titulo": "Cutting the Gordian knot: the moving-average type-token ratio (MATTR)", "tipo": "artigo",
          "veiculo": "Journal of Quantitative Linguistics", "detalhes": {"volume": "17", "numero": "2", "paginas": "94-100"},
          "doi_ou_url": "10.1080/09296171003643098"}
CONGRESSO = {"autores": ["Mihalcea, R.", "Tarau, P."], "ano": 2004, "titulo": "TextRank: bringing order into texts", "tipo": "congresso",
             "veiculo": "Proceedings of EMNLP 2004", "detalhes": {"paginas": "404-411"}}


def test_abnt_livro_artigo_congresso():
    assert formatos.formatar_abnt(LIVRO) == "SINCLAIR, J. Corpus, Concordance, Collocation. Oxford: Oxford University Press, 1991."
    assert formatos.formatar_abnt(ARTIGO) == (
        "COVINGTON, M. A.; MCFALL, J. D. Cutting the Gordian knot: the moving-average type-token ratio (MATTR). "
        "Journal of Quantitative Linguistics, v. 17, n. 2, p. 94-100, 2010. DOI: 10.1080/09296171003643098.")
    assert formatos.formatar_abnt(CONGRESSO) == "MIHALCEA, R.; TARAU, P. TextRank: bringing order into texts. In: PROCEEDINGS OF EMNLP 2004, 2004. p. 404-411."


def test_apa_livro_artigo_congresso():
    assert formatos.formatar_apa(LIVRO) == "Sinclair, J. (1991). Corpus, Concordance, Collocation. Oxford University Press."
    assert formatos.formatar_apa(ARTIGO) == (
        "Covington, M. A., & McFall, J. D. (2010). Cutting the Gordian knot: the moving-average type-token ratio (MATTR). "
        "Journal of Quantitative Linguistics, 17(2), 94–100. https://doi.org/10.1080/09296171003643098")
    assert formatos.formatar_apa(CONGRESSO) == "Mihalcea, R., & Tarau, P. (2004). TextRank: bringing order into texts. In Proceedings of EMNLP 2004 (pp. 404–411)."


def test_html_marca_titulo_e_escapa():
    abnt = formatos.formatar_abnt(LIVRO, html=True)
    assert "<b>Corpus, Concordance, Collocation</b>" in abnt
    apa = formatos.formatar_apa(ARTIGO, html=True)
    assert "<i>Journal of Quantitative Linguistics</i>, <i>17</i>(2)" in apa
    assert "McFall, J. D. (2010)" in apa and "&amp;" in apa  # & escapado
    assert 'href="https://doi.org/10.1080/09296171003643098"' in formatos.formatar_abnt(ARTIGO, html=True)


def test_bibtex_chave_e_campos():
    assert formatos.chave_bibtex(LIVRO) == "sinclair1991corpus"
    assert formatos.chave_bibtex(ARTIGO) == "covington2010cutting"
    assert formatos.chave_bibtex(CONGRESSO) == "mihalcea2004textrank"
    bib = formatos.formatar_bibtex(ARTIGO)
    assert bib.startswith("@article{covington2010cutting,")
    assert "author = {Covington, M. A. and McFall, J. D.}" in bib
    assert "pages = {94--100}" in bib and "doi = {10.1080/09296171003643098}" in bib
    assert formatos.formatar_bibtex(LIVRO).startswith("@book{sinclair1991corpus,")
    assert "booktitle = {Proceedings of EMNLP 2004}" in formatos.formatar_bibtex(CONGRESSO)
    assert formatos.formatar_bibtex(CONGRESSO).startswith("@inproceedings{")


def test_bibtex_chave_ascii_e_minuscula():
    ref = {"autores": ["Spärck Jones, K."], "ano": 1972, "titulo": "A statistical interpretation", "tipo": "artigo", "veiculo": "J"}
    assert formatos.chave_bibtex(ref) == "sparckjones1972a"
    ref2 = {"autores": ["Reinert, M."], "ano": 1983, "titulo": "L'analyse des données", "tipo": "artigo", "veiculo": "J"}
    assert formatos.chave_bibtex(ref2) == "reinert1983lanalyse"


def test_et_al_particula_e_chaves_unicas():
    ref = {"autores": ["Auer, C."], "et_al": True, "ano": 2024, "titulo": "Docling", "tipo": "preprint", "veiculo": "arXiv"}
    assert formatos.formatar_abnt(ref).startswith("AUER, C. et al. Docling.")
    assert formatos.formatar_apa(ref).startswith("Auer, C., et al. (2024).")
    assert "and others" in formatos.formatar_bibtex(ref)
    luxburg = {"autores": ["von Luxburg, U."], "ano": 2007, "titulo": "A tutorial", "tipo": "artigo", "veiculo": "S"}
    assert formatos.formatar_abnt(luxburg).startswith("LUXBURG, U. von. A tutorial.")
    assert formatos.chaves_bibtex_unicas([LIVRO, LIVRO, LIVRO]) == ["sinclair1991corpus", "sinclair1991corpusa", "sinclair1991corpusb"]


def test_formato_invalido():
    with pytest.raises(ValueError):
        formatos.formatar(LIVRO, "chicago")


def test_todas_as_referencias_do_catalogo_formatam_nos_tres_estilos():
    for ref in svc.carregar()["referencias"].values():
        for formato in ("abnt", "apa", "bibtex"):
            texto = formatos.formatar(ref, formato)
            assert str(ref["ano"]) in texto and texto.strip()
        for texto in (formatos.formatar_abnt(ref), formatos.formatar_apa(ref)):
            assert not re.search(r"(?<!\.)\.\.(?!\.)", texto), ref["chave"]  # sem ponto duplicado (reticências do título são válidas)


# ---------------------------------------------------------------- API
def test_api_catalogo_e_filtros(client):
    r = client.get("/api/metodologia")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] == len(corpo["analises"]) >= 30
    assert "Linguística de corpus" in corpo["familias"]
    so_plan = client.get("/api/metodologia", params={"status": "planejado"}).json()
    assert so_plan["total"] and all(a["status"] == "planejado" for a in so_plan["analises"])
    fam = client.get("/api/metodologia", params={"familia": "redes"}).json()
    assert {a["id"] for a in fam["analises"]} == {"similitude", "rede_coocorrencia", "rede_comunidades_centralidade"}
    assert client.get("/api/metodologia", params={"status": "pronto"}).status_code == 422
    assert client.get("/api/metodologia", params={"familia": "inexistente"}).json()["total"] == 0


def test_api_analise_por_id(client):
    a = client.get("/api/metodologia/keyness").json()
    assert a["id"] == "keyness" and a["referencias"][0]["autores"]
    assert client.get("/api/metodologia/nao_existe").status_code == 404


def test_api_referencias_formatos_ordenacao_e_deduplicacao(client):
    # similaridade e keyness_referencia_externa/keyness compartilham referências: união sem repetir
    r = client.get("/api/metodologia/referencias", params={"formato": "abnt", "ids": "keyness,keyness_referencia_externa,dicionario_codebook"}).json()
    chaves = [x["chave"] for x in r["referencias"]]
    assert len(chaves) == len(set(chaves))
    assert {"scott1997", "rayson2000", "hardie2014", "grimmer2013", "benoit2018"} <= set(chaves)
    ordem = [(_sem_acento(x["texto"].split(",")[0]), svc.carregar()["referencias"][x["chave"]]["ano"]) for x in r["referencias"]]
    assert ordem == sorted(ordem)  # ordem alfabética por sobrenome (ABNT começa pelo sobrenome em caixa alta) e ano
    rayson = next(x for x in r["referencias"] if x["chave"] == "rayson2000")
    assert set(rayson["analises"]) == {"keyness", "keyness_referencia_externa", "dicionario_codebook"}
    assert rayson["html"] and "RAYSON, P.; GARSIDE, R." in rayson["texto"]
    apa = client.get("/api/metodologia/referencias", params={"formato": "apa", "ids": "kwic"}).json()
    assert apa["total"] == 3 and apa["referencias"][0]["texto"].startswith("Anthony, L. (2024).")
    bib = client.get("/api/metodologia/referencias", params={"formato": "bibtex", "ids": "kwic"}).json()
    assert all(x["texto"].startswith("@") and x["html"] is None for x in bib["referencias"])
    todas = client.get("/api/metodologia/referencias").json()
    assert todas["total"] == len(svc.carregar()["referencias"])
    assert client.get("/api/metodologia/referencias", params={"formato": "chicago"}).status_code == 422
    assert client.get("/api/metodologia/referencias", params={"ids": "xyz"}).status_code == 404


def test_api_downloads(client):
    bib = client.get("/api/metodologia/referencias.bib")
    assert bib.status_code == 200 and "attachment" in bib.headers["content-disposition"]
    chaves = re.findall(r"^@\w+\{([^,]+),", bib.text, re.M)
    assert len(chaves) == len(set(chaves)) == len(svc.carregar()["referencias"])
    txt = client.get("/api/metodologia/referencias.txt", params={"formato": "apa", "ids": "afc"})
    assert txt.status_code == 200 and txt.headers["content-disposition"].endswith('referencias_apa.txt"')
    assert "Benzécri, J.-P. (1973)." in txt.text and "Greenacre, M. (2017)." in txt.text
    assert client.get("/api/metodologia/referencias.txt", params={"formato": "bibtex"}).status_code == 422
    assert client.get("/api/metodologia/referencias.bib", params={"ids": "xyz"}).status_code == 404


def test_api_projeto_marca_analises_usadas_e_parametros(client, projeto):
    pasta = database.pasta_do_projeto(projeto)
    atuais = svc_parametros.carregar(pasta)
    atuais["kwic_janela"] = 7
    svc_parametros.salvar(pasta, atuais)
    db = database.sessao_do_projeto(projeto)
    try:
        db.add(Analise(tipo="resumo", parametros_json="{}", resultado_json="{}"))
        db.add(Analise(tipo="keyness", parametros_json="{}", resultado_json="{}"))
        db.commit()
    finally:
        db.close()
    (pasta / "cache" / "tokens").mkdir(parents=True)
    (pasta / "cache" / "tokens" / "1.json").write_text("{}", encoding="utf-8")

    r = client.get(f"/api/projetos/{projeto}/metodologia")
    assert r.status_code == 200
    corpo = r.json()
    por_id = {a["id"]: a for a in corpo["analises"]}
    assert por_id["diversidade_lexical"]["usada_no_projeto"] and por_id["keyness"]["usada_no_projeto"]
    assert por_id["lematizacao"]["usada_no_projeto"] and por_id["kwic"]["usada_no_projeto"]  # cache/tokens
    assert not por_id["afc"]["usada_no_projeto"] and not por_id["legibilidade"]["usada_no_projeto"]
    assert set(corpo["usadas"]) == {i for i, a in por_id.items() if a["usada_no_projeto"]}
    kwic = next(p for p in por_id["kwic"]["parametros_padrao"] if p.get("parametro") == "kwic_janela")
    assert kwic["valor_projeto"] == 7 and kwic["difere_do_padrao"] is True
    seg = next(p for p in por_id["segmentacao"]["parametros_padrao"] if p.get("parametro") == "segmento_palavras")
    assert seg["valor_projeto"] == 40 and seg["difere_do_padrao"] is False
    # filtros valem também no endpoint do projeto
    so_impl = client.get(f"/api/projetos/{projeto}/metodologia", params={"status": "planejado"}).json()
    assert so_impl["analises"] and all(a["status"] == "planejado" for a in so_impl["analises"])


def test_api_projeto_inexistente(client):
    assert client.get("/api/projetos/nao-existe/metodologia").status_code == 404


def test_paginas_estaticas_existem():
    frontend = Path(RAIZ / "frontend")
    for nome in ("metodologia.html", "metodologia.js", "metodologia.css"):
        assert (frontend / nome).is_file()
    assert "metodologia.html" in (frontend / "index.html").read_text(encoding="utf-8")
