"""Frente 2: metadados manuais, grupos/CSV, conversão e controle de qualidade. Não exigem Docling."""
import json

import pytest

from app import database
from app.models import Documento
from app.services.etapas import conversao
from app.services.etapas.qualidade import avaliar_texto, detectar_idioma
from app.services.texto import palavras

TEXTO_EN = (
    "The study of the effects of the new method on the performance of the teams is that it can be used "
    "for all of the projects in which they were involved, and this is what we would also expect. "
) * 12
TEXTO_PT = (
    "O estudo dos efeitos do novo método sobre o desempenho das equipes mostra que ele pode ser usado "
    "para todos os projetos em que elas estavam envolvidas, e isso é o que também esperamos. "
) * 12
TEXTO_ES = (
    "El estudio de los efectos del nuevo método sobre el rendimiento de los equipos muestra que se puede "
    "usar para todos los proyectos en los que estaban involucrados, y esto es lo que también esperamos. "
) * 12


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return r.json()


def _docs(client, slug):
    return {d["arquivo"]: d for d in client.get(f"/api/projetos/{slug}/documentos").json()}


def _etapa(resumo, nome):
    return next(e for e in resumo["etapas"] if e["etapa"] == nome)


def _novo_projeto(client, pasta, nome="Projeto F2"):
    r = client.post("/api/projetos", json={"nome": nome, "pasta_origem": str(pasta)})
    assert r.status_code == 201, r.text
    return r.json()["slug"]


@pytest.fixture()
def corpus(tmp_path):
    pasta = tmp_path / "corpus"
    pasta.mkdir()
    (pasta / "001_2026_Kim_Artigo_En.md").write_text(TEXTO_EN, encoding="utf-8")
    (pasta / "002_2025_Silva_Artigo_Pt.md").write_text(TEXTO_PT, encoding="utf-8")
    return pasta


# ---------- 2.2 edição manual ----------

def test_patch_metadados_sobrevive_a_nova_varredura(client, corpus):
    slug = _novo_projeto(client, corpus)
    _executar(client, slug)
    doc = _docs(client, slug)["001_2026_Kim_Artigo_En.md"]
    assert (doc["id_estudo"], doc["ano"], doc["autor"]) == ("001", 2026, "Kim")

    r = client.patch(f"/api/projetos/{slug}/documentos/{doc['id']}", json={"autor": "Kim Hyunso", "grupo": "academica"})
    assert r.status_code == 200
    assert r.json()["autor"] == "Kim Hyunso" and r.json()["grupo"] == "academica"
    assert r.json()["ano"] == 2026  # campos não enviados ficam como estavam

    # arquivo alterado + nova varredura: metadados manuais continuam
    (corpus / "001_2026_Kim_Artigo_En.md").write_text(TEXTO_EN + " Mais texto.", encoding="utf-8")
    _executar(client, slug)
    doc = _docs(client, slug)["001_2026_Kim_Artigo_En.md"]
    assert doc["status"] == "alterado"
    assert (doc["autor"], doc["grupo"], doc["ano"]) == ("Kim Hyunso", "academica", 2026)

    # null e texto vazio limpam o campo
    r = client.patch(f"/api/projetos/{slug}/documentos/{doc['id']}", json={"grupo": "", "ano": None})
    assert r.json()["grupo"] is None and r.json()["ano"] is None
    assert client.patch(f"/api/projetos/{slug}/documentos/9999", json={"grupo": "x"}).status_code == 404


# ---------- 2.3 grupos e CSV ----------

def test_csv_com_bom_aplicado_e_linhas_sem_arquivo(client, corpus, projetos_dir):
    slug = _novo_projeto(client, corpus)
    csv_texto = (
        "arquivo;grupo;id_estudo;qp\n"
        "001_2026_Kim_Artigo_En.md;academica;R001;QP1\n"
        "002_2025_Silva_Artigo_Pt.md;cinzenta;;\n"
        "nao_existe.pdf;academica;R999;QP2\n"
    )
    (projetos_dir / slug / "documentos.csv").write_bytes(b"\xef\xbb\xbf" + csv_texto.encode("utf-8"))

    resumo = _executar(client, slug)
    msg = json.loads(_etapa(resumo, "metadados_csv")["mensagens"][0])
    assert msg["linhas"] == 3 and msg["aplicadas"] == 2 and msg["sem_arquivo"] == ["nao_existe.pdf"]

    docs = _docs(client, slug)
    d1, d2 = docs["001_2026_Kim_Artigo_En.md"], docs["002_2025_Silva_Artigo_Pt.md"]
    assert (d1["grupo"], d1["id_estudo"], d1["qp"]) == ("academica", "R001", "QP1")  # CSV vence o nome do arquivo
    assert (d2["grupo"], d2["id_estudo"], d2["qp"]) == ("cinzenta", "002", None)  # célula vazia não apaga

    grupos = {g["grupo"]: g["documentos"] for g in client.get(f"/api/projetos/{slug}/grupos").json()}
    assert grupos == {"academica": 1, "cinzenta": 1}


def test_upload_documentos_csv(client, corpus, projetos_dir):
    slug = _novo_projeto(client, corpus)
    _executar(client, slug)
    conteudo = "Arquivo;Grupo\n002_2025_Silva_Artigo_Pt.md;cinzenta\nfantasma.md;x\n".encode("cp1252")
    r = client.post(f"/api/projetos/{slug}/documentos-csv", content=conteudo)
    assert r.status_code == 200 and r.json()["aplicadas"] == 1 and r.json()["sem_arquivo"] == ["fantasma.md"]
    assert (projetos_dir / slug / "documentos.csv").is_file()
    assert _docs(client, slug)["002_2025_Silva_Artigo_Pt.md"]["grupo"] == "cinzenta"
    assert client.post(f"/api/projetos/{slug}/documentos-csv", content=b"grupo;qp\nx;y\n").status_code == 400
    assert client.post(f"/api/projetos/{slug}/documentos-csv", content=b"").status_code == 400


# ---------- 2.4 conversão ----------

def test_conversao_md_e_txt_vai_para_cache_e_mantem_marcadores(client, tmp_path, projetos_dir):
    pasta = tmp_path / "origem"
    pasta.mkdir()
    com_marcas = "<!-- Fonte: x.pdf | Docling | páginas: 2 -->\n\n<!-- página 1 -->\n\n" + TEXTO_EN + "\n\n<!-- página 2 -->\n\n" + TEXTO_EN
    (pasta / "a.md").write_bytes(com_marcas.replace("\n", "\r\n").encode("utf-8"))
    (pasta / "b.txt").write_bytes(TEXTO_PT.encode("cp1252"))
    antes = {p.name: p.read_bytes() for p in pasta.iterdir()}

    slug = _novo_projeto(client, pasta)
    _executar(client, slug)
    docs = _docs(client, slug)

    da, db_ = docs["a.md"], docs["b.txt"]
    assert da["caminho_md"] == f"cache/md/{da['id']}.md" and da["convertido_em"]
    md = (projetos_dir / slug / da["caminho_md"]).read_text(encoding="utf-8")
    assert "<!-- página 1 -->" in md and "<!-- página 2 -->" in md and "\r" not in md
    assert da["paginas"] == 2

    assert "estudo" in (projetos_dir / slug / db_["caminho_md"]).read_text(encoding="utf-8")  # cp1252 lido
    assert db_["paginas"] is None
    # nada foi escrito na pasta de origem
    assert {p.name: p.read_bytes() for p in pasta.iterdir()} == antes

    # segunda execução: cache
    r2 = _executar(client, slug)
    assert _etapa(r2, "conversao")["pulado"] == 2


def test_pdf_sem_docling_vira_com_problema(client, tmp_path, monkeypatch):
    def sem_docling():
        raise conversao.DoclingIndisponivel(conversao.MSG_SEM_DOCLING)

    monkeypatch.setattr(conversao, "_importar_docling", sem_docling)
    pasta = tmp_path / "pdfs"
    pasta.mkdir()
    (pasta / "003_2024_Souza_Doc.pdf").write_bytes(b"%PDF-1.4 falso")
    (pasta / "004_2024_Lima_Texto.md").write_text(TEXTO_EN, encoding="utf-8")

    slug = _novo_projeto(client, pasta)
    resumo = _executar(client, slug)  # não derruba o pipeline
    assert _etapa(resumo, "conversao")["ok"] == 1  # o .md convertido normalmente

    docs = _docs(client, slug)
    pdf = docs["003_2024_Souza_Doc.pdf"]
    assert pdf["status"] == "com_problema"
    assert pdf["problemas"] == ["Docling não instalado — rode instalar_docling.bat"]
    assert docs["004_2024_Lima_Texto.md"]["status"] == "novo"

    # problema de ambiente: nova execução tenta de novo (e falha de novo), sem travar
    resumo = _executar(client, slug)
    assert _etapa(resumo, "conversao")["erro"] == 1
    assert _docs(client, slug)["003_2024_Souza_Doc.pdf"]["status"] == "com_problema"

    pend = {p["arquivo"]: p for p in client.get(f"/api/projetos/{slug}/pendencias").json()}
    assert pend["003_2024_Souza_Doc.pdf"]["problemas"] == ["Docling não instalado — rode instalar_docling.bat"]


def test_com_problema_e_reprocessado_quando_o_arquivo_muda(client, tmp_path):
    pasta = tmp_path / "vazio"
    pasta.mkdir()
    arq = pasta / "vazio.md"
    arq.write_text("quase nada", encoding="utf-8")
    slug = _novo_projeto(client, pasta)
    _executar(client, slug)
    assert _docs(client, slug)["vazio.md"]["status"] == "com_problema"
    _executar(client, slug)
    assert _docs(client, slug)["vazio.md"]["status"] == "com_problema"  # sem mudança: continua pendente

    arq.write_text(TEXTO_EN, encoding="utf-8")
    _executar(client, slug)
    doc = _docs(client, slug)["vazio.md"]
    assert doc["status"] == "alterado" and doc["problemas"] == [] and doc["idioma"] == "en"


def test_parametro_conversao_ocr_e_repassado(client, tmp_path, monkeypatch):
    usados = []
    monkeypatch.setattr(conversao, "_converter_com_docling", lambda origem, ocr, *_: (usados.append(ocr), ("<!-- página 1 -->\n" + TEXTO_EN, {}))[1])
    pasta = tmp_path / "p"
    pasta.mkdir()
    (pasta / "x.pdf").write_bytes(b"%PDF")
    slug = _novo_projeto(client, pasta)
    assert client.get(f"/api/projetos/{slug}/parametros").json()["conversao"] == {"ocr": False}
    _executar(client, slug)
    params = client.get(f"/api/projetos/{slug}/parametros").json()
    params["conversao"]["ocr"] = True
    client.put(f"/api/projetos/{slug}/parametros", json=params)
    _executar(client, slug)
    assert usados == [False, True]


# ---------- 2.5 qualidade ----------

def test_qc_documento_vazio():
    r = avaliar_texto("<!-- página 1 -->\n\nSó umas poucas palavras.", ["en", "pt"])
    assert r["problemas"] == ["documento sem texto"]


def test_qc_escaneado_com_paginas_vazias():
    md = "".join(f"<!-- página {n} -->\n\n{TEXTO_EN if n == 1 else '<!-- image -->'}\n\n" for n in range(1, 5))
    r = avaliar_texto(md, ["en"])
    assert r["problemas"] == ["provável PDF escaneado — reconverter com OCR"]
    assert r["paginas_quase_vazias"] == [2, 3, 4]


def test_qc_paginas_quase_vazias_sao_so_aviso():
    md = "".join(f"<!-- página {n} -->\n\n{'curta' if n == 3 else TEXTO_EN}\n\n" for n in range(1, 5))
    r = avaliar_texto(md, ["en"])
    assert r["problemas"] == [] and r["paginas_quase_vazias"] == [3]
    assert r["avisos"] == ["páginas quase vazias: 3"]


def test_qc_idioma():
    assert detectar_idioma(palavras(TEXTO_EN)) == "en"
    assert detectar_idioma(palavras(TEXTO_PT)) == "pt"
    assert detectar_idioma(palavras(TEXTO_ES)) == "es"
    assert detectar_idioma(palavras("zzz qqq xxx yyy")) is None
    r = avaliar_texto(TEXTO_ES, ["en", "pt"])
    assert r["idioma"] == "es" and r["avisos"] == ["idioma 'es' fora dos esperados (en, pt)"]


def test_pipeline_qualidade_pendencias_e_duplicado(client, tmp_path):
    pasta = tmp_path / "qc"
    pasta.mkdir()
    (pasta / "a_original.md").write_text(TEXTO_EN, encoding="utf-8")
    (pasta / "b_copia.md").write_text(TEXTO_EN, encoding="utf-8")
    (pasta / "c_espanhol.md").write_text(TEXTO_ES, encoding="utf-8")
    (pasta / "d_vazio.md").write_text("<!-- página 1 -->\n\nnada", encoding="utf-8")
    (pasta / "e_ok.md").write_text(TEXTO_PT, encoding="utf-8")

    slug = _novo_projeto(client, pasta)
    _executar(client, slug)
    docs = _docs(client, slug)
    assert docs["d_vazio.md"]["status"] == "com_problema" and docs["d_vazio.md"]["problemas"] == ["documento sem texto"]
    assert docs["a_original.md"]["idioma"] == "en" and docs["e_ok.md"]["idioma"] == "pt"
    assert docs["a_original.md"]["avisos"] == []
    assert docs["b_copia.md"]["avisos"] == ["duplicado de a_original.md"]

    pend = {p["arquivo"]: p for p in client.get(f"/api/projetos/{slug}/pendencias").json()}
    assert set(pend) == {"b_copia.md", "c_espanhol.md", "d_vazio.md"}
    assert pend["d_vazio.md"]["status"] == "com_problema" and pend["d_vazio.md"]["problemas"] == ["documento sem texto"]
    assert pend["b_copia.md"]["avisos"] == ["duplicado de a_original.md"]
    assert pend["c_espanhol.md"]["avisos"] == ["idioma 'es' fora dos esperados (en, pt)"]

    # reexecução usa cache da qualidade e mantém os resultados
    r2 = _executar(client, slug)
    assert _etapa(r2, "qualidade")["pulado"] == 4  # d_vazio saiu (com_problema)
    assert {p["arquivo"] for p in client.get(f"/api/projetos/{slug}/pendencias").json()} == set(pend)


def test_migracao_adiciona_colunas_em_banco_antigo(projetos_dir):
    """Banco criado antes da Frente 2 (sem qp/convertido_em/caminho_md) ganha as colunas ao abrir."""
    from sqlalchemy import create_engine, inspect, text

    pasta = projetos_dir / "antigo"
    pasta.mkdir(parents=True)
    eng = create_engine(f"sqlite:///{(pasta / 'projeto.sqlite').as_posix()}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE documento (id INTEGER PRIMARY KEY, arquivo TEXT, status VARCHAR(20))"))
    eng.dispose()
    colunas = {c["name"] for c in inspect(database.engine_do_projeto("antigo")).get_columns("documento")}
    assert {"qp", "convertido_em", "caminho_md"} <= colunas
