"""10.1 - Execução do pipeline em segundo plano, com progresso por etapa.

Uma execução por projeto de cada vez. O estado vive em memória (some ao reiniciar o servidor; o
histórico durável continua na tabela ``execucao``). A sessão do SQLite é criada dentro da thread.
"""
import threading
import uuid
from pathlib import Path

from app.database import pasta_do_projeto, sessao_do_projeto
from app.models import agora
from app.services import orquestrador

_estados: dict[str, dict] = {}
_trava = threading.Lock()


class ExecucaoEmAndamento(Exception):
    pass


def _iso(dt) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _novo_estado(run_id: str, nomes: list[tuple[str, str]]) -> dict:
    return {
        "run_id": run_id, "rodando": True, "etapa_atual": None, "iniciado_em": agora(), "finalizado_em": None,
        "resumo": None, "erro": None,
        "etapas": [{"nome": n, "escopo": e, "total": None, "feitos": 0, "pulados": 0, "erros": 0, "status": "pendente"}
                   for n, e in nomes],
    }


def _callback(slug: str):
    def cb(ev: dict) -> None:
        with _trava:
            est = _estados[slug]
            etapa = next((e for e in est["etapas"] if e["nome"] == ev["nome"]), None)
            if etapa is None:
                return
            if ev["evento"] == "etapa":
                for anterior in est["etapas"]:
                    if anterior["status"] == "rodando":
                        anterior["status"] = "com_erros" if anterior["erros"] else "concluida"
                etapa["total"] = ev["total"]
                etapa["status"] = "rodando"
                est["etapa_atual"] = etapa["nome"]
            else:
                etapa["feitos"] += 1
                if ev["status"] == "pulado":
                    etapa["pulados"] += 1
                elif ev["status"] == "erro":
                    etapa["erros"] += 1
    return cb


def _corpo(slug: str, run_id: str, somente: list[str] | None) -> None:
    db = sessao_do_projeto(slug)  # a sessão nasce na thread que a usa
    try:
        resumo = orquestrador.executar_pipeline(db, Path(pasta_do_projeto(slug)), somente, progresso=_callback(slug))
        with _trava:
            _estados[slug]["resumo"] = resumo
    except Exception as exc:  # noqa: BLE001
        with _trava:
            _estados[slug]["erro"] = f"{type(exc).__name__}: {exc}"
    finally:
        db.close()
        with _trava:
            est = _estados[slug]
            for e in est["etapas"]:
                if e["status"] == "rodando":
                    e["status"] = "com_erros" if e["erros"] else "concluida"
                    if e["total"] is not None:
                        e["total"] = max(e["total"], e["feitos"])
            est["etapa_atual"] = None
            est["finalizado_em"] = agora()
            est["rodando"] = False


def esta_rodando(slug: str) -> bool:
    with _trava:
        est = _estados.get(slug)
        return bool(est and est["rodando"])


def iniciar(slug: str, somente: list[str] | None = None) -> dict:
    """Dispara a execução; levanta ExecucaoEmAndamento se já houver uma rodando neste projeto."""
    nomes = [(e.nome, e.escopo) for e in orquestrador.etapas_registradas() if not somente or e.nome in somente]
    with _trava:
        atual = _estados.get(slug)
        if atual and atual["rodando"]:
            raise ExecucaoEmAndamento(slug)
        run_id = uuid.uuid4().hex[:12]
        _estados[slug] = _novo_estado(run_id, nomes)
        iniciado = _estados[slug]["iniciado_em"]
    threading.Thread(target=_corpo, args=(slug, run_id, somente), name=f"raiox-{slug}", daemon=True).start()
    return {"run_id": run_id, "slug": slug, "iniciado_em": _iso(iniciado)}


def progresso(slug: str) -> dict:
    with _trava:
        est = _estados.get(slug)
        if est is None:
            return {"run_id": None, "rodando": False, "etapa_atual": None, "etapas": [], "iniciado_em": None,
                    "finalizado_em": None, "resumo": None, "erro": None}
        return {**est, "etapas": [dict(e) for e in est["etapas"]],
                "iniciado_em": _iso(est["iniciado_em"]), "finalizado_em": _iso(est["finalizado_em"])}
