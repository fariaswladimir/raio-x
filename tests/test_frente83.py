"""8.3 Checagem de evidência: trecho existe no texto limpo atual (na página citada), números batem com as métricas atuais;
quem falha vai para "revisar" com o motivo, e o laudo não inclui. Corpus sintético da Frente 8."""
import json

import pytest

from app.database import pasta_do_projeto, sessao_do_projeto
from app.models import Comentario
from app.services.analises import dados
from tests.test_frente8 import corpus8, listar, proj8  # noqa: F401
from tests.test_frente9 import agir


def checar(client, slug):
    r = client.post(f"/api/projetos/{slug}/comentarios/checagem")
    assert r.status_code == 200, r.text
    return r.json()


def primeiro_com_trecho(client, slug, regra=None):
    for c in listar(client, slug, status="sugerido"):
        if c["evidencias"] and any(e["posicao"] is not None for e in c["evidencias"]) and (regra is None or c["regra"] == regra):
            return c
    raise AssertionError("sem comentário com evidência de texto")


def adulterar_texto_limpo(slug, documento_id, antigo, novo):
    arq = pasta_do_projeto(slug) / "cache" / "limpo" / f"{documento_id}.json"
    d = json.loads(arq.read_text(encoding="utf-8"))
    mudou = False
    for b in d["blocos"]:
        if antigo in b["texto"]:
            b["texto"] = b["texto"].replace(antigo, novo)
            mudou = True
    assert mudou, antigo
    arq.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    dados.limpar_caches()


def test_corpus_intacto_nao_reprova_ninguem(client, proj8):
    r = checar(client, proj8)
    assert r["verificados"] > 0 and r["falhas"] == []
    assert all(c["status"] == "sugerido" for c in listar(client, proj8))


def test_trecho_que_sumiu_do_texto_vai_para_revisar_e_fica_fora_do_laudo(client, proj8):
    c = primeiro_com_trecho(client, proj8)
    agir(client, proj8, c["id"], acao="aceitar", revisor="Ana")
    ev = next(e for e in c["evidencias"] if e["posicao"] is not None)
    trecho = ev["trecho"].split("…")[0].strip()
    palavra = ev["termo"][0] if ev["termo"] else trecho.split()[0]
    assert palavra in trecho
    adulterar_texto_limpo(proj8, ev["documento_id"], palavra, palavra + "QQ")
    r = checar(client, proj8)
    falha = next(f for f in r["falhas"] if f["id"] == c["id"])
    assert falha["status_antes"] == "aceito" and falha["status_depois"] == "revisar"
    assert "trecho não encontrado" in " ".join(falha["motivos"])
    depois = next(x for x in listar(client, proj8) if x["id"] == c["id"])
    assert depois["status"] == "revisar" and "Checagem de evidência" in depois["motivo_revisao"]
    # o laudo não inclui e informa
    g = client.post(f"/api/projetos/{proj8}/laudo").json()
    assert any(f["id"] == c["id"] for f in g["checagem"]["falhas"])
    html = client.get(f"/api/projetos/{proj8}/laudo").text
    assert f'id="c-{c["id"]}"' not in html and "reprovado" in html


def test_trecho_em_outra_pagina_reprova(client, proj8):
    c = next(x for x in listar(client, proj8, status="sugerido")
             if any(e["pagina"] is not None and e["posicao"] is not None for e in x["evidencias"]))
    ev = next(e for e in c["evidencias"] if e["pagina"] is not None and e["posicao"] is not None)
    banco = sessao_do_projeto(proj8)
    try:
        from app.models import Evidencia
        banco.get(Evidencia, ev["id"]).pagina = 99
        banco.commit()
    finally:
        banco.close()
    r = checar(client, proj8)
    f = next(f for f in r["falhas"] if f["id"] == c["id"])
    assert "página 99" in " ".join(f["motivos"]) or "não na p. 99" in " ".join(f["motivos"])


def test_numero_errado_em_comentario_editado_reprova(client, proj8):
    c = primeiro_com_trecho(client, proj8, "R04") if any(x["regra"] == "R04" for x in listar(client, proj8)) else primeiro_com_trecho(client, proj8)
    agir(client, proj8, c["id"], acao="editar", texto="O corpus tem 123456789 palavras no total.", revisor="Beto")
    r = checar(client, proj8)
    f = next(f for f in r["falhas"] if f["id"] == c["id"])
    assert "123456789" in " ".join(f["motivos"])
    assert next(x for x in listar(client, proj8) if x["id"] == c["id"])["status"] == "revisar"


def test_metricas_gravadas_desatualizadas_reprovam_comentario_aceito(client, proj8):
    c = primeiro_com_trecho(client, proj8)
    agir(client, proj8, c["id"], acao="aceitar", revisor="Ana")
    banco = sessao_do_projeto(proj8)
    try:
        cm = banco.get(Comentario, c["id"])
        m = json.loads(cm.metricas_json)
        k = next(k for k, v in m.items() if isinstance(v, (int, float)) and not isinstance(v, bool))
        m[k] = m[k] + 7
        cm.metricas_json = json.dumps(m)
        banco.commit()
    finally:
        banco.close()
    f = next(f for f in checar(client, proj8)["falhas"] if f["id"] == c["id"])
    assert "métricas gravadas diferem" in " ".join(f["motivos"]) and k in " ".join(f["motivos"])


def test_comentario_llm_com_numero_inventado_reprova_e_com_numero_certo_passa(client, proj8):
    banco = sessao_do_projeto(proj8)
    try:
        cm = Comentario(regra="LLM:teste", texto="O corpus tem 987654 documentos.", status="aceito", origem="llm",
                        analise_tipo="resumo", chave="llm|resumo|x|1", metricas_json=json.dumps({"origem": "llm"}))
        banco.add(cm)
        banco.commit()
        cid = cm.id
    finally:
        banco.close()
    f = next(f for f in checar(client, proj8)["falhas"] if f["id"] == cid)
    assert f["origem"] == "llm" and "987654" in " ".join(f["motivos"])


def test_rejeitado_e_obsoleto_nao_sao_checados(client, proj8):
    c = primeiro_com_trecho(client, proj8)
    agir(client, proj8, c["id"], acao="rejeitar", revisor="Ana")
    ev = next(e for e in c["evidencias"] if e["posicao"] is not None)
    palavra = ev["termo"][0] if ev["termo"] else ev["trecho"].split()[0]
    adulterar_texto_limpo(proj8, ev["documento_id"], palavra, palavra + "QQ")
    r = checar(client, proj8)
    assert all(f["id"] != c["id"] for f in r["falhas"])
    assert next(x for x in listar(client, proj8) if x["id"] == c["id"])["status"] == "rejeitado"


def test_motor_roda_a_checagem_com_as_metricas_recem_calculadas(client, proj8):
    from app.services import parametros as svc_parametros
    from app.services.regras import catalogo, motor

    pasta = pasta_do_projeto(proj8)
    banco = sessao_do_projeto(proj8)
    try:
        r = motor.comentar(banco, pasta, svc_parametros.carregar(pasta), catalogo.carregar_catalogo())
    finally:
        banco.close()
    assert r["checagem"]["verificados"] > 0 and r["checagem"]["falhas"] == 0
