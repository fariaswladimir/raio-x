"""17.1 - Protocolo de coleta: itens (uma linha cada), regra das 2 frases, versionamento, importação e exportação.

Cada **item** do protocolo é uma linha com os campos:

    id             código curto (letras, dígitos, ``_ . -``; até 24 caracteres; único no protocolo)
    nome           rótulo curto do item
    definicao      **obrigatória, no máximo 2 frases** (regra do usuário, ver abaixo)
    tipo           texto | categoria | multipla | numero | sim_nao | data
    categorias     (categoria/multipla) valores permitidos; cada um com definição opcional de **no máximo 1 frase** e palavras-chave opcionais
    onde_procurar  lista de tipos de seção da 3.1 (resumo, introducao, referencial, metodos, resultados, discussao, conclusao, ...) ou "qualquer"
    palavras_chave termos e padrões: ``*`` curinga, frases entre aspas (ou com espaço), ``/regex/``
    obrigatorio    o item precisa ter valor (a tela destaca os que ficaram sem)
    max_trechos    quantos trechos de evidência guardar por célula (1 a 10; padrão 3)
    parte_planilha (opcional) chave de uma parte da planilha do corpus (16.1): o item usa as **mesmas regras** da 16.1 (``corpus/partes.py``)

Regra das frases (``contar_frases``)
------------------------------------
O texto é dividido em frases em cada ``.`` ``?`` ``!`` ``…`` seguido de espaço (ou do fim do texto). Não encerra a frase:
- ``.`` seguido de letra minúscula (a frase continua);
- ``.`` depois de abreviação conhecida (``e.g.``, ``i.e.``, ``et al.``, ``p.``, ``pp.``, ``n.``, ``vs.``, ``cf.``, ``fig.``, ``eq.``, ``dr.``, ``prof.``,
  ``ca.``...; "etc." encerra se a próxima palavra é maiúscula) ou depois de **inicial** isolada (``J. Smith``); "no."/"nº." só contam como
  abreviação diante de um número;
- ``.`` dentro de números e siglas (``3.5``, ``U.S.``): só encerra quando há espaço depois.
``?`` e ``!`` seguidos de espaço sempre encerram. Fragmento sem pontuação final conta como uma frase. Mais de 2 frases na definição do item (ou
mais de 1 na definição de uma categoria) é **recusado ao salvar e ao importar**, com sugestão de corte (as 2 primeiras frases); acima de
~40 palavras na definição sai só um **aviso** (não recusa).

Versionamento (como ``parametros.json``): ``projetos/<slug>/protocolo_coleta.json`` com ``versao_protocolo``; salvar com conteúdo diferente sobe a
versão e arquiva a anterior em ``protocolo_coleta_historico/protocolo_coleta_v<N>.json``.

Importação (CSV, XLSX, tabela Markdown): uma linha por item; cabeçalhos em português ou inglês, sem diferenciar caixa e acentos (id, nome/item/name,
definição/definition, tipo/type, categorias/categories, onde procurar/where, palavras-chave/keywords, obrigatório/required). Células de lista aceitam
``;`` ``,`` ``|`` ou quebra de linha; categorias: ``valor [palavra, palavra]: definição`` (colchetes e definição opcionais).
"""
import csv
import datetime
import hashlib
import io
import json
import re
import shutil
import unicodedata
from pathlib import Path

from app.services.analises.texto_documento import ABREVIACOES
from app.services.corpus import partes as P
from app.services.exportar.planilhas import csv_bytes
from app.services.limpeza_texto import TIPOS as TIPOS_SECAO
from app.services.llm.cache_prompt import json_estavel

ARQUIVO = "protocolo_coleta.json"
HISTORICO = "protocolo_coleta_historico"
TIPOS = ("texto", "categoria", "multipla", "numero", "sim_nao", "data")
ROTULO_TIPO = {"texto": "texto", "categoria": "categoria (uma)", "multipla": "múltipla escolha", "numero": "número", "sim_nao": "sim/não", "data": "data/ano"}
MAX_FRASES_DEFINICAO = 2
MAX_FRASES_CATEGORIA = 1
AVISO_PALAVRAS = 40
MAX_TRECHOS_PADRAO = 3
QUALQUER = "qualquer"
SECOES_VALIDAS = tuple(TIPOS_SECAO) + (QUALQUER,)
CAMPOS_HASH = ("definicao", "tipo", "categorias", "onde_procurar", "palavras_chave", "max_trechos", "parte_planilha")

# Abreviações que não encerram a frase (as da divisão de frases dos documentos, sem as palavras comuns, mais algumas).
_ABREV_EXTRA = frozenset({"n", "ca", "aprox", "art", "arts", "pag", "pág", "págs", "pags", "ph.d", "a.c", "d.c", "s.a", "ltda", "ibid", "viz", "esp"})
_ABREV_COMUNS = frozenset({"etc", "ed", "eds", "co", "st", "ex", "resp", "inc", "ltd", "ref", "refs"})
ABREVIACOES_DEFINICAO = (frozenset(ABREVIACOES) | _ABREV_EXTRA) - _ABREV_COMUNS
_ANTES_DE_NUMERO = ("no", "nº", "n°")
_FIM = re.compile(r"([.?!…]+)([\"'”’)\]]*)(?=\s|$)")
_ABRE = re.compile(r"[\"'“‘(\[]*[A-ZÀ-ÖØ-Þ0-9]")


class ProtocoloInvalido(ValueError):
    """Protocolo com erro (não salvo). ``erros`` = lista de problemas por item/campo."""

    def __init__(self, erros: list[dict]):
        self.erros = erros
        super().__init__(resumo_erros(erros))


def resumo_erros(erros: list[dict]) -> str:
    return "; ".join(f"{e.get('item') or 'linha ' + str(e.get('linha', '?'))}: {e['mensagem']}" for e in erros[:6]) + (" ..." if len(erros) > 6 else "")


# ---------- regra das frases ----------

def _sem_acento(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)).lower().strip()


def _eh_abreviacao(antes: str, resto: str) -> bool:
    m = re.search(r"([^\W\d_][\w.]*)$", antes)
    if not m:
        return False
    palavra = m.group(1).lower().rstrip(".")
    if palavra in _ANTES_DE_NUMERO:
        return bool(re.match(r"\s*\d", resto))
    if palavra in ABREVIACOES_DEFINICAO:
        return True
    return len(m.group(1)) == 1 and m.group(1).isupper()  # inicial: "J. Smith"


def dividir_frases(texto: str) -> list[str]:
    """Frases da definição (regra no docstring do módulo). Texto vazio -> lista vazia."""
    t = " ".join(str(texto or "").split())
    if not t:
        return []
    saida, ini = [], 0
    for m in _FIM.finditer(t):
        pont, fim = m.group(1), m.end()
        resto = t[fim:].lstrip()
        if not resto:
            break  # fim do texto: fechado abaixo
        if pont[0] in ".…":
            if not _ABRE.match(resto):
                continue
            if pont == "." and _eh_abreviacao(t[ini:m.start(1)], resto):
                continue
        saida.append(t[ini:fim].strip())
        ini = fim
    ultimo = t[ini:].strip()
    if ultimo:
        saida.append(ultimo)
    return saida


def contar_frases(texto: str) -> int:
    return len(dividir_frases(texto))


def contar_palavras(texto: str) -> int:
    return len(re.findall(r"\S+", str(texto or "")))


def sugestao_de_corte(texto: str, maximo: int = MAX_FRASES_DEFINICAO) -> str:
    return " ".join(dividir_frases(texto)[:maximo])


def regra_das_frases() -> dict:
    """Dados da regra para a tela (o contador ao vivo usa as mesmas abreviações)."""
    return {"max_frases_definicao": MAX_FRASES_DEFINICAO, "max_frases_categoria": MAX_FRASES_CATEGORIA, "aviso_palavras": AVISO_PALAVRAS,
            "abreviacoes": sorted(ABREVIACOES_DEFINICAO), "abreviacoes_antes_de_numero": list(_ANTES_DE_NUMERO),
            "descricao": "Conta frases em . ? ! … seguidos de espaço; ignora abreviações (e.g., i.e., et al., p., n., vs.), iniciais (J. Smith), decimais e ponto seguido de minúscula."}


# ---------- listas ----------

_FECHA_ASPAS = {"\"": "\"", "“": "”"}


def _separar(texto: str, separadores: str) -> list[str]:
    """Divide em itens por ``separadores`` fora de aspas e de /regex/."""
    saida, atual, fecha, regex = [], [], None, False
    for i, c in enumerate(texto):
        if fecha:
            atual.append(c)
            if c == fecha:
                fecha = None
        elif regex:
            atual.append(c)
            if c == "/" and (i + 1 == len(texto) or texto[i + 1] in separadores + " "):
                regex = False
        elif c in _FECHA_ASPAS:
            fecha = _FECHA_ASPAS[c]
            atual.append(c)
        elif c == "/" and not "".join(atual).strip():
            regex = True
            atual.append(c)
        elif c in separadores:
            saida.append("".join(atual))
            atual = []
        else:
            atual.append(c)
    saida.append("".join(atual))
    return [s.strip() for s in saida if s.strip()]


SEPARADORES_LISTA = ";|\n,"


def _lista(v, separadores: str = SEPARADORES_LISTA) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return _separar(str(v), separadores)


_CAT = re.compile(r"^(?P<v>[^\[:]+?)\s*(?:\[(?P<k>[^\]]*)\])?\s*(?::\s*(?P<d>.*))?$", re.S)


def parse_categoria(entrada) -> dict | None:
    """``"Survey [questionário, survey]: Pesquisa por questionário."`` -> ``{valor, definicao, palavras_chave}``."""
    if isinstance(entrada, dict):
        valor = str(entrada.get("valor") or entrada.get("nome") or "").strip()
        if not valor:
            return None
        return {"valor": valor, "definicao": " ".join(str(entrada.get("definicao") or "").split()), "palavras_chave": _lista(entrada.get("palavras_chave"))}
    texto = str(entrada or "").strip()
    if not texto:
        return None
    m = _CAT.match(texto)
    if not m:
        return {"valor": texto, "definicao": "", "palavras_chave": []}
    return {"valor": m.group("v").strip(), "definicao": " ".join((m.group("d") or "").split()), "palavras_chave": _lista(m.group("k")) if m.group("k") else []}


def parse_categorias(v) -> list[dict]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        itens = list(v)
    else:
        texto = str(v)
        sep = "\n" if "\n" in texto.strip() else ("|" if "|" in texto else ";")
        itens = _separar(texto, sep)
    saida, vistos = [], set()
    for e in itens:
        c = parse_categoria(e)
        if c and _sem_acento(c["valor"]) not in vistos:
            vistos.add(_sem_acento(c["valor"]))
            saida.append(c)
    return saida


def categorias_para_texto(categorias: list[dict]) -> str:
    partes = []
    for c in categorias:
        s = c["valor"]
        if c.get("palavras_chave"):
            s += " [" + ", ".join(c["palavras_chave"]) + "]"
        if c.get("definicao"):
            s += ": " + c["definicao"]
        partes.append(s)
    return " | ".join(partes)


_SINONIMOS_SECAO = {
    "abstract": "resumo", "resumen": "resumo", "summary": "resumo", "introduction": "introducao", "introduccion": "introducao", "intro": "introducao",
    "literature": "referencial", "literature review": "referencial", "background": "referencial", "revisao": "referencial", "referencial teorico": "referencial",
    "method": "metodos", "methods": "metodos", "metodo": "metodos", "metodologia": "metodos", "methodology": "metodos", "materiais e metodos": "metodos",
    "results": "resultados", "resultado": "resultados", "findings": "resultados", "discussion": "discussao", "discusion": "discussao",
    "conclusion": "conclusao", "conclusions": "conclusao", "conclusiones": "conclusao", "conclusoes": "conclusao",
    "references": "referencias", "referencia": "referencias", "appendix": "apendice", "acknowledgements": "agradecimentos", "acknowledgments": "agradecimentos",
    "declarations": "declaracoes", "funding": "declaracoes", "any": QUALQUER, "anywhere": QUALQUER, "todas": QUALQUER, "todos": QUALQUER, "*": QUALQUER,
    "title": "titulo", "other": "outro",
}
_SINONIMOS_TIPO = {
    "texto": "texto", "text": "texto", "livre": "texto", "free text": "texto", "string": "texto",
    "categoria": "categoria", "category": "categoria", "categorica": "categoria", "categorical": "categoria", "escolha unica": "categoria", "unica": "categoria", "single": "categoria",
    "multipla": "multipla", "multiple": "multipla", "multi": "multipla", "multipla escolha": "multipla", "multiple choice": "multipla", "multi-select": "multipla",
    "numero": "numero", "number": "numero", "numeric": "numero", "numerico": "numero", "quantidade": "numero", "inteiro": "numero",
    "sim_nao": "sim_nao", "sim/nao": "sim_nao", "sim nao": "sim_nao", "sim-nao": "sim_nao", "yes/no": "sim_nao", "yes no": "sim_nao",
    "boolean": "sim_nao", "booleano": "sim_nao", "bool": "sim_nao", "binario": "sim_nao",
    "data": "data", "date": "data", "ano": "data", "year": "data", "data/ano": "data",
}


def normalizar_tipo(v) -> str | None:
    k = _sem_acento(v)
    return _SINONIMOS_TIPO.get(k) or _SINONIMOS_TIPO.get(k.replace("_", " "))


def normalizar_secoes(v) -> list[str]:
    saida = []
    for s in _lista(v):
        k = _sem_acento(s)
        k = _SINONIMOS_SECAO.get(k, k)
        if k and k not in saida:
            saida.append(k)
    return saida


def parse_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return _sem_acento(v) in ("1", "sim", "s", "yes", "y", "true", "verdadeiro", "x", "obrigatorio", "required", "v")


# ---------- normalização e validação de um item ----------

def _erro(item_id, campo, codigo, mensagem, **extra) -> dict:
    return {"item": item_id, "campo": campo, "codigo": codigo, "gravidade": "erro", "mensagem": mensagem, **extra}


def _aviso(item_id, campo, codigo, mensagem, **extra) -> dict:
    return {"item": item_id, "campo": campo, "codigo": codigo, "gravidade": "aviso", "mensagem": mensagem, **extra}


def validar_definicao(definicao: str, item_id=None) -> list[dict]:
    """Problemas da definição: vazia, mais de 2 frases (erro com sugestão de corte), mais de ~40 palavras (aviso)."""
    d = (definicao or "").strip()
    if not d:
        return [_erro(item_id, "definicao", "definicao_vazia", "A definição é obrigatória (1 ou 2 frases).")]
    saida = []
    n = contar_frases(d)
    if n > MAX_FRASES_DEFINICAO:
        saida.append(_erro(item_id, "definicao", "frases_excedidas",
                           f"A definição tem {n} frases; o máximo é {MAX_FRASES_DEFINICAO}. Sugestão de corte: \"{sugestao_de_corte(d)}\"",
                           frases=n, sugestao=sugestao_de_corte(d)))
    p = contar_palavras(d)
    if p > AVISO_PALAVRAS:
        saida.append(_aviso(item_id, "definicao", "definicao_longa", f"A definição tem {p} palavras (acima de ~{AVISO_PALAVRAS}): prefira frases curtas.", palavras=p))
    return saida


def normalizar_item(bruto: dict, linha: int | None = None) -> tuple[dict, list[dict]]:
    """Item normalizado (sempre devolvido, mesmo com erro) + problemas. ``bruto`` aceita os nomes de campo em português."""
    item_id = str(bruto.get("id") or "").strip()
    problemas: list[dict] = []

    def err(campo, codigo, msg, **ex):
        problemas.append(_erro(item_id or None, campo, codigo, msg, linha=linha, **ex))

    if not item_id:
        err("id", "id_vazio", "O item precisa de um id (código curto).")
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,23}", item_id):
        err("id", "id_invalido", "Id inválido: use letras, dígitos, _ . - (até 24 caracteres, sem espaços).")
    nome = " ".join(str(bruto.get("nome") or "").split())
    if not nome:
        err("nome", "nome_vazio", "O item precisa de um nome.")
    definicao = " ".join(str(bruto.get("definicao") or "").split())
    for p in validar_definicao(definicao, item_id or None):
        problemas.append({**p, "linha": linha})
    tipo_bruto = bruto.get("tipo")
    tipo = normalizar_tipo(tipo_bruto) if str(tipo_bruto or "").strip() else "texto"
    if tipo is None:
        err("tipo", "tipo_invalido", f"Tipo inválido '{tipo_bruto}'. Use: {', '.join(TIPOS)}.")
        tipo = "texto"
    categorias = parse_categorias(bruto.get("categorias")) if tipo in ("categoria", "multipla") else []
    if tipo in ("categoria", "multipla"):
        if len(categorias) < 2:
            err("categorias", "categorias_faltando", "Informe pelo menos 2 categorias permitidas.")
        for c in categorias:
            n = contar_frases(c["definicao"])
            if n > MAX_FRASES_CATEGORIA:
                err("categorias", "frases_excedidas_categoria",
                    f"A definição da categoria \"{c['valor']}\" tem {n} frases; o máximo é {MAX_FRASES_CATEGORIA}. "
                    f"Sugestão de corte: \"{sugestao_de_corte(c['definicao'], 1)}\"", frases=n, sugestao=sugestao_de_corte(c["definicao"], 1), categoria=c["valor"])
    elif bruto.get("categorias") and str(bruto.get("categorias")).strip() not in ("", "[]"):
        problemas.append(_aviso(item_id or None, "categorias", "categorias_ignoradas",
                                "Categorias só valem para os tipos categoria e múltipla escolha: foram ignoradas.", linha=linha))
    secoes = normalizar_secoes(bruto.get("onde_procurar")) or [QUALQUER]
    ruins = [s for s in secoes if s not in SECOES_VALIDAS]
    if ruins:
        err("onde_procurar", "secao_invalida", f"Seção desconhecida: {', '.join(ruins)}. Use: {', '.join(SECOES_VALIDAS)}.")
        secoes = [s for s in secoes if s in SECOES_VALIDAS] or [QUALQUER]
    if QUALQUER in secoes:
        secoes = [QUALQUER]
    palavras = _lista(bruto.get("palavras_chave"))
    for k in palavras:
        if k.startswith("/") and k.endswith("/") and len(k) > 2:
            try:
                re.compile(k[1:-1])
            except re.error as exc:
                err("palavras_chave", "regex_invalida", f"Expressão regular inválida {k}: {exc}.")
    try:
        mt = int(bruto.get("max_trechos") or MAX_TRECHOS_PADRAO)
    except (TypeError, ValueError):
        mt = MAX_TRECHOS_PADRAO
        err("max_trechos", "max_trechos_invalido", "Máx. de trechos precisa ser um número de 1 a 10.")
    if not 1 <= mt <= 10:
        err("max_trechos", "max_trechos_invalido", "Máx. de trechos precisa ser de 1 a 10.")
        mt = min(10, max(1, mt))
    parte = str(bruto.get("parte_planilha") or "").strip() or None
    if parte and parte not in P.CHAVES:
        err("parte_planilha", "parte_invalida", f"Parte da planilha desconhecida '{parte}'. Use: {', '.join(P.CHAVES)}.")
        parte = None
    item = {"id": item_id, "nome": nome, "definicao": definicao, "tipo": tipo, "categorias": categorias, "onde_procurar": secoes,
            "palavras_chave": palavras, "obrigatorio": parse_bool(bruto.get("obrigatorio", False)), "max_trechos": mt}
    if parte:
        item["parte_planilha"] = parte
    return item, problemas


def validar_itens(brutos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Itens normalizados + todos os problemas (inclui ids repetidos). Não grava nada."""
    itens, problemas, vistos = [], [], {}
    for i, b in enumerate(brutos, 1):
        item, ps = normalizar_item(b if isinstance(b, dict) else {}, i)
        problemas += ps
        if item["id"]:
            k = item["id"].casefold()
            if k in vistos:
                problemas.append(_erro(item["id"], "id", "id_repetido", f"Id repetido (linhas {vistos[k]} e {i}).", linha=i))
            vistos.setdefault(k, i)
        itens.append(item)
    if not itens:
        problemas.append(_erro(None, None, "protocolo_vazio", "O protocolo precisa de pelo menos um item."))
    return itens, problemas


def so_erros(problemas: list[dict]) -> list[dict]:
    return [p for p in problemas if p["gravidade"] == "erro"]


def hash_item(item: dict) -> str:
    """Hash dos campos que mudam o resultado da coleta (nome e obrigatório ficam de fora)."""
    base = {k: item.get(k) for k in CAMPOS_HASH}
    return hashlib.sha256(json_estavel(base).encode("utf-8")).hexdigest()[:16]


# ---------- persistência versionada ----------

def _vazio() -> dict:
    return {"versao_protocolo": 0, "nome": "", "modelo_origem": None, "atualizado_em": None, "itens": []}


def carregar(pasta: Path) -> dict:
    c = pasta / ARQUIVO
    if not c.is_file():
        return _vazio()
    try:
        d = json.loads(c.read_text(encoding="utf-8"))
    except ValueError:
        return _vazio()
    return {**_vazio(), **d}


def _conteudo(d: dict) -> dict:
    return {"nome": d.get("nome") or "", "itens": d.get("itens") or []}


def _escrever(c: Path, d: dict) -> None:
    c.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def salvar(pasta: Path, brutos: list[dict], nome: str | None = None, modelo_origem: str | None = None) -> dict:
    """Valida (levanta ``ProtocoloInvalido``) e grava; conteúdo igual mantém a versão, diferente sobe e arquiva a anterior."""
    itens, problemas = validar_itens(brutos)
    erros = so_erros(problemas)
    if erros:
        raise ProtocoloInvalido(erros)
    avisos = [p for p in problemas if p["gravidade"] == "aviso"]
    pasta.mkdir(parents=True, exist_ok=True)
    atual = carregar(pasta)
    novo = {"versao_protocolo": 1, "nome": (nome if nome is not None else atual.get("nome")) or "",
            "modelo_origem": modelo_origem if modelo_origem is not None else atual.get("modelo_origem"),
            "atualizado_em": datetime.datetime.now().isoformat(timespec="seconds"), "itens": itens}
    c = pasta / ARQUIVO
    if not c.is_file():
        _escrever(c, novo)
        return {**novo, "avisos": avisos, "alterado": True}
    if _conteudo(atual) == _conteudo(novo):
        return {**atual, "avisos": avisos, "alterado": False}
    h = pasta / HISTORICO
    h.mkdir(exist_ok=True)
    shutil.copyfile(c, h / f"protocolo_coleta_v{atual['versao_protocolo']}.json")
    novo["versao_protocolo"] = int(atual["versao_protocolo"]) + 1
    _escrever(c, novo)
    return {**novo, "avisos": avisos, "alterado": True}


def listar_historico(pasta: Path) -> list[dict]:
    h = pasta / HISTORICO
    saida = []
    if h.is_dir():
        for f in h.glob("protocolo_coleta_v*.json"):
            try:
                n = int(f.stem.removeprefix("protocolo_coleta_v"))
                d = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            saida.append({"versao": n, "nome": d.get("nome"), "itens": len(d.get("itens") or []), "atualizado_em": d.get("atualizado_em")})
    atual = carregar(pasta)
    if atual["versao_protocolo"]:
        saida.append({"versao": atual["versao_protocolo"], "nome": atual.get("nome"), "itens": len(atual["itens"]), "atualizado_em": atual.get("atualizado_em"), "atual": True})
    return sorted(saida, key=lambda x: x["versao"])


def ler_versao(pasta: Path, versao: int) -> dict:
    atual = carregar(pasta)
    if atual["versao_protocolo"] == versao:
        return atual
    c = pasta / HISTORICO / f"protocolo_coleta_v{versao}.json"
    if not c.is_file():
        raise KeyError(f"A versão {versao} do protocolo não existe.")
    return json.loads(c.read_text(encoding="utf-8"))


def restaurar(pasta: Path, versao: int) -> dict:
    d = ler_versao(pasta, versao)
    return salvar(pasta, d["itens"], d.get("nome"), d.get("modelo_origem"))


# ---------- importação ----------

CAMPOS_CABECALHO = {
    "id": ("id", "codigo", "code", "cod", "item id", "id do item"),
    "nome": ("nome", "item", "name", "titulo", "label", "rotulo"),
    "definicao": ("definicao", "definition", "descricao", "description", "def"),
    "tipo": ("tipo", "type", "tipo de resposta", "response type", "answer type"),
    "categorias": ("categorias", "categories", "opcoes", "options", "valores permitidos", "allowed values", "values"),
    "onde_procurar": ("onde procurar", "onde_procurar", "where", "where to look", "secoes", "sections", "onde"),
    "palavras_chave": ("palavras-chave", "palavras chave", "palavras_chave", "keywords", "keyword", "termos", "terms"),
    "obrigatorio": ("obrigatorio", "required", "mandatory", "obrigatoria"),
    "max_trechos": ("max trechos", "max_trechos", "max. trechos", "maximo de trechos", "max excerpts", "max evidences"),
    "parte_planilha": ("parte da planilha", "parte_planilha", "parte planilha", "corpus part", "parte (16.1)", "parte da planilha (16.1)"),
}


def _chave_cabecalho(h) -> str:
    return re.sub(r"\s+", " ", _sem_acento(h or "").replace("_", " "))


_CAB_INVERSO = {_chave_cabecalho(a): campo for campo, alts in CAMPOS_CABECALHO.items() for a in alts}


def mapear_cabecalho(cabecalho: list) -> dict[str, int]:
    achados: dict[str, int] = {}
    for j, h in enumerate(cabecalho):
        campo = _CAB_INVERSO.get(_chave_cabecalho(h))
        if campo and campo not in achados:
            achados[campo] = j
    return achados


def _celula_texto(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) > 1 and s[0] == "'" and s[1] in "=+-@":  # apóstrofo da neutralização de fórmula na exportação
        s = s[1:]
    return s


def _linhas_para_itens(cabecalho: list, corpo: list[list]) -> dict:
    mapa = mapear_cabecalho(cabecalho)
    faltam = []
    if "id" not in mapa and "nome" not in mapa:
        faltam.append("id ou nome")
    if "definicao" not in mapa:
        faltam.append("definição")
    if faltam:
        raise ValueError(f"Cabeçalho não reconhecido: faltam as colunas {' e '.join(faltam)}. Use id, nome, definição, tipo, categorias, onde procurar, "
                         "palavras-chave, obrigatório (ou os nomes em inglês).")
    brutos = []
    for linha in corpo:
        if not any(_celula_texto(c) for c in linha):
            continue
        brutos.append({campo: _celula_texto(linha[j]) if j < len(linha) else "" for campo, j in mapa.items()})
    contador = 0
    for b in brutos:  # id automático para linhas sem id (I01, I02...)
        if not b.get("id"):
            contador += 1
            b["id"] = f"I{contador:02d}"
    return {"brutos": brutos, "colunas_reconhecidas": sorted(mapa)}


def decodificar(conteudo: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", "replace")


def ler_csv(conteudo: bytes) -> dict:
    texto = decodificar(conteudo)
    primeira = texto.splitlines()[0] if texto.strip() else ""
    delim = max(";,\t", key=lambda d: primeira.count(d)) if primeira else ";"
    linhas = list(csv.reader(io.StringIO(texto), delimiter=delim))
    if not linhas:
        raise ValueError("O CSV está vazio.")
    return _linhas_para_itens(linhas[0], linhas[1:])


def ler_abas_xlsx(conteudo: bytes) -> list[tuple[str, list[tuple]]]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Não foi possível ler o .xlsx: {type(exc).__name__}.") from exc
    try:
        return [(ws.title, list(ws.iter_rows(values_only=True))) for ws in wb.worksheets]
    finally:
        wb.close()


def ler_xlsx(conteudo: bytes) -> dict:
    abas = ler_abas_xlsx(conteudo)
    for _nome, linhas in sorted(abas, key=lambda a: _sem_acento(a[0]) != "protocolo"):  # aba "Protocolo" primeiro
        for i, l in enumerate(linhas[:5]):
            m = mapear_cabecalho(list(l))
            if "definicao" in m and ("id" in m or "nome" in m):
                return _linhas_para_itens(list(l), [list(x) for x in linhas[i + 1:]])
    raise ValueError("Nenhuma aba do .xlsx tem o cabeçalho do protocolo (id, nome, definição, ...).")


def _celulas_md(linha: str) -> list[str]:
    t = linha.strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|") and not t.endswith("\\|"):
        t = t[:-1]
    return [p.replace("\\|", "|").strip() for p in re.split(r"(?<!\\)\|", t)]


def ler_markdown(texto: str) -> dict:
    linhas = [l for l in texto.splitlines() if l.strip().startswith("|")]
    if len(linhas) < 2:
        raise ValueError("Não encontrei uma tabela Markdown (linhas começando com |).")
    cab = _celulas_md(linhas[0])
    corpo = [_celulas_md(l) for l in linhas[1:] if not re.fullmatch(r"\s*\|?[\s:\-|]+\|?\s*", l)]
    return _linhas_para_itens(cab, corpo)


def importar(conteudo: bytes, formato: str = "auto", nome_arquivo: str | None = None) -> dict:
    """Lê CSV/XLSX/Markdown e devolve ``{itens, problemas, erros, avisos, linhas, formato}`` (sem gravar). Itens com erro vêm mesmo assim, para a tela mostrar."""
    nome = (nome_arquivo or "").lower()
    if formato == "auto":
        if conteudo[:2] == b"PK" or nome.endswith((".xlsx", ".xlsm")):
            formato = "xlsx"
        elif nome.endswith((".md", ".markdown")) or re.match(rb"\s*\|", conteudo[:200] or b""):
            formato = "markdown"
        else:
            formato = "csv"
    if formato not in ("csv", "xlsx", "markdown"):
        raise ValueError("Formato inválido: use csv, xlsx ou markdown.")
    lido = ler_xlsx(conteudo) if formato == "xlsx" else (ler_markdown(decodificar(conteudo)) if formato == "markdown" else ler_csv(conteudo))
    itens, problemas = validar_itens(lido["brutos"])
    return {"formato": formato, "itens": itens, "problemas": problemas, "erros": so_erros(problemas), "avisos": [p for p in problemas if p["gravidade"] == "aviso"],
            "linhas": len(lido["brutos"]), "colunas_reconhecidas": lido["colunas_reconhecidas"]}


# ---------- exportação do protocolo ----------

COLUNAS_EXPORTACAO = ["id", "nome", "definição", "tipo", "categorias", "onde procurar", "palavras-chave", "obrigatório", "máx. trechos", "parte da planilha (16.1)"]


def linhas_do_protocolo(itens: list[dict]) -> list[list]:
    return [[i["id"], i["nome"], i["definicao"], i["tipo"], categorias_para_texto(i.get("categorias") or []), "; ".join(i.get("onde_procurar") or [QUALQUER]),
             "; ".join(i.get("palavras_chave") or []), "sim" if i.get("obrigatorio") else "não", i.get("max_trechos", MAX_TRECHOS_PADRAO), i.get("parte_planilha") or ""]
            for i in itens]


def exportar_csv(itens: list[dict]) -> bytes:
    return csv_bytes(COLUNAS_EXPORTACAO, linhas_do_protocolo(itens))


def adicionar_aba_protocolo(wb, itens: list[dict]) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from app.services.corpus.planilha import _txt

    ws = wb.create_sheet("Protocolo")
    ws.append(COLUNAS_EXPORTACAO)
    for j, w in enumerate([10, 28, 70, 12, 60, 24, 40, 12, 10, 18], 1):
        c = ws.cell(row=1, column=j)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5D8A")
        ws.column_dimensions[get_column_letter(j)].width = w
    for linha in linhas_do_protocolo(itens):
        ws.append([_txt(v) for v in linha])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"


def exportar_xlsx(itens: list[dict]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    adicionar_aba_protocolo(wb, itens)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
