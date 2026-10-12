"""5.4 - Colocados (colocações) de um termo-nó com log-likelihood (G²) e informação mútua (MI).

Equivale ao Collocates do AntConc e do LancsBox (LL, MI). **Não** equivale ao Collocates do Voyant, que só
conta coocorrências (sem estatística de associação). Notação de Evert (2005, 2008).

Universo de tokens
------------------
Os mesmos tokens do vocabulário (Frente 4.2) e do painel Frequências: só tokens do corpo (``incluir`` = 1)
com ``norm`` de >= 2 letras. Tokens de seções excluídas e de 1 letra **não existem** para a análise: não
ocupam posição na janela nem entram em N. Assim N, C1 e a frequência do nó batem com o painel Frequências
no mesmo escopo (``N`` = "palavras contadas").

Nó
--
``consulta`` = um ou mais termos separados por vírgula, com curinga ``*`` (``agent*``), casados com o lema
(``por="lema"``, padrão, D5) ou com a forma minúscula (``por="forma"``), como no KWIC. Com ``por="termo"`` (4.3) a unidade é o termo: um termo composto
(``agentic ai``) ocupa **uma** posição da janela e conta uma vez em N; as palavras que ele cobre não existem
como tokens à parte (o resto da sequência é o do universo acima). Todas as chaves que
casam formam um único nó; nenhuma delas pode ser colocado.

Janela (span posicional)
------------------------
``esquerda`` (L) e ``direita`` (R) posições em torno de cada ocorrência do nó (padrão: parâmetro
``colocacao_janela`` = 5 de cada lado; pode ser assimétrica, ex.: 0L/3R).

- **Palavras vazias ocupam posição** (span posicional, como no AntConc e no LancsBox): o filtro
  ``vazias="filtrar"`` só impede que elas sejam *candidatas* a colocado. Ocorrências do nó dentro da janela
  de outra ocorrência também ocupam posição, mas não são contadas (o nó não é colocado de si mesmo).
- **Fronteiras:** a janela nunca atravessa documentos. Com ``fronteira="bloco"`` (padrão) também não
  atravessa blocos do texto limpo (cache/limpo), que mudam a cada **página ou seção**: uma janela que
  chega ao fim do bloco é truncada ali. Motivo: entre blocos há títulos de seção removidos, seções
  excluídas (referências) e quebras de página com cabeçalhos/rodapés — juntar os dois lados criaria
  coocorrências que o texto não tem (é a mesma regra do KWIC, que marca a fronteira com " … ").
  Custo: uma frase partida na virada de página perde as coocorrências que cruzam a quebra.
  Com ``fronteira="documento"`` a janela corre livre pelo documento inteiro, sobre a sequência de tokens
  contados (o que o AntConc vê no ``corpus-limpo.zip``); serve para a validação cruzada (docs/validacao_antconc.md).

Janelas sobrepostas (convenção)
-------------------------------
Ocorrências próximas do nó produzem janelas que se sobrepõem. Aqui as janelas são **unidas**: cada token
do corpus conta **no máximo uma vez** como coocorrência, mesmo que esteja na janela de duas ocorrências
do nó. É a construção de Evert (2008, "Corpora and collocations", coocorrência de superfície): a região de
coocorrência é a união das janelas e a tabela 2×2 classifica cada token do corpus exatamente uma vez
(dentro × fora da região; é c × não é c). Só assim valem sempre O11 <= C1 e O11 <= R1 <= N, e as quatro
células são não negativas — com a contagem por pares (cada par ocorrência-do-nó × posição, como o
"Freq(LR)" do AntConc) um mesmo token pode contar duas vezes, O11 pode passar de C1 e O21 fica negativo.
A contagem por pares é informada à parte (``pares``) e é a base do perfil de posições.

Tabela de contingência (por colocado c)
---------------------------------------
- O11 = tokens de c dentro da região de coocorrência (união das janelas, já truncadas nas fronteiras)
- R1  = tamanho da região: posições distintas cobertas por alguma janela, **sem** as posições do nó
        (inclui palavras vazias, que ocupam posição)
- C1  = frequência de c no escopo (mesmo filtro de palavras vazias por token do painel Frequências)
- N   = tokens contados do escopo
- O12 = R1 − O11;  O21 = C1 − O11;  O22 = N − R1 − O21;  E_ij = R_i · C_j / N

Medidas
-------
- ``ll``: G² = 2 Σ O_ij ln(O_ij / E_ij) (Dunning 1993), convenção 0·ln 0 = 0, **com sinal**: negativo
  quando O11 < E11 (repulsão). Por padrão só a atração (O11 > E11) é listada.
- ``p``: P(χ² com 1 g.l. >= |G²|) = erfc(√(|G²|/2)) (sem dependência do scipy).
- ``mi``: log2(O11 / E11) (Church & Hanks 1990). Favorece colocados raros: use com ``min_freq``.
- ``t``: (O11 − E11) / √O11 (t-score).
- ``logdice``: 14 + log2(2·O11 / (f_nó + C1)) (Rychlý 2008), f_nó = ocorrências do nó. Com janela, O11
  pode passar de f_nó (o colocado aparece várias vezes na janela); então o logDice pode passar de 14.
- ``pares``: coocorrências contadas por par (ocorrência do nó, posição), como o Freq(LR) do AntConc (>= O11).
- ``posicoes``: perfil por posição relativa (−L..−1, 1..R), contado por pares (soma = ``pares``).
"""
import math
from collections import Counter

from app.services.analises import dados
from app.services.palavras_vazias import COMPRIMENTO_MINIMO, token_vazio

ORDENS = ("ll", "mi", "freq", "logdice", "t")
FRONTEIRAS = ("bloco", "documento")
JANELA_MAXIMA = 20
FERRAMENTA_EQUIVALENTE = "AntConc/LancsBox Collocates (LL, MI)"
NAO_EQUIVALENTE = "Voyant Collocates (só contagem)"

METODOLOGIA = {
    "janela": "Span posicional de L palavras à esquerda e R à direita; palavras vazias ocupam posição mas não são "
              "candidatas; o nó não é colocado de si mesmo; a janela não atravessa documento nem bloco (página/seção) "
              "com fronteira=bloco.",
    "sobreposicao": "Janelas sobrepostas são unidas: cada token conta no máximo uma vez (Evert 2008); R1 = posições "
                    "distintas cobertas, sem o nó. 'pares' conta por par ocorrência×posição, como o Freq(LR) do AntConc.",
    "tabela": "O11 = c na região; R1 = tamanho da região; C1 = frequência de c no escopo; N = tokens contados do "
              "escopo; E11 = R1·C1/N (Evert 2005).",
    "medidas": "LL = G² com sinal (Dunning 1993), p pelo qui-quadrado com 1 g.l.; MI = log2(O11/E11) (Church & Hanks "
               "1990); t = (O11−E11)/√O11; logDice = 14 + log2(2·O11/(f_nó + C1)) (Rychlý 2008).",
    "referencias": "Dunning (1993); Church & Hanks (1990); Evert (2005, 2008); Rychlý (2008).",
}


# ---------- estatística (funções puras) ----------

def _xlogx_e(o: float, e: float) -> float:
    return o * math.log(o / e) if o > 0 else 0.0  # convenção 0·ln 0 = 0


def tabela(o11: int, r1: int, c1: int, n: int) -> tuple[int, int, int, int]:
    """(O11, O12, O21, O22) a partir das marginais."""
    o12, o21 = r1 - o11, c1 - o11
    return o11, o12, o21, n - r1 - o21


def log_likelihood(o11: int, r1: int, c1: int, n: int) -> float:
    """G² da tabela 2×2 (Dunning 1993), com sinal negativo quando O11 < E11."""
    o = tabela(o11, r1, c1, n)
    r2, c2 = n - r1, n - c1
    e = (r1 * c1 / n, r1 * c2 / n, r2 * c1 / n, r2 * c2 / n)
    g2 = max(0.0, 2.0 * sum(_xlogx_e(oi, ei) for oi, ei in zip(o, e)))
    return -g2 if o11 < e[0] else g2


def valor_p(g2: float) -> float:
    """P(χ²₁ >= |G²|) = erfc(√(|G²|/2))."""
    return math.erfc(math.sqrt(abs(g2) / 2.0))


def medidas(o11: int, r1: int, c1: int, n: int, f_no: int) -> dict:
    """Todas as medidas de um colocado (O11 >= 1, 0 < R1 < N, 0 < C1 < N)."""
    e11 = r1 * c1 / n
    ll = log_likelihood(o11, r1, c1, n)
    return {
        "o11": o11, "c1": c1, "e11": e11, "ll": ll, "p": valor_p(ll),
        "mi": math.log2(o11 / e11), "t": (o11 - e11) / math.sqrt(o11),
        "logdice": 14 + math.log2(2 * o11 / (f_no + c1)),
    }


# ---------- estrutura por documento (cache junto com os tokens) ----------

def estrutura_do_documento(tk: dict, por: str = "lema") -> dict:
    """Sequência de tokens contados do documento (guardada em ``tk["_colocacao"]``, vive com o cache de tokens).

    ``rank[i]`` = índice do token i na sequência contada (−1 se não conta); ``norm``/``lema``/``bloco`` da
    sequência; ``freq[campo][chave]`` = [(outra_chave, freq)] para obter C1 com o filtro de palavras vazias por token.
    Com ``por="termo"`` (``tk`` com o array ``termo``) a sequência tem uma posição por termo: ``lema`` = termo e ``norm`` =
    termo (composto) ou a forma normalizada; tokens de continuação de termo composto ficam de fora.
    """
    guarda = "_colocacao_termo" if por == "termo" else "_colocacao"
    e = tk.get(guarda)
    if e is None:
        norm, lema, inc, bloco = tk["norm"], tk["lema"], tk["incluir"], tk["bloco"]
        if por == "termo":
            termo = tk["termo"]
            pos = [i for i in range(tk["n"]) if inc[i] and len(norm[i]) >= COMPRIMENTO_MINIMO and termo[i]]
            norm = [t if " " in t else n for t, n in zip(termo, norm)]
            lema = termo
        else:
            pos = [i for i in range(tk["n"]) if inc[i] and len(norm[i]) >= COMPRIMENTO_MINIMO]
        rank = [-1] * tk["n"]
        for k, i in enumerate(pos):
            rank[i] = k
        pares = Counter((norm[i], lema[i]) for i in pos)
        por_lema: dict[str, list] = {}
        por_norm: dict[str, list] = {}
        for (nm, lm), c in pares.items():
            por_lema.setdefault(lm, []).append((nm, c))
            por_norm.setdefault(nm, []).append((lm, c))
        e = tk[guarda] = {
            "n": len(pos), "rank": rank,
            "norm": [norm[i] for i in pos], "lema": [lema[i] for i in pos], "bloco": [bloco[i] for i in pos],
            "freq": {"lema": por_lema, "norm": por_norm},
        }
    return e


def _c1(estruturas: list[dict], campo: str, chave: str, filtro, filtrar: bool) -> int:
    total = 0
    for e in estruturas:
        for outra, c in e["freq"][campo].get(chave, ()):
            if filtrar:
                nm, lm = (outra, chave) if campo == "lema" else (chave, outra)
                if token_vazio(nm, lm, filtro):
                    continue
            total += c
    return total


# ---------- consulta ----------

def calcular(pasta_projeto, metas: list[dict], consulta: str, por: str = "lema", esquerda: int = 5, direita: int = 5,
             filtro=frozenset(), filtrar: bool = True, min_freq: int = 3, min_freq_colocado: int = 5,
             ordem: str = "ll", limite: int = 50, fronteira: str = "bloco", repulsao: bool = False) -> dict:
    """Colocados do nó ``consulta`` nos documentos ``metas`` (já filtrados pelo escopo). Ver o docstring do módulo."""
    if ordem not in ORDENS:
        raise ValueError(f"Ordem inválida '{ordem}'.")
    if fronteira not in FRONTEIRAS:
        raise ValueError(f"Fronteira inválida '{fronteira}'.")
    campo = "norm" if por == "forma" else "lema"  # com por="termo" a estrutura já traz os termos em "lema"
    itens = dados.compilar_consulta(consulta)
    rels = [*range(-esquerda, 0), *range(1, direita + 1)]

    estruturas: list[dict] = []
    n_total = r1 = f_no = docs_com_no = 0
    formas_no: Counter = Counter()
    o11: Counter = Counter()
    pares: Counter = Counter()
    perfil: Counter = Counter()  # (chave, rel) -> pares

    for m in metas:
        tk = dados.carregar_tokens(pasta_projeto, m["id"], termos=(por == "termo"))
        if tk is None:
            continue
        e = estrutura_do_documento(tk, por)
        estruturas.append(e)
        n_total += e["n"]
        if not itens:
            continue
        indice = dados.indice_do_documento(tk)["termo" if por == "termo" else campo]
        rank = e["rank"]
        nos = sorted({rank[p] for k in dados.chaves_que_casam(itens, indice) for p in indice[k] if rank[p] >= 0})
        if not nos:
            continue
        docs_com_no += 1
        f_no += len(nos)
        chaves, norm_c, lema_c = e[campo], e["norm"], e["lema"]
        formas_no.update(chaves[k] for k in nos)
        conjunto_nos = set(nos)
        seg = e["bloco"] if fronteira == "bloco" else None
        n_doc = e["n"]
        cobertura: dict[int, int] = {}
        for k in nos:
            s = seg[k] if seg is not None else None
            for passo, limite_lado in ((-1, esquerda), (1, direita)):
                for d in range(1, limite_lado + 1):
                    j = k + passo * d
                    if j < 0 or j >= n_doc or (seg is not None and seg[j] != s):
                        break  # fronteira: a janela é truncada
                    if j in conjunto_nos:
                        continue  # o nó ocupa a posição, mas não é colocado de si mesmo
                    cobertura[j] = cobertura.get(j, 0) + 1
                    if not filtrar or not token_vazio(norm_c[j], lema_c[j], filtro):
                        perfil[(chaves[j], passo * d)] += 1
        r1 += len(cobertura)
        for j, vezes in cobertura.items():
            if filtrar and token_vazio(norm_c[j], lema_c[j], filtro):
                continue
            o11[chaves[j]] += 1
            pares[chaves[j]] += vezes

    colocados = []
    for chave, o in o11.items():
        if o < min_freq:
            continue
        c1 = _c1(estruturas, campo, chave, filtro, filtrar)
        if c1 < min_freq_colocado or c1 >= n_total or r1 >= n_total:
            continue
        med = medidas(o, r1, c1, n_total, f_no)
        if not repulsao and med["ll"] < 0:
            continue
        colocados.append({"termo": chave, **med, "pares": pares[chave]})

    chave_ordem = {"ll": "ll", "mi": "mi", "freq": "o11", "logdice": "logdice", "t": "t"}[ordem]
    colocados.sort(key=lambda c: (-c[chave_ordem], -c["o11"], c["termo"]))
    total_candidatos = len(colocados)
    colocados = colocados[: max(0, limite)]
    for c in colocados:
        c["posicoes"] = {str(r): perfil.get((c["termo"], r), 0) for r in rels}
        for k in ("e11", "ll", "mi", "t", "logdice"):
            c[k] = round(c[k], 4)

    return {
        "no": {"consulta": consulta, "por": por, "termos": [t["texto"] for t in itens],
               "formas": [{"termo": t, "freq": f} for t, f in sorted(formas_no.items(), key=lambda kv: (-kv[1], kv[0]))[:30]]},
        "N": n_total, "R1": r1, "ocorrencias_no": f_no, "documentos": len(estruturas), "documentos_com_no": docs_com_no,
        "total_candidatos": total_candidatos, "colocados": colocados,
        "parametros": {"por": por, "esquerda": esquerda, "direita": direita, "vazias": "filtrar" if filtrar else "manter",
                       "min_freq": min_freq, "min_freq_colocado": min_freq_colocado, "ordem": ordem, "limite": limite,
                       "fronteira": fronteira, "repulsao": repulsao},
        "metodologia": METODOLOGIA,
        "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE,
        "nao_equivalente": NAO_EQUIVALENTE,
    }
