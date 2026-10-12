"""14.3 - Gera um parágrafo adaptado com LLM, confere o texto contra os dados e o grava como comentário "sugerido".

Fluxo: modelo de parágrafo + métricas + até 5 trechos -> provedor -> ``verificar`` -> ``Comentario`` (origem "llm").
O texto nunca é aceito automaticamente: sem problemas na checagem entra como ``sugerido``; com qualquer problema,
como ``revisar`` com os motivos no histórico. Só vai ao laudo se um humano aceitar.
"""
import datetime
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Comentario, Evidencia, agora
from app.services import paragrafos
from app.services.llm import config, prompts
from app.services.llm.provedores import ErroLLM, provedor_configurado
from app.services.regras.motor import registrar_historico

ARQUIVO_LOG = "llm_log.jsonl"


class LLMDesligado(Exception):
    """A geração com LLM está desligada na configuração global (padrão)."""


# ---------- verificação ----------

_NUMERO = re.compile(r"(?<![\w.,])\d[\d.,]*\d|(?<![\w.,])\d")
_CITACAO = re.compile(r"\(([^()]*\bp\.[^()]*)\)")
_PARTE_CITACAO = re.compile(r"^\s*(.+?),\s*p\.\s*(\d+)\s*$")
_ASPAS = re.compile(r"“([^”]{1,600})”|\"([^\"\n]{1,600})\"")
_ISENTOS = re.compile(r"(?i)\b(?:eixos?|grupos?|cluster|dimens[ãa]o|figura|tabela|etapa)\s+$")
_P_LIMIAR = re.compile(r"(?i)\bp\s*[<≤]\s*$")
_DEZ_MIL = re.compile(r"(?i)\b10\s*(?:mil|k)\b")
LIMIARES_P = (0.001, 0.01, 0.05)


def _norm(s: str) -> str:
    s = s.replace("–", "-").replace("—", "-").replace("’", "'")
    return " ".join(s.split()).casefold()


def candidatos_do_numero(token: str) -> list[tuple[float, int]]:
    """Interpretações possíveis de um número escrito (pt-BR 1.234,5 ou en 1,234.5): lista de (valor, casas decimais)."""
    pontos, virgulas = token.count("."), token.count(",")
    if pontos and virgulas:
        dec = "." if token.rfind(".") > token.rfind(",") else ","
        mil = "," if dec == "." else "."
        inteiro, _, frac = token.replace(mil, "").partition(dec)
        return [(float(f"{inteiro}.{frac}"), len(frac))]
    sep = "." if pontos else ("," if virgulas else "")
    if not sep:
        return [(float(token), 0)]
    partes = token.split(sep)
    if len(partes) > 2:  # 1.234.567: só pode ser separador de milhar
        return [(float("".join(partes)), 0)]
    inteiro, frac = partes
    cands = [(float(f"{inteiro}.{frac}"), len(frac))]
    if len(frac) == 3 and 1 <= len(inteiro) <= 3:  # 1.234 / 1,234: milhar ou decimal
        cands.append((float(inteiro + frac), 0))
    return cands


def _valores_permitidos(obj, saida: set[float] | None = None, textos: list[str] | None = None):
    saida = set() if saida is None else saida
    textos = [] if textos is None else textos
    if isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        saida.add(float(obj))
    elif isinstance(obj, str):
        textos.append(obj)
        for t in _NUMERO.findall(obj):
            saida.update(v for v, _ in candidatos_do_numero(t))
    elif isinstance(obj, dict):
        for v in obj.values():
            _valores_permitidos(v, saida, textos)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _valores_permitidos(v, saida, textos)
    return saida, textos


def _confere(x: float, casas: int, permitidos: set[float], porcentagem: bool = False) -> bool:
    tol = 0.5 * 10 ** (-casas) + 1e-9  # o texto mostra o valor arredondado às suas casas decimais
    for v in permitidos:
        if abs(x - v) <= tol or (porcentagem and abs(v) <= 1.5 and abs(x - v * 100) <= tol):  # fração 0,036 escrita como 3,6%
            return True
    return False


def verificar(texto: str, metricas: dict, evidencias: list[dict]) -> dict:
    """Confere números, citações "(rótulo, p. N)" e trechos entre aspas do ``texto`` contra o que foi fornecido ao modelo."""
    permitidos, textos_metricas = _valores_permitidos(metricas)
    for e in evidencias:  # páginas fornecidas também valem como números (ex.: "na página 7")
        if e.get("pagina") is not None:
            permitidos.add(float(e["pagina"]))
    base_trechos = _norm(" ".join(e["trecho"] for e in evidencias))
    base_metricas = _norm(" ".join(textos_metricas))
    validas = {(_norm(e["rotulo"]), int(e["pagina"])) for e in evidencias if e.get("pagina") is not None}

    citacoes_invalidas: list[str] = []
    for m in _CITACAO.finditer(texto):
        for parte in m.group(1).split(";"):
            casou = _PARTE_CITACAO.match(parte)
            if not casou or (_norm(casou.group(1)), int(casou.group(2))) not in validas:
                citacoes_invalidas.append(f"({parte.strip()})")
    sem_citacoes = _CITACAO.sub(" ", texto)

    trechos_nao_encontrados: list[str] = []
    for m in _ASPAS.finditer(sem_citacoes):
        q = m.group(1) or m.group(2)
        fragmentos = [f for f in re.split(r"…|\[\.\.\.\]|\.\.\.", q) if _norm(f)]
        if fragmentos and not all(_norm(f) in base_trechos or _norm(f) in base_metricas for f in fragmentos):
            trechos_nao_encontrados.append(q.strip())
    sem_aspas = _ASPAS.sub(" ", sem_citacoes)
    sem_aspas = _DEZ_MIL.sub(" ", sem_aspas)

    numeros_nao_encontrados: list[str] = []
    n_verificados = 0
    for m in _NUMERO.finditer(sem_aspas):
        antes = sem_aspas[max(0, m.start() - 20):m.start()]
        if _ISENTOS.search(antes):
            continue
        token = m.group(0)
        n_verificados += 1
        if _P_LIMIAR.search(antes) and any(round(v, 6) in LIMIARES_P for v, _ in candidatos_do_numero(token)):
            continue
        pct = sem_aspas[m.end():m.end() + 3].lstrip().startswith("%")
        if not any(_confere(v, casas, permitidos, pct) for v, casas in candidatos_do_numero(token)):
            numeros_nao_encontrados.append(token)
    ok = not (numeros_nao_encontrados or citacoes_invalidas or trechos_nao_encontrados)
    return {"ok": ok, "numeros_verificados": n_verificados, "numeros_nao_encontrados": list(dict.fromkeys(numeros_nao_encontrados)),
            "citacoes_invalidas": list(dict.fromkeys(citacoes_invalidas)), "trechos_nao_encontrados": list(dict.fromkeys(trechos_nao_encontrados))}


def motivos_da_verificacao(v: dict) -> str:
    partes = []
    if v["numeros_nao_encontrados"]:
        partes.append("números que não estão nas métricas fornecidas: " + ", ".join(v["numeros_nao_encontrados"]))
    if v["citacoes_invalidas"]:
        partes.append("citações que não correspondem às evidências: " + ", ".join(v["citacoes_invalidas"]))
    if v["trechos_nao_encontrados"]:
        partes.append("trechos entre aspas que não aparecem nas evidências: " + "; ".join(f"“{t}”" for t in v["trechos_nao_encontrados"]))
    return "Conferência automática: " + " | ".join(partes) + "." if partes else ""


# ---------- geração ----------

def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _registrar_log(pasta: Path, linha: dict) -> None:
    saidas = pasta / "saidas"
    saidas.mkdir(parents=True, exist_ok=True)
    with (saidas / ARQUIVO_LOG).open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def gerar_paragrafo(db: Session, pasta: Path, modelo_id: str, instrucoes: str | None = None, provedor=None) -> dict:
    """Gera, confere e grava. Devolve ``{comentario_id, status, texto, verificacao, ...}``.

    Levanta LLMDesligado, KeyError (modelo inexistente), SemDados/AnaliseIndisponivel (sem dados) ou ErroLLM (provedor).
    """
    cfg = config.carregar()
    if not cfg["habilitado"]:
        raise LLMDesligado("A geração de parágrafos com LLM está desligada: ligue em Configurações.")
    modelo = paragrafos.buscar(pasta, modelo_id)
    dados = paragrafos.coletar(db, pasta, modelo["analise"])
    metricas, evidencias = dados["metricas"], dados["evidencias"]
    system = prompts.SYSTEM
    user = prompts.montar_usuario(modelo, metricas, evidencias, instrucoes)
    prompt_hash = _hash(system + "\n" + user)
    base_log = {"em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "analise": modelo["analise"],
                "modelo_paragrafo": modelo_id, "provedor": cfg["provedor"], "prompt_hash": prompt_hash, "prompt": user}
    prov = provedor or provedor_configurado(cfg)
    try:
        resp = prov.gerar(system, user)
    except ErroLLM as exc:
        _registrar_log(pasta, {**base_log, "erro": str(exc), "categoria": exc.categoria})
        raise
    texto = resp["texto"].strip()
    verificacao = verificar(texto, metricas, evidencias)
    status = "sugerido" if verificacao["ok"] else "revisar"
    llm = {"provedor": prov.nome, "modelo": resp["modelo"], "uso": resp.get("uso") or {}, "request_id": resp.get("request_id"),
           "prompt_hash": prompt_hash, "modelo_paragrafo": modelo_id, "instrucoes": (instrucoes or "").strip() or None}
    chave = f"llm|{modelo['analise']}|{modelo_id}|{_hash(user)}"
    c = db.scalars(select(Comentario).where(Comentario.chave == chave, Comentario.origem == "llm",
                                            Comentario.status.in_(("sugerido", "revisar")))).first()
    if c is None:
        c = Comentario(chave=chave, regra=("LLM:" + str(resp["modelo"]))[:100], texto=texto, status=status)
        db.add(c)
    c.regra = ("LLM:" + str(resp["modelo"]))[:100]
    c.origem = "llm"
    c.analise_tipo = modelo["analise"]
    c.texto = c.texto_original = texto
    c.status = status
    c.forca = None
    c.metricas_json = json.dumps({"origem": "llm", "llm": llm, "verificacao": verificacao}, ensure_ascii=False)
    c.hash_evidencia = _hash(json.dumps([[e["documento_id"], e["pagina"], e["trecho"]] for e in evidencias], ensure_ascii=False))
    antigas = list(c.evidencias)
    c.evidencias = [Evidencia(documento_id=e["documento_id"], pagina=e["pagina"], trecho=e["trecho"], termo=e["termo"], posicao=e["posicao"])
                    for e in evidencias]
    for e in antigas:
        db.delete(e)
    registrar_historico(c, "gerado_llm", provedor=prov.nome, modelo=resp["modelo"], prompt_hash=prompt_hash)
    if status == "revisar":
        registrar_historico(c, "revisar", status_anterior="sugerido", motivo=motivos_da_verificacao(verificacao))
    c.atualizado_em = agora()
    db.commit()
    db.refresh(c)
    _registrar_log(pasta, {**base_log, "modelo": resp["modelo"], "uso": llm["uso"], "request_id": llm["request_id"], "comentario_id": c.id,
                           "status": status, "verificacao_ok": verificacao["ok"], "segundos": resp.get("segundos")})
    return {"comentario_id": c.id, "status": status, "texto": texto, "verificacao": verificacao, "provedor": prov.nome,
            "modelo": resp["modelo"], "uso": llm["uso"], "request_id": llm["request_id"], "evidencias": len(evidencias)}
