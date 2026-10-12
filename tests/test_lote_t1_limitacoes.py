"""16.1 refinamento de Limitações: conjunto POSITIVO (frases reais de limitações, EN/PT/ES) e conjunto NEGATIVO (itens de checklist,
títulos, frases de método, "limitações de recursos", ponteiros "ver Seção N"), regra forte x fraca por seção, páginas de checklist
de conferência e a rota por título de seção sem as orientações do checklist."""
import pytest

from app.services.corpus import partes


def _fr(texto, secao="discussao", pagina=5, i=0, titulo=None):
    return {"i": i, "texto": texto, "pagina": pagina, "secao": secao, "titulo_secao": titulo}


def _nota(texto, **kw):
    return partes.pontuar_frase("limitacoes", _fr(texto, **kw), 0.9)


POSITIVAS = [
    ("One limitation of this study is that it uses a single digital platform to build the sample.", "discussao"),
    ("This study has several limitations that should be considered when reading the results.", "conclusao"),
    ("Although this study makes significant contributions, several limitations must be acknowledged.", "conclusao"),
    ("The experiment has several important limitations worth enumerating for the reader.", "discussao"),
    ("These comments point to an important (and inherent) limitation of our experiment: it involves small tasks.", "outro"),
    ("The limitations of this study include the small sample and the short observation window.", "conclusao"),
    ("Our findings should be interpreted with caution because the sample is self-selected.", "discussao"),
    ("We acknowledge that this study examines activity within a single platform focused on software.", "conclusao"),
    ("The sample is limited to firms in one country, so the findings may not generalize to other settings.", "discussao"),
    ("A limitation is that we cannot observe the prompts that the founders used with the tools.", "discussao"),
    ("As limitações deste estudo incluem o tamanho da amostra e o período curto de observação dos dados.", "conclusao"),
    ("Este estudo possui limitações que precisam ser consideradas na interpretação dos resultados.", "discussao"),
    ("Uma limitação importante é que os dados vêm de uma única plataforma de lançamentos de produtos.", "conclusao"),
    ("Los resultados deben interpretarse con cautela y no pueden generalizarse a otros contextos del país.", "conclusao"),
    ("Una limitación de este estudio es que la muestra proviene de una sola plataforma digital en línea.", "discussao"),
    ("Este estudio tiene limitaciones importantes relacionadas con el tamaño de la muestra analizada aquí.", "conclusao"),
]

NEGATIVAS = [
    # frase de método e de resultados que só tem palavras soltas
    ("We collected the data from three platforms and removed duplicate launches before the analysis.", "metodos"),
    ("The results show a strong increase in entry after the release of the new tool in the second quarter.", "resultados"),
    # "limitações" sobre outro assunto (recursos, dados de treinamento), sem cue de limitação do estudo
    ("A coopetição é relevante para empreendedores que enfrentam limitações de recursos e acesso restrito a tecnologias.", "discussao"),
    ("Esta tensión requiere que usuarios desarrollen literacidad crítica sobre limitaciones de datos de entrenamiento.", "resultados"),
    ("Users should understand the limits of model training data and the biases inherent to these systems.", "discussao"),
    # cues fracos fora de discussão/conclusão
    ("The analysis is limited to English-language documents published after the year 2020 in the database.", "metodos"),
    ("We acknowledge that the sample was drawn from public repositories in the introduction of the paper.", "introducao"),
    ("Generalizability is discussed in the literature on external validity of survey experiments in general.", "referencial"),
    # ponteiros e checklist
    ("The limitations of this study are discussed in Section 7 of the paper and in the appendix.", "discussao"),
    ("Guidelines: The authors are encouraged to create a separate Limitations section in their paper.", "discussao"),
    ("Question: Does the paper discuss the limitations of the work performed by the authors in detail?", "discussao"),
    ("The answer NA means that the paper has no limitation while the answer No means that it has limitations.", "discussao"),
    ("- One limitation of the study is the sample size of the firms in the table of results shown here.", "discussao"),
    ("(a) the limitations of this study and the directions for future work are listed in the following table.", "discussao"),
]


@pytest.mark.parametrize("texto,secao", POSITIVAS)
def test_frases_reais_de_limitacao_passam(texto, secao):
    nota, regras = _nota(texto, secao=secao)
    assert regras and nota >= 2.0, f"deveria passar: {texto}"


@pytest.mark.parametrize("texto,secao", NEGATIVAS)
def test_checklist_titulo_metodo_e_ruido_nao_passam(texto, secao):
    f = _fr(texto, secao=secao)
    nota, regras = partes.pontuar_frase("limitacoes", f, 0.9)
    assert not regras or not partes._elegivel(f) or nota < 2.0, f"não deveria passar: {texto}"
    r = partes.preencher_padrao([f] if partes._elegivel(f) else [], "limitacoes", 3, 2.0, 1)
    assert r is None, f"não deveria virar trecho: {texto}"


def test_palavra_solta_limitation_nao_basta():
    assert _nota("The word limitations appears here only as a topic of the discussion about models.")[1] == []
    assert _nota("Some limitations of resources affect small firms in the region studied by the authors.")[1] == []


def test_cue_fraco_so_em_discussao_ou_conclusao_ou_titulo():
    texto = "The sample is limited to firms in one country, so the findings may not generalize to other settings."
    assert _nota(texto, secao="discussao")[1] and _nota(texto, secao="conclusao")[1]
    assert _nota(texto, secao="metodos")[1] == [] and _nota(texto, secao="outro")[1] == []
    assert _nota(texto, secao="outro", titulo="5.2 Limitations")[1]  # dentro de uma seção de limitações vale


def test_cue_forte_vale_em_qualquer_secao():
    assert _nota("The experiment has several important limitations worth enumerating for the reader.", secao="outro")[1]


def test_paginas_de_checklist_e_rota_por_titulo():
    checklist = [
        _fr("Question: Does the paper discuss the limitations of the work performed by the authors?", pagina=14, i=0, titulo="2. Limitations"),
        _fr("Guidelines: The answer NA means that the paper has no limitation while the answer No means it has limitations.", pagina=14, i=1, titulo="2. Limitations"),
        _fr("The authors are encouraged to create a separate Limitations section in their paper for reviewers.", pagina=14, i=2, titulo="2. Limitations"),
        _fr("In general, empirical results often depend on implicit assumptions, which should be articulated by the authors.", pagina=14, i=3, titulo="2. Limitations"),
    ]
    assert partes.paginas_de_checklist(checklist) == {14}
    assert partes.paginas_de_checklist(checklist[:1]) == set()  # uma frase só não marca a página
    real = [_fr("However, we did not collect human performance data because completing a task takes several hours.", pagina=29, i=4, titulo="Limitations")]
    r = partes.preencher_padrao([*checklist, *real], "limitacoes", 3, 2.0, 5, partes.paginas_de_checklist(checklist))
    assert r and [t["pagina"] for t in r["trechos"]] == [29] and r["metodo"] == "secao"
    assert partes.preencher_padrao(checklist, "limitacoes", 3, 2.0, 4, partes.paginas_de_checklist(checklist)) is None


def test_itens_de_lista_e_checklist_nao_sao_elegiveis():
    assert not partes._elegivel(_fr("- One limitation of the study is the sample size of the firms in the table of results."))
    assert not partes._elegivel(_fr("Justification: We discuss the limitations of this work in the conclusion of the paper."))
    assert partes._elegivel(_fr("One limitation of the study is the sample size of the firms in the table of results."))
