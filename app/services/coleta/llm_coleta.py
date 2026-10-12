"""17.2(d) - Coleta com LLM (opcional; só roda com "Permitir geração com LLM" ligado na Frente 14).

O modelo **não escreve texto próprio**: recebe a definição de cada item, o tipo, as categorias permitidas e frases candidatas do documento
(tamanho limitado) e devolve JSON ``{"<id>": {"valor": ..., "trechos": ["frase literal", ...], "confianca": 0-1}}``. Cada resposta é conferida:

- cada trecho precisa existir **literalmente** no documento (mesma conferência da 16.2, ``llm_partes.TextoDoDocumento.localizar``: só diferenças de
  espaço e de hifenização passam); o texto guardado é o do documento e a página é a do bloco onde o trecho começa; trecho inventado é descartado;
- ``categoria``: o valor tem de ser uma das categorias do item (sem diferenciar caixa/acentos), senão a resposta é recusada; ``multipla``: só as
  categorias válidas ficam (nenhuma -> recusada);
- ``numero``: o número tem de aparecer em um dos trechos devolvidos (pt-BR ou en; com milhar e multiplicador);
- ``sim_nao``: "sim" ou "não" (sinônimos aceitos), com pelo menos um trecho verificado;
- ``data``: o ano do valor tem de aparecer em um trecho;
- ``texto``: o valor é o próprio trecho verificado (o texto livre do modelo é ignorado).
Valor sem nenhum trecho verificado é descartado ("não encontrado"). Resultado: origem ``llm``, ``justificativa`` = id do modelo, status ``sugerido``.

Prompt caching: o ``system`` tem dois blocos estáveis (instruções + protocolo inteiro em JSON de chaves ordenadas, ``cache_control`` no último);
tudo que varia (documento e frases) vai na mensagem do usuário. Ollama e provedores compatíveis recebem o mesmo texto achatado, sem cache.
"""
import re
import unicodedata

from app.services.coleta import extratores as E
from app.services.corpus import llm_partes as L
from app.services.llm.cache_prompt import blocos_system, chave_natural, json_estavel

SYSTEM = ("Você é um assistente de coleta de dados para revisões sistemáticas. Você NUNCA escreve texto próprio como evidência: apenas copia, "
          "palavra por palavra, frases que já existem nos trechos fornecidos. Valores de categoria devem ser exatamente um dos permitidos no protocolo. "
          "Responda somente com JSON válido.")
MAX_CONTEXTO_ITEM = 2200
MAX_CONTEXTO_TOTAL = 9000
ITENS_POR_CHAMADA = 4


def protocolo_estavel(itens: list[dict]) -> str:
    """JSON do protocolo (só o que o modelo precisa, chaves e itens em ordem fixa): é o prefixo em cache."""
    saida = []
    for i in sorted(itens, key=lambda x: chave_natural(x["id"])):
        d = {"id": i["id"], "nome": i["nome"], "definicao": i["definicao"], "tipo": i["tipo"], "max_trechos": i.get("max_trechos", 3)}
        if i["tipo"] in ("categoria", "multipla"):
            d["categorias"] = [{"valor": c["valor"], "definicao": c.get("definicao") or ""} for c in i["categorias"]]
        saida.append(d)
    return json_estavel(saida)


def montar_system(itens: list[dict]) -> list[dict]:
    return blocos_system(SYSTEM, "PROTOCOLO DE COLETA (JSON, estável):\n" + protocolo_estavel(itens))


def contexto_do_item(cands: list[dict], limite: int = MAX_CONTEXTO_ITEM) -> str:
    """Frases candidatas (maior nota primeiro, até ``limite`` caracteres), em ordem do texto, com [p. N]."""
    escolhidas, total = [], 0
    for c in sorted(cands, key=lambda c: (-c["nota"], c["f"]["i"])):
        t = c["f"]["texto"]
        if total + len(t) > limite and escolhidas:
            break
        escolhidas.append(c["f"])
        total += len(t) + 8
    escolhidas.sort(key=lambda f: f["i"])
    return "\n".join(f"[p. {f['pagina']}] {f['texto']}" if f.get("pagina") else f["texto"] for f in escolhidas)


def montar_usuario(rotulo_doc: str, itens: list[dict], contextos: dict[str, str]) -> str:
    blocos = []
    for i in itens:
        extra = ""
        if i["tipo"] in ("categoria", "multipla"):
            extra = " Categorias permitidas: " + "; ".join(c["valor"] for c in i["categorias"]) + "."
        blocos.append(f"### ITEM {i['id']} ({i['tipo']}): {i['nome']}.{extra}\n{contextos.get(i['id']) or '(sem frases candidatas)'}")
    ids = ", ".join(i["id"] for i in itens)
    return (f"DOCUMENTO: {rotulo_doc}\n\nFRASES CANDIDATAS POR ITEM (cada linha começa com a página, [p. N]; copie as frases SEM esse prefixo):\n\n" + "\n\n".join(blocos) +
            "\n\n---\nPara cada item acima, responda com um objeto JSON no formato "
            "{\"<id>\": {\"valor\": ..., \"trechos\": [\"frase copiada literalmente\"], \"confianca\": 0.0}} com as chaves: " + ids + ". "
            "Regras do valor: categoria = exatamente uma categoria permitida; multipla = lista de categorias permitidas; numero = número; "
            "sim_nao = \"sim\" ou \"não\"; data = AAAA, AAAA-MM ou AAAA-MM-DD; texto = null. "
            "Em \"trechos\", no máximo o número de trechos do protocolo, frases copiadas palavra por palavra. Sem evidência: {\"valor\": null, \"trechos\": []}.")


# ---------- conferência ----------

def _sa(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)).lower().strip()


_SIM = {"sim", "yes", "true", "s", "y", "verdadeiro", "1"}
_NAO = {"nao", "no", "false", "n", "falso", "0"}
_NUM_VALOR = re.compile(r"^\s*(" + E._N + r")(?:\s*(" + E._MULT + r"))?", re.IGNORECASE)


def _numero_do_valor(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    m = _NUM_VALOR.match(str(v))
    if not m:
        return None
    return E._aplicar_multiplicador(E.valor_numero(m.group(1)), m.group(2))


def _numeros_nos_trechos(trechos: list[str]) -> set[float]:
    achados: set[float] = set()
    for t in trechos:
        for m in re.finditer(E._NUM, t):
            achados.add(float(E.valor_numero(m.group(0))))
        for n in E.numeros_do_texto(t):
            achados.add(float(n["valor"]))
    return achados


def _canonica(valor, categorias: list[dict]) -> str | None:
    k = _sa(valor)
    for c in categorias:
        if _sa(c["valor"]) == k:
            return c["valor"]
    return None


def conferir_resposta(item: dict, resp, doc: "L.TextoDoDocumento") -> tuple[dict | None, list[dict]]:
    """Confere a resposta do modelo para um item. Devolve ``(célula parcial ou None, descartes)``; descarte = ``{motivo, trecho?, valor?}``."""
    descartes: list[dict] = []
    if not isinstance(resp, dict):
        return None, [{"motivo": "resposta fora do formato"}]
    brutos = resp.get("trechos")
    if isinstance(brutos, str):
        brutos = [brutos]
    if not isinstance(brutos, list):
        brutos = []
    verificados, vistos = [], set()
    for t in brutos[:int(item.get("max_trechos") or 3) + 2]:
        if not isinstance(t, str) or not t.strip():
            continue
        loc = doc.localizar(t)
        if loc is None:
            descartes.append({"motivo": "trecho não existe no documento", "trecho": t[:200]})
            continue
        if loc["texto"] in vistos:
            continue
        vistos.add(loc["texto"])
        verificados.append(loc)
    verificados = verificados[:int(item.get("max_trechos") or 3)]
    valor, unidade = resp.get("valor"), None
    tipo = item["tipo"]
    if not verificados:
        return None, descartes + ([{"motivo": "sem nenhum trecho verificado", "valor": str(valor)[:80]}] if valor not in (None, "", []) else [])
    textos = [v["texto"] for v in verificados]
    if tipo == "categoria":
        canon = _canonica(valor, item["categorias"]) if not isinstance(valor, (list, dict)) else None
        if canon is None:
            return None, descartes + [{"motivo": "categoria fora da lista permitida", "valor": str(valor)[:80]}]
        valor = canon
    elif tipo == "multipla":
        lista = valor if isinstance(valor, list) else [x for x in re.split(r"[;|]", str(valor or "")) if x.strip()]
        boas = []
        for x in lista:
            c = _canonica(x, item["categorias"])
            if c is None:
                descartes.append({"motivo": "categoria fora da lista permitida", "valor": str(x)[:80]})
            elif c not in boas:
                boas.append(c)
        if not boas:
            return None, descartes
        valor = boas
    elif tipo == "numero":
        n = _numero_do_valor(valor)
        if n is None:
            return None, descartes + [{"motivo": "valor não é um número", "valor": str(valor)[:80]}]
        if not any(abs(float(n) - x) <= 1e-9 * max(1.0, abs(x)) for x in _numeros_nos_trechos(textos)):
            return None, descartes + [{"motivo": "o número não aparece nos trechos devolvidos", "valor": str(valor)[:80]}]
        valor = n
        un = resp.get("unidade")
        unidade = str(un).strip()[:40] if isinstance(un, str) and un.strip() else None
    elif tipo == "sim_nao":
        k = _sa(valor)
        if k in _SIM:
            valor = "sim"
        elif k in _NAO:
            valor = "não"
        else:
            return None, descartes + [{"motivo": "valor não é sim/não", "valor": str(valor)[:80]}]
    elif tipo == "data":
        v = str(valor or "").strip()
        anos = re.findall(r"(?:19|20)\d{2}", v)
        if not anos:
            return None, descartes + [{"motivo": "valor não é uma data/ano", "valor": v[:80]}]
        todo = " ".join(textos)
        if not all(a in todo for a in anos):
            return None, descartes + [{"motivo": "o ano não aparece nos trechos devolvidos", "valor": v[:80]}]
        valor = v
    else:  # texto: o valor é o trecho verificado
        valor = textos[0]
    try:
        conf = round(min(1.0, float(resp.get("confianca"))), 2)
    except (TypeError, ValueError):
        conf = 0.0
    if conf <= 0:
        conf = 0.6  # confiança informada pelo modelo ausente ou zerada: valor neutro (a conferência literal é que vale)
    trechos = [{"texto": v["texto"], "pagina": v.get("pagina"), "secao": v.get("titulo_secao") or v.get("secao")} for v in verificados]
    return {"valor": valor, "unidade": unidade, "trechos": trechos, "confianca": conf}, descartes


def ler_resposta(texto: str) -> dict:
    """JSON da resposta como ``{id: {valor, trechos}}``. Aceita também uma lista de objetos de uma chave só (``[{"a": {...}}, {"b": {...}}]``,
    comum em modelos pequenos) ou itens com ``id`` dentro. Levanta ValueError se não houver JSON utilizável."""
    import json as _json

    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.IGNORECASE)
    if not t.startswith("["):
        try:
            return L.ler_json(texto)
        except ValueError:
            pass
    i, j = t.find("["), t.rfind("]")
    if i < 0 or j < i:
        raise ValueError("resposta sem JSON")
    lista = _json.loads(t[i:j + 1])
    if not isinstance(lista, list):
        raise ValueError("JSON não é um objeto")
    saida: dict = {}
    for o in lista:
        if not isinstance(o, dict):
            continue
        if "id" in o and isinstance(o.get("id"), str):
            saida[o["id"]] = {k: v for k, v in o.items() if k != "id"}
        else:
            saida.update({k: v for k, v in o.items() if isinstance(v, dict)})
    if not saida:
        raise ValueError("JSON sem itens")
    return saida
