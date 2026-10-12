"""17.2(c) - Extratores por tipo de resposta, sem LLM. Cada um recebe as **frases candidatas** (com os acertos das palavras-chave) e devolve
``{"valor", "unidade", "frases", "confianca", "justificativa", "alternativas"}`` ou ``None`` (-> "não encontrado"). Nunca inventam: o valor sai
sempre de uma frase do documento, que vira a evidência.

Candidata (``dict``): ``{"f": frase do documento, "fi": FraseIndexada, "acertos": [Acerto], "na_secao": bool, "nota": float}``.

numero
    Padrões (EN/PT): ``n = 312``; "amostra/sample (size) of 1,200"; "312 respondents/respondentes"; "2.5 mil empresas"; "35%". Separador de milhar
    (``1,200`` EN, ``1.200`` PT, espaço fino) e decimal (``3.5``/``3,5``) são resolvidos por ``valor_numero``: com um só separador e exatamente 3 dígitos
    depois (e 1 a 3 antes), vale **milhar** (contagens); multiplicadores (mil, milhão, thousand, million) são aplicados. Fora: anos soltos
    (1900-2100), números depois de Tabela/Figura/Seção/p./RQ/H etc. Nota = força do padrão (n = 3,0; amostra de 2,6; número + unidade 2,0; % 1,5)
    + proximidade da palavra-chave (<= 30 caracteres: +1,5; <= 80: +0,8; <= 160: +0,3) + 1,5 se a unidade casa uma palavra-chave. Sem palavras-chave
    no item só valem os padrões "n = " e "amostra de" (força >= 2,5).
sim_nao
    Só frases que casam as palavras-chave. Negação (no, not, never, without, sem, não, nunca, nenhum, lack, absence, n't...) até 6 palavras antes
    do termo -> "não"; sem negação -> "sim". Frases com os dois -> a maioria; empate -> "ambíguo". **Sem frase com a palavra-chave: não encontrado**
    (ausência de menção não prova "não").
data
    ISO (2025-03-14), dd/mm/aaaa, "14 March 2025", "March 14, 2025", "março de 2025", intervalos "2020-2025" e ano solto (1950-2049, fora de
    citações "(Autor, 2020)"). Valor em ISO parcial: ``AAAA-MM-DD``, ``AAAA-MM``, ``AAAA`` ou ``AAAA/AAAA``.
categoria / multipla
    Cada categoria tem palavras-chave: o próprio valor (exceto "outro", "não especificado"...) e as da própria categoria. Nota da categoria = nº de
    frases candidatas que casam + 0,5 x termos distintos. Categoria com nota máxima única vence; **empate -> "ambíguo"** (evidência das empatadas).
    Múltipla: todas com nota >= 40% da maior.
"""
import re
import unicodedata

from app.services.coleta import termos as T

NAO_ENCONTRADO = "não encontrado"
AMBIGUO = "ambíguo"
GENERICAS = {"outro", "outros", "outra", "outras", "other", "others", "nao especificado", "nao informado", "nao se aplica", "not specified", "n/a", "na", "misto", "mixed"}

# ---------- números ----------

_N = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_NUM = rf"(?<![\w.,/-])(?:{_N})(?!\w|[.,]\d)"
_MULT = r"(?:thousand|million|billion|mil|milh[ãa]o|milh[õo]es|bilh[ãa]o|bilh[õo]es)\b"
_MULTIPLICADOR = {"thousand": 1e3, "mil": 1e3, "million": 1e6, "milhao": 1e6, "milhoes": 1e6, "billion": 1e9, "bilhao": 1e9, "bilhoes": 1e9}
_PARADA = frozenset("of de da do das dos in em on at to the a an and or e ou that were was is are foram foi são sao for para with com by from who which whom "
                    "as per por na no nas nos o os as um uma into over between among who whose had have has been be but not também also through across during via using about after before under within without out up down off con sin en del al los las el la y que se".split())
_CUE_ANTES = re.compile(r"(?<![A-Za-z])(?:table|tab\.?|figure|fig\.?|section|sec\.?|page|pages|p\.|pp\.|rq|h|eq\.?|equation|appendix|tabela|figura|se[çc][ãa]o|p[áa]gina|"
                        r"cap[ií]tulo|chapter|study|experiment|experimento|estudo|phase|wave|round|hypothesis|hip[óo]tese|version|vers[ãa]o|v|gpt-?|llama-?|model|"
                        r"step|passo|etapa|stage|ref\.?|reference|microsoft|office|windows|ios|android|python|llama|gemini|claude|qwen|mistral|gemma|\[)\s*$", re.IGNORECASE)
_N_IGUAL = re.compile(rf"(?<![A-Za-z])[Nn]\s*=\s*({_NUM})")
_AMOSTRA = re.compile(r"(?:sample\s+size|sample|samples|amostra|tamanho\s+(?:da\s+)?amostra(?:l)?|muestra|total\s+of|total\s+de|a\s+total\s+of|panel|painel|dataset|corpus)"
                      r"\s*(?:\(?n\)?\s*)?(?:of|de|com|with|comprising|consisting\s+of|consists?\s+of|comprises?|includes?|contains?|has|had|have|totals?|totall?ed|reached|amounts?\s+to|:|=|was|were|is|are|foi|foram|[eé]|[,])?\s*"
                      rf"(?:approximately|about|around|aproximadamente|cerca\s+de|over|more\s+than|mais\s+de)?\s*({_NUM})(?:\s*({_MULT}))?", re.IGNORECASE)
_NUM_UNIDADE = re.compile(rf"({_NUM})(?:\s*({_MULT}))?\s+([^\W\d_][\w'’-]*(?:\s+[^\W\d_][\w'’-]*){{0,2}})", re.IGNORECASE)
_PORCENTO = re.compile(rf"({_NUM})\s*(%|per\s*cent\b|percent\b|por\s*cento\b)", re.IGNORECASE)


def valor_numero(token: str) -> float | int:
    """Número escrito em pt-BR (1.234,5) ou en (1,234.5); ver o docstring do módulo para o caso de um separador só."""
    s = re.sub(r"[   ]", "", token)
    pontos, virgulas = s.count("."), s.count(",")
    if pontos and virgulas:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        mil = "," if dec == "." else "."
        s = s.replace(mil, "").replace(dec, ".")
    elif pontos or virgulas:
        sep = "." if pontos else ","
        partes = s.split(sep)
        if len(partes) > 2 or (len(partes[-1]) == 3 and 1 <= len(partes[0]) <= 3 and partes[0] != "0"):
            s = "".join(partes)
        else:
            s = ".".join(partes)
    f = float(s)
    return int(f) if f.is_integer() else f


def _aplicar_multiplicador(valor, mult: str | None):
    if not mult:
        return valor
    k = T.sem_acento(mult)
    m = _MULTIPLICADOR.get(k)
    if not m:
        return valor
    v = valor * m
    return int(v) if float(v).is_integer() else v


def _unidade_de(palavras: list[str]) -> str | None:
    """Até 2 palavras seguidas ao número, parando na primeira palavra de ligação (of, de, was, through...)."""
    saida = []
    for p in palavras:
        if T.sem_acento(p) in _PARADA:
            break
        saida.append(p)
    return " ".join(saida[:2]) or None


def numeros_do_texto(texto: str) -> list[dict]:
    """Todos os números do texto com unidade (se houver), padrão e posição: ``{valor, unidade, ini, fim, padrao, forca}``."""
    achados: dict[int, dict] = {}

    def add(ini, fim, valor, unidade, padrao, forca, token):
        antes = texto[max(0, ini - 14):ini]
        ano = bool(re.fullmatch(r"(?:19|20)\d{2}", token)) and 1900 <= int(token) <= 2100
        if _CUE_ANTES.search(antes) and forca < 3:
            return
        if ano and padrao not in ("n = N", "amostra de N", "N unidade"):
            return
        atual = achados.get(ini)
        if atual is None or forca > atual["forca"]:
            achados[ini] = {"valor": valor, "unidade": unidade, "ini": ini, "fim": fim, "padrao": padrao, "forca": forca, "ano": ano}

    for m in _N_IGUAL.finditer(texto):
        add(m.start(1), m.end(1), valor_numero(m.group(1)), "n", "n = N", 3.0, m.group(1))
    for m in _AMOSTRA.finditer(texto):
        resto = texto[m.end():m.end() + 40]
        mu = re.match(r"\s*([^\W\d_][\w'’-]*(?:\s+[^\W\d_][\w'’-]*)?)", resto)
        unidade = _unidade_de(mu.group(1).split()) if mu else None
        add(m.start(1), m.end(1), _aplicar_multiplicador(valor_numero(m.group(1)), m.group(2)), unidade, "amostra de N", 2.6, m.group(1))
    for m in _PORCENTO.finditer(texto):
        add(m.start(1), m.end(2), valor_numero(m.group(1)), "%", "N %", 1.5, m.group(1))
    for m in _NUM_UNIDADE.finditer(texto):
        unidade = (_unidade_de(m.group(3).split()) or "").split()
        if not unidade:
            continue
        valor = _aplicar_multiplicador(valor_numero(m.group(1)), m.group(2))
        add(m.start(1), m.start(3) + len(" ".join(unidade)), valor, " ".join(unidade[:2]), "N unidade", 2.0, m.group(1))
    return sorted(achados.values(), key=lambda c: c["ini"])


def _distancia(c: dict, acertos: list) -> int | None:
    ds = []
    for a in acertos:
        if a.fim <= c["ini"]:
            ds.append(c["ini"] - a.fim)
        elif a.ini >= c["fim"]:
            ds.append(a.ini - c["fim"])
        else:
            ds.append(0)
    return min(ds) if ds else None


def _proximidade(d: int | None) -> float:
    if d is None:
        return 0.0
    return 1.5 if d <= 30 else 0.8 if d <= 80 else 0.3 if d <= 160 else 0.0


def _confianca(nota: float) -> float:
    return round(min(0.92, max(0.30, 0.30 + 0.09 * nota)), 2)


def _unidade_casa(unidade: str | None, termos_acerto: set[str]) -> bool:
    if not unidade or not termos_acerto:
        return False
    palavras = {T.sem_acento(p) for p in unidade.split()}
    return any(any(t.startswith(p[:5]) or p.startswith(t[:5]) for p in palavras if len(p) >= 3 and len(t) >= 3) for t in termos_acerto)


def extrair_numero(candidatas: list[dict], tem_palavras: bool, max_trechos: int, aceita_percentual: bool = False) -> dict | None:
    pontuadas = []
    for c in candidatas:
        termos_acerto = {T.sem_acento(a.termo.strip("\"/*")) for a in c["acertos"]}
        for n in numeros_do_texto(c["f"]["texto"]):
            if not tem_palavras and n["forca"] < 2.5:
                continue
            if n["unidade"] == "%" and not aceita_percentual:
                continue
            if n["ano"] and not (n["forca"] >= 2.6 or _unidade_casa(n["unidade"], termos_acerto)):
                continue
            casa = _unidade_casa(n["unidade"], termos_acerto)
            dist = _distancia(n, c["acertos"])
            if tem_palavras and n["padrao"] == "N unidade" and not casa and (dist is None or dist > 40):
                continue  # "365 Copilot": número solto, longe da palavra-chave e sem unidade que a case
            nota = n["forca"] + _proximidade(dist) + (1.5 if casa else 0.0) + 0.3 * c.get("nota", 0) - (1.0 if tem_palavras and not c.get("na_secao") else 0.0)
            if tem_palavras and not c["acertos"] and not c.get("na_secao"):
                nota -= 1.0
            pontuadas.append((nota, c, n))
    if not pontuadas:
        return None
    pontuadas.sort(key=lambda x: (-x[0], x[1]["f"]["i"]))
    nota, c, n = pontuadas[0]
    frases, vistos = [], set()
    for nt, cc, nn in pontuadas:
        if cc["f"]["i"] not in vistos and (nn["valor"] == n["valor"] or len(frases) < 1):
            vistos.add(cc["f"]["i"])
            frases.append(cc["f"])
        if len(frases) >= max_trechos:
            break
    outros = []
    for nt, cc, nn in pontuadas[1:6]:
        if nn["valor"] != n["valor"] and all(o["valor"] != nn["valor"] for o in outros):
            outros.append({"valor": nn["valor"], "unidade": nn["unidade"], "nota": round(nt, 2)})
    return {"valor": n["valor"], "unidade": n["unidade"], "frases": frases, "confianca": _confianca(nota),
            "justificativa": f"número por padrão \"{n['padrao']}\"" + (f"; unidade \"{n['unidade']}\"" if n["unidade"] else ""), "alternativas": outros[:3]}


# ---------- sim / não ----------

_NEGACAO = frozenset("no not never without none neither nor nobody nowhere cannot lack lacks lacked lacking absence absent unable não nao nunca sem nenhum nenhuma "
                     "nenhuns jamais ninguém ninguem tampouco nem ausência ausencia falta ningún ningun ninguna ninguno tampoco sin".split())
_JANELA_NEGACAO = 6


def _negado(fi: T.FraseIndexada, acerto: T.Acerto) -> bool:
    ini = max(0, acerto.tok_i - _JANELA_NEGACAO)
    for k in range(ini, acerto.tok_i):
        norm = fi.toks[k][0]
        if norm in _NEGACAO or norm.endswith("n't") or norm.endswith("n't"):
            return True
    return False


def extrair_sim_nao(candidatas: list[dict], max_trechos: int) -> dict | None:
    sim, nao = [], []
    for c in candidatas:
        if not c["acertos"]:
            continue
        negados = [_negado(c["fi"], a) for a in c["acertos"]]
        (nao if all(negados) else sim).append(c)
    if not sim and not nao:
        return None
    if len(sim) == len(nao):
        valor, escolhidas, conf = AMBIGUO, (sim + nao), 0.35
    elif len(sim) > len(nao):
        valor, escolhidas, conf = "sim", sim, 0.7 if not nao else 0.5
    else:
        valor, escolhidas, conf = "não", nao, 0.65 if not sim else 0.45
    escolhidas = sorted(escolhidas, key=lambda c: -c.get("nota", 0))[:max_trechos]
    return {"valor": valor, "unidade": None, "frases": [c["f"] for c in sorted(escolhidas, key=lambda c: c["f"]["i"])], "confianca": conf,
            "justificativa": f"palavra-chave presente{' com negação' if valor == 'não' else ''} em {len(sim) + len(nao)} frase(s) ({len(sim)} afirmativa(s), {len(nao)} negada(s))",
            "alternativas": []}


# ---------- datas ----------

_MESES = {}
_NOMES_MES = set()
for _i, _nomes in enumerate([
    "january jan janeiro enero", "february feb fevereiro fev febrero", "march mar março marco marzo", "april apr abril abr", "may maio mai mayo",
    "june jun junho junio", "july jul julho julio", "august aug agosto ago", "september sep sept setembro set septiembre setiembre",
    "october oct outubro out octubre", "november nov novembro noviembre", "december dec dezembro dez diciembre"], 1):
    for _n in _nomes.split():
        _MESES[unicodedata.normalize("NFKD", _n).encode("ascii", "ignore").decode()] = _i
        _NOMES_MES.update({_n, unicodedata.normalize("NFKD", _n).encode("ascii", "ignore").decode()})
_MES = r"(" + "|".join(sorted(_NOMES_MES, key=len, reverse=True)) + r")"
_ANO = r"((?:19|20)\d{2})"
_D_ISO = re.compile(rf"\b{_ANO}-(\d{{2}})(?:-(\d{{2}}))?\b")
_D_BARRA = re.compile(rf"\b(\d{{1,2}})/(\d{{1,2}})/{_ANO}\b")
_D_DMA = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|º)?\s+(?:de\s+)?{_MES}\.?,?\s+(?:de\s+)?{_ANO}\b", re.IGNORECASE)
_D_MDA = re.compile(rf"\b{_MES}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+{_ANO}\b", re.IGNORECASE)
_D_MA = re.compile(rf"\b{_MES}\.?,?\s+(?:de\s+|of\s+)?{_ANO}\b", re.IGNORECASE)
_D_INTERVALO = re.compile(rf"\b{_ANO}\s*(?:-|–|—|to|a|até|and|e|y|through)\s*{_ANO}\b", re.IGNORECASE)
_D_ANO = re.compile(r"\b((?:19[5-9]|20[0-4])\d)\b")


def _mes(nome: str) -> int | None:
    return _MESES.get(T.sem_acento(nome).strip("."))


def datas_do_texto(texto: str) -> list[dict]:
    """``{valor, ini, fim, forca, padrao}`` por data encontrada (sobreposições: vence a de maior força)."""
    c: list[dict] = []

    def add(m, valor, forca, padrao):
        c.append({"valor": valor, "ini": m.start(), "fim": m.end(), "forca": forca, "padrao": padrao})

    for m in _D_ISO.finditer(texto):
        mm = int(m.group(2))
        if 1 <= mm <= 12:
            add(m, f"{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else ""), 3.0, "AAAA-MM-DD")
    for m in _D_BARRA.finditer(texto):
        a, b, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        dia, mes = (a, b) if b <= 12 else (b, a)
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            add(m, f"{ano}-{mes:02d}-{dia:02d}", 3.0 if (a > 12 or b > 12) else 2.4, "dd/mm/aaaa")
    for m in _D_DMA.finditer(texto):
        mes = _mes(m.group(2))
        if mes:
            add(m, f"{m.group(3)}-{mes:02d}-{int(m.group(1)):02d}", 3.0, "dia mês ano")
    for m in _D_MDA.finditer(texto):
        mes = _mes(m.group(1))
        if mes:
            add(m, f"{m.group(3)}-{mes:02d}-{int(m.group(2)):02d}", 3.0, "mês dia, ano")
    for m in _D_MA.finditer(texto):
        mes = _mes(m.group(1))
        if mes:
            add(m, f"{m.group(2)}-{mes:02d}", 2.5, "mês ano")
    for m in _D_INTERVALO.finditer(texto):
        if int(m.group(1)) < int(m.group(2)):
            add(m, f"{m.group(1)}/{m.group(2)}", 2.2, "intervalo de anos")
    for m in _D_ANO.finditer(texto):
        antes, depois = texto[max(0, m.start() - 3):m.start()], texto[m.end():m.end() + 2]
        if re.search(r"[,;]\s*$", antes) and depois[:1] == ")" or re.search(r"\(\s*$", antes) and depois[:1] in (")", ","):
            continue  # citação "(Autor, 2020)"
        add(m, m.group(1), 1.0, "ano")
    c.sort(key=lambda x: (-x["forca"], x["ini"]))
    escolhidas: list[dict] = []
    for x in c:
        if all(x["fim"] <= y["ini"] or x["ini"] >= y["fim"] for y in escolhidas):
            escolhidas.append(x)
    return sorted(escolhidas, key=lambda x: x["ini"])


def extrair_data(candidatas: list[dict], tem_palavras: bool, max_trechos: int) -> dict | None:
    pontuadas = []
    for c in candidatas:
        for d in datas_do_texto(c["f"]["texto"]):
            if d["padrao"] == "ano" and not c["acertos"] and not c.get("na_secao"):
                continue
            nota = d["forca"] + _proximidade(_distancia(d, c["acertos"])) + 0.3 * c.get("nota", 0)
            pontuadas.append((nota, c, d))
    if not pontuadas:
        return None
    pontuadas.sort(key=lambda x: (-x[0], x[1]["f"]["i"]))
    nota, c, d = pontuadas[0]
    frases, vistos = [], set()
    for nt, cc, dd in pontuadas:
        if cc["f"]["i"] not in vistos and (dd["valor"] == d["valor"] or not frases):
            vistos.add(cc["f"]["i"])
            frases.append(cc["f"])
        if len(frases) >= max_trechos:
            break
    outros = []
    for nt, cc, dd in pontuadas[1:6]:
        if dd["valor"] != d["valor"] and all(o["valor"] != dd["valor"] for o in outros):
            outros.append({"valor": dd["valor"], "nota": round(nt, 2)})
    return {"valor": d["valor"], "unidade": None, "frases": frases, "confianca": _confianca(nota),
            "justificativa": f"data por padrão \"{d['padrao']}\"", "alternativas": outros[:3]}


# ---------- categorias ----------

def termos_da_categoria(cat: dict) -> list[str]:
    termos = list(cat.get("palavras_chave") or [])
    if T.sem_acento(cat["valor"]).strip() not in GENERICAS:
        termos.insert(0, cat["valor"])
    return termos


def extrair_categoria(candidatas_por_categoria: dict[str, list[dict]], categorias: list[dict], multipla: bool, max_trechos: int) -> dict | None:
    """``candidatas_por_categoria``: valor da categoria -> candidatas (frases) que casam as palavras dela (``nota`` já calculada)."""
    notas = {c["valor"]: candidatas_por_categoria.get(c["valor"]) for c in categorias}
    pontos = {}
    for valor, cands in notas.items():
        if not cands:
            continue
        distintos = {T.sem_acento(a.termo) for c in cands for a in c["acertos"]}
        pontos[valor] = len(cands) + 0.5 * len(distintos)
    if not pontos:
        return None
    melhor = max(pontos.values())
    ordem = sorted(pontos, key=lambda v: (-pontos[v], [c["valor"] for c in categorias].index(v)))
    if multipla:
        escolhidas = [v for v in ordem if pontos[v] >= 0.4 * melhor]
        valor = escolhidas
        conf = 0.6
    else:
        topo = [v for v in ordem if abs(pontos[v] - melhor) < 1e-9]
        if len(topo) > 1:
            valor, escolhidas, conf = AMBIGUO, topo, 0.35
        else:
            valor, escolhidas = topo[0], topo
            segundo = sorted(pontos.values(), reverse=True)[1] if len(pontos) > 1 else 0
            conf = round(min(0.9, 0.5 + 0.1 * (melhor - segundo)), 2)
    frases, vistos = [], set()
    for v in escolhidas:
        for c in sorted(notas[v], key=lambda c: -len(c["acertos"]))[:max(1, max_trechos if len(escolhidas) == 1 else 1)]:
            if c["f"]["i"] not in vistos:
                vistos.add(c["f"]["i"])
                frases.append(c["f"])
    frases = sorted(frases, key=lambda f: f["i"])[:max(max_trechos, len(escolhidas) if valor == AMBIGUO else 0)]
    alternativas = [{"valor": v, "nota": round(pontos[v], 2)} for v in ordem if v not in escolhidas][:3]
    termos = sorted({a.termo for v in escolhidas for c in notas[v] for a in c["acertos"]})[:6]
    return {"valor": valor, "unidade": None, "frases": frases, "confianca": conf,
            "justificativa": "palavras-chave da categoria: " + ", ".join(termos) + f" ({'; '.join(f'{v}: {pontos[v]:g}' for v in ordem[:4])})", "alternativas": alternativas}
