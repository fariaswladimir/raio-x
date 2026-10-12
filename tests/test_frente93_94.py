"""9.3 Laudo DOCX e 9.4 Texto de Métodos (determinístico). Corpus sintético da Frente 8 com revisão da Frente 9."""
import io
import zipfile

from docx import Document

from tests.test_frente8 import corpus8, listar, proj8  # noqa: F401
from tests.test_frente9 import EDITADO, gerar, proj9  # noqa: F401


def _docx(client, slug):
    r = client.get(f"/api/projetos/{slug}/laudo/docx")
    assert r.status_code == 200, r.text
    return Document(io.BytesIO(r.content))


def test_laudo_docx_tem_secoes_comentarios_e_referencias(client, proj9):
    slug = proj9["slug"]
    info, _ = gerar(client, slug)
    assert info["arquivo_docx"] == "saidas/laudo.docx" and info["tamanho_docx_bytes"] > 5000
    d = _docx(client, slug)
    titulos = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    for esperado in ("1. Identificação", "2. Corpus", "3. Métodos", "4. Resultados", "5. Notas do revisor", "6. Parâmetros e registro de execução"):
        assert esperado in titulos
    assert d.paragraphs[0].style.name == "Title"
    texto = "\n".join(p.text for p in d.paragraphs)
    for c in proj9["aceitos"]:
        assert c["texto"] in texto
    assert EDITADO in texto and "Conferir com o artigo original." in texto
    assert proj9["rejeitado"]["texto"] not in texto
    assert any(p.text.startswith("“") and ", p. " in p.text for p in d.paragraphs)  # evidência "(rótulo, p. N)"
    refs = [p.text for p in d.paragraphs if p.style.name == "List Number"]
    assert refs and all(r.strip() for r in refs)
    assert len(d.tables) >= 4


def test_docx_entra_no_pacote_e_na_info(client, proj9):
    slug = proj9["slug"]
    r = client.post(f"/api/projetos/{slug}/exportar/pacote.zip")
    assert r.status_code == 200
    nomes = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "laudo.docx" in nomes and "laudo.html" in nomes
    assert client.get(f"/api/projetos/{slug}/laudo/info").json()["docx"] is True


def test_docx_404_antes_de_gerar(client, proj8):
    assert client.get(f"/api/projetos/{proj8}/laudo/docx").status_code == 404


def test_metodos_pt_abnt_e_deterministico(client, proj9):
    slug = proj9["slug"]
    a = client.get(f"/api/projetos/{slug}/metodos-texto").json()
    b = client.get(f"/api/projetos/{slug}/metodos-texto").json()
    assert a == b
    titulos = [p["titulo"] for p in a["paragrafos"]]
    assert titulos[0] == "Corpus" and titulos[1] == "Pré-processamento"
    corpus = a["paragrafos"][0]["texto"]
    assert "documentos" in corpus and "palavras" in corpus
    assert "frequencias" in a["analises"] and "keyness" in a["analises"]
    assert any("(" in p["texto"] and ", 19" in p["texto"] or ", 20" in p["texto"] for p in a["paragrafos"][2:])  # citação (Autor, ano)
    assert a["referencias"] and "Uso de modelo de linguagem" not in titulos
    assert "Referências" in a["texto"] and a["markdown"].startswith("## Métodos")


def test_metodos_apa_en_md_e_docx(client, proj9):
    slug = proj9["slug"]
    en = client.get(f"/api/projetos/{slug}/metodos-texto", params={"idioma": "en", "estilo": "apa"}).json()
    assert en["titulo"] == "Methods" and en["paragrafos"][0]["texto"].startswith("The corpus comprises")
    assert any("(" in r and ")." in r for r in en["referencias"])
    pt = client.get(f"/api/projetos/{slug}/metodos-texto", params={"estilo": "apa"}).json()
    assert pt["referencias"] != client.get(f"/api/projetos/{slug}/metodos-texto").json()["referencias"]
    md = client.get(f"/api/projetos/{slug}/metodos-texto", params={"formato": "md"})
    assert md.status_code == 200 and md.text.startswith("## Métodos")
    dx = client.get(f"/api/projetos/{slug}/metodos-texto", params={"formato": "docx"})
    assert dx.status_code == 200
    d = Document(io.BytesIO(dx.content))
    assert any(p.text.startswith("Corpus. ") for p in d.paragraphs)


def test_metodos_so_declara_llm_com_comentario_llm_aceito(client, proj9):
    import json
    from app.database import sessao_do_projeto
    from app.models import Comentario
    slug = proj9["slug"]
    banco = sessao_do_projeto(slug)
    try:
        banco.add(Comentario(regra="LLM:modelo-x", texto="x", status="aceito", origem="llm", analise_tipo="resumo",
                             chave="llm|resumo|a|b", metricas_json=json.dumps({"llm": {"provedor": "ollama", "modelo": "modelo-x"}})))
        banco.commit()
    finally:
        banco.close()
    m = client.get(f"/api/projetos/{slug}/metodos-texto").json()
    assert m["llm"] == ["ollama: modelo-x"]
    assert any(p["titulo"] == "Uso de modelo de linguagem" and "modelo-x" in p["texto"] for p in m["paragrafos"])


def test_nota_metodologica_servida_e_com_secoes(client):
    r = client.get("/api/metodologia/nota")
    assert r.status_code == 200 and r.text.startswith("# Nota metodológica")
    for trecho in ("G² de 2 células", "0,5 no lugar do zero", "Convenção de sinal", "ramos pequenos", "(planejado)", "## 13. Referências"):
        assert trecho in r.text
