"""17.3 - Concordância da coleta: kappa e alfa por item (funções da 15.1, ``concordancia/estatisticas.py``).

Duas fontes de "segundo codificador":
- ``revisao``: **sugestão automática x valor revisado**. Para cada célula decidida pelo revisor, o par é (o que a máquina sugeriu, o valor final): aceitar = concordância;
  editar = discordância; rejeitar = "(rejeitado)"; célula sem sugestão que o revisor preencheu = "(não encontrado)". Mede o quanto a coleta automática acerta;
- ``segundo``: **segundo codificador humano** importado de CSV/XLSX (``importar_segundo``): uma linha por documento (coluna ``arquivo``, ``documento`` ou ``rótulo``) e uma
  coluna por item com o **mesmo id** do protocolo (também vale o cabeçalho "id nome" da exportação larga); ou formato longo com as colunas documento, item e valor.
  O par é (valor final do revisor principal, valor do segundo codificador), só onde os dois existem.

Por item: ``categoria`` e ``sim_nao`` -> percentual de concordância, kappa de Cohen e alfa de Krippendorff nominal (faixas de Landis & Koch e de Krippendorff);
``numero`` -> concordância exata e, se ``bandas`` (cortes crescentes, ex.: 100,500,1000) for informado, kappa nas faixas e alfa **ordinal** das faixas;
``multipla`` -> concordância exata do conjunto; ``texto`` e ``data`` -> só concordância exata (``data``) ou "não calculado" (``texto``).
Com menos de 2 pares, ou sem variação (todos iguais), as estatísticas ficam indefinidas (None) e a nota explica.
"""
import csv
import io
import json
import re
from pathlib import Path

from app.services.coleta import celulas as C
from app.services.coleta import protocolo as PR
from app.services.concordancia import estatisticas as ST
from app.services.corpus import projeto as svc_projeto
from app.services.analises import dados as svc_dados

ARQUIVO = "coleta_segundo_codificador.json"
NAO_ENCONTRADO = "(não encontrado)"
REJEITADO = "(rejeitado)"
_CHAVES_DOC = ("arquivo", "documento", "rotulo", "file", "document", "doc", "id", "nome do arquivo", "filename")
_CHAVES_ITEM = ("item", "item id", "id do item", "id item", "item_id")
_CHAVES_VALOR = ("valor", "value", "resposta", "answer")


def _sa(s) -> str:
    return PR._sem_acento(s)


def _chave_doc(s) -> str:
    return re.sub(r"\.(md|pdf|docx|txt)$", "", _sa(s))


# ---------- segundo codificador ----------

def caminho(pasta: Path) -> Path:
    return pasta / ARQUIVO


def carregar_segundo(pasta: Path) -> dict | None:
    c = caminho(pasta)
    if not c.is_file():
        return None
    try:
        return json.loads(c.read_text(encoding="utf-8"))
    except ValueError:
        return None


def remover_segundo(pasta: Path) -> bool:
    c = caminho(pasta)
    if c.is_file():
        c.unlink()
        return True
    return False


def _tabela(conteudo: bytes, nome_arquivo: str | None) -> tuple[list, list[list]]:
    if conteudo[:2] == b"PK" or (nome_arquivo or "").lower().endswith((".xlsx", ".xlsm")):
        abas = PR.ler_abas_xlsx(conteudo)
        for nome, linhas in abas:
            if _sa(nome) in ("protocolo", "leia-me"):
                continue
            for i, l in enumerate(linhas[:5]):
                if any(_sa(c) in _CHAVES_DOC for c in l if c is not None):
                    return list(l), [list(x) for x in linhas[i + 1:]]
        raise ValueError("Nenhuma aba do .xlsx tem uma coluna de documento (arquivo, documento ou rótulo).")
    texto = PR.decodificar(conteudo)
    primeira = texto.splitlines()[0] if texto.strip() else ""
    delim = max(";,\t", key=lambda d: primeira.count(d)) if primeira else ";"
    linhas = list(csv.reader(io.StringIO(texto), delimiter=delim))
    if not linhas:
        raise ValueError("O arquivo está vazio.")
    return linhas[0], linhas[1:]


def importar_segundo(db, pasta: Path, conteudo: bytes, nome_arquivo: str | None = None, nome_codificador: str | None = None) -> dict:
    cab, corpo = _tabela(conteudo, nome_arquivo)
    itens = PR.carregar(pasta)["itens"]
    if not itens:
        raise ValueError("O protocolo está vazio.")
    docs = svc_projeto.documentos_ativos(db)
    por_chave = {}
    for d in docs:
        por_chave[_chave_doc(d.arquivo)] = d
        por_chave.setdefault(_chave_doc(svc_dados.rotulo_do_documento(d)), d)
        por_chave.setdefault(str(d.id), d)
    hs = [_sa(h) for h in cab]
    j_doc = next((j for j, h in enumerate(hs) if h in _CHAVES_DOC), None)
    if j_doc is None:
        raise ValueError("Não encontrei a coluna do documento (arquivo, documento ou rótulo).")
    valores: dict[str, dict] = {}
    nao_casados: list[str] = []

    def casar(chave):
        d = por_chave.get(_chave_doc(chave))
        if d is None and str(chave).strip():
            nao_casados.append(str(chave))
        return d

    j_item = next((j for j, h in enumerate(hs) if h in _CHAVES_ITEM), None)
    j_valor = next((j for j, h in enumerate(hs) if h in _CHAVES_VALOR), None)
    colunas: dict[int, str] = {}
    for it in itens:
        for j, h in enumerate(cab):
            hn = _sa(h)
            if j == j_doc:
                continue
            if hn == _sa(it["id"]) or hn.startswith(_sa(it["id"]) + " ") or hn == _sa(it["nome"]):
                if "evidencia" in hn or "status" in hn:
                    continue
                colunas.setdefault(j, it["id"])
    if colunas:
        for linha in corpo:
            d = casar(linha[j_doc]) if j_doc < len(linha) and linha[j_doc] not in (None, "") else None
            if d is None:
                continue
            for j, iid in colunas.items():
                v = linha[j] if j < len(linha) else None
                if v not in (None, ""):
                    valores.setdefault(d.arquivo, {})[iid] = str(v).strip()
        formato = "larga"
    elif j_item is not None and j_valor is not None:
        ids = {_sa(i["id"]): i["id"] for i in itens}
        for linha in corpo:
            if j_doc >= len(linha) or linha[j_doc] in (None, ""):
                continue
            d = casar(linha[j_doc])
            iid = ids.get(_sa(linha[j_item])) if j_item < len(linha) else None
            if d is None or iid is None:
                continue
            v = linha[j_valor] if j_valor < len(linha) else None
            if v not in (None, ""):
                valores.setdefault(d.arquivo, {})[iid] = str(v).strip()
        formato = "longa"
    else:
        raise ValueError("Não reconheci colunas de itens: use o id do item como cabeçalho (ou o formato longo: documento, item, valor).")
    dados = {"nome": (nome_codificador or "").strip() or "Segundo codificador", "arquivo": nome_arquivo, "formato": formato, "valores": valores,
             "nao_casados": sorted(set(nao_casados))[:50], "itens_reconhecidos": sorted(set(colunas.values())) if colunas else sorted({i for v in valores.values() for i in v})}
    pasta.mkdir(parents=True, exist_ok=True)
    caminho(pasta).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"nome": dados["nome"], "formato": formato, "documentos_casados": len(valores), "itens_reconhecidos": dados["itens_reconhecidos"],
            "valores": sum(len(v) for v in valores.values()), "nao_casados": dados["nao_casados"]}


# ---------- cálculo ----------

def _rotulo(v, tipo: str) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return "; ".join(sorted(_sa(x) for x in v))
    if tipo == "sim_nao":
        k = _sa(v)
        return "sim" if k in ("sim", "s", "yes", "y", "true") else "não" if k in ("nao", "n", "no", "false") else k
    if tipo == "multipla":
        return "; ".join(sorted(_sa(x) for x in re.split(r"[;|]", str(v)) if x.strip()))
    if tipo == "numero":
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f"{float(v):g}"
        from app.services.coleta.extratores import valor_numero

        m = re.match(r"^\s*([\d.,   ]*\d)", str(v))  # "1.200" (pt-BR) = 1200, como na coleta
        return f"{float(valor_numero(m.group(1).strip())):g}" if m else _sa(v)
    return _sa(v)


def _banda(v: str | None, cortes: list[float]) -> int | None:
    if v is None:
        return None
    try:
        n = float(v)
    except ValueError:
        return None
    return sum(1 for c in cortes if n >= c)


def _limpo(obj):
    return json.loads(json.dumps(obj, default=float))


def estatisticas_do_item(a: list, b: list, item: dict, bandas: list[float] | None) -> dict:
    """Linha da tabela de concordância para um item (``a`` e ``b`` já alinhados, sem faltantes)."""
    tipo = item["tipo"]
    base = {"id": item["id"], "nome": item["nome"], "tipo": tipo, "n": len(a), "percentual": ST.percentual(a, b), "kappa": None, "kappa_faixa": None, "kappa_ic95": None,
            "alfa": None, "alfa_faixa": None, "metrica": None, "nota": None}
    if tipo == "texto":
        base.update(percentual=None, nota="texto livre: não calculado")
        return base
    if len(a) < 2:
        base["nota"] = "menos de 2 pares: estatísticas indefinidas"
        return base
    if tipo == "numero":
        if not bandas:
            base["nota"] = "só concordância exata; informe faixas (bandas) para kappa e alfa ordinal"
            return base
        ba = [_banda(x, bandas) for x in a]
        bb = [_banda(x, bandas) for x in b]
        pares = [(x, y) for x, y in zip(ba, bb) if x is not None and y is not None]
        if len(pares) < 2:
            base["nota"] = "menos de 2 pares numéricos"
            return base
        a, b = [p[0] for p in pares], [p[1] for p in pares]
        base["percentual"] = ST.percentual(a, b)
        base["n"] = len(pares)
        metrica = "ordinal"
    elif tipo in ("categoria", "sim_nao"):
        metrica = "nominal"
    else:  # multipla, data
        base["nota"] = "só concordância exata" if tipo == "data" else "múltipla escolha: concordância exata do conjunto"
        return base
    k = ST.cohen_kappa(a, b)
    al = ST.krippendorff_alfa([a, b], metrica)
    base.update(kappa=k.get("kappa"), kappa_faixa=k.get("faixa"), kappa_ic95=k.get("ic95"), alfa=al.get("alfa"), alfa_faixa=al.get("faixa"), metrica=metrica)
    if k.get("kappa") is None:
        base["nota"] = "sem variação nos valores: kappa e alfa indefinidos"
    return _limpo(base)


def calcular(db, pasta: Path, fonte: str = "revisao", bandas: list[float] | None = None) -> dict:
    if fonte not in ("revisao", "segundo"):
        raise ValueError("Fonte inválida: use revisao ou segundo.")
    prot = PR.carregar(pasta)
    itens = prot["itens"]
    dados = C.carregar(pasta)
    docs = svc_projeto.documentos_ativos(db)
    segundo = carregar_segundo(pasta) if fonte == "segundo" else None
    if fonte == "segundo" and segundo is None:
        raise LookupError("Nenhum segundo codificador importado: envie o CSV/XLSX com as colunas dos itens.")
    saida = []
    for it in itens:
        a, b = [], []
        for d in docs:
            cel = C.celula_de(dados, d.arquivo, it["id"])
            if cel is None:
                continue
            if fonte == "revisao":
                if cel["status"] not in ("aceito", "editado", "rejeitado"):
                    continue
                auto = cel.get("automatico") or {}
                va = auto.get("valor") if auto.get("status") != "nao_encontrado" else None
                a.append(_rotulo(va, it["tipo"]) if va is not None else NAO_ENCONTRADO)
                b.append(REJEITADO if cel["status"] == "rejeitado" else _rotulo(cel.get("valor"), it["tipo"]))
            else:
                if cel["status"] not in C.FINAIS:
                    continue
                v2 = (segundo["valores"].get(d.arquivo) or {}).get(it["id"])
                if v2 is None:
                    continue
                a.append(_rotulo(cel.get("valor"), it["tipo"]))
                b.append(_rotulo(v2, it["tipo"]))
        saida.append(estatisticas_do_item(a, b, it, bandas))
    return {"fonte": fonte, "descricao": ("sugestão automática x valor revisado" if fonte == "revisao" else f"revisor principal x {segundo['nome']}"),
            "bandas": bandas, "itens": saida, "segundo_codificador": ({k: segundo[k] for k in ("nome", "formato", "arquivo", "itens_reconhecidos", "nao_casados")} if segundo else None),
            "referencias": "Cohen (1960); Krippendorff (2011, 2018); Landis & Koch (1977) (funções da 15.1)"}
