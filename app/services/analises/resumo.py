"""5.1 - Resumo do corpus e por documento (equivale ao Summary do Voyant e às estatísticas do IRaMuTeQ).

Definições
----------
- ``tokens``: palavras do corpo (``incluir`` = 1, ver Frente 3.2), de qualquer tamanho e *com* palavras
  vazias, como o Voyant conta; ``tokens_total`` inclui também referências/apêndice excluídos.
- ``tipos_lema`` / ``tipos_forma``: formas distintas (lema; ``norm`` em minúsculas) entre esses tokens.
- ``densidade_*`` = tipos / tokens (a "densidade vocabular" do Voyant). Depende do tamanho do texto: para
  comparar documentos de tamanhos diferentes, use o MATTR.
- ``mattr``: média móvel da razão tipo/ocorrência (moving-average type-token ratio) com janela de 500 sobre
  as formas ``norm`` dos tokens do corpo, mantendo as palavras vazias (prática padrão). Em cada janela de
  500 palavras consecutivas calcula-se tipos/500, e o MATTR é a média de todas as janelas. Documentos com
  menos de 500 tokens não têm janela completa: usa-se a razão tipo/ocorrência simples (``mattr_ttr = true``),
  que não é comparável com os demais e fica fora dos rankings de maior/menor MATTR. Covington, M. A.;
  McFall, J. D. (2010). Cutting the Gordian knot: the moving-average type-token ratio (MATTR). *Journal of
  Quantitative Linguistics*, 17(2), 94-100.
- Termos distintivos por documento: **TF-IDF** (lema, sem palavras vazias, frequência >= 3 no documento),
  ``tf = freq / tokens contados do documento`` e ``idf = ln(N / df)``. É o equivalente dos "termos distintivos"
  do Voyant; **não** é keyness (a keyness, log-likelihood entre grupos, é a análise 6.1). Termos presentes em
  todos os documentos têm idf = 0 e não aparecem.
- Top termos do corpus: lema, sem palavras vazias (filtro dos parâmetros atuais).
"""
import math
import statistics

from app.services.analises import dados, frequencias

JANELA_MATTR = 500
MIN_FREQ_DISTINTIVO = 3
TOP_DISTINTIVOS = 10
TOP_TERMOS_CORPUS = 15
TOP_RANKINGS = 5


def mattr(formas: list[str], janela: int = JANELA_MATTR) -> tuple[float | None, bool]:
    """MATTR de uma sequência de formas. Devolve ``(valor, ttr_simples)``; vazio -> ``(None, True)``.

    Com menos de ``janela`` formas devolve a razão tipo/ocorrência simples e ``ttr_simples = True``.
    """
    n = len(formas)
    if n == 0:
        return None, True
    if n < janela:
        return len(set(formas)) / n, True
    cont: dict[str, int] = {}
    distintos = 0
    for f in formas[:janela]:
        if cont.get(f, 0) == 0:
            distintos += 1
        cont[f] = cont.get(f, 0) + 1
    soma = distintos
    for i in range(janela, n):
        sai = formas[i - janela]
        cont[sai] -= 1
        if cont[sai] == 0:
            distintos -= 1
        entra = formas[i]
        if cont.get(entra, 0) == 0:
            distintos += 1
        cont[entra] = cont.get(entra, 0) + 1
        soma += distintos
    return soma / (janela * (n - janela + 1)), False


def termos_distintivos(contagem: dict, tokens_doc: int, df: dict, n_docs: int,
                       minimo: int = MIN_FREQ_DISTINTIVO, limite: int = TOP_DISTINTIVOS) -> list[dict]:
    """TF-IDF dos lemas de um documento. ``contagem`` já vem sem palavras vazias."""
    pontos = []
    for termo, freq in contagem.items():
        if freq < minimo or not tokens_doc:
            continue
        idf = math.log(n_docs / df[termo]) if df.get(termo) else 0.0
        if idf > 0:
            pontos.append((termo, freq / tokens_doc * idf, freq))
    pontos.sort(key=lambda p: (-p[1], p[0]))
    return [{"termo": t, "tfidf": round(s, 5), "freq": f} for t, s, f in pontos[:limite]]


def calcular(pasta_projeto, metas: list[dict], voc: dict, filtro, janela: int = JANELA_MATTR) -> dict:
    """Resumo do corpus (``corpus``) e de cada documento (``documentos``). ``metas`` = documentos ativos com tokens."""
    metas = [m for m in metas if str(m["id"]) in voc["documentos"]]
    n_docs = len(metas)
    df_lema = voc["corpus"]["df_lema"]
    por_doc: list[dict] = []
    tipos_lema_c: set = set()
    tipos_forma_c: set = set()
    tokens_corpo_c = tokens_total_c = 0

    for m in metas:
        tk = dados.carregar_tokens(pasta_projeto, m["id"])
        if tk is None:
            continue
        inc = tk["incluir"]
        normas = [n for n, i in zip(tk["norm"], inc) if i]
        lemas = {l for l, i in zip(tk["lema"], inc) if i}
        tipos_forma = set(normas)
        valor_mattr, ttr = mattr(normas, janela)
        tokens = len(normas)
        tipos_lema_c |= lemas
        tipos_forma_c |= tipos_forma
        tokens_corpo_c += tokens
        tokens_total_c += tk["n"]

        vd = voc["documentos"][str(m["id"])]
        contagem = frequencias.contagem_documento(vd, filtro, "lema", True)
        por_doc.append({
            "documento_id": m["id"], "arquivo": m["arquivo"], "rotulo": m["rotulo"],
            "ano": m["ano"], "grupo": m["grupo"],
            "tokens": tokens, "tokens_total": tk["n"],
            "tipos_lema": len(lemas), "tipos_forma": len(tipos_forma),
            "densidade": round(len(tipos_forma) / tokens, 4) if tokens else None,
            "mattr": round(valor_mattr, 4) if valor_mattr is not None else None, "mattr_ttr": ttr,
            "paginas": m["paginas"], "pct_corpo": m["pct_corpo"],
            "termos_distintivos": termos_distintivos(contagem, vd["tokens"], df_lema, n_docs),
        })

    por_doc_ordenados = sorted(por_doc, key=lambda d: (-d["tokens"], d["arquivo"]))
    comparaveis = [d for d in por_doc if d["mattr"] is not None and not d["mattr_ttr"]]
    por_mattr = sorted(comparaveis, key=lambda d: (-d["mattr"], d["arquivo"]))
    tamanhos = [d["tokens"] for d in por_doc]
    mattrs = [d["mattr"] for d in comparaveis]

    def ref(d, campo):
        return {"documento_id": d["documento_id"], "rotulo": d["rotulo"], campo: d[campo]}

    anos: dict[str, int] = {}
    grupos: dict[str, int] = {}
    for m in metas:
        anos[dados.chave_ano(m)] = anos.get(dados.chave_ano(m), 0) + 1
        grupos[dados.chave_grupo(m)] = grupos.get(dados.chave_grupo(m), 0) + 1

    top = frequencias.listar(voc, metas, filtro, por="lema", filtrar=True, limite=TOP_TERMOS_CORPUS)
    corpus = {
        "n_documentos": len(por_doc),
        "tokens": tokens_corpo_c,
        "tokens_total": tokens_total_c,
        "tipos_lema": len(tipos_lema_c),
        "tipos_forma": len(tipos_forma_c),
        "densidade_lema": round(len(tipos_lema_c) / tokens_corpo_c, 4) if tokens_corpo_c else None,
        "densidade_forma": round(len(tipos_forma_c) / tokens_corpo_c, 4) if tokens_corpo_c else None,
        "mattr_janela": janela,
        "mattr_media": round(statistics.fmean(mattrs), 4) if mattrs else None,
        "mattr_mediana": round(statistics.median(mattrs), 4) if mattrs else None,
        "mattr_documentos_comparaveis": len(mattrs),
        "media_tokens": round(statistics.fmean(tamanhos), 1) if tamanhos else None,
        "mediana_tokens": statistics.median(tamanhos) if tamanhos else None,
        "mais_longos": [ref(d, "tokens") for d in por_doc_ordenados[:TOP_RANKINGS]],
        "mais_curtos": [ref(d, "tokens") for d in reversed(por_doc_ordenados[-TOP_RANKINGS:])],
        "maior_mattr": [ref(d, "mattr") for d in por_mattr[:TOP_RANKINGS]],
        "menor_mattr": [ref(d, "mattr") for d in reversed(por_mattr[-TOP_RANKINGS:])],
        "documentos_por_ano": [{"ano": k, "documentos": anos[k]} for k in sorted(anos, key=frequencias._ordem_ano)],
        "documentos_por_grupo": [{"grupo": k, "documentos": grupos[k]} for k in sorted(grupos, key=frequencias._ordem_grupo)],
        "top_termos": [{"termo": i["termo"], "freq": i["freq"]} for i in top["itens"]],
    }
    return {
        "formato": 1,
        "metodologia": {
            "tokens": "palavras do corpo (sem referências/apêndice), com palavras vazias; números puros fora",
            "mattr": f"média móvel tipo/ocorrência, janela {janela}, formas em minúsculas, palavras vazias mantidas "
                     "(Covington; McFall, 2010); com menos tokens que a janela vale a razão simples (TTR)",
            "termos_distintivos": "TF-IDF por lema, sem palavras vazias, frequência mínima "
                                  f"{MIN_FREQ_DISTINTIVO} (equivale aos 'termos distintivos' do Voyant; não é keyness)",
            "top_termos": "lemas sem palavras vazias",
        },
        "corpus": corpus,
        "documentos": por_doc,
    }


_MEMO: dict = {}
_MEMO_MAX = 8


def resumo_do_projeto(pasta_projeto, metas: list[dict], parametros: dict) -> dict | None:
    """Resumo calculado na hora a partir do vocabulário e dos tokens atuais (com memória em processo).

    A chave da memória inclui o vocabulário (data de modificação), o filtro de palavras vazias e os
    metadados dos documentos (ano/grupo editados à mão valem sem reexecutar o pipeline). ``None`` se não
    há vocabulário (pipeline não executado).
    """
    from app.services.palavras_vazias import filtro_palavras_vazias
    from app.services.vocabulario import caminho_vocabulario, ler_vocabulario

    voc = ler_vocabulario(pasta_projeto)
    if voc is None:
        return None
    filtro = filtro_palavras_vazias(parametros)
    chave = (str(pasta_projeto), caminho_vocabulario(pasta_projeto).stat().st_mtime_ns, hash(filtro),
             dados.assinatura_metadados(metas))
    achado = _MEMO.get(chave)
    if achado is None:
        achado = calcular(pasta_projeto, metas, voc, filtro)
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[chave] = achado
    return achado
