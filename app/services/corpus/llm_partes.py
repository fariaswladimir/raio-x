"""16.2 - Extração assistida por LLM das partes do artigo que as regras da 16.1 não acharam (opcional, desligada por padrão).

Fluxo: partes vazias ou fracas de um documento -> seções relevantes (tamanho limitado) + definição de cada parte -> o modelo devolve em
JSON até 3 **frases literais** do texto por parte -> cada frase é **conferida contra o texto do documento** -> o que não existe é
descartado -> o que existe vira **sugestão** ("LLM (modelo)", com página) que o usuário aceita ou rejeita célula a célula.
Só as aceitas entram na planilha (.xlsx); as demais aparecem na coluna "Sugestões LLM (não aceitas)".

Regra de conferência (``localizar_trecho``): o trecho devolvido e o texto do corpo são **compactados** (NFKC, caixa baixa, aspas e
travessões tipográficos normalizados, hífen suave removido e **todo espaço e hífen removidos**) e o trecho compactado precisa ser
uma **substring contígua** do texto compactado. Assim só diferenças de espaçamento e de hifenização (quebra de linha "infor-
mation" x "information") são toleradas (cobertura exigida: 100% do trecho; um limite de 0,9 de similaridade NÃO é usado para
palavras trocadas, que são rejeitadas). Frases com "..." / "…" no meio são recusadas. O texto salvo é o **do documento**
(não o devolvido pelo modelo) e a página é a do bloco onde o trecho começa. Sem LLM ligado (Frente 14, "Permitir geração com LLM")
a rota responde 409.
"""
import datetime
import json
import re
import unicodedata
from pathlib import Path

from app.services.corpus import partes as P
from app.services.llm import config, gerador
from app.services.llm.provedores import ErroLLM, provedor_configurado

ARQUIVO = "corpus_llm.json"
ROTULO_ORIGEM = "LLM (modelo)"
MAX_SUGESTOES = 3
MAX_CARACTERES_CONTEXTO = 9000
MIN_CARACTERES_TRECHO = 25
NOTA_FRACA = 3.0
PARTES_LLM = P.CHAVES

DEFINICOES = {
    "resumo": "o resumo (abstract) do documento",
    "introducao": "o texto da introdução",
    "objetivo": "o objetivo do estudo (o que os autores dizem que querem fazer, investigar ou propor)",
    "perguntas": "as perguntas de pesquisa ou hipóteses formuladas pelos autores",
    "referencial": "o referencial teórico / revisão de literatura",
    "metodo": "o método (desenho, procedimentos, técnicas de análise)",
    "dados": "os dados, a amostra ou o contexto empírico (quem/o quê foi estudado, de onde vêm os dados, tamanho da amostra)",
    "resultados": "os principais resultados",
    "discussao": "a discussão dos resultados",
    "conclusao": "a conclusão",
    "limitacoes": "as limitações reconhecidas pelos autores",
    "futuros": "as sugestões de trabalhos/pesquisas futuras",
    "contribuicoes": "as contribuições e implicações (teóricas, práticas, de política) declaradas pelos autores",
}
SECOES_RELEVANTES = {
    "resumo": ("resumo",), "introducao": ("introducao",), "objetivo": ("resumo", "introducao"),
    "perguntas": ("introducao", "referencial", "resumo"), "referencial": ("referencial",), "metodo": ("metodos",),
    "dados": ("metodos", "resumo", "introducao"), "resultados": ("resultados",), "discussao": ("discussao",),
    "conclusao": ("conclusao",), "limitacoes": ("discussao", "conclusao", "metodos"), "futuros": ("discussao", "conclusao"),
    "contribuicoes": ("introducao", "conclusao", "discussao", "resumo"),
}
SYSTEM = ("Você é um assistente de extração de informação de artigos científicos. Você NUNCA escreve texto próprio: apenas copia, "
          "palavra por palavra, frases que já existem no texto fornecido. Responda somente com JSON válido.")


# ---------- armazenamento das sugestões ----------

def caminho(pasta: Path) -> Path:
    return pasta / ARQUIVO


def carregar(pasta: Path) -> dict:
    c = caminho(pasta)
    if c.is_file():
        try:
            d = json.loads(c.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("documentos"), dict):
                return d
        except ValueError:
            pass
    return {"versao": 1, "documentos": {}}


def salvar(pasta: Path, dados: dict) -> None:
    caminho(pasta).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def sugestoes_do_documento(dados: dict, arquivo: str, parte: str) -> list[dict]:
    return (dados["documentos"].get(arquivo, {}).get(parte) or {}).get("sugestoes", [])


# ---------- conferência literal ----------

_TRACOS = "-‐‑‒–—−­"


def compactar(texto: str) -> tuple[str, list[int]]:
    """Forma compacta do texto + índice de cada caractere compacto no texto original."""
    saida: list[str] = []
    idx: list[int] = []
    for i, c in enumerate(texto):
        n = unicodedata.normalize("NFKC", c)
        for ch in n:
            if ch in _TRACOS or ch.isspace() or ch == "­":
                continue
            ch = {"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'", "`": "'"}.get(ch, ch).casefold()
            saida.append(ch)
            idx.append(i)
    return "".join(saida), idx


class TextoDoDocumento:
    """Blocos do corpo concatenados em forma compacta, com mapa de volta ao bloco, posição original e página."""

    def __init__(self, blocos: list[dict]):
        pares = [(i, b) for i, b in enumerate(blocos) if b.get("incluir", True) and b["texto"].strip()]
        self.blocos = [b for _i, b in pares]
        self.indice_original = [i for i, _b in pares]
        pedacos, self.mapa = [], []
        for bi, b in enumerate(self.blocos):
            comp, idx = compactar(b["texto"])
            pedacos.append(comp)
            self.mapa.extend((bi, i) for i in idx)
        self.compacto = "".join(pedacos)

    def localizar(self, trecho: str) -> dict | None:
        trecho = re.sub(r"^\s*\[(?:pp?\.\s*[\d\-–, ]+)\]\s*", "", trecho.strip())
        if re.search(r"\.\.\.|…|\[\.\.\.\]", trecho.strip(" .…")):
            return None
        comp, _ = compactar(trecho)
        if len(comp) < MIN_CARACTERES_TRECHO:
            return None
        pos = self.compacto.find(comp)
        if pos < 0:
            return None
        (b0, o0), (b1, o1) = self.mapa[pos], self.mapa[pos + len(comp) - 1]
        if b0 == b1:
            original = self.blocos[b0]["texto"][o0:o1 + 1]
        else:
            original = self.blocos[b0]["texto"][o0:] + " " + " ".join(self.blocos[k]["texto"] for k in range(b0 + 1, b1)) \
                + (" " if b1 > b0 + 1 else "") + self.blocos[b1]["texto"][:o1 + 1]
        return {"texto": re.sub(r"\s+", " ", original).strip(), "pagina": self.blocos[b0]["pagina"], "secao": self.blocos[b0]["secao"],
                "titulo_secao": self.blocos[b0].get("titulo_secao"), "bloco": self.indice_original[b0], "offset": o0}


def conferir_trechos(devolvidos: dict, blocos: list[dict]) -> tuple[dict, dict]:
    """Confere as frases por parte. Devolve ``({parte: [trecho verificado]}, {"aceitos": n, "descartados": [..]})``."""
    doc = TextoDoDocumento(blocos)
    ok: dict[str, list[dict]] = {}
    descartados: list[dict] = []
    for parte, lista in devolvidos.items():
        if parte not in PARTES_LLM or not isinstance(lista, list):
            continue
        vistos: set[str] = set()
        for t in lista[:MAX_SUGESTOES + 2]:
            if not isinstance(t, str) or not t.strip():
                continue
            loc = doc.localizar(t)
            if loc is None:
                descartados.append({"parte": parte, "trecho": t[:200], "motivo": "não existe no documento"})
                continue
            if loc["texto"] in vistos:
                continue
            vistos.add(loc["texto"])
            ok.setdefault(parte, []).append(loc)
        ok[parte] = ok.get(parte, [])[:MAX_SUGESTOES]
    return ok, {"aceitos": sum(len(v) for v in ok.values()), "descartados": descartados}


# ---------- pedido ao modelo ----------

def partes_fracas(analise: dict) -> list[str]:
    """Partes vazias ou, nas de padrão, com a melhor nota abaixo de ``NOTA_FRACA``."""
    fracas = []
    for chave in P.CHAVES:
        parte = analise.get(chave)
        if not parte or not parte["trechos"]:
            fracas.append(chave)
        elif parte["metodo"] == "padrao" and max((t["nota"] or 0) for t in parte["trechos"]) < NOTA_FRACA:
            fracas.append(chave)
    return fracas


def montar_contexto(frases: list[dict], partes: list[str], limite: int = MAX_CARACTERES_CONTEXTO) -> str:
    tipos = []
    for p in partes:
        for t in SECOES_RELEVANTES[p]:
            if t not in tipos:
                tipos.append(t)
    por_tipo = {t: [f for f in frases if f["secao"] == t] for t in tipos}
    ativos = [t for t in tipos if por_tipo[t]]
    if not ativos:  # sem seções detectadas: começo do corpo
        ativos = ["*"]
        por_tipo["*"] = frases
    cota = max(600, limite // len(ativos))
    escolhidas: list[dict] = []
    for t in ativos:
        total = 0
        for f in por_tipo[t]:
            if total + len(f["texto"]) > cota:
                break
            escolhidas.append(f)
            total += len(f["texto"]) + 8
    escolhidas.sort(key=lambda f: f["i"])
    return "\n".join(f"[p. {f['pagina']}] {f['texto']}" if f["pagina"] else f["texto"] for f in escolhidas)


def montar_pedido(contexto: str, partes: list[str]) -> str:
    itens = "\n".join(f'- "{p}": {DEFINICOES[p]}' for p in partes)
    return (f"TEXTO DO DOCUMENTO (trechos, cada um com a página no início):\n\n{contexto}\n\n---\n"
            f"Para cada parte abaixo, devolva até {MAX_SUGESTOES} frases COPIADAS LITERALMENTE do texto acima (sem o prefixo [p. N], sem "
            f"alterar nenhuma palavra, sem resumir, sem traduzir) que respondam à parte. Se o texto não tiver nada que responda, devolva uma "
            f"lista vazia. Não invente.\n\nPARTES:\n{itens}\n\n"
            f"Responda SOMENTE com um objeto JSON no formato {{\"<parte>\": [\"frase literal 1\", \"frase literal 2\"]}} com estas chaves: "
            f"{', '.join(partes)}.")


def ler_json(texto: str) -> dict:
    t = texto.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise ValueError("resposta sem JSON")
    d = json.loads(t[i:j + 1])
    if not isinstance(d, dict):
        raise ValueError("JSON não é um objeto")
    return d


class LLMDesligado(Exception):
    """A geração com LLM está desligada na configuração global (padrão)."""


def extrair_documento(pasta: Path, db_doc_arquivo: str, documento_id: int, analise: dict, blocos: list[dict], frases: list[dict],
                      partes: list[str] | None = None, provedor=None) -> dict:
    """Pede ao LLM as partes fracas do documento, confere e guarda as sugestões. Levanta ``LLMDesligado`` e ``ErroLLM``."""
    cfg = config.carregar()
    if not cfg["habilitado"]:
        raise LLMDesligado("A extração com LLM está desligada: ligue \"Permitir geração com LLM\" em Configurações.")
    alvo = [p for p in (partes or partes_fracas(analise)) if p in PARTES_LLM]
    if not alvo:
        return {"documento_id": documento_id, "partes": [], "sugestoes": 0, "descartados": [], "mensagem": "Nenhuma parte fraca ou vazia."}
    prov = provedor or provedor_configurado(cfg)
    contexto = montar_contexto(frases, alvo)
    pedido = montar_pedido(contexto, alvo)
    resp = prov.gerar(SYSTEM, pedido)
    try:
        devolvido = ler_json(resp["texto"])
    except ValueError as exc:
        gerador._registrar_log(pasta, {"em": _agora(), "extracao_partes": arquivo_seguro(db_doc_arquivo), "erro": f"JSON inválido: {exc}"})
        raise ErroLLM("O modelo não devolveu um JSON válido.", "formato") from exc
    ok, rel = conferir_trechos({k: v for k, v in devolvido.items() if k in alvo}, blocos)
    dados = carregar(pasta)
    doc = dados["documentos"].setdefault(db_doc_arquivo, {})
    modelo = str(resp.get("modelo") or getattr(prov, "modelo", "") or "")
    n = 0
    for parte in alvo:
        anteriores = [s for s in (doc.get(parte) or {}).get("sugestoes", []) if s["status"] != "sugerida"]  # mantém aceitas/rejeitadas
        existentes = {s["texto"] for s in anteriores}
        novas = []
        for t in ok.get(parte, []):
            if t["texto"] in existentes:
                continue
            novas.append({"texto": t["texto"], "pagina": t["pagina"], "secao": t["secao"], "titulo_secao": t.get("titulo_secao"),
                          "status": "sugerida", "origem": ROTULO_ORIGEM, "modelo": modelo, "provedor": prov.nome, "em": _agora()})
        doc[parte] = {"sugestoes": anteriores + novas}
        n += len(novas)
    salvar(pasta, dados)
    gerador._registrar_log(pasta, {"em": _agora(), "extracao_partes": arquivo_seguro(db_doc_arquivo), "provedor": prov.nome, "modelo": modelo,
                                   "partes": alvo, "aceitos_na_conferencia": rel["aceitos"], "descartados": len(rel["descartados"]),
                                   "prompt": pedido, "uso": resp.get("uso")})
    return {"documento_id": documento_id, "partes": alvo, "sugestoes": n, "descartados": rel["descartados"], "modelo": modelo}


def arquivo_seguro(a: str) -> str:
    return a.replace("\\", "/")


def _agora() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def decidir(pasta: Path, arquivo: str, parte: str, acao: str, indices: list[int] | None = None) -> list[dict]:
    """Aceita, rejeita ou volta a "sugerida" as sugestões da célula (todas, ou as de ``indices``)."""
    status = {"aceitar": "aceita", "rejeitar": "rejeitada", "limpar": "sugerida"}[acao]
    dados = carregar(pasta)
    lista = (dados["documentos"].get(arquivo, {}).get(parte) or {}).get("sugestoes")
    if lista is None:
        raise KeyError("Não há sugestões de LLM nesta célula.")
    for i, s in enumerate(lista):
        if indices is None or i in indices:
            s["status"] = status
    salvar(pasta, dados)
    return lista
