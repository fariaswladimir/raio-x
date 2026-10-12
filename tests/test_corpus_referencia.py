"""EAP 12.1: corpus de referência pequeno com resultados esperados.

Roda o pipeline completo (?sincrono=1) sobre tests/corpus_referencia/ e compara com esperado.json, que é
gerado por calcular_esperado.py sem importar o app. A pasta de origem é só lida: o teste nunca escreve nela.

Tolerância de 3% nas contagens de tokens por documento: o script de referência conta toda palavra de
letras do corpo; o app conta os mesmos tokens, mas o limpador pode tratar diferente casos de borda (por
exemplo, palavras de uma letra e hifenizações). Com estes textos a contagem deve bater; a folga existe
para não quebrar o teste por um detalhe de tokenização.
"""
import json
from pathlib import Path

import pytest

CORPUS = Path(__file__).resolve().parent / "corpus_referencia"
ESPERADO = json.loads((CORPUS / "esperado.json").read_text(encoding="utf-8"))
TOLERANCIA_TOKENS = 0.03


@pytest.fixture()
def projeto_referencia(client):
    r = client.post("/api/projetos", json={"nome": "Corpus de referência", "pasta_origem": str(CORPUS)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200 and r.json()["erros"] == 0, r.text
    return slug


def _frequencias(client, slug, por):
    r = client.get(f"/api/projetos/{slug}/analises/frequencias",
                   params={"por": por, "vazias": "manter", "limite": 5000})
    assert r.status_code == 200, r.text
    return {i["termo"]: i["freq"] for i in r.json()["itens"]}


def test_tokens_por_documento_conferem_com_o_esperado(client, projeto_referencia):
    r = client.get(f"/api/projetos/{projeto_referencia}/analises/resumo")
    assert r.status_code == 200, r.text
    resumo = r.json()
    obtidos = {d["arquivo"]: d["tokens"] for d in resumo["documentos"]}
    assert set(obtidos) == set(ESPERADO["documentos"])
    for arquivo, esperado in ESPERADO["documentos"].items():
        limite = TOLERANCIA_TOKENS * esperado["tokens"]
        assert abs(obtidos[arquivo] - esperado["tokens"]) <= limite, (arquivo, obtidos[arquivo], esperado["tokens"])


def test_total_de_tokens_do_corpus_confere_com_o_esperado(client, projeto_referencia):
    corpus = client.get(f"/api/projetos/{projeto_referencia}/analises/resumo").json()["corpus"]
    assert corpus["n_documentos"] == len(ESPERADO["documentos"])
    assert abs(corpus["tokens"] - ESPERADO["total_tokens"]) <= TOLERANCIA_TOKENS * ESPERADO["total_tokens"]


def test_frequencia_do_lema_agent_soma_agent_e_agents(client, projeto_referencia):
    itens = _frequencias(client, projeto_referencia, "lema")
    assert itens.get("agent") == ESPERADO["agent_mais_agents"]


def test_termo_das_referencias_nao_aparece_nas_frequencias(client, projeto_referencia):
    # "Smith" só existe na lista de referências, que o corpo do texto exclui da análise.
    for por in ("lema", "forma"):
        assert "smith" not in _frequencias(client, projeto_referencia, por), por
