"""Frente 3 - lógica pura de limpeza e estrutura do texto (sem banco, sem arquivos).

Entrada: o Markdown convertido (com ``<!-- página N -->`` e títulos ``## `` do Docling).
Saída de ``processar``: dict com ``blocos``, ``secoes`` e ``estatisticas`` (ver a etapa
``limpeza`` em app/services/etapas/limpeza.py, que grava o JSON).

Passos, nesta ordem:
1. extrair linhas (página, tipo) removendo comentários HTML, separadores de tabela e marcas de título;
2. remover cabeçalho/rodapé repetidos e números de página isolados (3.3);
3. detectar seções por título (EN/PT/ES) e, sem título de referências, por heurística (3.1);
4. montar blocos (um por página e seção), marcando ``incluir`` conforme os parâmetros (3.2);
5. limpar cada bloco: URLs/e-mails/DOI, marcas de ênfase, hifenização de fim de linha, espaços (3.3).
"""
import html
import re
import unicodedata
from dataclasses import dataclass

from app.services.texto import COMENTARIO_HTML, MARCADOR_PAGINA, PALAVRA

TIPOS = (
    "titulo", "resumo", "introducao", "referencial", "metodos", "resultados", "discussao",
    "conclusao", "referencias", "apendice", "agradecimentos", "declaracoes", "outro",
)
EXCLUIR_SECOES_PADRAO = ("referencias", "apendice", "agradecimentos", "declaracoes")

MIN_PALAVRAS_REFERENCIAS = 30  # abaixo disso, um título "References" é considerado falso (ex.: sumário)
FRACAO_FINAL_HEURISTICA = 0.40  # a heurística só olha os últimos 40% do texto
DENSIDADE_HEURISTICA = 0.60
MIN_REFERENCIAS_HEURISTICA = 5
MIN_PAGINAS_REPETICAO = 4
FRACAO_PAGINAS_REPETICAO = 0.5
TAMANHO_MAX_REPETIDA = 80
ZONA_REPETICAO = 3  # linhas no topo e no pé da página examinadas
ZONA_NUMERO_PAGINA = 2

# ---------- classificação de títulos ----------
# Termos sem acento e em minúsculas. Um título casa com um termo quando contém o termo
# como sequência de palavras e não tem mais de 3 palavras além dele. "$" no fim: título
# inteiro igual ao termo.
TERMOS: dict[str, tuple[str, ...]] = {
    "referencias": (
        "references", "reference list", "list of references", "bibliography", "works cited", "literature cited",
        "cited literature", "bibliographic references", "referencias", "referencias bibliograficas",
        "referencia bibliografica", "bibliografia", "bibliografias", "obras citadas", "references cited",
    ),
    "apendice": (
        "appendix", "appendices", "apendice", "apendices", "anexo", "anexos", "annex", "annexes",
        "supplementary", "supplemental", "supporting information", "online appendix", "material suplementar",
        "material suplementario",
    ),
    "agradecimentos": (
        "acknowledgements", "acknowledgments", "acknowledgement", "acknowledgment", "agradecimentos",
        "agradecimento", "agradecimientos",
    ),
    "declaracoes": (
        "funding", "conflict of interest", "conflicts of interest", "competing interests", "competing interest",
        "declaration of interest", "declarations of interest", "declaration", "declarations",
        "author contributions", "authors contributions", "author contribution", "credit authorship contribution statement",
        "data availability", "code availability", "ethics statement", "ethical approval", "ethics approval",
        "disclosure", "disclosures", "financial support", "informed consent", "consent for publication",
        "declaracao de conflito de interesses", "conflito de interesses", "contribuicao dos autores",
        "contribuicoes dos autores", "disponibilidade de dados", "financiamento", "declaracoes",
        "declaraciones", "conflicto de intereses", "contribucion de los autores", "disponibilidad de datos",
        "financiacion", "financiamiento",
    ),
    "resumo": (
        "abstract", "resumo", "resumen", "executive summary", "sumario executivo", "resumen ejecutivo", "summary$",
    ),
    "conclusao": (
        "conclusion", "conclusions", "conclusao", "conclusoes", "conclusiones", "conclusion$", "concluding remarks",
        "final considerations", "consideracoes finais", "consideraciones finales", "closing remarks", "final remarks",
    ),
    "discussao": (
        "discussion", "discussao", "discusion", "implications", "limitations", "limitacoes", "limitaciones",
        "future work", "future research", "trabalhos futuros", "trabajo futuro", "pesquisas futuras",
    ),
    "resultados": (
        "results", "result", "resultados", "findings", "experimental results", "experiments", "evaluation",
        "resultats", "resultado",
    ),
    "metodos": (
        "method", "methods", "methodology", "metodologia", "metodo", "metodos", "materials and methods",
        "materiais e metodos", "materiales y metodos", "research design", "study design", "data collection",
        "empirical strategy", "data and methods", "data and measures", "experimental setup",
        "procedimentos metodologicos", "metodologia da pesquisa",
    ),
    "referencial": (
        "theoretical framework", "theoretical background", "literature review", "related work", "related works",
        "background", "conceptual framework", "referencial teorico", "fundamentacao teorica", "revisao da literatura",
        "revisao de literatura", "revision de la literatura", "marco teorico", "state of the art", "estado da arte",
        "estado del arte", "theoretical foundations",
    ),
    "introducao": ("introduction", "introducao", "introduccion", "introducao geral"),
}
# Prioridade em empate de posição (mais específico primeiro).
PRIORIDADE = ("referencias", "apendice", "agradecimentos", "declaracoes", "resumo", "conclusao", "discussao",
              "resultados", "metodos", "referencial", "introducao")
TIPOS_CORPO = ("resumo", "introducao", "referencial", "metodos", "resultados", "discussao", "conclusao")

_APENDICE_INICIO = re.compile(
    r"^(appendix|appendices|apendice|apendices|anexo|anexos|annex|annexes|supplementary|supplemental|"
    r"supporting information|online appendix|material suplementa)\b"
)

_PREFIXO = re.compile(
    r"""^\s*(?:(?:section|sec|chapter|capitulo|seccion|secao)\s+)?
        (?:(?P<dig>\d+(?:\.\d+)*)[.):]?
          |(?P<romano>[IVXLC]{1,6})[.)]
          |(?P<letra>[A-Za-z](?:\.\d+)*)[.):](?=\s)
          |(?P<letradig>[A-Z]\d+(?:\.\d+)*)[.):]?)
        \s+""",
    re.VERBOSE,
)


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def _tokens_titulo(texto: str) -> list[str]:
    limpo = _sem_acento(texto).lower()
    return re.sub(r"[^a-z0-9]+", " ", limpo).split()


def separar_numeracao(titulo: str) -> tuple[str, str]:
    """Remove a numeração do título. Devolve (título sem número, prefixo).

    prefixo: "principal" (5, V., I.), "sub" (6.1, A.1, B1), "letra" (A.) ou "nenhum".
    """
    m = _PREFIXO.match(titulo)
    if not m:
        return titulo, "nenhum"
    resto = titulo[m.end():]
    if m.group("dig"):
        return resto, "sub" if "." in m.group("dig") else "principal"
    if m.group("romano"):
        return resto, "principal"
    if m.group("letradig"):
        return resto, "sub"
    letra = m.group("letra")
    return resto, "sub" if "." in letra else "letra"


def classificar_titulo(titulo: str) -> str | None:
    """Tipo da seção (um de TIPOS, exceto titulo/outro) ou None se o título não for reconhecido."""
    sem_num, _ = separar_numeracao(titulo)
    tokens = _tokens_titulo(sem_num)
    if not tokens:
        return None
    texto = " ".join(tokens)
    if _APENDICE_INICIO.match(texto):
        return "apendice"
    melhor: tuple[int, int, str] | None = None  # (posição, prioridade, tipo)
    for tipo, termos in TERMOS.items():
        for termo in termos:
            exato = termo.endswith("$")
            partes = termo.rstrip("$").split()
            n = len(partes)
            if exato:
                achou = 0 if tokens == partes else -1
            elif len(tokens) > n + 3:
                achou = -1
            else:
                achou = -1
                for i in range(len(tokens) - n + 1):
                    if tokens[i:i + n] == partes:
                        achou = i
                        break
            if achou >= 0:
                chave = (achou, PRIORIDADE.index(tipo), tipo)
                if melhor is None or chave < melhor:
                    melhor = chave
    return melhor[2] if melhor else None


# ---------- limpeza de texto ----------

# E-mail simples ("a@b.org"), com chaves ("{ana, rui}@cs.univ.edu") e com espaço depois do @ (quebra de coluna do PDF).
_RE_EMAIL = re.compile(r"(?:\{[^{}@]{1,150}\}|[\w.+\-]+)@ ?[\w\-]+(?:\.[\w\-]+)+")
# URL, inclusive com espaço depois de "https:" ou "//" (também por quebra do PDF).
_RE_URL = re.compile(r"(?:https?:\s?//\s?|ftp://|www\.)\S+", re.IGNORECASE)
_RE_DOI = re.compile(r"(?:\bdoi:\s*)?\b10\.\d{4,9}/\S+", re.IGNORECASE)
_RE_IMAGEM = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]*)\)")
_RE_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_RE_NEGRITO = re.compile(r"\*{1,3}")
_RE_SUBLINHADO_INI = re.compile(r"(?<!\w)_{1,3}(?=\w)")
_RE_SUBLINHADO_FIM = re.compile(r"(?<=\w)_{1,3}(?!\w)")
_RE_CRASE = re.compile(r"`+")
_RE_HIFEN = re.compile(r"([^\W\d_]{1,})-[ \t]*\n[ \t]*([^\W\d_]+)")
_RE_ESPACOS = re.compile(r"[ \t    ​­]+")
_PONTUACAO_FINAL = ".,;:)]}'\"!?"


def _remover_com_contagem(padrao: re.Pattern, texto: str) -> tuple[str, int]:
    """Remove o padrão, mas devolve a pontuação final colada (ex.: 'veja http://x.org.')."""
    n = 0

    def troca(m: re.Match) -> str:
        nonlocal n
        n += 1
        achado = m.group(0)
        resto = achado[len(achado.rstrip(_PONTUACAO_FINAL)):]
        return " " + resto

    return padrao.sub(troca, texto), n


# Prefixos que formam compostos reais ("non-experimental", "self-employed") e quase nunca são a primeira sílaba de uma
# quebra de linha; "pre-", "multi-", "anti-" ficam de fora porque também são sílabas ("pre-vious", "multi-ple").
PREFIXOS_COM_HIFEN = frozenset({"non", "self", "semi", "quasi", "pseudo", "cross", "well", "ill", "vice", "all", "half"})


def _juntar_hifenizada(m: re.Match) -> str:
    antes, depois = m.group(1), m.group(2)
    if depois[:1].islower() and antes.lower() in PREFIXOS_COM_HIFEN:
        return f"{antes}-{depois}"  # "non-\nexperimental": composto real
    if not depois[:1].islower():
        return f"{antes}-{depois}"  # "Smith-\nJones": nome composto, mantém o hífen
    # "AI-\ndriven" e "state-of-the-\nart" são compostos reais: mantém o hífen.
    if len(antes) <= 2 or antes.isupper():
        return f"{antes}-{depois}"
    return antes + depois


def corrigir_hifenizacao(texto: str) -> tuple[str, int]:
    """Junta palavras partidas no fim da linha ("entrepre-\\nneurship"). Compostos reais sem quebra não mudam."""
    n = 0

    def troca(m: re.Match) -> str:
        nonlocal n
        r = _juntar_hifenizada(m)
        if "-" not in r:
            n += 1
        return r

    # "state-of-the-\nart": o grupo 1 só pega letras; sem este cuidado a palavra colaria ("theart").
    def troca_composto(m: re.Match) -> str:
        ini = m.string[max(0, m.start() - 1):m.start()]
        if ini == "-":
            return f"{m.group(1)}-{m.group(2)}"
        return troca(m)

    return _RE_HIFEN.sub(troca_composto, texto), n


def limpar_texto(bruto: str) -> tuple[str, dict]:
    """Limpa um trecho de Markdown. Devolve (texto, {"urls": n, "hifenizacoes": n})."""
    t = _RE_IMAGEM.sub(" ", bruto)
    t = _RE_LINK.sub(r"\1", t)
    t = html.unescape(_RE_TAG.sub(" ", t))
    urls = 0
    for padrao in (_RE_EMAIL, _RE_URL, _RE_DOI):
        t, n = _remover_com_contagem(padrao, t)
        urls += n
    t = _RE_CRASE.sub("", t)
    t = _RE_NEGRITO.sub("", t)
    t = _RE_SUBLINHADO_INI.sub("", t)
    t = _RE_SUBLINHADO_FIM.sub("", t)
    t, hifens = corrigir_hifenizacao(t)
    paragrafos = []
    for par in re.split(r"\n\s*\n", t):
        par = _RE_ESPACOS.sub(" ", par.replace("\n", " ")).strip()
        if par:
            paragrafos.append(par)
    return "\n\n".join(paragrafos), {"urls": urls, "hifenizacoes": hifens}


def contar_palavras(texto: str) -> int:
    return len(PALAVRA.findall(texto))


# ---------- 1. linhas ----------

@dataclass
class Linha:
    pagina: int | None
    tipo: str  # "vazio" | "texto" | "titulo" | "tabela"
    texto: str = ""
    removida: bool = False


_RE_TITULO_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_RE_SEPARADOR_TABELA = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_RE_MARCADOR_LISTA = re.compile(r"^\s*(?:[-*+•]\s+|>\s*)")


def _titulo_limpo(texto: str) -> str:
    t, _ = limpar_texto(texto)
    return t.replace("\n", " ").strip().rstrip(".:").strip()[:200]


def extrair_linhas(md: str) -> list[Linha]:
    """Linhas do MD com a página de cada uma. Comentários HTML (exceto marcadores de página) somem."""
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    md = COMENTARIO_HTML.sub(lambda m: m.group(0) if MARCADOR_PAGINA.fullmatch(m.group(0)) else "\n", md)
    linhas: list[Linha] = []
    pagina: int | None = None
    for bruta in md.split("\n"):
        achou = MARCADOR_PAGINA.search(bruta)
        if achou:
            pagina = int(achou.group(1))
            bruta = MARCADOR_PAGINA.sub("", bruta)
        if not bruta.strip():
            linhas.append(Linha(pagina, "vazio"))
            continue
        titulo = _RE_TITULO_MD.match(bruta)
        if titulo:
            t = _titulo_limpo(titulo.group(1))
            linhas.append(Linha(pagina, "titulo", t) if t else Linha(pagina, "vazio"))
        elif bruta.lstrip().startswith("|"):
            if _RE_SEPARADOR_TABELA.match(bruta):
                continue
            celulas = [c.strip() for c in bruta.strip().strip("|").split("|")]
            texto = " ".join(c for c in celulas if c)
            linhas.append(Linha(pagina, "tabela", texto) if texto else Linha(pagina, "vazio"))
        else:
            linhas.append(Linha(pagina, "texto", _RE_MARCADOR_LISTA.sub("", bruta, count=1).strip()))
    return linhas


# ---------- 2. cabeçalho/rodapé repetidos ----------

_RE_NUMERO_PAGINA = re.compile(
    r"^\W*(?:p(?:ag(?:e|ina)?)?\.?\s*)?\d{1,3}(?:\s*(?:/|of|de)\s*\d{1,3})?\W*$", re.IGNORECASE
)


def _chave_repeticao(texto: str) -> str:
    t = re.sub(r"\d+", "#", _sem_acento(texto).lower())
    return " ".join(re.sub(r"[^a-z# ]+", " ", t).split())


def _candidata_repeticao(l: Linha) -> bool:
    """Linha curta que pode ser cabeçalho/rodapé. Títulos só contam se parecem cabeçalho corrido (>= 3 palavras),
    para que 'Seção 1', 'Seção 2'... não sejam confundidos com ele."""
    if len(l.texto) >= TAMANHO_MAX_REPETIDA:
        return False
    return l.tipo != "titulo" or len(_chave_repeticao(l.texto).replace("#", "").split()) >= 3


def remover_repetidas(linhas: list[Linha]) -> dict:
    """Marca como removidas as linhas repetidas no topo/pé das páginas e os números de página isolados."""
    por_pagina: dict[int, list[int]] = {}
    for i, l in enumerate(linhas):
        if l.pagina is not None and l.tipo in ("texto", "titulo"):
            por_pagina.setdefault(l.pagina, []).append(i)
    paginas = sorted(por_pagina)
    repetidas = numeros = 0
    zonas: dict[int, list[int]] = {}
    for p in paginas:
        idx = por_pagina[p]
        zonas[p] = list(dict.fromkeys(idx[:ZONA_REPETICAO] + idx[-ZONA_REPETICAO:]))

    chaves_remover: set[str] = set()
    if len(paginas) >= MIN_PAGINAS_REPETICAO:
        contagem: dict[str, int] = {}
        for p in paginas:
            vistas = {_chave_repeticao(linhas[i].texto) for i in zonas[p] if _candidata_repeticao(linhas[i])}
            for c in vistas:
                if c:
                    contagem[c] = contagem.get(c, 0) + 1
        minimo = max(2, FRACAO_PAGINAS_REPETICAO * len(paginas))
        chaves_remover = {c for c, n in contagem.items() if n >= minimo}

    for p in paginas:
        idx = por_pagina[p]
        zona_numero = set(idx[:ZONA_NUMERO_PAGINA] + idx[-ZONA_NUMERO_PAGINA:])
        for i in zonas[p]:
            l = linhas[i]
            if _candidata_repeticao(l) and _chave_repeticao(l.texto) in chaves_remover:
                l.removida = True
                repetidas += 1
            elif i in zona_numero and l.tipo == "texto" and _RE_NUMERO_PAGINA.match(l.texto):
                l.removida = True
                numeros += 1
    return {"repetidas": repetidas, "numeros_pagina": numeros}


# ---------- 3. seções ----------

# Padrões de uma entrada de referência (heurística sem título).
_PADROES_REF = {
    "ano_parenteses": re.compile(r"\((?:19|20)\d{2}[a-z]?\)"),
    "ano_virgula": re.compile(r",\s*(?:19|20)\d{2}[a-z]?\s*[.,;]"),
    "et_al": re.compile(r"\bet al\b", re.IGNORECASE),
    "doi": re.compile(r"\bdoi\b|\b10\.\d{4,}/", re.IGNORECASE),
    "url": re.compile(r"https?://|www\.", re.IGNORECASE),
    "paginas": re.compile(r"\bpp?\.\s*\d", re.IGNORECASE),
    "volume": re.compile(r"\bvol(?:ume)?\.?\s*\d", re.IGNORECASE),
    "inicial_depois": re.compile(r"\b[A-ZÀ-Ý][\w'’\-]+,\s+(?:[A-Z]\.[\s\-]?){1,4}"),
    "inicial_antes": re.compile(r"(?:\b[A-Z]\.\s?){1,3}[A-Z][a-zà-ÿ]+"),
    "veiculo": re.compile(r"\barxiv\b|\bproceedings\b|\bjournal\b|\bconference\b|\bpreprint\b|\bpublisher\b|\bpress\b", re.IGNORECASE),
}
_PADROES_REF.update({
    "rotulo_numerico": re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3}\.)\s+\S"),
    "lista_autores": re.compile(r"(?:[A-ZÀ-Ý][\w'’\-]+(?: [A-Z]\.?)?(?: [A-ZÀ-Ý][\w'’\-]+)?, ){2,}(?:and |& |e |y )?[A-ZÀ-Ý]"),
    "ano_solto": re.compile(r"\b(?:19|20)\d{2}[a-z]?\b"),
    "intervalo_paginas": re.compile(r"\b\d{1,5}\s?[–\-]\s?\d{1,5}\b"),
})
_FORTES = {"doi", "url", "inicial_depois", "inicial_antes", "rotulo_numerico", "lista_autores"}
_FRACOS = {"ano_solto", "intervalo_paginas"}
_ANO = re.compile(r"\((?:19|20)\d{2}[a-z]?\)|,\s*(?:19|20)\d{2}[a-z]?\s*[.,;]")


def _peso_referencia(texto: str) -> int:
    """0 se o parágrafo não parece referência; senão, quantas entradas ele aparenta ter."""
    achados = {nome for nome, p in _PADROES_REF.items() if p.search(texto)}
    sem_fracos = achados - _FRACOS  # ano solto e intervalo de páginas aparecem em qualquer prosa
    ehref = len(sem_fracos) >= 3 or (len(achados) >= 2 and bool(achados & _FORTES) and len(texto) < 500)
    if not ehref:
        return 0
    return max(1, len(_ANO.findall(texto))) if len(texto) > 600 else 1


MAX_LACUNA_HEURISTICA = 2  # parágrafos sem cara de referência tolerados entre duas referências


def _detectar_heuristica(linhas: list[Linha]) -> tuple[int, int | None] | None:
    """Sequência densa em referências que chega aos últimos 40% do texto: (linha inicial, linha final exclusiva ou None).

    Percorre os parágrafos agrupando os que parecem referência (com lacunas curtas). Vale o maior grupo
    com >= 5 referências e densidade >= 60%. ``None`` como fim: o grupo vai até o fim do documento.
    """
    unidades: list[tuple[int, int, int, int]] = []  # (linha inicial, linha final+1, palavras, peso)
    atual: list[int] = []

    def fecha():
        if atual:
            texto = " ".join(linhas[i].texto for i in atual)
            unidades.append((atual[0], atual[-1] + 1, contar_palavras(texto), _peso_referencia(texto)))
            atual.clear()

    for i, l in enumerate(linhas):
        if l.removida:
            continue
        if l.tipo == "texto" and l.texto:
            if atual and linhas[atual[-1]].pagina != l.pagina:
                fecha()
            atual.append(i)
        else:
            fecha()
    fecha()
    unidades = [u for u in unidades if u[2] >= 4]
    total = sum(u[2] for u in unidades)
    if total == 0:
        return None
    # Posição (em palavras) onde cada unidade termina; o grupo precisa chegar aos últimos 40% do texto.
    termina, acumulado = [], 0
    for u in unidades:
        acumulado += u[2]
        termina.append(acumulado)
    limite = total * (1 - FRACAO_FINAL_HEURISTICA)

    melhor: tuple[int, int, int] | None = None  # (peso, k inicial, k final)
    k = 0
    while k < len(unidades):
        if not unidades[k][3]:
            k += 1
            continue
        ini = fim = k
        peso, lacunas, vazios = 0, 0, 0
        j = k
        while j < len(unidades):
            if unidades[j][3]:
                peso += unidades[j][3]
                fim = j
                vazios = 0
            else:
                vazios += 1
                if vazios > MAX_LACUNA_HEURISTICA:
                    break
            j += 1
        lacunas = sum(1 for m in range(ini, fim + 1) if not unidades[m][3])
        if (termina[fim] > limite and peso >= MIN_REFERENCIAS_HEURISTICA
                and peso / (peso + lacunas) >= DENSIDADE_HEURISTICA):
            if melhor is None or peso > melhor[0]:
                melhor = (peso, ini, fim)
        k = fim + 1
    if melhor is None:
        return None
    _, ini, fim = melhor
    return unidades[ini][0], (unidades[fim][1] if fim < len(unidades) - 1 else None)


def _segmentar(linhas: list[Linha], ignorar_ref: bool = False, inicio_heuristico: int | None = None,
               fim_heuristico: int | None = None):
    """Atribui uma seção a cada linha. Devolve (secoes, secao_por_linha).

    secoes: [{"tipo","titulo","pagina_inicio","origem"}], origem = "titulo" | "heuristica" | "inicio".
    """
    secoes: list[dict] = [{"tipo": "outro", "titulo": None, "pagina_inicio": None, "origem": "inicio"}]
    mapa: list[int] = [0] * len(linhas)
    estado: str | None = None
    primeiro_titulo = True
    letras = _inicios_apendice_por_letra(linhas)
    for i, l in enumerate(linhas):
        if l.removida:
            mapa[i] = len(secoes) - 1
            continue
        novo: dict | None = None
        if i == inicio_heuristico and estado != "referencias":
            novo = {"tipo": "referencias", "titulo": None, "pagina_inicio": l.pagina, "origem": "heuristica"}
        elif i == fim_heuristico and estado == "referencias":
            novo = {"tipo": "outro", "titulo": None, "pagina_inicio": l.pagina, "origem": "heuristica_fim"}
        elif l.tipo == "titulo" or (l.tipo == "texto" and _pseudotitulo_referencias(linhas, i)):
            tipo = _tipo_do_titulo(
                l.texto, estado, primeiro_titulo and l.tipo == "titulo", l.pagina, ignorar_ref,
                apendice_por_letra=estado == "referencias" and i in letras,
            )
            if l.tipo == "titulo":
                primeiro_titulo = False
            novo = {"tipo": tipo, "titulo": l.texto, "pagina_inicio": l.pagina, "origem": "titulo"}
            # Título que ficou em "referencias" só porque a seção anterior era de referências.
            if tipo == "referencias" and estado == "referencias" and classificar_titulo(l.texto) != "referencias":
                novo["pegajosa"] = True
        if novo:
            secoes.append(novo)
            # Dentro do apêndice, "Agradecimentos"/"Declarações" não encerram o estado: o resto continua apêndice.
            if not (estado == "apendice" and novo["tipo"] in ("agradecimentos", "declaracoes")):
                estado = novo["tipo"]
            mapa[i] = len(secoes) - 1
        else:
            mapa[i] = len(secoes) - 1
    _soltar_secoes_em_prosa(linhas, secoes, mapa)
    return secoes, mapa


LIMIAR_PROSA = 0.35  # fração de parágrafos com cara de referência abaixo da qual a seção é prosa
MIN_PALAVRAS_PROSA = 80


def _soltar_secoes_em_prosa(linhas: list[Linha], secoes: list[dict], mapa: list[int]) -> None:
    """Seções "pegajosas" após as referências que são prosa (ex.: capítulos de um relatório que continuam
    depois de uma lista de referências) deixam de ser referências. Seções curtas herdam a decisão da anterior."""
    paragrafos: dict[int, list[str]] = {}
    atual: list[str] = []
    ultimo = None
    for l, s in zip(linhas, mapa):
        if l.removida:
            continue
        if l.tipo == "texto" and l.texto and secoes[s].get("pegajosa"):
            if ultimo is not None and ultimo != (s, l.pagina):
                paragrafos.setdefault(ultimo[0], []).append(" ".join(atual))
                atual = []
            atual.append(l.texto)
            ultimo = (s, l.pagina)
        elif atual:
            paragrafos.setdefault(ultimo[0], []).append(" ".join(atual))
            atual, ultimo = [], None
    if atual and ultimo is not None:
        paragrafos.setdefault(ultimo[0], []).append(" ".join(atual))
    anterior_ref = True
    for idx, sec in enumerate(secoes):
        if not sec.get("pegajosa"):
            anterior_ref = sec["tipo"] == "referencias"
            continue
        pars = [p for p in paragrafos.get(idx, []) if contar_palavras(p) >= 4]
        palavras = sum(contar_palavras(p) for p in pars)
        if palavras >= MIN_PALAVRAS_PROSA:
            densidade = sum(1 for p in pars if _peso_referencia(p)) / len(pars)
            anterior_ref = densidade >= LIMIAR_PROSA
        if not anterior_ref:
            sec["tipo"] = "outro"


_RE_LETRA_TITULO = re.compile(r"^([A-Z])\s+\S")


def _inicios_apendice_por_letra(linhas: list[Linha]) -> set[int]:
    """Apêndices sem a palavra 'Appendix': títulos 'A Título', 'B Título'... em sequência (A seguido de B)."""
    marcados = []
    for i, l in enumerate(linhas):
        m = _RE_LETRA_TITULO.match(l.texto) if l.tipo == "titulo" and not l.removida else None
        if m:
            marcados.append((i, m.group(1)))
    return {i for k, (i, letra) in enumerate(marcados)
            if letra == "A" and any(outra == "B" for _, outra in marcados[k + 1:])}


def _pseudotitulo_referencias(linhas: list[Linha], i: int) -> bool:
    """Linha solta 'References'/'Bibliografia' que o Docling não marcou como título."""
    l = linhas[i]
    if len(l.texto) > 40 or l.texto.endswith("."):
        return False
    anterior = linhas[i - 1] if i > 0 else None
    if anterior is not None and anterior.tipo not in ("vazio",) and not anterior.removida:
        return False
    return classificar_titulo(l.texto) == "referencias" and _tokens_titulo(l.texto) == _tokens_titulo(separar_numeracao(l.texto)[0])


def _tipo_do_titulo(titulo: str, estado: str | None, primeiro: bool, pagina: int | None, ignorar_ref: bool,
                    apendice_por_letra: bool = False) -> str:
    c = classificar_titulo(titulo)
    if apendice_por_letra and c != "referencias":
        return "apendice"
    if ignorar_ref and c == "referencias":
        c = None
    _, prefixo = separar_numeracao(titulo)
    if c is None and primeiro and (pagina is None or pagina <= 2):
        return "titulo"
    if estado == "apendice":
        return c if c in ("referencias", "declaracoes", "agradecimentos") else "apendice"
    if estado == "referencias":
        if c in ("apendice", "declaracoes", "agradecimentos", "referencias"):
            return c
        if c in TIPOS_CORPO and prefixo == "principal":
            return c
        if prefixo == "letra":  # "A. Título", "B. Título": apêndice sem a palavra Appendix
            return "apendice"
        return "referencias"
    if c:
        return c
    if prefixo == "sub" and estado not in (None, "titulo"):
        return estado
    return "outro"


def detectar_secoes(linhas: list[Linha]) -> tuple[list[dict], list[int], str]:
    """Seções + seção de cada linha + método ("titulo" | "heuristica" | "nenhum")."""
    secoes, mapa = _segmentar(linhas)
    if _palavras_tipo(linhas, secoes, mapa, "referencias") >= MIN_PALAVRAS_REFERENCIAS:
        return secoes, mapa, "titulo"
    if any(s["tipo"] == "referencias" for s in secoes):  # título falso (ex.: sumário): ignora
        secoes, mapa = _segmentar(linhas, ignorar_ref=True)
    achado = _detectar_heuristica(linhas)
    if achado is not None:
        secoes, mapa = _segmentar(linhas, ignorar_ref=True, inicio_heuristico=achado[0], fim_heuristico=achado[1])
        if _palavras_tipo(linhas, secoes, mapa, "referencias") >= MIN_PALAVRAS_REFERENCIAS:
            return secoes, mapa, "heuristica"
        secoes, mapa = _segmentar(linhas, ignorar_ref=True)
    return secoes, mapa, "nenhum"


def _palavras_tipo(linhas: list[Linha], secoes: list[dict], mapa: list[int], tipo: str) -> int:
    return sum(
        contar_palavras(l.texto)
        for l, s in zip(linhas, mapa)
        if not l.removida and l.tipo in ("texto", "tabela") and secoes[s]["tipo"] == tipo
    )


# ---------- 4 e 5. blocos ----------

def _excluidas(parametros: dict | None) -> set[str]:
    p = parametros or {}
    if not p.get("excluir_referencias", True):
        return set()
    return set(p.get("excluir_secoes") or EXCLUIR_SECOES_PADRAO)


_RE_FIM_HIFEN = re.compile(r"([^\W\d_]{3,})-$")
_RE_INICIO_PALAVRA = re.compile(r"^([^\W\d_]+)")


def _juntar_hifen_entre_blocos(blocos: list[dict]) -> int:
    """Palavra partida na virada de página: devolve o resto ao bloco anterior (a atribuição fica na página de origem)."""
    n = 0
    for ant, atual in zip(blocos, blocos[1:]):
        if ant["secao_idx"] != atual["secao_idx"]:
            continue
        m = _RE_FIM_HIFEN.search(ant["texto"])
        resto = _RE_INICIO_PALAVRA.match(atual["texto"])
        if not m or not resto or not resto.group(1)[:1].islower() or m.group(1).isupper():
            continue
        ant["texto"] = ant["texto"][:m.start()] + m.group(1) + resto.group(1)
        atual["texto"] = atual["texto"][resto.end():].lstrip()
        n += 1
    return n


def processar(md: str, parametros: dict | None = None) -> dict:
    """Limpa e estrutura um MD convertido. Ver o docstring do módulo."""
    linhas = extrair_linhas(md)
    repet = remover_repetidas(linhas)
    secoes, mapa, metodo = detectar_secoes(linhas)
    excluidas = _excluidas(parametros)

    # blocos brutos: um por (página, seção) consecutivos
    brutos: list[dict] = []
    atual: dict | None = None
    for l, s in zip(linhas, mapa):
        if l.removida or l.tipo == "titulo":
            continue
        chave = (l.pagina, s)
        if atual is None or atual["chave"] != chave:
            atual = {"chave": chave, "linhas": []}
            brutos.append(atual)
        atual["linhas"].append(l.texto if l.tipo != "vazio" else "")

    urls = hifens = 0
    blocos: list[dict] = []
    for b in brutos:
        texto, info = limpar_texto("\n".join(b["linhas"]))
        urls += info["urls"]
        hifens += info["hifenizacoes"]
        if not texto:
            continue
        pagina, s = b["chave"]
        sec = secoes[s]
        blocos.append({
            "pagina": pagina,
            "secao": sec["tipo"],
            "titulo_secao": sec["titulo"],
            "texto": texto,
            "incluir": sec["tipo"] not in excluidas,
            "secao_idx": s,
        })
    hifens += _juntar_hifen_entre_blocos(blocos)
    blocos = [b for b in blocos if b["texto"]]

    # resumo das seções
    resumo = []
    for idx, sec in enumerate(secoes):
        meus = [b for b in blocos if b["secao_idx"] == idx]
        if not meus and sec["origem"] == "inicio":
            continue
        paginas = [b["pagina"] for b in meus if b["pagina"] is not None]
        inicio = sec["pagina_inicio"] if sec["pagina_inicio"] is not None else (min(paginas) if paginas else None)
        fim = max(paginas + ([inicio] if inicio is not None else [])) if (paginas or inicio is not None) else None
        resumo.append({
            "tipo": sec["tipo"],
            "titulo": sec["titulo"],
            "pagina_inicio": inicio,
            "pagina_fim": fim,
            "palavras": sum(contar_palavras(b["texto"]) for b in meus),
            "incluir": sec["tipo"] not in excluidas,
        })
    for b in blocos:
        del b["secao_idx"]

    total = sum(contar_palavras(b["texto"]) for b in blocos)
    corpo = sum(contar_palavras(b["texto"]) for b in blocos if b["incluir"])
    refs = sum(contar_palavras(b["texto"]) for b in blocos if b["secao"] == "referencias")
    estatisticas = {
        "palavras_total": total,
        "palavras_corpo": corpo,
        "palavras_referencias": refs,
        "referencias_detectadas": metodo != "nenhum",
        "metodo_deteccao": metodo,
        "urls_removidas": urls,
        "hifenizacoes_corrigidas": hifens,
        "linhas_repetidas_removidas": repet["repetidas"] + repet["numeros_pagina"],
        "numeros_pagina_removidos": repet["numeros_pagina"],
        "secoes_excluidas": sorted(excluidas),
        "parece_academico": _parece_academico(resumo, blocos),
    }
    return {"blocos": blocos, "secoes": resumo, "estatisticas": estatisticas}


_RE_CITACAO = re.compile(r"\bet al\b|\((?:19|20)\d{2}[a-z]?\)|\[\d+(?:\s*[,–\-]\s*\d+)*\]", re.IGNORECASE)


def _parece_academico(secoes: list[dict], blocos: list[dict]) -> bool:
    """Estrutura de artigo (>= 2 seções típicas) ou citações no corpo do texto."""
    tipicas = {s["tipo"] for s in secoes} & {"resumo", "introducao", "referencial", "metodos", "resultados", "discussao", "conclusao"}
    if len(tipicas) >= 2:
        return True
    citacoes = sum(len(_RE_CITACAO.findall(b["texto"])) for b in blocos if b["secao"] != "referencias")
    return citacoes >= 3


def texto_para_inspecao(dados: dict, incluir: str = "corpo") -> str:
    """Texto limpo com marcadores de página e de seção, para conferência visual."""
    saida: list[str] = []
    pagina_ant: object = "?"
    secao_ant: tuple | None = None
    for b in dados.get("blocos", []):
        if incluir == "corpo" and not b.get("incluir", True):
            continue
        if b["pagina"] != pagina_ant:
            if b["pagina"] is not None:
                saida.append(f"<!-- página {b['pagina']} -->")
            pagina_ant = b["pagina"]
        secao = (b["secao"], b["titulo_secao"])
        if secao != secao_ant:
            saida.append(f"## {b['titulo_secao'] or '(sem título)'} [{b['secao']}]")
            secao_ant = secao
        saida.append(b["texto"])
    return "\n\n".join(saida) + ("\n" if saida else "")
