"""15.8 - Keyness contra um corpus de referência externo (lista de frequências importada).

O corpus do projeto (inteiro ou um grupo/ano) é comparado com uma lista de frequências de referência com as mesmas
medidas da 6.1 (``keyness.py``): G² de 2 células com sinal, p (qui-quadrado, 1 g.l.), Log Ratio e %DIFF. O lado A é o
corpus do projeto e o lado B é a referência; ``c`` = tokens do lado A, ``d`` = tokens da referência.

**Nenhum corpus de referência é distribuído com o Raio-X** (licenças). O usuário importa o seu:

- ``lista``: CSV/TSV com ``termo;frequência`` por linha (separador ``;``, tabulação ou vírgula, detectado; cabeçalho
  opcional; números com separador de milhar ``1.234`` / ``1,234`` / ``1 234`` aceitos). O total de tokens da referência
  pode vir numa linha ``# total: 1000000`` ou no parâmetro ``total``. **Sem total, usa-se a soma da lista**, que é
  só uma aproximação quando a lista foi truncada (por exemplo, as 50 mil palavras mais frequentes de um corpus de 1
  bilhão): informe o total real sempre que souber, ou o Log Ratio e o G² saem distorcidos.
- ``textos``: pasta com arquivos ``.txt``/``.md``, contados aqui com o **mesmo tokenizador e lematizador** do projeto
  (``tokenizacao.py``), de modo que formas e lemas são diretamente comparáveis. O total vem da contagem.

Onde obter uma referência (o usuário precisa ter o direito de uso): listas de palavras de corpora gerais que o próprio
autor distribui (por exemplo, listas de frequência do COCA, do BNC, do Corpus do Português, do brWaC, do OpenSubtitles
ou do Wikipedia dump, conforme a licença de cada um), ou uma pasta de textos que o usuário já possui.

**A referência precisa ser comparável**: mesmo idioma e, de preferência, gênero próximo (comparar artigos
científicos com legendas de filme faz quase todo termo acadêmico parecer "chave"). A tela e o catálogo repetem o aviso.

Unidade
-------
- ``forma``: forma normalizada (minúscula, NFKC). Numa lista, é a coluna do arquivo.
- ``lema``: lista de **formas** é lematizada na importação com o lematizador do projeto (``Lematizador``, simplemma +
  exceções do projeto) no idioma da referência, **somando** as frequências das formas que viram o mesmo lema; a lista
  de formas original é guardada junto (``formas``), então a mesma referência serve para os dois modos.
  Limitação: a lematização da lista é feita sem contexto (uma forma ambígua recebe um só lema), e o corpus do projeto é
  lematizado com o idioma de cada documento; se a referência e o corpus não têm o mesmo idioma, a comparação é inválida.

OOV (palavras fora da referência)
---------------------------------
Termo do corpus ausente da referência tem b = 0: o Log Ratio usa 0,5 no lugar do zero (Hardie 2014) e o termo vem
marcado ``oov`` = verdadeiro (``so_em_a``). Com ``oov="excluir"`` esses termos saem da lista. Termos da referência
ausentes do corpus (a = 0) aparecem como sub-representados (lado B) quando passam nos filtros.

Armazenamento
-------------
Por projeto, em ``<projeto>/referencias/<id>.json`` (a pasta é fora de ``cache/``: não é apagada ao reprocessar o
corpus). Metadados: nome, fonte, idioma, tipo, tokens, tipos, data de importação.
"""
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import regex

from app.services.analises import dados, keyness
from app.services.palavras_vazias import COMPRIMENTO_MINIMO, token_vazio
from app.services.tokenizacao import IDIOMAS_SUPORTADOS, Lematizador, normalizar, tokenizar

PASTA = "referencias"
MAX_TERMOS_LISTA = 2_000_000
MAX_ARQUIVOS_TEXTO = 5000
EXTENSOES_TEXTO = {".txt", ".md", ".markdown"}
AVISO_COMPARAVEL = ("A referência precisa ser comparável ao corpus (mesmo idioma e, de preferência, gênero próximo): "
                    "uma referência de outro gênero faz o vocabulário técnico inteiro parecer palavra-chave.")
FERRAMENTA_EQUIVALENTE = "AntConc Keyword List com corpus de referência, WordSmith KeyWords, Sketch Engine Keywords"
METODOLOGIA = (
    "Corpus do projeto (A) contra lista de frequências importada (B): G² de 2 células (Rayson & Garside 2000), Log Ratio "
    "(Hardie 2014, 0,5 no lugar de contagem zero) e %DIFF (Gabrielatos & Marchi 2012), as mesmas medidas da 6.1. "
    "Tamanho de B = total informado (ou a soma da lista). Palavras fora da referência (OOV) têm b = 0."
)

_NUM = regex.compile(r"^\d[\d.,\s  ]*$")


class ReferenciaInvalida(ValueError):
    """Entrada de referência inválida (mensagem em português para a tela)."""


# ---------- armazenamento ----------

def pasta_referencias(pasta_projeto: Path) -> Path:
    return pasta_projeto / PASTA


def _id_seguro(nome: str) -> str:
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40]
    return base or "referencia"


def _caminho(pasta_projeto: Path, ref_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,60}", ref_id or ""):
        raise ReferenciaInvalida("Identificador de referência inválido.")
    return pasta_referencias(pasta_projeto) / f"{ref_id}.json"


def listar(pasta_projeto: Path) -> list[dict]:
    """Metadados das referências do projeto (sem as contagens)."""
    pasta = pasta_referencias(pasta_projeto)
    saida = []
    for arq in sorted(pasta.glob("*.json")) if pasta.is_dir() else []:
        try:
            saida.append(json.loads(arq.read_text(encoding="utf-8"))["meta"])
        except (ValueError, KeyError, OSError):
            continue
    return saida


def carregar(pasta_projeto: Path, ref_id: str) -> dict:
    arq = _caminho(pasta_projeto, ref_id)
    if not arq.is_file():
        raise FileNotFoundError(ref_id)
    return json.loads(arq.read_text(encoding="utf-8"))


def remover(pasta_projeto: Path, ref_id: str) -> bool:
    arq = _caminho(pasta_projeto, ref_id)
    if not arq.is_file():
        return False
    arq.unlink()
    return True


def _gravar(pasta_projeto: Path, meta: dict, formas: dict, lemas: dict | None) -> dict:
    pasta = pasta_referencias(pasta_projeto)
    pasta.mkdir(parents=True, exist_ok=True)
    base = _id_seguro(meta["nome"])
    ref_id, n = base, 2
    while (pasta / f"{ref_id}.json").exists():
        ref_id, n = f"{base}-{n}", n + 1
    meta = {**meta, "id": ref_id, "importada_em": datetime.now().isoformat(timespec="seconds"),
            "tipos_forma": len(formas), "tipos_lema": len(lemas) if lemas else None, "aviso": AVISO_COMPARAVEL}
    (pasta / f"{ref_id}.json").write_text(
        json.dumps({"meta": meta, "formas": formas, "lemas": lemas}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8", newline="\n")
    return meta


# ---------- importação ----------

def _numero(texto: str) -> int | None:
    t = (texto or "").strip().strip('"')
    if not t or not _NUM.match(t):
        return None
    t = re.sub(r"[\s  ]", "", t)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", t):  # milhar: 1.234.567 ou 1,234,567
        return int(re.sub(r"[.,]", "", t))
    if re.fullmatch(r"\d+[.,]\d+", t):  # decimal (frequência normalizada): arredonda
        return int(round(float(t.replace(",", "."))))
    return int(t) if t.isdigit() else None


def _separador(linhas: list[str]) -> str:
    for sep in ("\t", ";", ","):
        amostra = linhas[:20]
        if sum(1 for l in amostra if sep in l) * 2 >= len(amostra):
            return sep
    raise ReferenciaInvalida("Não foi possível detectar o separador: use 'termo;frequência' (ponto e vírgula, tabulação ou vírgula).")


def ler_lista(texto: str, total: int | None = None) -> tuple[dict[str, int], int | None]:
    """Interpreta o texto de uma lista ``termo;frequência``. Devolve (formas normalizadas -> frequência, total declarado).

    Linhas ``# ...`` são comentários (``# total: N`` declara o total); a 1ª linha é cabeçalho se a 2ª coluna não é número.
    Termos repetidos são somados (após normalização); frequência 0 é ignorada. Levanta ``ReferenciaInvalida``.
    """
    texto = texto.lstrip("﻿")
    declarado = total
    linhas = []
    for bruta in texto.splitlines():
        l = bruta.strip()
        if not l:
            continue
        if l.startswith("#"):
            m = re.match(r"#\s*(?:total|tamanho)\s*[:=]\s*([\d.,\s]+)$", l, re.I)
            if m and declarado is None:
                declarado = _numero(m.group(1))
            continue
        linhas.append(l)
    if not linhas:
        raise ReferenciaInvalida("A lista está vazia.")
    sep = _separador(linhas)
    freq: Counter = Counter()
    ignoradas = 0
    for i, l in enumerate(linhas):
        partes = [p.strip().strip('"') for p in l.split(sep)]
        if len(partes) < 2:
            ignoradas += 1
            continue
        n = _numero(partes[1])
        if n is None:
            if i == 0:
                continue  # cabeçalho
            ignoradas += 1
            continue
        termo = normalizar(partes[0])
        if not termo or n <= 0:
            continue
        freq[termo] += n
        if len(freq) > MAX_TERMOS_LISTA:
            raise ReferenciaInvalida(f"Lista grande demais (mais de {MAX_TERMOS_LISTA} termos).")
    if not freq:
        raise ReferenciaInvalida("Nenhuma linha 'termo;frequência' válida (a 2ª coluna precisa ser um número).")
    if ignoradas > len(linhas) * 0.2:
        raise ReferenciaInvalida(f"{ignoradas} de {len(linhas)} linhas sem frequência numérica: confira o formato 'termo;frequência'.")
    return dict(freq), declarado


def lematizar_lista(formas: dict[str, int], idioma: str, excecoes: dict | None = None) -> dict[str, int]:
    """Soma as frequências das formas que têm o mesmo lema (lematizador do projeto, no idioma da referência)."""
    lem = Lematizador(idioma, ativa=True, excecoes=excecoes)
    saida: Counter = Counter()
    for forma, n in formas.items():
        saida[lem.lema(forma, forma)] += n
    return dict(saida)


def _contar_texto(texto: str, lem: Lematizador, formas: Counter, lemas: Counter) -> int:
    total = 0
    cache: dict[str, str] = {}
    for f, _a, _z in tokenizar(texto):
        n = normalizar(f)
        if len(n) < COMPRIMENTO_MINIMO:
            continue
        l = cache.get(f)
        if l is None:
            l = cache[f] = lem.lema(f, n)
        formas[n] += 1
        lemas[l] += 1
        total += 1
    return total


def importar_lista(pasta_projeto: Path, nome: str, texto: str, idioma: str, fonte: str = "", total: int | None = None,
                   excecoes: dict | None = None) -> dict:
    """Importa uma lista de frequências (ver docstring do módulo). Devolve os metadados gravados."""
    _validar(nome, idioma)
    formas, declarado = ler_lista(texto, total)
    soma = sum(formas.values())
    tokens = declarado if declarado else soma
    if tokens < soma:
        raise ReferenciaInvalida(f"O total informado ({tokens}) é menor que a soma das frequências da lista ({soma}).")
    lemas = lematizar_lista(formas, idioma, excecoes)
    meta = {"nome": nome.strip(), "fonte": (fonte or "").strip(), "idioma": idioma, "tipo": "lista", "tokens": tokens,
            "soma_lista": soma, "total_declarado": bool(declarado),
            "nota_unidade": "Lista de formas: o modo 'lema' usa as formas lematizadas na importação (sem contexto)."}
    return _gravar(pasta_projeto, meta, formas, lemas)


def importar_textos(pasta_projeto: Path, nome: str, pasta_textos: Path, idioma: str, fonte: str = "",
                    excecoes: dict | None = None) -> dict:
    """Conta uma pasta de .txt/.md com o tokenizador e o lematizador do projeto e grava a referência."""
    _validar(nome, idioma)
    pasta_textos = Path(pasta_textos)
    if not pasta_textos.is_dir():
        raise ReferenciaInvalida(f"Pasta não encontrada: {pasta_textos}")
    arquivos = sorted(p for p in pasta_textos.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSOES_TEXTO)
    if not arquivos:
        raise ReferenciaInvalida("Nenhum arquivo .txt/.md na pasta.")
    if len(arquivos) > MAX_ARQUIVOS_TEXTO:
        raise ReferenciaInvalida(f"Pasta com arquivos demais ({len(arquivos)}; máximo {MAX_ARQUIVOS_TEXTO}).")
    lem = Lematizador(idioma, ativa=True, excecoes=excecoes)
    formas: Counter = Counter()
    lemas: Counter = Counter()
    total = 0
    for arq in arquivos:
        total += _contar_texto(arq.read_text(encoding="utf-8", errors="replace"), lem, formas, lemas)
    if total == 0:
        raise ReferenciaInvalida("Os arquivos não têm palavras.")
    meta = {"nome": nome.strip(), "fonte": (fonte or "").strip() or str(pasta_textos), "idioma": idioma, "tipo": "textos",
            "tokens": total, "soma_lista": total, "total_declarado": True, "arquivos": len(arquivos),
            "nota_unidade": "Contagem direta com o tokenizador e o lematizador do projeto (forma e lema)."}
    return _gravar(pasta_projeto, meta, dict(formas), dict(lemas))


def _validar(nome: str, idioma: str) -> None:
    if not (nome or "").strip():
        raise ReferenciaInvalida("Informe um nome para a referência.")
    if idioma not in IDIOMAS_SUPORTADOS:
        raise ReferenciaInvalida(f"Idioma '{idioma}' não suportado: use {', '.join(IDIOMAS_SUPORTADOS)}.")


# ---------- cálculo ----------

def calcular(voc: dict, metas: list[dict], filtro, referencia: dict, por: str = "lema", filtrar: bool = True,
             min_freq: int = 5, min_docs: int = 2, p: float = 0.01, bonferroni: bool = False, ordem: str = "ll",
             oov: str = "incluir", limite: int = 50, rotulo_corpus: str = "corpus") -> dict:
    """Palavras-chave do corpus (``metas``: documentos do escopo) contra ``referencia`` (arquivo carregado).

    ``por``: "lema" ou "forma". Levanta ValueError (parâmetros) ou ReferenciaInvalida (referência sem a unidade).
    """
    if por not in ("lema", "forma"):
        raise ValueError(f"Unidade inválida '{por}': use 'lema' ou 'forma'.")
    if ordem not in ("ll", "logratio"):
        raise ValueError(f"Ordenação inválida '{ordem}': use 'll' ou 'logratio'.")
    if oov not in ("incluir", "excluir"):
        raise ValueError("oov: use 'incluir' ou 'excluir'.")
    if not metas:
        raise ValueError("Nenhum documento no escopo.")
    lado = keyness._lado(voc, metas, filtro, "lema" if por == "lema" else "norma", filtrar)
    c = lado["tokens"]
    contagens_ref = referencia["lemas"] if por == "lema" else referencia["formas"]
    if not contagens_ref:
        raise ReferenciaInvalida("Esta referência não tem contagens por lema.")
    d = int(referencia["meta"]["tokens"])
    if c == 0 or d == 0:
        raise ValueError("Corpus ou referência sem tokens contados.")
    min_a = min(min_docs, lado["documentos"])

    def vazia(t: str) -> bool:
        return filtrar and token_vazio(t, t, filtro)

    termos = set(lado["freq"]) | {t for t in contagens_ref if len(t) >= COMPRIMENTO_MINIMO}
    testados = []
    for t in termos:
        if vazia(t):
            continue
        fa, fb = lado["freq"].get(t, 0), contagens_ref.get(t, 0)
        if fa + fb >= min_freq:
            testados.append((t, fa, fb))
    m = len(testados)
    limiar = p / m if bonferroni and m else p

    positivas, negativas = [], []
    for t, fa, fb in testados:
        med = keyness.medidas(fa, fb, c, d)
        if med["g2"] == 0 or not med["p"] < limiar:
            continue
        item = {"termo": t, **med, "docs_a": lado["df"].get(t, 0), "oov": fb == 0 and fa > 0,
                "p_bonferroni": min(1.0, med["p"] * m)}
        if med["g2"] > 0:
            if item["docs_a"] >= min_a and not (oov == "excluir" and item["oov"]):
                positivas.append(item)
        else:
            negativas.append(item)

    def chave_ordem(i):
        principal = abs(i["g2"]) if ordem == "ll" else abs(i["log_ratio"])
        return (-principal, -abs(i["g2"]), i["termo"])

    positivas.sort(key=chave_ordem)
    negativas.sort(key=chave_ordem)
    limite = max(0, limite)
    oov_corpus = sum(1 for t, fa, fb in testados if fb == 0 and fa > 0)
    ocorrencias_oov = sum(fa for t, fa, fb in testados if fb == 0)
    meta = referencia["meta"]
    return {
        "por": por,
        "corpus": {"valor": rotulo_corpus, "documentos": lado["documentos"], "tokens": c, "tipos": len(lado["freq"]),
                   "ids": [x["id"] for x in metas]},
        "referencia": {k: meta.get(k) for k in ("id", "nome", "fonte", "idioma", "tipo", "tokens", "soma_lista",
                                                "total_declarado", "arquivos", "importada_em", "tipos_forma", "tipos_lema",
                                                "nota_unidade")},
        "termos_testados": m, "limiar_p": limiar, "oov_testados": oov_corpus, "ocorrencias_oov": ocorrencias_oov,
        "total_positivas": len(positivas), "total_negativas": len(negativas),
        "positivas": positivas[:limite], "negativas": negativas[:limite],
        "avisos": _avisos(meta, c),
        "aviso_comparavel": AVISO_COMPARAVEL,
        "parametros": {"referencia": meta.get("id"), "por": por, "vazias": "filtrar" if filtrar else "manter",
                       "min_freq": min_freq, "min_docs": min_docs, "min_docs_efetivo": min_a, "p": p,
                       "bonferroni": bonferroni, "ordem": ordem, "oov": oov, "limite": limite},
        "metodologia": METODOLOGIA, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE,
    }


def _avisos(meta: dict, tokens_corpus: int) -> list[str]:
    avisos = []
    if meta.get("tipo") == "lista" and not meta.get("total_declarado"):
        avisos.append("Total da referência não informado: usada a soma da lista. Se a lista foi truncada, o tamanho real é "
                      "maior e as medidas ficam distorcidas; reimporte com o total.")
    if meta.get("tokens", 0) < tokens_corpus:
        avisos.append("A referência é menor que o corpus do projeto: os resultados são pouco estáveis.")
    return avisos


def escopo_metas(metas: list[dict], escopo: str, valor: str | None) -> tuple[list[dict], str]:
    """Documentos do escopo ("corpus", "grupo" ou "ano") e o rótulo exibido. Levanta ValueError."""
    if escopo not in ("corpus", "grupo", "ano"):
        raise ValueError(f"Escopo inválido '{escopo}': use corpus, grupo ou ano.")
    if escopo == "corpus":
        return list(metas), "corpus inteiro"
    sel = dados.filtrar_escopo(metas, escopo, valor)
    if not sel:
        raise ValueError(f"Nenhum documento em {escopo} '{valor}'.")
    return sel, f"{escopo}: {valor}"
