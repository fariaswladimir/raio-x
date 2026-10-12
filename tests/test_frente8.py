"""Frente 8 - Catálogo de regras (8.1), motor com reconciliação e API de revisão (8.2). Sem LLM, sem Docling."""
import json

import pytest
import yaml
from sqlalchemy import select

from app import database
from app.models import Comentario, Documento
from app.services.analises import dados
from app.services.regras import catalogo, motor
from app.services.regras.avaliadores import AVALIADORES, montar_trecho
from app.services.regras.catalogo import Candidato, CatalogoInvalido, Regra, interpretar, renderizar, valor_p_texto

BASE = "The analysis of the data shows that the results of the study are consistent. "
CATALOGO_ORIGINAL = catalogo.CATALOGO_PADRAO

# Ajustes do catálogo para o corpus sintético (poucos documentos): só afrouxam limiares e tetos.
AJUSTES_BASE = {
    "R03": {"condicao": {"min_documentos": 3, "z_min": 0.1}},
    "R07": {"max_comentarios": 20},
    "R09": {"max_comentarios": 100, "condicao": {"n_termos": 25, "mi_min": 1.0}},
}


def _md(*paginas: str) -> str:
    return "".join(f"\n\n<!-- página {i + 1} -->\n\n{t}" for i, t in enumerate(paginas))


# (arquivo, id_estudo, ano, grupo, texto da página 2, texto da página 3)
DOCS = [
    ("d01.md", "D01", 2024, "alfa", "zorblax engine runs the model. " * 20 + "trendword appears. " * 2, ""),
    ("d02.md", "D02", 2024, "alfa", "zorblax engine runs the model. " * 20 + "trendword appears. " * 2, ""),
    ("d03.md", "D03", 2025, "alfa", "zorblax engine runs the model. " * 20 + "trendword appears. " * 2, "vexil crystal. " * 40),
    ("d04.md", "D04", 2025, "alfa", "zorblax engine runs the model. " * 20 + "trendword appears. " * 2, ""),
    ("d05.md", "D05", 2025, "beta", "The quokka habitat is wide. " * 20 + "trendword appears. " * 2, ""),
    ("d06.md", "D06", 2026, "beta", "The quokka habitat is wide. " * 20 + "trendword grows. " * 10, ""),
    ("d07.md", "D07", 2026, "beta", "The quokka habitat is wide. " * 20 + "trendword grows. " * 10, ""),
    ("d08.md", "D08", 2026, "beta", "The quokka habitat is wide. " * 20 + "trendword grows. " * 10, ""),
    ("d09.md", "D09", 2026, "gama", "The plinth statue is old. " * 20 + "trendword grows. " * 10, ""),
    ("d10.md", "D10", 2026, "gama", "The plinth statue is old. " * 20 + "trendword grows. " * 10, ""),
]


@pytest.fixture()
def corpus8(tmp_path):
    pasta = tmp_path / "corpus8"
    pasta.mkdir()
    for arquivo, _i, _ano, _g, p2, p3 in DOCS:
        (pasta / arquivo).write_text(_md(BASE * 45, BASE * 5 + p2, p3 or BASE * 5), encoding="utf-8")
    (pasta / "curto.md").write_text("Texto curto demais.", encoding="utf-8")  # reprovado na qualidade -> com_problema
    return pasta


def ajustar_catalogo(monkeypatch, tmp_path, ajustes: dict | None = None, nome: str = "catalogo.yaml"):
    """Copia o catálogo padrão aplicando ``ajustes`` ({id: {chave: valor, "condicao": {...}}}) e aponta RAIOX_CATALOGO para ele."""
    conteudo = yaml.safe_load(CATALOGO_ORIGINAL.read_text(encoding="utf-8"))
    for r in conteudo["regras"]:
        for k, v in (ajustes or {}).get(r["id"], {}).items():
            if k == "condicao":
                r.setdefault("condicao", {}).update(v)
            else:
                r[k] = v
    caminho = tmp_path / nome
    caminho.write_text(yaml.safe_dump(conteudo, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("RAIOX_CATALOGO", str(caminho))
    return caminho


def executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return r.json()


def etapa_comentarios(resumo: dict) -> dict:
    return next(e for e in resumo["etapas"] if e["etapa"] == "comentarios")


@pytest.fixture()
def proj8(client, corpus8, monkeypatch, tmp_path):
    """Projeto com o corpus sintético executado até a etapa de comentários."""
    ajustar_catalogo(monkeypatch, tmp_path, AJUSTES_BASE)
    r = client.post("/api/projetos", json={"nome": "Projeto F8", "pasta_origem": str(corpus8)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    executar(client, slug)
    docs = {d["arquivo"]: d["id"] for d in client.get(f"/api/projetos/{slug}/documentos").json()}
    for arquivo, ident, ano, grupo, *_ in DOCS:
        r = client.patch(f"/api/projetos/{slug}/documentos/{docs[arquivo]}",
                         json={"grupo": grupo, "ano": ano, "id_estudo": ident, "autor": "Autor"})
        assert r.status_code == 200, r.text
    resumo = executar(client, slug)
    assert resumo["erros"] == 0, resumo
    dados.limpar_caches()
    return slug


def listar(client, slug, **params):
    r = client.get(f"/api/projetos/{slug}/comentarios", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def por_chave(lista):
    return {c["chave"]: c for c in lista}


def por_regra(lista, regra):
    return [c for c in lista if c["regra"] == regra]


# ---------- catálogo: leitura e validação ----------

def test_catalogo_padrao_carrega_dez_regras_validas():
    regras = catalogo.carregar_catalogo(CATALOGO_ORIGINAL)
    assert [r.id for r in regras] == [f"R{i:02d}" for i in range(1, 11)]
    assert {r.analise for r in regras} == {"resumo", "frequencias", "tendencias", "keyness", "colocacoes"}
    assert all(r.ativa and r.max_comentarios >= 1 for r in regras)
    assert next(r for r in regras if r.id == "R07").condicao["p_max"] == 0.01


def _yaml(regras: list[dict]) -> dict:
    return {"regras": regras}


REGRA_OK = {"id": "R04", "analise": "frequencias", "modelo": "‘{termo}’ ocorre {freq} vezes.", "condicao": {"top_n": 3}}


@pytest.mark.parametrize("mudanca, trecho", [
    ({"analise": "outra"}, "analise 'outra' inválida"),
    ({"analise": "keyness"}, "trabalha com a análise 'frequencias'"),
    ({"modelo": "‘{termo}’ tem {inexistente}"}, "campos inexistentes: {inexistente}"),
    ({"modelo": "‘{termo’ aberto"}, "modelo mal formado"),
    ({"modelo": "{termo:d}"}, "não pôde ser preenchido"),
    ({"condicao": {"top_n": "cinco"}}, "'top_n' deve ser inteiro"),
    ({"condicao": {"top_n": 0}}, "'top_n' deve ser >= 1"),
    ({"condicao": {"limiar_inventado": 1}}, "limiar desconhecido em 'condicao': limiar_inventado"),
    ({"max_comentarios": -1}, "'max_comentarios' deve ser um número inteiro >= 0"),
    ({"evidencias": "muitas"}, "'evidencias' deve ser um número inteiro"),
    ({"ativa": "sim"}, "'ativa' deve ser true ou false"),
    ({"avaliador": "R99"}, "não há lógica para 'R99'"),
])
def test_regra_invalida_da_erro_claro_com_a_regra_e_o_campo(mudanca, trecho):
    with pytest.raises(CatalogoInvalido) as e:
        interpretar(_yaml([{**REGRA_OK, **mudanca}]))
    assert trecho in str(e.value) and "Regra R04" in str(e.value)


def test_catalogo_malformado(tmp_path):
    for conteudo, trecho in (("regras: [", "não é um YAML válido"), ("outra: 1", "item 'regras'"), ("regras:\n  - 5", "Regra nº 1")):
        arq = tmp_path / "c.yaml"
        arq.write_text(conteudo, encoding="utf-8")
        with pytest.raises(CatalogoInvalido) as e:
            catalogo.carregar_catalogo(arq)
        assert trecho in str(e.value)
    with pytest.raises(CatalogoInvalido, match="não encontrado"):
        catalogo.carregar_catalogo(tmp_path / "nao_existe.yaml")
    with pytest.raises(CatalogoInvalido, match="id repetido"):
        interpretar(_yaml([REGRA_OK, REGRA_OK]))
    with pytest.raises(CatalogoInvalido, match="falta o campo 'id'"):
        interpretar(_yaml([{"analise": "frequencias", "modelo": "x"}]))


def test_regra_duplicada_com_outro_id_usa_avaliador():
    regras = interpretar(_yaml([REGRA_OK, {**REGRA_OK, "id": "R04b", "avaliador": "R04", "condicao": {"top_n": 1}}]))
    assert [(r.id, r.avaliador, r.condicao["top_n"]) for r in regras] == [("R04", "R04", 3), ("R04b", "R04", 1)]


def test_todo_avaliador_tem_modelo_padrao_coerente():
    """Os campos de exemplo de cada avaliador preenchem o modelo do catálogo (nenhum campo esquecido)."""
    for regra in catalogo.carregar_catalogo(CATALOGO_ORIGINAL):
        assert renderizar(regra.modelo, AVALIADORES[regra.avaliador]["campos"])


# ---------- renderização pt-BR ----------

def test_numeros_em_ptbr():
    assert renderizar("{a} / {b} / {c:.1f} / {d:,d} / {e}", {"a": 1234567, "b": 3.14159, "c": 2007.34, "d": 1000, "e": "x.y,z"}) == \
        "1.234.567 / 3,14 / 2.007,3 / 1.000 / x.y,z"
    assert renderizar("{v:.3f}", {"v": 0.5213}) == "0,521"
    assert renderizar("{v:.1f}", {"v": 7}) == "7,0"  # inteiro com formato decimal
    assert valor_p_texto(0.0000001) == "p < 0,001" and valor_p_texto(0.0042) == "p = 0,004"


def test_montar_trecho_limita_em_300_e_mantem_o_termo():
    esq, termo, dir_ = "palavra " * 60, "alvo", " depois" * 60
    t = montar_trecho(esq, termo, dir_)
    assert len(t) <= 300 and "alvo" in t and t.startswith("…") and t.endswith("…")
    assert montar_trecho("antes ", "alvo", " depois") == "antes alvo depois"
    assert len(montar_trecho("x" * 500, "alvo", "y" * 500)) <= 300


# ---------- reconciliação (sem pipeline) ----------

@pytest.fixture()
def banco(client, projeto):
    db = database.sessao_do_projeto(projeto)
    db.add_all([Documento(arquivo="a.md", status="processado"), Documento(arquivo="b.md", status="processado")])
    db.commit()
    yield db
    db.close()


REGRA_TESTE = Regra("R04", "R04", "frequencias", "", {}, "{termo}", 5, 3, True)


def cand(chave="R04|termo=x", texto="‘x’ aparece 10 vezes.", forca=1.0, trecho="trecho um", doc=1, pagina=3):
    evid = [{"documento_id": doc, "pagina": pagina, "trecho": trecho, "termo": "x", "posicao": 7}]
    return Candidato(REGRA_TESTE, chave, {"termo": "x"}, {"freq": 10}, forca, lambda n: evid, texto=texto, evidencias=evid,
                     hash_evidencia=motor.hash_das_evidencias(evid))


def gravar(db, *candidatos):
    cont = motor.reconciliar(db, list(candidatos))
    db.commit()
    return cont


def obter(db, chave="R04|termo=x") -> Comentario:
    db.expire_all()
    return db.scalars(select(Comentario).where(Comentario.chave == chave)).one()


def test_novo_vira_sugerido_com_evidencia(banco):
    cont = gravar(banco, cand())
    c = obter(banco)
    assert cont["novos"] == 1 and c.status == "sugerido" and c.texto == c.texto_original == "‘x’ aparece 10 vezes."
    assert [(e.documento_id, e.pagina, e.trecho, e.posicao) for e in c.evidencias] == [(1, 3, "trecho um", 7)]
    assert c.analise_tipo == "frequencias" and json.loads(c.metricas_json) == {"freq": 10} and c.hash_evidencia


def test_sugerido_e_atualizado_com_texto_e_evidencia_novos(banco):
    gravar(banco, cand())
    cont = gravar(banco, cand(texto="‘x’ aparece 12 vezes.", trecho="trecho dois", pagina=5))
    c = obter(banco)
    assert cont["atualizados"] == 1 and c.status == "sugerido" and c.texto == "‘x’ aparece 12 vezes."
    assert [(e.pagina, e.trecho) for e in c.evidencias] == [(5, "trecho dois")]
    assert banco.scalars(select(Comentario)).all().__len__() == 1


def test_aceito_igual_continua_aceito(banco):
    gravar(banco, cand())
    obter(banco).status = "aceito"
    banco.commit()
    gravar(banco, cand(forca=9.0))
    c = obter(banco)
    assert c.status == "aceito" and c.forca == 9.0 and not motor.ler_historico(c)


def test_aceito_vira_revisar_quando_a_evidencia_muda_e_guarda_o_anterior(banco):
    gravar(banco, cand())
    c = obter(banco)
    c.status = "aceito"
    banco.commit()
    gravar(banco, cand(trecho="outro trecho", pagina=9))  # mesmo texto, evidência diferente
    c = obter(banco)
    assert c.status == "revisar" and c.texto == "‘x’ aparece 10 vezes."
    assert [e.trecho for e in c.evidencias] == ["outro trecho"]
    h = motor.ler_historico(c)
    assert h[-1]["evento"] == "revisar" and h[-1]["status_anterior"] == "aceito" and "evidências mudaram" in h[-1]["motivo"]
    assert h[-1]["evidencias_anteriores"][0]["trecho"] == "trecho um" and h[-1]["texto_anterior"] == "‘x’ aparece 10 vezes."


def test_aceito_vira_revisar_quando_os_numeros_mudam(banco):
    gravar(banco, cand())
    obter(banco).status = "aceito"
    banco.commit()
    gravar(banco, cand(texto="‘x’ aparece 99 vezes."))
    c = obter(banco)
    assert c.status == "revisar" and c.texto == "‘x’ aparece 10 vezes." and c.texto_original == "‘x’ aparece 99 vezes."
    assert "números" in motor.ler_historico(c)[-1]["motivo"]
    gravar(banco, cand(texto="‘x’ aparece 100 vezes."))  # segue em revisão, com a proposta mais recente
    c = obter(banco)
    assert c.status == "revisar" and c.texto_original == "‘x’ aparece 100 vezes." and len(motor.ler_historico(c)) == 1


def test_editado_mantem_o_texto_humano(banco):
    gravar(banco, cand())
    c = obter(banco)
    c.status, c.texto = "editado", "Meu texto revisado."
    banco.commit()
    gravar(banco, cand())  # nada mudou
    assert (obter(banco).status, obter(banco).texto) == ("editado", "Meu texto revisado.")
    gravar(banco, cand(texto="‘x’ aparece 50 vezes."))
    c = obter(banco)
    assert c.status == "revisar" and c.texto == "Meu texto revisado." and c.texto_original == "‘x’ aparece 50 vezes."
    assert motor.ler_historico(c)[-1]["status_anterior"] == "editado"


def test_rejeitado_nao_ressuscita_e_atualiza_metricas(banco):
    gravar(banco, cand())
    obter(banco).status = "rejeitado"
    banco.commit()
    cont = gravar(banco, cand(texto="‘x’ aparece 77 vezes.", trecho="novo", forca=5.0))
    c = obter(banco)
    assert c.status == "rejeitado" and cont["rejeitados_mantidos"] == 1 and c.forca == 5.0 and c.texto == "‘x’ aparece 10 vezes."
    gravar(banco)  # a chave deixa de ser gerada: continua rejeitada (não vira obsoleta)
    assert obter(banco).status == "rejeitado"


def test_chave_que_some_vira_obsoleta_e_volta_ao_status_anterior(banco):
    gravar(banco, cand("R04|termo=a"), cand("R04|termo=b"), cand("R04|termo=c"))
    for chave, status in (("a", "aceito"), ("b", "rejeitado")):
        obter(banco, f"R04|termo={chave}").status = status
        banco.commit()
    cont = gravar(banco)  # nenhuma chave gerada
    assert cont["obsoletos"] == 2  # a (aceito) e c (sugerido); b rejeitado fica
    assert [obter(banco, f"R04|termo={k}").status for k in "abc"] == ["obsoleto", "rejeitado", "obsoleto"]
    cont = gravar(banco, cand("R04|termo=a"), cand("R04|termo=c"))
    assert cont["reativados"] == 2
    assert [obter(banco, f"R04|termo={k}").status for k in "ac"] == ["aceito", "sugerido"]


def test_comentario_antigo_sem_chave_nao_e_tocado(banco):
    banco.add(Comentario(regra="manual", texto="Escrito à mão", status="aceito"))
    banco.commit()
    gravar(banco)
    antigo = banco.scalars(select(Comentario).where(Comentario.regra == "manual")).one()
    assert antigo.status == "aceito" and antigo.chave is None


# ---------- migração ----------

def test_migracao_acrescenta_colunas_em_banco_antigo(projetos_dir):
    from sqlalchemy import create_engine, inspect, text

    pasta = projetos_dir / "antigo"
    pasta.mkdir(parents=True)
    eng = create_engine(f"sqlite:///{(pasta / 'projeto.sqlite').as_posix()}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE comentario (id INTEGER PRIMARY KEY, regra VARCHAR(100), texto TEXT, status VARCHAR(15), "
                          "revisor VARCHAR(200), criado_em DATETIME, atualizado_em DATETIME)"))
        conn.execute(text("CREATE TABLE evidencia (id INTEGER PRIMARY KEY, documento_id INTEGER, pagina INTEGER, trecho TEXT)"))
        conn.execute(text("INSERT INTO comentario (regra, texto, status) VALUES ('antiga', 'texto', 'sugerido')"))
    from app.database import _adicionar_colunas_novas
    for tabela in ("projeto", "documento", "execucao", "analise"):  # tabelas que a migração também consulta
        from app.models import Base
        Base.metadata.tables[tabela].create(eng)
    _adicionar_colunas_novas(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("comentario")}
    assert {"chave", "analise_tipo", "metricas_json", "forca", "hash_evidencia", "texto_original", "nota", "historico_json"} <= cols
    assert {"termo", "posicao"} <= {c["name"] for c in inspect(eng).get_columns("evidencia")}
    with eng.begin() as conn:
        assert conn.execute(text("SELECT regra, chave FROM comentario")).one() == ("antiga", None)
    eng.dispose()


# ---------- as dez regras no corpus sintético ----------

def test_regras_disparam_no_corpus_sintetico(client, proj8):
    todos = listar(client, proj8)
    assert all(c["status"] == "sugerido" for c in todos)
    # cada comentário tem evidência (documento + página ou linha de métrica); os de termo trazem o termo no trecho
    for c in todos:
        assert c["evidencias"], c["chave"]
    assert {c["regra"] for c in todos} == {"R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10"}

    r01 = por_regra(todos, "R01")[0]
    assert r01["texto"].startswith("O corpus tem 10 documentos (") and "publicados entre 2024 e 2026" in r01["texto"]
    assert "alfa (4), beta (4), gama (2)" in r01["texto"] and r01["analise_tipo"] == "resumo"

    r02 = por_regra(todos, "R02")[0]
    assert " de 11 documentos têm pendências" in r02["texto"] and "1 fora das análises (curto)" in r02["texto"]
    assert r02["evidencias"][0]["documento"] == "curto" and r02["evidencias"][0]["pagina"] is None

    r03 = por_regra(todos, "R03")
    assert r03 and all("MATTR" in c["texto"] and c["chave"].startswith("R03|doc=d") for c in r03)

    r04 = por_regra(todos, "R04")
    top = client.get(f"/api/projetos/{proj8}/analises/frequencias", params={"limite": 5}).json()["itens"]
    assert [c["chave"].split("termo=")[1] for c in sorted(r04, key=lambda c: c["metricas"]["posicao"])] == [t["termo"] for t in top]
    assert "o 1º termo mais frequente do corpus" in sorted(r04, key=lambda c: c["metricas"]["posicao"])[0]["texto"]

    r05 = por_chave(por_regra(todos, "R05"))
    assert {"R05|termo=vexil", "R05|termo=plinth"} <= set(r05)  # vexil: 1 documento; plinth: 2 (gama)
    assert "só em 2 de 10 documentos" in r05["R05|termo=plinth"]["texto"]
    ev = r05["R05|termo=vexil"]["evidencias"][0]
    assert ev["pagina"] == 3 and "vexil" in ev["trecho"].lower() and ev["documento"].startswith("D03")
    assert "concentrado em D03 · Autor 2025 (100 %)" in r05["R05|termo=vexil"]["texto"]

    r06 = por_chave(por_regra(todos, "R06"))
    assert "R06|termo=trendword" in r06
    t = r06["R06|termo=trendword"]
    assert "em 2026" in t["texto"] and t["metricas"]["razao"] >= 2 and "2024 a 2025" in t["texto"]
    assert all("trendword" in e["trecho"] and e["documento"].split(" ")[0] in {"D06", "D07", "D08", "D09", "D10"} for e in t["evidencias"])

    r07 = por_chave(por_regra(todos, "R07"))
    z = r07["R07|grupo=alfa|termo=zorblax"]
    assert z["texto"].startswith("‘zorblax’ é ") and "mais frequente em alfa que nos demais documentos (G² = " in z["texto"]
    assert "p < 0,001" in z["texto"] and "presente em 4 de 4 documentos" in z["texto"] and "×" in z["texto"]
    assert z["metricas"]["g2"] > 0 and z["analise_tipo"] == "keyness"
    for e in z["evidencias"]:
        assert e["pagina"] == 2 and "zorblax" in e["trecho"].lower() and e["termo"][0].lower() == "zorblax"
    assert len({e["documento_id"] for e in z["evidencias"]}) == len(z["evidencias"]) == 3  # documentos distintos
    assert "R07|grupo=beta|termo=quokka" in r07 and "R07|grupo=gama|termo=plinth" in r07

    r08 = por_regra(todos, "R08")
    assert r08 and all(c["texto"].startswith("‘") and "menos frequente em" in c["texto"] for c in r08)

    r09 = por_chave(por_regra(todos, "R09"))
    col = r09["R09|termo=zorblax|colocado=engine"]
    assert "‘engine’ é colocado forte de ‘zorblax’" in col["texto"] and "janela de 5 palavras" in col["texto"]
    for e in col["evidencias"]:
        assert "zorblax engine" in e["trecho"].lower() and e["termo"] == ["zorblax", "engine"] and e["pagina"] == 2

    r10 = por_chave(por_regra(todos, "R10"))
    assert set(r10) == {"R10|grupo=alfa", "R10|grupo=beta", "R10|grupo=gama"}
    assert "O grupo ‘gama’ tem 2 documentos" in r10["R10|grupo=gama"]["texto"]

    assert "G² = " in z["texto"] and "." not in z["texto"].split("G² = ")[1].split(";")[0]


def test_limiares_e_ativa_controlam_o_disparo(client, proj8, monkeypatch, tmp_path):
    antes = listar(client, proj8)
    assert por_regra(antes, "R05") and por_regra(antes, "R06") and por_regra(antes, "R03")
    ajustar_catalogo(monkeypatch, tmp_path, {
        **AJUSTES_BASE,
        "R03": {"condicao": {"min_documentos": 3, "z_min": 99.0}},      # ninguém passa de |z| = 99
        "R05": {"condicao": {"min_freq": 1000}},                          # vexil tem 40
        "R06": {"condicao": {"razao_min": 1000.0}},
        "R07": {"max_comentarios": 20, "condicao": {"log_ratio_min": 50.0}},
        "R08": {"ativa": False},
        "R09": {"max_comentarios": 100, "condicao": {"n_termos": 25, "ll_min": 1e9}},
        "R10": {"condicao": {"docs_max": 1, "pct_tokens_max": 1.0}},
        "R02": {"condicao": {"min_documentos": 50}},
    })
    r = executar(client, proj8)
    assert r["erros"] == 0, r
    depois = por_chave(listar(client, proj8))
    vivos = {k for k, c in depois.items() if c["status"] != "obsoleto"}
    regras_vivas = {k.split("|")[0] for k in vivos}
    assert regras_vivas == {"R01", "R04"}, regras_vivas
    assert all(depois[k]["status"] == "obsoleto" for k in depois if k.split("|")[0] in {"R02", "R03", "R05", "R06", "R07", "R08", "R09", "R10"})


def test_r08_so_com_tres_ou_mais_grupos(client, proj8, monkeypatch, tmp_path):
    assert por_regra(listar(client, proj8), "R08")
    docs = {d["id_estudo"]: d["id"] for d in client.get(f"/api/projetos/{proj8}/documentos").json()}
    for ident in ("D09", "D10"):  # gama passa para beta: restam 2 grupos
        assert client.patch(f"/api/projetos/{proj8}/documentos/{docs[ident]}", json={"grupo": "beta"}).status_code == 200
    executar(client, proj8)
    r08 = por_regra(listar(client, proj8), "R08")
    assert r08 and all(c["status"] == "obsoleto" for c in r08)


def test_max_comentarios_por_regra_e_por_grupo(client, proj8, monkeypatch, tmp_path):
    ajustar_catalogo(monkeypatch, tmp_path, {**AJUSTES_BASE, "R04": {"max_comentarios": 2}, "R07": {"max_comentarios": 1}})
    executar(client, proj8)
    vivos = [c for c in listar(client, proj8) if c["status"] != "obsoleto"]
    assert len(por_regra(vivos, "R04")) == 2
    r07 = por_regra(vivos, "R07")
    assert sorted(c["chave"].split("|")[1] for c in r07) == ["grupo=alfa", "grupo=beta", "grupo=gama"]  # 1 por grupo
    forte = [c for c in listar(client, proj8, regra="R07") if c["chave"].startswith("R07|grupo=alfa")]
    maior = max(forte, key=lambda c: c["forca"])
    assert next(c for c in r07 if "grupo=alfa" in c["chave"])["chave"] == maior["chave"]  # o mais forte fica


def test_evidencias_zero_geram_comentario_sem_evidencia(client, proj8, monkeypatch, tmp_path):
    ajustar_catalogo(monkeypatch, tmp_path, {**AJUSTES_BASE, "R04": {"evidencias": 0}})
    executar(client, proj8)
    assert all(c["evidencias"] == [] for c in por_regra(listar(client, proj8), "R04"))


def test_editar_o_yaml_regenera_os_comentarios(client, proj8, monkeypatch, tmp_path):
    antes = por_regra(listar(client, proj8), "R04")[0]
    assert "é o" in antes["texto"]
    ajustar_catalogo(monkeypatch, tmp_path, {**AJUSTES_BASE, "R04": {"modelo": "Termo frequente: ‘{termo}’ ({freq} ocorrências)."}})
    r = executar(client, proj8)
    assert etapa_comentarios(r)["ok"] == 1 and etapa_comentarios(r)["pulado"] == 0
    depois = por_chave(listar(client, proj8))[antes["chave"]]
    assert depois["texto"].startswith("Termo frequente: ‘") and depois["status"] == "sugerido"
    r = executar(client, proj8)  # sem mudar nada, o cache pula a etapa
    assert etapa_comentarios(r)["pulado"] == 1


def test_catalogo_invalido_da_erro_na_etapa_com_mensagem(client, proj8, monkeypatch, tmp_path):
    ajustar_catalogo(monkeypatch, tmp_path, {"R04": {"modelo": "‘{termo}’ {nao_existe}"}})
    r = executar(client, proj8)
    comentarios = etapa_comentarios(r)
    assert comentarios["erro"] == 1 and "campos inexistentes" in comentarios["mensagens"][0] and "R04" in comentarios["mensagens"][0]
    assert listar(client, proj8)  # os comentários anteriores continuam intactos


def test_reconciliacao_no_pipeline_aceito_vira_revisar_ao_mudar_grupo(client, proj8):
    comentarios = por_chave(listar(client, proj8))
    chave = "R07|grupo=alfa|termo=zorblax"
    assert client.patch(f"/api/projetos/{proj8}/comentarios/{comentarios[chave]['id']}",
                        json={"acao": "aceitar", "revisor": "Ana"}).status_code == 200
    rejeitado = comentarios["R07|grupo=beta|termo=quokka"]["id"]
    assert client.patch(f"/api/projetos/{proj8}/comentarios/{rejeitado}", json={"acao": "rejeitar"}).status_code == 200
    editado = comentarios["R10|grupo=gama"]["id"]
    r = client.patch(f"/api/projetos/{proj8}/comentarios/{editado}", json={"acao": "editar", "texto": "Texto da Ana."})
    assert r.json()["status"] == "editado"
    executar(client, proj8)  # nada mudou: o cache pula e nada se altera
    assert por_chave(listar(client, proj8))[chave]["status"] == "aceito"

    docs = {d["id_estudo"]: d["id"] for d in client.get(f"/api/projetos/{proj8}/documentos").json()}
    assert client.patch(f"/api/projetos/{proj8}/documentos/{docs['D01']}", json={"grupo": "beta"}).status_code == 200  # alfa perde um doc
    assert client.patch(f"/api/projetos/{proj8}/documentos/{docs['D09']}", json={"grupo": "beta"}).status_code == 200  # gama perde um doc
    executar(client, proj8)
    depois = por_chave(listar(client, proj8))
    assert depois[chave]["status"] == "revisar" and "presente em 3 de 3 documentos" in depois[chave]["texto_original"]
    assert "presente em 4 de 4 documentos" in depois[chave]["texto"]  # o texto aceito foi preservado
    assert depois[chave]["motivo_revisao"]
    assert depois["R07|grupo=beta|termo=quokka"]["status"] == "rejeitado"
    assert depois["R10|grupo=gama"]["status"] in ("revisar", "editado") and depois["R10|grupo=gama"]["texto"] == "Texto da Ana."


# ---------- API de revisão ----------

def test_listagem_ordem_filtros_e_resumo(client, proj8):
    todos = listar(client, proj8)
    ordem = ["resumo", "frequencias", "tendencias", "keyness", "colocacoes"]
    pos = [ordem.index(c["analise_tipo"]) for c in todos]
    assert pos == sorted(pos)
    for tipo in ordem:  # dentro de cada análise, força decrescente
        forcas = [c["forca"] for c in todos if c["analise_tipo"] == tipo]
        assert forcas == sorted(forcas, reverse=True)
    assert {c["analise_tipo"] for c in listar(client, proj8, analise="keyness")} == {"keyness"}
    assert {c["regra"] for c in listar(client, proj8, regra="R04,R05")} == {"R04", "R05"}
    assert listar(client, proj8, status="aceito") == []
    assert client.get(f"/api/projetos/{proj8}/comentarios", params={"status": "xyz"}).status_code == 422

    resumo = client.get(f"/api/projetos/{proj8}/comentarios/resumo").json()
    assert resumo["total"] == len(todos) and resumo["por_status"]["sugerido"] == len(todos)
    assert set(resumo["por_status"]) == {"sugerido", "aceito", "editado", "rejeitado", "revisar", "obsoleto"}
    assert resumo["por_regra"]["R01"] == 1 and resumo["por_analise"]["keyness"] == len(listar(client, proj8, analise="keyness"))


def test_acoes_aceitar_editar_rejeitar_anotar_reabrir(client, proj8):
    c = por_regra(listar(client, proj8), "R04")[0]
    url = f"/api/projetos/{proj8}/comentarios/{c['id']}"
    r = client.patch(url, json={"acao": "aceitar", "revisor": "  Ana Souza "})
    assert r.status_code == 200 and r.json()["status"] == "aceito" and r.json()["revisor"] == "Ana Souza"
    assert r.json()["atualizado_em"] >= c["atualizado_em"]

    r = client.patch(url, json={"acao": "editar", "texto": "Texto do revisor.", "revisor": "Bia"})
    assert r.json()["status"] == "editado" and r.json()["texto"] == "Texto do revisor." and r.json()["revisor"] == "Bia"
    assert r.json()["texto_original"] == c["texto"]  # o gerado fica guardado
    assert client.patch(url, json={"acao": "editar", "texto": "  "}).status_code == 422
    assert client.patch(url, json={"acao": "editar"}).status_code == 422

    r = client.patch(url, json={"acao": "anotar", "nota": "Conferir com o orientador."})
    assert r.json()["nota"] == "Conferir com o orientador." and r.json()["status"] == "editado"
    assert client.patch(url, json={"acao": "anotar", "nota": ""}).json()["nota"] is None
    assert client.patch(url, json={"acao": "anotar"}).status_code == 422

    r = client.patch(url, json={"acao": "rejeitar"})
    assert r.json()["status"] == "rejeitado" and r.json()["revisor"] == "Bia"  # sem revisor novo, mantém o anterior

    r = client.patch(url, json={"acao": "reabrir"})
    assert r.json()["status"] == "sugerido" and r.json()["texto"] == c["texto"]  # volta ao texto gerado
    assert client.patch(url, json={"acao": "reabrir"}).status_code == 409

    assert client.patch(url, json={"acao": "apagar"}).status_code == 422
    assert client.patch(f"/api/projetos/{proj8}/comentarios/99999", json={"acao": "aceitar"}).status_code == 404

    banco = database.sessao_do_projeto(proj8)
    try:
        eventos = [h["evento"] for h in motor.ler_historico(banco.get(Comentario, c["id"]))]
    finally:
        banco.close()
    assert eventos == ["aceitar", "editar", "anotar", "anotar", "rejeitar", "reabrir"]


def test_editar_com_o_texto_gerado_vira_aceito_e_proposta_nova_em_revisar(client, proj8):
    c = por_regra(listar(client, proj8), "R04")[0]
    url = f"/api/projetos/{proj8}/comentarios/{c['id']}"
    assert client.patch(url, json={"acao": "editar", "texto": c["texto"]}).json()["status"] == "aceito"
    banco = database.sessao_do_projeto(proj8)
    try:
        obj = banco.get(Comentario, c["id"])
        obj.status, obj.texto_original = "revisar", "Texto novo do motor."
        banco.commit()
    finally:
        banco.close()
    r = client.patch(url, json={"acao": "aceitar", "usar_proposta": True})
    assert r.json()["status"] == "aceito" and r.json()["texto"] == "Texto novo do motor."


def test_lote_aceitar_rejeitar_e_ignorados(client, proj8):
    todos = listar(client, proj8)
    ids = [c["id"] for c in por_regra(todos, "R07")][:3]
    r = client.post(f"/api/projetos/{proj8}/comentarios/lote", json={"ids": ids, "acao": "aceitar", "revisor": "Caio"})
    assert r.status_code == 200 and r.json()["atualizados"] == 3 and r.json()["ignorados"] == []
    aceitos = listar(client, proj8, status="aceito")
    assert {c["id"] for c in aceitos} == set(ids) and {c["revisor"] for c in aceitos} == {"Caio"}

    r = client.post(f"/api/projetos/{proj8}/comentarios/lote", json={"ids": ids[:1] + [99999], "acao": "rejeitar"})
    assert r.json()["atualizados"] == 1 and r.json()["ignorados"] == [{"id": 99999, "motivo": "não encontrado"}]
    assert client.post(f"/api/projetos/{proj8}/comentarios/lote", json={"ids": [], "acao": "aceitar"}).status_code == 422
    assert client.post(f"/api/projetos/{proj8}/comentarios/lote", json={"ids": ids, "acao": "editar"}).status_code == 422
    resumo = client.get(f"/api/projetos/{proj8}/comentarios/resumo").json()["por_status"]
    assert resumo["aceito"] == 2 and resumo["rejeitado"] == 1


def test_obsoleto_so_aceita_anotar_e_rejeitar(client, proj8, monkeypatch, tmp_path):
    ajustar_catalogo(monkeypatch, tmp_path, {**AJUSTES_BASE, "R10": {"ativa": False}})
    executar(client, proj8)
    obsoletos = listar(client, proj8, status="obsoleto")
    assert obsoletos and {c["regra"] for c in obsoletos} == {"R10"}
    url = f"/api/projetos/{proj8}/comentarios/{obsoletos[0]['id']}"
    for acao in ("aceitar", "editar", "reabrir"):
        assert client.patch(url, json={"acao": acao, "texto": "x"}).status_code == 409
    assert client.patch(url, json={"acao": "anotar", "nota": "ok"}).status_code == 200
    r = client.post(f"/api/projetos/{proj8}/comentarios/lote", json={"ids": [obsoletos[1]["id"]], "acao": "aceitar"})
    assert r.json()["atualizados"] == 0 and len(r.json()["ignorados"]) == 1
    assert client.patch(url, json={"acao": "rejeitar"}).json()["status"] == "rejeitado"


def test_comentarios_de_projeto_inexistente_da_404(client):
    assert client.get("/api/projetos/nao-existe/comentarios").status_code == 404
    assert client.get("/api/projetos/nao-existe/comentarios/resumo").status_code == 404
