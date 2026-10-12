"""4.4 - Segmentos de ~40 palavras ("segmentos de texto", ST, no estilo IRaMuTeQ/Alceste).

Base metodológica: a classificação hierárquica descendente opera sobre segmentos de texto de tamanho aproximado
constante, tratados como "contextos" (Reinert, 1983, 1990); o IRaMuTeQ adota segmentos de ~40 ocorrências, cortados
preferencialmente na pontuação (Camargo & Justo, 2013). Esta etapa é o pré-requisito da CHD (7.1).

Convenções
----------
- Palavra = token do corpo (``incluir`` = 1), qualquer tamanho, com as palavras vazias (números puros não são tokens).
- Um segmento **nunca atravessa bloco** (página/seção do texto limpo): o fim do bloco sempre fecha o segmento.
- Alvo ``T`` = ``segmento_palavras`` (40). Janela "perto do alvo": de 0,75·T a 1,25·T (30..50). Dentro dela corta-se
  na melhor pontuação do texto original *depois* de um token, em ordem de prioridade
  ``. ? ! …`` ou parágrafo (forte) > ``; :`` > ``,`` > nenhuma; empate: mais perto de T, depois o menor.
  Sem pontuação na janela, procura-se até 1,5·T (60); se ainda não houver, corte duro em 1,5·T.
  Um ponto só conta como fim de frase se a palavra seguinte começar em maiúscula (evita ``Fig. 3``, ``et al. em``).
- Cauda < 25% de T no fim do bloco é anexada ao segmento anterior do mesmo bloco (que pode passar de 1,5·T);
  um bloco curto sozinho (ex.: título de uma linha) fica como segmento pequeno.
- ``texto`` do segmento = trecho do texto limpo (espaços colapsados), da 1ª palavra até a pontuação que antecede a
  próxima; ``pagina``/``secao`` vêm do bloco; ``inicio_token``/``fim_token`` são índices em cache/tokens (fim inclusivo).

Diferenças em relação ao IRaMuTeQ
---------------------------------
O IRaMuTeQ conta "formas" (já depois de seu dicionário/lematização, e algumas palavras vazias não entram na
contagem), tem as próprias regras de pontuação e de caracteres, e não conhece blocos de página: aqui a contagem é de
palavras do corpo com as vazias, e o fim de página/seção fecha o segmento. Por isso os segmentos não coincidem
um a um com os do IRaMuTeQ (comparação na 12.2).

Arquivo ``cache/segmentos/<id>.json`` (arquivo lateral; ``cache/tokens`` não é reescrito, como nos termos compostos):
``{"formato", "alvo", "n", "seg": [índice do segmento por token, -1 fora do corpo], "segmentos": [{seg, pagina, secao,
bloco, inicio_token, fim_token, n_tokens, corte, texto}]}``. O ``corte`` é "forte", "media", "fraca", "duro" ou
"fim_bloco".
"""
import json
import re
from pathlib import Path

FORMATO = 1
PRIORIDADES = {1: "forte", 2: "media", 3: "fraca"}
_ESPACOS = re.compile(r"\s+")


def caminho_segmentos(pasta_projeto: Path, documento_id: int) -> Path:
    return pasta_projeto / "cache" / "segmentos" / f"{documento_id}.json"


def ler_segmentos(pasta_projeto: Path, documento_id: int) -> dict | None:
    caminho = caminho_segmentos(pasta_projeto, documento_id)
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.is_file() else None


def _prioridade(texto: str, formas: list[str], ini: list[int], fim: list[int], j: int) -> int | None:
    """Prioridade da pontuação entre o token ``j`` e o seguinte (1 forte, 2 média, 3 fraca; ``None`` sem pontuação)."""
    gap = texto[fim[j]:ini[j + 1]]
    if "\n\n" in gap or any(c in gap for c in "?!…"):
        return 1
    if "." in gap and formas[j + 1][:1].isupper():
        return 1
    if ";" in gap or ":" in gap:
        return 2
    if "," in gap:
        return 3
    return None


def cortes_do_bloco(texto: str, formas: list[str], ini: list[int], fim: list[int], alvo: int) -> list[tuple[int, int, str]]:
    """Segmenta um bloco: ``[(a, b, corte)]`` com ``[a, b)`` índices locais (0..m-1) das palavras do bloco."""
    m = len(formas)
    perto_min, perto_max, duro = max(1, round(0.75 * alvo)), max(2, round(1.25 * alvo)), max(2, round(1.5 * alvo))

    def melhor(s: int, l_min: int, l_max: int):
        achado = None
        for tam in range(l_min, min(l_max, m - s - 1) + 1):
            p = _prioridade(texto, formas, ini, fim, s + tam - 1)
            if p is not None:
                chave = (p, abs(tam - alvo), tam)
                if achado is None or chave < achado[0]:
                    achado = (chave, tam, p)
        return achado

    saida: list[tuple[int, int, str]] = []
    s = 0
    while s < m:
        resto = m - s
        if resto <= perto_max:
            saida.append((s, m, "fim_bloco"))
            break
        achado = melhor(s, perto_min, perto_max)
        if achado is None and resto <= duro:
            saida.append((s, m, "fim_bloco"))
            break
        if achado is None:
            achado = melhor(s, perto_max + 1, duro)
        if achado is None:
            saida.append((s, s + duro, "duro"))
            s += duro
        else:
            saida.append((s, s + achado[1], PRIORIDADES[achado[2]]))
            s += achado[1]
    if len(saida) >= 2 and saida[-1][1] - saida[-1][0] < 0.25 * alvo:
        (a, _, _), (_, b, _) = saida[-2], saida[-1]
        saida[-2:] = [(a, b, "fim_bloco")]
    return saida


def segmentar(tk: dict, blocos: list[dict], alvo: int = 40) -> dict:
    """Segmentos de um documento (estrutura do arquivo ``cache/segmentos/<id>.json``)."""
    n = tk["n"]
    seg = [-1] * n
    segmentos: list[dict] = []
    i = 0
    while i < n:
        if not tk["incluir"][i]:
            i += 1
            continue
        b = tk["bloco"][i]
        j = i
        while j < n and tk["bloco"][j] == b and tk["incluir"][j]:
            j += 1
        texto = blocos[b]["texto"]
        formas, ini, fim = tk["forma"][i:j], tk["inicio"][i:j], tk["fim"][i:j]
        for a, z, corte in cortes_do_bloco(texto, formas, ini, fim, alvo):
            fim_texto = ini[z] if z < len(formas) else len(texto)
            idx = len(segmentos)
            for k in range(i + a, i + z):
                seg[k] = idx
            segmentos.append({
                "seg": idx, "pagina": tk["pagina"][i + a], "secao": tk["secoes"][tk["secao"][i + a]], "bloco": b,
                "inicio_token": i + a, "fim_token": i + z - 1, "n_tokens": z - a, "corte": corte,
                "texto": _ESPACOS.sub(" ", texto[ini[a]:fim_texto]).strip(),
            })
        i = j
    return {"formato": FORMATO, "alvo": alvo, "n": n, "seg": seg, "segmentos": segmentos}
