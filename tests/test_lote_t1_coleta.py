"""9.5 Exportação para a planilha de coleta da MLR: colunas na ordem da aba de trechos, trecho literal, tradução vazia, motivo
"Raio-X: ...", duplicatas por texto normalizado marcadas (e omitidas se pedido), origens (comentário, KWIC, célula do corpus,
codificação LLM, trecho livre), planilha do usuário intacta. Planilha sintética com os nomes de coluna da aba real."""
import hashlib
import io

import pytest
from openpyxl import Workbook, load_workbook

from app import database
from app.models import CodificacaoTrecho, Comentario, Documento, Evidencia
from app.services.concordancia import exportacao_coleta as X
from tests.conftest import texto_longo

CABECALHO = X.COLUNAS_PADRAO


def test_normalizar_e_indice():
    assert X.normalizar_trecho("[p. 3] Não é “bom”… ÓTIMO!") == "nao e bom otimo"
    ind = X.IndiceExistentes()
    longo = "Generative AI lowers the cost of building startups and reshapes how founders allocate their limited attention across tasks."
    ind.adicionar(longo, "R001-T01")
    ind.adicionar("curto", "R001-T02")  # curto demais para checar
    assert ind.achar(longo.upper()) == "R001-T01"
    assert ind.achar(longo[:90] + " (…)") == "R001-T01"  # mesmo início de 60 caracteres normalizados
    assert ind.achar("Outra frase qualquer sobre empreendedorismo e agentes de inteligência artificial em startups.") is None
    assert ind.total == 1


@pytest.fixture()
def planilha_usuario(tmp_path):
    """Planilha sintética: capa, aba de trechos com cabeçalho na linha 2 e dois trechos (um será duplicado)."""
    wb = Workbook()
    wb.active.title = "0_LEIA-ME"
    wb.active["A1"] = "capa"
    ws = wb.create_sheet("T_Trechos_Tematicos")
    ws.append(["Tabela de trechos"])
    ws.append(CABECALHO)
    ws.append(["R001-T01", "R001", "Kim (2025)", "Cinzenta", 1, "Intro", "The analysis of the data shows that the results of the study are consistent.",
               "A análise ...", "C3.1", "x", "T3", "", "QP3", "", "motivo", "", "E1", "direta", "sentença completa", None, None, None])
    ws.append(["R002-T01", "R002", "Silva (2025)", "Branca", 2, "Método", "Texto totalmente diferente que não está no corpus de teste de forma alguma aqui.",
               "", "C1.1", "x", "T1", "", "QP1", "", "motivo", "", "E1", "direta", "sentença completa", None, None, None])
    caminho = tmp_path / "Coleta_sintetica.xlsx"
    wb.save(caminho)
    return caminho


@pytest.fixture()
def projeto_coleta(client, projeto, projetos_dir):
    assert client.post(f"/api/projetos/{projeto}/executar?sincrono=1").status_code == 200
    return projeto


def _banco(slug):
    return database.sessao_do_projeto(slug)


def _inserir_comentario_aceito(slug, trecho, pagina=None):
    b = _banco(slug)
    try:
        doc = b.query(Documento).order_by(Documento.id).first()
        ev = Evidencia(documento_id=doc.id, pagina=pagina, trecho=trecho)
        c = Comentario(regra="regra-teste", texto="comentário", status="aceito")
        c.evidencias.append(ev)
        b.add(c)
        b.commit()
        return doc.id, c.id
    finally:
        b.close()


def _linhas(resposta):
    wb = load_workbook(io.BytesIO(resposta.content))
    ws = wb[wb.sheetnames[0]]
    return wb, [list(r) for r in ws.iter_rows(values_only=True)]


def test_exporta_comentarios_e_marca_duplicata(client, projeto_coleta, planilha_usuario):
    slug = projeto_coleta
    sha = hashlib.sha256(planilha_usuario.read_bytes()).hexdigest()
    doc_id, _cid = _inserir_comentario_aceito(slug, "The analysis of the data shows that the results of the study are consistent.", 1)
    _inserir_comentario_aceito(slug, "The founders of small startups rely on generative tools for most routine decisions in 2025.", 2)
    corpo = {"selecao": [{"tipo": "comentario"}], "planilha_referencia": str(planilha_usuario)}
    previa = client.post(f"/api/projetos/{slug}/exportar/coleta/previa", json=corpo)
    assert previa.status_code == 200, previa.text
    pj = previa.json()
    assert pj["selecionados"] == 2 and pj["exportados"] == 2 and pj["duplicados_na_planilha"] == 1 and pj["trechos_na_planilha"] == 2
    assert pj["duplicados"][0]["registro"] == "R001-T01"
    r = client.post(f"/api/projetos/{slug}/exportar/coleta.xlsx", json=corpo)
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and "X-Raiox-Resumo" in r.headers
    wb, linhas = _linhas(r)
    assert linhas[0] == CABECALHO  # mesmas colunas, na mesma ordem (cabeçalho copiado da planilha do usuário)
    assert wb.sheetnames == ["T_Trechos_Tematicos", "Resumo"]
    por_texto = {l[CABECALHO.index("Trecho original (sentença)")]: l for l in linhas[1:]}
    dup = por_texto["The analysis of the data shows that the results of the study are consistent."]
    assert dup[CABECALHO.index("Observação")].startswith("DUPLICADO") and "R001-T01" in dup[CABECALHO.index("Observação")]
    novo = por_texto["The founders of small startups rely on generative tools for most routine decisions in 2025."]
    assert novo[CABECALHO.index("Observação")] in (None, "")
    assert novo[CABECALHO.index("Trecho traduzido (PT-BR)")] in (None, "")  # tradução fica vazia
    assert novo[CABECALHO.index("Motivo da coleta")].startswith("Raio-X: comentário aceito")
    assert novo[CABECALHO.index("Página")] == 2 and novo[CABECALHO.index("Sentença verificada (auto)")] == "não localizado no texto"
    assert novo[CABECALHO.index("ID registro")].startswith("RX-") and novo[CABECALHO.index("Trilha")] in (None, "")
    assert dup[CABECALHO.index("Sentença verificada (auto)")] == "verbatim (Raio-X)"
    # omitir duplicadas
    omit = client.post(f"/api/projetos/{slug}/exportar/coleta.xlsx", json={**corpo, "incluir_duplicados": False})
    assert len(_linhas(omit)[1]) == 2 and omit.headers["X-Raiox-Resumo"].count("exportados\": 1") == 1
    # a planilha do usuário não foi tocada
    assert hashlib.sha256(planilha_usuario.read_bytes()).hexdigest() == sha


def test_sem_planilha_usa_cabecalho_padrao_e_get(client, projeto_coleta):
    slug = projeto_coleta
    _inserir_comentario_aceito(slug, "The analysis of the data shows that the results of the study are consistent.", 1)
    r = client.get(f"/api/projetos/{slug}/exportar/coleta.xlsx")
    assert r.status_code == 200
    _wb, linhas = _linhas(r)
    assert linhas[0] == CABECALHO and len(linhas) == 2
    assert linhas[1][CABECALHO.index("ID fonte")] == "R001" and linhas[1][CABECALHO.index("Fonte (autor, ano)")] == "Kim (2026)"
    assert client.get(f"/api/projetos/{slug}/exportar/coleta.xlsx", params={"origens": "kwic"}).status_code == 422


def test_origens_kwic_celula_codificacao_e_livre(client, projeto_coleta):
    slug = projeto_coleta
    b = _banco(slug)
    try:
        doc = b.query(Documento).order_by(Documento.id).first()
        b.add(CodificacaoTrecho(documento_id=doc.id, texto="The analysis of the data shows consistent results.", pagina=1, codigo_llm="C3.1",
                                tema_humano="T3 Resultados", status="codificado", modelo="modelo-x", confianca=0.9))
        b.add(CodificacaoTrecho(documento_id=doc.id, texto="Pendente de codificar nunca vai.", status="pendente"))
        b.commit()
        doc_id = doc.id
    finally:
        b.close()
    selecao = [{"tipo": "kwic", "consulta": "analysis", "por": "forma", "limite": 5},
               {"tipo": "codificacao"},
               {"tipo": "trecho", "documento_id": doc_id, "texto": "Um trecho livre escolhido pelo usuário na tela.", "codigo": "C9", "tema": "T9"},
               {"tipo": "celula", "documento_id": doc_id, "parte": "resultados"}]
    r = client.post(f"/api/projetos/{slug}/exportar/coleta.xlsx", json={"selecao": selecao})
    assert r.status_code == 200, r.text
    _wb, linhas = _linhas(r)
    cab, corpo = linhas[0], linhas[1:]
    motivos = [l[cab.index("Motivo da coleta")] for l in corpo]
    assert any(m.startswith("Raio-X: KWIC") for m in motivos)
    cod = next(l for l in corpo if "codificação LLM" in l[cab.index("Motivo da coleta")])
    assert cod[cab.index("Código")] == "C3.1" and cod[cab.index("Tema")] == "T3 Resultados"
    livre = next(l for l in corpo if l[cab.index("Código")] == "C9")
    assert livre[cab.index("Tema")] == "T9" and livre[cab.index("Sentença verificada (auto)")] == "não localizado no texto"
    assert not any("Pendente" in str(l[cab.index("Trecho original (sentença)")]) for l in corpo)
    # KWIC: o trecho é a frase inteira, literal
    kw = next(l for l in corpo if l[cab.index("Motivo da coleta")].startswith("Raio-X: KWIC"))
    assert "analysis" in kw[cab.index("Trecho original (sentença)")].lower() and kw[cab.index("Sentença verificada (auto)")] == "verbatim (Raio-X)"


def test_erros(client, projeto_coleta, tmp_path):
    slug = projeto_coleta
    base = f"/api/projetos/{slug}/exportar/coleta.xlsx"
    assert client.post(base, json={"selecao": [{"tipo": "comentario"}]}).status_code == 422  # sem comentários aceitos
    assert client.post(base, json={"selecao": []}).status_code == 422
    assert client.post(base, json={"selecao": [{"tipo": "trecho", "texto": "x y z"}], "planilha_referencia": str(tmp_path / "nao.xlsx")}).status_code == 422
    assert client.post(base, json={"selecao": [{"tipo": "celula", "documento_id": 99, "parte": "limitacoes"}]}).status_code == 422
    assert client.post(base, json={"selecao": [{"tipo": "kwic", "posicoes": ["abc"]}]}).status_code == 422
