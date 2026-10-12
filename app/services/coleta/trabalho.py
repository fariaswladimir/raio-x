"""17.2 - Execução da coleta (síncrona ou em segundo plano, com progresso) e execução incremental.

Incremental: cada célula guarda ``hash_entrada`` (hash do texto do documento + hash da definição do item). Uma nova execução só recalcula as células
cujo documento ou item mudou (ou que ainda não existem). **Nunca** sobrescreve célula decidida pelo revisor (aceito, editado, rejeitado, não se aplica):
se o texto do documento mudou, confere se a evidência ainda existe literalmente e, se não, marca a célula como ``revisar``; se a definição do item mudou,
marca ``definicao_mudou``. ``forcar`` recalcula tudo, menos as decididas.

LLM (``llm``): ``desligado`` (padrão; só regras), ``faltantes`` (só itens sem valor, ambíguos ou com confiança < 0.5) ou ``todos``. Exige "Permitir geração
com LLM" ligado na Frente 14 (``LLMDesligado`` senão). Uma chamada por documento e lote de até ``itens_por_chamada`` itens; o protocolo inteiro é o prefixo
em cache (``llm_coleta.montar_system``). O resultado do modelo só entra se passar na conferência literal (``llm_coleta.conferir_resposta``).

Progresso em segundo plano: mesmo padrão da 10.1 (estado em memória por projeto, uma execução por vez, ``GET .../coleta/progresso``).
"""
import threading
import time
import uuid
from pathlib import Path

from app.database import pasta_do_projeto, sessao_do_projeto
from app.services import parametros as svc_parametros
from app.services import ruido as svc_ruido
from app.services.coleta import celulas as C
from app.services.coleta import llm_coleta as LC
from app.services.coleta import motor as M
from app.services.coleta import protocolo as PR
from app.services.corpus import llm_partes as L
from app.services.corpus import planilha as svc_planilha
from app.services.corpus import projeto as svc_projeto
from app.services.llm import config as cfg_llm
from app.services.llm.provedores import ErroLLM, provedor_configurado

MODOS_LLM = ("desligado", "faltantes", "todos")
CONFIANCA_BAIXA = 0.5
CATEGORIAS_FATAIS = ("config", "conexao", "chave", "autenticacao", "permissao", "offline", "modelo")
MAX_CONTEXTO_FALLBACK = 2200


class LLMDesligado(Exception):
    """A geração com LLM está desligada na configuração global (padrão)."""


def precisa_llm(cel: dict, modo: str) -> bool:
    if modo == "todos":
        return True
    return cel.get("status") == "nao_encontrado" or cel.get("valor") == M.E.AMBIGUO or float(cel.get("confianca") or 0) < CONFIANCA_BAIXA


def precisa_recalcular(cel: dict | None, hash_ent: str, llm_sig: str, modo: str) -> bool:
    if cel is None or cel.get("hash_entrada") != hash_ent:
        return True
    if modo != "desligado" and cel.get("llm_assinatura", "") != llm_sig:
        if modo == "todos":
            return True
        return cel.get("origem") != "llm" and precisa_llm(cel, "faltantes")
    return False


def _fallback(ctx: M.ContextoDocumento, item: dict) -> list[dict]:
    """Sem candidatas: frases das seções do item (ou resumo + introdução) para o modelo ler."""
    secoes = item["onde_procurar"] if item["onde_procurar"] != [PR.QUALQUER] else ["resumo", "introducao"]
    return [{"f": f, "nota": 0.0} for f in ctx.frases_para(secoes) if f["secao"] in secoes and len(f["texto"]) >= 20]


def _rotulo(doc) -> str:
    from app.services.analises import dados as svc_dados

    return svc_dados.rotulo_do_documento(doc)


def _celula_llm(item: dict, parcial: dict, modelo: str, base: dict) -> dict:
    alternativas = list(base.get("alternativas") or [])
    if base.get("valor") is not None and base.get("valor") != parcial["valor"]:
        alternativas.insert(0, {"valor": base["valor"], "origem": base.get("origem"), "justificativa": base.get("justificativa"), "confianca": base.get("confianca")})
    return {**base, "valor": parcial["valor"], "unidade": parcial.get("unidade"), "trechos": parcial["trechos"], "origem": "llm", "confianca": parcial["confianca"],
            "status": "sugerido", "justificativa": f"LLM: {modelo}", "alternativas": alternativas[:3]}


def _rodar_llm(ctx: M.ContextoDocumento, doc, itens_protocolo: list[dict], alvo: list[dict], cands: dict, novas: dict, prov, modo: str, por_chamada: int, resumo: dict, llm_sig: str) -> None:
    system = LC.montar_system(itens_protocolo)
    for k in range(0, len(alvo), por_chamada):
        lote = alvo[k:k + por_chamada]
        contextos = {}
        total = 0
        for it in lote:
            base_cands = cands.get(it["id"]) or _fallback(ctx, it)
            contextos[it["id"]] = LC.contexto_do_item(base_cands, min(LC.MAX_CONTEXTO_ITEM, max(600, LC.MAX_CONTEXTO_TOTAL // len(lote))))
            total += len(contextos[it["id"]])
        usuario = LC.montar_usuario(_rotulo(doc), lote, contextos)
        resumo["llm"]["chamadas"] += 1
        try:
            resp = prov.gerar(system, usuario)
        except ErroLLM as exc:
            if exc.categoria in CATEGORIAS_FATAIS:
                raise
            resumo["erros"].append({"documento": doc.arquivo, "erro": cfg_llm.ocultar(str(exc), cfg_llm.ler_chave("anthropic"), cfg_llm.ler_chave("openai_compativel"))})
            continue
        resumo["llm"]["modelo"] = str(resp.get("modelo") or getattr(prov, "modelo", "") or "")
        uso = resp.get("uso") or {}
        for chave in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            resumo["llm"]["uso"][chave] = resumo["llm"]["uso"].get(chave, 0) + int(uso.get(chave) or 0)
        try:
            devolvido = LC.ler_resposta(resp["texto"])
        except ValueError:
            resumo["llm"]["json_invalido"] += 1
            resumo["erros"].append({"documento": doc.arquivo, "erro": "o modelo não devolveu um JSON válido"})
            continue
        for it in lote:
            parcial, descartes = LC.conferir_resposta(it, devolvido.get(it["id"]), ctx.texto_do_documento())
            resumo["llm"]["descartados"] += len([d for d in descartes if d["motivo"] == "trecho não existe no documento"])
            resumo["llm"]["respostas_recusadas"] += 1 if parcial is None and devolvido.get(it["id"]) not in (None, {}) and (devolvido.get(it["id"]) or {}).get("valor") not in (None, "", []) else 0
            cel = novas[it["id"]]
            cel["llm_assinatura"] = llm_sig
            if parcial is not None:
                resumo["llm"]["trechos_verificados"] += len(parcial["trechos"])
                resumo["llm"]["celulas"] += 1
                novas[it["id"]] = _celula_llm(it, parcial, resumo["llm"]["modelo"], cel)
                novas[it["id"]]["llm_assinatura"] = llm_sig
            else:
                cel["llm_descartes"] = [d["motivo"] for d in descartes][:5]
            if descartes:
                resumo["llm"]["descartes"].extend({"documento": doc.arquivo, "item": it["id"], **d} for d in descartes[:6])


def executar(db, pasta: Path, opcoes: dict | None = None, progresso=None, provedor=None) -> dict:
    """Executa a coleta. ``opcoes``: ``documento_ids``, ``item_ids``, ``llm`` (desligado|faltantes|todos), ``forcar``, ``itens_por_chamada``."""
    opcoes = opcoes or {}
    cb = progresso or (lambda ev: None)
    prot = PR.carregar(pasta)
    itens = prot["itens"]
    if not itens:
        raise ValueError("O protocolo de coleta está vazio: crie ou carregue um modelo antes de executar.")
    ids_itens = opcoes.get("item_ids")
    alvo_itens = [i for i in itens if not ids_itens or i["id"] in ids_itens]
    if not alvo_itens:
        raise ValueError("Nenhum item do protocolo corresponde à seleção.")
    modo = opcoes.get("llm") or "desligado"
    if modo not in MODOS_LLM:
        raise ValueError(f"Modo de LLM inválido: use {', '.join(MODOS_LLM)}.")
    prov, llm_sig = None, ""
    if modo != "desligado":
        cfg = cfg_llm.carregar()
        if not cfg["habilitado"]:
            raise LLMDesligado("A coleta com LLM está desligada: ligue \"Permitir geração com LLM\" em Configurações.")
        prov = provedor or provedor_configurado(cfg)
        llm_sig = f"{prov.nome}:{getattr(prov, 'modelo', '')}:{modo}"
    forcar = bool(opcoes.get("forcar"))
    por_chamada = max(1, int(opcoes.get("itens_por_chamada") or LC.ITENS_POR_CHAMADA))
    params = svc_parametros.carregar(pasta)
    excluir = svc_ruido.excluir_ruido(params)
    params16 = svc_planilha.parametros_planilha(pasta)
    hashes = {i["id"]: PR.hash_item(i) for i in itens}
    ids_docs = opcoes.get("documento_ids")
    docs = [d for d in svc_projeto.documentos_ativos(db) if not ids_docs or d.id in ids_docs]
    inicio = time.time()
    resumo = {"documentos": len(docs), "itens": len(alvo_itens), "calculadas": 0, "puladas": 0, "preservadas": 0, "sem_texto": [], "erros": [], "tempos": {},
              "revisar": 0, "llm": {"modo": modo, "chamadas": 0, "celulas": 0, "trechos_verificados": 0, "descartados": 0, "respostas_recusadas": 0, "json_invalido": 0,
                                     "modelo": None, "uso": {}, "descartes": [], "json_invalido_ids": []},
              "por_status": {}, "versao_protocolo": prot["versao_protocolo"]}
    cb({"evento": "inicio", "total": len(docs)})
    for doc in docs:
        t0 = time.time()
        hd = M.hash_documento(pasta, doc.id, excluir)
        if hd is None:
            resumo["sem_texto"].append(doc.arquivo)
            cb({"evento": "documento", "arquivo": doc.arquivo, "calculadas": 0, "puladas": 0})
            continue
        instantaneo = C.carregar(pasta)
        ctx = None
        conferencias: dict[str, dict] = {}
        pendentes = []
        puladas = preservadas = 0
        for it in alvo_itens:
            cel = C.celula_de(instantaneo, doc.arquivo, it["id"])
            he = M.hash_entrada(hd, it, hashes[it["id"]], params16)
            if C.decidida(cel):
                preservadas += 1
                conf = {}
                if cel.get("hash_doc") != hd or forcar:
                    ctx = ctx or M.ContextoDocumento(pasta, doc, params, excluir)
                    ok, total = M.evidencia_existe(ctx.texto_do_documento(), cel.get("trechos") or [])
                    conf["revisar"] = None if (total == 0 or ok == total) else f"a evidência não foi encontrada no texto atual ({total - ok} de {total} trecho(s)); confira o documento"
                    conf["hash_doc"] = hd
                if cel.get("hash_item") != hashes[it["id"]]:
                    conf["definicao_mudou"] = True
                if conf:
                    conferencias[it["id"]] = conf
                continue
            if not forcar and not precisa_recalcular(cel, he, llm_sig, modo):
                puladas += 1
                continue
            pendentes.append((it, he))
        novas: dict[str, dict] = {}
        if pendentes:
            ctx = ctx or M.ContextoDocumento(pasta, doc, params, excluir)
            cands: dict[str, list] = {}
            for it, he in pendentes:
                cel, cs = M.calcular_item(ctx, it)
                cel.update({"hash_doc": hd, "hash_item": hashes[it["id"]], "hash_entrada": he, "llm_assinatura": "", "calculado_em": M.agora()})
                novas[it["id"]] = cel
                cands[it["id"]] = cs
            if prov is not None:
                alvo_llm = [it for it, _he in pendentes if precisa_llm(novas[it["id"]], modo)]
                if alvo_llm:
                    _rodar_llm(ctx, doc, itens, alvo_llm, cands, novas, prov, modo, por_chamada, resumo, llm_sig)
        with C.trava(pasta):
            dados = C.carregar(pasta)
            por_doc = dados["celulas"].setdefault(doc.arquivo, {})
            for iid, cel in novas.items():
                if C.decidida(por_doc.get(iid)):  # decidida enquanto a execução rodava: vale a decisão
                    continue
                por_doc[iid] = cel
            for iid, conf in conferencias.items():
                if iid in por_doc:
                    por_doc[iid].update(conf)
            C.salvar(pasta, dados)
        resumo["calculadas"] += len(novas)
        resumo["puladas"] += puladas
        resumo["preservadas"] += preservadas
        resumo["revisar"] += sum(1 for c in conferencias.values() if c.get("revisar"))
        resumo["tempos"][doc.arquivo] = round(time.time() - t0, 2)
        cb({"evento": "documento", "arquivo": doc.arquivo, "calculadas": len(novas), "puladas": puladas, "preservadas": preservadas, "llm": resumo["llm"]})
    final = C.carregar(pasta)
    for itens_doc in final["celulas"].values():
        for c in itens_doc.values():
            resumo["por_status"][c["status"]] = resumo["por_status"].get(c["status"], 0) + 1
    resumo["segundos"] = round(time.time() - inicio, 2)
    resumo["llm"]["descartes"] = resumo["llm"]["descartes"][:60]
    with C.trava(pasta):
        dados = C.carregar(pasta)
        dados["ultima_execucao"] = {k: v for k, v in resumo.items() if k not in ("tempos",)} | {"em": M.agora(), "tempo_medio_por_documento": round(sum(resumo["tempos"].values()) / max(1, len(resumo["tempos"])), 2)}
        C.salvar(pasta, dados)
    return resumo


# ---------- segundo plano ----------

_estados: dict[str, dict] = {}
_trava = threading.Lock()


def _novo_estado(run_id: str, opcoes: dict) -> dict:
    return {"run_id": run_id, "rodando": True, "total": None, "feitos": 0, "documento_atual": None, "calculadas": 0, "puladas": 0, "preservadas": 0,
            "llm": {"modo": opcoes.get("llm") or "desligado", "chamadas": 0, "celulas": 0, "trechos_verificados": 0, "descartados": 0},
            "iniciado_em": M.agora(), "finalizado_em": None, "resumo": None, "erro": None}


def _callback(slug: str):
    def cb(ev: dict) -> None:
        with _trava:
            est = _estados[slug]
            if ev["evento"] == "inicio":
                est["total"] = ev["total"]
            elif ev["evento"] == "documento":
                est["feitos"] += 1
                est["documento_atual"] = ev["arquivo"]
                est["calculadas"] += ev.get("calculadas", 0)
                est["puladas"] += ev.get("puladas", 0)
                est["preservadas"] += ev.get("preservadas", 0)
                if ev.get("llm"):
                    est["llm"].update({k: ev["llm"][k] for k in ("chamadas", "celulas", "trechos_verificados", "descartados")})
    return cb


def esta_rodando(slug: str) -> bool:
    with _trava:
        est = _estados.get(slug)
        return bool(est and est["rodando"])


def _corpo(slug: str, opcoes: dict) -> None:
    db = sessao_do_projeto(slug)
    try:
        resumo = executar(db, Path(pasta_do_projeto(slug)), opcoes, progresso=_callback(slug))
        with _trava:
            _estados[slug]["resumo"] = resumo
    except Exception as exc:  # noqa: BLE001
        with _trava:
            _estados[slug]["erro"] = f"{type(exc).__name__}: {exc}"
    finally:
        db.close()
        with _trava:
            _estados[slug]["rodando"] = False
            _estados[slug]["finalizado_em"] = M.agora()


class ExecucaoEmAndamento(Exception):
    pass


def iniciar(slug: str, opcoes: dict | None = None) -> dict:
    """Dispara a coleta em segundo plano; levanta ``ExecucaoEmAndamento`` se já houver uma rodando neste projeto."""
    opcoes = opcoes or {}
    with _trava:
        atual = _estados.get(slug)
        if atual and atual["rodando"]:
            raise ExecucaoEmAndamento(slug)
        run_id = uuid.uuid4().hex[:12]
        _estados[slug] = _novo_estado(run_id, opcoes)
        iniciado = _estados[slug]["iniciado_em"]
    threading.Thread(target=_corpo, args=(slug, opcoes), name=f"raiox-coleta-{slug}", daemon=True).start()
    return {"run_id": run_id, "slug": slug, "iniciado_em": iniciado}


def progresso(slug: str) -> dict:
    with _trava:
        est = _estados.get(slug)
        if est is None:
            return {"run_id": None, "rodando": False, "total": None, "feitos": 0, "resumo": None, "erro": None}
        return {**est, "llm": dict(est["llm"])}
