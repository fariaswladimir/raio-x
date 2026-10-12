"""8.3 - Checagem de evidência antes do laudo (comentários de regra e de LLM).

Para cada comentário (``aceito``, ``editado``, ``sugerido`` ou ``revisar``; rejeitados e obsoletos ficam de fora)
conferem-se, contra o **estado atual** do projeto:

1. **Evidências**: cada trecho precisa existir no texto limpo atual do documento (``cache/limpo``), na página
   declarada (espaços colapsados; trechos com "…" são conferidos fragmento a fragmento); documento excluído,
   removido ou sem texto limpo também falha.
2. **Números e citações**:
   - comentário de regra sem edição: o texto tem de ser idêntico ao que a regra gera agora (todos os números vêm das
     métricas atuais); as métricas gravadas têm de coincidir com as atuais;
   - comentário editado por humano ou redigido por LLM: ``verificar()`` (``llm/gerador.py``) confere números,
     citações "(rótulo, p. N)" e trechos entre aspas contra as métricas atuais (a regra reavaliada, ou
     ``paragrafos.coletar`` para o LLM) e as evidências do comentário.

Falha -> o comentário passa a ``revisar`` (aceito, editado e sugerido) com o motivo no histórico, que a tela de revisão
já mostra; nada é reaceito automaticamente. O laudo só inclui o que passou (``laudo_html.gerar_laudo`` chama a checagem
antes de coletar). A checagem roda na etapa ``comentarios`` (com as métricas recém-calculadas) e em "Gerar laudo"
(reavalia as regras, pois o corpus pode ter mudado depois da última etapa).

Limites: a conferência é textual e numérica; não detecta interpretação indevida sem números, e um trecho que ainda
existe na página, mas cujo contexto mudou, continua válido.
"""
import json
import math
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Comentario, Documento
from app.services.analises import dados
from app.services.regras.motor import ler_historico, registrar_historico

STATUS_CHECADOS = ("aceito", "editado", "sugerido", "revisar")
STATUS_REBAIXADOS = ("aceito", "editado", "sugerido")
PREFIXO = "Checagem de evidência: "
_ESPACOS = re.compile(r"\s+")
_RETICENCIAS = re.compile(r"…|\[\.\.\.\]|\.\.\.")


def _colapsar(texto: str) -> str:
    return _ESPACOS.sub(" ", texto).strip()


# ---------- evidências ----------

class _Paginas:
    """Texto limpo atual de cada documento, por página (espaços colapsados), carregado uma vez por checagem."""

    def __init__(self, pasta: Path):
        self.pasta = pasta
        self._docs: dict[int, dict | None] = {}

    def doc(self, documento_id: int) -> dict | None:
        if documento_id not in self._docs:
            blocos = dados.carregar_blocos(self.pasta, documento_id)
            if blocos is None:
                self._docs[documento_id] = None
            else:
                por_pagina: dict[int | None, list[str]] = {}
                for b in blocos:
                    por_pagina.setdefault(b.get("pagina"), []).append(b["texto"])
                paginas = {p: _colapsar(" ".join(t)) for p, t in por_pagina.items()}
                self._docs[documento_id] = {"paginas": paginas, "tudo": " ".join(paginas.values())}
        return self._docs[documento_id]


def checar_evidencia(e, paginas: _Paginas, documentos: dict[int, Documento]) -> str | None:
    """Motivo da falha da evidência ``e`` (``None`` = ok)."""
    d = documentos.get(e.documento_id)
    rotulo = dados.rotulo_do_documento(d) if d else f"documento {e.documento_id}"
    if d is None or d.status == "removido":
        return f"documento da evidência ({rotulo}) não existe mais no projeto"
    if e.posicao is None and e.pagina is None:
        return None  # evidência de métrica/metadado ("D06 · Autor 2026: 890 palavras no corpo"): não é citação do texto
    if d.excluido or d.status == "com_problema":
        return f"documento da evidência ({rotulo}) está excluído ou com problema"
    texto = paginas.doc(e.documento_id)
    if texto is None:
        return f"texto limpo de {rotulo} não encontrado (execute o pipeline)"
    pag = f"p. {e.pagina}" if e.pagina is not None else "sem página"
    base = texto["paginas"].get(e.pagina) if e.pagina is not None else texto["tudo"]
    if base is None:
        return f"página {e.pagina} não existe em {rotulo}"
    fragmentos = [f for f in (_colapsar(x) for x in _RETICENCIAS.split(e.trecho)) if f]
    for f in fragmentos:
        if f not in texto["tudo"]:
            return f"trecho não encontrado no texto atual de {rotulo}: “{f[:60]}{'…' if len(f) > 60 else ''}”"
    # o contexto pode se estender às páginas vizinhas (fragmentos separados por "…"): o fragmento do termo (ou ao
    # menos um) precisa estar na página declarada
    formas = [t.strip().lower() for t in (e.termo or "").split("|") if t.strip()]
    do_termo = [f for f in fragmentos if any(t in f.lower() for t in formas)] or fragmentos
    if do_termo and not any(f in base for f in do_termo):
        return f"o trecho existe no texto atual de {rotulo}, mas não na {pag}: “{do_termo[0][:60]}{'…' if len(do_termo[0]) > 60 else ''}”"
    return None


# ---------- números ----------

def _iguais(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_iguais(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_iguais(x, y) for x, y in zip(a, b))
    return a == b


def _campos_diferentes(gravadas: dict, atuais: dict) -> list[str]:
    return sorted(k for k in set(gravadas) | set(atuais) if not _iguais(gravadas.get(k), atuais.get(k)))


def _lista_evidencias(c: Comentario) -> list[dict]:
    return [{"documento_id": e.documento_id, "pagina": e.pagina, "trecho": e.trecho,
             "rotulo": dados.rotulo_do_documento(e.documento)} for e in c.evidencias]


def _verificar_texto(c: Comentario, metricas: dict) -> list[str]:
    from app.services.llm import gerador  # import tardio: evita ciclo (gerador importa regras.motor)

    v = gerador.verificar(c.texto, metricas, _lista_evidencias(c))
    return [] if v["ok"] else [gerador.motivos_da_verificacao(v).removeprefix("Conferência automática: ").rstrip(".")]


def _metricas_gravadas(c: Comentario) -> dict:
    try:
        m = json.loads(c.metricas_json) if c.metricas_json else {}
    except ValueError:
        return {}
    return m if isinstance(m, dict) else {}


def checar_numeros_regra(c: Comentario, cand) -> list[str]:
    if cand is None:
        return ["a regra não gera mais este comentário com o corpus e os parâmetros atuais"]
    atuais = json.loads(json.dumps(cand.metricas, ensure_ascii=False, default=str))
    motivos = []
    diff = _campos_diferentes(_metricas_gravadas(c), atuais)
    if diff:
        motivos.append("as métricas gravadas diferem das atuais (" + ", ".join(diff[:6]) + (", …" if len(diff) > 6 else "") + ")")
    editado = c.status == "editado" or (c.texto_original is not None and c.texto != c.texto_original)
    if not editado:
        if c.texto != cand.texto:
            motivos.append("os números do texto não coincidem com as métricas atuais")
    else:
        motivos.extend(_verificar_texto(c, atuais))
    return motivos


def checar_numeros_llm(db: Session, pasta: Path, c: Comentario, cache: dict) -> list[str]:
    from app.services import paragrafos

    analise = c.analise_tipo
    if not analise:
        return []
    if analise not in cache:
        try:
            cache[analise] = paragrafos.coletar(db, pasta, analise)["metricas"]
        except (paragrafos.AnaliseIndisponivel, ValueError, KeyError) as exc:
            cache[analise] = exc
    atuais = cache[analise]
    if isinstance(atuais, Exception):
        return [f"não foi possível recalcular as métricas de {analise}: {atuais}"]
    return _verificar_texto(c, json.loads(json.dumps(atuais, ensure_ascii=False, default=str)))


# ---------- comentário e corpus ----------

def checar_comentario(db: Session, pasta: Path, c: Comentario, frescos: dict | None, paginas: _Paginas,
                      documentos: dict[int, Documento], cache_llm: dict) -> list[str]:
    motivos = []
    for e in c.evidencias:
        m = checar_evidencia(e, paginas, documentos)
        if m:
            motivos.append(m)
    if c.origem == "llm":
        motivos.extend(checar_numeros_llm(db, pasta, c, cache_llm))
    elif c.origem == "regra" and c.chave and frescos is not None:
        motivos.extend(checar_numeros_regra(c, frescos.get(c.chave)))
    return motivos


def candidatos_atuais(db: Session, pasta: Path, parametros: dict) -> dict | None:
    """``{chave: candidato}`` com o que as regras geram agora (``None`` se o catálogo for inválido ou faltar dado)."""
    from app.services.regras import avaliadores, catalogo, motor

    try:
        regras = catalogo.carregar_catalogo()
        ctx = avaliadores.Contexto(db, pasta, parametros)
        candidatos, _ = motor.gerar(ctx, regras, motor.humanas_existentes(db))
    except Exception:  # noqa: BLE001  (sem pipeline/catálogo inválido: a checagem de números das regras fica de fora)
        return None
    return {c.chave: c for c in candidatos}


def checar_todos(db: Session, pasta: Path, parametros: dict, frescos: dict | None = None, recalcular: bool = True,
                 aplicar: bool = True) -> dict:
    """Checa os comentários e (``aplicar``) rebaixa os que falham para ``revisar``. Faz commit se mudou algo.

    ``frescos`` = candidatos já calculados (etapa ``comentarios``); sem ele e com ``recalcular`` as regras são reavaliadas.
    Devolve ``{"verificados", "ok", "falhas": [{id, regra, origem, status_antes, status_depois, motivos}]}``."""
    if frescos is None and recalcular:
        frescos = candidatos_atuais(db, pasta, parametros)
    documentos = {d.id: d for d in db.scalars(select(Documento))}
    paginas, cache_llm = _Paginas(pasta), {}
    comentarios = list(db.scalars(select(Comentario).where(Comentario.status.in_(STATUS_CHECADOS)).order_by(Comentario.id)))
    falhas = []
    for c in comentarios:
        motivos = checar_comentario(db, pasta, c, frescos, paginas, documentos, cache_llm)
        if not motivos:
            continue
        antes = c.status
        depois = "revisar" if aplicar and antes in STATUS_REBAIXADOS else antes
        if aplicar:
            texto_motivo = PREFIXO + "; ".join(motivos) + "."
            ultimo = [e.get("motivo") for e in ler_historico(c) if e.get("evento") == "revisar"]
            if depois != antes or not ultimo or ultimo[-1] != texto_motivo:
                registrar_historico(c, "revisar", status_anterior=antes, motivo=texto_motivo, origem_do_motivo="checagem")
                c.status = depois
        falhas.append({"id": c.id, "regra": c.regra, "origem": c.origem, "status_antes": antes, "status_depois": depois,
                       "motivos": motivos})
    if aplicar and falhas:
        db.commit()
    return {"verificados": len(comentarios), "ok": len(comentarios) - len(falhas), "falhas": falhas}
