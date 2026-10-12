"""Frente 16 - metadados (16.4), planilha do corpus (16.1), extração por LLM (16.2) e .bib para o bibliometrix (16.3).

Sem rede (httpx simulado) e sem LLM real (provedor simulado). Um projeto sintético com 2 artigos e 1 relatório é processado uma
vez por módulo (``ambiente``); o restante são testes unitários de funções puras.
"""
import io
import json

import httpx
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.services.corpus import bibtex, indice, llm_partes, metadados, online, partes, referencias
from app.services.llm import config

FILLER = ("The analysis of the data shows that the results of the study are consistent with the expectations of the field. " * 12)

ARTIGO1 = f"""<!-- página 1 -->

## Generative AI and Solo Founders: Evidence from a Field Experiment

Maria Souza1, John Smith2 and Ana Lima Costa1

1 Department of Economics, University of Alagoas, Maceió, Brazil
2 Institute of Technology, Massachusetts, USA
Correspondence: maria@ufal.br

Published 2026

## Abstract

This paper aims to investigate how generative artificial intelligence changes the entry of solo founders in digital markets. We study a sample of firms and show that entry rises while quality stays flat across the distribution of ventures in the market.

Keywords: generative AI; entrepreneurship; solo founders

DOI: 10.1234/abcd.2026.001

## 1 Introduction

Entrepreneurship is changing quickly. Our research question is how AI affects entry. We contribute to the literature on entrepreneurial strategy and experimentation. {FILLER}

<!-- página 2 -->

## 2 Method

We collected data on 1,200 startups from a public platform between 2020 and 2025. The sample consists of firms with at least one product launch. {FILLER}

## 3 Results

Entry increased after the release of the tool. {FILLER}

<!-- página 3 -->

## 4 Discussion

One limitation of this study is that it uses a single platform, so results may not generalize to other settings. Future research could examine incorporated firms. {FILLER}

## 5 Conclusion

We conclude that the effect is real. This study has practical implications for policy makers. {FILLER}

## References

1. Acemoglu, D.; Restrepo, P. Automation and New Tasks: How Technology Displaces and Reinstates Labor. J. Econ. Perspect. 2019, 33, 3-30.
2. Autor, D.H. Why Are There Still So Many Jobs? J. Econ. Perspect. 2015, 29, 3-30.
3. Brynjolfsson, E.; Li, D.; Raymond, L. Generative AI at Work. Quarterly Journal of Economics 2025, 140, 889-942.
4. Doe, J.; Roe, R. A study of nothing in particular and its consequences for theory. Working Paper, 2021.
"""

ARTIGO2 = f"""<!-- página 1 -->

## Uma Análise do Uso de Agentes de IA em Pequenos Negócios

João Pereira, Carla Dias e Pedro Nunes

Universidade Federal de Alagoas

## Resumo

Este artigo tem como objetivo analisar o uso de agentes de inteligência artificial por pequenos negócios no Brasil, com base em dados de uma pesquisa nacional realizada em 2025 com microempreendedores individuais.

Palavras-chave: agentes de IA; pequenos negócios; empreendedorismo

## 1 Introdução

O uso de agentes de IA cresce rapidamente. {FILLER}

<!-- página 2 -->

## 2 Metodologia

Os dados foram coletados por meio de questionário aplicado a 800 empresas. {FILLER}

## 3 Resultados

Os resultados mostram adoção crescente. {FILLER}

## 4 Conclusão

Concluímos que a adoção é desigual. Pesquisas futuras devem investigar os efeitos de longo prazo. {FILLER}

## Referências

Silva, A. B. (2020). Agentes de IA e pequenos negócios no Brasil. Revista de Administração, 55(2), 100-120.

Souza, C.; Lima, D. (2019). Empreendedorismo digital: um panorama. Revista de Negócios, 10(1), 1-20.

Oliveira, E. F., Santos, G. H., & Costa, I. J. (2021). Inteligência artificial nas empresas. Journal of Business, 33(4), 200-215.
"""

RELATORIO = f"""<!-- página 1 -->

## Annual Report on Small Business AI Adoption

## Executive Summary

Adoption of AI tools among small firms is uneven across regions. {FILLER}

## Findings

{FILLER}

## References

Organisation for Economic Co-operation and Development (2024). SME digitalisation to manage shocks and transitions: survey results. OECD Publishing, Paris.
"""

INDICE_CSV = (
    "ID,Citação,Ano,Trilha candidata,URL da fonte,URL do PDF,Estado,Ficheiro,Bytes,Autor/produtor (extraído da citação),Título (extraído da citação)\n"
    'R001,"Souza, Maria; Smith, John; Lima Costa, Ana. Generative AI and Solo Founders: Evidence from a Field Experiment. Journal of Test Studies, 12(3), 45-67 (2026). DOI: 10.1234/abcd.2026.001.",2026,branca candidata,https://example.org/a,https://example.org/a.pdf,PDF descarregado,artigo_um.pdf,100,"Souza, Maria; Smith, John; Lima Costa, Ana",Generative AI and Solo Founders: Evidence from a Field Experiment\n'
    'R002,"[QP1] Pereira, João et al. Uma Análise do Uso de Agentes de IA em Pequenos Negócios. SBC 2025.",2025,cinzenta/candidata a classificar,https://example.org/b,,PDF descarregado,artigo_dois.pdf,100,"[QP1] Pereira, João et al",Uma Análise do Uso de Agentes de IA em Pequenos Negócios\n'
    'R003,"OECD. Annual Report on Small Business AI Adoption",2024,Cinzenta — candidata,https://example.org/c,,PDF descarregado,relatorio.pdf,100,OECD,Annual Report on Small Business AI Adoption\n'
    'R004,"Alguém. Documento sem arquivo",2020,branca candidata,,,Sem PDF,,0,Alguém,Documento sem arquivo\n'
)


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    base = tmp_path_factory.mktemp("f16")
    mp = pytest.MonkeyPatch()
    mp.setenv("RAIOX_PROJETOS_DIR", str(base / "projetos"))
    mp.setenv("RAIOX_CONFIG_DIR", str(base / "cfg"))
    pasta = base / "artigos"
    pasta.mkdir()
    (pasta / "artigo_um.md").write_text(ARTIGO1, encoding="utf-8")
    (pasta / "artigo_dois.md").write_text(ARTIGO2, encoding="utf-8")
    (pasta / "relatorio.md").write_text(RELATORIO, encoding="utf-8")
    with TestClient(app) as c:
        r = c.post("/api/projetos", json={"nome": "f16", "pasta_origem": str(pasta)})
        assert r.status_code == 201, r.text
        slug = r.json()["slug"]
        r = c.post(f"/api/projetos/{slug}/executar?sincrono=1")
        assert r.status_code == 200, r.text
        yield {"c": c, "slug": slug, "base": base}
    for engine in list(database._engines.values()):
        engine.dispose()
    database._engines.clear()
    mp.undo()


def _url(amb, caminho):
    return f"/api/projetos/{amb['slug']}/{caminho}"


def _docs(amb):
    return {d["arquivo"]: d for d in amb["c"].get(_url(amb, "metadados")).json()["documentos"]}


# =============== 16.4 metadados do texto ===============

def test_extrai_titulo_autores_doi_palavras_chave_e_resumo_do_texto():
    resumo = ("This paper aims to investigate how generative artificial intelligence changes the entry of solo founders in digital markets. "
              "We study a sample of firms and show that entry rises while quality stays flat.")
    r = metadados.extrair_do_texto(ARTIGO1, resumo, "en")
    assert r["titulo"]["valor"] == "Generative AI and Solo Founders: Evidence from a Field Experiment"
    assert r["autores"]["valor"] == ["Souza, Maria", "Smith, John", "Costa, Ana Lima"]  # e-mail, números e "and" removidos
    assert r["doi"]["valor"] == "10.1234/abcd.2026.001"
    assert r["palavras_chave"]["valor"] == ["generative AI", "entrepreneurship", "solo founders"]
    assert any("Department of Economics" in a for a in r["afiliacoes"]["valor"])
    assert not any("@" in a for a in r["afiliacoes"]["valor"])
    assert r["ano"]["valor"] == 2026
    assert r["resumo"]["valor"].startswith("This paper aims")
    assert r["idioma"]["valor"] == "en"


def test_titulo_generico_e_ignorado_e_autores_colados_por_marcas():
    md = "<!-- página 1 -->\n\n## Abstract\n\n## Generative AI Fuels Solo Entrepreneurship, but Teams Still Lead\n\nHyunso Kim∗ Hyo Kang† Jaeyong Song‡ May 12, 2026\n\n## Abstract\n\nTexto.\n"
    r = metadados.extrair_do_texto(md)
    assert r["titulo"]["valor"].startswith("Generative AI Fuels")
    assert r["autores"]["valor"] == ["Kim, Hyunso", "Kang, Hyo", "Song, Jaeyong"]


def test_palavras_chave_em_portugues_e_espanhol():
    r = metadados.extrair_do_texto(ARTIGO2)
    assert r["palavras_chave"]["valor"] == ["agentes de IA", "pequenos negócios", "empreendedorismo"]
    r = metadados.extrair_do_texto("<!-- página 1 -->\n\n## Un estudio sobre algo importante\n\nPalabras clave: inteligencia artificial; negocios\n")
    assert r["palavras_chave"]["valor"] == ["inteligencia artificial", "negocios"]


def test_resolver_prefere_manual_e_lista_conflito():
    e = {"candidatos": {}, "manual": {}}
    metadados.definir_candidato(e, "ano", "texto", 2024, 0.55)
    metadados.definir_candidato(e, "ano", "indice", 2025, 0.9)
    metadados.definir_candidato(e, "titulo", "texto", "Generative AI at Work", 0.8)
    metadados.definir_candidato(e, "titulo", "indice", "Generative AI at Work: A Study", 0.9)  # variação pequena: sem conflito
    r = metadados.resolver(e)
    assert r["ano"]["valor"] == 2025 and r["ano"]["origem"] == "indice" and r["ano"]["conflito"] is True
    assert r["titulo"]["conflito"] is False
    d = {"documentos": {"a.md": e}}
    assert [c["campo"] for c in metadados.conflitos(d)] == ["ano"]
    r = metadados.editar_manual(d, "a.md", {"ano": 2023})
    assert r["ano"]["valor"] == 2023 and r["ano"]["origem"] == "manual"
    r = metadados.editar_manual(d, "a.md", {"ano": None})
    assert r["ano"]["origem"] == "indice"
    with pytest.raises(ValueError):
        metadados.editar_manual(d, "a.md", {"campo_inexistente": 1})


# =============== 16.4 índice CSV ===============

def test_indice_casa_por_nome_do_arquivo_e_sugere_grupo():
    r = indice.importar(INDICE_CSV.encode("utf-8"), {"artigo_um": "artigo_um.md", "artigo_dois": "artigo_dois.md", "relatorio": "relatorio.md"})
    assert set(r["casados"]) == {"artigo_um.md", "artigo_dois.md", "relatorio.md"}
    assert r["sem_arquivo"] == ["R004"]
    um = r["casados"]["artigo_um.md"]
    assert um["grupo"] == "branca" and um["trilha"] == "branca candidata"
    assert r["casados"]["artigo_dois.md"]["grupo"] == "cinzenta" and r["casados"]["relatorio.md"]["grupo"] == "cinzenta"
    campos = um["campos"]
    assert campos["titulo"][0].startswith("Generative AI and Solo Founders")
    assert campos["autores"][0] == ["Souza, Maria", "Smith, John", "Lima Costa, Ana"]
    assert campos["ano"][0] == 2026 and campos["doi"][0] == "10.1234/abcd.2026.001"
    assert campos["fonte"][0] == "Journal of Test Studies" and campos["volume"][0] == "12" and campos["paginas"][0] == "45-67"
    assert campos["tipo_documento"][0] == "article"
    dois = r["casados"]["artigo_dois.md"]["campos"]
    assert dois["autores"][0] == ["Pereira, João"] and dois["autores"][1] < 0.85  # "et al": confiança menor
    assert r["casados"]["relatorio.md"]["campos"]["autores"][0] == ["OECD"]


def test_indice_sem_coluna_de_arquivo_e_recusado():
    with pytest.raises(ValueError):
        indice.importar(b"Titulo,Ano\nA,2020\n", {})


def test_api_indice_nao_altera_grupo_sozinho_e_confirmacao_aplica(ambiente):
    c, amb = ambiente["c"], ambiente
    c.post(_url(amb, "metadados/extrair"))
    r = c.post(_url(amb, "metadados/importar-indice?nome=indice.csv"), content=INDICE_CSV.encode("utf-8"))
    assert r.status_code == 200, r.text
    rel = r.json()
    assert rel["casados"] == 3 and rel["grupo_aplicado"] is False
    assert {s["grupo_sugerido"] for s in rel["sugestoes_de_grupo"]} == {"branca", "cinzenta"}
    docs = _docs(ambiente)
    assert all(d["grupo"] is None for d in docs.values())  # nada aplicado
    assert docs["artigo_um.md"]["grupo_sugerido"]["valor"] == "branca" and docs["artigo_um.md"]["grupo_difere"] is True
    assert docs["artigo_um.md"]["campos"]["titulo"]["origem"] == "indice"
    r = c.post(_url(amb, "metadados/grupos/confirmar"), json={"documento_ids": [docs["artigo_um.md"]["documento_id"]]})
    assert r.json()["aplicados"] == [{"documento_id": docs["artigo_um.md"]["documento_id"], "de": None, "para": "branca"}]
    docs = _docs(ambiente)
    assert docs["artigo_um.md"]["grupo"] == "branca" and docs["artigo_dois.md"]["grupo"] is None
    assert c.post(_url(amb, "metadados/importar-indice"), content=b"").status_code == 400


def test_api_patch_manual_vence_e_conflitos(ambiente):
    c, amb = ambiente["c"], ambiente
    docs = _docs(ambiente)
    did = docs["artigo_um.md"]["documento_id"]
    r = c.patch(_url(amb, f"metadados/{did}"), json={"titulo": "Título editado à mão", "autores": "Souza, Maria; Smith, John"})
    assert r.status_code == 200, r.text
    campos = r.json()["campos"]
    assert campos["titulo"]["origem"] == "manual" and campos["autores"]["valor"] == ["Souza, Maria", "Smith, John"]
    assert c.patch(_url(amb, f"metadados/{did}"), json={"inexistente": 1}).status_code == 422
    assert c.patch(_url(amb, "metadados/9999"), json={"titulo": "x"}).status_code == 404
    assert c.get(_url(amb, "metadados/conflitos")).status_code == 200
    c.patch(_url(amb, f"metadados/{did}"), json={"titulo": "", "autores": ""})  # volta ao automático


# =============== 16.4 consulta online ===============

def _cliente_simulado(chamadas):
    def tratar(request: httpx.Request):
        chamadas.append(request)
        if "api.crossref.org/works/10.1234" in str(request.url):
            return httpx.Response(200, json={"message": {
                "title": ["Generative AI and Solo Founders"], "author": [{"given": "Maria", "family": "Souza", "affiliation": [{"name": "UFAL"}]}],
                "issued": {"date-parts": [[2026, 3]]}, "container-title": ["Journal of Test Studies"], "volume": "12", "issue": "3",
                "page": "45-67", "type": "journal-article", "DOI": "10.1234/abcd.2026.001", "abstract": "<jats:p>Um resumo.</jats:p>"}})
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(tratar))


def test_online_desligado_por_padrao_e_sem_email_nao_chama_a_rede(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(online, "_cliente", lambda email: _cliente_simulado(chamadas))
    c, amb = ambiente["c"], ambiente
    assert online.carregar_config()["email_contato"] == ""
    r = c.post(_url(amb, "metadados/extrair"))  # padrão: sem consulta online
    assert r.status_code == 200 and "online" not in r.json()
    assert c.post(_url(amb, "metadados/extrair?online=true")).status_code == 409
    assert c.post(_url(amb, "metadados/consultar-online"), json={}).status_code == 409
    with pytest.raises(online.SemEmail):
        online.consultar("10.1234/x")
    assert chamadas == []


def test_online_com_email_consulta_crossref_com_user_agent_educado(ambiente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(online, "_cliente", lambda email: _cliente_simulado(chamadas))
    c, amb = ambiente["c"], ambiente
    assert c.put("/api/config/metadados", json={"email_contato": "email-invalido"}).status_code == 422
    assert c.put("/api/config/metadados", json={"email_contato": "pesquisa@exemplo.org"}).json()["configurado"] is True
    r = c.post(_url(amb, "metadados/extrair?online=true&fonte=crossref"))
    assert r.status_code == 200, r.text
    assert r.json()["online"]["consultados"] >= 1 and r.json()["online"]["com_resposta"] >= 1
    assert all("10.1234" in str(q.url) for q in chamadas)  # só o DOI vai para a API
    assert "mailto=pesquisa%40exemplo.org" in str(chamadas[0].url)
    um = _docs(ambiente)["artigo_um.md"]["campos"]
    assert um["volume"]["origem"] == "online" and um["volume"]["valor"] == "12"
    assert um["resumo"]["alternativas"] or um["resumo"]["origem"] in ("online", "texto")
    c.put("/api/config/metadados", json={"email_contato": ""})


def test_parsers_crossref_e_openalex():
    cr = online.de_crossref({"title": ["T"], "author": [{"given": "A", "family": "B"}], "issued": {"date-parts": [[2020]]}, "type": "proceedings-article"})
    assert cr["autores"] == ["B, A"] and cr["ano"] == 2020 and cr["tipo_documento"] == "conference paper"
    oa = online.de_openalex({"title": "T", "publication_year": 2021, "authorships": [{"author": {"display_name": "Ana Maria Lima"}, "institutions": [{"display_name": "UFAL"}]}],
                             "abstract_inverted_index": {"Hello": [0], "world": [1]}, "type": "preprint"})
    assert oa["autores"] == ["Lima, Ana Maria"] and oa["resumo"] == "Hello world" and oa["tipo_documento"] == "preprint" and oa["afiliacoes"] == ["UFAL"]


# =============== 16.1 partes ===============

def _frases(textos, secoes=None, pagina=1):
    return [{"i": i, "texto": t, "pagina": pagina + i // 3, "secao": (secoes or {}).get(i, "introducao"), "titulo_secao": None} for i, t in enumerate(textos)]


def test_padroes_en_pt_es_para_objetivo_limitacoes_futuros():
    fr = _frases([
        "In this section we describe the weather in the city during the last decade of the study.",
        "This paper aims to investigate how generative AI changes the entry of solo founders into markets.",
        "Este artigo tem como objetivo analisar o uso de agentes de IA por pequenos negócios no Brasil.",
        "El objetivo de este estudio es analizar el uso de agentes de inteligencia artificial en pymes.",
    ])
    r = partes.preencher_padrao(fr, "objetivo", 3, 2.0, len(fr))
    assert [t["frase_i"] for t in r["trechos"]] == [1, 2, 3] and r["metodo"] == "padrao"
    assert all(t["nota"] >= 2.0 and t["regra"] for t in r["trechos"])
    lim = _frases(["One limitation of this study is the single platform used for the sample of firms in the analysis.",
                   "As limitações do estudo incluem o tamanho da amostra e o período curto de observação dos dados."], {0: "discussao", 1: "conclusao"})
    assert len(partes.preencher_padrao(lim, "limitacoes", 3, 2.0, 2)["trechos"]) == 2
    fut = _frases(["Future research could examine incorporated firms and capital intensive industries in other countries."], {0: "conclusao"})
    assert partes.preencher_padrao(fut, "futuros", 3, 2.0, 1)["trechos"][0]["frase_i"] == 0
    assert partes.preencher_padrao(_frases(["Nothing relevant is said in this sentence about anything of interest."]), "limitacoes", 3, 2.0, 1) is None


def test_padroes_perguntas_e_dados_e_limite_de_frases():
    fr = _frases([
        "Our research question is how generative AI affects the entry of solo founders into digital markets.",
        "We hypothesize that entry increases after the release of the tool in the market for software products.",
        "H1: entry rises after the release of the tool among the firms in the sample of the platform.",
        "RQ2 asks whether quality changes among the top ventures in the ranking of the platform over time.",
        "The data were collected from a public platform between 2020 and 2025 using its official interface.",
    ])
    r = partes.preencher_padrao(fr, "perguntas", 3, 2.0, len(fr))
    assert len(r["trechos"]) == 3  # no máximo max_frases
    assert [t["frase_i"] for t in r["trechos"]] == sorted(t["frase_i"] for t in r["trechos"])  # em ordem de posição
    d = partes.preencher_padrao(fr, "dados", 5, 2.0, len(fr))
    assert 4 in [t["frase_i"] for t in d["trechos"]]


def test_parte_por_secao_trunca_no_fim_da_frase_com_reticencias_e_paginas():
    fr = [{"i": i, "texto": f"Frase número {i} da seção de método com texto suficiente para contar caracteres aqui.", "pagina": 2 + i // 5, "secao": "metodos", "titulo_secao": "2 Method"}
          for i in range(30)]
    r = partes.preencher_secao(fr, "metodos", 400)
    t = r["trechos"][0]
    assert t["truncado"] is True and t["texto"].endswith("(…)") and t["texto"].rstrip(" (…)").endswith("aqui.")
    assert t["paginas"] == "p. 2"
    assert partes.preencher_secao(fr, "resultados", 400) is None
    cel = partes.texto_da_celula(r)
    assert cel.startswith("[p. 2]") and partes.texto_da_celula(None) == "não encontrado"


def test_checklists_e_perguntas_nao_entram():
    fr = _frases(["Question: Does the paper discuss the limitations of the work performed by the authors in detail?"])
    assert partes.analisar_documento.__doc__  # a função existe
    assert not partes._elegivel(fr[0])


# =============== 16.1 planilha (API) ===============

def test_planilha_json_tem_partes_secoes_padroes_e_nao_encontrado(ambiente):
    c, amb = ambiente["c"], ambiente
    c.post(_url(amb, "metadados/extrair"))
    r = c.get(_url(amb, "corpus/planilha"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert [p["rotulo"] for p in d["partes"]][:4] == ["Resumo", "Introdução", "Objetivo", "Perguntas de pesquisa/hipóteses"]
    assert len(d["partes"]) == 13 and d["documentos"] == 3
    linhas = {l["arquivo"]: l for l in d["linhas"]}
    um = linhas["artigo_um.md"]["partes"]
    assert um["resumo"]["metodo"] == "secao" and um["resumo"]["texto"].startswith("[p. 1] This paper aims")
    assert um["objetivo"]["metodo"] == "padrao" and "[p. 1]" in um["objetivo"]["texto"]
    assert "Our research question" in um["perguntas"]["texto"]
    assert "single platform" in um["limitacoes"]["texto"] and "[p. 3]" in um["limitacoes"]["texto"]
    assert "Future research could" in um["futuros"]["texto"]
    assert "1,200 startups" in um["dados"]["texto"] or "sample consists" in um["dados"]["texto"]
    assert "We contribute" in um["contribuicoes"]["texto"] or "implications" in um["contribuicoes"]["texto"]
    dois = linhas["artigo_dois.md"]["partes"]
    assert "tem como objetivo" in dois["objetivo"]["texto"] and "Pesquisas futuras" in dois["futuros"]["texto"]
    rel = linhas["relatorio.md"]["partes"]
    assert rel["objetivo"]["texto"] == "não encontrado" and rel["limitacoes"]["metodo"] == "nao"  # nunca inventa
    assert rel["metodo"]["texto"] == "não encontrado"
    cob = d["cobertura"]
    assert cob["resumo"]["secao"] == 3 and cob["limitacoes"]["nao"] >= 1
    assert all(sum(v.values()) == 3 for v in cob.values())


def test_celula_traz_pagina_secao_regra_e_link_de_contexto(ambiente):
    c, amb = ambiente["c"], ambiente
    d = _docs(ambiente)["artigo_um.md"]["documento_id"]
    r = c.get(_url(amb, f"corpus/planilha/celula?documento_id={d}&parte=limitacoes"))
    assert r.status_code == 200, r.text
    t = r.json()["trechos"][0]
    assert t["pagina"] == 3 and t["metodo"] == "padrao" and t["regra"] and t["secao"] == "discussao"
    assert t["posicao"] is not None and t["contexto"].endswith(f"documento_id={d}&posicao={t['posicao']}")
    ctx = c.get(t["contexto"]).json()
    assert "limitation" in (ctx["esquerda"] + ctx["termo"] + ctx["direita"]).lower() or ctx["pagina"] == 3
    assert c.get(_url(amb, f"corpus/planilha/celula?documento_id={d}&parte=xx")).status_code == 404


def _xlsx(amb):
    r = amb["c"].get(_url(amb, "exportar/planilha-corpus.xlsx"))
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    return openpyxl.load_workbook(io.BytesIO(r.content))


def test_xlsx_abas_colunas_formatacao_e_rastreabilidade(ambiente):
    wb = _xlsx(ambiente)
    assert wb.sheetnames == ["Corpus", "Rastreabilidade", "Metadados", "Cobertura", "LEIA-ME"]
    ws = wb["Corpus"]
    cab = [c.value for c in ws[1]]
    assert cab[:7] == ["Rótulo", "Arquivo", "Ano", "Grupo", "Título", "Autores", "DOI"]
    for parte in ("Resumo", "Introdução", "Objetivo", "Perguntas de pesquisa/hipóteses", "Referencial teórico", "Método", "Dados/amostra/contexto",
                  "Resultados", "Discussão", "Conclusão", "Limitações", "Trabalhos futuros", "Contribuições/implicações", "Sugestões LLM (não aceitas)"):
        assert parte in cab
    assert ws.freeze_panes == "B2" and ws.auto_filter.ref
    linhas = {r[1].value: r for r in ws.iter_rows(min_row=2)}
    col = {n: i for i, n in enumerate(cab)}
    assert linhas["relatorio.md"][col["Objetivo"]].value == "não encontrado"
    assert linhas["artigo_um.md"][col["Limitações"]].value.startswith("[p. 3]")
    assert linhas["artigo_um.md"][col["Limitações"]].alignment.wrap_text
    wr = wb["Rastreabilidade"]
    cab_r = [c.value for c in wr[1]]
    assert cab_r == ["Documento", "Arquivo", "Parte", "Trecho", "Página", "Seção de origem", "Regra/padrão", "Método", "Nota"]
    linhas_r = [[c.value for c in r] for r in wr.iter_rows(min_row=2)]
    assert {l[7] for l in linhas_r} <= {"seção", "padrão", "llm"} and {"seção", "padrão"} <= {l[7] for l in linhas_r}
    assert any(l[2] == "Limitações" and l[4] == 3 and l[6] for l in linhas_r)
    assert all(l[1] for l in linhas_r) and any(l[8] is not None for l in linhas_r if l[7] == "padrão")
    assert wb["Metadados"].max_row == 4 and "Planilha do corpus" in "".join(str(c.value) for c in wb["LEIA-ME"]["A"])


def test_xlsx_neutraliza_injecao_de_formula(ambiente):
    c, amb = ambiente["c"], ambiente
    did = _docs(ambiente)["artigo_dois.md"]["documento_id"]
    c.patch(_url(amb, f"metadados/{did}"), json={"titulo": '=HYPERLINK("http://x","clique")', "autores": "+cmd|' /C calc'!A0"})
    wb = _xlsx(amb)
    ws = wb["Corpus"]
    cab = [x.value for x in ws[1]]
    linha = [r for r in ws.iter_rows(min_row=2) if r[1].value == "artigo_dois.md"][0]
    assert linha[cab.index("Título")].value.startswith("'=HYPERLINK")
    assert linha[cab.index("Autores")].value.startswith("'+cmd")
    for aba in wb:  # nenhuma célula de texto começa com = + - @ (fora os apóstrofos)
        for row in aba.iter_rows():
            for cel in row:
                assert not (isinstance(cel.value, str) and cel.value[:1] in "=+-@"), (aba.title, cel.coordinate)
    c.patch(_url(amb, f"metadados/{did}"), json={"titulo": "", "autores": ""})


# =============== 16.2 LLM ===============

BLOCOS = [
    {"pagina": 4, "secao": "discussao", "titulo_secao": "Discussion", "incluir": True,
     "texto": "Our results are strong. A second limitation concerns the use of a single plat-\nform for the whole sample of firms."},
    {"pagina": 5, "secao": "conclusao", "titulo_secao": "Conclusion", "incluir": True, "texto": "Further studies should test other countries and sectors of the economy."},
    {"pagina": 9, "secao": "referencias", "titulo_secao": "References", "incluir": False, "texto": "Hidden reference sentence that must never be found by the check."},
]


def test_conferencia_aceita_frase_real_com_hifenizacao_e_acha_a_pagina():
    ok, rel = llm_partes.conferir_trechos({"limitacoes": ["A second limitation concerns the use of a single platform for the whole sample of firms."],
                                           "futuros": ["Further studies should test other countries and sectors of the economy."]}, BLOCOS)
    assert rel["aceitos"] == 2 and rel["descartados"] == []
    lim = ok["limitacoes"][0]
    assert lim["pagina"] == 4 and "plat-" in lim["texto"].replace("\n", " ") or "platform" in lim["texto"]  # texto salvo = o do documento
    assert ok["futuros"][0]["pagina"] == 5 and ok["futuros"][0]["secao"] == "conclusao"


def test_conferencia_rejeita_frase_inventada_alterada_ou_de_referencias():
    ok, rel = llm_partes.conferir_trechos({"limitacoes": [
        "The authors admit that their sample is too small to say anything useful about the population.",  # inventada
        "A second limitation concerns the use of a single website for the whole sample of firms.",         # palavra trocada
        "Hidden reference sentence that must never be found by the check.",                                  # só em referências
        "A second limitation concerns ... the whole sample of firms.",                                      # reticências
        "Too short.",
    ]}, BLOCOS)
    assert ok.get("limitacoes") == [] and rel["aceitos"] == 0 and len(rel["descartados"]) >= 4


class ProvedorSimulado:
    nome = "simulado"
    modelo = "mock-1"

    def __init__(self, resposta):
        self.resposta = resposta
        self.pedidos = []

    def gerar(self, system, user):
        self.pedidos.append(user)
        return {"texto": self.resposta, "modelo": self.modelo, "uso": {}, "request_id": None}


def test_extrair_documento_guarda_so_o_que_existe_e_aceitar_vai_para_a_planilha(ambiente, monkeypatch):
    c, amb = ambiente["c"], ambiente
    docs = _docs(ambiente)
    # 409 com o LLM desligado (padrão)
    assert config.carregar()["habilitado"] is False
    assert c.post(_url(amb, "corpus/planilha/llm/extrair"), json={}).status_code == 409
    config.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "mock"}})
    resposta = json.dumps({"objetivo": ["This paper aims to investigate how generative artificial intelligence changes the entry of solo founders in digital markets.",
                                        "Esta frase foi inventada pelo modelo e não existe em lugar nenhum do documento analisado."],
                           "limitacoes": ["One limitation of this study is that it uses a single platform, so results may not generalize to other settings."]})
    prov = ProvedorSimulado("```json\n" + resposta + "\n```")
    monkeypatch.setattr(llm_partes, "provedor_configurado", lambda cfg=None: prov)
    did = docs["relatorio.md"]["documento_id"]  # relatório: texto sem essas frases -> tudo descartado
    r = c.post(_url(amb, "corpus/planilha/llm/extrair"), json={"documento_ids": [did], "partes": ["objetivo", "limitacoes"]})
    assert r.status_code == 200, r.text
    assert r.json()["sugestoes"] == 0 and len(r.json()["documentos"][0]["descartados"]) == 3
    did1 = docs["artigo_um.md"]["documento_id"]
    r = c.post(_url(amb, "corpus/planilha/llm/extrair"), json={"documento_ids": [did1], "partes": ["limitacoes", "objetivo"]})
    assert r.status_code == 200, r.text
    assert r.json()["sugestoes"] == 2 and len(r.json()["documentos"][0]["descartados"]) == 1  # a inventada caiu
    assert "TEXTO DO DOCUMENTO" in prov.pedidos[-1] and len(prov.pedidos[-1]) < 12000  # contexto limitado
    cel = c.get(_url(amb, f"corpus/planilha/celula?documento_id={did1}&parte=objetivo")).json()
    assert len(cel["sugestoes"]) == 1 and cel["sugestoes"][0]["origem"] == "LLM (modelo)" and cel["sugestoes"][0]["pagina"] == 1
    # não aceita: aparece na coluna "Sugestões LLM (não aceitas)" e não na célula
    wb = _xlsx(amb)
    ws = wb["Corpus"]
    cab = [x.value for x in ws[1]]
    linha = [rw for rw in ws.iter_rows(min_row=2) if rw[1].value == "artigo_um.md"][0]
    assert "Objetivo: [p. 1]" in (linha[cab.index("Sugestões LLM (não aceitas)")].value or "")
    # aceita: entra na célula marcada "LLM (modelo)" e na rastreabilidade com método llm
    r = c.post(_url(amb, f"corpus/planilha/llm/{did1}/objetivo"), json={"acao": "aceitar"})
    assert r.status_code == 200 and r.json()["sugestoes"][0]["status"] == "aceita"
    wb = _xlsx(amb)
    ws = wb["Corpus"]
    linha = [rw for rw in ws.iter_rows(min_row=2) if rw[1].value == "artigo_um.md"][0]
    assert "[LLM (modelo)]" in linha[cab.index("Objetivo")].value
    assert "Objetivo: [p. 1]" not in (linha[cab.index("Sugestões LLM (não aceitas)")].value or "")
    assert any(rw[2].value == "Objetivo" and rw[7].value == "llm" for rw in wb["Rastreabilidade"].iter_rows(min_row=2))
    assert c.post(_url(amb, f"corpus/planilha/llm/{did1}/dados"), json={"acao": "aceitar"}).status_code == 404  # sem sugestões nessa célula
    assert c.post(_url(amb, f"corpus/planilha/llm/{did1}/objetivo"), json={"acao": "xx"}).status_code == 422
    config.salvar({"habilitado": False})


def test_resposta_do_llm_sem_json_vira_erro_502_ou_formato(ambiente, monkeypatch):
    from app.services.llm.provedores import ErroLLM

    c, amb = ambiente["c"], ambiente
    config.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "mock"}})
    monkeypatch.setattr(llm_partes, "provedor_configurado", lambda cfg=None: ProvedorSimulado("não sei responder"))
    did = _docs(ambiente)["artigo_um.md"]["documento_id"]
    r = c.post(_url(amb, "corpus/planilha/llm/extrair"), json={"documento_ids": [did]})
    assert r.status_code == 200 and r.json()["erros"] and r.json()["sugestoes"] == 0
    config.salvar({"habilitado": False})
    assert issubclass(ErroLLM, Exception)


# =============== 16.3 referências ===============

def test_separa_referencias_numeradas_com_continuacao():
    linhas = [("texto", "1. Acemoglu, D.; Restrepo, P. Automation and New Tasks. J. Econ. Perspect. 2019, 33, 3-30. [CrossRef]"),
              ("vazio", ""),
              ("texto", "2. Autor, D.H. Why Are There Still So Many Jobs? The History and Future of Workplace Automation."),
              ("texto", "J. Econ. Perspect. 2015, 29, 3-30."),
              ("texto", "[3] Brynjolfsson, E.; Li, D. Generative AI at Work. Q. J. Econ. 2025, 140, 889-942.")]
    itens = referencias.separar(linhas)
    assert len(itens) == 3
    assert itens[1].endswith("J. Econ. Perspect. 2015, 29, 3-30.") and "[CrossRef]" not in itens[0] and not itens[2].startswith("[3]")


def test_separa_referencias_autor_ano_uma_por_linha_e_linha_colada():
    linhas = [("texto", "Silva, A. B. (2020). Agentes de IA e pequenos negócios no Brasil. Revista de Administração, 55(2), 100-120."),
              ("texto", "Souza, C. & Lima, D. (2019). Empreendedorismo digital: um panorama. Revista de Negócios, 10(1), 1-20."),
              ("texto", "Silva, A. B. (2020). Agentes de IA e pequenos negócios no Brasil. Revista de Administração, 55(2), 100-120. "
                        "Souza, C. & Lima, D. (2019). Empreendedorismo digital: um panorama. Revista de Negócios, 10(1), 1-20. "
                        "Oliveira, E. F., Santos, G. H., & Costa, I. J. (2021). Inteligência artificial nas empresas. Journal of Business, 33(4), 200-215.")]
    itens = referencias.separar(linhas)
    assert len(itens) == 5 and itens[2].startswith("Silva, A. B.") and itens[4].startswith("Oliveira, E. F.")


def test_interpreta_apa_mdpi_e_acl_e_formata_no_estilo_scopus():
    r = referencias.interpretar("Silva, A. B., & Costa, I. J. (2020). Agentes de IA e pequenos negócios. Revista de Administração, 55(2), 100-120. https://doi.org/10.1000/xyz123")
    assert r["parseada"] and r["autores"] == ["Silva, A. B.", "Costa, I. J."] and r["ano"] == 2020 and r["doi"] == "10.1000/xyz123"
    assert r["titulo"] == "Agentes de IA e pequenos negócios" and r["fonte"] == "Revista de Administração" and (r["volume"], r["numero"], r["paginas"]) == ("55", "2", "100-120")
    assert referencias.formato_scopus(r) == "Silva, A.B., Costa, I.J., Agentes de IA e pequenos negócios (2020) Revista de Administração, 55 (2), pp. 100-120"
    m = referencias.interpretar("Acemoglu, D.; Restrepo, P. Automation and New Tasks: How Technology Displaces Labor. J. Econ. Perspect. 2019, 33, 3-30.")
    assert m["parseada"] and m["ano"] == 2019 and m["autores"][1] == "Restrepo, P." and m["volume"] == "33" and m["paginas"] == "3-30"
    a = referencias.interpretar("Josh Achiam, Steven Adler, and Sandhini Agarwal. 2023. Gpt-4 technical report. arXiv preprint arXiv:2303.08774.")
    assert a["ano"] == 2023 and a["autores"][0] == "Achiam, Josh" and a["titulo"].lower().startswith("gpt-4")
    nao = referencias.interpretar("OECD, Agentic AI in organisations: early insights, https://www.oecd.org/x, accessed: 2025-09-10.")
    assert nao["parseada"] is False
    assert ";" not in referencias.formato_scopus(nao) and referencias.formato_scopus(nao).startswith("OECD")  # mantém o texto bruto


# =============== 16.3 .bib ===============

def test_escape_bibtex_completo_e_minimo():
    assert bibtex.escapar("R&D 100% {x} a_b #1 $5 ~ ^") == r"R\&D 100\% \{x\} a\_b \#1 \$5 \textasciitilde{} \textasciicircum{}"
    assert bibtex.escapar("R&D 50% {x}", "minimo") == r"R&D 50% \{x\}"


def test_autor_bib_iniciais_e_organizacao():
    assert bibtex.autor_bib("Souza, Maria Clara") == "Souza, M.C."
    assert bibtex.autor_bib("Smith, John-Paul") == "Smith, J.P."
    assert bibtex.autor_bib("OECD") == "{OECD}"
    assert bibtex.autor_bib("Pop Cohuţ, Ioana") == "Pop Cohuţ, I."


def test_chave_de_citacao_unica_e_ascii():
    usados = set()
    ks = [bibtex.chave_citacao(["Müller, Hans"], 2020, usados), bibtex.chave_citacao(["Muller, H."], 2020, usados), bibtex.chave_citacao([], None, usados)]
    assert ks[0] == "Muller2020" and ks[1] == "Muller2020a" and ks[2] == "Docnd"


def test_tipos_de_entrada_e_campos_scopus():
    class D:
        arquivo = "x/a.md"
        ano = None

    ref = referencias.interpretar("Silva, A. B. (2020). Agentes de IA e pequenos negócios. Revista de Administração, 55(2), 100-120.")
    base = {"titulo": "Um título com & e _", "autores": ["Souza, Maria", "OECD"], "ano": 2024, "fonte": "Journal X", "doi": "10.1/x", "idioma": "pt",
            "resumo": "Resumo {com chaves}.", "palavras_chave": ["a", "b"], "afiliacoes": ["UFAL", "MIT"]}
    casos = {"article": ("ARTICLE", "Article"), "conference paper": ("CONFERENCE", "Conference Paper"), "book": ("BOOK", "Book"),
             "book chapter": ("INCOLLECTION", "Book Chapter"), "report": ("MISC", "Report"), "preprint": ("MISC", "Preprint"),
             "working paper": ("MISC", "Working Paper"), "document": ("MISC", "Document")}
    for tipo, (entrada, dt) in casos.items():
        e = bibtex.entrada_do_documento(D, {**base, "tipo_documento": tipo}, [ref])
        assert e["tipo"] == entrada and e["campos"]["document_type"] == dt
    e = bibtex.entrada_do_documento(D, {**base, "tipo_documento": "article"}, [ref])
    c = e["campos"]
    assert c["author"] == "Souza, M. and {OECD}" and c["affiliations"] == "UFAL; MIT" and c["author_keywords"] == "a; b" and c["language"] == "Portuguese"
    assert c["source"] == "Scopus" and "Raio-X" in c["note"] and not any(ch.isdigit() for ch in c["note"]) and "keywords" not in c
    assert c["references"] == "Silva, A.B., Agentes de IA e pequenos negócios (2020) Revista de Administração, 55 (2), pp. 100-120"
    assert bibtex.entrada_do_documento(D, {**base, "tipo_documento": "article"}, [], "copiar")["campos"]["keywords"] == "a; b"
    sem_fonte = bibtex.entrada_do_documento(D, {"titulo": "Relatório", "autores": ["OECD"], "tipo_documento": "report"}, [])
    assert sem_fonte["campos"]["journal"] == "OECD"  # literatura cinzenta: a organização como fonte
    txt = bibtex.para_bibtex([e], "completo")
    assert txt.startswith("@ARTICLE{Souza2024,") and r"title = {Um título com \& e \_}" in txt and r"abstract = {Resumo \{com chaves\}.}" in txt
    assert "author = {Souza, M. and {OECD}}" in txt and txt.rstrip().endswith("}")


def test_bib_via_api_utf8_campos_e_referencias(ambiente):
    c, amb = ambiente["c"], ambiente
    c.post(_url(amb, "metadados/extrair"))
    c.post(_url(amb, "metadados/importar-indice"), content=INDICE_CSV.encode("utf-8"))
    r = c.get(_url(amb, "exportar/bibliometrix.bib"))
    assert r.status_code == 200 and "charset=utf-8" in r.headers["content-type"]
    txt = r.content.decode("utf-8")
    assert txt.count("@") >= 2 and "@ARTICLE{" in txt and "@MISC{" in txt
    assert "Pereira, J." in txt and "Análise" in txt and "source = {Scopus}" in txt and "document_type = {Article}" in txt
    um = [b for b in txt.split("@") if "Solo Founders" in b][0]
    for campo in ("author", "title", "journal", "year", "volume", "number", "pages", "doi", "affiliations", "abstract", "author_keywords", "references", "language", "document_type"):
        assert f"\t{campo} = {{" in um, campo
    assert "Acemoglu, D., Restrepo, P., Automation and New Tasks" in um and "(2019) J. Econ. Perspect" in um
    refs = [x for x in um.split("\treferences = {")[1].split("},\n")[0].split("; ") if x]
    assert len(refs) == 4  # 4 referências numeradas do artigo 1
    r2 = c.get(_url(amb, "exportar/bibliometrix.bib?escape=minimo&palavras_indexadas=copiar"))
    assert "\tkeywords = {" in r2.text
    rr = c.get(_url(amb, "corpus/referencias")).json()["documentos"]
    assert {d["arquivo"]: d["referencias"] for d in rr} == {"artigo_um.md": 4, "artigo_dois.md": 3, "relatorio.md": 0}


def test_api_sem_pipeline_devolve_409(client, projeto):
    assert client.get(f"/api/projetos/{projeto}/exportar/planilha-corpus.xlsx").status_code == 409
    assert client.get(f"/api/projetos/{projeto}/exportar/bibliometrix.bib").status_code == 409

