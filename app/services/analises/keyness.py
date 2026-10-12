"""6.1 - Palavras-chave entre grupos (keyness): corpus A contra corpus B, com log-likelihood e tamanho de efeito.

Equivale à Keyword List do AntConc, ao Wmatrix e ao ``textstat_keyness`` (G²) do quanteda. **Não** equivale
aos "termos distintivos" do Voyant (TF-IDF por documento, sem teste de significância).

Lados A e B
-----------
A e B são conjuntos de documentos definidos por uma **partição**:

- ``particao="grupo"``: ``a`` = um grupo (ou vários, separados por vírgula; "sem grupo" = documentos sem grupo);
  ``b`` = outro(s) grupo(s) **ou** ``"resto"`` = *todos* os demais documentos, com qualquer grupo ou nenhum.
- ``particao="ano"``: o mesmo, com anos ("2024", "2023,2024", "s/ano"). ``b`` pode ser "resto".

A escolha entre "B = grupo específico" e "B = resto" é explícita no parâmetro ``b`` (padrão "resto"); com B
específico os demais documentos ficam fora da comparação. A e B nunca se sobrepõem (erro se houver
valor comum) e nenhum dos dois pode ser vazio. Um grupo chamado "resto" colide com o valor reservado:
renomeie-o.

Universo de tokens
------------------
O mesmo do vocabulário (Frente 4.2) e do painel Frequências: só o corpo (``incluir`` = 1), tokens com >= 2
letras, contados por lema (padrão, D5) ou por forma. As palavras vazias são filtradas **na consulta** (não
entram na lista de palavras-chave), mas os tamanhos ``c`` e ``d`` contam todos os tokens do universo, com as
palavras vazias, como no denominador do painel Frequências e do /10k do Voyant.

Tabela por termo
----------------
a = frequência do termo em A; b = em B; c = tokens de A; d = tokens de B; E1 = c(a+b)/(c+d) e
E2 = d(a+b)/(c+d) (frequências esperadas se o termo fosse igualmente frequente nos dois lados).

Medidas
-------
- ``g2`` (log-likelihood, Rayson & Garside 2000): **forma de 2 células** G² = 2·(a·ln(a/E1) + b·ln(b/E2)), com
  0·ln 0 = 0. É a forma usada pelo AntConc e pelo Wmatrix, e por isso a escolhida aqui (comparabilidade).
  Ela **difere** do G² de 4 células da tabela 2×2 completa (que soma também as células "não é o termo",
  c−a e d−b; é o usado nos colocados da 5.4 e em ``chi2_contingency(lambda_="log-likelihood")`` do scipy):
  a de 2 células omite as células de complemento, que pesam pouco quando o termo é raro, mas não são nulas.
  Sinal: positivo se a/c > b/d (sobre-representado em A), negativo se menor (sobre-representado em B).
- ``p`` = erfc(√(|G²|/2)) = P(χ² com 1 g.l. >= |G²|). Com ``bonferroni=True`` o limiar vira ``p`` / m, com m =
  termos testados (os que passam a frequência mínima); ``p_bonferroni`` = min(1, p·m) vem sempre.
- ``log_ratio`` (Hardie 2014) = log2((a/c)/(b/d)): cada unidade = o dobro da frequência relativa. Se a = 0 ou
  b = 0 usa-se 0,5 no lugar da contagem zero (convenção de Hardie), só nesse cálculo.
- ``pct_diff`` (Gabrielatos & Marchi 2012) = ((a/c − b/d)/(b/d))·100; com b = 0 é indefinido (∞): vem ``None`` e
  ``so_em_a`` = True ("só em A"); com a = 0 vale −100 e ``so_em_b`` = True.
- ``por_10k_a``/``por_10k_b`` = frequência por 10 mil tokens do lado; ``docs_a``/``docs_b`` = amplitude
  (em quantos documentos do lado o termo aparece).

Filtros (padrões)
-----------------
frequência total (a+b) >= 5; p < 0,01 (ou Bonferroni); dispersão: nas palavras-chave de A o termo deve
ocorrer em >= ``min_docs_a`` (2) documentos de A, e nas de B em >= ``min_docs_b`` (2) documentos de B, o que
evita palavras-chave de um documento só; o mínimo é limitado ao nº de documentos do lado. Ordenação por |G²|
(padrão) ou por |Log Ratio|; positivas (A) e negativas (B) em listas separadas, até ``limite`` de cada.
"""
import math
from collections import Counter

from app.services.analises import dados, frequencias

RESTO = "resto"
PARTICOES = ("grupo", "ano")
FERRAMENTA_EQUIVALENTE = "AntConc Keyword List, Wmatrix, quanteda textstat_keyness (G²)"
NAO_EQUIVALENTE = "Voyant 'termos distintivos' (TF-IDF, sem teste)"
METODOLOGIA = (
    "Log-likelihood de 2 células (Rayson & Garside 2000; a forma do AntConc/Wmatrix, que difere do G² de 4 "
    "células), com sinal (positivo = sobre-representado em A); p pelo qui-quadrado com 1 g.l.; Log Ratio "
    "(Hardie 2014, 0,5 no lugar de contagem zero) e %DIFF (Gabrielatos & Marchi 2012). Tamanhos c e d com todas "
    "as palavras do corpo (>= 2 letras); palavras vazias filtradas na consulta."
)


# ---------- estatística (funções puras) ----------

def _xlogx(o: float, e: float) -> float:
    return o * math.log(o / e) if o > 0 else 0.0


def log_likelihood(a: int, b: int, c: int, d: int) -> float:
    """G² de 2 células (Rayson & Garside 2000), com sinal: positivo se a/c > b/d, negativo se menor, 0 se iguais."""
    if c <= 0 or d <= 0 or a + b == 0:
        return 0.0
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    g2 = max(2.0 * (_xlogx(a, e1) + _xlogx(b, e2)), 0.0)  # max: erro de arredondamento
    if a * d > b * c:
        return g2
    if a * d < b * c:
        return -g2
    return 0.0


def valor_p(g2: float) -> float:
    """P(χ²₁ >= |G²|) = erfc(√(|G²|/2))."""
    return math.erfc(math.sqrt(abs(g2) / 2.0))


def log_ratio(a: int, b: int, c: int, d: int) -> float:
    """log2((a/c)/(b/d)) (Hardie 2014); contagem zero vira 0,5 (só aqui)."""
    a_ = a if a > 0 else 0.5
    b_ = b if b > 0 else 0.5
    return math.log2((a_ / c) / (b_ / d))


def pct_diff(a: int, b: int, c: int, d: int) -> float | None:
    """((a/c − b/d)/(b/d))·100 (Gabrielatos & Marchi 2012); ``None`` quando b = 0 (infinito)."""
    if b == 0:
        return None
    return ((a / c - b / d) / (b / d)) * 100.0


def medidas(a: int, b: int, c: int, d: int) -> dict:
    g2 = log_likelihood(a, b, c, d)
    return {
        "a": a, "b": b,
        "por_10k_a": round(a / c * 10000, 2), "por_10k_b": round(b / d * 10000, 2),
        "g2": g2, "p": valor_p(g2),
        "log_ratio": log_ratio(a, b, c, d),
        "pct_diff": pct_diff(a, b, c, d),
        "so_em_a": b == 0, "so_em_b": a == 0,
    }


# ---------- lados A e B ----------

def _valores(texto: str | None) -> list[str]:
    return [v.strip() for v in (texto or "").split(",") if v.strip()]


def selecionar_lados(metas: list[dict], particao: str, a: str, b: str = RESTO) -> tuple[list[dict], list[dict]]:
    """Documentos de A e de B. ``b`` = "resto" (todos os demais) ou valor(es) da partição. ValueError se inválido."""
    if particao not in PARTICOES:
        raise ValueError(f"Partição inválida '{particao}': use 'grupo' ou 'ano'.")
    chave = dados.chave_grupo if particao == "grupo" else dados.chave_ano
    va = _valores(a)
    if not va:
        raise ValueError("Informe o lado A (parâmetro 'a').")
    docs_a = [m for m in metas if chave(m) in va]
    ids_a = {m["id"] for m in docs_a}
    vb = _valores(b) or [RESTO]
    if vb == [RESTO]:
        docs_b = [m for m in metas if m["id"] not in ids_a]
    else:
        comuns = sorted(set(va) & set(vb))
        if comuns:
            raise ValueError(f"A e B se sobrepõem em {', '.join(comuns)}: escolha valores diferentes.")
        docs_b = [m for m in metas if chave(m) in vb]
    if not docs_a:
        raise ValueError(f"Nenhum documento no lado A ({a}).")
    if not docs_b:
        raise ValueError(f"Nenhum documento no lado B ({b or RESTO}).")
    return docs_a, docs_b


def _lado(voc: dict, metas: list[dict], filtro, por: str, filtrar: bool) -> dict:
    docs = frequencias._docs_do_escopo(voc, metas)
    freq: Counter = Counter()
    df: Counter = Counter()
    for d in docs:
        local = frequencias.contagem_documento(d, filtro, por, filtrar)
        freq.update(local)
        df.update(local.keys())
    return {"freq": freq, "df": df, "tokens": sum(d["tokens"] for d in docs), "documentos": len(docs)}


def calcular(voc: dict, metas: list[dict], filtro, particao: str = "grupo", a: str = "", b: str = RESTO,
             por: str = "lema", filtrar: bool = True, min_freq: int = 5, min_docs_a: int = 2, min_docs_b: int = 2,
             p: float = 0.01, bonferroni: bool = False, ordem: str = "ll", limite: int = 50) -> dict:
    """Palavras-chave de A contra B. ``metas`` = documentos do corpus (com ``grupo``/``ano``). Levanta ValueError."""
    if ordem not in ("ll", "logratio"):
        raise ValueError(f"Ordenação inválida '{ordem}': use 'll' ou 'logratio'.")
    docs_a, docs_b = selecionar_lados(metas, particao, a, b)
    la = _lado(voc, docs_a, filtro, por, filtrar)
    lb = _lado(voc, docs_b, filtro, por, filtrar)
    c, d = la["tokens"], lb["tokens"]
    if c == 0 or d == 0:
        raise ValueError("Um dos lados não tem tokens contados (documento sem texto?).")
    min_a = min(min_docs_a, la["documentos"])
    min_b = min(min_docs_b, lb["documentos"])

    testados = []
    for termo in set(la["freq"]) | set(lb["freq"]):
        fa, fb = la["freq"].get(termo, 0), lb["freq"].get(termo, 0)
        if fa + fb >= min_freq:
            testados.append((termo, fa, fb))
    m = len(testados)
    limiar = p / m if bonferroni and m else p

    positivas, negativas = [], []
    for termo, fa, fb in testados:
        med = medidas(fa, fb, c, d)
        if med["g2"] == 0 or not med["p"] < limiar:
            continue
        item = {"termo": termo, **med, "docs_a": la["df"].get(termo, 0), "docs_b": lb["df"].get(termo, 0),
                "p_bonferroni": min(1.0, med["p"] * m)}
        if med["g2"] > 0:
            if item["docs_a"] >= min_a:
                positivas.append(item)
        elif item["docs_b"] >= min_b:
            negativas.append(item)

    def chave_ordem(i):
        principal = abs(i["g2"]) if ordem == "ll" else abs(i["log_ratio"])
        return (-principal, -abs(i["g2"]), i["termo"])

    positivas.sort(key=chave_ordem)
    negativas.sort(key=chave_ordem)
    limite = max(0, limite)
    return {
        "particao": particao, "por": por,
        "lado_a": {"valor": a, "documentos": la["documentos"], "tokens": c, "tipos": len(la["freq"]),
                   "ids": [x["id"] for x in docs_a]},
        "lado_b": {"valor": b or RESTO, "documentos": lb["documentos"], "tokens": d, "tipos": len(lb["freq"]),
                   "ids": [x["id"] for x in docs_b]},
        "termos_testados": m, "limiar_p": limiar,
        "total_positivas": len(positivas), "total_negativas": len(negativas),
        "positivas": positivas[:limite], "negativas": negativas[:limite],
        "parametros": {"particao": particao, "a": a, "b": b or RESTO, "por": por,
                       "vazias": "filtrar" if filtrar else "manter", "min_freq": min_freq,
                       "min_docs_a": min_docs_a, "min_docs_b": min_docs_b, "min_docs_a_efetivo": min_a,
                       "min_docs_b_efetivo": min_b, "p": p, "bonferroni": bonferroni, "ordem": ordem,
                       "limite": limite},
        "metodologia": METODOLOGIA,
        "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE,
        "nao_equivalente": NAO_EQUIVALENTE,
    }


# ---------- listas de grupos/anos e instantâneo ----------

def lados_disponiveis(voc: dict, metas: list[dict]) -> dict:
    """Grupos e anos do corpus com nº de documentos e de tokens (tokens contados do vocabulário)."""
    def contar(chave_de, ordem):
        acc: dict[str, dict] = {}
        for m in metas:
            v = voc["documentos"].get(str(m["id"]))
            item = acc.setdefault(chave_de(m), {"valor": chave_de(m), "documentos": 0, "tokens": 0})
            item["documentos"] += 1
            item["tokens"] += v["tokens"] if v else 0
        return [acc[k] for k in sorted(acc, key=ordem)]

    grupos = contar(dados.chave_grupo, frequencias._ordem_grupo)
    anos = contar(dados.chave_ano, frequencias._ordem_ano)
    return {"grupos": grupos, "anos": anos,
            "grupos_definidos": sum(1 for g in grupos if g["valor"] != dados.SEM_GRUPO)}


def comparar_grupos(voc: dict, metas: list[dict], filtro, **kw) -> dict | None:
    """Cada grupo definido contra o resto (instantâneo da etapa). ``None`` se há menos de 2 grupos com documentos."""
    grupos = [g["valor"] for g in lados_disponiveis(voc, metas)["grupos"] if g["valor"] != dados.SEM_GRUPO]
    if len(grupos) < 2:
        return None
    return {"grupos": grupos,
            "comparacoes": [calcular(voc, metas, filtro, particao="grupo", a=g, b=RESTO, **kw) for g in grupos]}
