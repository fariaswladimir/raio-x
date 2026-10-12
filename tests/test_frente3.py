"""Frente 3: limpeza e estrutura (seções, referências, exclusão, cabeçalho/rodapé, URLs, hifenização). Sem Docling."""
import json

import pytest

from app.services import parametros as svc_parametros
from app.services.limpeza_texto import classificar_titulo, corrigir_hifenizacao, limpar_texto, processar, texto_para_inspecao

PROSA = (
    "The analysis of the data shows that the results of the study are consistent with the theory "
    "and that the effects of the new method on the performance of the teams are large. "
)
REFS = [
    "Acemoglu, D. (2025). The simple macroeconomics of ai. Economic Policy, 40(121):13-58.",
    "Bhave, M. P. (1994). A process model of entrepreneurial venture creation. Journal of Business Venturing, 9(3):223-242.",
    "Bick, A., Blandin, A., and Deming, D. J. (2024). The rapid adoption of generative ai. Working Paper 32966, NBER.",
    "Brynjolfsson, E., Li, D., and Raymond, L. R. (2025). Generative ai at work. Quarterly Journal of Economics, 140(2):889-942.",
    "Cai, J. J., Gu, X., Sheng, L. (2025). Ai as co-founder. arXiv preprint arXiv:2512.06506.",
    "Contigiani, A. (2023). Experimentation and appropriability. Strategic Management Journal, 44(9):2128-2174.",
    "Fleming, L. (2001). Recombinant uncertainty in technological search. Management Science, 47(1):117-132.",
    "Gans, J. S., Stern, S., and Wu, J. (2019). Foundations of entrepreneurial strategy. Strategic Management Journal, 40(5):736-756.",
]


def pagina(n: int, texto: str) -> str:
    return f"\n\n<!-- página {n} -->\n\n{texto}"


def md_paginas(*textos: str) -> str:
    return "<!-- Fonte: x.pdf | Conversão: Docling -->\n" + "".join(pagina(i + 1, t) for i, t in enumerate(textos))


def secoes_tipos(r: dict) -> list[str]:
    return [s["tipo"] for s in r["secoes"]]


def blocos_de(r: dict, tipo: str) -> list[dict]:
    return [b for b in r["blocos"] if b["secao"] == tipo]


@pytest.fixture()
def artigo_com_referencias() -> str:
    return md_paginas(
        "## Um Título de Artigo\n\nAutores aqui.\n\n## Abstract\n\n" + PROSA * 3 + "\n\n## 1 Introduction\n\n" + PROSA * 4,
        "## 2 Method\n\n" + PROSA * 4 + "\n\n## 3 Results\n\n" + PROSA * 4,
        "## 4 Discussion\n\n" + PROSA * 2 + "\n\n## References\n\n" + "\n".join(f"- {r}\n" for r in REFS),
    )


# ---------- 3.1 classificação de títulos ----------

@pytest.mark.parametrize("titulo,esperado", [
    ("References", "referencias"),
    ("REFERENCES", "referencias"),
    ("Bibliography", "referencias"),
    ("Works Cited", "referencias"),
    ("Literature cited", "referencias"),
    ("Referências", "referencias"),
    ("Referências Bibliográficas", "referencias"),
    ("Referencias", "referencias"),
    ("Bibliografía", "referencias"),
    ("7. Referências", "referencias"),
    ("Abstract", "resumo"),
    ("Resumo", "resumo"),
    ("Resumen", "resumo"),
    ("1 Introduction", "introducao"),
    ("1. Introdução", "introducao"),
    ("Introducción", "introducao"),
    ("2 Related Work", "referencial"),
    ("Referencial teórico", "referencial"),  # não confundir com "Referências"
    ("Marco teórico", "referencial"),
    ("3 Methodology", "metodos"),
    ("III. METHOD", "metodos"),
    ("3 Metodologia", "metodos"),
    ("Materials and Methods", "metodos"),
    ("5. Results", "resultados"),
    ("Resultados", "resultados"),
    ("V. DISCUSSION", "discussao"),
    ("Discussão", "discussao"),
    ("Discusión", "discussao"),
    ("6 Conclusion", "conclusao"),
    ("Conclusões", "conclusao"),
    ("Conclusiones", "conclusao"),
    ("Appendix A Product Hunt Platform Background", "apendice"),
    ("Apêndice B", "apendice"),
    ("Anexo I - Roteiro de entrevista", "apendice"),
    ("Supplementary Material", "apendice"),
    ("Acknowledgements", "agradecimentos"),
    ("Acknowledgments", "agradecimentos"),
    ("Agradecimentos", "agradecimentos"),
    ("Funding", "declaracoes"),
    ("Conflict of Interest", "declaracoes"),
    ("Author Contributions", "declaracoes"),
    ("Data Availability Statement", "declaracoes"),
    ("Disponibilidade de dados", "declaracoes"),
    ("Results and Discussion", "resultados"),
    ("Discussion and Conclusions", "discussao"),
])
def test_classificar_titulo(titulo, esperado):
    assert classificar_titulo(titulo) == esperado


@pytest.mark.parametrize("titulo", [
    "Generative AI Fuels Solo Entrepreneurship, but Teams Still Lead at the Top",
    "Entrepreneurial Entry Following ChatGPT",
    "A Reference Architecture for Agent Systems and Their Many Components",
    "Table of contents",
])
def test_titulo_nao_reconhecido(titulo):
    assert classificar_titulo(titulo) is None


# ---------- 3.1 referências por título ----------

def test_referencias_por_titulo(artigo_com_referencias):
    r = processar(artigo_com_referencias, {})
    est = r["estatisticas"]
    assert est["metodo_deteccao"] == "titulo" and est["referencias_detectadas"] is True
    assert secoes_tipos(r) == ["titulo", "resumo", "introducao", "metodos", "resultados", "discussao", "referencias"]
    refs = blocos_de(r, "referencias")
    assert refs and all(not b["incluir"] for b in refs)
    assert refs[0]["pagina"] == 3 and refs[0]["titulo_secao"] == "References"
    assert "Acemoglu" in refs[0]["texto"]
    assert est["palavras_referencias"] > 50
    # nada de texto de referência no corpo
    corpo = " ".join(b["texto"] for b in r["blocos"] if b["incluir"])
    assert "Acemoglu" not in corpo and "analysis of the data" in corpo


def test_titulo_references_vazio_nao_conta_como_deteccao():
    """Um 'References' do sumário (sem conteúdo) não pode marcar o resto do documento como referências."""
    md = md_paginas(
        "## Contents\n\n## References\n\n## Appendix\n\n",
        "## 1 Introduction\n\n" + PROSA * 6,
        "## 2 Results\n\n" + PROSA * 6,
    )
    r = processar(md, {})
    assert r["estatisticas"]["metodo_deteccao"] == "nenhum"
    assert r["estatisticas"]["palavras_corpo"] == r["estatisticas"]["palavras_total"] - sum(
        s["palavras"] for s in r["secoes"] if not s["incluir"]
    )
    assert "referencias" not in secoes_tipos(r)


# ---------- 3.1 referências por heurística ----------

def test_referencias_por_heuristica_sem_titulo():
    corpo = "## Abstract\n\n" + PROSA * 3 + "\n\n## 1 Introduction\n\n" + PROSA * 8 + "\n\n"
    lista = "\n\n".join(REFS * 2)  # 16 entradas, sem título "References"
    r = processar(md_paginas(corpo, PROSA * 6 + "\n\n" + lista), {})
    est = r["estatisticas"]
    assert est["metodo_deteccao"] == "heuristica" and est["referencias_detectadas"] is True
    refs = blocos_de(r, "referencias")
    assert refs and refs[0]["texto"].startswith("Acemoglu") and refs[0]["incluir"] is False
    assert refs[0]["titulo_secao"] is None
    # a prosa da página 2 antes da lista continua no corpo
    prosa_p2 = [b for b in r["blocos"] if b["pagina"] == 2 and b["incluir"]]
    assert prosa_p2 and "analysis of the data" in prosa_p2[0]["texto"]
    assert est["palavras_referencias"] > 100


def test_heuristica_conservadora_prosa_com_citacoes_nao_vira_referencia():
    citando = (
        "As shown by Smith et al. (2019) and Jones et al. (2020), the effect is robust, "
        "which agrees with Brown et al. (2021) and with the review by Lee and Kim (2018). "
    ) * 2
    md = md_paginas("## 1 Introduction\n\n" + PROSA * 8, ("\n\n".join([citando] * 12)))
    r = processar(md, {})
    assert r["estatisticas"]["metodo_deteccao"] == "nenhum"
    assert all(b["incluir"] for b in r["blocos"])


def test_heuristica_so_olha_o_final_do_documento():
    """Uma lista de referências no início (últimos 40% não a alcançam) não é marcada."""
    lista = "\n\n".join(REFS * 2)
    md = md_paginas(lista, "## 1 Introduction\n\n" + PROSA * 40)
    r = processar(md, {})
    assert r["estatisticas"]["metodo_deteccao"] == "nenhum"


# ---------- 3.1 seções depois das referências ----------

def test_apendice_depois_das_referencias_e_titulo_desconhecido_fica_em_referencias():
    md = md_paginas(
        "## 1 Introduction\n\n" + PROSA * 6,
        "## References\n\n" + "\n\n".join(REFS) + "\n\n## en.\n\n" + "\n\n".join(REFS),
        "## Appendix A Detalhes\n\n" + PROSA * 3 + "\n\n## B1 Mais detalhes\n\n" + PROSA * 2
        + "\n\n## Declarations\n\n" + PROSA,
    )
    r = processar(md, {})
    assert secoes_tipos(r) == ["introducao", "referencias", "referencias", "apendice", "apendice", "declaracoes"]
    assert r["estatisticas"]["metodo_deteccao"] == "titulo"
    # "en." (título desconhecido) ficou em referências; o apêndice ficou fora delas
    assert [s["incluir"] for s in r["secoes"]] == [True, False, False, False, False, False]
    assert not [b for b in r["blocos"] if b["incluir"] and "Acemoglu" in b["texto"]]


def test_apendice_por_letras_depois_das_referencias_sem_a_palavra_appendix():
    md = md_paginas(
        "## 1 Introduction\n\n" + PROSA * 6,
        "## References\n\n" + "\n\n".join(REFS),
        "## A Additional Results\n\n" + PROSA * 3 + "\n\n## B Benchmark Construction\n\n" + PROSA * 3,
    )
    r = processar(md, {})
    assert secoes_tipos(r) == ["introducao", "referencias", "apendice", "apendice"]


def test_capitulo_em_prosa_depois_das_referencias_volta_ao_corpo():
    """Relatório com 'References' ao fim do capítulo 1 e o capítulo 2 em seguida."""
    md = md_paginas(
        "## 1 Introduction\n\n" + PROSA * 6,
        "## References\n\n" + "\n\n".join(REFS),
        "## 2 How are firms using the tools\n\n" + PROSA * 8,
    )
    r = processar(md, {})
    assert secoes_tipos(r) == ["introducao", "referencias", "outro"]
    assert blocos_de(r, "outro")[0]["incluir"] is True


def test_numeracao_romana_e_subsecoes_herdam_o_tipo():
    md = md_paginas(
        "## I. INTRODUCTION\n\n" + PROSA * 3 + "\n\n## IV. RESULTS\n\n" + PROSA * 2
        + "\n\n## 4.1 Entrepreneurial Entry Following ChatGPT\n\n" + PROSA * 2,
    )
    r = processar(md, {})
    assert secoes_tipos(r) == ["introducao", "resultados", "resultados"]


# ---------- 3.2 exclusão ----------

def test_exclusao_padrao_e_palavras_corpo(artigo_com_referencias):
    md = artigo_com_referencias + pagina(4, "## Acknowledgements\n\nThanks to everyone who helped.\n\n## Appendix A\n\n" + PROSA * 2)
    # as seções acima ficam depois de "References" -> agradecimentos e apêndice
    r = processar(md, {"excluir_referencias": True, "excluir_secoes": ["referencias", "apendice", "agradecimentos", "declaracoes"]})
    est = r["estatisticas"]
    assert est["palavras_corpo"] < est["palavras_total"]
    incluidas = {b["secao"] for b in r["blocos"] if b["incluir"]}
    assert incluidas.isdisjoint({"referencias", "apendice", "agradecimentos", "declaracoes"})
    palavras_corpo = sum(s["palavras"] for s in r["secoes"] if s["incluir"])
    assert palavras_corpo == est["palavras_corpo"]
    assert est["palavras_referencias"] + palavras_corpo <= est["palavras_total"]


def test_excluir_referencias_falso_inclui_tudo(artigo_com_referencias):
    r = processar(artigo_com_referencias, {"excluir_referencias": False})
    assert all(b["incluir"] for b in r["blocos"])
    assert r["estatisticas"]["palavras_corpo"] == r["estatisticas"]["palavras_total"]
    assert r["estatisticas"]["palavras_referencias"] > 0  # continua sendo medido


def test_excluir_secoes_personalizado(artigo_com_referencias):
    md = artigo_com_referencias + pagina(4, "## Appendix A\n\n" + PROSA * 2)
    r = processar(md, {"excluir_referencias": True, "excluir_secoes": ["referencias"]})
    apendice = blocos_de(r, "apendice")
    assert apendice and all(b["incluir"] for b in apendice)
    assert all(not b["incluir"] for b in blocos_de(r, "referencias"))


def test_parametros_antigos_sem_excluir_secoes_recebem_o_padrao(client, projeto, projetos_dir):
    pasta = projetos_dir / projeto
    antigos = svc_parametros.carregar(pasta)
    del antigos["excluir_secoes"]
    (pasta / "parametros.json").write_text(json.dumps(antigos), encoding="utf-8")
    assert "excluir_secoes" not in json.loads((pasta / "parametros.json").read_text(encoding="utf-8"))
    carregados = svc_parametros.carregar(pasta)
    assert carregados["excluir_secoes"] == ["referencias", "apendice", "agradecimentos", "declaracoes"]
    r = client.get(f"/api/projetos/{projeto}/parametros")
    assert r.status_code == 200 and r.json()["excluir_secoes"] == carregados["excluir_secoes"]
    # sem o parâmetro (processar sem dicionário) vale o padrão também
    r2 = processar(md_paginas("## Appendix A\n\n" + PROSA * 3), None)
    assert r2["blocos"][0]["incluir"] is False


# ---------- 3.3 limpeza ----------

def test_hifenizacao_de_fim_de_linha_corrigida_e_compostos_mantidos():
    texto, n = corrigir_hifenizacao("The field of entrepre-\nneurship is AI-driven and state-of-the-art, "
                                     "while AI-\ndriven tools and state-of-the-\nart models differ.")
    assert "entrepreneurship" in texto
    assert "AI-driven and state-of-the-art" in texto  # composto sem quebra: intacto
    assert "AI-driven tools" in texto  # composto real quebrado na linha: hífen mantido
    assert "state-of-the-art models" in texto
    assert n == 1


def test_hifenizacao_nao_junta_nome_proprio():
    texto, n = corrigir_hifenizacao("Smith-\nJones argue")
    assert texto == "Smith-Jones argue" and n == 0


def test_urls_emails_e_doi_removidos_com_contagem():
    bruto = (
        "See https://example.org/a/b?x=1. Contact: ana.silva@edge.ufal.br or visit www.edge.ufal.br/projeto, "
        "doi:10.1016/j.jbusvent.2020.106000 and [the site](https://site.io/x) for **more** details."
    )
    texto, info = limpar_texto(bruto)
    assert "http" not in texto and "@" not in texto and "www." not in texto and "10.1016" not in texto
    assert info["urls"] == 4  # url, e-mail, www, doi (o link [..](..) fica só com o texto)
    assert "the site for more details." in texto
    assert texto.count("See") == 1 and "." in texto


def test_marcas_de_markdown_tabelas_e_comentarios_removidos():
    md = md_paginas(
        "## 1 Introduction\n\n<!-- image -->\n\nTexto **forte** e _ênfase_ com `codigo`.\n\n"
        "| Variável | Valor |\n|---|---|\n| idade | 30 |\n| renda | alta |\n\n<!-- formula-not-decoded -->\n\nFim."
    )
    r = processar(md, {})
    texto = " ".join(b["texto"] for b in r["blocos"])
    for lixo in ("**", "_ênfase_", "`", "|", "---", "<!--", "#"):
        assert lixo not in texto
    assert "Variável Valor" in texto and "idade 30" in texto and "Fim." in texto


def test_cabecalho_e_rodape_repetidos_removidos():
    paginas = []
    for i in range(1, 7):
        paginas.append(
            f"Journal of Agentic Studies, Vol. 3, 2026\n\n## Seção {i}\n\n{PROSA}Conteúdo único da página {i} aqui.\n\nPage {i} of 6"
        )
    md = md_paginas(*paginas)
    r = processar(md, {})
    texto = " ".join(b["texto"] for b in r["blocos"])
    assert "Journal of Agentic Studies" not in texto
    assert "Page 3 of 6" not in texto
    assert "Conteúdo único da página 4 aqui." in texto
    assert r["estatisticas"]["linhas_repetidas_removidas"] == 12  # 6 cabeçalhos + 6 rodapés


def test_numero_de_pagina_isolado_removido_e_poucas_paginas_nao_removem_repetidas():
    md = md_paginas(
        "Cabeçalho do periódico\n\n" + PROSA + "\n\n7",
        "Cabeçalho do periódico\n\n" + PROSA + "\n\n8",
    )
    r = processar(md, {})
    texto = " ".join(b["texto"] for b in r["blocos"])
    assert "Cabeçalho do periódico" in texto  # só 2 páginas: não há base para dizer que se repete
    assert not texto.strip().endswith("8") and "\n7" not in texto
    assert r["estatisticas"]["linhas_repetidas_removidas"] == 2


def test_linha_curta_legitima_que_nao_se_repete_e_preservada():
    paginas = [f"{PROSA}\n\nDefinição importante número {i}." if i == 2 else PROSA for i in range(1, 6)]
    r = processar(md_paginas(*paginas), {})
    assert "Definição importante número 2." in " ".join(b["texto"] for b in r["blocos"])


# ---------- atribuição de página ----------

def test_pagina_preservada_em_secao_que_atravessa_paginas():
    md = md_paginas(
        "## 1 Introduction\n\n" + PROSA,
        "## 3 Results\n\nPrimeiro trecho dos resultados.",
        "Segundo trecho, ainda nos resultados.",
        "Terceiro trecho e fim.\n\n## 4 Discussion\n\nDiscussão aqui.",
    )
    r = processar(md, {})
    res = blocos_de(r, "resultados")
    assert [b["pagina"] for b in res] == [2, 3, 4]
    assert all(b["titulo_secao"] == "3 Results" for b in res)
    assert res[1]["texto"] == "Segundo trecho, ainda nos resultados."
    s = next(s for s in r["secoes"] if s["tipo"] == "resultados")
    assert (s["pagina_inicio"], s["pagina_fim"]) == (2, 4)
    assert blocos_de(r, "discussao")[0]["pagina"] == 4


def test_palavra_hifenizada_na_virada_de_pagina_fica_na_pagina_de_origem():
    md = md_paginas("## 1 Introduction\n\nO tema do empreende-", "dorismo agêntico segue na página dois.")
    r = processar(md, {})
    b1, b2 = r["blocos"][0], r["blocos"][1]
    assert b1["pagina"] == 1 and b1["texto"].endswith("empreendedorismo")
    assert b2["pagina"] == 2 and b2["texto"].startswith("agêntico")
    assert r["estatisticas"]["hifenizacoes_corrigidas"] == 1


def test_documento_sem_marcadores_de_pagina():
    r = processar("## Abstract\n\n" + PROSA * 3 + "\n\n## References\n\n" + "\n\n".join(REFS), {})
    assert all(b["pagina"] is None for b in r["blocos"])
    assert r["estatisticas"]["metodo_deteccao"] == "titulo"


def test_texto_para_inspecao_tem_marcadores_de_pagina_e_filtra_corpo(artigo_com_referencias):
    r = processar(artigo_com_referencias, {})
    corpo = texto_para_inspecao(r, "corpo")
    tudo = texto_para_inspecao(r, "tudo")
    assert "<!-- página 1 -->" in corpo and "<!-- página 3 -->" in corpo
    assert "Acemoglu" not in corpo and "Acemoglu" in tudo
    assert "## References [referencias]" in tudo and "[referencias]" not in corpo


# ---------- integração: etapa, cache, API, pendências ----------

def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return r.json()


def _etapa(resumo, nome):
    return next(e for e in resumo["etapas"] if e["etapa"] == nome)


@pytest.fixture()
def corpus3(tmp_path, artigo_com_referencias):
    pasta = tmp_path / "corpus3"
    pasta.mkdir()
    (pasta / "001_2026_Kim_Com_Referencias.md").write_text(artigo_com_referencias, encoding="utf-8")
    return pasta


@pytest.fixture()
def projeto3(client, corpus3):
    r = client.post("/api/projetos", json={"nome": "Projeto F3", "pasta_origem": str(corpus3)})
    assert r.status_code == 201, r.text
    return r.json()["slug"]


def test_limpeza_grava_json_e_estatisticas_e_pula_na_segunda_execucao(client, projeto3, projetos_dir):
    primeiro = _executar(client, projeto3)
    assert primeiro["erros"] == 0
    assert _etapa(primeiro, "limpeza")["ok"] == 1

    doc = client.get(f"/api/projetos/{projeto3}/documentos").json()[0]
    arquivo = projetos_dir / projeto3 / "cache" / "limpo" / f"{doc['id']}.json"
    assert arquivo.is_file()
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    assert set(dados) == {"blocos", "secoes", "estatisticas"}
    for chave in ("palavras_total", "palavras_corpo", "palavras_referencias", "referencias_detectadas", "metodo_deteccao",
                  "urls_removidas", "hifenizacoes_corrigidas", "linhas_repetidas_removidas"):
        assert chave in dados["estatisticas"]
    assert set(dados["blocos"][0]) == {"pagina", "secao", "titulo_secao", "texto", "incluir"}
    assert set(dados["secoes"][0]) >= {"tipo", "titulo", "pagina_inicio", "pagina_fim", "palavras"}
    # resumo em qualidade_json["limpeza"] (visível na lista de documentos)
    assert doc["referencias"] == "titulo" and 0 < doc["pct_corpo"] < 100

    segundo = _executar(client, projeto3)
    assert _etapa(segundo, "limpeza")["pulado"] == 1 and _etapa(segundo, "limpeza")["ok"] == 0

    # mudar um parâmetro invalida o cache
    p = client.get(f"/api/projetos/{projeto3}/parametros").json()
    p["excluir_secoes"] = ["referencias"]
    assert client.put(f"/api/projetos/{projeto3}/parametros", json=p).status_code == 200
    terceiro = _executar(client, projeto3)
    assert _etapa(terceiro, "limpeza")["ok"] == 1


def test_api_secoes_e_texto(client, projeto3, projetos_dir):
    _executar(client, projeto3)
    doc = client.get(f"/api/projetos/{projeto3}/documentos").json()[0]
    # sem o texto limpo (ex.: documento com problema): 404 explicativo
    arquivo = projetos_dir / projeto3 / "cache" / "limpo" / f"{doc['id']}.json"
    guardado = arquivo.read_bytes()
    arquivo.unlink()
    assert client.get(f"/api/projetos/{projeto3}/documentos/{doc['id']}/secoes").status_code == 404
    assert client.get(f"/api/projetos/{projeto3}/documentos/{doc['id']}/texto").status_code == 404
    arquivo.write_bytes(guardado)

    r = client.get(f"/api/projetos/{projeto3}/documentos/{doc['id']}/secoes")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["arquivo"] == doc["arquivo"]
    tipos = [s["tipo"] for s in corpo["secoes"]]
    assert "referencias" in tipos and "resultados" in tipos
    assert next(s for s in corpo["secoes"] if s["tipo"] == "referencias")["incluir"] is False
    assert corpo["estatisticas"]["metodo_deteccao"] == "titulo"

    texto_corpo = client.get(f"/api/projetos/{projeto3}/documentos/{doc['id']}/texto?incluir=corpo")
    assert texto_corpo.status_code == 200 and texto_corpo.headers["content-type"].startswith("text/plain")
    assert "<!-- página 2 -->" in texto_corpo.text and "Acemoglu" not in texto_corpo.text
    texto_tudo = client.get(f"/api/projetos/{projeto3}/documentos/{doc['id']}/texto?incluir=tudo")
    assert "Acemoglu" in texto_tudo.text
    assert client.get(f"/api/projetos/{projeto3}/documentos/{doc['id']}/texto?incluir=xyz").status_code == 422
    assert client.get(f"/api/projetos/{projeto3}/documentos/9999/secoes").status_code == 404


def _artigo_sem_referencias() -> str:
    paginas = [
        "## Abstract\n\n" + PROSA * 3,
        "## 1 Introduction\n\n" + PROSA * 4,
        "## 2 Method\n\n" + PROSA * 4,
        "## 3 Results\n\n" + PROSA * 4,
        "## 4 Discussion\n\n" + PROSA * 4,
        "## 5 Conclusion\n\n" + PROSA * 4,
    ]
    return md_paginas(*paginas)


def test_pendencia_referencias_nao_detectadas_e_grupo_cinzenta(client, tmp_path):
    pasta = tmp_path / "corpus_sem_refs"
    pasta.mkdir()
    (pasta / "001_2026_Silva_Sem_Referencias.md").write_text(_artigo_sem_referencias(), encoding="utf-8")
    slug = client.post("/api/projetos", json={"nome": "Sem refs", "pasta_origem": str(pasta)}).json()["slug"]
    _executar(client, slug)

    pend = {p["arquivo"]: p for p in client.get(f"/api/projetos/{slug}/pendencias").json()}
    assert "referências não detectadas" in pend["001_2026_Silva_Sem_Referencias.md"]["avisos"]
    doc = client.get(f"/api/projetos/{slug}/documentos").json()[0]
    assert doc["referencias"] == "nenhum" and "referências não detectadas" in doc["avisos"]

    # literatura cinzenta: o aviso some na hora (não precisa reexecutar)
    client.patch(f"/api/projetos/{slug}/documentos/{doc['id']}", json={"grupo": "cinzenta"})
    # (o relatório repete o texto do artigo curto: a duplicata próxima é outro aviso, coberto em test_frente26)
    pend = client.get(f"/api/projetos/{slug}/pendencias").json()
    assert [p for p in pend if not all("duplicata" in a for a in p["avisos"])] == []


def test_pendencia_documento_curto_ou_nao_academico_nao_gera_aviso(client, tmp_path):
    pasta = tmp_path / "corpus_curto"
    pasta.mkdir()
    # 3 páginas apenas, mesmo com estrutura de artigo
    (pasta / "001_2026_Curto.md").write_text(md_paginas("## Abstract\n\n" + PROSA * 8, "## 1 Introduction\n\n" + PROSA * 8, "## 2 Results\n\n" + PROSA * 8), encoding="utf-8")
    # 6 páginas de texto corrido, sem seções nem citações (relatório): não é "obviamente acadêmico"
    (pasta / "002_2026_Relatorio.md").write_text(md_paginas(*[PROSA * 8 for _ in range(6)]), encoding="utf-8")
    slug = client.post("/api/projetos", json={"nome": "Curtos", "pasta_origem": str(pasta)}).json()["slug"]
    _executar(client, slug)
    # (o relatório repete o texto do artigo curto: a duplicata próxima é outro aviso, coberto em test_frente26)
    pend = client.get(f"/api/projetos/{slug}/pendencias").json()
    assert [p for p in pend if not all("duplicata" in a for a in p["avisos"])] == []


def test_pendencia_referencias_ocupam_mais_da_metade(client, tmp_path):
    pasta = tmp_path / "corpus_refs_grandes"
    pasta.mkdir()
    md = md_paginas("## Abstract\n\n" + PROSA * 2 + "\n\n## 1 Introduction\n\n" + PROSA * 3, "## References\n\n" + "\n\n".join(REFS * 8))
    (pasta / "001_2026_Refs_Grandes.md").write_text(md, encoding="utf-8")
    slug = client.post("/api/projetos", json={"nome": "Refs grandes", "pasta_origem": str(pasta)}).json()["slug"]
    _executar(client, slug)
    avisos = client.get(f"/api/projetos/{slug}/pendencias").json()[0]["avisos"]
    assert any("referências ocupam > 50%" in a for a in avisos)
