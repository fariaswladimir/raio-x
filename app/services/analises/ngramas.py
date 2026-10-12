"""5.5 - N-gramas (clusters): sequências contíguas de 2 a 6 palavras e suas frequências.

Equivale ao *Clusters/N-Grams* do AntConc e ao *Phrases* do Voyant. **Não é o mesmo que os termos compostos (4.3)**:
aqui a lista é *exaustiva* (todo n-grama que passa nos filtros de frequência e de palavras vazias, sem teste de
associação) e serve para explorar o texto; os termos compostos (4.3) são uma lista *curada*, pontuada por log-likelihood
e usada como unidade de contagem nas demais análises. Biber, Conrad e Cortes (2004) chamam n-gramas frequentes de
*lexical bundles*.

Unidade e contiguidade
----------------------
- ``por="forma"`` (padrão, como o AntConc) conta a forma em minúsculas (``norm``); ``por="lema"`` conta o lema.
- Só tokens do corpo (``incluir``) com >= 2 letras (o universo do vocabulário). Um n-grama nunca atravessa bloco
  (página/seção) nem parágrafo (linha em branco); entre os tokens só cabem espaço, no máximo uma quebra de linha e,
  com ``quebrar_pontuacao=True`` (padrão), no máximo um hífen: vírgula, ponto, ponto e vírgula, parênteses etc.
  quebram (a lógica é a de ``termos_compostos.sequencias``). Com ``quebrar_pontuacao=False`` a pontuação é ignorada
  (como o AntConc com os símbolos fora do token).
- Palavras vazias (filtro do projeto): ``todas`` mantém todos os n-gramas (AntConc); ``sem_bordas`` (padrão) descarta
  os que começam ou terminam com palavra vazia; ``sem_vazias`` descarta os que contêm qualquer uma.

Métricas
--------
``freq`` ocorrências no escopo; ``por_10k`` = freq / palavras contadas do escopo x 10.000 (mesmo denominador das
frequências); ``docs`` = documentos em que aparece (a *faixa*, ``range`` do AntConc); ``concentracao`` = parcela das
ocorrências que está no documento onde o n-grama é mais frequente (1,0 = todas num só documento). Escolhida em lugar
do D de Juilland por ser direta de ler e não depender de pesos por tamanho de documento; os dois ficam próximos de
"disperso" quando ``concentracao`` é baixa e ``docs`` é alto.

Filtros e ordem
---------------
``min_freq`` (padrão 3) e ``min_docs`` (padrão 2); ``contem`` = busca estilo *Clusters* do AntConc (n-gramas que
contêm o termo, por forma ou lema conforme ``por``; vírgula separa alternativas e ``*`` é curinga) com
``posicao`` = qualquer | inicio | fim. Ordem: ``freq`` (padrão), ``docs`` (depois ``freq``) ou ``n`` (maiores
primeiro, depois ``freq``); desempate pelo n-grama. Paginação por ``offset``/``limite``.

Desempenho
----------
Cada tamanho n é contado separadamente (memória limitada) e o resultado (já com ``min_freq`` aplicado) fica num cache
em processo por (documentos do escopo, unidade, n, palavras vazias, pontuação, ``min_freq``), validado pelo mtime dos
arquivos de tokens e de texto limpo (se o pipeline for reexecutado, o cache deixa de valer). ``contem``, ``min_docs``,
ordem e paginação são aplicados sobre o cache.
"""
from collections import Counter, OrderedDict
import threading

from app.services import parametros as parametros_do_projeto
from app.services import ruido
from app.services.analises import dados
from app.services.etapas.limpeza import caminho_limpo
from app.services.etapas.linguistica import caminho_tokens
from app.services.palavras_vazias import token_vazio
from app.services.termos_compostos import sequencias

POR = ("forma", "lema")
STOP = ("todas", "sem_bordas", "sem_vazias")
POSICOES = ("qualquer", "inicio", "fim")
ORDENS = ("freq", "docs", "n")
N_MAXIMO = 6

_CACHE: OrderedDict = OrderedDict()
_TRAVA = threading.Lock()
_MAX_CACHE = 48


def limpar_cache() -> None:
    with _TRAVA:
        _CACHE.clear()
        _PREPARO.clear()


def _validar(por, n_min, n_max, stop, posicao, ordem) -> None:
    if por not in POR:
        raise ValueError(f"'por' inválido: {por}.")
    if not 2 <= n_min <= n_max <= N_MAXIMO:
        raise ValueError(f"Tamanhos inválidos: n_min={n_min}, n_max={n_max} (2 a {N_MAXIMO}, n_min <= n_max).")
    if stop not in STOP:
        raise ValueError(f"'stop' inválido: {stop}.")
    if posicao not in POSICOES:
        raise ValueError(f"'posicao' inválida: {posicao}.")
    if ordem not in ORDENS:
        raise ValueError(f"'ordem' inválida: {ordem}.")


def _marca_do_escopo(pasta, metas: list[dict]) -> tuple:
    marcas = []
    for m in metas:
        for caminho in (caminho_tokens(pasta, m["id"]), caminho_limpo(pasta, m["id"])):
            marcas.append((m["id"], dados._marca(caminho) if caminho.is_file() else None))
        marcas.append((m["id"], "ruido", ruido.marca_do_arquivo(pasta, m["id"]) if ruido.excluir_ruido(parametros_do_projeto.carregar(pasta)) else None))
    return tuple(marcas)


_PREPARO: OrderedDict = OrderedDict()  # (pasta, documento, mtime, pontuação, filtro) -> (sequências, vazias, contados)


def _preparo(pasta, meta: dict, quebrar: bool, filtro):
    """Sequências contíguas e marca de palavra vazia por token (independem de forma/lema; ficam em cache)."""
    chave = (str(pasta), meta["id"], _marca_do_escopo(pasta, [meta]), bool(quebrar), hash(filtro), len(filtro))
    with _TRAVA:
        achado = _PREPARO.get(chave)
        if achado is not None:
            _PREPARO.move_to_end(chave)
            return achado
    tk = dados.carregar_tokens(pasta, meta["id"])
    blocos = dados.carregar_blocos(pasta, meta["id"])
    if tk is None or blocos is None:
        return [], [], 0
    seqs = sequencias(tk, blocos, quebrar_pontuacao=quebrar)
    if ruido.excluir_ruido(parametros_do_projeto.carregar(pasta)):  # 3.4: segmentos de ruído não geram n-gramas
        seqs = ruido.subtrair_intervalos(seqs, ruido.intervalos_de_tokens(pasta, meta["id"]))
    norm, lema = tk["norm"], tk["lema"]
    vazias = [token_vazio(norm[i], lema[i], filtro) for i in range(tk["n"])]
    achado = (seqs, vazias, sum(b - a for a, b in seqs))  # tokens contados = corpo com >= 2 letras
    with _TRAVA:
        _PREPARO[chave] = achado
        while len(_PREPARO) > 256:
            _PREPARO.popitem(last=False)
    return achado


def _segmentos_do_documento(pasta, meta: dict, por: str, filtro, quebrar: bool):
    """Segmentos contíguos do documento: ([(unidades, vazias)], tokens contados)."""
    seqs, vazias, contados = _preparo(pasta, meta, quebrar, filtro)
    if not seqs:
        return [], contados
    tk = dados.carregar_tokens(pasta, meta["id"])
    unidades = tk["norm"] if por == "forma" else tk["lema"]
    return [(unidades[a:b], vazias[a:b]) for a, b in seqs], contados


def _contar_n(segmentos, n: int, stop: str) -> Counter:
    """Contagem dos n-gramas de tamanho ``n`` de um documento (tuplas de unidades)."""
    c: Counter = Counter()
    for unid, vz in segmentos:
        m = len(unid)
        if m < n:
            continue
        if stop == "todas":
            c.update(zip(*(unid[k:] for k in range(n))))
        elif stop == "sem_bordas":
            c.update(tuple(unid[k:k + n]) for k in range(m - n + 1) if not vz[k] and not vz[k + n - 1])
        else:  # sem_vazias: corridas de palavras não vazias
            i = 0
            while i < m:
                if vz[i]:
                    i += 1
                    continue
                j = i
                while j < m and not vz[j]:
                    j += 1
                if j - i >= n:
                    c.update(zip(*(unid[i + k:j] for k in range(n))))
                i = j
    return c


def _linhas_de_n(metas, n, stop, min_freq, prep) -> list[tuple]:
    """Linhas ``(tupla, freq, docs, maior_freq_num_documento)`` com freq >= min_freq, para o tamanho n."""
    locais = [_contar_n(prep[m["id"]], n, stop) for m in metas]
    total: Counter = Counter()
    for loc in locais:
        total.update(loc)
    ficam = {g for g, f in total.items() if f >= min_freq}
    df: Counter = Counter()
    maximo: dict = {}
    for loc in locais:
        for g, c in loc.items():
            if g in ficam:
                df[g] += 1
                if c > maximo.get(g, 0):
                    maximo[g] = c
    return [(g, total[g], df[g], maximo[g]) for g in ficam]


def _agregar(pasta, metas, n_min, n_max, por, stop, quebrar, min_freq, filtro):
    """Linhas de todos os tamanhos pedidos e palavras contadas, usando o cache por tamanho."""
    marca = _marca_do_escopo(pasta, metas)
    base = (str(pasta), tuple(m["id"] for m in metas), marca, por, stop, bool(quebrar), min_freq, hash(filtro), len(filtro))
    linhas: list[tuple] = []
    tokens = None
    prep = None
    for n in range(n_min, n_max + 1):
        chave = (*base, n)
        with _TRAVA:
            achado = _CACHE.get(chave)
            if achado is not None:
                _CACHE.move_to_end(chave)
        if achado is None:
            if prep is None:
                prep, tokens_prep = {}, 0
                for m in metas:
                    prep[m["id"]], contados = _segmentos_do_documento(pasta, m, por, filtro, quebrar)
                    tokens_prep += contados
                tokens = tokens_prep
            achado = {"linhas": _linhas_de_n(metas, n, stop, min_freq, prep), "tokens": tokens}
            with _TRAVA:
                _CACHE[chave] = achado
                while len(_CACHE) > _MAX_CACHE:
                    _CACHE.popitem(last=False)
        linhas.extend(achado["linhas"])
        if tokens is None:
            tokens = achado["tokens"]
    return linhas, tokens or 0


def _casador_contem(contem: str, posicao: str):
    itens = dados.compilar_consulta(contem or "")
    if not itens:
        return None

    def casa_unidade(u: str) -> bool:
        return any(dados.casa(i, u) for i in itens)

    if posicao == "inicio":
        return lambda g: casa_unidade(g[0])
    if posicao == "fim":
        return lambda g: casa_unidade(g[-1])
    return lambda g: any(casa_unidade(u) for u in g)


def listar(pasta, metas: list[dict], filtro, por: str = "forma", n_min: int = 2, n_max: int = 4,
           stop: str = "sem_bordas", quebrar_pontuacao: bool = True, min_freq: int = 3, min_docs: int = 2,
           contem: str = "", posicao: str = "qualquer", ordem: str = "freq", limite: int = 100, offset: int = 0) -> dict:
    """N-gramas dos documentos ``metas`` (já filtrados pelo escopo). Ver o docstring do módulo."""
    _validar(por, n_min, n_max, stop, posicao, ordem)
    min_freq = max(1, int(min_freq))
    linhas, tokens = _agregar(pasta, metas, n_min, n_max, por, stop, quebrar_pontuacao, min_freq, filtro)
    casador = _casador_contem(contem, posicao)
    escolhidas = [r for r in linhas if r[2] >= min_docs and (casador is None or casador(r[0]))]
    if ordem == "docs":
        escolhidas.sort(key=lambda r: (-r[2], -r[1], r[0]))
    elif ordem == "n":
        escolhidas.sort(key=lambda r: (-len(r[0]), -r[1], r[0]))
    else:
        escolhidas.sort(key=lambda r: (-r[1], r[0]))
    pagina = escolhidas[max(0, offset): max(0, offset) + max(0, limite)]
    itens = [{
        "ngrama": " ".join(g), "n": len(g), "freq": f, "por_10k": round(f / tokens * 10000, 2) if tokens else 0.0,
        "docs": d, "concentracao": round(mx / f, 3),
    } for g, f, d, mx in pagina]
    por_n = {n: sum(1 for r in escolhidas if len(r[0]) == n) for n in range(n_min, n_max + 1)}
    return {
        "por": por, "n_min": n_min, "n_max": n_max, "stop": stop, "quebrar_pontuacao": quebrar_pontuacao,
        "min_freq": min_freq, "min_docs": min_docs, "contem": contem or "", "posicao": posicao, "ordem": ordem,
        "documentos": len(metas), "tokens": tokens, "total": len(escolhidas), "total_por_n": por_n,
        "offset": max(0, offset), "limite": limite, "itens": itens,
    }
