"""15.11 - Classificação zero-shot / few-shot por LLM nas categorias do dicionário (codebook) ou numa lista de rótulos.

- **Unidades:** ``trechos`` (a codificação humana importada em 15.1; permite comparar com os rótulos humanos),
  ``segmentos`` (segmentos de ~40 palavras do corpus, com documento e página) ou ``documentos`` (início do texto limpo).
- **Zero-shot:** só as definições dos rótulos. **Few-shot:** até ``k`` exemplos por rótulo, tirados dos trechos
  codificados por humanos, escolhidos de forma determinística (ordem por hash SHA-1 de "rótulo|id", sem sorteio).
  Os trechos usados como exemplo ficam de fora da avaliação (status ``exemplo``) para não haver vazamento.
- **Multirrótulo (opcional):** o modelo pode devolver mais de um rótulo; no rótulo único devolve exatamente um (ou ``nenhum``).
- **Saída:** rótulo(s) + justificativa + confiança (0 a 1); leitura tolerante, rótulo fora da lista = erro (sem adivinhar).
- **Cache de prompt (item 0):** instruções, rótulos e exemplos vão no ``system`` (prefixo estável, ordenado, com ponto de
  cache no último bloco); a unidade a classificar vai na mensagem do usuário.
- **Revisão:** cada item pode ser aceito ou rejeitado por uma pessoa; a concordância com o humano (15.1) pode ser
  calculada sobre todos os itens ou só sobre os aceitos/pendentes.
- Lote em segundo plano com progresso e cancelamento; log em ``saidas/llm_log.jsonl`` (como 14.3 e 15.1).
"""
import datetime
import hashlib
import json
import threading
import time
from pathlib import Path

from sqlalchemy import Float, Integer, String, Text, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, CodificacaoTrecho, agora
from app.services.analises import dados
from app.services.busca import corpus as busca_corpus
from app.services.concordancia import codificador
from app.services.concordancia.codificador import LLMDesligado, _confianca, _objetos_json
from app.services.llm import cache_prompt, config, precos
from app.services.llm.provedores import ErroLLM, provedor_configurado

NENHUM = codificador.NENHUM
VERSAO_PROMPT = "classificacao-v1"
ARQUIVO_CONFIG = "classificacao_config.json"
MAX_CHARS_DOCUMENTO = 3000
ORIGENS = ("trechos", "segmentos", "documentos")
MODOS = ("zero_shot", "few_shot")


class ClassificacaoItem(Base):
    """Resultado da classificação de uma unidade (a execução atual do projeto; uma nova execução substitui a anterior)."""

    __tablename__ = "classificacao_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    origem: Mapped[str] = mapped_column(String(12), index=True)  # trechos | segmentos | documentos
    ref: Mapped[str] = mapped_column(String(40), index=True)  # id do trecho, "doc:seg" ou id do documento
    documento_id: Mapped[int | None] = mapped_column(Integer, index=True)
    rotulo_doc: Mapped[str | None] = mapped_column(String(300))
    pagina: Mapped[int | None] = mapped_column(Integer)
    texto: Mapped[str] = mapped_column(Text)
    rotulos: Mapped[str | None] = mapped_column(Text)  # JSON: lista de rótulos atribuídos pelo LLM
    rotulo_humano: Mapped[str | None] = mapped_column(String(50))
    justificativa: Mapped[str | None] = mapped_column(Text)
    confianca: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="pendente", index=True)  # pendente | classificado | erro | exemplo
    revisao: Mapped[str] = mapped_column(String(12), default="pendente", index=True)  # pendente | aceito | rejeitado
    modelo: Mapped[str | None] = mapped_column(String(200))
    resposta_bruta: Mapped[str | None] = mapped_column(Text)
    atualizado_em: Mapped[datetime.datetime] = mapped_column(default=agora, onupdate=agora)


class ConfigInvalida(ValueError):
    pass


# ---------- configuração e rótulos ----------

def rotulos_do_dicionario(pasta: Path) -> list[dict]:
    return [{"id": c["id"], "nome": c.get("nome") or c["id"], "definicao": " ".join((c.get("descricao") or "").split())}
            for c in codificador.codebook(pasta)]


def interpretar_rotulos_texto(texto: str) -> list[dict]:
    """Uma linha por rótulo: ``rótulo: definição`` (a definição é opcional)."""
    saida, vistos = [], set()
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        nome, _, definicao = linha.partition(":")
        nome = nome.strip()
        if not nome or nome.lower() == NENHUM:
            continue
        if nome.lower() in vistos:
            raise ConfigInvalida(f"Rótulo repetido: {nome}.")
        vistos.add(nome.lower())
        saida.append({"id": nome, "nome": nome, "definicao": " ".join(definicao.split())})
    return saida


def normalizar_config(cfg: dict, pasta: Path) -> dict:
    """Valida e completa a configuração de uma execução (levanta ConfigInvalida)."""
    origem = cfg.get("origem") or "trechos"
    modo = cfg.get("modo") or "zero_shot"
    if origem not in ORIGENS:
        raise ConfigInvalida(f"Origem inválida. Use: {', '.join(ORIGENS)}.")
    if modo not in MODOS:
        raise ConfigInvalida(f"Modo inválido. Use: {', '.join(MODOS)}.")
    rotulos = cfg.get("rotulos")
    if isinstance(rotulos, str):
        rotulos = interpretar_rotulos_texto(rotulos)
    if not rotulos:
        rotulos = rotulos_do_dicionario(pasta)
    fonte_rotulos = "lista" if cfg.get("rotulos") else "dicionario"
    if not rotulos:
        raise ConfigInvalida("Sem rótulos: importe o codebook (dicionário do projeto) ou informe uma lista de rótulos.")
    k = int(cfg.get("k") or 3)
    if not 1 <= k <= 10:
        raise ConfigInvalida("k (exemplos por rótulo) deve estar entre 1 e 10.")
    limite = cfg.get("limite")
    if limite is not None and int(limite) < 1:
        raise ConfigInvalida("limite deve ser >= 1.")
    return {"origem": origem, "modo": modo, "rotulos": sorted(({"id": str(r["id"]), "nome": str(r.get("nome") or r["id"]),
                                                              "definicao": str(r.get("definicao") or "")} for r in rotulos),
                                                             key=lambda r: cache_prompt.chave_natural(r["id"])),
            "fonte_rotulos": fonte_rotulos, "k": k, "multirrotulo": bool(cfg.get("multirrotulo")),
            "limite": int(limite) if limite is not None else None, "documento_id": cfg.get("documento_id")}


# ---------- prompt ----------

def _instrucoes(multi: bool) -> str:
    saida = ("{\"rotulos\": [\"<rótulo>\", ...], \"justificativa\": \"<uma ou duas frases em português>\", \"confianca\": <0 a 1>}"
             if multi else
             "{\"rotulos\": [\"<um rótulo da lista ou nenhum>\"], \"justificativa\": \"<uma ou duas frases em português>\", \"confianca\": <0 a 1>}")
    regra = ("Escolha TODOS os rótulos que se aplicam (no mínimo um; use \"nenhum\" sozinho se nenhum se aplicar)." if multi else
             "Escolha exatamente UM rótulo, o que melhor se aplica, ou \"nenhum\" se nenhum se aplicar.")
    return ("Você classifica unidades de texto (trechos, segmentos ou documentos) nos rótulos de uma lista, seguindo a definição de "
            f"cada rótulo. {regra} Não invente rótulos. Responda SOMENTE com um objeto JSON, sem texto antes ou depois: {saida}")


def texto_rotulos(rotulos: list[dict]) -> str:
    return "\n".join(f"- {r['id']} | {r['nome']} | definição: {r['definicao'] or '-'}" for r in rotulos)


def escolher_exemplos(trechos: list, rotulos: list[dict], k: int) -> list:
    """Até ``k`` trechos humanos por rótulo, determinísticos: ordem por SHA-1 de "rótulo|id"; um trecho serve a um só rótulo."""
    ids_rotulos = {r["id"] for r in rotulos}
    por_rotulo: dict[str, list] = {r: [] for r in ids_rotulos}
    for t in trechos:
        if t.codigo_humano in ids_rotulos and len(t.texto.strip()) >= 20:
            por_rotulo[t.codigo_humano].append(t)
    escolhidos = []
    for r in sorted(por_rotulo, key=cache_prompt.chave_natural):
        cand = sorted(por_rotulo[r], key=lambda t: (hashlib.sha1(f"{r}|{t.id}".encode()).hexdigest(), t.id))
        escolhidos.extend(cand[:k])
    return escolhidos


def texto_exemplos(exemplos: list) -> str:
    return "\n\n".join(f"EXEMPLO (rótulo: {t.codigo_humano}):\n\"\"\"\n{' '.join(t.texto.split())[:600]}\n\"\"\"" for t in exemplos)


def montar_system(rotulos: list[dict], multi: bool, exemplos: list | None = None) -> list[dict]:
    partes = [_instrucoes(multi), "RÓTULOS (rótulo | nome | definição):\n" + texto_rotulos(rotulos)]
    if exemplos:
        partes.append("EXEMPLOS CLASSIFICADOS POR HUMANOS (use como referência, não os repita):\n\n" + texto_exemplos(exemplos))
    return cache_prompt.blocos_system(*partes)


def montar_usuario(texto: str) -> str:
    return 'UNIDADE A CLASSIFICAR:\n"""\n' + texto.strip() + '\n"""\n\nResponda só com o JSON pedido.'


# ---------- leitura da resposta ----------

def interpretar(resposta: str, ids: list[str], multi: bool) -> dict:
    """{rotulos: [...], justificativa, confianca, ok, erro}. Rótulo fora da lista = erro (sem adivinhar)."""
    validos = {i.lower(): i for i in ids}
    dados_json = None
    for bloco in _objetos_json(resposta or ""):
        for tentativa in (bloco, bloco.replace("'", '"')):
            try:
                d = json.loads(tentativa)
            except ValueError:
                continue
            if isinstance(d, dict):
                dados_json = {str(k).lower(): v for k, v in d.items()}
                break
        if dados_json is not None:
            break
    if dados_json is None:
        return {"rotulos": None, "justificativa": None, "confianca": None, "ok": False, "erro": "Resposta sem JSON reconhecível."}
    bruto = dados_json.get("rotulos", dados_json.get("rótulos", dados_json.get("rotulo", dados_json.get("rótulo", dados_json.get("labels")))))
    if isinstance(bruto, (str, int, float)):
        bruto = [bruto]
    just = str(dados_json.get("justificativa", dados_json.get("justification", "")) or "")[:2000]
    conf = _confianca(dados_json.get("confianca", dados_json.get("confiança", dados_json.get("confidence"))))
    if not isinstance(bruto, list) or not bruto:
        return {"rotulos": None, "justificativa": just, "confianca": conf, "ok": False, "erro": "Resposta sem o campo rotulos."}
    saida = []
    for b in bruto:
        s = str(b).strip().strip("\"'`").strip()
        if s.lower() in (NENHUM, "none", "n/a", "null", ""):
            cod = NENHUM
        elif s.lower() in validos:
            cod = validos[s.lower()]
        else:
            return {"rotulos": None, "justificativa": just, "confianca": conf, "ok": False, "erro": f"Rótulo fora da lista: {b!r}."}
        if cod not in saida:
            saida.append(cod)
    if len(saida) > 1 and NENHUM in saida:
        saida = [x for x in saida if x != NENHUM]
    if not multi and len(saida) > 1:
        return {"rotulos": None, "justificativa": just, "confianca": conf, "ok": False,
                "erro": "Mais de um rótulo no modo de rótulo único."}
    return {"rotulos": saida, "justificativa": just, "confianca": conf, "ok": True, "erro": None}


# ---------- unidades, estimativa, lote ----------

def _texto_do_documento(pasta: Path, doc_id: int) -> str:
    blocos = dados.carregar_blocos(pasta, doc_id) or []
    return " ".join(" ".join(b["texto"].split()) for b in blocos)[:MAX_CHARS_DOCUMENTO]


def _unidades(db, pasta: Path, cfg: dict, excluir_trechos: set[int]) -> list[dict]:
    """Unidades a classificar: [{origem, ref, documento_id, rotulo_doc, pagina, texto, rotulo_humano}] (ordem estável)."""
    saida = []
    if cfg["origem"] == "trechos":
        rot = {m["id"]: m["rotulo"] for m in dados.documentos_do_corpus(db, pasta)}
        for t in db.scalars(select(CodificacaoTrecho).order_by(CodificacaoTrecho.id)):
            saida.append({"origem": "trechos", "ref": str(t.id), "documento_id": t.documento_id, "rotulo_doc": rot.get(t.documento_id) or t.fonte_rotulo,
                          "pagina": t.pagina, "texto": t.texto, "rotulo_humano": t.codigo_humano,
                          "exemplo": t.id in excluir_trechos})
    elif cfg["origem"] == "segmentos":
        for s in busca_corpus.carregar_segmentos(db, pasta):
            if cfg.get("documento_id") and s["documento_id"] != int(cfg["documento_id"]):
                continue
            saida.append({"origem": "segmentos", "ref": s["id"], "documento_id": s["documento_id"], "rotulo_doc": s["rotulo"],
                          "pagina": s["pagina"], "texto": s["texto"], "rotulo_humano": None, "exemplo": False})
    else:
        for m in dados.documentos_do_corpus(db, pasta):
            if cfg.get("documento_id") and m["id"] != int(cfg["documento_id"]):
                continue
            saida.append({"origem": "documentos", "ref": str(m["id"]), "documento_id": m["id"], "rotulo_doc": m["rotulo"], "pagina": None,
                          "texto": _texto_do_documento(pasta, m["id"]), "rotulo_humano": None, "exemplo": False})
    lim = cfg.get("limite")
    if lim:
        permitidos = {id(u) for u in [x for x in saida if not x["exemplo"]][:lim]}
        saida = [u for u in saida if u["exemplo"] or id(u) in permitidos]
    return saida


def _exemplos(db, cfg: dict) -> list:
    if cfg["modo"] != "few_shot":
        return []
    humanos = list(db.scalars(select(CodificacaoTrecho).where(CodificacaoTrecho.codigo_humano.is_not(None)).order_by(CodificacaoTrecho.id)))
    return escolher_exemplos(humanos, cfg["rotulos"], cfg["k"])


def estimativa(db, pasta: Path, cfg_in: dict) -> dict:
    cfg = normalizar_config(cfg_in, pasta)
    ex = _exemplos(db, cfg)
    unidades = [u for u in _unidades(db, pasta, cfg, {t.id for t in ex}) if not u["exemplo"]]
    system = cache_prompt.system_como_texto(montar_system(cfg["rotulos"], cfg["multirrotulo"], ex))
    prefixo = cache_prompt.tokens_aprox(system)
    var = (sum(cache_prompt.tokens_aprox(montar_usuario(u["texto"])) for u in unidades) / len(unidades)) if unidades else 0
    pc = config.carregar()
    modelo = pc["anthropic"]["modelo"] if pc["provedor"] == "anthropic" else None
    return {"unidades": len(unidades), "rotulos": len(cfg["rotulos"]), "exemplos": len(ex), "prefixo_tokens_aprox": prefixo,
            "tokens_entrada_aprox": int(len(unidades) * (prefixo + var)), "tokens_saida_aprox": 80 * len(unidades),
            "custo": precos.estimar(modelo, len(unidades), prefixo, var, 80) if modelo else None,
            "provedor": pc["provedor"], "habilitado": pc["habilitado"], "remoto": pc["provedor"] in ("anthropic", "openai_compativel"),
            "com_humano": sum(1 for u in unidades if u["rotulo_humano"]),
            "nota": "Estimativa grosseira (~4 caracteres por token). Provedores remotos cobram por token e recebem as unidades."}


_ESTADO: dict[str, dict] = {}
_TRAVA = threading.Lock()


def progresso(slug: str) -> dict:
    with _TRAVA:
        e = dict(_ESTADO.get(slug) or {"rodando": False, "feitos": 0, "total": 0, "erros": 0})
    e.pop("cancelar", None)
    return e


def cancelar(slug: str) -> bool:
    with _TRAVA:
        e = _ESTADO.get(slug)
        if e and e.get("rodando"):
            e["cancelar"] = True
            return True
    return False


def ler_config_salva(pasta: Path) -> dict | None:
    try:
        return json.loads((pasta / "saidas" / ARQUIVO_CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _salvar_config(pasta: Path, cfg: dict, extra: dict) -> None:
    (pasta / "saidas").mkdir(parents=True, exist_ok=True)
    (pasta / "saidas" / ARQUIVO_CONFIG).write_text(json.dumps({**cfg, **extra}, ensure_ascii=False, indent=2), encoding="utf-8")


def _preparar(db, pasta: Path, cfg_in: dict, provedor=None):
    pc = config.carregar()
    if not pc["habilitado"]:
        raise LLMDesligado("O uso de LLM está desligado: ligue \"Permitir geração com LLM\" em Configurações.")
    cfg = normalizar_config(cfg_in, pasta)
    ex = _exemplos(db, cfg)
    unidades = _unidades(db, pasta, cfg, {t.id for t in ex})
    return pc, cfg, ex, unidades, provedor or provedor_configurado(pc)


def _classificar(db, pasta: Path, item: ClassificacaoItem, system, cfg: dict, prov, pc: dict) -> dict:
    user = montar_usuario(item.texto)
    texto_system = cache_prompt.system_como_texto(system)
    h = hashlib.sha256((texto_system + "\n" + user).encode("utf-8")).hexdigest()[:16]
    base = {"em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "analise": "classificacao",
            "item_id": item.id, "origem": item.origem, "provedor": pc["provedor"], "prompt_hash": h, "versao_prompt": VERSAO_PROMPT,
            "modo": cfg["modo"]}
    try:
        resp = prov.gerar(system, user)
    except ErroLLM as exc:
        item.status, item.rotulos, item.justificativa, item.confianca = "erro", None, f"Erro do provedor: {exc}", None
        db.commit()
        codificador._registrar_log(pasta, {**base, "erro": str(exc), "categoria": exc.categoria})
        return {"ok": False, "erro": str(exc)}
    r = interpretar(resp["texto"], [x["id"] for x in cfg["rotulos"]], cfg["multirrotulo"])
    item.modelo = str(resp.get("modelo") or "")[:200]
    item.resposta_bruta = resp["texto"][:4000]
    item.confianca = r["confianca"]
    if r["ok"]:
        item.status, item.rotulos, item.justificativa = "classificado", json.dumps(r["rotulos"], ensure_ascii=False), r["justificativa"]
    else:
        item.status, item.rotulos, item.justificativa = "erro", None, r["erro"]
    db.commit()
    codificador._registrar_log(pasta, {**base, "modelo": resp.get("modelo"), "uso": resp.get("uso") or {}, "request_id": resp.get("request_id"),
                                       **precos.anotar_uso(resp.get("modelo"), resp.get("uso"), cache_prompt.tokens_aprox(texto_system)),
                                       "ok": r["ok"], "segundos": resp.get("segundos")})
    return r


def executar(slug: str, sessao_factory, pasta: Path, cfg_in: dict, provedor=None) -> dict:
    """Classifica as unidades (síncrono) e grava os itens; uma execução nova substitui a anterior."""
    db = sessao_factory()
    try:
        pc, cfg, ex, unidades, prov = _preparar(db, pasta, cfg_in, provedor)
        db.execute(delete(ClassificacaoItem))
        itens = []
        for u in unidades:
            it = ClassificacaoItem(origem=u["origem"], ref=u["ref"], documento_id=u["documento_id"], rotulo_doc=u["rotulo_doc"], pagina=u["pagina"],
                                   texto=u["texto"], rotulo_humano=u["rotulo_humano"], status="exemplo" if u["exemplo"] else "pendente")
            db.add(it)
            itens.append(it)
        db.commit()
        _salvar_config(pasta, cfg, {"iniciado_em": datetime.datetime.now().isoformat(timespec="seconds"), "exemplos": [t.id for t in ex],
                                    "provedor": pc["provedor"]})
        alvo = [i for i in itens if i.status == "pendente"]
        with _TRAVA:
            _ESTADO[slug] = {"rodando": True, "feitos": 0, "total": len(alvo), "erros": 0, "cancelado": False, "finalizado_em": None,
                             "provedor": pc["provedor"], "ultimo_erro": None}
        system = montar_system(cfg["rotulos"], cfg["multirrotulo"], ex)
        inicio = time.time()
        for it in alvo:
            with _TRAVA:
                if _ESTADO[slug].get("cancelar"):
                    _ESTADO[slug]["cancelado"] = True
                    break
            r = _classificar(db, pasta, it, system, cfg, prov, pc)
            with _TRAVA:
                _ESTADO[slug]["feitos"] += 1
                if not r["ok"]:
                    _ESTADO[slug]["erros"] += 1
                    _ESTADO[slug]["ultimo_erro"] = r.get("erro")
        with _TRAVA:
            _ESTADO[slug].update(rodando=False, finalizado_em=datetime.datetime.now().isoformat(timespec="seconds"),
                                 segundos=round(time.time() - inicio, 1))
            return {k: v for k, v in _ESTADO[slug].items() if k != "cancelar"}
    except Exception as exc:
        with _TRAVA:
            if slug in _ESTADO and _ESTADO[slug].get("rodando"):
                _ESTADO[slug].update(rodando=False, erro=str(exc))
        raise
    finally:
        db.close()


def iniciar(slug: str, sessao_factory, pasta: Path, cfg_in: dict, provedor=None) -> dict:
    """Valida (LLM ligado, rótulos) e roda ``executar`` numa thread. Levanta RuntimeError se já houver lote rodando."""
    with _TRAVA:
        if (_ESTADO.get(slug) or {}).get("rodando"):
            raise RuntimeError("Já existe uma classificação em andamento neste projeto.")
    db = sessao_factory()
    try:
        _, _, ex, unidades, _ = _preparar(db, pasta, cfg_in, provedor)
        n = len([u for u in unidades if not u["exemplo"]])
    finally:
        db.close()
    with _TRAVA:
        _ESTADO[slug] = {"rodando": True, "feitos": 0, "total": n, "erros": 0}

    def alvo():
        try:
            executar(slug, sessao_factory, pasta, cfg_in, provedor)
        except Exception as exc:  # noqa: BLE001 - erro registrado no estado
            with _TRAVA:
                _ESTADO.setdefault(slug, {}).update(rodando=False, erro=str(exc))

    threading.Thread(target=alvo, name=f"classificacao-{slug}", daemon=True).start()
    return {"iniciado": True, "total": n}


# ---------- revisão e comparação com o humano ----------

def rotulos_do_item(it: ClassificacaoItem) -> list[str]:
    try:
        return list(json.loads(it.rotulos)) if it.rotulos else []
    except ValueError:
        return []


def par_humano_llm(it: ClassificacaoItem) -> tuple[str, str] | None:
    """(humano, llm) de um item com rótulo humano e classificação válida. Multirrótulo: se o humano está entre os rótulos
    do LLM conta como acerto (llm = humano); senão vale o 1º rótulo do LLM."""
    r = rotulos_do_item(it)
    if not it.rotulo_humano or not r or it.status != "classificado":
        return None
    return it.rotulo_humano, (it.rotulo_humano if it.rotulo_humano in r else r[0])
