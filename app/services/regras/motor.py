"""8.1 - Motor de regras: gera os comentários e os reconcilia com a revisão humana (princípio 4 e fluxo 5.3 [8]-[9]).

Geração
-------
Para cada regra ativa, o avaliador (``avaliadores.py``) devolve os candidatos com sua força; vale o corte
``max_comentarios`` (por cota: R07/R08 cortam por grupo), mais os comentários que já foram revisados por um
humano (aceito/editado/revisar/rejeitado) e continuam válidos, para que uma revisão não suma só porque o
ranking mudou. Para os selecionados, o texto é o ``modelo`` preenchido (pt-BR) e as evidências são trechos KWIC
com página. Sem LLM: o mesmo corpus e o mesmo catálogo dão sempre os mesmos comentários.

Reconciliação (casamento pela ``chave``)
----------------------------------------
- novo                -> ``sugerido``
- sugerido            -> texto, métricas e evidências atualizados
- aceito / editado    -> mantém o texto humano; atualiza as métricas; se o texto gerado ou a evidência mudou,
                         vira ``revisar`` (a proposta nova fica em ``texto_original``; o estado anterior, no histórico)
- revisar             -> atualiza proposta, métricas e evidências (continua em revisão)
- rejeitado           -> nunca ressuscita enquanto a chave continuar sendo gerada (só as métricas são atualizadas)
- chave não gerada    -> ``obsoleto`` (exceto rejeitado); se a chave voltar, o status anterior é restaurado
"""
import datetime
import hashlib
import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Comentario, Evidencia, agora
from app.services.regras import avaliadores
from app.services.regras.catalogo import Candidato, Regra, renderizar

STATUS_HUMANOS = ("aceito", "editado", "revisar", "rejeitado")
MAX_HISTORICO = 50


# ---------- geração ----------

def hash_das_evidencias(evidencias: list[dict]) -> str:
    base = [[e["documento_id"], e["pagina"], e["posicao"], e["trecho"]] for e in evidencias]
    return hashlib.sha256(json.dumps(base, ensure_ascii=False).encode("utf-8")).hexdigest()


def _selecionar(candidatos: list[Candidato], regra: Regra, humanas: set[str]) -> list[Candidato]:
    por_cota: dict[str, list[Candidato]] = {}
    for c in candidatos:
        por_cota.setdefault(c.cota, []).append(c)
    escolhidos: list[Candidato] = []
    for lista in por_cota.values():
        lista.sort(key=lambda c: (-c.forca, c.chave))
        topo = lista[: regra.max_comentarios]
        escolhidos.extend(topo)
        escolhidos.extend(c for c in lista[regra.max_comentarios:] if c.chave in humanas)
    return escolhidos


def gerar(ctx: avaliadores.Contexto, regras: list[Regra], humanas: set[str] = frozenset()) -> tuple[list[Candidato], list[str]]:
    """Candidatos finais (texto e evidências preenchidos) e avisos (ex.: candidato descartado por falta de evidência)."""
    finais: list[Candidato] = []
    avisos: list[str] = []
    vistas: set[str] = set()
    for regra in regras:
        if not regra.ativa:
            continue
        for c in _selecionar(avaliadores.avaliar(ctx, regra), regra, humanas):
            if c.chave in vistas:
                raise ValueError(f"Chave de comentário repetida: {c.chave} (regras duplicadas com a mesma lógica e o mesmo id?).")
            vistas.add(c.chave)
            c.texto = renderizar(regra.modelo, c.valores)
            c.evidencias = c.buscar_evidencias(regra.evidencias)
            if regra.evidencias > 0 and not c.evidencias:
                avisos.append(f"{c.chave}: sem evidência encontrada, comentário descartado")
                continue
            c.hash_evidencia = hash_das_evidencias(c.evidencias)
            finais.append(c)
    return finais, avisos


# ---------- reconciliação ----------

def ler_historico(c: Comentario) -> list[dict]:
    try:
        h = json.loads(c.historico_json) if c.historico_json else []
    except ValueError:
        return []
    return h if isinstance(h, list) else []


def registrar_historico(c: Comentario, evento: str, **dados) -> None:
    h = ler_historico(c)
    h.append({"em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "evento": evento, **dados})
    c.historico_json = json.dumps(h[-MAX_HISTORICO:], ensure_ascii=False)


def _snapshot_evidencias(c: Comentario) -> list[dict]:
    return [{"documento_id": e.documento_id, "pagina": e.pagina, "trecho": e.trecho} for e in c.evidencias]


def _trocar_evidencias(db: Session, c: Comentario, novas: list[dict]) -> None:
    antigas = list(c.evidencias)
    c.evidencias = [Evidencia(documento_id=e["documento_id"], pagina=e["pagina"], trecho=e["trecho"], termo=e["termo"],
                              posicao=e["posicao"]) for e in novas]
    for e in antigas:
        db.delete(e)


def _preencher(db: Session, c: Comentario, cand: Candidato, trocar_evidencias: bool) -> None:
    c.regra = cand.regra.id
    c.analise_tipo = cand.regra.analise
    c.metricas_json = json.dumps(cand.metricas, ensure_ascii=False)
    c.forca = cand.forca
    c.texto_original = cand.texto
    if trocar_evidencias:
        _trocar_evidencias(db, c, cand.evidencias)
    c.hash_evidencia = cand.hash_evidencia


def _motivo(mudou_texto: bool, mudou_evidencia: bool) -> str:
    if mudou_texto and mudou_evidencia:
        return "Os números e as evidências mudaram desde a revisão."
    return "Os números do comentário mudaram desde a revisão." if mudou_texto else "As evidências mudaram desde a revisão."


def _atualizar(db: Session, c: Comentario, cand: Candidato, cont: Counter) -> None:
    if c.status == "obsoleto":
        anteriores = [e.get("status_anterior") for e in ler_historico(c) if e.get("evento") == "obsoleto"]
        c.status = anteriores[-1] if anteriores and anteriores[-1] else "sugerido"
        cont["reativados"] += 1
    mudou_texto = cand.texto != (c.texto_original if c.texto_original is not None else c.texto)
    mudou_evidencia = cand.hash_evidencia != c.hash_evidencia
    if c.status == "sugerido":
        if mudou_texto or mudou_evidencia or c.texto != cand.texto:
            cont["atualizados"] += 1
        c.texto = cand.texto
        _preencher(db, c, cand, trocar_evidencias=mudou_evidencia)
    elif c.status == "rejeitado":
        _preencher(db, c, cand, trocar_evidencias=False)
        cont["rejeitados_mantidos"] += 1
    elif c.status in ("aceito", "editado"):
        if mudou_texto or mudou_evidencia:
            registrar_historico(
                c, "revisar", status_anterior=c.status, motivo=_motivo(mudou_texto, mudou_evidencia), texto_anterior=c.texto,
                texto_gerado_anterior=c.texto_original, hash_anterior=c.hash_evidencia,
                metricas_anteriores=json.loads(c.metricas_json) if c.metricas_json else None,
                evidencias_anteriores=_snapshot_evidencias(c))
            c.status = "revisar"
            _preencher(db, c, cand, trocar_evidencias=True)
            cont["revisar"] += 1
        else:
            _preencher(db, c, cand, trocar_evidencias=False)
    else:  # revisar: segue em revisão com a proposta mais recente
        _preencher(db, c, cand, trocar_evidencias=mudou_evidencia)


def reconciliar(db: Session, candidatos: list[Candidato]) -> Counter:
    """Grava os candidatos preservando a revisão humana. Não faz commit."""
    # Comentários redigidos por LLM (Frente 14) não vêm do motor: nunca viram obsoletos nem são sobrescritos aqui.
    existentes = {c.chave: c for c in db.scalars(select(Comentario).where(Comentario.chave.is_not(None))) if c.origem != "llm"}
    cont: Counter = Counter()
    geradas: set[str] = set()
    for cand in candidatos:
        geradas.add(cand.chave)
        c = existentes.get(cand.chave)
        if c is None:
            c = Comentario(chave=cand.chave, regra=cand.regra.id, texto=cand.texto, status="sugerido")
            _preencher(db, c, cand, trocar_evidencias=True)
            db.add(c)
            cont["novos"] += 1
        else:
            _atualizar(db, c, cand, cont)
    for chave, c in existentes.items():
        if chave not in geradas and c.status not in ("rejeitado", "obsoleto"):
            registrar_historico(c, "obsoleto", status_anterior=c.status)
            c.status = "obsoleto"
            cont["obsoletos"] += 1
    return cont


def humanas_existentes(db: Session) -> set[str]:
    return set(db.scalars(select(Comentario.chave).where(Comentario.chave.is_not(None), Comentario.status.in_(STATUS_HUMANOS))))


def comentar(db: Session, pasta_projeto, parametros: dict, regras: list[Regra], checar: bool = True) -> dict:
    """Gera e reconcilia. Devolve contagens (por situação e por regra) e avisos."""
    ctx = avaliadores.Contexto(db, pasta_projeto, parametros)
    candidatos, avisos = gerar(ctx, regras, humanas_existentes(db))
    cont = reconciliar(db, candidatos)
    db.commit()
    por_regra = Counter(c.regra.id for c in candidatos)
    resultado = {"gerados": len(candidatos), "por_regra": dict(sorted(por_regra.items())), **dict(cont), "avisos": avisos}
    if checar:  # 8.3: confere evidências e números com as métricas que acabaram de ser calculadas
        from app.services.regras import checagem
        c = checagem.checar_todos(db, pasta_projeto, parametros, frescos={x.chave: x for x in candidatos})
        resultado["checagem"] = {"verificados": c["verificados"], "falhas": len(c["falhas"])}
    return resultado
