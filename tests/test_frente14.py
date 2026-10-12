"""Frente 14 - LLM opcional: configuração e segredos (14.1), modelos de parágrafo (14.2), geração com verificação (14.3).

Sem chamadas de rede: provedores simulados, ``anthropic.Anthropic`` e ``httpx.Client`` trocados, ``keyring`` falso.
"""
import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import anthropic
import httpx
import httpx2
import pytest

from app.services import paragrafos
from app.services.llm import config, gerador, prompts, provedores
from app.services.llm.provedores import ErroLLM, ProvedorAnthropic, ProvedorOllama, ProvedorOpenAICompativel, provedor_configurado
from scripts import empacotar
from tests.test_frente8 import corpus8, executar, proj8  # noqa: F401  (fixtures do corpus sintético com grupos e anos)

SEGREDO = "sk-ant-api03-SEGREDOMUITOSECRETO1234"


class KeyringFalso:
    def __init__(self):
        self.cofre: dict[tuple[str, str], str] = {}

    def get_password(self, servico, usuario):
        return self.cofre.get((servico, usuario))

    def set_password(self, servico, usuario, senha):
        self.cofre[(servico, usuario)] = senha

    def delete_password(self, servico, usuario):
        if (servico, usuario) not in self.cofre:
            raise RuntimeError("não há senha")
        del self.cofre[(servico, usuario)]


@pytest.fixture(autouse=True)
def cofre(tmp_path, monkeypatch):
    """Configuração em pasta temporária (nunca em %APPDATA%) e cofre falso."""
    monkeypatch.setenv("RAIOX_CONFIG_DIR", str(tmp_path / "cfg"))
    kr = KeyringFalso()
    monkeypatch.setattr(config, "_keyring", lambda: kr)
    return kr


def salvar_config(client, **corpo):
    r = client.put("/api/config/llm", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 14.1 configuração e segredo ----------

def test_padrao_e_desligado_sem_provedor(client):
    cfg = client.get("/api/config/llm").json()
    assert cfg["habilitado"] is False and cfg["provedor"] == "nenhum"
    assert cfg["anthropic"]["modelo"] == "claude-opus-5-5" and cfg["anthropic"]["esforco"] == "medium"
    assert cfg["ollama"]["base_url"] == "http://127.0.0.1:11434"
    assert cfg["chaves"] == {"anthropic": None, "openai_compativel": None}
    assert cfg["modelos_anthropic"] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


def test_salvar_config_e_chave_mascarada(client, cofre):
    cfg = salvar_config(client, habilitado=True, provedor="anthropic", chaves={"anthropic": SEGREDO},
                        anthropic={"modelo": "claude-sonnet-5-5"})
    assert cfg["habilitado"] is True and cfg["provedor"] == "anthropic" and cfg["anthropic"]["modelo"] == "claude-sonnet-5-5"
    assert cfg["chaves"]["anthropic"] == "••••1234"
    assert SEGREDO not in json.dumps(cfg) and SEGREDO not in client.get("/api/config/llm").text
    assert cofre.cofre[("RaioX", "anthropic")] == SEGREDO
    assert cfg["armazenamento_chave"] == "keyring"
    # a chave não vai para o arquivo de configuração
    assert SEGREDO not in (config.pasta_config() / "config_llm.json").read_text(encoding="utf-8")
    assert not (config.pasta_config() / "segredos.json").exists()


def test_chave_vazia_mantem_a_guardada_e_remover_apaga(client, cofre):
    salvar_config(client, chaves={"anthropic": SEGREDO})
    cfg = salvar_config(client, provedor="anthropic", chaves={"anthropic": ""})
    assert cofre.cofre[("RaioX", "anthropic")] == SEGREDO and cfg["chaves"]["anthropic"] == "••••1234"
    cfg = salvar_config(client, remover_chaves=["anthropic"])
    assert cfg["chaves"]["anthropic"] is None and ("RaioX", "anthropic") not in cofre.cofre


@pytest.mark.parametrize("corpo", [{"provedor": "gpt"}, {"anthropic": {"modelo": "claude-opus-5-5-20260101"}},
                                   {"anthropic": {"esforco": "enorme"}}, {"ollama": {"base_url": "ftp://x"}}])
def test_config_invalida_422(client, corpo):
    assert client.put("/api/config/llm", json=corpo).status_code == 422


def test_sem_keyring_usa_arquivo_fora_do_projeto_com_aviso(client, monkeypatch, projetos_dir):
    monkeypatch.setattr(config, "_keyring", lambda: None)
    cfg = salvar_config(client, chaves={"openai_compativel": SEGREDO})
    assert cfg["armazenamento_chave"] == "arquivo" and cfg["chaves"]["openai_compativel"] == "••••1234"
    arquivo = config.pasta_config() / "segredos.json"
    assert json.loads(arquivo.read_text(encoding="utf-8")) == {"openai_compativel": SEGREDO}
    assert projetos_dir not in arquivo.parents and config.ler_chave("openai_compativel") == SEGREDO


def test_selecao_de_provedor(client):
    assert isinstance(provedor_configurado(config.salvar({"provedor": "ollama", "ollama": {"modelo": "m"}})), ProvedorOllama)
    assert isinstance(provedor_configurado(config.salvar({"provedor": "anthropic"})), ProvedorAnthropic)
    assert isinstance(provedor_configurado(config.salvar({"provedor": "openai_compativel"})), ProvedorOpenAICompativel)
    with pytest.raises(ErroLLM):
        provedor_configurado(config.salvar({"provedor": "nenhum"}))


def test_empacotar_nunca_leva_configuracao_nem_segredos(client, tmp_path):
    for nome in ("config_llm.json", "segredos.json", "llm_log.jsonl"):
        assert empacotar._arquivo_excluido(nome)
    salvar_config(client, provedor="anthropic", chaves={"anthropic": SEGREDO})
    nomes = [n for _c, n in empacotar.coletar_arquivos()]
    assert not any(n.endswith(("config_llm.json", "segredos.json", "llm_log.jsonl")) for n in nomes)
    assert not any(str(config.pasta_config()) in str(c) for c, _n in empacotar.coletar_arquivos())
    # uma cópia fora de lugar dentro do zip também seria barrada pela conferência final
    zip_ruim = tmp_path / "ruim.zip"
    with zipfile.ZipFile(zip_ruim, "w") as zf:
        zf.writestr("app/segredos.json", "{}")
    with pytest.raises(RuntimeError):
        empacotar.verificar_zip(zip_ruim)


# ---------- provedor Anthropic (SDK oficial, mock) ----------

class ClienteFalso:
    instancias: list = []

    def __init__(self, **kw):
        self.init = kw
        self.chamadas: list[tuple[str, dict]] = []
        self.resposta = ClienteFalso.resposta
        self.erro = ClienteFalso.erro
        ClienteFalso.instancias.append(self)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: self._criar("beta", k)))
        self.messages = SimpleNamespace(create=lambda **k: self._criar("messages", k))

    def _criar(self, via, kw):
        self.chamadas.append((via, kw))
        if self.erro:
            raise self.erro
        return self.resposta

    resposta = None
    erro = None


def resposta_anthropic(texto="Parágrafo.", stop="end_turn", categoria=None, modelo="claude-opus-5-5"):
    return SimpleNamespace(
        stop_reason=stop, model=modelo, _request_id="req_123", usage=SimpleNamespace(input_tokens=321, output_tokens=45),
        stop_details=SimpleNamespace(category=categoria) if stop == "refusal" else None,
        content=[SimpleNamespace(type="thinking", thinking="…"), SimpleNamespace(type="text", text=texto)])


@pytest.fixture()
def sdk(monkeypatch):
    ClienteFalso.instancias = []
    ClienteFalso.erro = None
    ClienteFalso.resposta = resposta_anthropic()
    monkeypatch.setattr(anthropic, "Anthropic", ClienteFalso)
    return ClienteFalso


PROIBIDOS = {"temperature", "top_p", "top_k", "thinking", "budget_tokens"}


@pytest.mark.parametrize("modelo", ["claude-opus-5-5", "claude-sonnet-5-5"])
def test_anthropic_opus_e_sonnet_usam_beta_com_fallback(sdk, modelo):
    sdk.resposta = resposta_anthropic("Texto gerado.", modelo=modelo)
    r = ProvedorAnthropic(SEGREDO, modelo, "medium").gerar("SISTEMA", "USUARIO")
    cli = sdk.instancias[0]
    assert cli.init["api_key"] == SEGREDO
    via, kw = cli.chamadas[0]
    assert via == "beta"
    assert kw["model"] == modelo and kw["max_tokens"] == 16000
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["system"] == "SISTEMA" and kw["messages"] == [{"role": "user", "content": "USUARIO"}]
    assert not PROIBIDOS & set(kw)
    assert r["texto"] == "Texto gerado." and r["uso"] == {"input_tokens": 321, "output_tokens": 45, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0} and r["request_id"] == "req_123"


def test_anthropic_haiku_usa_messages_sem_beta_nem_fallback(sdk):
    sdk.resposta = resposta_anthropic("Ok.", modelo="claude-haiku-5-5")
    ProvedorAnthropic(SEGREDO, "claude-haiku-5-5").gerar("S", "U")
    via, kw = sdk.instancias[0].chamadas[0]
    assert via == "messages" and kw["model"] == "claude-haiku-5-5" and kw["max_tokens"] == 16000
    assert not ({"betas", "fallbacks"} | PROIBIDOS) & set(kw)


def test_anthropic_modelo_fora_da_lista_e_recusado():
    with pytest.raises(ErroLLM):
        ProvedorAnthropic(SEGREDO, "claude-opus-5-5-20260101")


def _resp_http(status, **cab):
    return httpx2.Response(status, headers=cab, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


@pytest.mark.parametrize("erro, categoria, trecho", [
    (anthropic.AuthenticationError("x", response=_resp_http(401), body=None), "chave", "Chave de API inválida"),
    (anthropic.PermissionDeniedError("x", response=_resp_http(403), body=None), "permissao", "permissão"),
    (anthropic.NotFoundError("x", response=_resp_http(404), body=None), "modelo", "não encontrado"),
    (anthropic.RateLimitError("x", response=_resp_http(429, **{"retry-after": "42"}), body=None), "limite", "42 s"),
    (anthropic.InternalServerError("x", response=_resp_http(503), body=None), "servidor", "tente mais tarde"),
    (anthropic.APIStatusError("ruim " + SEGREDO, response=_resp_http(400), body=None), "erro", "recusou o pedido"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "conexao", "Sem rede"),
])
def test_anthropic_mapeia_cada_excecao_para_mensagem_amigavel(sdk, erro, categoria, trecho):
    sdk.erro = erro
    with pytest.raises(ErroLLM) as e:
        ProvedorAnthropic(SEGREDO, "claude-opus-5-5").gerar("S", "U")
    assert e.value.categoria == categoria and trecho in str(e.value)
    assert SEGREDO not in str(e.value)


def test_anthropic_recusa_e_truncamento(sdk):
    sdk.resposta = resposta_anthropic(stop="refusal", categoria="cyber")
    with pytest.raises(ErroLLM) as e:
        ProvedorAnthropic(SEGREDO).gerar("S", "U")
    assert e.value.categoria == "recusa" and "recusou" in str(e.value) and "cyber" in str(e.value)
    sdk.resposta = resposta_anthropic("corta", stop="max_tokens")
    with pytest.raises(ErroLLM) as e:
        ProvedorAnthropic(SEGREDO).gerar("S", "U")
    assert e.value.categoria == "truncada" and "truncada" in str(e.value)


def test_anthropic_sem_chave():
    with pytest.raises(ErroLLM) as e:
        ProvedorAnthropic(None).gerar("S", "U")
    assert e.value.categoria == "chave"


# ---------- Ollama e compatível com OpenAI (httpx simulado) ----------

CLIENTE_REAL = httpx.Client


def transporte(monkeypatch, tratador):
    real = CLIENTE_REAL
    monkeypatch.setattr(provedores.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(tratador), **kw))


def test_ollama_lista_modelos_e_conversa_sem_stream(monkeypatch):
    vistos = []

    def tratador(req: httpx.Request):
        vistos.append((req.method, str(req.url), json.loads(req.content) if req.content else None))
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.1:8b"}]})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": " Texto local. "}, "prompt_eval_count": 12, "eval_count": 7})

    transporte(monkeypatch, tratador)
    p = ProvedorOllama("http://127.0.0.1:11434/", "llama3.1:8b")
    assert p.listar_modelos() == ["llama3.1:8b", "qwen2.5:7b"]
    r = p.gerar("SIS", "USR")
    assert r["texto"] == "Texto local." and r["modelo"] == "llama3.1:8b" and r["uso"] == {"input_tokens": 12, "output_tokens": 7}
    assert vistos[0][:2] == ("GET", "http://127.0.0.1:11434/api/tags")
    metodo, url, corpo = vistos[1]
    assert (metodo, url) == ("POST", "http://127.0.0.1:11434/api/chat")
    assert corpo["stream"] is False and corpo["model"] == "llama3.1:8b"
    assert corpo["messages"] == [{"role": "system", "content": "SIS"}, {"role": "user", "content": "USR"}]


def test_ollama_fora_do_ar_e_modelo_ausente(monkeypatch):
    def fora(req):
        raise httpx.ConnectError("recusou", request=req)

    transporte(monkeypatch, fora)
    with pytest.raises(ErroLLM) as e:
        ProvedorOllama("http://127.0.0.1:1", "m").gerar("S", "U")
    assert e.value.categoria == "conexao" and "rodando" in str(e.value)
    transporte(monkeypatch, lambda req: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(ErroLLM) as e:
        ProvedorOllama("http://127.0.0.1:11434", "inexistente").gerar("S", "U")
    assert e.value.categoria == "modelo"


def test_openai_compativel_monta_o_pedido(monkeypatch):
    vistos = []

    def tratador(req: httpx.Request):
        vistos.append((str(req.url), req.headers.get("authorization"), json.loads(req.content)))
        return httpx.Response(200, json={"id": "gen-1", "model": "x/free", "choices": [{"message": {"content": "Texto."}}],
                                         "usage": {"prompt_tokens": 9, "completion_tokens": 3}})

    transporte(monkeypatch, tratador)
    r = ProvedorOpenAICompativel("https://openrouter.ai/api/v1/", "x/free", SEGREDO).gerar("SIS", "USR")
    url, auth, corpo = vistos[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions" and auth == f"Bearer {SEGREDO}"
    assert corpo["model"] == "x/free" and corpo["messages"][0] == {"role": "system", "content": "SIS"}
    assert r["texto"] == "Texto." and r["request_id"] == "gen-1" and r["uso"] == {"input_tokens": 9, "output_tokens": 3}


@pytest.mark.parametrize("status, categoria", [(401, "chave"), (404, "modelo"), (429, "limite"), (503, "servidor")])
def test_openai_compativel_erros_amigaveis(monkeypatch, status, categoria):
    transporte(monkeypatch, lambda req: httpx.Response(status, json={"error": "ruim " + SEGREDO}))
    with pytest.raises(ErroLLM) as e:
        ProvedorOpenAICompativel("https://x/v1", "m", SEGREDO).gerar("S", "U")
    assert e.value.categoria == categoria and SEGREDO not in str(e.value)


def test_testar_conexao_ollama_devolve_modelos_e_latencia(client, monkeypatch):
    def tratador(req):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
        return httpx.Response(200, json={"message": {"content": "ok"}})

    transporte(monkeypatch, tratador)
    assert client.post("/api/config/llm/testar").status_code == 409  # provedor "nenhum"
    salvar_config(client, provedor="ollama", ollama={"modelo": "llama3.1:8b"})
    r = client.post("/api/config/llm/testar").json()
    assert r["ok"] is True and r["modelos"] == ["llama3.1:8b"] and r["latencia_ms"] >= 0


def test_testar_conexao_erro_nao_vaza_a_chave(client, sdk):
    sdk.erro = anthropic.AuthenticationError("ruim " + SEGREDO, response=_resp_http(401), body=None)
    salvar_config(client, provedor="anthropic", chaves={"anthropic": SEGREDO})
    r = client.post("/api/config/llm/testar")
    assert r.status_code == 200 and r.json()["ok"] is False and "inválida" in r.json()["mensagem"] and SEGREDO not in r.text


# ---------- 14.2 modelos de parágrafo ----------

def test_modelos_padrao_cobrem_as_analises_com_ao_menos_dois_validos():
    modelos = paragrafos.modelos_padrao()
    for analise in paragrafos.ANALISES_PARAGRAFO:
        mm = [m for m in modelos if m["analise"] == analise]
        assert len(mm) >= 2, analise
        assert all(m["titulo"] and m["estilo"] and m["notas"] for m in mm)
        assert all(paragrafos.campos_do_texto(m["texto_modelo"]) <= set(paragrafos.PLACEHOLDERS[analise]) for m in mm)
    assert len({m["id"] for m in modelos}) == len(modelos)


def test_modelos_lista_sobrescrita_e_restaura_sem_tocar_nos_padroes(client, proj8):
    slug = proj8
    padrao_hash = hashlib.sha256(paragrafos.caminho_padrao().read_bytes()).hexdigest()
    r = client.get(f"/api/projetos/{slug}/modelos-paragrafo").json()
    base = next(m for m in r["modelos"] if m["id"] == "resumo-descritivo")
    assert base["origem"] == "padrao" and r["llm_habilitado"] is False and "tokens" in r["campos"]["resumo"]
    editado = {k: base[k] for k in ("id", "analise", "titulo", "estilo", "idioma", "texto_modelo", "notas")}
    editado["texto_modelo"] = "O corpus tem {n_documentos} documentos."
    duplicata = {**editado, "id": "meu-resumo", "titulo": "Meu resumo"}
    r = client.put(f"/api/projetos/{slug}/modelos-paragrafo", json={"modelos": [editado, duplicata]})
    assert r.status_code == 200, r.text
    por_id = {m["id"]: m for m in r.json()["modelos"]}
    assert por_id["resumo-descritivo"]["origem"] == "padrao_editado" and por_id["resumo-descritivo"]["texto_modelo"] == editado["texto_modelo"]
    assert por_id["meu-resumo"]["origem"] == "projeto"
    assert hashlib.sha256(paragrafos.caminho_padrao().read_bytes()).hexdigest() == padrao_hash  # padrão intacto
    # restaurar: lista vazia volta aos padrões
    r = client.put(f"/api/projetos/{slug}/modelos-paragrafo", json={"modelos": []}).json()
    assert {m["id"]: m["origem"] for m in r["modelos"]}["resumo-descritivo"] == "padrao"
    assert "meu-resumo" not in {m["id"] for m in r["modelos"]}


@pytest.mark.parametrize("mudanca, trecho", [
    ({"id": "Id Ruim"}, "Id inválido"), ({"analise": "nada"}, "inválida"), ({"texto_modelo": "  "}, "vazio"),
    ({"texto_modelo": "usa {campo_inexistente}"}, "campos desconhecidos"), ({"texto_modelo": "chave {aberta"}, "mal formadas"),
])
def test_modelo_invalido_422(client, proj8, mudanca, trecho):
    ok = {"id": "novo", "analise": "resumo", "titulo": "t", "estilo": "descritivo", "texto_modelo": "{n_documentos}"}
    r = client.put(f"/api/projetos/{proj8}/modelos-paragrafo", json={"modelos": [{**ok, **mudanca}]})
    assert r.status_code == 422 and trecho in r.json()["detail"]


def test_previa_deterministica_sem_llm_com_dados_do_projeto(client, proj8):
    slug = proj8
    url = f"/api/projetos/{slug}/modelos-paragrafo"
    a = client.post(f"{url}/resumo-descritivo/previa")
    assert a.status_code == 200, a.text
    j = a.json()
    assert j["llm"] is False and "10" in j["texto"] and "documentos" in j["texto"]
    assert j["metricas_usadas"]["n_documentos"] == 10
    assert client.post(f"{url}/resumo-descritivo/previa").json()["texto"] == j["texto"]
    assert client.post(f"{url}/inexistente/previa").status_code == 404
    # nenhuma chamada ao provedor: a configuração está desligada e a prévia funciona
    assert client.get("/api/config/llm").json()["habilitado"] is False


def test_previas_de_todas_as_analises_disponiveis(client, proj8):
    url = f"/api/projetos/{proj8}/modelos-paragrafo"
    sem_dados = {"dicionario"}  # corpus sintético sem categorias no dicionário
    for m in client.get(url).json()["modelos"]:
        r = client.post(f"{url}/{m['id']}/previa")
        if m["analise"] in sem_dados:
            assert r.status_code == 409 and "icionário" in r.json()["detail"], m["id"]
            continue
        assert r.status_code == 200, (m["id"], r.text)
        texto = r.json()["texto"]
        assert texto and "{" not in texto, m["id"]


# ---------- verificar() ----------

EVID = [{"documento_id": 1, "rotulo": "001 — Kim 2026", "pagina": 7, "trecho": "the agent runs the model\n  with human oversight", "termo": "agent", "posicao": 3},
        {"documento_id": 2, "rotulo": "002 — Silva 2025", "pagina": 12, "trecho": "outro trecho qualquer", "termo": "x", "posicao": 9}]
MET = {"n_documentos": 51, "tokens": 439771, "densidade": 0.036, "mattr": 0.5212, "por_10k": 115.78, "p_texto": "p < 0,001",
       "top": [{"termo": "ai", "freq": 4943}], "ano": 2026}


def v(texto, met=MET, ev=EVID):
    return gerador.verificar(texto, met, ev)


def test_verificar_numeros_pt_br_e_en():
    assert v("Há 51 documentos e 439.771 palavras; MATTR 0,521 e 115,78 por 10 mil palavras.")["ok"]
    assert v("There are 439,771 words and 115.78 per 10k.")["ok"]  # formatação inglesa
    assert v("O termo ocorreu 4.943 vezes em 2026.")["ok"]


def test_verificar_tolerancia_de_arredondamento_e_porcentagem():
    assert v("O MATTR foi 0,52 (0,5212 exato).")["ok"]  # arredondado às casas mostradas
    assert v("A densidade foi de 3,6%.")["ok"]  # fração 0,036 mostrada como porcentagem
    assert v("Cerca de 116 por 10 mil.")["ok"]  # 115,78 arredondado para inteiro
    r = v("A média foi 0,6.")
    assert not r["ok"] and r["numeros_nao_encontrados"] == ["0,6"]


def test_verificar_numero_inventado_e_isentos():
    r = v("Foram 52 documentos e 8.000 palavras.")
    assert r["numeros_nao_encontrados"] == ["52", "8.000"] and not r["ok"]
    assert v("O eixo 1 e o grupo 2 em 10 mil palavras (p < 0,001).")["ok"]  # rótulos e limiar de p
    assert not v("p < 0,0001 e 51.")["ok"]


def test_verificar_citacoes():
    assert v("Como visto (001 — Kim 2026, p. 7) e (002 — Silva 2025, p. 12).")["ok"]
    assert v("Duas fontes (001 — Kim 2026, p. 7; 002 — Silva 2025, p. 12).")["ok"]
    r = v("Veja (001 — Kim 2026, p. 8) e (Fulano 2020, p. 3).")
    assert r["citacoes_invalidas"] == ["(001 — Kim 2026, p. 8)", "(Fulano 2020, p. 3)"] and not r["ok"]
    # as páginas das citações não contam como números a conferir
    assert v("Cf. (001 — Kim 2026, p. 7).")["numeros_nao_encontrados"] == []


def test_verificar_trechos_entre_aspas():
    assert v('Os autores dizem "the agent runs the model with human oversight" (001 — Kim 2026, p. 7).')["ok"]  # espaços normalizados
    assert v("O termo “ai” é o mais frequente.")["ok"]  # termo das métricas
    r = v('Segundo eles, "agents replace all humans" (001 — Kim 2026, p. 7).')
    assert r["trechos_nao_encontrados"] == ["agents replace all humans"] and not r["ok"]
    assert v('Trecho "the agent … human oversight" (001 — Kim 2026, p. 7).')["ok"]  # reticências entre fragmentos literais
    assert v('Dizem "the agent runs 99 models"')["trechos_nao_encontrados"]  # números dentro de aspas não bastam
    assert v('Dizem "outro trecho qualquer" (002 — Silva 2025, p. 12).')["numeros_nao_encontrados"] == []


def test_candidatos_do_numero_ambiguo():
    assert (1234.0, 0) in gerador.candidatos_do_numero("1.234") and (1.234, 3) in gerador.candidatos_do_numero("1.234")
    assert gerador.candidatos_do_numero("1.234,5") == [(1234.5, 1)] and gerador.candidatos_do_numero("1,234.5") == [(1234.5, 1)]
    assert gerador.candidatos_do_numero("1.234.567") == [(1234567.0, 0)]


def test_prompt_traz_modelo_notas_metricas_e_evidencias():
    modelo = {"analise": "resumo", "titulo": "T", "estilo": "descritivo", "idioma": "pt", "texto_modelo": "MODELO {x}", "notas": "NAO AFIRMAR"}
    u = prompts.montar_usuario(modelo, MET, EVID, "  seja breve ")
    for trecho in ("MODELO {x}", "NAO AFIRMAR", '"n_documentos":51', "001 — Kim 2026", "seja breve"):
        assert trecho in u
    assert "(rótulo, p. N)" in prompts.SYSTEM and "ONLY" not in prompts.SYSTEM and "SOMENTE" in prompts.SYSTEM


# ---------- 14.3 geração ----------

class ProvedorFalso:
    nome = "ollama"

    def __init__(self, texto=None, erro=None, modelo="llama3.1:8b"):
        self.texto, self.erro, self.modelo, self.chamadas = texto, erro, modelo, []

    def gerar(self, system, user):
        self.chamadas.append((system, user))
        if self.erro:
            raise self.erro
        return {"texto": self.texto if self.texto is not None else "Texto.", "modelo": self.modelo,
                "uso": {"input_tokens": 100, "output_tokens": 50}, "request_id": "req_x", "segundos": 1.5}


def ligar_llm(client, monkeypatch, prov):
    salvar_config(client, habilitado=True, provedor="ollama", ollama={"modelo": prov.modelo})
    monkeypatch.setattr(gerador, "provedor_configurado", lambda cfg=None: prov)


def gerar_llm(client, slug, modelo="frequencias-descritivo", **corpo):
    return client.post(f"/api/projetos/{slug}/modelos-paragrafo/{modelo}/gerar", json=corpo)


def comentarios_llm(client, slug):
    return [c for c in client.get(f"/api/projetos/{slug}/comentarios").json() if c["origem"] == "llm"]


def test_gerar_com_llm_desligado_devolve_409(client, proj8, monkeypatch):
    prov = ProvedorFalso("x")
    monkeypatch.setattr(gerador, "provedor_configurado", lambda cfg=None: prov)
    r = gerar_llm(client, proj8)
    assert r.status_code == 409 and "desligada" in r.json()["detail"] and prov.chamadas == []
    assert comentarios_llm(client, proj8) == []


def test_gerar_texto_conferido_entra_como_sugerido_origem_llm_e_grava_log(client, proj8, monkeypatch, projetos_dir):
    previa = client.post(f"/api/projetos/{proj8}/modelos-paragrafo/frequencias-descritivo/previa").json()
    ev = previa["evidencias"][0]
    texto = previa["texto"] + f" Veja ({ev['rotulo']}, p. {ev['pagina']})."
    prov = ProvedorFalso(texto)
    ligar_llm(client, monkeypatch, prov)
    r = gerar_llm(client, proj8, instrucoes="seja objetivo")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "sugerido" and j["verificacao"]["ok"] is True and j["modelo"] == "llama3.1:8b"
    assert "seja objetivo" in prov.chamadas[0][1] and prompts.SYSTEM == prov.chamadas[0][0]
    (c,) = comentarios_llm(client, proj8)
    assert c["status"] == "sugerido" and c["origem"] == "llm" and c["regra"] == "LLM:llama3.1:8b" and c["analise_tipo"] == "frequencias"
    assert c["chave"].startswith("llm|frequencias|frequencias-descritivo|") and c["texto"] == c["texto_original"] == texto
    assert c["llm"]["provedor"] == "ollama" and c["llm"]["modelo"] == "llama3.1:8b" and c["llm"]["request_id"] == "req_x"
    assert c["llm"]["uso"] == {"input_tokens": 100, "output_tokens": 50} and len(c["llm"]["prompt_hash"]) == 16
    assert c["verificacao"]["ok"] is True and 1 <= len(c["evidencias"]) <= 5
    log = (projetos_dir / proj8 / "saidas" / "llm_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    linha = json.loads(log[-1])
    assert linha["comentario_id"] == c["id"] and linha["status"] == "sugerido" and linha["modelo"] == "llama3.1:8b"
    assert linha["prompt_hash"] == c["llm"]["prompt_hash"] and "api_key" not in log[-1]
    # repetir com os mesmos dados atualiza o mesmo comentário (ainda sugerido) em vez de duplicar
    gerar_llm(client, proj8, instrucoes="seja objetivo")
    assert len(comentarios_llm(client, proj8)) == 1


def test_gerar_texto_com_numero_inventado_vai_para_revisar_com_motivos(client, proj8, monkeypatch):
    prov = ProvedorFalso('O corpus tem 99999 documentos (Fulano 2020, p. 3) e "frase que não existe".')
    ligar_llm(client, monkeypatch, prov)
    j = gerar_llm(client, proj8).json()
    assert j["status"] == "revisar"
    v_ = j["verificacao"]
    assert v_["numeros_nao_encontrados"] == ["99999"] and v_["citacoes_invalidas"] == ["(Fulano 2020, p. 3)"]
    assert v_["trechos_nao_encontrados"] == ["frase que não existe"]
    (c,) = comentarios_llm(client, proj8)
    assert c["status"] == "revisar" and "99999" in c["motivo_revisao"] and "Fulano" in c["motivo_revisao"]
    # nunca é aceito sozinho: fica fora do laudo até um humano aceitar
    assert client.post(f"/api/projetos/{proj8}/laudo").status_code == 200
    assert c["texto"] not in client.get(f"/api/projetos/{proj8}/laudo").text


def test_gerar_erro_do_provedor_502_registra_no_log_sem_segredo(client, proj8, monkeypatch, projetos_dir):
    prov = ProvedorFalso(erro=ErroLLM("Chave de API inválida.", "chave"))
    salvar_config(client, habilitado=True, provedor="anthropic", chaves={"anthropic": SEGREDO})
    monkeypatch.setattr(gerador, "provedor_configurado", lambda cfg=None: prov)
    r = gerar_llm(client, proj8)
    assert r.status_code == 502 and "inválida" in r.json()["detail"] and SEGREDO not in r.text
    assert comentarios_llm(client, proj8) == []
    log = (projetos_dir / proj8 / "saidas" / "llm_log.jsonl").read_text(encoding="utf-8")
    assert "Chave de API inválida." in log and SEGREDO not in log


def test_gerar_analise_sem_dados_409(client, proj8, monkeypatch):
    prov = ProvedorFalso("x")
    ligar_llm(client, monkeypatch, prov)
    r = gerar_llm(client, proj8, modelo="dicionario-descritivo")
    assert r.status_code == 409 and prov.chamadas == []


def test_segredo_nunca_aparece_no_projeto_nem_nas_exportacoes(client, proj8, monkeypatch, projetos_dir):
    prov = ProvedorFalso("Texto sem números.")
    salvar_config(client, habilitado=True, provedor="anthropic", chaves={"anthropic": SEGREDO})
    monkeypatch.setattr(gerador, "provedor_configurado", lambda cfg=None: prov)
    assert gerar_llm(client, proj8).status_code == 200
    cid = comentarios_llm(client, proj8)[0]["id"]
    client.patch(f"/api/projetos/{proj8}/comentarios/{cid}", json={"acao": "aceitar", "revisor": "Ana"})
    client.post(f"/api/projetos/{proj8}/laudo")
    pacote = client.post(f"/api/projetos/{proj8}/exportar/pacote.zip")
    assert pacote.status_code == 200
    with zipfile.ZipFile(io.BytesIO(pacote.content)) as zf:
        for nome in zf.namelist():
            assert SEGREDO.encode() not in zf.read(nome), nome
    for arquivo in projetos_dir.rglob("*"):
        if arquivo.is_file():
            assert SEGREDO.encode() not in arquivo.read_bytes(), arquivo
    for rota in (f"/api/projetos/{proj8}/comentarios", "/api/config/llm"):
        assert SEGREDO not in client.get(rota).text


def test_reexecutar_o_pipeline_nao_torna_o_comentario_llm_obsoleto(client, proj8, monkeypatch):
    ligar_llm(client, monkeypatch, ProvedorFalso("Texto sem números."))
    gerar_llm(client, proj8)
    antes = comentarios_llm(client, proj8)[0]
    executar(client, proj8)
    (depois,) = comentarios_llm(client, proj8)
    assert depois["id"] == antes["id"] and depois["status"] == "sugerido"


# ---------- laudo ----------

def aceitar_primeiro(client, slug, origem):
    lista = [c for c in client.get(f"/api/projetos/{slug}/comentarios").json() if c["origem"] == origem and c["status"] in ("sugerido", "revisar")]
    r = client.patch(f"/api/projetos/{slug}/comentarios/{lista[0]['id']}", json={"acao": "aceitar", "revisor": "Ana"})
    assert r.status_code == 200, r.text
    return r.json()


def laudo(client, slug):
    assert client.post(f"/api/projetos/{slug}/laudo").status_code == 200
    return client.get(f"/api/projetos/{slug}/laudo").text


def test_laudo_declara_sem_llm_enquanto_nao_ha_llm_aceito(client, proj8, monkeypatch):
    aceitar_primeiro(client, proj8, "regra")
    ligar_llm(client, monkeypatch, ProvedorFalso("Texto sem números."))
    gerar_llm(client, proj8)  # sugerido, ainda não aceito
    html = laudo(client, proj8)
    assert "Gerado sem LLM; comentários produzidos por regras e revisados por humano." in html
    assert "redigido com LLM" not in html and 'id="metodo-llm"' not in html


def test_laudo_muda_declaracao_e_marca_comentario_quando_llm_aceito(client, proj8, monkeypatch):
    aceitar_primeiro(client, proj8, "regra")
    ligar_llm(client, monkeypatch, ProvedorFalso("Texto sem números."))
    gerar_llm(client, proj8)
    c = aceitar_primeiro(client, proj8, "llm")
    html = laudo(client, proj8)
    assert "Gerado sem LLM" not in html
    assert "Comentários produzidos por regras e, quando indicado, redigidos com auxílio de LLM (ollama: llama3.1:8b), revisados por humano." in html
    assert html.count("redigido com LLM") == 1 and f'id="c-{c["id"]}"' in html
    assert 'id="metodo-llm"' in html and "conferência automática" in html and "revisão humana" in html
    # editar o texto aceito mantém a origem e a marca
    client.patch(f"/api/projetos/{proj8}/comentarios/{c['id']}", json={"acao": "editar", "texto": "Texto editado por mim."})
    html = laudo(client, proj8)
    assert "Texto editado por mim." in html and "redigido com LLM" in html
    # rejeitar o comentário LLM devolve o laudo à declaração sem LLM
    client.patch(f"/api/projetos/{proj8}/comentarios/{c['id']}", json={"acao": "rejeitar"})
    assert "Gerado sem LLM" in laudo(client, proj8)
