"""6.4 - Dicionário / codebook: contagem automática de categorias (padrões de lema ou forma) por grupo, ano ou documento.

Equivale aos dicionários do quanteda (``dfm_lookup``) e às regras de codificação do KH Coder. **Não** é a codificação
manual de trechos do ATLAS.ti/NVivo: aqui a categoria é a presença de padrões escritos no ``dicionario.yaml``.

Casamento
---------
``por="lema"`` (padrão) casa o lema do token; ``por="forma"``, a forma em minúsculas (``norm``). Só tokens do corpo
(``incluir`` = 1) com >= 2 letras. Padrão de uma palavra: exato ou com ``*`` (``agent*``). Padrão com espaço = **frase**:
palavras contíguas no mesmo bloco, sem parágrafo nem pontuação entre elas (as mesmas regras do KWIC por frase e dos
n-gramas, ``kwic.posicoes_da_frase``). Uma **ocorrência** é uma posição inicial distinta por categoria: se dois padrões
da categoria começam no mesmo token, conta uma vez (a frase prevalece sobre a palavra, para o ranking de termos).
Ocorrências de frases que se sobrepõem a partir de tokens diferentes contam cada uma.

Métricas
--------
Por categoria: ``total`` de ocorrências, ``por_10k`` = total / tokens do corpus x 10.000 (denominador do Voyant:
palavras do corpo, com vazias, como nas Frequências), ``docs`` = documentos com >= 1 ocorrência, ``media_por_doc`` =
total / nº de documentos. Por unidade (grupo, ano ou documento): ocorrências, /10k da unidade, documentos.
``termos_top`` = padrões/lemas efetivamente casados, mais frequentes.

Comparação entre unidades (grupo ou ano)
----------------------------------------
Cada categoria é tratada como um "termo" da keyness 6.1: unidade contra todas as demais, com a=ocorrências da categoria na
unidade, b = nas demais, c e d = tokens da unidade e das demais. ``g2`` = G² de 2 células com sinal (Rayson & Garside
2000), ``p`` = qui-quadrado 1 g.l., ``log_ratio`` (Hardie 2014): as mesmas funções de ``keyness.py``. Com uma só unidade
(ou ``agrupar=documento``) não há comparação (campos nulos). Categorias sem termos ficam fora dos números e voltam em
``sem_termos``.
"""
from collections import Counter

from app.services.analises import dados, frequencias, keyness
from app.services.analises.kwic import posicoes_da_frase
from app.services.termos_compostos import sequencias

FERRAMENTA_EQUIVALENTE = "quanteda dictionary (dfm_lookup), KH Coder (regras de codificação)"
NAO_EQUIVALENTE = "codificação manual de trechos (ATLAS.ti, NVivo)"
AGRUPAMENTOS = ("grupo", "ano", "documento")
TOP_TERMOS = 10
METODOLOGIA = (
    "Contagem de ocorrências de padrões do dicionário (lema ou forma; * = curinga; espaço = frase de palavras contíguas) "
    "por categoria; por 10 mil palavras do corpo; comparação entre grupos/anos pelo G² de 2 células (Rayson & Garside 2000) "
    "e Log Ratio (Hardie 2014), tratando cada categoria como um termo."
)


def compilar_padrao(padrao: str) -> dict:
    """"agent*" -> {"padrao", "itens": [item]} (palavra) ; "human oversight" -> {"padrao", "itens": [i1, i2], "frase": True}."""
    palavras = padrao.split()
    itens = [i for w in palavras for i in dados.compilar_consulta(w)[:1]]
    return {"padrao": padrao, "itens": itens, "frase": len(itens) > 1}


def compilar_categorias(dic: dict) -> list[dict]:
    """Só as categorias com termos, com os padrões compilados."""
    return [{**c, "padroes": [compilar_padrao(t) for t in c["termos"]]} for c in dic["categorias"] if c["termos"]]


def consulta_kwic(termos: list[str]) -> str:
    """Padrões da categoria como consulta do KWIC: ``agent*, "human oversight"``."""
    return ", ".join(f'"{t}"' if " " in t else t for t in termos)


def ocorrencias_no_documento(tk: dict, blocos: list[dict], categorias: list[dict], por: str = "lema") -> dict[str, dict[int, str]]:
    """Por categoria, ``{posição inicial: texto casado}`` (lema/forma, ou a sequência para frases) num documento."""
    campo = "lema" if por == "lema" else "norm"
    inc, norm, unid = tk["incluir"], tk["norm"], tk[campo]
    indice = dados.indice_do_documento(tk)[campo]
    seqs = None
    saida: dict[str, dict[int, str]] = {}
    for cat in categorias:
        achadas: dict[int, str] = {}
        for pad in cat["padroes"]:
            if not pad["frase"]:
                for chave in dados.chaves_que_casam(pad["itens"], indice):
                    for p in indice[chave]:
                        if inc[p] and len(norm[p]) >= 2:
                            achadas.setdefault(p, chave)
            else:
                if seqs is None:
                    seqs = sequencias(tk, blocos, quebrar_pontuacao=True)
                tam = len(pad["itens"])
                for p in posicoes_da_frase(tk, seqs, pad["itens"], campo):
                    achadas[p] = " ".join(unid[p:p + tam])  # a frase prevalece sobre a palavra no mesmo início
        saida[cat["id"]] = achadas
    return saida


def _comparar(a: int, b: int, c: int, d: int) -> dict:
    if c <= 0 or d <= 0:
        return {"g2": None, "p": None, "log_ratio": None}
    g2 = keyness.log_likelihood(a, b, c, d)
    return {"g2": g2, "p": keyness.valor_p(g2), "log_ratio": keyness.log_ratio(a, b, c, d)}


def calcular(pasta_projeto, voc: dict, metas: list[dict], dic: dict, por: str = "lema", agrupar: str = "grupo") -> dict:
    """Resultados do dicionário ``dic`` (já validado) sobre os documentos ``metas``. Levanta ValueError se inválido."""
    if agrupar not in AGRUPAMENTOS:
        raise ValueError(f"Agrupamento inválido '{agrupar}': use grupo, ano ou documento.")
    if por not in ("lema", "forma"):
        raise ValueError(f"Unidade inválida '{por}': use lema ou forma.")
    cats = compilar_categorias(dic)
    sem_termos = [{"id": c["id"], "nome": c["nome"], "tema": c["tema"]} for c in dic["categorias"] if not c["termos"]]
    docs = [m for m in metas if str(m["id"]) in voc["documentos"]]
    tokens_doc = {m["id"]: voc["documentos"][str(m["id"])]["tokens"] for m in docs}
    por_doc: dict[int, dict[str, dict[int, str]]] = {}
    if cats:
        for m in docs:
            tk = dados.carregar_tokens(pasta_projeto, m["id"])
            blocos = dados.carregar_blocos(pasta_projeto, m["id"])
            if tk is None or blocos is None:
                continue
            por_doc[m["id"]] = ocorrencias_no_documento(tk, blocos, cats, por)
    unidades = frequencias.unidades(docs, agrupar)
    for u in unidades:
        u["documentos"] = len(u["metas"])
        u["tokens"] = sum(tokens_doc[m["id"]] for m in u["metas"])
    total_tokens = sum(tokens_doc.values())
    comparar = agrupar != "documento" and len(unidades) >= 2

    resultados = []
    for cat in cats:
        n_doc = {m["id"]: len(por_doc.get(m["id"], {}).get(cat["id"], {})) for m in docs}
        total = sum(n_doc.values())
        termos: Counter = Counter()
        for m in docs:
            termos.update(por_doc.get(m["id"], {}).get(cat["id"], {}).values())
        linhas = []
        for u in unidades:
            a = sum(n_doc[m["id"]] for m in u["metas"])
            c = u["tokens"]
            linha = {"chave": u["chave"], "rotulo": u["rotulo"], "n": a, "por_10k": round(a / c * 10000, 2) if c else 0.0,
                     "docs": sum(1 for m in u["metas"] if n_doc[m["id"]] > 0), "documentos": u["documentos"], "tokens": c}
            linha.update(_comparar(a, total - a, c, total_tokens - c) if comparar else {"g2": None, "p": None, "log_ratio": None})
            linhas.append(linha)
        resultados.append({
            "id": cat["id"], "nome": cat["nome"], "tema": cat["tema"], "descricao": cat["descricao"],
            "n_termos": len(cat["termos"]), "termos": cat["termos"], "consulta_kwic": consulta_kwic(cat["termos"]),
            "total": total, "por_10k": round(total / total_tokens * 10000, 2) if total_tokens else 0.0,
            "docs": sum(1 for v in n_doc.values() if v > 0),
            "media_por_doc": round(total / len(docs), 3) if docs else 0.0,
            "termos_top": [{"termo": t, "freq": f} for t, f in sorted(termos.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TERMOS]],
            "unidades": linhas,
        })
    return {
        "por": por, "agrupar": agrupar, "documentos": len(docs), "tokens": total_tokens,
        "unidades": [{"chave": u["chave"], "rotulo": u["rotulo"], "documentos": u["documentos"], "tokens": u["tokens"]} for u in unidades],
        "comparacao": comparar, "categorias": resultados, "sem_termos": sem_termos,
        "parametros": {"por": por, "agrupar": agrupar},
        "metodologia": METODOLOGIA, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE, "nao_equivalente": NAO_EQUIVALENTE,
    }
