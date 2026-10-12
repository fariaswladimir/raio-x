"""Frente 17 - coleta guiada por protocolo: protocolo (17.1), coleta automática (17.2), revisão, exportação e concordância (17.3).

Sem rede e sem LLM real (provedor simulado). Um projeto sintético com 6 artigos é processado uma vez por módulo (``ambiente``); cada teste começa
sem protocolo nem células (``limpo``). O restante são testes unitários de funções puras (contador de frases, extratores, conferência do LLM).
"""
import csv
import io
import json
import shutil
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.services import tokenizacao as tk
from app.services.coleta import celulas as C
from app.services.coleta import concordancia_coleta as CC
from app.services.coleta import extratores as E
from app.services.coleta import llm_coleta as LC
from app.services.coleta import modelos as MO
from app.services.coleta import protocolo as PR
from app.services.coleta import termos as T
from app.services.coleta import trabalho as TR
from app.services.concordancia import estatisticas as ST
from app.services.corpus import llm_partes as L
from app.services.corpus import partes as P
from app.services.corpus import planilha as svc_planilha
from app.services.llm import config as cfg_llm

_SILABAS = ["zor", "bal", "qui", "mix", "tra", "vel", "dun", "pho", "lek", "sar", "nim", "gro", "fle", "wub", "kra", "tiv", "mon", "dre", "hul", "pax"]


def enchimento(semente: int, frases: int = 12) -> str:
    """Texto longo de palavras inventadas e diferentes em cada documento (senão a detecção de ruído da 3.4 trata o enchimento repetido como cláusula repetida)."""
    import random

    rng = random.Random(semente)
    def p():
        return "".join(rng.choice(_SILABAS) for _ in range(rng.randint(2, 3)))
    return " ".join(f"The {p()} {p()} {p()} shows that the {p()} {p()} of {p()} {p()} are {p()} with {p()} {p()}." for _ in range(frases))
DESENHOS = [
    "We conducted a questionnaire survey with respondents from many firms.",
    "We present a case study of one large firm and its founders.",
    "We ran a randomized field experiment with the founders of new firms.",
    "We conducted semi-structured interviews with the founders of new firms.",
    "We conducted a questionnaire survey with respondents from many firms.",
    "We run a simulation of an agent-based model of the market.",
]
TAMANHOS = [1200, 312, 450, 25, 2500, 80]


def artigo(i: int) -> str:
    return f"""<!-- página 1 -->

## Abstract

This paper aims to investigate how generative AI changes the entry of solo founders in digital markets. {DESENHOS[i]}

## 1 Introduction

Entrepreneurship is changing quickly across the world. {enchimento(i * 10 + 1)}

<!-- página 2 -->

## 2 Method

The sample consists of {TAMANHOS[i]:,} startups located in Brazil. Data were collected between March 2024 and June 2025. We did not use interviews in this study. {enchimento(i * 10 + 2)}

## 3 Results

Entry increased after the release of the tool. {enchimento(i * 10 + 3)}

<!-- página 3 -->

## 4 Discussion

One limitation of this study is that it uses a single platform, so results may not generalize to other settings. {enchimento(i * 10 + 4)}

## 5 Conclusion

We conclude that the effect is real. {enchimento(i * 10 + 5)}

## Acknowledgements

This research was funded by the CNPq under grant {i}2345. The authors declare no conflict of interest.

## References

1. Acemoglu, D.; Restrepo, P. Automation and New Tasks. J. Econ. Perspect. 2019, 33, 3-30.
"""


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    base = tmp_path_factory.mktemp("f17")
    mp = pytest.MonkeyPatch()
    mp.setenv("RAIOX_PROJETOS_DIR", str(base / "projetos"))
    mp.setenv("RAIOX_CONFIG_DIR", str(base / "cfg"))
    pasta = base / "artigos"
    pasta.mkdir()
    for i in range(6):
        (pasta / f"artigo_{i + 1}.md").write_text(artigo(i), encoding="utf-8")
    with TestClient(app) as c:
        r = c.post("/api/projetos", json={"nome": "f17", "pasta_origem": str(pasta)})
        assert r.status_code == 201, r.text
        slug = r.json()["slug"]
        r = c.post(f"/api/projetos/{slug}/executar?sincrono=1")
        assert r.status_code == 200, r.text
        yield {"c": c, "slug": slug, "base": base, "pasta": base / "projetos" / slug}
    for engine in list(database._engines.values()):
        engine.dispose()
    database._engines.clear()
    mp.undo()


@pytest.fixture(autouse=True)
def limpo(request):
    """Cada teste do projeto começa sem protocolo, células, segundo codificador e com o LLM desligado."""
    if "ambiente" not in request.fixturenames:
        yield
        return
    amb = request.getfixturevalue("ambiente")
    _limpar(amb)
    yield
    _limpar(amb)


def _limpar(amb):
    p = amb["pasta"]
    for nome in (PR.ARQUIVO, C.ARQUIVO, CC.ARQUIVO):
        (p / nome).unlink(missing_ok=True)
    shutil.rmtree(p / PR.HISTORICO, ignore_errors=True)
    (amb["base"] / "cfg" / "config_llm.json").unlink(missing_ok=True)


def _url(amb, caminho):
    return f"/api/projetos/{amb['slug']}/coleta/{caminho}"


def _db(amb):
    return database.sessao_do_projeto(amb["slug"])


def _ligar_llm():
    cfg_llm.salvar({"habilitado": True, "provedor": "ollama", "ollama": {"modelo": "stub-1"}})


def _carregar_modelo(amb, modelo="revisao_sistematica"):
    r = amb["c"].post(_url(amb, f"protocolo/modelos/{modelo}/carregar?aplicar=true"))
    assert r.status_code == 200, r.text
    return r.json()


def _executar(amb, **corpo):
    r = amb["c"].post(_url(amb, "executar?sincrono=1"), json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


def _celulas(amb) -> dict:
    return C.carregar(amb["pasta"])["celulas"]


def _arquivo(i: int) -> str:
    return f"artigo_{i}.md"


def _id_doc(amb, arquivo: str) -> int:
    docs = amb["c"].get(f"/api/projetos/{amb['slug']}/documentos").json()
    return next(d["id"] for d in docs if d["arquivo"] == arquivo)


# =============== contador de frases (17.1) ===============

@pytest.mark.parametrize("texto,esperado", [
    ("Mede o tamanho da amostra final. Conta as unidades analisadas.", 2),
    ("Uma. Duas. Três.", 3),
    ("Sem pontuação final", 1),
    ("", 0),
    ("Is it used? Yes! Maybe.", 3),
    ("Sample size, e.g. 1,200 firms. Reported by Smith et al. (2020).", 2),                       # e.g. e et al. não encerram
    ("The size, i.e. the number of firms. It excludes dropouts (n. 12).", 2),                     # i.e. e "n." não encerram
    ("Valor médio de 3.5 pontos na escala Likert. Ver p. 12 do artigo.", 2),                       # decimal e "p." não encerram
    ("J. Smith e A. Jones medem os itens vs. o grupo controle.", 1),                               # iniciais e "vs."
    ("Veja no. 5 da lista. O resultado é não. Nada mais.", 3),                                     # "no." só é abreviação diante de número
    ("A média foi de 0.75 em 2020. Isso indica melhora. Mas há ressalvas.", 3),
    ("O objetivo é medir X, a saber, o total. Isso exclui Dr. Silva e Fig. 3 do texto.", 2),
])
def test_contar_frases_regra_documentada(texto, esperado):
    assert PR.contar_frases(texto) == esperado


def test_definicao_com_tres_frases_e_recusada_com_sugestao_de_corte():
    ps = PR.validar_definicao("Primeira frase aqui. Segunda frase aqui. Terceira frase aqui.", "x")
    erro = next(p for p in ps if p["codigo"] == "frases_excedidas")
    assert erro["gravidade"] == "erro" and erro["frases"] == 3
    assert erro["sugestao"] == "Primeira frase aqui. Segunda frase aqui."
    assert "Sugestão de corte" in erro["mensagem"]
    assert PR.validar_definicao("Uma frase só. Outra frase.", "x") == []
    assert [p["codigo"] for p in PR.validar_definicao("", "x")] == ["definicao_vazia"]


def test_aviso_de_definicao_longa_nao_bloqueia():
    longa = "Palavra " * 45 + "final."
    ps = PR.validar_definicao(longa, "x")
    assert [p["codigo"] for p in ps] == ["definicao_longa"] and ps[0]["gravidade"] == "aviso"
    item, problemas = PR.normalizar_item({"id": "a", "nome": "A", "definicao": longa, "tipo": "texto"})
    assert not PR.so_erros(problemas)


def test_categoria_com_definicao_de_duas_frases_e_recusada():
    item, problemas = PR.normalizar_item({"id": "a", "nome": "A", "definicao": "Ok.", "tipo": "categoria",
                                          "categorias": "X: Uma frase. Duas frases. | Y: boa"})
    assert any(p["codigo"] == "frases_excedidas_categoria" and p["sugestao"] == "Uma frase." for p in problemas)


def test_item_valida_campos_e_ids_repetidos():
    itens, problemas = PR.validar_itens([
        {"id": "a", "nome": "A", "definicao": "Boa.", "tipo": "numero"},
        {"id": "A", "nome": "B", "definicao": "Boa.", "tipo": "categoria", "categorias": "só uma"},
        {"id": "c d", "nome": "", "definicao": "Boa.", "tipo": "inexistente"},
        {"id": "e", "nome": "E", "definicao": "Boa.", "tipo": "texto", "onde_procurar": "resumo; inventada", "palavras_chave": "/(/"},
    ])
    codigos = {p["codigo"] for p in problemas}
    assert {"id_repetido", "categorias_faltando", "id_invalido", "nome_vazio", "tipo_invalido", "secao_invalida", "regex_invalida"} <= codigos


# =============== importação e exportação do protocolo ===============

def _csv(cab, linhas, delim=";"):
    s = io.StringIO()
    w = csv.writer(s, delimiter=delim)
    w.writerow(cab)
    w.writerows(linhas)
    return s.getvalue().encode("utf-8-sig")


def test_importa_csv_com_cabecalho_em_portugues_sem_acento_e_caixa():
    conteudo = _csv(["ID", "NOME", "Definicao", "TIPO", "Categorias", "Onde Procurar", "PALAVRAS-CHAVE", "Obrigatorio"], [
        ["a1", "Amostra", "Número de unidades. Total final.", "Número", "", "métodos; Abstract", "sample*; \"sample size\"", "sim"],
        ["a2", "Desenho", "Estratégia metodológica.", "Categoria", "Survey [questionário, survey]: Pesquisa por questionário. | Experimento", "", "", "não"],
    ])
    r = PR.importar(conteudo, "csv")
    assert not r["erros"], r["erros"]
    a1, a2 = r["itens"]
    assert a1["tipo"] == "numero" and a1["obrigatorio"] is True and a1["onde_procurar"] == ["metodos", "resumo"]
    assert a1["palavras_chave"] == ["sample*", "\"sample size\""]
    assert a2["tipo"] == "categoria" and [c["valor"] for c in a2["categorias"]] == ["Survey", "Experimento"]
    assert a2["categorias"][0]["palavras_chave"] == ["questionário", "survey"] and a2["categorias"][0]["definicao"] == "Pesquisa por questionário."
    assert a2["onde_procurar"] == ["qualquer"]


def test_importa_csv_em_ingles_e_aplica_a_regra_das_duas_frases():
    conteudo = _csv(["id", "item", "definition", "type", "categories", "where", "keywords", "required"], [
        ["q1", "Country", "Where the study took place. Name the country. And the region too.", "text", "", "methods", "country; Brazil", "yes"],
        ["q2", "Yes no", "Is there funding?", "yes/no", "", "any", "funding", "no"],
    ], delim=",")
    r = PR.importar(conteudo, "csv")
    assert [e["codigo"] for e in r["erros"]] == ["frases_excedidas"]
    assert r["erros"][0]["sugestao"] == "Where the study took place. Name the country." and r["erros"][0]["item"] == "q1"
    assert [i["tipo"] for i in r["itens"]] == ["texto", "sim_nao"] and r["itens"][0]["onde_procurar"] == ["metodos"]  # item com erro vem na lista


def test_importa_xlsx_e_markdown():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Outra"
    ws.append(["nada"])
    ws2 = wb.create_sheet("Protocolo")
    ws2.append(["id", "name", "definition", "type", "categories", "where", "keywords", "required"])
    ws2.append(["x1", "Funding", "Source of money. Copy the statement.", "text", None, "agradecimentos", "funding; grant*", "sim"])
    buf = io.BytesIO()
    wb.save(buf)
    r = PR.importar(buf.getvalue(), "auto", "p.xlsx")
    assert r["formato"] == "xlsx" and not r["erros"] and r["itens"][0]["palavras_chave"] == ["funding", "grant*"]
    md = ("| id | Nome | Definição | Tipo | Categorias | Onde procurar | Palavras-chave | Obrigatório |\n|---|---|---|---|---|---|---|---|\n"
          "| m1 | Ano | Ano do estudo. | data | | resumo; método | \"published in\" | não |\n"
          "| m2 | Setor | Setor econômico. | categoria | Saúde; Educação | | | sim |\n")
    r = PR.importar(md.encode("utf-8"), "auto", "p.md")
    assert r["formato"] == "markdown" and not r["erros"], r["erros"]
    assert r["itens"][0]["onde_procurar"] == ["resumo", "metodos"] and [c["valor"] for c in r["itens"][1]["categorias"]] == ["Saúde", "Educação"]


def test_importacao_recusa_cabecalho_desconhecido():
    with pytest.raises(ValueError, match="Cabeçalho não reconhecido"):
        PR.importar(_csv(["a", "b"], [["1", "2"]]), "csv")


def test_exporta_e_reimporta_csv_e_xlsx_sem_perder_nada_e_neutraliza_formulas():
    itens, problemas = PR.validar_itens([
        {"id": "n1", "nome": "=SOMA(A1)", "definicao": "Número de casos. Total.", "tipo": "numero", "onde_procurar": "metodos", "palavras_chave": "sample*; \"sample size\"", "obrigatorio": True, "max_trechos": 2},
        {"id": "c1", "nome": "Desenho", "definicao": "Como foi feito.", "tipo": "categoria", "categorias": "Survey [survey]: Questionário. | Caso"},
    ])
    assert not PR.so_erros(problemas)
    csv_bytes = PR.exportar_csv(itens)
    assert b"'=SOMA(A1)" in csv_bytes  # injeção de fórmula neutralizada
    for r in (PR.importar(csv_bytes, "csv"), PR.importar(PR.exportar_xlsx(itens), "xlsx")):
        assert not r["erros"], r["erros"]
        assert r["itens"][0]["nome"] == "=SOMA(A1)"  # o apóstrofo é tirado na volta
        assert [{k: v for k, v in i.items()} for i in r["itens"]] == itens
    wb = openpyxl.load_workbook(io.BytesIO(PR.exportar_xlsx(itens)))
    assert wb.sheetnames == ["Protocolo"] and wb["Protocolo"]["B2"].value == "'=SOMA(A1)"


# =============== modelos prontos ===============

def test_modelos_sao_validos_e_tem_definicoes_de_ate_duas_frases():
    assert {m["id"] for m in MO.listar()} == {"partes_artigo", "revisao_sistematica"}
    for mid in ("partes_artigo", "revisao_sistematica"):
        m = MO.obter(mid)
        assert not m["erros"], m["erros"]
        assert all(1 <= PR.contar_frases(i["definicao"]) <= 2 for i in m["itens"])
        assert all(PR.contar_frases(c["definicao"]) <= 1 for i in m["itens"] for c in i["categorias"])
        assert len({i["id"] for i in m["itens"]}) == len(m["itens"])
    partes = MO.obter("partes_artigo")["itens"]
    assert [i["id"] for i in partes] == list(P.CHAVES) and all(i["parte_planilha"] == i["id"] for i in partes)
    rsl = MO.obter("revisao_sistematica")["itens"]
    assert len(rsl) == 12
    assert {i["id"] for i in rsl} >= {"objetivo", "perguntas", "desenho", "amostra", "contexto", "setor", "tecnologia", "achados", "limitacoes", "financiamento", "evidencia"}
    assert {i["tipo"] for i in rsl} >= {"texto", "categoria", "multipla", "numero"}


def test_modelo_partes_do_artigo_reproduz_a_planilha_do_corpus(ambiente):
    """17.1: o modelo "Partes do artigo" usa as mesmas regras da 16.1 (sem copiar regra): trechos idênticos aos da planilha do corpus."""
    amb = ambiente
    _carregar_modelo(amb, "partes_artigo")
    _executar(amb)
    db = _db(amb)
    try:
        plan = svc_planilha.montar(db, amb["pasta"])
    finally:
        db.close()
    celulas = _celulas(amb)
    comparadas = 0
    for linha in plan["linhas"]:
        for parte in P.CHAVES:
            esperado = [t["texto"] for t in linha["partes"][parte]["trechos"]]
            cel = celulas[linha["arquivo"]][parte]
            assert [t["texto"] for t in cel["trechos"]] == esperado[:3], (linha["arquivo"], parte)
            assert (cel["status"] == "nao_encontrado") == (not esperado)
            if esperado:
                assert cel["trechos"][0]["pagina"] == linha["partes"][parte]["trechos"][0]["pagina"]
                comparadas += 1
    assert comparadas > 30


# =============== protocolo versionado ===============

def test_protocolo_versionado_historico_e_restauracao(tmp_path):
    pasta = tmp_path / "proj"
    a = {"id": "a", "nome": "A", "definicao": "Boa definição.", "tipo": "texto"}
    r1 = PR.salvar(pasta, [a])
    assert r1["versao_protocolo"] == 1 and r1["alterado"]
    assert PR.salvar(pasta, [a])["alterado"] is False and PR.carregar(pasta)["versao_protocolo"] == 1  # mesmo conteúdo: mesma versão
    r2 = PR.salvar(pasta, [a, {"id": "b", "nome": "B", "definicao": "Outra.", "tipo": "sim_nao", "palavras_chave": "x"}])
    assert r2["versao_protocolo"] == 2 and (pasta / PR.HISTORICO / "protocolo_coleta_v1.json").is_file()
    assert [v["versao"] for v in PR.listar_historico(pasta)] == [1, 2]
    assert len(PR.ler_versao(pasta, 1)["itens"]) == 1
    r3 = PR.restaurar(pasta, 1)
    assert r3["versao_protocolo"] == 3 and len(r3["itens"]) == 1
    with pytest.raises(PR.ProtocoloInvalido):
        PR.salvar(pasta, [{**a, "definicao": "Um. Dois. Três."}])
    assert PR.carregar(pasta)["versao_protocolo"] == 3  # recusado: nada gravado


# =============== extratores ===============

def _cand(texto, termos, i=0, idioma="en"):
    lem = tk.Lematizador(idioma)
    fi = T.indexar(texto, lem)
    ac = T.acertos(T.compilar(termos, lem), fi)
    return {"f": {"i": i, "texto": texto, "pagina": 3, "secao": "metodos"}, "fi": fi, "acertos": ac, "na_secao": True, "nota": 1.0}


@pytest.mark.parametrize("texto,esperado", [
    ("1,234", 1234), ("1.234", 1234), ("1.234,5", 1234.5), ("1,234.5", 1234.5), ("3.5", 3.5), ("3,5", 3.5), ("312", 312), ("0,500", 0.5),
    ("1.234.567", 1234567), ("2 500", 2500), ("12,5", 12.5),
])
def test_valor_numero_pt_e_en_com_separador_de_milhar(texto, esperado):
    assert E.valor_numero(texto) == esperado


@pytest.mark.parametrize("texto,valor,unidade", [
    ("We surveyed n = 312 founders in the study.", 312, "n"),
    ("The sample comprised 1,200 firms from three countries.", 1200, "firms"),
    ("We received 312 respondents who answered fully.", 312, "respondents"),
    ("A amostra foi composta por 1.200 empresas brasileiras.", 1200, "empresas"),
    ("A sample size of 2.5 thousand firms was drawn.", 2500, None),
    ("Our dataset covers 1 200 startups in total.", 1200, "startups"),
])
def test_extrator_numero_com_unidades_e_separadores_pt_en(texto, valor, unidade):
    c = _cand(texto, ["sample*", "respondent*", "firm*", "startup*", "amostra", "empresa*", "founder*"], idioma="pt" if "amostra" in texto.lower() else "en")
    r = E.extrair_numero([c], True, 3)
    assert r is not None and r["valor"] == valor, r
    if unidade is not None:
        assert (r["unidade"] or "").startswith(unidade)
    assert r["frases"][0]["texto"] == texto


def test_extrator_numero_ignora_anos_tabelas_e_numeros_longe_da_palavra_chave():
    c = _cand("In 2020 the sample was drawn as shown in Table 3 and Figure 2 of Section 4.", ["sample*"])
    assert E.extrair_numero([c], True, 3) is None
    c = _cand("Microsoft 365 Copilot adoption was measured among many large organisations over a long period of time in the market.", ["firms", "adoption"])
    assert E.extrair_numero([c], True, 3) is None
    assert [n["valor"] for n in E.numeros_do_texto("We got 35% of replies and n=40 later.")] == [35, 40]


def test_extrator_sim_nao_com_negacao():
    sim = _cand("The authors used interviews with the founders of many firms.", ["interview*"])
    nao = _cand("We did not use interviews in this study of firms.", ["interview*"], i=1)
    nao2 = _cand("There were no interviews with founders at all.", ["interview*"], i=2)
    assert E.extrair_sim_nao([sim], 3)["valor"] == "sim"
    assert E.extrair_sim_nao([nao], 3)["valor"] == "não"
    assert E.extrair_sim_nao([nao2], 3)["valor"] == "não"
    assert E.extrair_sim_nao([sim, nao], 3)["valor"] == E.AMBIGUO
    assert E.extrair_sim_nao([sim, nao, nao2], 3)["valor"] == "não"
    assert E.extrair_sim_nao([_cand("Nothing relevant is said here about the market.", ["interview*"])], 3) is None  # sem menção: não é "não"


def test_extrator_data_e_ano():
    for texto, valor in [("Data were collected on 2025-03-14 from the platform.", "2025-03-14"), ("The survey ran in March 2024 for all firms.", "2024-03"),
                         ("Collected on 14 de março de 2025 from many firms.", "2025-03-14"), ("The period covers 2020-2024 for all firms.", "2020/2024"),
                         ("We sampled firms in 2023 and followed them for long.", "2023")]:
        r = E.extrair_data([_cand(texto, ["collected", "survey", "period", "sampled", "firms"])], True, 3)
        assert r["valor"] == valor, (texto, r)
    assert E.extrair_data([_cand("As shown by Smith (2020) the sample was large and diverse.", ["sample"])], True, 3) is None  # citação, não data do estudo


def _cats(*pares):
    return [{"valor": v, "definicao": "", "palavras_chave": k} for v, k in pares]


def _por_categoria(cats, frases, idioma="en"):
    lem = tk.Lematizador(idioma)
    saida = {}
    for k, texto in enumerate(frases):
        fi = T.indexar(texto, lem)
        for c in cats:
            ac = T.acertos(T.compilar(E.termos_da_categoria(c), lem), fi)
            if ac:
                saida.setdefault(c["valor"], []).append({"f": {"i": k, "texto": texto, "pagina": 1, "secao": "metodos"}, "fi": fi, "acertos": ac, "na_secao": True, "nota": 0.0})
    return saida


def test_extrator_categoria_com_evidencia_e_empate_vira_ambiguo():
    cats = _cats(("Survey", ["questionnaire*"]), ("Experimento", ["randomi*"]), ("Outro", []))
    r = E.extrair_categoria(_por_categoria(cats, ["We sent a questionnaire to many firms.", "The questionnaire had many items for the founders."]), cats, False, 3)
    assert r["valor"] == "Survey" and len(r["frases"]) == 2 and r["confianca"] > 0.5
    r = E.extrair_categoria(_por_categoria(cats, ["We sent a questionnaire to many firms.", "We randomised the founders into two groups."]), cats, False, 3)
    assert r["valor"] == E.AMBIGUO and len(r["frases"]) == 2  # empate: evidência das duas
    r = E.extrair_categoria(_por_categoria(cats, ["We sent a questionnaire to many firms.", "We randomised the founders into two groups."]), cats, True, 3)
    assert sorted(r["valor"]) == ["Experimento", "Survey"]
    assert E.extrair_categoria({}, cats, False, 3) is None


def test_palavras_chave_com_lema_curinga_frase_e_regex():
    lem = tk.Lematizador("en")
    fi = T.indexar("The agents of the multi-agent systems estimated n = 45 sample sizes.", lem)
    def acha(*b):
        return [a.termo for a in T.acertos(T.compilar(list(b), lem), fi)]
    assert acha("agent") == ["agent", "agent"] or "agent" in acha("agent")   # "agents" casa pelo lema
    assert acha("multi-agent*") and acha("\"sample size\"") and acha("sample size")
    assert acha("/n\\s*=\\s*\\d+/") and not acha("/zzz/") and not acha("robot*")
    assert T.acertos(T.compilar(["AGENT"], lem), fi)  # sem diferenciar caixa
    fi_pt = T.indexar("A avaliação foi feita pelas empresas da amostra.", tk.Lematizador("pt"))
    assert T.acertos(T.compilar(["empresa", "avaliacao"], tk.Lematizador("pt")), fi_pt)  # lema e acento


# =============== conferência do LLM (simulada) ===============

BLOCOS = [{"texto": "We collected data from 1,200 startups across Brazil between 2020 and 2024. The sample was drawn in two waves.", "pagina": 5, "secao": "metodos", "titulo_secao": "Method", "incluir": True},
          {"texto": "The authors declare no competing interests and received funding from the CNPq.", "pagina": 9, "secao": "declaracoes", "titulo_secao": "Funding", "incluir": True}]


def _doc():
    return L.TextoDoDocumento(BLOCOS)


def _item(tipo, **kw):
    base = {"id": "i1", "nome": "Item", "definicao": "Boa.", "tipo": tipo, "max_trechos": 3, "categorias": [], "onde_procurar": ["qualquer"], "palavras_chave": []}
    return {**base, **kw}


def test_llm_trecho_inventado_e_descartado_e_pagina_e_encontrada():
    item = _item("numero")
    r, desc = LC.conferir_resposta(item, {"valor": 1200, "trechos": ["We collected data from 1,200 startups across Brazil between 2020 and 2024.", "Invented sentence that is nowhere in the document text."]}, _doc())
    assert r["valor"] == 1200 and len(r["trechos"]) == 1 and r["trechos"][0]["pagina"] == 5
    assert [d["motivo"] for d in desc] == ["trecho não existe no documento"]
    r, desc = LC.conferir_resposta(item, {"valor": 1200, "trechos": ["Invented sentence that is nowhere in the document text."]}, _doc())
    assert r is None  # sem trecho verificado: descartado


def test_llm_trecho_com_hifenizacao_e_espaco_diferentes_passa_e_palavra_trocada_nao():
    item = _item("sim_nao")
    ok = "The authors declare no  competing inter-ests and received funding from the CNPq."
    r, _ = LC.conferir_resposta(item, {"valor": "yes", "trechos": [ok]}, _doc())
    assert r["valor"] == "sim" and r["trechos"][0]["texto"].startswith("The authors declare no competing interests") and r["trechos"][0]["pagina"] == 9
    r, _ = LC.conferir_resposta(item, {"valor": "sim", "trechos": ["The authors declare no competing interests and received money from the CNPq."]}, _doc())
    assert r is None


def test_llm_categoria_fora_da_lista_e_recusada_e_multipla_filtra():
    cats = [{"valor": "Survey", "definicao": "", "palavras_chave": []}, {"valor": "Caso", "definicao": "", "palavras_chave": []}]
    trecho = "We collected data from 1,200 startups across Brazil between 2020 and 2024."
    r, desc = LC.conferir_resposta(_item("categoria", categorias=cats), {"valor": "Netnografia", "trechos": [trecho]}, _doc())
    assert r is None and desc[0]["motivo"] == "categoria fora da lista permitida"
    r, _ = LC.conferir_resposta(_item("categoria", categorias=cats), {"valor": " survey ", "trechos": [trecho]}, _doc())
    assert r["valor"] == "Survey"
    r, desc = LC.conferir_resposta(_item("multipla", categorias=cats), {"valor": ["Survey", "Inventada", "caso"], "trechos": [trecho]}, _doc())
    assert r["valor"] == ["Survey", "Caso"] and any(d["valor"] == "Inventada" for d in desc)
    r, _ = LC.conferir_resposta(_item("multipla", categorias=cats), {"valor": ["Inventada"], "trechos": [trecho]}, _doc())
    assert r is None


def test_llm_numero_precisa_aparecer_no_trecho():
    trecho = "We collected data from 1,200 startups across Brazil between 2020 and 2024."
    item = _item("numero")
    assert LC.conferir_resposta(item, {"valor": "1.200", "trechos": [trecho]}, _doc())[0]["valor"] == 1200
    r, desc = LC.conferir_resposta(item, {"valor": 999, "trechos": [trecho]}, _doc())
    assert r is None and desc[0]["motivo"] == "o número não aparece nos trechos devolvidos"
    assert LC.conferir_resposta(item, {"valor": "muitos", "trechos": [trecho]}, _doc())[0] is None
    r, _ = LC.conferir_resposta(_item("data"), {"valor": "2020-2024", "trechos": [trecho]}, _doc())
    assert r["valor"] == "2020-2024"
    assert LC.conferir_resposta(_item("data"), {"valor": "2019", "trechos": [trecho]}, _doc())[0] is None


def test_llm_texto_usa_o_trecho_literal_como_valor():
    trecho = "We collected data from 1,200 startups across Brazil between 2020 and 2024."
    r, _ = LC.conferir_resposta(_item("texto"), {"valor": "um resumo inventado pelo modelo", "trechos": [trecho]}, _doc())
    assert r["valor"] == trecho


def test_protocolo_em_cache_e_estavel_e_o_que_muda_vai_na_mensagem_do_usuario():
    itens = MO.obter("revisao_sistematica")["itens"]
    s1, s2 = LC.montar_system(itens), LC.montar_system(list(reversed(itens)))
    assert s1 == s2 and len(s1) == 2  # mesma saída, qualquer ordem de entrada
    assert "cache_control" not in s1[0] and s1[1]["cache_control"] == {"type": "ephemeral"}
    assert "PROTOCOLO DE COLETA" in s1[1]["text"] and "amostra" in s1[1]["text"]
    assert json.loads(s1[1]["text"].split("\n", 1)[1])[0]["id"] == "achados"  # ordenado por id
    u1 = LC.montar_usuario("doc A", itens[:2], {itens[0]["id"]: "[p. 1] frase um."})
    u2 = LC.montar_usuario("doc B", itens[:2], {itens[0]["id"]: "[p. 2] frase dois."})
    assert u1 != u2 and "doc A" in u1 and "doc A" not in s1[1]["text"]


class ProvedorFalso:
    nome = "falso"
    modelo = "falso-1"

    def __init__(self, respostas):
        self.respostas = respostas
        self.chamadas = []

    def gerar(self, system, user):
        self.chamadas.append((system, user))
        resp = self.respostas(user) if callable(self.respostas) else self.respostas
        return {"texto": json.dumps(resp, ensure_ascii=False), "modelo": self.modelo, "uso": {"input_tokens": 10, "output_tokens": 5}, "request_id": None}


def _protocolo_pequeno(amb):
    itens = [i for i in MO.obter("revisao_sistematica")["itens"] if i["id"] in ("amostra", "desenho", "setor")]
    r = amb["c"].put(_url(amb, "protocolo"), json={"itens": itens})
    assert r.status_code == 200, r.text


def test_coleta_com_llm_simulado_so_aceita_o_que_confere(ambiente):
    amb = ambiente
    _protocolo_pequeno(amb)
    _ligar_llm()
    arq = _arquivo(1)
    trecho_ok = "The sample consists of 1,200 startups located in Brazil."

    def resposta(user):
        if "DOCUMENTO" not in user or "1,200" not in user:
            return {}
        return {"amostra": {"valor": 1200, "trechos": [trecho_ok, "Invented sentence that is nowhere in the document text."]},
                "desenho": {"valor": "Netnografia", "trechos": ["We conducted a questionnaire survey with respondents from many firms."]},
                "setor": {"valor": "Tecnologia/software", "trechos": [trecho_ok]}}

    prov = ProvedorFalso(resposta)
    db = _db(amb)
    try:
        res = TR.executar(db, amb["pasta"], {"llm": "todos", "documento_ids": [_id_doc(amb, arq)]}, provedor=prov)
    finally:
        db.close()
    cel = _celulas(amb)[arq]
    assert cel["amostra"]["origem"] == "llm" and cel["amostra"]["valor"] == 1200 and len(cel["amostra"]["trechos"]) == 1
    assert cel["amostra"]["trechos"][0]["pagina"] == 2 and cel["amostra"]["justificativa"] == "LLM: falso-1" and cel["amostra"]["status"] == "sugerido"
    assert cel["desenho"]["origem"] == "regra" and "categoria fora da lista permitida" in cel["desenho"]["llm_descartes"]  # LLM recusado, regra mantida
    assert cel["setor"]["origem"] == "llm" and cel["setor"]["valor"] == "Tecnologia/software"
    assert res["llm"]["descartados"] == 1 and res["llm"]["trechos_verificados"] == 2 and res["llm"]["chamadas"] == 1
    # protocolo inteiro como prefixo estável em todas as chamadas
    assert len({json.dumps(s, sort_keys=True) for s, _u in prov.chamadas}) == 1 and prov.chamadas[0][0][-1]["cache_control"]


def test_llm_desligado_coleta_so_com_regras_e_endpoints_do_llm_dao_409(ambiente):
    amb = ambiente
    _carregar_modelo(amb)
    r = amb["c"].post(_url(amb, "llm/executar?sincrono=1"), json={})
    assert r.status_code == 409 and "Permitir geração com LLM" in r.json()["detail"]
    r = amb["c"].post(_url(amb, "executar?sincrono=1"), json={"llm": "faltantes"})
    assert r.status_code == 409
    res = _executar(amb)  # padrão: só regras
    assert res["calculadas"] == 6 * 12 and res["llm"]["chamadas"] == 0
    assert all(c["origem"] in ("regra", "padrao") for doc in _celulas(amb).values() for c in doc.values())
    assert res["por_status"]["sugerido"] > 20


# =============== coleta por regras (documentos sintéticos) ===============

def test_coleta_por_regras_acha_valores_com_pagina_e_marca_nao_encontrado(ambiente):
    amb = ambiente
    _carregar_modelo(amb)
    _executar(amb)
    cel = _celulas(amb)
    for i, esperado in enumerate(TAMANHOS, 1):
        a = cel[_arquivo(i)]["amostra"]
        assert a["valor"] == esperado and a["status"] == "sugerido" and a["origem"] == "regra", (i, a)
        assert a["trechos"][0]["pagina"] == 2 and "startups" in a["trechos"][0]["texto"]
    assert [cel[_arquivo(i)]["desenho"]["valor"] for i in range(1, 7)] == ["Survey", "Estudo de caso", "Experimento", "Entrevistas/qualitativo", "Survey", "Modelagem/simulação"]
    assert cel[_arquivo(1)]["limitacoes"]["origem"] == "padrao" and "limitation" in cel[_arquivo(1)]["limitacoes"]["valor"]
    assert cel[_arquivo(1)]["contexto"]["trechos"][0]["pagina"] == 2 and "Brazil" in cel[_arquivo(1)]["contexto"]["valor"]
    fin = cel[_arquivo(1)]["financiamento"]  # seção "Acknowledgements" fica fora do texto-base, mas o item a lista em onde_procurar
    assert fin["status"] == "sugerido" and "funded by the CNPq" in fin["valor"] or "CNPq" in fin["valor"]
    assert cel[_arquivo(1)]["evidencia"]["status"] in ("sugerido", "nao_encontrado")
    nao = [c for d in cel.values() for c in d.values() if c["status"] == "nao_encontrado"]
    assert nao and all(c["valor"] is None and c["trechos"] == [] and c["confianca"] == 0 for c in nao)  # nunca valor sem evidência
    assert all(c["trechos"] for d in cel.values() for c in d.values() if c["status"] == "sugerido")


def test_item_sem_palavras_chave_nem_secao_e_nao_encontrado(ambiente):
    amb = ambiente
    r = amb["c"].put(_url(amb, "protocolo"), json={"itens": [{"id": "z", "nome": "Z", "definicao": "Sem pistas.", "tipo": "numero"}]})
    assert r.status_code == 200
    _executar(amb)
    assert all(d["z"]["status"] == "nao_encontrado" for d in _celulas(amb).values())


# =============== execução incremental ===============

def _alterar_texto_limpo(amb, arquivo, antigo, novo):
    doc_id = _id_doc(amb, arquivo)
    caminho = amb["pasta"] / "cache" / "limpo" / f"{doc_id}.json"
    original = caminho.read_bytes()
    dados = json.loads(original.decode("utf-8"))
    n = 0
    for b in dados["blocos"]:
        if antigo in b["texto"]:
            b["texto"] = b["texto"].replace(antigo, novo)
            n += 1
    assert n, antigo
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return caminho, original


def test_reexecucao_so_recalcula_o_que_mudou_e_preserva_o_que_o_revisor_decidiu(ambiente):
    amb = ambiente
    _carregar_modelo(amb)
    r1 = _executar(amb)
    assert r1["calculadas"] == 72 and r1["puladas"] == 0
    r2 = _executar(amb)
    assert r2["calculadas"] == 0 and r2["puladas"] == 72  # nada mudou: nada recalculado
    d1 = _id_doc(amb, _arquivo(1))
    assert amb["c"].post(_url(amb, "celula/decidir"), json={"documento_id": d1, "item": "amostra", "acao": "aceitar"}).status_code == 200
    r = amb["c"].post(_url(amb, "celula/decidir"), json={"documento_id": d1, "item": "desenho", "acao": "editar", "valor": "Estudo de caso", "nota": "visto no PDF"})
    assert r.status_code == 200 and r.json()["origem"] == "humano"
    # 1) muda o texto de um documento: a evidência aceita some -> revisar; as outras células do documento são recalculadas; os outros documentos não
    caminho, original = _alterar_texto_limpo(amb, _arquivo(1), "1,200 startups", "900 startups")
    try:
        r3 = _executar(amb)
        assert r3["preservadas"] == 2 and r3["revisar"] == 1 and r3["calculadas"] == 10 and r3["puladas"] == 60
        cel = _celulas(amb)[_arquivo(1)]
        assert cel["amostra"]["status"] == "aceito" and cel["amostra"]["valor"] == 1200  # não foi sobrescrita
        assert "evidência" in cel["amostra"]["revisar"] and cel["desenho"]["status"] == "editado" and cel["desenho"]["revisar"] is None
        assert cel["desenho"]["valor"] == "Estudo de caso" and cel["desenho"]["nota"] == "visto no PDF"
        m = amb["c"].get(_url(amb, "matriz")).json()
        linha = next(l for l in m["linhas"] if l["arquivo"] == _arquivo(1))
        assert linha["celulas"]["amostra"]["revisar"] and linha["celulas"]["amostra"]["status"] == "aceito"
    finally:
        caminho.write_bytes(original)
    # voltou o texto original: as células não decididas do documento são recalculadas e a marca "revisar" some
    r_volta = _executar(amb)
    assert r_volta["calculadas"] == 10 and r_volta["revisar"] == 0
    assert _celulas(amb)[_arquivo(1)]["amostra"]["revisar"] is None and _celulas(amb)[_arquivo(1)]["amostra"]["status"] == "aceito"
    # 2) muda a definição de um item: só as células desse item são recalculadas
    itens = amb["c"].get(_url(amb, "protocolo")).json()["itens"]
    for i in itens:
        if i["id"] == "contexto":
            i["palavras_chave"] = i["palavras_chave"] + ["Mexico"]
    assert amb["c"].put(_url(amb, "protocolo"), json={"itens": itens}).status_code == 200
    r4 = _executar(amb)
    assert r4["calculadas"] == 6 and r4["puladas"] == 72 - 6 - 2 and r4["preservadas"] == 2
    # 3) forçar recalcula tudo, mas nunca as decididas
    r5 = _executar(amb, forcar=True)
    assert r5["preservadas"] == 2 and r5["calculadas"] == 70
    assert _celulas(amb)[_arquivo(1)]["desenho"]["status"] == "editado"


# =============== decisões na matriz ===============

def test_decisoes_por_celula_e_em_lote(ambiente):
    amb = ambiente
    _carregar_modelo(amb)
    _executar(amb)
    c, d1, d2 = amb["c"], _id_doc(amb, _arquivo(1)), _id_doc(amb, _arquivo(2))
    def dec(doc, item, acao, **kw):
        return c.post(_url(amb, "celula/decidir"), json={"documento_id": doc, "item": item, "acao": acao, **kw})
    assert dec(d1, "amostra", "editar", valor="999 respondentes").json()["valor"] == "999"
    assert _celulas(amb)[_arquivo(1)]["amostra"]["unidade"] == "respondentes"
    assert dec(d1, "desenho", "editar", valor="inventado").status_code == 422  # fora da lista
    assert dec(d1, "setor", "rejeitar").json()["status"] == "rejeitado"
    assert dec(d1, "evidencia", "nao_se_aplica").json()["valor"] == "não se aplica"
    nao = next((i for i in ("perguntas", "limitacoes", "evidencia", "financiamento") if _celulas(amb)[_arquivo(1)][i]["status"] == "nao_encontrado"), None)
    if nao:
        assert dec(d1, nao, "aceitar").status_code == 422  # nada a aceitar
    assert dec(d1, "amostra", "desfazer").json()["status"] == "sugerido" and _celulas(amb)[_arquivo(1)]["amostra"]["valor"] == 1200
    det = c.get(_url(amb, f"celula?documento_id={d2}&item=amostra")).json()
    assert det["celula"]["trechos"][0]["pagina"] == 2 and det["celula"]["trechos"][0]["contexto"]  # link do contexto (KWIC)
    ctx = c.get(det["celula"]["trechos"][0]["contexto"])
    assert ctx.status_code == 200 and "startups" in (ctx.json()["esquerda"] + ctx.json()["termo"] + ctx.json()["direita"])
    # lote por item
    r = c.post(_url(amb, "decidir-lote"), json={"acao": "aceitar", "item": "amostra"}).json()
    assert r["aplicadas"] == 6
    assert all(_celulas(amb)[_arquivo(i)]["amostra"]["status"] == "aceito" for i in range(1, 7))
    # lote por documento: ambíguas e sem valor ficam de fora
    r = c.post(_url(amb, "decidir-lote"), json={"acao": "aceitar", "documento_id": d2}).json()
    assert r["aplicadas"] > 3
    assert all(c_["status"] != "sugerido" or c_["valor"] in (None, E.AMBIGUO) for c_ in _celulas(amb)[_arquivo(2)].values())
    m = c.get(_url(amb, "matriz?status=aceito&item=amostra")).json()
    assert [i["id"] for i in m["itens"]] == ["amostra"] and len(m["linhas"]) == 6
    cont = next(x for x in m["contadores"] if x["id"] == "amostra")
    assert cont["contagem"]["aceito"] == 6 and cont["progresso"] == 1.0
    assert c.get(_url(amb, "matriz?grupo=inexistente")).json()["linhas"] == []


# =============== exportação ===============

def _aceitar_tudo_que_tem_valor(amb):
    c = amb["c"]
    for it in ("amostra", "desenho", "contexto"):
        c.post(_url(amb, "decidir-lote"), json={"acao": "aceitar", "item": it})


def test_exportacoes_larga_e_longa_final_e_auditoria(ambiente):
    amb = ambiente
    c = amb["c"]
    _carregar_modelo(amb)
    _executar(amb)
    _aceitar_tudo_que_tem_valor(amb)
    d1 = _id_doc(amb, _arquivo(1))
    assert c.post(_url(amb, "celula/decidir"), json={"documento_id": d1, "item": "achados", "acao": "editar", "valor": "=HYPERLINK(\"http://x\")"}).status_code == 200
    def xlsx(formato, versao):
        r = c.get(_url(amb, f"exportar?formato={formato}&versao={versao}&extensao=xlsx"))
        assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
        return openpyxl.load_workbook(io.BytesIO(r.content))
    # larga final: só aceitos/editados; coluna de evidência ao lado do valor
    wb = xlsx("larga", "final")
    assert wb.sheetnames == ["Larga", "Protocolo", "LEIA-ME"]
    ws = wb["Larga"]
    cab = [x.value for x in ws[1]]
    assert cab[4:8] == ["objetivo Objetivo", "objetivo evidência", "perguntas Perguntas de pesquisa", "perguntas evidência"]
    col_amostra = cab.index("amostra Amostra/tamanho")
    linhas = {r[1].value: r for r in ws.iter_rows(min_row=2)}
    assert linhas[_arquivo(1)][col_amostra].value == 1200
    assert linhas[_arquivo(1)][col_amostra + 1].value.startswith("[p. 2] The sample consists of 1,200 startups")
    assert linhas[_arquivo(1)][cab.index("objetivo Objetivo")].value is None  # sugerido (não decidido): fora da versão final
    achados = linhas[_arquivo(1)][cab.index("achados Principais achados")].value
    assert achados.startswith("'=HYPERLINK")  # injeção de fórmula neutralizada
    assert [r[0].value for r in wb["Protocolo"].iter_rows(min_row=2, max_col=1)] == [i["id"] for i in MO.obter("revisao_sistematica")["itens"]]
    # larga auditoria: tudo, com status
    wa = xlsx("larga", "auditoria")["Larga"]
    cab_a = [x.value for x in wa[1]]
    assert "objetivo status" in cab_a
    r1 = {r[1].value: r for r in wa.iter_rows(min_row=2)}[_arquivo(1)]
    assert r1[cab_a.index("objetivo Objetivo")].value and "sugerido" in r1[cab_a.index("objetivo status")].value
    assert "aceito" in r1[cab_a.index("amostra status")].value and "regra" in r1[cab_a.index("amostra status")].value
    # longa: uma linha por documento x item x trecho
    wl = xlsx("longa", "auditoria")["Longa"]
    cab_l = [x.value for x in wl[1]]
    assert cab_l[:9] == ["Documento", "Arquivo", "Grupo", "Ano", "Item", "Nome do item", "Tipo", "Valor", "Unidade"]
    linhas_l = list(wl.iter_rows(min_row=2, values_only=True))
    n_esperado = sum(max(1, len(cel["trechos"])) for d in _celulas(amb).values() for cel in d.values())
    assert len(linhas_l) == n_esperado
    amostras = [r for r in linhas_l if r[4] == "amostra" and r[1] == _arquivo(2)]
    assert amostras and amostras[0][7] == 312 and amostras[0][14] == 2 and "312" in amostras[0][13]
    wl_final = xlsx("longa", "final")["Longa"]
    assert {r[9] for r in wl_final.iter_rows(min_row=2, values_only=True)} <= {"aceito", "editado", "não se aplica"}
    # CSV
    r = c.get(_url(amb, "exportar?formato=longa&versao=final&extensao=csv"))
    texto = r.content.decode("utf-8-sig")
    assert r.status_code == 200 and texto.splitlines()[0].startswith("Documento;Arquivo") and "'=HYPERLINK" in texto
    assert c.get(_url(amb, "exportar?formato=larga&versao=final&extensao=csv")).status_code == 200


def test_envio_dos_aceitos_para_a_planilha_de_coleta_com_deduplicacao(ambiente, tmp_path):
    amb = ambiente
    c = amb["c"]
    _carregar_modelo(amb)
    _executar(amb)
    assert c.post(_url(amb, "exportar/mlr"), json={}).status_code == 422  # nada aceito ainda
    _aceitar_tudo_que_tem_valor(amb)
    r = c.post(_url(amb, "exportar/mlr"), json={})
    assert r.status_code == 200
    resumo = json.loads(r.headers["X-Raiox-Resumo"])
    assert resumo["exportados"] >= 12 and resumo["duplicados_na_planilha"] == 0 and resumo["por_origem"] == {"coleta": resumo["selecionados"]}
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["T_Trechos_Tematicos"]
    cab = [x.value for x in ws[1]]
    linhas = list(ws.iter_rows(min_row=2, values_only=True))
    j = cab.index("Trecho original (sentença)")
    assert any("The sample consists of 1,200 startups" in (l[j] or "") for l in linhas)
    assert all((l[cab.index("Motivo da coleta")] or "").startswith("Raio-X: coleta guiada (") for l in linhas)
    # a planilha do usuário (só lida) já tem um dos trechos: vem marcado como duplicado
    ref = tmp_path / "coleta_usuario.xlsx"
    w = openpyxl.Workbook()
    w.active.title = "T_Trechos_Tematicos"
    w.active.append(["ID registro", "ID fonte", "Fonte (autor, ano)", "Trilha", "Página", "Seção", "Trecho original (sentença)", "Código"])
    w.active.append(["R001-01", "R001", "X (2025)", "", 2, "Method", "The sample consists of 1,200 startups located in Brazil.", "C1"])
    w.save(ref)
    antes = ref.read_bytes()
    r = c.post(_url(amb, "exportar/mlr"), json={"planilha_referencia": str(ref), "incluir_duplicados": False})
    assert r.status_code == 200 and json.loads(r.headers["X-Raiox-Resumo"])["duplicados_na_planilha"] >= 1
    assert ref.read_bytes() == antes  # a planilha do usuário não é alterada


# =============== concordância (kappa e alfa da 15.1) ===============

def test_concordancia_sugestao_automatica_x_valor_revisado(ambiente):
    amb = ambiente
    c = amb["c"]
    _carregar_modelo(amb)
    _executar(amb)
    docs = {i: _id_doc(amb, _arquivo(i)) for i in range(1, 7)}
    c.post(_url(amb, "decidir-lote"), json={"acao": "aceitar", "item": "desenho"})
    r = c.post(_url(amb, "celula/decidir"), json={"documento_id": docs[2], "item": "desenho", "acao": "editar", "valor": "Survey"})
    assert r.status_code == 200
    conc = c.get(_url(amb, "concordancia?fonte=revisao")).json()
    d = next(i for i in conc["itens"] if i["id"] == "desenho")
    assert d["n"] == 6 and d["percentual"] == pytest.approx(5 / 6) and d["metrica"] == "nominal"
    auto = ["survey", "estudo de caso", "experimento", "entrevistas/qualitativo", "survey", "modelagem/simulacao"]
    final = ["survey", "survey", "experimento", "entrevistas/qualitativo", "survey", "modelagem/simulacao"]
    esperado = ST.cohen_kappa(auto, final)["kappa"]
    assert d["kappa"] == pytest.approx(esperado) and d["alfa"] == pytest.approx(ST.krippendorff_alfa([auto, final], "nominal")["alfa"])
    assert d["kappa_faixa"] and d["alfa_faixa"]
    assert next(i for i in conc["itens"] if i["id"] == "objetivo")["n"] == 0  # nada decidido: sem pares
    # número só tem concordância exata sem faixas; com faixas calcula kappa/alfa ordinal
    c.post(_url(amb, "decidir-lote"), json={"acao": "aceitar", "item": "amostra"})
    c.post(_url(amb, "celula/decidir"), json={"documento_id": docs[1], "item": "amostra", "acao": "editar", "valor": "300"})
    sem = next(i for i in c.get(_url(amb, "concordancia?fonte=revisao")).json()["itens"] if i["id"] == "amostra")
    assert sem["kappa"] is None and sem["percentual"] == pytest.approx(5 / 6) and "faixas" in sem["nota"]
    com = next(i for i in c.get(_url(amb, "concordancia?fonte=revisao&bandas=100,500,1000")).json()["itens"] if i["id"] == "amostra")
    assert com["metrica"] == "ordinal" and com["n"] == 6 and com["alfa"] is not None and com["kappa"] is not None


def test_concordancia_com_segundo_codificador_importado(ambiente):
    amb = ambiente
    c = amb["c"]
    _carregar_modelo(amb)
    _executar(amb)
    c.post(_url(amb, "decidir-lote"), json={"acao": "aceitar", "item": "desenho"})
    c.post(_url(amb, "decidir-lote"), json={"acao": "aceitar", "item": "amostra"})
    assert c.get(_url(amb, "concordancia?fonte=segundo")).status_code == 409  # ainda sem segundo codificador
    segundo = ["Survey", "Estudo de caso", "Experimento", "Survey", "Survey", "Modelagem/simulação"]  # discorda no documento 4
    conteudo = _csv(["arquivo", "desenho", "amostra Amostra/tamanho"], [[_arquivo(i + 1), segundo[i], ("1.200", "312")[i] if i < 2 else ""] for i in range(6)])
    r = c.post(_url(amb, "concordancia/segundo-codificador?nome=cod2.csv&codificador=Ana"), content=conteudo)
    assert r.status_code == 200, r.text
    assert r.json()["documentos_casados"] == 6 and set(r.json()["itens_reconhecidos"]) >= {"desenho", "amostra"} and not r.json()["nao_casados"]
    conc = c.get(_url(amb, "concordancia?fonte=segundo")).json()
    assert "Ana" in conc["descricao"]
    d = next(i for i in conc["itens"] if i["id"] == "desenho")
    principal = [_celulas(amb)[_arquivo(i)]["desenho"]["valor"] for i in range(1, 7)]
    a = [CC._rotulo(v, "categoria") for v in principal]
    b = [CC._rotulo(v, "categoria") for v in segundo]
    assert d["n"] == 6 and d["percentual"] == pytest.approx(5 / 6)
    assert d["kappa"] == pytest.approx(ST.cohen_kappa(a, b)["kappa"]) and d["alfa"] == pytest.approx(ST.krippendorff_alfa([a, b], "nominal")["alfa"])
    amostra = next(i for i in conc["itens"] if i["id"] == "amostra")
    assert amostra["n"] == 2 and amostra["percentual"] == 1.0  # só os documentos 1 e 2 têm valor do segundo codificador; "1.200" = 1200
    assert c.delete(_url(amb, "concordancia/segundo-codificador")).json() == {"removido": True}
    # formato longo e XLSX
    wb = openpyxl.Workbook()
    wb.active.append(["documento", "item", "valor"])
    wb.active.append([_arquivo(1), "desenho", "Survey"])
    buf = io.BytesIO()
    wb.save(buf)
    r = c.post(_url(amb, "concordancia/segundo-codificador?nome=cod2.xlsx"), content=buf.getvalue())
    assert r.status_code == 200 and r.json()["formato"] == "longa" and r.json()["valores"] == 1


# =============== API: protocolo, execução e progresso ===============

def test_api_protocolo_salvar_recusa_definicao_longa_e_mostra_sugestao(ambiente):
    amb = ambiente
    c = amb["c"]
    item = {"id": "a", "nome": "A", "definicao": "Primeira. Segunda. Terceira.", "tipo": "texto"}
    r = c.put(_url(amb, "protocolo"), json={"itens": [item]})
    assert r.status_code == 422
    det = r.json()["detail"]
    assert "Sugestão de corte" in det["mensagem"] and det["erros"][0]["sugestao"] == "Primeira. Segunda." and det["erros"][0]["linha"] == 1
    assert c.get(_url(amb, "protocolo")).json()["versao_protocolo"] == 0  # nada gravado
    v = c.post(_url(amb, "protocolo/validar"), json={"itens": [item]}).json()
    assert len(v["erros"]) == 1
    r = c.put(_url(amb, "protocolo"), json={"itens": [{**item, "definicao": "Primeira. Segunda."}], "nome": "Meu protocolo"})
    assert r.status_code == 200 and r.json()["versao_protocolo"] == 1
    p = c.get(_url(amb, "protocolo")).json()
    assert p["nome"] == "Meu protocolo" and p["regra_frases"]["max_frases_definicao"] == 2 and "e.g" in p["regra_frases"]["abreviacoes"]
    assert [t["id"] for t in p["tipos"]] == list(PR.TIPOS) and len(p["partes_planilha"]) == 13


def test_api_importar_exportar_modelos_e_historico(ambiente):
    amb = ambiente
    c = amb["c"]
    assert {m["id"] for m in c.get(_url(amb, "protocolo/modelos")).json()["modelos"]} == {"partes_artigo", "revisao_sistematica"}
    assert c.get(_url(amb, "protocolo/modelos/nao_existe")).status_code == 404
    pre = c.post(_url(amb, "protocolo/modelos/partes_artigo/carregar")).json()
    assert pre["aplicado"] is False and len(pre["itens"]) == 13 and c.get(_url(amb, "protocolo")).json()["versao_protocolo"] == 0
    c.post(_url(amb, "protocolo/modelos/partes_artigo/carregar?aplicar=true"))
    ap = c.post(_url(amb, "protocolo/modelos/revisao_sistematica/carregar?aplicar=true&modo=anexar")).json()
    assert ap["aplicado"] and len(ap["itens"]) == 13 + 12 - 3 and ap["versao_protocolo"] == 2  # ids repetidos (objetivo, perguntas, limitacoes) são trocados
    hist = c.get(_url(amb, "protocolo/historico")).json()["versoes"]
    assert [v["versao"] for v in hist] == [1, 2] and hist[0]["itens"] == 13
    assert c.get(_url(amb, "protocolo/historico/1")).json()["itens"][0]["id"] == "resumo"
    assert c.get(_url(amb, "protocolo/historico/9")).status_code == 404
    assert c.post(_url(amb, "protocolo/historico/1/restaurar")).json()["versao_protocolo"] == 3
    csv_ = c.get(_url(amb, "protocolo/exportar.csv"))
    assert csv_.status_code == 200 and csv_.content.decode("utf-8-sig").splitlines()[0].startswith("id;nome;definição;tipo")
    r = c.post(_url(amb, "protocolo/importar?nome=p.csv&aplicar=true&modo=substituir"), content=csv_.content)
    assert r.status_code == 200 and r.json()["aplicado"] and len(r.json()["itens"]) == 13
    xl = c.get(_url(amb, "protocolo/exportar.xlsx"))
    assert openpyxl.load_workbook(io.BytesIO(xl.content)).sheetnames == ["Protocolo"]
    ruim = _csv(["id", "nome", "definição", "tipo"], [["a", "A", "Um. Dois. Três.", "texto"]])
    r = c.post(_url(amb, "protocolo/importar?nome=p.csv&aplicar=true"), content=ruim)
    assert r.status_code == 422 and "Sugestão de corte" in r.json()["detail"]["mensagem"]
    r = c.post(_url(amb, "protocolo/importar?nome=p.csv"), content=ruim)
    assert r.status_code == 200 and r.json()["erros"][0]["sugestao"] == "Um. Dois." and r.json()["aplicado"] is False
    assert c.post(_url(amb, "protocolo/importar"), content=b"").status_code == 400


def test_api_executar_em_segundo_plano_com_progresso(ambiente):
    import time

    amb = ambiente
    c = amb["c"]
    assert c.post(_url(amb, "executar")).status_code == 409  # protocolo vazio
    _carregar_modelo(amb)
    r = c.post(_url(amb, "executar"), json={})
    assert r.status_code == 202 and r.json()["run_id"]
    for _ in range(300):
        p = c.get(_url(amb, "progresso")).json()
        if not p["rodando"]:
            break
        time.sleep(0.2)
    assert not p["rodando"] and p["erro"] is None and p["total"] == 6 and p["feitos"] == 6 and p["calculadas"] == 72
    assert p["resumo"]["calculadas"] == 72 and p["resumo"]["por_status"]["sugerido"] > 20
    m = c.get(_url(amb, "matriz")).json()
    assert m["documentos"] == 6 and len(m["itens"]) == 12 and m["ultima_execucao"]["calculadas"] == 72
    assert c.get(_url(amb, "celula?documento_id=9999&item=amostra")).status_code == 404
    assert c.get(_url(amb, f"celula?documento_id={_id_doc(amb, _arquivo(1))}&item=zzz")).status_code == 404


def test_interface_tem_a_aba_coleta_e_o_contador_ao_vivo():
    base = Path(__file__).resolve().parents[1] / "frontend"
    html = (base / "index.html").read_text(encoding="utf-8")
    assert 'data-aba="coleta"' in html and 'id="aba-coleta"' in html and 'src="coleta.js"' in html
    js = (base / "coleta.js").read_text(encoding="utf-8")
    assert "frases" in js and "regra-frases" not in js or "regra_frases" in js
    assert "'coleta'" in (base / "navegacao.js").read_text(encoding="utf-8")


def test_llm_resposta_em_lista_de_objetos_de_modelo_pequeno_e_aceita():
    texto = 'Aqui vai: [{"amostra": {"valor": 72, "trechos": ["x"]}}, {"desenho": {"valor": "Survey", "trechos": []}}]'
    assert LC.ler_resposta(texto) == {"amostra": {"valor": 72, "trechos": ["x"]}, "desenho": {"valor": "Survey", "trechos": []}}
    assert LC.ler_resposta('```json\n[{"id": "a", "valor": 1, "trechos": []}]\n```') == {"a": {"valor": 1, "trechos": []}}
    assert LC.ler_resposta('{"a": {"valor": 1}}') == {"a": {"valor": 1}}
    with pytest.raises(ValueError):
        LC.ler_resposta("sem json nenhum")
