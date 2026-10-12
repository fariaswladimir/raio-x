"""4.2 - Palavras vazias (stopwords) configuráveis: EN / PT / ES / acadêmico / próprias.

As listas partem das do protótipo ``voyant-local`` (SW.en/pt/es/acad), com o acréscimo de
termos de artigos científicos no grupo ``academico`` (et, al, fig, doi, arxiv, https...).

Decisão de projeto: o status de "palavra vazia" **não é gravado nos tokens**. Quem consome
(vocabulário, KWIC, colocados...) aplica o filtro na hora da consulta; assim, mudar as listas
não obriga a retokenizar nem a recalcular o cache (ver ``parametros_relevantes`` no orquestrador).

Uso:

    filtro = filtro_palavras_vazias(parametros)          # frozenset de palavras (minúsculas)
    eh_vazia("the", filtro)                              # True
    token_vazio(norm, lema, filtro)                      # True se norm OU lema estão no filtro

Os termos comparados já vêm normalizados (minúsculas, apóstrofo reto), como em ``norm``/``lema``
dos tokens (ver app/services/tokenizacao.py).
"""
COMPRIMENTO_MINIMO = 2  # termos com menos de 2 letras nunca entram nas contagens

LISTAS: dict[str, str] = {
    "en": """a about above after again against all almost also although always am among an and another any are aren't
around as at be because been before being below between both but by can cannot could couldn't did didn't do does
doesn't doing don't down during each either else even ever every few for from further had hadn't has hasn't have
haven't having he her here hers herself him himself his how however i if in into is isn't it it's its itself just
least less let made many may me might more most much must my myself neither no nor not now of off often on once one
only or other others our ours ourselves out over own per rather same several she should shouldn't since so some such
than that that's the their theirs them themselves then there there's these they this those though through thus to
too toward towards under until up upon us very via was wasn't we well were weren't what when where whether which
while who whom whose why will with within without would wouldn't yet you your yours yourself yourselves whereas
therefore hence moreover furthermore across along two three first second e.g i.e etc""",
    "pt": """a à ao aos as às até com como da das de dela delas dele deles depois do dos e é ela elas ele eles em entre era
eram essa essas esse esses esta está estão estas este estes eu foi foram há isso isto já lhe lhes mais mas me mesmo
meu minha muito na não nas nem no nos nós nossa nosso num numa o os ou para pela pelas pelo pelos por qual quando que
quem se sem ser seu seus sua suas só também te tem têm ter um uma umas uns você vocês sobre são pode podem cada assim
ainda onde porque seja sendo sido tanto todo todos toda todas outro outros outra outras bem aqui""",
    "es": """el la los las un una unos unas de del al y o u en con por para que se su sus es son como más pero le les lo ya
muy sin sobre entre también este esta estos estas ese esa esos esas fue ha han hay ser ni nos cuando donde porque cual
quien según mismo cada otro otra otros otras""",
    "academico": """et al fig figure figures table tables pp vol doi https http www org com arxiv preprint journal page pages
ibid eq section appendix see note notes cid glyph id e.g i.e etc""",
}

PALAVRAS = {nome: frozenset(texto.split()) for nome, texto in LISTAS.items()}
CHAVES_LISTAS = tuple(PALAVRAS)  # ("en", "pt", "es", "academico")


def _normalizar(termo: str) -> str:
    return termo.strip().lower().replace("’", "'")


def palavras_proprias(parametros: dict | None) -> list[str]:
    """Lista ``palavras_vazias.proprias``: aceita lista de strings ou texto separado por espaço, vírgula ou ;."""
    brutas = ((parametros or {}).get("palavras_vazias") or {}).get("proprias") or []
    if isinstance(brutas, str):
        brutas = brutas.replace(",", " ").replace(";", " ").split()
    return [p for p in (_normalizar(str(x)) for x in brutas) if p]


def filtro_palavras_vazias(parametros: dict | None) -> frozenset:
    """Conjunto de palavras vazias ativas segundo ``parametros["palavras_vazias"]``.

    Compatível com parâmetros antigos: chave de lista ausente conta como ligada;
    ``acad`` (nome do protótipo) é aceito como sinônimo de ``academico``.
    """
    cfg = (parametros or {}).get("palavras_vazias") or {}
    ativo = set()
    for nome in CHAVES_LISTAS:
        ligada = cfg.get(nome)
        if ligada is None and nome == "academico":
            ligada = cfg.get("acad")
        if ligada is None or ligada:
            ativo |= PALAVRAS[nome]
    ativo.update(palavras_proprias(parametros))
    return frozenset(ativo)


def eh_vazia(termo: str, filtro, lema: str | None = None) -> bool:
    """Termo vazio: curto demais (< 2 letras) ou presente no filtro. Com ``lema``, vale qualquer um dos dois."""
    termo = _normalizar(termo)
    if len(termo) < COMPRIMENTO_MINIMO or termo in filtro:
        return True
    return lema is not None and _normalizar(lema) in filtro


def token_vazio(norm: str, lema: str, filtro) -> bool:
    """Atalho para tokens: compara ``norm`` e ``lema`` com o filtro (e descarta os de 1 letra)."""
    return len(norm) < COMPRIMENTO_MINIMO or norm in filtro or lema in filtro
