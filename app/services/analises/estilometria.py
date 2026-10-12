"""15.6 - Estilometria: Delta de Burrows e variantes, agrupamento, árvore de consenso, PCA e MDS dos perfis de estilo.

Conferido contra o pacote **stylo** 0.7.71 do R (Eder, Rybicki e Kestemont, 2016): ``dist.delta``, ``dist.argamon``,
``dist.eder``, ``dist.simple``, ``dist.wurzburg``, ``dist.cosine``, ``hclust(method = "ward.D" | "average")``,
``prcomp`` e ``ape::prop.part`` dão os mesmos números (até 1e-9) na mesma tabela de frequências (ver
``tests/test_frente156_estilometria.py``).

Atributos (features)
--------------------
As ``mfw`` **palavras mais frequentes** do corpus pela **forma** (superfície em minúsculas, ``norm`` dos tokens; não o
lema), **com** as palavras vazias: na estilometria as palavras funcionais são o sinal. Só tokens do corpo
(``incluir`` = 1: sem referências nem seções excluídas) e, com ``limpeza.excluir_ruido`` ligado, sem os segmentos de
ruído da 3.4 (autores, tabelas, cláusulas repetidas). Números e símbolos já não são tokens (o tokenizador só aceita
palavras que começam por letra).

- Ordem das palavras: frequência absoluta somada sobre **todas as unidades** (como ``stylo::make.frequency.list``, que
  junta os tokens do corpus: documentos longos pesam mais); empate pela ordem alfabética (código Unicode). O R ordena os
  empates pela colação do sistema: em empates exatos no fim da lista a ordem pode diferir.
- Corte (*culling*, Hoover 2004): fica a palavra presente (frequência > 0) em pelo menos ``culling``% das unidades,
  aplicado **antes** de tomar as ``mfw`` primeiras (como ``stylo::perform.culling`` seguido de ``[, 1:mfw]``).
  ``culling`` = 0 desliga o corte.
- Se o corpus tem menos palavras do que ``mfw``, usam-se todas (``mfw_efetivo``).

Unidade
-------
``documento`` (padrão): cada documento é uma linha. ``amostra``: o texto do corpo de cada documento é cortado em
amostras consecutivas de ``tamanho_amostra`` tokens (padrão 2.000; como o ``sampling = "normal.sampling"`` do stylo); o
resto final menor que o tamanho é descartado e documentos menores que uma amostra saem (``excluidos``). Amostras de
tamanho fixo tornam comparáveis documentos de extensões muito diferentes (a frequência relativa de palavras raras é
instável em textos curtos) e permitem ver se as amostras de um mesmo documento se agrupam (``coesao``).

Frequências e escores z
-----------------------
``f(w, u)`` = 100 × ocorrências de w na unidade u / nº de tokens da unidade (em %, como o stylo). Escore z por palavra,
sobre as unidades da análise: ``z = (f − média) / dp``, com o **desvio-padrão amostral (n − 1)**, que é o do
``scale()`` do R usado pelo stylo. Palavras de dp = 0 (frequência idêntica em todas as unidades) não têm escore z e
saem das medidas baseadas em z (o stylo daria NaN; o ``dist.wurzburg`` também as remove); ``n`` abaixo é o nº de
palavras que ficaram.

Distâncias (Evert et al., 2017; definições exatas do stylo 0.7.71)
------------------------------------------------------------------
- ``delta_classico`` (Burrows, 2002): ``Δ(a, b) = (1/n) Σ_i |z_i(a) − z_i(b)|`` (Manhattan dos z dividida por n).
- ``argamon`` (Delta quadrático/linear de Argamon, 2008): ``sqrt(Σ_i (z_i(a) − z_i(b))²) / n``. O stylo divide a
  euclidiana por n (Argamon não divide): só muda a escala, não a ordem nem os agrupamentos.
- ``eder`` (Delta de Eder): ``Σ_i |w_i z_i(a) − w_i z_i(b)|`` com ``w_i = (n − i + 2)/n`` para a palavra de posição
  i = 1..n (o código do stylo usa ``(1 + n:1)/n``, de (n+1)/n a 2/n; a fórmula costuma ser citada como
  ``(n − i + 1)/n``). Seguimos o stylo, sem dividir por n.
- ``eder_simples`` (Delta simples de Eder): ``Σ_i |sqrt(f_i(a)) − sqrt(f_i(b))|`` sobre as frequências em %, sem z.
- ``cosine_delta`` (Smith e Aldridge, 2011; "Delta de Würzburg"): ``1 − cos(z(a), z(b))``. Evert et al. (2017)
  mostram que é a variante mais robusta ao nº de palavras.
- ``cosseno``: ``1 − cos(f(a), f(b))`` sobre as frequências em % (sem z; ``dist.cosine`` do stylo), só para comparar.

Agrupamento, consenso e mapas
-----------------------------
- Hierárquico sobre a matriz de distâncias, como a "Cluster Analysis" do stylo: ``ward`` = ``hclust(method="ward.D")``
  (a opção "ward" do stylo; Lance-Williams aplicado à própria distância. Implementado como o Ward do scipy sobre
  ``sqrt(D)`` com as alturas elevadas ao quadrado, o que é algebricamente o ward.D) ou ``average`` (UPGMA). Grupos:
  corte em k (informado ou automático = maior silhueta média sobre D, k de 2 a 8), numerados pela ordem das folhas.
- Consenso (aproximação da *bootstrap consensus tree* de Eder, 2017, que o stylo faz com ``ape::consensus``): uma
  árvore para cada faixa de MFW (``bandas``, padrão 100, 200, ..., 500; as maiores que o vocabulário disponível saem),
  mesma distância e ligação. ``clados``: cada grupo de unidades (clado com 2..N−1 folhas) com a fração de árvores em
  que aparece (igual a ``ape::prop.part``); a árvore de consenso de maioria é o conjunto dos clados com fração > 0,5
  (compatíveis entre si). ``pares``: fração de árvores em que dois documentos caem no mesmo grupo quando cada árvore é
  cortada no mesmo k. Não é *bootstrap* por reamostragem: as árvores variam só pelo nº de palavras, e com 5 faixas as
  frações andam de 0,2 em 0,2.
- PCA (como o "PCR"/"PCV" do stylo): ``correlacao`` (padrão) = componentes principais dos escores z (= ``prcomp(...,
  scale. = TRUE)``); ``covariancia`` = das frequências em % apenas centradas (= ``prcomp(...)``). ``cargas`` = vetores
  próprios (as palavras que puxam cada eixo, com sinal). Sinal de cada eixo fixado para a maior coordenada absoluta
  ser positiva.
- MDS clássico (Torgerson, = ``cmdscale``) sobre a matriz de distâncias.

Perfil de estilo por documento
------------------------------
Média dos escores z das unidades do documento: as palavras mais super e sub-representadas em relação ao corpus,
a cobertura das MFW (parte dos tokens que são MFW) e a distância média aos demais documentos (atipicidade).

**Cuidado de interpretação.** Neste tipo de corpus (revisão de literatura: muitos autores por documento, gêneros
diferentes — artigo, relatório, capítulo — e mais de um idioma), a distância estilométrica reflete sobretudo
**gênero/registro, idioma e tradução**, não autoria. Atribuição de autoria está fora do escopo (não há autores rotulados).
"""
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.cluster import hierarchy
from scipy.spatial.distance import cdist

from app.services import ruido as svc_ruido
from app.services.analises import agrupamento, dados, similaridade

DISTANCIAS = ("delta_classico", "argamon", "eder", "eder_simples", "cosine_delta", "cosseno")
NOMES_DISTANCIA = {
    "delta_classico": "Delta clássico (Burrows)", "argamon": "Delta quadrático (Argamon)", "eder": "Delta de Eder",
    "eder_simples": "Delta simples de Eder", "cosine_delta": "Cosine Delta (Würzburg)", "cosseno": "Cosseno das frequências",
}
USA_Z = {"delta_classico": True, "argamon": True, "eder": True, "cosine_delta": True, "eder_simples": False, "cosseno": False}
METODOS = ("ward", "average")
UNIDADES = ("documento", "amostra")
PCAS = ("correlacao", "covariancia")
PADRAO = {"mfw": 100, "culling": 0, "distancia": "delta_classico", "unidade": "documento", "tamanho_amostra": 2000}
BANDAS = (100, 200, 300, 400, 500)
MFW_MAX = 5000
K_MAX_AUTO = 8
N_VIZINHOS = 5
N_CARGAS = 12
N_PERFIL = 8
AVISO = ("Neste corpus os documentos têm muitos autores e gêneros diferentes (artigo, relatório, capítulo) e mais de um idioma: "
         "a distância estilométrica reflete sobretudo gênero/registro, idioma e tradução, não autoria. Atribuição de autoria "
         "está fora do escopo (não há autores rotulados).")
METODOLOGIA = (
    "Palavras mais frequentes (MFW) do corpus pela forma em minúsculas, com as palavras vazias, só do corpo e sem ruído; "
    "frequências relativas (%) e escores z com desvio-padrão amostral; distâncias Delta clássico (Burrows), Argamon, Eder, "
    "Eder simples, Cosine Delta (Würzburg) e cosseno com as definições do stylo 0.7.71; agrupamento hierárquico ward.D ou "
    "ligação média; consenso entre faixas de MFW (aproximação da árvore de consenso de Eder, 2017); PCA dos escores z "
    "(correlação) ou das frequências (covariância); MDS clássico."
)
FERRAMENTA_EQUIVALENTE = "stylo (R): stylo(), dist.delta/argamon/eder/simple/wurzburg/cosine, Cluster Analysis, BCT, PCA"


# ---------- unidades de texto ----------

def tokens_do_corpo(pasta: Path, documento_id: int, excluir_ruido: bool = True) -> tuple[list[str], str | None] | None:
    """Formas em minúsculas (``norm``) dos tokens do corpo (``incluir`` = 1), sem os segmentos de ruído; e o idioma."""
    tk = dados.carregar_tokens(pasta, documento_id)
    if tk is None:
        return None
    norm, incluir = tk["norm"], tk["incluir"]
    fora = np.zeros(len(norm), dtype=bool)
    if excluir_ruido:
        for ini, fim, _m in svc_ruido.intervalos_de_tokens(pasta, documento_id):
            fora[ini:fim + 1] = True
    return [w for i, w in enumerate(norm) if incluir[i] and not fora[i]], tk.get("idioma")


def montar_unidades(textos: list[tuple[dict, list[str]]], unidade: str = "documento", tamanho: int = 2000) -> tuple[list[dict], list[dict]]:
    """``[{"doc": meta, "parte": j, "tokens": [...]}]`` e os excluídos. ``amostra`` = blocos consecutivos de ``tamanho`` tokens."""
    unidades, excluidos = [], []
    for meta, toks in textos:
        if not toks:
            excluidos.append({"id": meta["id"], "rotulo": meta["rotulo"], "motivo": "sem tokens no corpo"})
            continue
        if unidade == "documento":
            unidades.append({"doc": meta, "parte": 0, "tokens": toks})
            continue
        n = len(toks) // tamanho
        if n == 0:
            excluidos.append({"id": meta["id"], "rotulo": meta["rotulo"],
                              "motivo": f"menos de {tamanho} tokens no corpo ({len(toks)}): nenhuma amostra completa"})
            continue
        for j in range(n):
            unidades.append({"doc": meta, "parte": j + 1, "tokens": toks[j * tamanho:(j + 1) * tamanho]})
    return unidades, excluidos


# ---------- tabela de frequências ----------

def lista_de_palavras(contagens: list[Counter], culling: float = 0.0, maximo: int | None = None) -> list[str]:
    """Palavras por frequência somada (desc; empate alfabético), já com o corte de presença em ``culling``% das unidades."""
    total: Counter = Counter()
    for c in contagens:
        total.update(c)
    ordem = sorted(total, key=lambda w: (-total[w], w))
    if culling > 0:
        n = len(contagens)
        minimo = culling / 100.0
        saida = []
        for w in ordem:
            if sum(1 for c in contagens if c.get(w, 0) > 0) / n >= minimo - 1e-12:
                saida.append(w)
                if maximo and len(saida) >= maximo:
                    break
        return saida
    return ordem[:maximo] if maximo else ordem


def tabela_relativa(contagens: list[Counter], tamanhos: list[int], palavras: list[str]) -> np.ndarray:
    """Frequências relativas em % (unidades × palavras)."""
    f = np.zeros((len(contagens), len(palavras)))
    for i, (c, n) in enumerate(zip(contagens, tamanhos)):
        for j, w in enumerate(palavras):
            v = c.get(w)
            if v:
                f[i, j] = 100.0 * v / n
    return f


def escores_z(f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Escores z por coluna com dp amostral (n − 1), como ``scale()``; e a máscara das colunas com dp > 0."""
    media = f.mean(axis=0)
    dp = f.std(axis=0, ddof=1) if f.shape[0] > 1 else np.zeros(f.shape[1])
    ok = dp > 1e-12
    z = np.zeros_like(f)
    z[:, ok] = (f[:, ok] - media[ok]) / dp[ok]
    return z, ok


def _cosseno_dist(x: np.ndarray) -> np.ndarray:
    normas = np.sqrt((x ** 2).sum(axis=1))
    den = np.outer(normas, normas)
    s = np.divide(x @ x.T, den, out=np.zeros((x.shape[0], x.shape[0])), where=den > 0)
    d = 1.0 - s
    d = (d + d.T) / 2.0
    np.fill_diagonal(d, 0.0)
    return d


def _manhattan(x: np.ndarray) -> np.ndarray:
    return cdist(x, x, "cityblock")


def distancia(f: np.ndarray, medida: str) -> np.ndarray:
    """Matriz de distâncias (unidades × unidades) entre as linhas de ``f`` (frequências em %, colunas na ordem das MFW)."""
    if medida not in DISTANCIAS:
        raise ValueError(f"Distância inválida '{medida}': use {', '.join(DISTANCIAS)}.")
    if medida == "eder_simples":
        return _manhattan(np.sqrt(f))
    if medida == "cosseno":
        return _cosseno_dist(f)
    z, ok = escores_z(f)
    z = z[:, ok]
    n = z.shape[1]
    if n == 0:
        raise ValueError("Nenhuma palavra varia entre as unidades: não há escores z.")
    if medida == "delta_classico":
        return _manhattan(z) / n
    if medida == "argamon":
        return cdist(z, z, "euclidean") / n
    if medida == "eder":
        pesos = (n - np.arange(1, n + 1) + 2) / n  # (1 + n:1)/n do stylo
        return _manhattan(z * pesos)
    return _cosseno_dist(z)  # cosine_delta


# ---------- agrupamento e consenso ----------

def ligar(d: np.ndarray, metodo: str = "ward") -> np.ndarray:
    """Matriz Z (scipy) de ``hclust(d, "ward.D")`` ou ``hclust(d, "average")``."""
    if metodo not in METODOS:
        raise ValueError(f"Ligação inválida '{metodo}': use 'ward' ou 'average'.")
    n = d.shape[0]
    cond = np.maximum(d[np.triu_indices(n, 1)], 0.0)
    if metodo == "average":
        return hierarchy.linkage(cond, method="average")
    z = hierarchy.linkage(np.sqrt(cond), method="ward")
    z[:, 2] = z[:, 2] ** 2
    return z


def clados(z: np.ndarray) -> list[frozenset]:
    """Clados internos (2..N−1 folhas) da árvore, em ordem de fusão."""
    n = z.shape[0] + 1
    membros: list[frozenset] = [frozenset([i]) for i in range(n)]
    saida = []
    for a, b, _h, _t in z:
        novo = membros[int(a)] | membros[int(b)]
        membros.append(novo)
        if len(novo) < n:
            saida.append(novo)
    return saida


def cortar_k(z: np.ndarray, k: int) -> np.ndarray:
    """Rótulos 1..k numerados pela ordem das folhas."""
    bruto = hierarchy.cut_tree(z, n_clusters=k).ravel()
    novo: dict[int, int] = {}
    for i in hierarchy.leaves_list(z):
        novo.setdefault(int(bruto[i]), len(novo) + 1)
    return np.array([novo[int(b)] for b in bruto])


def escolher_k(z: np.ndarray, d: np.ndarray) -> tuple[int, list[dict]]:
    n = d.shape[0]
    if n < 3:
        return n, []
    sil = []
    for k in range(2, min(K_MAX_AUTO, n - 1) + 1):
        sil.append({"k": k, "silhueta": round(float(similaridade.silhueta(d, cortar_k(z, k))), 4)})
    melhor = max(sil, key=lambda r: (r["silhueta"], -r["k"]))
    return melhor["k"], sil


def consenso(arvores: list[np.ndarray], k: int) -> tuple[dict[frozenset, float], np.ndarray]:
    """Fração de árvores com cada clado e matriz de co-pertinência (mesmo grupo no corte em k)."""
    cont: Counter = Counter()
    n = arvores[0].shape[0] + 1
    junto = np.zeros((n, n))
    for z in arvores:
        cont.update(set(clados(z)))
        r = cortar_k(z, k)
        junto += (r[:, None] == r[None, :])
    m = len(arvores)
    return {c: v / m for c, v in cont.items()}, junto / m


# ---------- PCA ----------

def pca(x: np.ndarray, componentes: int = 2) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Coordenadas, cargas (componentes × colunas) e variância explicada (soma 1) do PCA das colunas centradas."""
    c = x - x.mean(axis=0, keepdims=True)
    u, s, vt = np.linalg.svd(c, full_matrices=False)
    total = float((s ** 2).sum())
    var = [float(v) / total for v in s ** 2] if total > 0 else [0.0] * len(s)
    coords = np.zeros((x.shape[0], componentes))
    cargas = np.zeros((componentes, x.shape[1]))
    for d in range(min(componentes, len(s))):
        col, ld = u[:, d] * s[d], vt[d].copy()
        i_max = int(np.argmax(np.abs(col)))
        if col[i_max] < 0:
            col, ld = -col, -ld
        coords[:, d], cargas[d] = col, ld
    return coords, cargas, var


# ---------- análise completa ----------

def _rotulo(u: dict) -> str:
    return u["doc"]["rotulo"] if u["parte"] == 0 else f"{u['doc']['rotulo']} [{u['parte']}]"


def validar(mfw: int, culling: float, distancia_: str, unidade: str, tamanho_amostra: int, metodo: str, pca_: str) -> None:
    if not 2 <= mfw <= MFW_MAX:
        raise ValueError(f"mfw deve estar entre 2 e {MFW_MAX}.")
    if not 0 <= culling <= 100:
        raise ValueError("culling deve estar entre 0 e 100 (%).")
    if distancia_ not in DISTANCIAS:
        raise ValueError(f"Distância inválida '{distancia_}': use {', '.join(DISTANCIAS)}.")
    if unidade not in UNIDADES:
        raise ValueError(f"Unidade inválida '{unidade}': use 'documento' ou 'amostra'.")
    if tamanho_amostra < 100:
        raise ValueError("tamanho_amostra deve ser >= 100 tokens.")
    if metodo not in METODOS:
        raise ValueError(f"Ligação inválida '{metodo}': use 'ward' ou 'average'.")
    if pca_ not in PCAS:
        raise ValueError(f"PCA inválido '{pca_}': use 'correlacao' ou 'covariancia'.")


def textos_do_corpus(pasta: Path, metas: list[dict], excluir_ruido: bool = True) -> list[tuple[dict, list[str]]]:
    saida = []
    for m in metas:
        r = tokens_do_corpo(pasta, m["id"], excluir_ruido)
        if r is None:
            continue
        toks, idioma = r
        saida.append(({**m, "idioma": idioma}, toks))
    return saida


def calcular(pasta: Path, metas: list[dict], mfw: int = 100, culling: float = 0, distancia_: str = "delta_classico",
             unidade: str = "documento", tamanho_amostra: int = 2000, metodo: str = "ward", k: int | None = None,
             pca_: str = "correlacao", bandas: tuple[int, ...] = BANDAS, excluir_ruido: bool = True) -> dict:
    """Estilometria do corpus (ver o docstring do módulo)."""
    return calcular_textos(textos_do_corpus(pasta, metas, excluir_ruido), mfw, culling, distancia_, unidade, tamanho_amostra,
                           metodo, k, pca_, bandas, excluir_ruido)


def calcular_textos(textos: list[tuple[dict, list[str]]], mfw: int = 100, culling: float = 0, distancia_: str = "delta_classico",
                    unidade: str = "documento", tamanho_amostra: int = 2000, metodo: str = "ward", k: int | None = None,
                    pca_: str = "correlacao", bandas: tuple[int, ...] = BANDAS, excluir_ruido: bool = True) -> dict:
    validar(mfw, culling, distancia_, unidade, tamanho_amostra, metodo, pca_)
    unidades, excluidos = montar_unidades(textos, unidade, tamanho_amostra)
    n = len(unidades)
    if n < 3:
        raise ValueError("São necessárias ao menos 3 unidades (documentos ou amostras) com texto para a estilometria.")
    if k is not None and not 2 <= k <= n - 1:
        raise ValueError(f"k deve estar entre 2 e {n - 1} (ou omitido para escolha automática).")
    contagens = [Counter(u["tokens"]) for u in unidades]
    tamanhos = [len(u["tokens"]) for u in unidades]
    bandas_ok = sorted({int(b) for b in bandas if int(b) >= 2})
    palavras = lista_de_palavras(contagens, culling, max([mfw, *bandas_ok]))
    if len(palavras) < 2:
        raise ValueError("Menos de 2 palavras passam no corte (culling): reduza o culling.")
    f_todas = tabela_relativa(contagens, tamanhos, palavras)
    mfw_ef = min(mfw, len(palavras))
    f = f_todas[:, :mfw_ef]
    d = distancia(f, distancia_)
    z_mat, ok = escores_z(f)
    constantes = [palavras[j] for j in range(mfw_ef) if not ok[j]]

    arv = ligar(d, metodo)
    if k is None:
        k_usado, silhuetas = escolher_k(arv, d)
    else:
        k_usado, silhuetas = k, []
    rotulos = cortar_k(arv, k_usado)

    # consenso entre faixas de MFW
    bandas_usadas = [b for b in bandas_ok if b <= len(palavras)]
    bandas_ajustadas = False
    if len(bandas_usadas) < 2:  # vocabulário menor que as faixas: 20%, 40%, ..., 100% das MFW disponíveis
        bandas_usadas = sorted({max(2, round(mfw_ef * q)) for q in (0.2, 0.4, 0.6, 0.8, 1.0)})
        bandas_ajustadas = True
    arvores, varredura = [], []
    for b in bandas_usadas:
        db = distancia(f_todas[:, :b], distancia_)
        zb = ligar(db, metodo)
        arvores.append(zb)
        rb = cortar_k(zb, k_usado)
        nn_b = np.argsort(db + np.diag(np.full(n, np.inf)), axis=1, kind="stable")[:, 0]
        nn_0 = np.argsort(d + np.diag(np.full(n, np.inf)), axis=1, kind="stable")[:, 0]
        varredura.append({"mfw": b, "ari": round(agrupamento.ari(rb, rotulos), 4),
                          "vizinho_igual": round(float((nn_b == nn_0).mean()), 4)})
    consenso_info = None
    if len(arvores) >= 2:
        freq, junto = consenso(arvores, k_usado)
        lista_clados = sorted(freq.items(), key=lambda kv: (-kv[1], len(kv[0]), sorted(kv[0])))
        maioria = [c for c, v in lista_clados if v > 0.5]
        principais = []
        for g in range(1, k_usado + 1):
            membros = frozenset(int(i) for i in np.where(rotulos == g)[0])
            sub = junto[np.ix_(sorted(membros), sorted(membros))]
            m = len(membros)
            media_par = float((sub.sum() - m) / (m * (m - 1))) if m > 1 else None
            principais.append({"cluster": g, "unidades": m, "clado": round(freq.get(membros, 0.0), 4) if 1 < m < n else None,
                               "pares_juntos": round(media_par, 4) if media_par is not None else None})
        pares = []
        for i in range(n):
            for j in range(i + 1, n):
                if junto[i, j] > 0:
                    pares.append((float(junto[i, j]), float(d[i, j]), i, j))
        pares.sort(key=lambda t: (-t[0], t[1], t[2], t[3]))
        consenso_info = {
            "bandas": bandas_usadas, "bandas_ajustadas": bandas_ajustadas, "n_arvores": len(arvores),
            "clados_maioria": [{"unidades": sorted(int(i) for i in c), "rotulos": [_rotulo(unidades[i]) for i in sorted(c)],
                                "frequencia": round(v, 4)} for c in maioria for v in [freq[c]]],
            "grupos": principais,
            "pares": [{"a": i, "b": j, "rotulo_a": _rotulo(unidades[i]), "rotulo_b": _rotulo(unidades[j]),
                       "frequencia": round(v, 4), "distancia": round(dd, 6)} for v, dd, i, j in pares[:60]],
            "nota": ("Aproximação da árvore de consenso (Eder, 2017): árvores para cada faixa de MFW (não é reamostragem); "
                     "clado = fração de árvores com exatamente esse grupo; par = fração de árvores em que os dois caem no mesmo grupo "
                     f"no corte em k = {k_usado}."),
        }

    # PCA e MDS
    x_pca = z_mat[:, ok] if pca_ == "correlacao" else f
    pal_pca = [palavras[j] for j in range(mfw_ef) if ok[j]] if pca_ == "correlacao" else palavras[:mfw_ef]
    coords, cargas, var = pca(x_pca)
    cargas_saida = []
    for eixo in range(2):
        ordem = np.argsort(-cargas[eixo], kind="stable")
        cargas_saida.append({
            "eixo": eixo + 1,
            "positivas": [{"palavra": pal_pca[j], "carga": round(float(cargas[eixo, j]), 5)} for j in ordem[:N_CARGAS] if cargas[eixo, j] > 0],
            "negativas": [{"palavra": pal_pca[j], "carga": round(float(cargas[eixo, j]), 5)} for j in ordem[::-1][:N_CARGAS] if cargas[eixo, j] < 0],
        })
    mds, var_mds = similaridade.mds_classico(d)

    # vizinhos e coesão das amostras
    viz_ordem = np.argsort(d + np.diag(np.full(n, np.inf)), axis=1, kind="stable")
    unidades_saida = []
    mesma_doc = []
    for i, u in enumerate(unidades):
        cand = [int(j) for j in viz_ordem[i] if j != i]
        if unidade == "amostra":
            mesma_doc.append(unidades[cand[0]]["doc"]["id"] == u["doc"]["id"])
            cand = [j for j in cand if unidades[j]["doc"]["id"] != u["doc"]["id"]]
        m = u["doc"]
        unidades_saida.append({
            "i": i, "id": m["id"], "parte": u["parte"], "rotulo": _rotulo(u), "arquivo": m["arquivo"],
            "grupo": dados.chave_grupo(m), "ano": dados.chave_ano(m), "idioma": m.get("idioma") or "?",
            "tokens": tamanhos[i], "cluster": int(rotulos[i]),
            "x": round(float(coords[i, 0]), 6), "y": round(float(coords[i, 1]), 6),
            "mx": round(float(mds[i, 0]), 6), "my": round(float(mds[i, 1]), 6),
            "distancia_media": round(float(d[i].sum() / (n - 1)), 6),
            "vizinhos": [{"i": j, "id": unidades[j]["doc"]["id"], "rotulo": _rotulo(unidades[j]), "distancia": round(float(d[i, j]), 6),
                          "cluster": int(rotulos[j])} for j in cand[:N_VIZINHOS]],
        })

    # perfil de estilo por documento (média das unidades do documento)
    media_corpus = f.mean(axis=0)
    perfis = []
    ids_docs = list(dict.fromkeys(u["doc"]["id"] for u in unidades))
    for did in ids_docs:
        idx = [i for i, u in enumerate(unidades) if u["doc"]["id"] == did]
        zm = z_mat[idx].mean(axis=0)
        fm = f[idx].mean(axis=0)
        ordem = [j for j in np.argsort(-zm, kind="stable") if ok[j]]
        item = lambda j: {"palavra": palavras[j], "z": round(float(zm[j]), 3), "freq": round(float(fm[j]), 4),  # noqa: E731
                          "freq_corpus": round(float(media_corpus[j]), 4)}
        outros = [i for i, u in enumerate(unidades) if u["doc"]["id"] != did]
        perfis.append({
            "id": did, "rotulo": unidades[idx[0]]["doc"]["rotulo"], "unidades": len(idx),
            "cobertura_mfw": round(float(fm.sum() / 100.0), 4), "cobertura_corpus": round(float(media_corpus.sum() / 100.0), 4),
            "distancia_media": round(float(d[np.ix_(idx, outros)].mean()), 6) if outros else None,
            "acima": [item(j) for j in ordem[:N_PERFIL] if zm[j] > 0],
            "abaixo": [item(j) for j in ordem[::-1][:N_PERFIL] if zm[j] < 0],
        })

    ordem_folhas = [int(i) for i in hierarchy.leaves_list(arv)]
    fusoes = [{"esquerda": int(a), "direita": int(b), "altura": round(float(h), 6), "tamanho": int(t)} for a, b, h, t in arv]
    coesao = None
    if unidade == "amostra":
        coesao = {"vizinho_do_mesmo_documento": round(float(np.mean(mesma_doc)), 4),
                  "nota": "Fração de amostras cujo vizinho mais próximo é outra amostra do mesmo documento (1 = estilo interno consistente)."}
    return {
        "distancia": distancia_, "nome_distancia": NOMES_DISTANCIA[distancia_], "metodo": metodo, "unidade": unidade,
        "mfw": mfw, "mfw_efetivo": mfw_ef, "culling": culling, "palavras_disponiveis": len(palavras),
        "palavras": palavras[:mfw_ef], "palavras_constantes": constantes,
        "n_unidades": n, "n_documentos": len(ids_docs), "excluidos": excluidos,
        "k": k_usado, "k_automatico": k is None, "silhuetas": silhuetas,
        "silhueta": round(float(similaridade.silhueta(d, rotulos)), 4) if 2 <= k_usado < n else None,
        "unidades": unidades_saida,
        "matriz": [[round(float(v), 6) for v in linha] for linha in d],
        "dendrograma": {"metodo": metodo, "ordem_folhas": ordem_folhas, "fusoes": fusoes,
                        "altura_corte": similaridade.altura_de_corte(arv, k_usado)},
        "consenso": consenso_info, "varredura": varredura, "coesao": coesao,
        "pca": {"tipo": pca_, "variancia_explicada": [round(v, 4) for v in var[:10]], "soma_eixos": round(sum(var[:2]), 4),
                "cargas": cargas_saida, "n_palavras": len(pal_pca),
                "cargas_todas": [{"palavra": w, "pc1": round(float(cargas[0, j]), 6), "pc2": round(float(cargas[1, j]), 6)}
                                 for j, w in enumerate(pal_pca)]},
        "mds": {"variancia_explicada": [round(v, 4) for v in var_mds]},
        "perfis": perfis,
        "parametros": {"mfw": mfw, "culling": culling, "distancia": distancia_, "unidade": unidade, "tamanho_amostra": tamanho_amostra,
                       "metodo": metodo, "k": k, "pca": pca_, "bandas": list(bandas_ok), "excluir_ruido": excluir_ruido,
                       "atributo": "forma (minúsculas), com palavras vazias"},
        "aviso": AVISO, "metodologia": METODOLOGIA, "ferramenta_equivalente": FERRAMENTA_EQUIVALENTE,
    }
