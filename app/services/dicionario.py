"""6.4 - Dicionário do projeto (codebook) em ``projetos/<slug>/dicionario.yaml``: leitura, validação e importação.

Formato::

    versao: 1
    categorias:
      - id: C1.1                      # obrigatório, único
        nome: IA como cofundador      # padrão: o id
        tema: T1                      # opcional (T1..T5 no codebook da MLR)
        tema_nome: Conceituação       # opcional
        descricao: regra de aplicação # opcional
        termos: ["agent*", "human oversight"]

Padrões (``termos``): lema (padrão) ou forma, em minúsculas; ``*`` casa qualquer sequência de caracteres; um padrão com
espaço é uma **frase** (palavras contíguas, cada uma com ``*`` possível). Nenhuma palavra-chave é inventada: a
importação do codebook cria categorias com ``termos = []`` quando a planilha não tem coluna de palavras-chave; elas
aparecem como "sem termos — preencha" e ficam fora das contagens até serem preenchidas.

Equivale aos dicionários do quanteda e às regras de codificação do KH Coder (contagem automática por categoria); **não**
é a codificação manual de trechos do ATLAS.ti/NVivo.
"""
import hashlib
import io
import re
import unicodedata
from pathlib import Path

import yaml

from app.services.tokenizacao import normalizar

ARQUIVO = "dicionario.yaml"
VERSAO = 1
MAX_PALAVRAS_PADRAO = 6
AVISO_SEM_TERMOS = "sem termos — preencha"
_TEMA = re.compile(r"^([A-Za-z]{1,3}\d+)\b\s*(.*)$")


class DicionarioInvalido(ValueError):
    """Dicionário com problemas; ``erros`` lista todos, na ordem em que aparecem."""

    def __init__(self, erros: list[str]):
        super().__init__("; ".join(erros))
        self.erros = erros


def caminho(pasta_projeto: Path) -> Path:
    return pasta_projeto / ARQUIVO


def hash_do_arquivo(pasta_projeto: Path) -> str:
    c = caminho(pasta_projeto)
    return hashlib.sha256(c.read_bytes()).hexdigest() if c.is_file() else ""


def vazio() -> dict:
    return {"versao": VERSAO, "categorias": []}


# ---------- validação ----------

def normalizar_padrao(padrao: str) -> str:
    """"Human  Oversight" -> "human oversight" (minúsculas, NFKC, espaços colapsados)."""
    return " ".join(normalizar(str(padrao)).split())


def _lista_de_termos(bruto) -> list[str]:
    if bruto is None:
        return []
    if isinstance(bruto, str):
        return [t for t in re.split(r"[;\n,]", bruto) if t.strip()]
    if isinstance(bruto, (list, tuple)):
        return [str(t) for t in bruto if t is not None and str(t).strip()]
    raise TypeError("'termos' deve ser uma lista (ou texto separado por vírgula).")


def validar(dados) -> dict:
    """Dicionário normalizado (ids sem espaços nas pontas, padrões em minúsculas e sem repetição).

    Levanta ``DicionarioInvalido`` com todos os problemas: id vazio/repetido, padrão só de curingas, frase longa demais."""
    erros: list[str] = []
    if dados is None:
        dados = vazio()
    if not isinstance(dados, dict):
        raise DicionarioInvalido(["O dicionário deve ser um objeto com a chave 'categorias'."])
    brutas = dados.get("categorias")
    if brutas is None:
        brutas = []
    if not isinstance(brutas, list):
        raise DicionarioInvalido(["'categorias' deve ser uma lista."])
    saida, vistos = [], set()
    for n, c in enumerate(brutas, 1):
        if not isinstance(c, dict):
            erros.append(f"Categoria {n}: deve ser um objeto com id, nome, tema, descricao e termos.")
            continue
        cid = str(c.get("id") if c.get("id") is not None else "").strip()
        if not cid:
            erros.append(f"Categoria {n}: 'id' é obrigatório.")
            continue
        if len(cid) > 80:
            erros.append(f"Categoria {cid[:20]}…: id com mais de 80 caracteres.")
        if cid in vistos:
            erros.append(f"Categoria {cid}: id repetido.")
            continue
        vistos.add(cid)
        try:
            termos_brutos = _lista_de_termos(c.get("termos"))
        except TypeError as e:
            erros.append(f"Categoria {cid}: {e}")
            continue
        termos: list[str] = []
        for t in termos_brutos:
            p = normalizar_padrao(t)
            palavras = p.split()
            if not p or any(w.strip("*") == "" for w in palavras):
                erros.append(f"Categoria {cid}: padrão inválido {t!r} (precisa de letras além do curinga).")
            elif len(palavras) > MAX_PALAVRAS_PADRAO:
                erros.append(f"Categoria {cid}: padrão {t!r} tem mais de {MAX_PALAVRAS_PADRAO} palavras.")
            elif p not in termos:
                termos.append(p)
        texto = lambda k: str(c.get(k) if c.get(k) is not None else "").strip()  # noqa: E731
        saida.append({"id": cid, "nome": texto("nome") or cid, "tema": texto("tema"), "tema_nome": texto("tema_nome"),
                      "descricao": texto("descricao"), "termos": termos})
    if erros:
        raise DicionarioInvalido(erros)
    return {"versao": VERSAO, "categorias": saida}


def com_marcas(dic: dict) -> dict:
    """Cópia com ``sem_termos`` (bool) e ``aviso`` em cada categoria (só para exibição; não vai para o arquivo)."""
    return {**dic, "categorias": [{**c, "sem_termos": not c["termos"], "aviso": AVISO_SEM_TERMOS if not c["termos"] else ""}
                                  for c in dic["categorias"]]}


def categorias_com_termos(dic: dict) -> list[dict]:
    return [c for c in dic["categorias"] if c["termos"]]


# ---------- arquivo ----------

def carregar(pasta_projeto: Path) -> dict:
    """Dicionário do projeto (vazio se não existir). Levanta ``DicionarioInvalido`` se o arquivo estiver quebrado."""
    c = caminho(pasta_projeto)
    if not c.is_file():
        return vazio()
    try:
        dados = yaml.safe_load(c.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DicionarioInvalido([f"dicionario.yaml não é um YAML válido: {e}"])
    return validar(dados)


def salvar(pasta_projeto: Path, dic: dict) -> dict:
    dic = validar(dic)
    pasta_projeto.mkdir(parents=True, exist_ok=True)
    texto = yaml.safe_dump(dic, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000)
    caminho(pasta_projeto).write_text(texto, encoding="utf-8", newline="\n")
    return dic


def ler_texto(texto: str) -> dict:
    """YAML ou JSON (JSON é YAML) -> dicionário validado."""
    try:
        return validar(yaml.safe_load(texto))
    except yaml.YAMLError as e:
        raise DicionarioInvalido([f"Texto inválido (YAML/JSON): {e}"])


def para_yaml(dic: dict) -> str:
    return yaml.safe_dump(validar(dic), allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000)


# ---------- importação do codebook (.xlsx) ----------

def _sem_acento(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch)).lower().strip()


_PAPEIS = {
    "id": lambda h: h in ("codigo", "cod", "code", "id", "id codigo", "id categoria") or h.startswith("codigo"),
    "nome": lambda h: h in ("rotulo", "nome", "label", "name", "categoria", "titulo"),
    "tema": lambda h: h in ("tema", "theme"),
    "descricao": lambda h: ("regra" in h or "descri" in h or "definic" in h) and "tema" not in h,
    "termos": lambda h: any(x in h for x in ("palavra", "keyword", "termos", "padroes", "padrao", "dicionario")),
}


def mapear_colunas(cabecalho: list) -> dict[str, int]:
    """Papel -> índice da coluna, pelo texto do cabeçalho (sem acento, minúsculas); cada coluna serve a um papel."""
    hs = [_sem_acento(h) if h is not None else "" for h in cabecalho]
    achados: dict[str, int] = {}
    for papel, teste in _PAPEIS.items():
        for j, h in enumerate(hs):
            if h and j not in achados.values() and teste(h):
                achados[papel] = j
                break
    return achados


def _tema(texto: str) -> tuple[str, str]:
    """"T1 Conceituação" -> ("T1", "Conceituação"); sem padrão T<n>: (texto, "")."""
    m = _TEMA.match(texto.strip())
    return (m.group(1).upper(), m.group(2).strip()) if m else (texto.strip(), "")


def importar_codebook(conteudo: bytes, existente: dict | None = None, aba: str | None = None,
                      modo: str = "mesclar") -> tuple[dict, dict]:
    """Lê o .xlsx do codebook e devolve ``(dicionario, relatorio)``.

    Aba: a pedida, ou a que tem "codebook" no nome, ou a primeira. Cabeçalho: a primeira das 10 primeiras linhas com
    coluna de código e de rótulo reconhecidas. Mapeia código -> id, rótulo -> nome, tema, regra/descrição -> descricao e,
    **se existir** coluna de palavras-chave (palavras-chave/keywords/termos/padrões), -> termos; sem ela, termos = [].
    ``modo`` "mesclar" (padrão): categorias já existentes mantêm seus termos (a planilha acrescenta os dela); "substituir": só o
    que vem da planilha. Levanta ``DicionarioInvalido`` se o arquivo ou as colunas não servirem."""
    if modo not in ("mesclar", "substituir"):
        raise DicionarioInvalido([f"Modo inválido '{modo}': use 'mesclar' ou 'substituir'."])
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as e:  # arquivo que não é xlsx
        raise DicionarioInvalido([f"Não foi possível ler o .xlsx: {type(e).__name__}: {e}"])
    try:
        nomes = wb.sheetnames
        if aba:
            if aba not in nomes:
                raise DicionarioInvalido([f"Aba '{aba}' não existe. Abas: {', '.join(nomes)}."])
            escolhida = aba
        else:
            escolhida = next((n for n in nomes if "codebook" in _sem_acento(n)), nomes[0])
        linhas = list(wb[escolhida].iter_rows(values_only=True))
    finally:
        wb.close()
    cab_i, colunas = None, {}
    for i, linha in enumerate(linhas[:10]):
        m = mapear_colunas(list(linha))
        if "id" in m and "nome" in m:
            cab_i, colunas = i, m
            break
    if cab_i is None:
        visto = [str(c) for c in (linhas[0] if linhas else []) if c is not None]
        raise DicionarioInvalido([f"Na aba '{escolhida}' não achei as colunas de código e rótulo. Cabeçalho: {', '.join(visto) or '(vazio)'}."])
    cabecalho = [str(c) if c is not None else "" for c in linhas[cab_i]]

    def cel(linha, papel):
        j = colunas.get(papel)
        v = linha[j] if j is not None and j < len(linha) else None
        return "" if v is None else str(v).strip()

    importadas: list[dict] = []
    for linha in linhas[cab_i + 1:]:
        cid = cel(linha, "id")
        if not cid:
            continue
        tema, tema_nome = _tema(cel(linha, "tema"))
        termos = _lista_de_termos(cel(linha, "termos")) if "termos" in colunas else []
        importadas.append({"id": cid, "nome": cel(linha, "nome") or cid, "tema": tema, "tema_nome": tema_nome,
                           "descricao": cel(linha, "descricao"), "termos": termos})
    antigas = {c["id"]: c for c in (existente or vazio())["categorias"]}
    novas, atualizadas = 0, 0
    resultado: dict[str, dict] = {}
    if modo == "mesclar":
        resultado.update({k: dict(v) for k, v in antigas.items()})
    for c in importadas:
        if c["id"] in antigas and modo == "mesclar":
            atualizadas += 1
            c = {**c, "termos": [*antigas[c["id"]]["termos"], *c["termos"]]}
        else:
            novas += 1
        resultado[c["id"]] = c
    dic = validar({"categorias": list(resultado.values())})
    relatorio = {
        "aba": escolhida, "linha_cabecalho": cab_i + 1,
        "colunas": {papel: cabecalho[j] for papel, j in colunas.items()},
        "tem_coluna_termos": "termos" in colunas,
        "categorias_importadas": len(importadas), "novas": novas, "atualizadas": atualizadas,
        "categorias_no_dicionario": len(dic["categorias"]),
        "sem_termos": sum(1 for c in dic["categorias"] if not c["termos"]),
        "aviso": (None if "termos" in colunas else
                  "A planilha não tem coluna de palavras-chave: as categorias foram criadas sem termos "
                  f"({AVISO_SEM_TERMOS}); nenhum termo foi inventado."),
    }
    return dic, relatorio
