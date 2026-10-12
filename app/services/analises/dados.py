"""Acesso compartilhado da Frente 5: documentos do escopo, consultas com curinga e cache de tokens.

Escopos aceitos (``escopo`` + ``valor``): ``corpus`` | ``documento`` (id) | ``grupo`` (nome) | ``ano``.

Cache em processo (LRU)
-----------------------
``carregar_tokens`` e ``carregar_blocos`` mantêm em memória os arquivos de ``cache/tokens/<id>.json`` e
``cache/limpo/<id>.json``, com chave (pasta, documento, mtime, tamanho): se o arquivo muda (pipeline
reexecutado) a entrada antiga deixa de ser usada. Os tokens de cada documento trazem também um índice
invertido (lema -> posições, norm -> posições) construído sob demanda (``indice_do_documento``).
As cadeias dos arrays são internadas (``sys.intern``) para poupar memória.

Com ``termos=True`` (por=termo, 4.3) o dicionário devolvido é uma cópia rasa dos tokens com o array paralelo ``termo``
(montado de ``cache/termos/<id>.json``; ver services/termos_compostos.py); a chave do cache inclui o mtime dos dois
arquivos e a cópia não herda os índices do dicionário base (têm donos de cache diferentes).
"""
import json
import re
import sys
import threading
from collections import OrderedDict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Documento
from app.services.etapas.limpeza import caminho_limpo
from app.services.etapas.linguistica import caminho_tokens
from app.services.orquestrador import condicao_ativo
from app.services.texto import ler_qualidade
from app.services.termos_compostos import array_termo, caminho_termos_doc
from app.services.tokenizacao import normalizar

ESCOPOS = ("corpus", "documento", "grupo", "ano")
SEM_ANO = "s/ano"
SEM_GRUPO = "sem grupo"
MAX_TERMOS = 6


# ---------- documentos ----------

def rotulo_do_documento(doc: Documento) -> str:
    """Rótulo curto para citação, como no protótipo: "001 · Kim 2026" (sem metadados: nome do arquivo)."""
    corpo = " ".join(str(x) for x in (doc.autor, doc.ano) if x)
    if doc.id_estudo and corpo:
        return f"{doc.id_estudo} · {corpo}"
    if doc.id_estudo or corpo:
        return doc.id_estudo or corpo
    return doc.arquivo.rsplit("/", 1)[-1].rsplit(".", 1)[0][:40]


def meta_do_documento(doc: Documento) -> dict:
    q = ler_qualidade(doc)
    lim = q.get("limpeza") or {}
    pct = round(100 * lim.get("palavras_corpo", 0) / lim["palavras_total"], 1) if lim.get("palavras_total") else None
    return {
        "id": doc.id, "arquivo": doc.arquivo, "rotulo": rotulo_do_documento(doc), "ano": doc.ano,
        "grupo": doc.grupo, "id_estudo": doc.id_estudo, "autor": doc.autor,
        "paginas": q.get("paginas"), "pct_corpo": pct,
    }


def documentos_do_corpus(db: Session, pasta_projeto: Path) -> list[dict]:
    """Documentos ativos que têm tokens, em ordem de arquivo (a ordem do corpus em todas as análises)."""
    consulta = select(Documento).where(condicao_ativo()).order_by(Documento.arquivo)
    return [meta_do_documento(d) for d in db.scalars(consulta) if caminho_tokens(pasta_projeto, d.id).is_file()]


def chave_ano(meta: dict) -> str:
    return str(meta["ano"]) if meta.get("ano") else SEM_ANO


def chave_grupo(meta: dict) -> str:
    return meta.get("grupo") or SEM_GRUPO


def filtrar_escopo(metas: list[dict], escopo: str = "corpus", valor: str | int | None = None) -> list[dict]:
    """Documentos do escopo. ``documento`` aceita o id; ``grupo``/``ano`` aceitam "sem grupo"/"s/ano"."""
    if escopo == "corpus":
        return list(metas)
    if escopo == "documento":
        return [m for m in metas if str(m["id"]) == str(valor)]
    if escopo == "grupo":
        return [m for m in metas if chave_grupo(m) == str(valor)]
    if escopo == "ano":
        return [m for m in metas if chave_ano(m) == str(valor)]
    raise ValueError(f"Escopo inválido '{escopo}'.")


def assinatura_metadados(metas: list[dict]) -> str:
    """Texto estável dos metadados que as análises usam (entra em chaves de cache)."""
    return repr([(m["id"], m["rotulo"], m["ano"], m["grupo"], m["paginas"], m["pct_corpo"]) for m in metas])


# ---------- consultas com curinga ----------

def compilar_consulta(consulta: str) -> list[dict]:
    """Consulta "a, b*, c" -> lista de itens ``{"texto", "exato" | "prefixo" | "regex"}``, já normalizados.

    ``*`` casa qualquer sequência de caracteres; um único ``*`` no final vira busca por prefixo (rápida).
    """
    itens = []
    for bruto in consulta.split(","):
        t = normalizar(bruto.strip())
        if not t or t.strip("*") == "":
            continue
        if "*" not in t:
            itens.append({"texto": t, "exato": t})
        elif t.endswith("*") and "*" not in t[:-1]:
            itens.append({"texto": t, "prefixo": t[:-1]})
        else:
            padrao = ".*".join(re.escape(p) for p in t.split("*"))
            itens.append({"texto": t, "regex": re.compile(f"^{padrao}$", re.DOTALL)})
    return itens


def casa(item: dict, chave: str) -> bool:
    if "exato" in item:
        return chave == item["exato"]
    if "prefixo" in item:
        return chave.startswith(item["prefixo"])
    return item["regex"].match(chave) is not None


def chaves_que_casam(itens: list[dict], chaves) -> list[str]:
    """Chaves (de um dicionário/índice) que casam com algum item da consulta, sem repetição.

    Prefixos (``agent*``) usam ``str.startswith`` em compreensão de lista e os demais curingas a regex
    compilada, para varrer os ~20 mil tipos de um documento em poucos milissegundos.
    """
    achadas: list[str] = [i["exato"] for i in itens if "exato" in i and i["exato"] in chaves]
    for item in itens:
        if "prefixo" in item:
            achadas.extend([c for c in chaves if c.startswith(item["prefixo"])])
        elif "regex" in item:
            achadas.extend([c for c in chaves if item["regex"].match(c)])
    return list(dict.fromkeys(achadas))


def termos_da_lista(termos: str) -> list[str]:
    """"a, b*,c" -> ["a", "b*", "c"] (sem repetições, no máximo MAX_TERMOS), já normalizados."""
    vistos: list[str] = []
    for t in compilar_consulta(termos):
        if t["texto"] not in vistos:
            vistos.append(t["texto"])
    return vistos[:MAX_TERMOS]


# ---------- cache de tokens, blocos e índices ----------

class _LRU:
    def __init__(self, maximo: int):
        self.maximo = maximo
        self._d: OrderedDict = OrderedDict()
        self._trava = threading.Lock()

    def obter(self, chave):
        with self._trava:
            v = self._d.get(chave)
            if v is not None:
                self._d.move_to_end(chave)
            return v

    def guardar(self, chave, valor):
        with self._trava:
            self._d[chave] = valor
            self._d.move_to_end(chave)
            while len(self._d) > self.maximo:
                self._d.popitem(last=False)

    def limpar(self):
        with self._trava:
            self._d.clear()


_TOKENS = _LRU(256)
_BLOCOS = _LRU(256)


def limpar_caches() -> None:
    _TOKENS.limpar()
    _BLOCOS.limpar()


def _marca(caminho: Path) -> tuple[int, int]:
    e = caminho.stat()
    return e.st_mtime_ns, e.st_size


def _ler_json(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


def carregar_tokens(pasta_projeto: Path, documento_id: int, termos: bool = False) -> dict | None:
    """Tokens do documento (cache LRU por mtime). Não altere os arrays devolvidos.

    ``termos=True`` acrescenta o array ``termo`` (sem arquivo lateral de termos compostos, ``termo`` = ``lema``)."""
    caminho = caminho_tokens(pasta_projeto, documento_id)
    if not caminho.is_file():
        return None
    chave = (str(pasta_projeto), documento_id, _marca(caminho))
    dados = _TOKENS.obter(chave)
    if dados is None:
        dados = _ler_json(caminho)
        for k in ("forma", "norm", "lema"):
            dados[k] = [sys.intern(x) for x in dados[k]]
        _TOKENS.guardar(chave, dados)
    if not termos:
        return dados
    lateral = caminho_termos_doc(pasta_projeto, documento_id)
    marca_t = _marca(lateral) if lateral.is_file() else None
    chave_t = (*chave, "termo", marca_t)
    com_termos = _TOKENS.obter(chave_t)
    if com_termos is None:
        ocorrencias = _ler_json(lateral)["ocorrencias"] if marca_t else []
        com_termos = {k: v for k, v in dados.items() if not k.startswith("_")}
        com_termos["termo"] = [sys.intern(x) for x in array_termo(dados, ocorrencias)]
        _TOKENS.guardar(chave_t, com_termos)
    return com_termos


def carregar_blocos(pasta_projeto: Path, documento_id: int) -> list[dict] | None:
    caminho = caminho_limpo(pasta_projeto, documento_id)
    if not caminho.is_file():
        return None
    chave = (str(pasta_projeto), documento_id, _marca(caminho))
    blocos = _BLOCOS.obter(chave)
    if blocos is None:
        blocos = _ler_json(caminho)["blocos"]
        _BLOCOS.guardar(chave, blocos)
    return blocos


def indice_do_documento(tokens: dict) -> dict:
    """Índice invertido {"lema": {lema: [posições]}, "norm": {norm: [posições]}} (+ "termo" se o array existir; só 1º token do trecho) (todos os tokens; filtre por ``incluir``).

    Guardado em ``tokens["_indice"]``: vive e morre junto com a entrada do cache de tokens.
    """
    indice = tokens.get("_indice")
    if indice is None:
        por_lema: dict[str, list[int]] = {}
        por_norm: dict[str, list[int]] = {}
        for i, (l, n) in enumerate(zip(tokens["lema"], tokens["norm"])):
            por_lema.setdefault(l, []).append(i)
            por_norm.setdefault(n, []).append(i)
        indice = tokens["_indice"] = {"lema": por_lema, "norm": por_norm}
    if "termo" in tokens and "termo" not in indice:
        por_termo: dict[str, list[int]] = {}
        for i, t in enumerate(tokens["termo"]):
            if t:  # "" = continuação de um termo composto
                por_termo.setdefault(t, []).append(i)
        indice["termo"] = por_termo
    return indice
