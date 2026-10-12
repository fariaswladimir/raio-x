"""Frente 9 - Laudo HTML (9.1) e exportação CSV (9.2). Sem LLM, sem Docling (reusa o corpus sintético da Frente 8)."""
import csv
import html
import io
import re
import zipfile

import pytest

from app.models import Comentario
from app.services import parametros as svc_parametros
from app.services.analises import dados
from app.services.exportar import laudo_html, planilhas
from tests.test_frente8 import corpus8, listar, proj8  # noqa: F401  (fixtures e utilitário)

EDITADO = "Texto editado pelo revisor: ‘zorblax’ marca o grupo alfa."


def agir(client, slug, cid, **corpo):
    r = client.patch(f"/api/projetos/{slug}/comentarios/{cid}", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


def visivel(texto_html: str) -> str:
    """Texto que o leitor vê (sem tags, com entidades resolvidas)."""
    return html.unescape(re.sub(r"<[^>]+>", "", texto_html))


@pytest.fixture()
def proj9(client, proj8):  # noqa: F811
    """Projeto da Frente 8 com revisão: aceitos de várias regras, 1 editado (com nota), 1 rejeitado e o resto pendente."""
    slug = proj8
    lista = listar(client, slug, status="sugerido")
    escolhidos, vistos = [], set()
    for c in lista:  # um aceito por regra, no máximo 6 regras
        if c["regra"] not in vistos and len(vistos) < 6:
            vistos.add(c["regra"])
            escolhidos.append(c)
    editado, aceitos = escolhidos[0], escolhidos[1:]
    for c in aceitos:
        agir(client, slug, c["id"], acao="aceitar", revisor="Ana")
    agir(client, slug, editado["id"], acao="editar", texto=EDITADO, revisor="Beto")
    agir(client, slug, editado["id"], acao="anotar", nota="Conferir com o artigo original.")
    restantes = [c for c in lista if c["id"] not in {e["id"] for e in escolhidos}]
    rejeitado = restantes[0]
    agir(client, slug, rejeitado["id"], acao="rejeitar", revisor="Ana")
    return {"slug": slug, "editado": editado, "aceitos": aceitos, "rejeitado": rejeitado,
            "pendentes": [c for c in restantes[1:]]}


def gerar(client, slug):
    r = client.post(f"/api/projetos/{slug}/laudo")
    assert r.status_code == 200, r.text
    g = client.get(f"/api/projetos/{slug}/laudo")
    assert g.status_code == 200
    return r.json(), g.text


# ---------- 9.1 laudo ----------

def test_laudo_so_tem_comentarios_aceitos_ou_editados(client, proj9):
    slug = proj9["slug"]
    info, laudo = gerar(client, slug)
    visto = visivel(laudo)
    for c in proj9["aceitos"]:
        assert c["texto"] in visto, c["regra"]
    assert EDITADO in visto  # o editado mostra o texto humano
    assert proj9["rejeitado"]["texto"] not in visto
    for c in proj9["pendentes"]:
        assert c["texto"] not in visto, f"comentário pendente apareceu no laudo: {c['chave']}"
    assert info["aceitos"] == len(proj9["aceitos"]) + 1
    ids_no_laudo = set(re.findall(r'<article class="cm" id="c-(\d+)"', laudo))
    assert ids_no_laudo == {str(c["id"]) for c in [*proj9["aceitos"], proj9["editado"]]}


def test_laudo_editado_mostra_texto_humano_e_nota(client, proj9):
    _info, laudo = gerar(client, proj9["slug"])
    assert "st-editado" in laudo
    assert "Conferir com o artigo original." in laudo
    assert "Beto" in laudo and "Ana" in laudo  # revisores


def test_laudo_avisa_quantos_comentarios_aguardam_revisao(client, proj9):
    info, laudo = gerar(client, proj9["slug"])
    n = len(proj9["pendentes"])
    assert n > 0 and info["pendentes"] == n
    assert f"{n} comentários aguardam revisão — não entraram no laudo" in visivel(laudo)
    assert "1 rejeitado(s)" in visivel(laudo)


def test_laudo_evidencia_com_rotulo_e_pagina(client, proj9):
    _info, laudo = gerar(client, proj9["slug"])
    citacoes = re.findall(r"\(D\d\d · Autor \d{4}, p\. \d+\)", visivel(laudo))
    assert len(citacoes) >= 3
    assert "<mark>" in laudo  # termo destacado no trecho


def test_laudo_numeros_do_comentario_levam_as_evidencias(client, proj9):
    _info, laudo = gerar(client, proj9["slug"])
    alvos = set(re.findall(r'<a class="num" href="#ev-(\d+)">', laudo))
    assert alvos
    for cid in alvos:
        assert f'id="ev-{cid}"' in laudo


def test_laudo_metodos_com_equivalencias_e_referencias(client, proj9):
    _info, laudo = gerar(client, proj9["slug"])
    metodos = laudo.split('id="metodos"')[1].split('id="resultados"')[0]
    texto = visivel(metodos)
    assert "Equivale a" in texto and "Não é igual a" in texto
    assert "Voyant Terms/Cirrus" in texto  # frequências
    assert "AntConc Keywords" in texto and "TF-IDF" in texto  # keyness
    assert "RAYSON, P.; GARSIDE, R." in texto and "HARDIE, A." in texto  # ABNT, do catálogo único
    assert "COVINGTON, M. A.; MCFALL, J. D." in texto  # MATTR (resumo)
    analises_aceitas = {c["analise_tipo"] for c in [*proj9["aceitos"], proj9["editado"]]}
    if "colocacoes" in analises_aceitas:
        assert "CHURCH, K. W.; HANKS, P." in texto and "LancsBox Collocates" in texto


def test_laudo_parametros_e_hash(client, proj9, projetos_dir):
    slug = proj9["slug"]
    _info, laudo = gerar(client, slug)
    params = svc_parametros.carregar(projetos_dir / slug)
    assert svc_parametros.hash_parametros(params) in laudo
    assert '"versao_parametros"' in html.unescape(laudo)
    assert "Última execução de cada etapa" in laudo and "comentarios" in laudo
    assert "Gerado sem LLM; comentários produzidos por regras e revisados por humano" in laudo


def test_laudo_autossuficiente_e_utf8(client, proj9, projetos_dir):
    slug = proj9["slug"]
    _info, laudo = gerar(client, slug)
    bruto = (projetos_dir / slug / "saidas" / "laudo.html").read_bytes()
    bruto.decode("utf-8")  # não levanta
    assert not re.search(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", laudo, re.I)
    assert not re.search(r"<link\b|<script[^>]*\bsrc=|@import|url\(\s*[\"']?https?:", laudo, re.I)
    assert "prefers-color-scheme: dark" in laudo and "@media print" in laudo
    assert 'name="viewport"' in laudo and "<svg" in laudo


def test_laudo_get_404_antes_de_gerar_e_409_sem_pipeline(client, projeto):
    assert client.get(f"/api/projetos/{projeto}/laudo").status_code == 404
    assert client.get(f"/api/projetos/{projeto}/laudo/info").json() == {"existe": False}
    r = client.post(f"/api/projetos/{projeto}/laudo")
    assert r.status_code == 409 and "pipeline" in r.json()["detail"]


def test_laudo_sem_comentarios_aceitos_nao_quebra(client, proj8):
    info, laudo = gerar(client, proj8)
    assert info["aceitos"] == 0
    assert "Nenhum comentário foi aceito ainda" in laudo
    assert "comentários aguardam revisão" in visivel(laudo)
    assert client.get(f"/api/projetos/{proj8}/laudo/info").json()["existe"] is True


def test_laudo_escapa_html_do_texto_editado(client, proj9):
    slug = proj9["slug"]
    agir(client, slug, proj9["editado"]["id"], acao="editar", texto="<script>alerta()</script> várias vezes & 'aspas'")
    _info, laudo = gerar(client, slug)
    assert "<script>alerta()</script>" not in laudo
    assert "&lt;script&gt;" in laudo


# ---------- 9.2 CSV ----------

def ler_csv(client, slug, nome):
    r = client.get(f"/api/projetos/{slug}/exportar/{nome}.csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf"), "sem BOM UTF-8"
    texto = r.content.decode("utf-8-sig")
    assert "\r\n" in texto
    linhas = list(csv.reader(io.StringIO(texto, newline=""), delimiter=";"))
    return linhas[0], linhas[1:]


def test_csv_documentos(client, proj9):
    cab, linhas = ler_csv(client, proj9["slug"], "documentos")
    assert cab[:3] == ["id", "arquivo", "rotulo"] and {"status", "paginas", "idioma", "palavras_corpo", "mattr", "problemas"} <= set(cab)
    assert len(linhas) == 11  # 10 documentos + curto.md (com problema)
    col = {n: i for i, n in enumerate(cab)}
    curto = next(l for l in linhas if l[col["arquivo"]] == "curto.md")
    assert curto[col["status"]] == "com_problema" and curto[col["problemas"]] and curto[col["palavras_corpo"]] == ""
    d01 = next(l for l in linhas if l[col["arquivo"]] == "d01.md")
    assert d01[col["grupo"]] == "alfa" and d01[col["id_estudo"]] == "D01" and int(d01[col["palavras_corpo"]]) > 0
    assert "," not in d01[col["mattr"]] and 0 < float(d01[col["mattr"]]) <= 1  # decimal com ponto


def test_csv_frequencias(client, proj9):
    cab, linhas = ler_csv(client, proj9["slug"], "frequencias")
    assert cab == ["posicao", "lema", "frequencia", "por_10_mil", "documentos"]
    assert len(linhas) > 20 and linhas[0][0] == "1"
    freqs = [int(l[2]) for l in linhas]
    assert freqs == sorted(freqs, reverse=True)
    assert any(l[1] == "zorblax" for l in linhas)


def test_csv_keyness(client, proj9):
    cab, linhas = ler_csv(client, proj9["slug"], "keyness")
    assert cab[:5] == ["grupo_a", "contra", "lado", "posicao", "lema"] and {"g2", "p", "log_ratio", "pct_diff"} <= set(cab)
    assert {l[0] for l in linhas} == {"alfa", "beta", "gama"}
    assert any(l[2] == "A sobre-representado" and l[4] == "zorblax" and l[0] == "alfa" for l in linhas)
    col = {n: i for i, n in enumerate(cab)}
    assert all(float(l[col["g2"]]) > 0 for l in linhas if l[2].startswith("A"))


def test_csv_colocacoes_usa_termos_dos_comentarios_aceitos(client, proj9):
    cab, linhas = ler_csv(client, proj9["slug"], "colocacoes")
    assert cab == ["no", "posicao", "colocado", "o11", "c1", "e11", "ll", "p", "mi", "t", "logdice", "pares"]
    assert linhas
    nos = {l[0] for l in linhas}
    termos = set()
    for c in [*proj9["aceitos"], proj9["editado"]]:
        t = laudo_html.comum.termo_da_chave(c["chave"])
        if t:
            termos.add(t)
    if termos:
        assert nos <= termos


def test_csv_colocacoes_sem_aceitos_usa_os_dez_termos_mais_frequentes(client, proj8):
    cab, linhas = ler_csv(client, proj8, "colocacoes")
    assert 1 <= len({l[0] for l in linhas}) <= 10


def test_csv_comentarios_e_evidencias(client, proj9):
    slug = proj9["slug"]
    todos = listar(client, slug)
    cab, linhas = ler_csv(client, slug, "comentarios")
    assert len(linhas) == len(todos)
    assert cab[:5] == ["id", "chave", "regra", "analise", "status"]
    assert {"texto", "texto_original", "revisor", "nota", "criado_em", "atualizado_em", "m_g2"} <= set(cab)
    col = {n: i for i, n in enumerate(cab)}
    por_id = {int(l[col["id"]]): l for l in linhas}
    ed = por_id[proj9["editado"]["id"]]
    assert ed[col["status"]] == "editado" and ed[col["texto"]] == EDITADO and ed[col["texto_original"]] != EDITADO
    assert ed[col["revisor"]] == "Beto" and ed[col["nota"]] == "Conferir com o artigo original."
    assert {l[col["status"]] for l in linhas} >= {"aceito", "editado", "rejeitado", "sugerido"}

    cab_e, linhas_e = ler_csv(client, slug, "evidencias")
    assert cab_e == ["comentario_id", "comentario_chave", "regra", "status", "documento_id", "documento", "arquivo", "pagina", "trecho", "termo"]
    assert len(linhas_e) == sum(len(c["evidencias"]) for c in todos) > 0
    assert sum(l[7].isdigit() for l in linhas_e) >= len(linhas_e) // 2  # página presente na maioria (R02 cita documentos inteiros)


def test_csv_aspas_e_separador_no_texto():
    bruto = planilhas.csv_bytes(["a", "b"], [["x;y", 'diz "oi"\nlinha 2'], [0.5, None]])
    assert bruto.startswith(b"\xef\xbb\xbf")
    linhas = list(csv.reader(io.StringIO(bruto.decode("utf-8-sig"), newline=""), delimiter=";"))
    assert linhas == [["a", "b"], ["x;y", 'diz "oi"\nlinha 2'], ["0.5", ""]]


def test_csv_nome_invalido_e_sem_pipeline(client, proj8, projeto):
    assert client.get(f"/api/projetos/{proj8}/exportar/inexistente.csv").status_code == 404
    assert client.get(f"/api/projetos/{projeto}/exportar/frequencias.csv").status_code == 409
    # comentarios.csv não depende do vocabulário? Depende só do banco: segue funcionando
    assert client.get(f"/api/projetos/{projeto}/exportar/comentarios.csv").status_code == 200


def test_csv_decimais_com_ponto_e_sem_milhar():
    assert planilhas._n(1234.5) == "1234.5" and planilhas._n(0.000012345678912) == "1.234567891e-05" and planilhas._n(None) == ""


# ---------- pacote ----------

def test_pacote_zip(client, proj9, projetos_dir):
    slug = proj9["slug"]
    r = client.post(f"/api/projetos/{slug}/exportar/pacote.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    esperados = {"laudo.html", "laudo.docx", "parametros.json", "LEIAME.txt", *[f"{n}.csv" for n in planilhas.NOMES]}
    assert set(z.namelist()) == esperados
    assert "Gerado sem LLM" in z.read("laudo.html").decode("utf-8")
    assert z.read("documentos.csv").startswith(b"\xef\xbb\xbf")
    assert z.read("parametros.json") == (projetos_dir / slug / "parametros.json").read_bytes()
    assert "PONTO" in z.read("LEIAME.txt").decode("utf-8")
    saidas = projetos_dir / slug / "saidas"
    assert {p.name for p in saidas.iterdir()} >= {"laudo.html", "pacote.zip", "documentos.csv", "evidencias.csv"}


def test_pacote_sem_pipeline_409(client, projeto):
    assert client.post(f"/api/projetos/{projeto}/exportar/pacote.zip").status_code == 409


def test_laudo_nao_escreve_na_pasta_de_origem(client, proj9, corpus8):
    antes = sorted(p.name for p in corpus8.iterdir())
    client.post(f"/api/projetos/{proj9['slug']}/laudo")
    client.post(f"/api/projetos/{proj9['slug']}/exportar/pacote.zip")
    assert sorted(p.name for p in corpus8.iterdir()) == antes


def test_csv_neutraliza_formula_e_preserva_numeros():
    from app.services.exportar.planilhas import csv_bytes
    texto = csv_bytes(["a", "b", "c"], [["=SOMA(A1)", "-12.5", "- item de lista"]]).decode("utf-8-sig")
    linha = texto.splitlines()[1]
    assert linha == "'=SOMA(A1);-12.5;'- item de lista"
