"""5.3 - Concordância (KWIC) com página e citação. Equivale ao Contexts do Voyant e ao Concordance do AntConc.

Consulta
--------
``consulta`` = termos separados por vírgula, com curinga ``*`` (``agent*``). ``por="lema"`` (padrão) casa
com o lema do token (``agent`` acha agents, agent's); ``por="forma"`` casa com a forma em minúsculas
(``norm``); ``por="termo"`` (4.3) casa com o termo (composto ou, nos demais tokens, o lema), e a linha mostra o
trecho inteiro do termo composto em ``termo`` (as janelas contam a partir do trecho). A consulta é normalizada como os tokens (minúsculas, NFKC, apóstrofo reto).

Frase (5.5)
-----------
Consulta entre aspas (``"human oversight"``) busca a *sequência* de palavras, por forma ou lema (``por``), com ``*`` por
palavra; é o que abre um n-grama da aba de n-gramas. As palavras precisam ser contíguas com as mesmas regras dos
n-gramas (mesmo bloco, sem parágrafo entre elas e, com ``quebrar=True``, sem pontuação além de hífen); a ocorrência
do corpo apenas (seções excluídas quebram a sequência) e a linha destaca a frase inteira. ``por="termo"`` não aceita frase.

Contexto
--------
Esquerda/direita são recortes do **texto limpo do bloco** (cache/limpo/<id>.json) entre os deslocamentos
dos tokens vizinhos, de modo que a pontuação original é preservada (espaços e quebras de linha viram um
espaço). Cada bloco é uma página/seção: se a janela atravessa a fronteira de blocos, os trechos são unidos
por `` … `` (reticências entre espaços), para não sugerir continuidade que o texto não tem. Por padrão
só entram ocorrências do corpo; com ``incluir_excluidas`` entram também as de seções excluídas
(referências etc.). Sem essa opção, o contexto de uma ocorrência do corpo para na fronteira da seção excluída.

Desempenho
----------
Tokens e blocos ficam no cache LRU de ``dados`` e cada documento tem índice invertido, de modo que só as
linhas da página pedida (``offset``/``limit``) são montadas.
"""
import re
from bisect import bisect_right

from app.services import ruido
from app.services.analises import dados
from app.services.termos_compostos import fim_do_termo, sequencias

ORDENS = ("corpus", "esquerda", "direita")
MARCA_QUEBRA = " … "
_ESPACOS = re.compile(r"\s+")


def _limpo(texto: str) -> str:
    return _ESPACOS.sub(" ", texto)


def _janela_de_tokens(tk: dict, i: int, k: int, incluir_excluidas: bool, e: int | None = None) -> tuple[int, int]:
    """Intervalo [a, b] de tokens do contexto (sem atravessar seção excluída, salvo se pedido).

    ``e`` = último token do trecho que começa em ``i`` (termo composto); padrão ``i``."""
    e = i if e is None else e
    n = tk["n"]
    a, b = max(0, i - k), min(n - 1, e + k)
    if not incluir_excluidas:
        inc = tk["incluir"]
        while a < i and not all(inc[a:i]):
            a += 1
        while b > e and not all(inc[e + 1:b + 1]):
            b -= 1
    return a, b


def contexto_do_token(tk: dict, blocos: list[dict], i: int, k: int, incluir_excluidas: bool = False,
                      e: int | None = None) -> tuple[str, str, str]:
    """``(esquerda, termo, direita)`` brutos (espaços colapsados) em torno do token ``i`` com ``k`` tokens de cada lado.

    ``e`` = último token do trecho (termo composto de ``i`` a ``e``, no mesmo bloco); ``termo`` é o texto do trecho."""
    e = i if e is None else e
    a, b = _janela_de_tokens(tk, i, k, incluir_excluidas or not tk["incluir"][i], e)
    bloco, inicio, fim = tk["bloco"], tk["inicio"], tk["fim"]
    antes: list[str] = []
    depois: list[str] = []
    esq_no_bloco = dir_no_bloco = ""
    j = a
    while j <= b:  # segmentos de tokens consecutivos do mesmo bloco
        j1 = j
        while j1 + 1 <= b and bloco[j1 + 1] == bloco[j]:
            j1 += 1
        texto = blocos[bloco[j]]["texto"]
        # segmento seguido de outro bloco: vai até o fim do texto do bloco (preserva o ponto final etc.)
        fim_seg = len(texto) if j1 < b else fim[j1]
        if j <= i <= j1:
            esq_no_bloco = texto[inicio[j]:inicio[i]]
            dir_no_bloco = texto[fim[e]:fim_seg]
        elif j1 < i:
            antes.append(texto[inicio[j]:fim_seg])
        else:
            depois.append(texto[inicio[j]:fim_seg])
        j = j1 + 1
    esq = MARCA_QUEBRA.join([*(_limpo(t).strip() for t in antes), _limpo(esq_no_bloco)]) if antes else _limpo(esq_no_bloco)
    dir_ = MARCA_QUEBRA.join([_limpo(dir_no_bloco), *(_limpo(t).strip() for t in depois)]) if depois else _limpo(dir_no_bloco)
    termo = tk["forma"][i] if e == i else _limpo(blocos[tk["bloco"][i]]["texto"][inicio[i]:fim[e]])
    return esq, termo, dir_


def _linha(meta: dict, tk: dict, blocos: list[dict], i: int, k: int, incluir_excluidas: bool, por: str = "lema",
           fim: int | None = None) -> dict:
    e = fim if fim is not None else (fim_do_termo(tk["termo"], i) if por == "termo" else i)
    esq, termo, dir_ = contexto_do_token(tk, blocos, i, k, incluir_excluidas, e)
    return {
        "documento_id": meta["id"], "arquivo": meta["arquivo"], "rotulo": meta["rotulo"],
        "pagina": tk["pagina"][i], "secao": tk["secoes"][tk["secao"][i]], "posicao": i,
        "corpo": bool(tk["incluir"][i]),
        "esquerda": esq.strip(), "termo": termo, "direita": dir_.strip(),
    }


def frase_da_consulta(consulta: str) -> list[dict] | None:
    """Consulta entre aspas ("human oversight") -> itens compilados, um por palavra; ``None`` se não for frase."""
    t = consulta.strip()
    if len(t) >= 2 and t[0] in "\"“" and t[-1] in "\"”":
        palavras = t[1:-1].split()
        if len(palavras) >= 2:
            return [i for w in palavras for i in dados.compilar_consulta(w)[:1]]
    return None


def posicoes_da_frase(tk: dict, seqs: list[tuple[int, int]], itens: list[dict], campo: str) -> list[int]:
    """Posições iniciais (em ordem) da frase ``itens`` num documento, dadas as sequências ligadas ``seqs``
    (``termos_compostos.sequencias``). ``campo`` = "lema" ou "norm". Reutilizada pelo dicionário (6.4)."""
    inicios = [a for a, _ in seqs]
    tam = len(itens)
    unid = tk[campo]
    indice = dados.indice_do_documento(tk)[campo]
    candidatas: set[int] = set()
    for chave in dados.chaves_que_casam(itens[:1], indice):
        candidatas.update(indice[chave])
    achadas = []
    for p in sorted(candidatas):
        k = bisect_right(inicios, p) - 1
        if k < 0 or not (seqs[k][0] <= p and p + tam <= seqs[k][1]):
            continue  # fora do corpo ou a sequência não comporta a frase
        if all(dados.casa(itens[j], unid[p + j]) for j in range(1, tam)):
            achadas.append(p)
    return achadas


def _ocorrencias_frase(pasta_projeto, metas: list[dict], itens: list[dict], por: str, quebrar: bool):
    """Ocorrências da frase: [(ordem_doc, início, meta, tokens, fim)] e as formas (sequências) casadas."""
    campo = "lema" if por == "lema" else "norm"
    achadas: list[tuple] = []
    formas: dict[str, int] = {}
    tam = len(itens)
    for ordem_doc, m in enumerate(metas):
        tk = dados.carregar_tokens(pasta_projeto, m["id"])
        blocos = dados.carregar_blocos(pasta_projeto, m["id"])
        if tk is None or blocos is None:
            continue
        seqs = sequencias(tk, blocos, quebrar_pontuacao=quebrar)
        unid = tk[campo]
        for p in posicoes_da_frase(tk, seqs, itens, campo):
            achadas.append((ordem_doc, p, m, tk, p + tam - 1))
            f = " ".join(tk["norm"][p:p + tam]) if campo == "norm" else " ".join(unid[p:p + tam])
            formas[f] = formas.get(f, 0) + 1
    return achadas, formas


_PARTES = re.compile(r'"[^"]*"|“[^”]*”|[^,]+')


def partes_da_consulta(consulta: str) -> list[str]:
    """Separa a consulta por vírgula, sem quebrar frases entre aspas: ``agent*, "human oversight"`` -> 2 partes."""
    return [p.strip() for p in _PARTES.findall(consulta) if p.strip()]


def _ocorrencias(pasta_projeto, metas: list[dict], consulta: str, por: str, incluir_excluidas: bool, quebrar: bool = True):
    """Todas as ocorrências: [(ordem_doc, posição, meta, tokens, fim|None)] em ordem de corpus + as formas casadas."""
    partes = partes_da_consulta(consulta)
    if len(partes) > 1 and any(frase_da_consulta(p) is not None for p in partes):
        return _ocorrencias_mistas(pasta_projeto, metas, partes, por, incluir_excluidas, quebrar)
    frase = frase_da_consulta(consulta)
    if frase is not None:
        if por == "termo":
            raise ValueError("Consulta por frase (entre aspas) vale para lema ou forma, não para termo.")
        return _ocorrencias_frase(pasta_projeto, metas, frase, por, quebrar)
    consulta = consulta.strip().strip("\"“”")
    itens = dados.compilar_consulta(consulta)
    campo = {"lema": "lema", "termo": "termo"}.get(por, "norm")
    achadas: list[tuple] = []
    formas: dict[str, int] = {}
    for ordem_doc, m in enumerate(metas):
        tk = dados.carregar_tokens(pasta_projeto, m["id"], termos=(por == "termo"))
        if tk is None or not itens:
            continue
        indice = dados.indice_do_documento(tk)[campo]
        posicoes: set[int] = set()
        for chave in dados.chaves_que_casam(itens, indice):
            posicoes.update(indice[chave])
        inc = tk["incluir"]
        for p in sorted(posicoes):
            if incluir_excluidas or inc[p]:
                achadas.append((ordem_doc, p, m, tk, None))
                formas[tk[campo][p]] = formas.get(tk[campo][p], 0) + 1
    return achadas, formas


def _ocorrencias_mistas(pasta_projeto, metas, partes, por, incluir_excluidas, quebrar):
    """Consulta com palavras (curinga) e frases entre aspas juntas (ex.: o dicionário 6.4): une as ocorrências,
    sem repetir a mesma posição inicial (a frase prevalece sobre a palavra que começa no mesmo token)."""
    palavras = [p.strip('"“”') for p in partes if frase_da_consulta(p) is None]
    unidas: dict[tuple, tuple] = {}
    formas: dict[str, int] = {}
    grupos = ([", ".join(palavras)] if palavras else []) + [p for p in partes if frase_da_consulta(p) is not None]
    for g in grupos:
        achadas, _ = _ocorrencias(pasta_projeto, metas, g, por, incluir_excluidas, quebrar)
        for o in achadas:
            chave = (o[0], o[1])
            if chave not in unidas or (o[4] is not None and unidas[chave][4] is None):
                unidas[chave] = o
    ordem = sorted(unidas.values(), key=lambda o: (o[0], o[1]))
    campo = "lema" if por == "lema" else ("termo" if por == "termo" else "norm")
    for o in ordem:
        tk, p, fim = o[3], o[1], o[4]
        f = " ".join(tk["norm" if campo == "norm" else campo][p:(fim if fim is not None else p) + 1])
        formas[f] = formas.get(f, 0) + 1
    return ordem, formas


def _chave_ordem(ordem: str, ocorrencia, por: str = "lema"):
    ordem_doc, p, _, tk, fim = ocorrencia
    norm = tk["norm"]
    n = tk["n"]
    if ordem == "direita" and fim is not None:
        p = fim  # frase: a "direita" conta a partir do fim da frase
    elif por == "termo" and ordem == "direita":
        p = fim_do_termo(tk["termo"], p)  # a "direita" conta a partir do fim do trecho
    if ordem == "esquerda":  # L1, L2, depois ordem do corpus
        return (norm[p - 1] if p >= 1 else "", norm[p - 2] if p >= 2 else "", ordem_doc, p)
    return (norm[p + 1] if p + 1 < n else "", norm[p + 2] if p + 2 < n else "", ordem_doc, p)


def buscar(pasta_projeto, metas: list[dict], consulta: str, por: str = "lema", janela: int = 10,
           ordem: str = "corpus", offset: int = 0, limit: int = 200, incluir_excluidas: bool = False,
           quebrar: bool = True) -> dict:
    """Concordância da ``consulta`` nos documentos ``metas`` (já filtrados pelo escopo), paginada.

    ``quebrar`` (só para frase entre aspas): pontuação entre as palavras quebra a sequência (como nos n-gramas)."""
    achadas, formas = _ocorrencias(pasta_projeto, metas, consulta, por, incluir_excluidas, quebrar)
    if ordem in ("esquerda", "direita"):
        achadas.sort(key=lambda o: _chave_ordem(ordem, o, por))
    pagina = achadas[max(0, offset): max(0, offset) + max(0, limit)]
    blocos_por_doc: dict[int, list[dict]] = {}
    for _, _, m, _, _ in pagina:
        if m["id"] not in blocos_por_doc:
            blocos_por_doc[m["id"]] = dados.carregar_blocos(pasta_projeto, m["id"]) or []
    itens = [_linha(m, tk, blocos_por_doc[m["id"]], p, janela, incluir_excluidas, por, fim) for _, p, m, tk, fim in pagina]
    intervalos: dict[int, list] = {}
    for it in itens:  # 3.4: marca de segmento de ruído (continua visível na concordância)
        d = it["documento_id"]
        if d not in intervalos:
            intervalos[d] = ruido.intervalos_de_tokens(pasta_projeto, d)
        it["ruido"] = ruido.motivo_do_token(intervalos[d], it["posicao"])
    return {
        "consulta": consulta, "por": por, "janela": janela, "ordem": ordem, "incluir_excluidas": incluir_excluidas,
        "total": len(achadas), "documentos_com_ocorrencias": len({o[2]["id"] for o in achadas}),
        "formas": [{"forma": f, "freq": c} for f, c in sorted(formas.items(), key=lambda kv: (-kv[1], kv[0]))[:30]],
        "offset": max(0, offset), "limit": limit, "itens": itens,
    }


def contexto_ampliado(pasta_projeto, meta: dict, posicao: int, janela: int = 60, incluir_excluidas: bool = False) -> dict | None:
    """Contexto de uma ocorrência (±``janela`` tokens) com a citação pronta: "(rótulo, p. N)"."""
    tk = dados.carregar_tokens(pasta_projeto, meta["id"])
    blocos = dados.carregar_blocos(pasta_projeto, meta["id"])
    if tk is None or blocos is None or not 0 <= posicao < tk["n"]:
        return None
    esq, termo, dir_ = contexto_do_token(tk, blocos, posicao, janela, incluir_excluidas)
    pagina = tk["pagina"][posicao]
    citacao = f"({meta['rotulo']}, p. {pagina})" if pagina is not None else f"({meta['rotulo']})"
    trecho = (esq + termo + dir_).strip()
    return {
        "documento_id": meta["id"], "arquivo": meta["arquivo"], "rotulo": meta["rotulo"], "pagina": pagina,
        "secao": tk["secoes"][tk["secao"][posicao]], "posicao": posicao, "janela": janela,
        "esquerda": esq.lstrip(), "termo": termo, "direita": dir_.rstrip(),
        "trecho": trecho, "citacao": citacao, "citacao_completa": f"“…{trecho}…” {citacao}",
    }
