"""17.2 - Coleta automática por regras: para cada documento x item, candidatos -> extrator do tipo -> célula com valor, trechos, origem e confiança.

Candidatos (sem LLM), por item
-------------------------------
(a) **Seções** de ``onde_procurar`` (tipos da 3.1). Item sem palavras-chave: o texto da seção (mesma regra da 16.1, ``partes.preencher_secao``: frases
    inteiras até 1500 caracteres) -> tipo ``texto``; para os demais tipos as frases da seção são os candidatos.
(b) **Frases que casam as palavras-chave** (``termos.py``: lema, curinga ``*``, frases entre aspas, ``/regex/``; sem diferenciar caixa e acentos).
    Só frases "elegíveis" da 16.1 (6 a 90 palavras, sem URL/DOI, fora de legenda e de páginas de checklist). Com seções listadas, só valem as frases
    dentro delas; se o documento não tem nenhuma seção desse tipo (detecção falhou), vale qualquer parte. Nota da frase = termos distintos + 1 na seção
    listada + 0,1 por acerto. Porcentagens ("35%") só contam como número se o item fala de porcentagem/proporção/taxa.
(c) **Extratores por tipo** (``extratores.py``): numero, sim_nao, data, categoria/multipla (palavras-chave por categoria; empate -> "ambíguo").
    ``texto``: as ``max_trechos`` frases de maior nota (ordem do texto); o valor é a primeira frase, literal.
Item ligado a uma parte da planilha do corpus (``parte_planilha``): os candidatos são **exatamente** os trechos que a 16.1 acha
(``partes.analisar_documento``, via ``planilha.analise_do_documento``, sem copiar regra nenhuma); palavras-chave e seções do item não entram.
Seções fora do texto-base (agradecimentos, declarações, apêndice, referências) só são lidas quando o item as lista em ``onde_procurar``.

Célula: ``valor``, ``unidade``, ``trechos [{texto, pagina, secao}]``, ``origem`` (regra | padrao | llm | humano), ``confianca`` (0 a 1),
``status`` (sugerido | aceito | editado | rejeitado | nao_encontrado | nao_se_aplica), ``justificativa`` (nome da regra ou id do modelo), ``alternativas``.
**Sem evidência não há valor**: sem frase candidata a célula é ``nao_encontrado``.
"""
import hashlib
import re
from pathlib import Path

from app.services import parametros as svc_parametros
from app.services import tokenizacao as tk
from app.services.analises import dados as svc_dados
from app.services.analises import texto_documento
from app.services.coleta import extratores as E
from app.services.coleta import termos as T
from app.services.coleta.protocolo import QUALQUER
from app.services.corpus import llm_partes as L
from app.services.corpus import partes as P
from app.services.corpus import planilha as svc_planilha
from app.services.etapas.limpeza import caminho_limpo
from app.services.llm.cache_prompt import json_estavel
from app.services import ruido as svc_ruido
from app.services.texto import ler_qualidade

MOTOR_VERSAO = "1"
SECOES_FORA_DO_CORPO = ("referencias", "apendice", "agradecimentos", "declaracoes")
MIN_PALAVRAS_EXTRAS = 3
MAX_PALAVRAS_EXTRAS = 120
LIMITE_VALOR_TEXTO = 1500
_PEDE_PERCENTUAL = re.compile(r"%|(?<![A-Za-z])(?:percent[a-z]*|porcent[a-z]*|propor[a-z]*|taxa|share|rate|ratio|fra[çc][ãa]o)(?![A-Za-z])", re.IGNORECASE)


def agora() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


def hash_documento(pasta: Path, documento_id: int, excluir_ruido: bool) -> str | None:
    """Hash do conteúdo que alimenta a coleta (texto limpo + marcas de ruído + versão do motor); ``None`` se o documento não tem texto limpo."""
    c = caminho_limpo(pasta, documento_id)
    if not c.is_file():
        return None
    h = hashlib.sha256()
    h.update(c.read_bytes())
    if excluir_ruido:
        r = svc_ruido.caminho_ruido(pasta, documento_id)
        if r.is_file():
            h.update(r.read_bytes())
    h.update(f"|{int(excluir_ruido)}|{MOTOR_VERSAO}".encode())
    return h.hexdigest()[:20]


def hash_entrada(hash_doc: str, item: dict, hash_item_: str, params16: dict) -> str:
    base = hash_doc + "|" + hash_item_
    if item.get("parte_planilha"):
        base += "|" + json_estavel(params16)
    return hashlib.sha256(base.encode()).hexdigest()[:20]


class ContextoDocumento:
    """Texto, frases, índice de lemas e partes da 16.1 de um documento (tudo calculado sob demanda e guardado)."""

    def __init__(self, pasta: Path, doc, parametros: dict | None = None, excluir_ruido: bool | None = None):
        self.pasta = pasta
        self.doc = doc
        self.parametros = parametros if parametros is not None else svc_parametros.carregar(pasta)
        self.excluir_ruido = svc_ruido.excluir_ruido(self.parametros) if excluir_ruido is None else excluir_ruido
        self.params16 = svc_planilha.parametros_planilha(pasta)
        idioma = tk.idioma_do_documento(ler_qualidade(doc), self.parametros)
        lem = self.parametros.get("lematizacao") or {}
        self.lem = tk.Lematizador(idioma, ativa=bool(lem.get("ativa", True)), excecoes=lem.get("excecoes"))
        self.frases = texto_documento.frases_do_documento(pasta, doc.id, excluir_ruido=self.excluir_ruido)
        self.blocos = svc_dados.carregar_blocos(pasta, doc.id)
        self.checklist = P.paginas_de_checklist(self.frases or [])
        self._extras: dict[str, list[dict]] = {}
        self._indexadas: dict[int, T.FraseIndexada] = {}
        self._elegiveis: dict[int, bool] = {}
        self._termos: dict[str, list] = {}
        self._texto_doc = None
        self._analise16 = None
        self._analise16_lida = False

    # --- texto ---
    def texto_do_documento(self) -> "L.TextoDoDocumento":
        if self._texto_doc is None:
            self._texto_doc = L.TextoDoDocumento(self.blocos or [])
        return self._texto_doc

    def frases_extras(self, secao: str) -> list[dict]:
        """Frases de uma seção que o texto-base exclui (referências, apêndice, agradecimentos, declarações)."""
        if secao not in self._extras:
            lista = []
            if self.blocos and secao in SECOES_FORA_DO_CORPO:
                escolhidos = [b for b in self.blocos if b.get("secao") == secao and not b.get("incluir", True)]
                base = len(self.frases or []) + sum(len(v) for v in self._extras.values())
                corridas = texto_documento._unir_blocos([{**b, "incluir": True} for b in escolhidos], [b["texto"] for b in escolhidos])
                for corrida in corridas:
                    import bisect

                    offs = [o for o, _p in corrida["inicios"]]
                    for off, f in texto_documento.dividir_frases(corrida["texto"]):
                        k = max(0, bisect.bisect_right(offs, off) - 1)
                        lista.append({"i": base + len(lista), "texto": f, "pagina": corrida["inicios"][k][1], "secao": corrida["secao"],
                                      "titulo_secao": corrida["titulo"], "extra": True})
            self._extras[secao] = lista
        return self._extras[secao]

    def frases_para(self, secoes: list[str]) -> list[dict]:
        base = list(self.frases or [])
        for s in secoes:
            if s in SECOES_FORA_DO_CORPO:
                base += self.frases_extras(s)
        return base

    def elegivel(self, f: dict) -> bool:
        i = f["i"]
        if i not in self._elegiveis:
            if f.get("extra"):
                n = len(texto_documento.palavras_da_frase(f["texto"]))
                self._elegiveis[i] = MIN_PALAVRAS_EXTRAS <= n <= MAX_PALAVRAS_EXTRAS
            else:
                self._elegiveis[i] = P.elegivel(f) and f.get("pagina") not in self.checklist
        return self._elegiveis[i]

    def indexada(self, f: dict) -> T.FraseIndexada:
        i = f["i"]
        if i not in self._indexadas:
            self._indexadas[i] = T.indexar(f["texto"], self.lem)
        return self._indexadas[i]

    def indexar_texto(self, texto: str) -> T.FraseIndexada:
        return T.indexar(texto, self.lem)

    def termos(self, lista: list[str], chave: str) -> list:
        if chave not in self._termos:
            self._termos[chave] = T.compilar(lista, self.lem)
        return self._termos[chave]

    def analise16(self) -> dict | None:
        if not self._analise16_lida:
            self._analise16 = svc_planilha.analise_do_documento(self.pasta, self.doc.id, self.params16, self.excluir_ruido)
            self._analise16_lida = True
        return self._analise16


# ---------- candidatos ----------

def candidatos(ctx: ContextoDocumento, item: dict) -> list[dict]:
    """Frases candidatas do item (ver o docstring do módulo): ``{"f", "fi", "acertos", "na_secao", "nota"}``."""
    if item.get("parte_planilha"):
        return candidatos_16_1(ctx, item)
    secoes = item["onde_procurar"]
    qualquer = secoes == [QUALQUER]
    termos = ctx.termos(item["palavras_chave"], "item:" + item["id"])
    saida = []
    for f in ctx.frases_para(secoes):
        if not ctx.elegivel(f):
            continue
        na_secao = qualquer or f["secao"] in secoes
        fi = ctx.indexada(f)
        ac = T.acertos(termos, fi) if termos else []
        if termos and not ac:
            continue
        if not termos and not na_secao:
            continue
        nota = len({a.termo for a in ac}) + (1.0 if (na_secao and not qualquer) else 0.0) + 0.1 * len(ac)
        saida.append({"f": f, "fi": fi, "acertos": ac, "na_secao": na_secao, "nota": nota})
    if termos and not qualquer:
        # com seções listadas: só vale o que está nelas; se o documento não tem nenhuma seção desse tipo (detecção falhou), vale em qualquer parte
        if any(f["secao"] in secoes for f in ctx.frases_para(secoes)):
            saida = [c for c in saida if c["na_secao"]]
    return saida


def candidatos_16_1(ctx: ContextoDocumento, item: dict) -> list[dict]:
    analise = ctx.analise16() or {}
    parte = analise.get(item["parte_planilha"])
    saida = []
    if not parte:
        return saida
    termos = ctx.termos(item["palavras_chave"], "item:" + item["id"]) if item["tipo"] != "texto" else []
    for k, t in enumerate(parte["trechos"]):
        f = {"i": t.get("frase_i", k), "texto": t["texto"], "pagina": t.get("pagina"), "secao": t.get("secao"), "titulo_secao": t.get("titulo_secao"),
             "regra_16_1": t.get("regra"), "metodo_16_1": t.get("metodo"), "nota_16_1": t.get("nota"), "paginas": t.get("paginas")}
        fi = ctx.indexar_texto(t["texto"])
        saida.append({"f": f, "fi": fi, "acertos": T.acertos(termos, fi) if termos else [], "na_secao": True, "nota": float(t.get("nota") or 1.0), "origem_16_1": True})
    return saida


# ---------- células ----------

def trecho_da_frase(f: dict) -> dict:
    return {"texto": f["texto"], "pagina": f.get("pagina"), "secao": f.get("titulo_secao") or f.get("secao")}


def _nao_encontrado(motivo: str) -> dict:
    return {"valor": None, "unidade": None, "trechos": [], "origem": "regra", "confianca": 0.0, "status": "nao_encontrado", "justificativa": motivo, "alternativas": []}


def _celula(res: dict, origem: str) -> dict:
    trechos = res.get("trechos") or [trecho_da_frase(f) for f in res["frases"]]
    return {"valor": res["valor"], "unidade": res.get("unidade"), "trechos": trechos, "origem": origem, "confianca": res["confianca"],
            "status": "sugerido", "justificativa": res["justificativa"], "alternativas": res.get("alternativas") or []}


def calcular_item(ctx: ContextoDocumento, item: dict) -> tuple[dict, list[dict]]:
    """Célula do item neste documento (por regras) e os candidatos usados (reaproveitados pelo caminho LLM)."""
    tipo, mt = item["tipo"], int(item.get("max_trechos") or 3)
    secoes = item["onde_procurar"]
    sem_pistas = not item["palavras_chave"] and secoes == [QUALQUER] and not item.get("parte_planilha") and tipo != "categoria" and tipo != "multipla"
    if sem_pistas:
        return _nao_encontrado("o item não tem palavras-chave nem seção para procurar"), []
    if tipo in ("categoria", "multipla"):
        return _categoria(ctx, item, mt)
    cands = candidatos(ctx, item)
    termos_item = ctx.termos(item["palavras_chave"], "item:" + item["id"])
    if tipo == "numero":
        res = E.extrair_numero(cands, bool(termos_item), mt, bool(_PEDE_PERCENTUAL.search(f"{item['nome']} {item['definicao']} {' '.join(item['palavras_chave'])}")))
    elif tipo == "data":
        res = E.extrair_data(cands, bool(termos_item), mt)
    elif tipo == "sim_nao":
        res = E.extrair_sim_nao(cands, mt)
    else:
        res = _texto(ctx, item, cands, mt)
    if res is None:
        motivo = "nenhuma frase candidata" if not cands else "nenhum valor do tipo " + tipo + " nas frases candidatas"
        return _nao_encontrado(motivo), cands
    origem = "regra"
    if cands and all(c.get("origem_16_1") for c in cands) and tipo == "texto":
        origem = "padrao" if any(c["f"].get("metodo_16_1") == "padrao" for c in cands) else "regra"
    return _celula(res, origem), cands


def _texto(ctx: ContextoDocumento, item: dict, cands: list[dict], mt: int) -> dict | None:
    if item.get("parte_planilha"):
        if not cands:
            return None
        escolhidos = cands[:mt]
        trechos = [{"texto": c["f"]["texto"], "pagina": c["f"].get("pagina"), "secao": c["f"].get("titulo_secao") or c["f"].get("secao")} for c in escolhidos]
        regras = "; ".join(dict.fromkeys(str(c["f"].get("regra_16_1") or "") for c in escolhidos if c["f"].get("regra_16_1")))
        notas = [c["f"].get("nota_16_1") for c in escolhidos if c["f"].get("nota_16_1") is not None]
        conf = round(min(0.9, 0.3 + 0.1 * max(notas)), 2) if notas else 0.6
        return {"valor": _valor_texto(trechos), "unidade": None, "trechos": trechos, "frases": [], "confianca": conf,
                "justificativa": f"planilha do corpus (16.1): {regras}" if regras else "planilha do corpus (16.1)", "alternativas": []}
    secoes, termos = item["onde_procurar"], item["palavras_chave"]
    if not termos:  # só seção: texto da seção, como na 16.1
        frases = [f for f in ctx.frases_para(secoes) if len(f["texto"]) >= 15]
        trechos, regras = [], []
        for tipo in secoes:
            r = P.preencher_secao(frases, tipo, int(ctx.params16["max_caracteres"]))
            if r:
                trechos += [{"texto": t["texto"], "pagina": t["pagina"], "secao": t.get("titulo_secao") or t["secao"]} for t in r["trechos"]]
                regras.append(r["trechos"][0]["regra"])
            if len(trechos) >= mt:
                break
        if not trechos:
            return None
        trechos = trechos[:mt]
        return {"valor": _valor_texto(trechos), "unidade": None, "trechos": trechos, "frases": [], "confianca": 0.6, "justificativa": "; ".join(regras), "alternativas": []}
    if not cands:
        return None
    top = sorted(cands, key=lambda c: (-c["nota"], c["f"]["i"]))[:mt]
    top = sorted(top, key=lambda c: c["f"]["i"])
    nomes = sorted({a.termo for c in top for a in c["acertos"]})[:5]
    conf = round(min(0.85, 0.35 + 0.1 * max(c["nota"] for c in top)), 2)
    return {"valor": _valor_texto([trecho_da_frase(top[0]["f"])]), "unidade": None, "frases": [c["f"] for c in top], "confianca": conf,
            "justificativa": "palavras-chave: " + ", ".join(nomes) + (" (seção listada)" if any(c["na_secao"] and secoes != [QUALQUER] for c in top) else ""), "alternativas": []}


def _valor_texto(trechos: list[dict]) -> str:
    v = " ".join(t["texto"] for t in trechos[:1])
    return v if len(v) <= LIMITE_VALOR_TEXTO else v[:LIMITE_VALOR_TEXTO - 4] + " (…)"


def _categoria(ctx: ContextoDocumento, item: dict, mt: int) -> tuple[dict, list[dict]]:
    base = candidatos(ctx, item) if (item["palavras_chave"] or item["onde_procurar"] != [QUALQUER] or item.get("parte_planilha")) else None
    if base is None:  # sem pistas no item: todas as frases elegíveis do texto-base
        base = [{"f": f, "fi": ctx.indexada(f), "acertos": [], "na_secao": True, "nota": 0.0} for f in (ctx.frases or []) if ctx.elegivel(f)]
    por_cat: dict[str, list[dict]] = {}
    for cat in item["categorias"]:
        termos = ctx.termos(E.termos_da_categoria(cat), f"cat:{item['id']}:{cat['valor']}")
        if not termos:
            continue
        achadas = []
        for c in base:
            ac = T.acertos(termos, c["fi"])
            if ac:
                achadas.append({**c, "acertos": ac, "nota": c["nota"] + len({a.termo for a in ac})})
        if achadas:
            por_cat[cat["valor"]] = achadas
    res = E.extrair_categoria(por_cat, item["categorias"], item["tipo"] == "multipla", mt)
    if res is None:
        return _nao_encontrado("nenhuma palavra-chave de categoria nas frases candidatas" if base else "nenhuma frase candidata"), base
    return _celula(res, "regra"), base


# ---------- evidência de células decididas por humano ----------

def _sem_marcas(texto: str) -> str:
    import re

    return re.sub(r"\s*\(…\)\s*$", "", texto).strip()


def existe_no_texto(texto_doc: "L.TextoDoDocumento", texto: str) -> bool:
    """O trecho (sem a marca " (…)", só os primeiros 400 caracteres) existe literalmente no texto do documento (compactado, como na 16.2)?"""
    comp, _ = L.compactar(_sem_marcas(texto)[:400])
    return len(comp) >= 5 and comp in texto_doc.compacto


def evidencia_existe(texto_doc: "L.TextoDoDocumento", trechos: list[dict]) -> tuple[int, int]:
    """(trechos que ainda existem literalmente no documento, total de trechos)."""
    return sum(1 for t in trechos if existe_no_texto(texto_doc, t["texto"])), len(trechos)
