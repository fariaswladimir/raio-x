"""17.2/17.3 - Armazenamento das células da coleta e decisões do revisor.

Arquivo ``projetos/<slug>/coleta_celulas.json``: ``{"versao", "celulas": {<arquivo do documento>: {<id do item>: célula}}, "ultima_execucao"}``.

Célula: ``valor``, ``unidade``, ``trechos [{texto, pagina, secao}]``, ``origem`` (regra | padrao | llm | humano), ``confianca``, ``status``
(sugerido | aceito | editado | rejeitado | nao_encontrado | nao_se_aplica), ``justificativa``, ``alternativas``, ``hash_doc``, ``hash_item``,
``hash_entrada`` (documento + definição do item: base da execução incremental), ``automatico`` (o que a máquina sugeriu, guardado na 1ª decisão humana:
base da concordância), ``revisar`` (motivo, se a evidência de uma célula já decidida deixou de existir no texto), ``definicao_mudou``, ``nota``.

Decisões (``decidir``): aceitar (sugerido -> aceito), editar valor (-> editado, origem humano), rejeitar, nao_se_aplica, desfazer (volta ao automático).
Uma execução nova **nunca** sobrescreve célula decidida (aceito, editado, rejeitado, nao_se_aplica): só confere se a evidência ainda existe.
"""
import json
import os
import re
import threading
from pathlib import Path

from app.services.coleta import extratores as E

ARQUIVO = "coleta_celulas.json"
STATUS = ("sugerido", "aceito", "editado", "rejeitado", "nao_encontrado", "nao_se_aplica")
DECIDIDOS = ("aceito", "editado", "rejeitado", "nao_se_aplica")
FINAIS = ("aceito", "editado")  # entram na exportação final (nao_se_aplica também, como "não se aplica")
ORIGENS = ("regra", "padrao", "llm", "humano")
ROTULO_STATUS = {"sugerido": "sugerido", "aceito": "aceito", "editado": "editado", "rejeitado": "rejeitado", "nao_encontrado": "não encontrado", "nao_se_aplica": "não se aplica"}
NAO_SE_APLICA = "não se aplica"

_TRAVAS: dict[str, threading.RLock] = {}
_TRAVA_GERAL = threading.Lock()


def trava(pasta: Path) -> threading.RLock:
    with _TRAVA_GERAL:
        return _TRAVAS.setdefault(str(pasta), threading.RLock())


def _vazio() -> dict:
    return {"versao": 1, "celulas": {}, "ultima_execucao": None}


def carregar(pasta: Path) -> dict:
    c = pasta / ARQUIVO
    if not c.is_file():
        return _vazio()
    try:
        d = json.loads(c.read_text(encoding="utf-8"))
    except ValueError:
        return _vazio()
    if not isinstance(d, dict) or not isinstance(d.get("celulas"), dict):
        return _vazio()
    return {**_vazio(), **d}


def salvar(pasta: Path, dados: dict) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    c = pasta / ARQUIVO
    tmp = c.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, c)


def celula_de(dados: dict, arquivo: str, item_id: str) -> dict | None:
    return (dados["celulas"].get(arquivo) or {}).get(item_id)


def decidida(cel: dict | None) -> bool:
    return bool(cel) and cel.get("status") in DECIDIDOS


def agora() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------- valores ----------

def valor_como_texto(cel: dict, tipo: str | None = None) -> str:
    """Valor da célula como texto (listas com "; ")."""
    if cel.get("status") == "nao_se_aplica":
        return NAO_SE_APLICA
    v = cel.get("valor")
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def validar_valor(item: dict, valor):
    """Valor digitado pelo revisor -> (valor normalizado, unidade). Levanta ValueError com mensagem em português."""
    tipo = item["tipo"]
    if valor is None or (isinstance(valor, str) and not valor.strip()) or valor == []:
        raise ValueError("Informe o valor.")
    if tipo == "categoria":
        for c in item["categorias"]:
            if str(c["valor"]).casefold() == str(valor).strip().casefold():
                return c["valor"], None
        raise ValueError(f"Valor fora da lista. Permitidos: {', '.join(c['valor'] for c in item['categorias'])}.")
    if tipo == "multipla":
        lista = valor if isinstance(valor, list) else re.split(r"[;|]", str(valor))
        permitidos = {str(c["valor"]).casefold(): c["valor"] for c in item["categorias"]}
        saida = []
        for x in lista:
            k = str(x).strip().casefold()
            if not k:
                continue
            if k not in permitidos:
                raise ValueError(f"'{x}' não está na lista. Permitidos: {', '.join(permitidos.values())}.")
            if permitidos[k] not in saida:
                saida.append(permitidos[k])
        if not saida:
            raise ValueError("Informe ao menos uma categoria.")
        return saida, None
    if tipo == "numero":
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return valor, None
        m = re.match(r"^\s*(" + E._N + r")(?:\s*(" + E._MULT + r"))?\s*(.*)$", str(valor), re.IGNORECASE)
        if not m:
            raise ValueError("Informe um número (ex.: 312, 1.200, 1,200 ou 2.5 mil).")
        un = m.group(3).strip()
        return E._aplicar_multiplicador(E.valor_numero(m.group(1)), m.group(2)), (un or None)
    if tipo == "sim_nao":
        k = str(valor).strip().casefold()
        if k in ("sim", "s", "yes", "y", "true"):
            return "sim", None
        if k in ("não", "nao", "n", "no", "false"):
            return "não", None
        raise ValueError("Use sim ou não.")
    if tipo == "data":
        v = str(valor).strip()
        if re.fullmatch(r"(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?(?:/(?:19|20)\d{2})?", v):
            return v, None
        achadas = E.datas_do_texto(v)
        if achadas:
            return achadas[0]["valor"], None
        raise ValueError("Informe uma data ou ano (ex.: 2025, 2025-03, 14/03/2025).")
    return str(valor).strip(), None


# ---------- decisões ----------

def _snapshot(cel: dict) -> dict:
    return {k: cel.get(k) for k in ("valor", "unidade", "trechos", "origem", "confianca", "justificativa", "status")}


def decidir(cel: dict, acao: str, item: dict, valor=None, nota: str | None = None, hash_doc: str | None = None, hash_item_: str | None = None) -> dict:
    """Aplica uma decisão do revisor à célula (modifica e devolve). Levanta ValueError (mensagem para a tela)."""
    if acao not in ("aceitar", "editar", "rejeitar", "nao_se_aplica", "desfazer"):
        raise ValueError("Ação inválida: use aceitar, editar, rejeitar, nao_se_aplica ou desfazer.")
    if acao == "desfazer":
        snap = cel.get("automatico")
        if not snap:
            raise ValueError("Esta célula não foi decidida: nada a desfazer.")
        cel.update({k: snap.get(k) for k in ("valor", "unidade", "trechos", "origem", "confianca", "justificativa")})
        cel["status"] = snap.get("status") or ("sugerido" if snap.get("valor") is not None else "nao_encontrado")
        cel.pop("automatico", None)
        cel.pop("decidido_em", None)
        cel["revisar"] = None
        return cel
    if "automatico" not in cel:
        cel["automatico"] = _snapshot(cel)
    if acao == "aceitar":
        if cel.get("status") == "nao_encontrado" or (cel.get("valor") is None and cel.get("status") != "nao_se_aplica"):
            raise ValueError("Não há valor para aceitar: use \"editar valor\" ou \"não se aplica\".")
        if cel.get("valor") == E.AMBIGUO:
            raise ValueError("O valor é ambíguo: use \"editar valor\" para escolher a categoria.")
        if cel.get("status") in ("rejeitado", "nao_se_aplica"):
            snap = cel["automatico"]
            cel.update({k: snap.get(k) for k in ("valor", "unidade", "trechos", "origem", "confianca", "justificativa")})
        cel["status"] = "aceito"
    elif acao == "editar":
        v, un = validar_valor(item, valor)
        cel["valor"], cel["unidade"] = v, un
        cel["status"], cel["origem"] = "editado", "humano"
        cel["justificativa"] = "valor digitado pelo revisor"
        cel["confianca"] = 1.0
        cel["sem_evidencia"] = not cel.get("trechos")
    elif acao == "rejeitar":
        cel["status"] = "rejeitado"
    else:
        cel["status"] = "nao_se_aplica"
    if nota is not None:
        cel["nota"] = nota.strip() or None
    cel["decidido_em"] = agora()
    cel["revisar"] = None
    cel["definicao_mudou"] = False
    if hash_doc:
        cel["hash_doc"] = hash_doc
    if hash_item_:
        cel["hash_item"] = hash_item_
    return cel
