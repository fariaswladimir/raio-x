"""8.1 - Lógica de cada regra do catálogo: lê um instantâneo (ou uma análise sob demanda) e devolve candidatos.

Cada avaliador declara ``params`` (nome -> (tipo, padrão, mínimo): os limiares editáveis na ``condicao`` do
YAML), ``campos`` (campo do modelo -> valor de exemplo, usado para validar o modelo) e a função
``(Contexto, Regra) -> list[Candidato]``. A função só decide *quais* comentários existem e com que números;
as evidências (trechos KWIC com página) são buscadas depois, só para os comentários selecionados.
"""
import json
import statistics
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analise, Documento
from app.services import vocabulario as svc_vocabulario
from app.services.analises import colocacoes, dados, frequencias, kwic
from app.services.palavras_vazias import filtro_palavras_vazias
from app.services.regras.catalogo import Candidato, Regra, valor_p_texto
from app.services.texto import avisos_do_documento, ler_qualidade

MAX_TRECHO = 300
SEM_GRUPO = dados.SEM_GRUPO


def _pt(valor, spec: str = ",d") -> str:
    """Número no formato pt-BR (usado nos trechos de evidência montados fora dos modelos)."""
    return format(valor, spec).translate(str.maketrans({",": ".", ".": ","}))


def _k(valor) -> str:
    """Valor seguro para compor a chave (o separador é "|")."""
    return str(valor).replace("|", "/").strip()


# ---------- contexto ----------

class Contexto:
    """Tudo que as regras consultam, carregado sob demanda e uma vez por geração."""

    def __init__(self, db: Session, pasta_projeto, parametros: dict):
        self.db = db
        self.pasta = pasta_projeto
        self.parametros = parametros
        self._snap: dict[str, dict | None] = {}
        self._metas: list[dict] | None = None
        self._voc = None
        self._filtro = None
        self._docs_db: list[Documento] | None = None

    def snapshot(self, tipo: str) -> dict | None:
        if tipo not in self._snap:
            linha = self.db.scalars(select(Analise).where(Analise.tipo == tipo).order_by(Analise.id.desc()).limit(1)).first()
            self._snap[tipo] = json.loads(linha.resultado_json) if linha and linha.resultado_json else None
        return self._snap[tipo]

    @property
    def metas(self) -> list[dict]:
        if self._metas is None:
            self._metas = dados.documentos_do_corpus(self.db, self.pasta)
        return self._metas

    @property
    def meta_por_id(self) -> dict[int, dict]:
        return {m["id"]: m for m in self.metas}

    @property
    def voc(self) -> dict:
        if self._voc is None:
            self._voc = svc_vocabulario.ler_vocabulario(self.pasta)
            if self._voc is None:
                raise FileNotFoundError("Vocabulário não encontrado: execute o pipeline antes de gerar comentários.")
        return self._voc

    @property
    def filtro(self):
        if self._filtro is None:
            self._filtro = filtro_palavras_vazias(self.parametros)
        return self._filtro

    @property
    def docs_db(self) -> list[Documento]:
        if self._docs_db is None:
            self._docs_db = list(self.db.scalars(select(Documento).where(Documento.status != "removido").order_by(Documento.arquivo)))
        return self._docs_db


# ---------- evidências ----------

def _evid_documento(documento_id: int, trecho: str) -> dict:
    return {"documento_id": documento_id, "pagina": None, "trecho": trecho, "termo": None, "posicao": None}


def _cortar_esq(texto: str, n: int) -> str:
    if len(texto) <= n:
        return texto
    corte = texto[-n:]
    espaco = corte.find(" ")
    return "…" + (corte[espaco + 1:] if espaco != -1 else corte)


def _cortar_dir(texto: str, n: int) -> str:
    if len(texto) <= n:
        return texto
    corte = texto[:n]
    espaco = corte.rfind(" ")
    return (corte[:espaco] if espaco != -1 else corte) + "…"


def montar_trecho(esq: str, termo: str, dir_: str, maximo: int = MAX_TRECHO) -> str:
    """Trecho "esquerda + termo + direita" com no máximo ``maximo`` caracteres (corta nas bordas, em fronteira de palavra)."""
    if len(esq) + len(termo) + len(dir_) > maximo:
        lado = max(0, (maximo - len(termo)) // 2 - 1)
        esq, dir_ = _cortar_esq(esq, lado), _cortar_dir(dir_, lado)
    return (esq + termo + dir_).strip()


def _achar_junto(tk: dict, p: int, lema: str, janela: int) -> int | None:
    """Posição de um token de lema ``lema`` até ``janela`` palavras de ``p``, no mesmo bloco e no corpo."""
    for j in range(max(0, p - janela), min(tk["n"], p + janela + 1)):
        if j != p and tk["bloco"][j] == tk["bloco"][p] and tk["incluir"][j] and tk["lema"][j] == lema:
            return j
    return None


def evidencias_kwic(ctx: Contexto, termo: str, doc_ids: set[int] | None, n: int, junto: str | None = None,
                    janela_junto: int = 5) -> list[dict]:
    """Até ``n`` trechos KWIC do ``termo`` (lema), preferindo documentos distintos.

    Documentos com mais ocorrências primeiro (desempate pelo arquivo); em cada um, a primeira ocorrência
    (estável: não muda se o documento não mudar). Faltando documentos, entram as ocorrências seguintes.
    ``junto``: só ocorrências com esse lema a até ``janela_junto`` palavras (evidência de colocação).
    """
    if n <= 0:
        return []
    metas = ctx.metas if doc_ids is None else [m for m in ctx.metas if m["id"] in doc_ids]
    achadas, _ = kwic._ocorrencias(ctx.pasta, metas, termo, "lema", False)
    por_doc: dict[int, tuple[dict, dict, list[tuple[int, int | None]]]] = {}
    for _, p, m, tk, _fim in achadas:
        j = None
        if junto:
            j = _achar_junto(tk, p, junto, janela_junto)
            if j is None:
                continue
        por_doc.setdefault(m["id"], (m, tk, []))[2].append((p, j))
    ordem = sorted(por_doc.values(), key=lambda x: (-len(x[2]), x[0]["arquivo"]))
    escolhidos: list[tuple[dict, dict, tuple[int, int | None]]] = []
    rodada = 0
    while len(escolhidos) < n:
        rodada_atual = [(m, tk, ps[rodada]) for m, tk, ps in ordem if len(ps) > rodada]
        if not rodada_atual:
            break
        escolhidos.extend(rodada_atual[: n - len(escolhidos)])
        rodada += 1
    janela = max(int(ctx.parametros.get("kwic_janela") or 10), janela_junto)
    saida = []
    for m, tk, (p, j) in escolhidos:
        blocos = dados.carregar_blocos(ctx.pasta, m["id"]) or []
        esq, forma, dir_ = kwic.contexto_do_token(tk, blocos, p, janela, False)
        destaque = forma if j is None else f"{forma}|{tk['forma'][j]}"
        saida.append({"documento_id": m["id"], "pagina": tk["pagina"][p], "trecho": montar_trecho(esq, forma, dir_),
                      "termo": destaque, "posicao": p})
    return saida


def _evid_kwic(ctx, termo, doc_ids=None, junto=None, janela_junto=5) -> Callable[[int], list[dict]]:
    return lambda n: evidencias_kwic(ctx, termo, doc_ids, n, junto, janela_junto)


def _sem_evidencias(_n: int) -> list[dict]:
    return []


# ---------- R01 visão geral ----------

def _r01(ctx: Contexto, regra: Regra) -> list[Candidato]:
    snap = ctx.snapshot("resumo")
    if not snap:
        return []
    c = snap["corpus"]
    if c["n_documentos"] < regra.condicao["min_documentos"]:
        return []
    anos = [(int(a["ano"]), a["documentos"]) for a in c["documentos_por_ano"] if str(a["ano"]).isdigit()]
    sem_ano = sum(a["documentos"] for a in c["documentos_por_ano"] if not str(a["ano"]).isdigit())
    if anos:
        ini, fim = min(a for a, _ in anos), max(a for a, _ in anos)
        periodo = f"todos de {ini}" if ini == fim else f"publicados entre {ini} e {fim}"
        if sem_ano:
            periodo += f" ({sem_ano} sem ano)"
    else:
        periodo = "sem ano informado"
    definidos = [g for g in c["documentos_por_grupo"] if g["grupo"] != SEM_GRUPO]
    grupos = ", ".join(f"{g['grupo']} ({g['documentos']})" for g in c["documentos_por_grupo"]) if definidos else "nenhum definido"
    valores = {"n_docs": c["n_documentos"], "tokens": c["tokens"], "tokens_total": c["tokens_total"],
               "periodo": periodo, "grupos": grupos}
    longos = c["mais_longos"]

    def evid(n):
        return [_evid_documento(d["documento_id"], f"{d['rotulo']}: {_pt(d['tokens'])} palavras no corpo") for d in longos[:n]]

    return [Candidato(regra, "R01", valores, {k: valores[k] for k in ("n_docs", "tokens", "tokens_total")}, 1e6, evid)]


# ---------- R02 pendências ----------

def _r02(ctx: Contexto, regra: Regra) -> list[Candidato]:
    pend = []
    for doc in ctx.docs_db:
        q = ler_qualidade(doc)
        motivos = list(q.get("problemas") or []) + avisos_do_documento(q, doc.grupo)
        excluido = doc.status == "com_problema" or bool(doc.excluido)
        if excluido or motivos:
            pend.append((doc, excluido, motivos))
    if not pend or len(pend) < regra.condicao["min_documentos"]:
        return []
    excl = [(d, m) for d, e, m in pend if e]
    n_av = len(pend) - len(excl)
    rotulos = [dados.rotulo_do_documento(d) for d, _ in excl]
    excluidos = "nenhum" if not rotulos else ", ".join(rotulos[:3]) + (f" e mais {len(rotulos) - 3}" if len(rotulos) > 3 else "")
    valores = {"n_pend": len(pend), "n_total": len(ctx.docs_db), "n_excl": len(excl), "n_av": n_av, "excluidos": excluidos}
    ordenados = sorted(pend, key=lambda t: (not t[1], t[0].arquivo))

    def evid(n):
        return [_evid_documento(d.id, "; ".join(m) or "fora das análises (status com_problema)") for d, _e, m in ordenados[:n]]

    return [Candidato(regra, "R02", valores, dict(valores), float(len(pend)), evid)]


# ---------- R03 MATTR atípico ----------

def _r03(ctx: Contexto, regra: Regra) -> list[Candidato]:
    snap = ctx.snapshot("resumo")
    if not snap:
        return []
    comp = [d for d in snap["documentos"] if d["mattr"] is not None and not d["mattr_ttr"]]
    if len(comp) < regra.condicao["min_documentos"]:
        return []
    valores_m = [d["mattr"] for d in comp]
    media, desvio = statistics.fmean(valores_m), statistics.stdev(valores_m)
    if desvio == 0:
        return []
    saida = []
    for d in comp:
        z = (d["mattr"] - media) / desvio
        if abs(z) < regra.condicao["z_min"]:
            continue
        alto = z > 0
        valores = {"rotulo": d["rotulo"], "mattr": d["mattr"], "media": media, "desvio": desvio, "z": z,
                   "direcao": "acima" if alto else "abaixo",
                   "leitura": "mais variado" if alto else "mais repetitivo (conferir texto repetido, tabelas ou listas)",
                   "n_comparaveis": len(comp)}

        def evid(n, d=d, z=z):
            return [_evid_documento(d["documento_id"], f"MATTR {_pt(d['mattr'], '.3f')}; {_pt(d['tokens'])} palavras; "
                                    f"média do corpus {_pt(media, '.3f')} (desvio-padrão {_pt(desvio, '.3f')}; z = {_pt(z, '.1f')})")][:n]

        saida.append(Candidato(regra, f"R03|doc={_k(d['arquivo'])}", valores,
                               {k: valores[k] for k in ("mattr", "media", "desvio", "z", "n_comparaveis")}, abs(z), evid))
    return saida


# ---------- R04 termos mais frequentes ----------

def _freq_itens(ctx: Contexto) -> tuple[list[dict], int]:
    snap = ctx.snapshot("frequencias")
    if not snap:
        return [], 0
    return snap["itens"], snap["documentos"]


def _r04(ctx: Contexto, regra: Regra) -> list[Candidato]:
    itens, n_docs = _freq_itens(ctx)
    saida = []
    for pos, it in enumerate(itens[: regra.condicao["top_n"]], start=1):
        valores = {"termo": it["termo"], "posicao": pos, "freq": it["freq"], "por_10k": it["por_10k"], "docs": it["docs"], "n_docs": n_docs}
        saida.append(Candidato(regra, f"R04|termo={_k(it['termo'])}", valores,
                               {k: valores[k] for k in ("posicao", "freq", "por_10k", "docs", "n_docs")},
                               float(it["por_10k"]), _evid_kwic(ctx, it["termo"])))
    return saida


# ---------- R05 termos concentrados ----------

def _r05(ctx: Contexto, regra: Regra) -> list[Candidato]:
    itens, n_docs = _freq_itens(ctx)
    cond = regra.condicao
    if n_docs < cond["min_documentos_corpus"]:
        return []
    saida = []
    for it in itens:
        if it["freq"] < cond["min_freq"] or it["docs"] > cond["max_docs"]:
            continue
        por_doc = []
        for m in ctx.metas:
            c = ctx.voc["documentos"].get(str(m["id"]), {}).get("lema", {}).get(it["termo"], 0)
            if c:
                por_doc.append((c, m))
        por_doc.sort(key=lambda t: (-t[0], t[1]["arquivo"]))
        total = sum(c for c, _ in por_doc) or 1
        onde = "; ".join(f"{m['rotulo']} ({'< 1' if 100 * c / total < 0.5 else _pt(100 * c / total, '.0f')} %)" for c, m in por_doc)
        valores = {"termo": it["termo"], "freq": it["freq"], "por_10k": it["por_10k"], "docs": it["docs"], "n_docs": n_docs, "onde": onde}
        saida.append(Candidato(regra, f"R05|termo={_k(it['termo'])}", valores,
                               {"freq": it["freq"], "por_10k": it["por_10k"], "docs": it["docs"], "n_docs": n_docs,
                                "pct_maior_doc": round(100 * por_doc[0][0] / total, 1) if por_doc else None},
                               float(it["freq"]), _evid_kwic(ctx, it["termo"], {m["id"] for _, m in por_doc})))
    return saida


# ---------- R06 tendência temporal ----------

def _r06(ctx: Contexto, regra: Regra) -> list[Candidato]:
    itens, _ = _freq_itens(ctx)
    cond = regra.condicao
    termos = [it["termo"] for it in itens[: cond["top_termos"]] if it["freq"] >= cond["min_freq"]]
    if not termos:
        return []
    series, categorias = [], None
    for i in range(0, len(termos), dados.MAX_TERMOS):  # a distribuição aceita até 6 termos por consulta
        r = frequencias.distribuicao(ctx.voc, ctx.metas, termos[i:i + dados.MAX_TERMOS], por="lema", agrupar="ano", metrica="rel")
        categorias = r["categorias"]
        series.extend(r["series"])
    idx_anos = [(int(c["chave"]), i) for i, c in enumerate(categorias or []) if c["chave"].isdigit()]
    if len(idx_anos) < cond["min_anos"]:
        return []
    idx_anos.sort()
    ano_ult, i_ult = idx_anos[-1]
    anteriores = idx_anos[:-1]
    cat = categorias[i_ult]
    if cat["documentos"] < cond["min_docs_ultimo_ano"] or cat["tokens"] < cond["min_tokens_ultimo_ano"]:
        return []
    docs_ult = [m for m in ctx.metas if m["ano"] == ano_ult]
    anos_ant = f"{anteriores[0][0]} a {anteriores[-1][0]}" if len(anteriores) > 1 else str(anteriores[0][0])
    saida = []
    for s in series:
        rel_ult = s["rel"][i_ult]
        media = statistics.fmean(s["rel"][i] for _, i in anteriores)
        if media <= 0 or s["brutos"][i_ult] < cond["min_freq_ultimo"]:
            continue
        razao = rel_ult / media
        if razao < cond["razao_min"]:
            continue
        termo = s["termo"]
        docs_com = sum(1 for m in docs_ult if ctx.voc["documentos"].get(str(m["id"]), {}).get("lema", {}).get(termo, 0))
        valores = {"termo": termo, "ano_ultimo": ano_ult, "rel_ultimo": rel_ult, "razao": razao, "rel_media": media,
                   "anos_anteriores": anos_ant, "freq_ultimo": s["brutos"][i_ult], "docs_ultimo": docs_com}
        saida.append(Candidato(regra, f"R06|termo={_k(termo)}", valores,
                               {k: valores[k] for k in ("ano_ultimo", "rel_ultimo", "razao", "rel_media", "freq_ultimo", "docs_ultimo")},
                               razao, _evid_kwic(ctx, termo, {m["id"] for m in docs_ult})))
    for c in saida:  # "ano_ultimo" é rótulo, não número com milhar: o modelo recebe texto
        c.valores["ano_ultimo"] = str(c.valores["ano_ultimo"])
    return saida


# ---------- R07 / R08 keyness ----------

def _contra(ctx: Contexto, ids_b: list[int]) -> str:
    por_id = ctx.meta_por_id
    grupos = {dados.chave_grupo(por_id[i]) for i in ids_b if i in por_id}
    return f"em {next(iter(grupos))}" if len(grupos) == 1 else "nos demais documentos"


def _r07(ctx: Contexto, regra: Regra) -> list[Candidato]:
    snap = ctx.snapshot("keyness")
    if not snap:
        return []
    cond = regra.condicao
    saida = []
    for comp in snap["comparacoes"]:
        grupo, ids_a = comp["lado_a"]["valor"], set(comp["lado_a"]["ids"])
        contra = _contra(ctx, comp["lado_b"]["ids"])
        for it in comp["positivas"]:
            if not (it["p"] < cond["p_max"] and it["log_ratio"] >= cond["log_ratio_min"]
                    and it["docs_a"] >= cond["docs_a_min"] and it["a"] >= cond["min_freq_a"]):
                continue
            valores = {"termo": it["termo"], "razao": 2 ** it["log_ratio"], "grupo_a": grupo, "contra": contra, "g2": it["g2"],
                       "p_txt": valor_p_texto(it["p"]), "docs_a": it["docs_a"], "n_a": comp["lado_a"]["documentos"],
                       "freq_a": it["a"], "por_10k_a": it["por_10k_a"], "por_10k_b": it["por_10k_b"], "log_ratio": it["log_ratio"]}
            saida.append(Candidato(
                regra, f"R07|grupo={_k(grupo)}|termo={_k(it['termo'])}", valores,
                {k: it[k] for k in ("a", "b", "por_10k_a", "por_10k_b", "g2", "p", "log_ratio", "docs_a", "docs_b")},
                it["g2"], _evid_kwic(ctx, it["termo"], ids_a), cota=grupo))
    return saida


def _r08(ctx: Contexto, regra: Regra) -> list[Candidato]:
    snap = ctx.snapshot("keyness")
    cond = regra.condicao
    if not snap or len(snap["grupos"]) < cond["min_grupos"]:
        return []
    saida = []
    for comp in snap["comparacoes"]:
        grupo, ids_b = comp["lado_a"]["valor"], set(comp["lado_b"]["ids"])
        contra = _contra(ctx, comp["lado_b"]["ids"])
        for it in comp["negativas"]:
            if not (it["p"] < cond["p_max"] and -it["log_ratio"] >= cond["log_ratio_min"] and it["docs_b"] >= cond["docs_b_min"]):
                continue
            valores = {"termo": it["termo"], "razao": 2 ** -it["log_ratio"], "grupo_a": grupo, "contra": contra, "g2": abs(it["g2"]),
                       "p_txt": valor_p_texto(it["p"]), "docs_b": it["docs_b"], "n_b": comp["lado_b"]["documentos"],
                       "freq_b": it["b"], "por_10k_a": it["por_10k_a"], "por_10k_b": it["por_10k_b"], "log_ratio": it["log_ratio"]}
            saida.append(Candidato(
                regra, f"R08|grupo={_k(grupo)}|termo={_k(it['termo'])}", valores,
                {k: it[k] for k in ("a", "b", "por_10k_a", "por_10k_b", "g2", "p", "log_ratio", "docs_a", "docs_b")},
                abs(it["g2"]), _evid_kwic(ctx, it["termo"], ids_b), cota=grupo))
    return saida


# ---------- R09 colocados ----------

def _r09(ctx: Contexto, regra: Regra) -> list[Candidato]:
    itens, _ = _freq_itens(ctx)
    cond = regra.condicao
    janela = int(ctx.parametros.get("colocacao_janela") or 5)
    saida = []
    for it in itens[: cond["n_termos"]]:
        r = colocacoes.calcular(ctx.pasta, ctx.metas, it["termo"], por="lema", esquerda=janela, direita=janela, filtro=ctx.filtro,
                                filtrar=True, min_freq=cond["o11_min"], ordem="ll", limite=50)
        fortes = [c for c in r["colocados"] if c["ll"] >= cond["ll_min"] and c["mi"] >= cond["mi_min"] and c["o11"] >= cond["o11_min"]]
        for c in fortes[: cond["por_termo"]]:
            valores = {"termo": it["termo"], "colocado": c["termo"], "o11": c["o11"], "janela": janela, "ll": c["ll"],
                       "mi": c["mi"], "p_txt": valor_p_texto(c["p"])}
            saida.append(Candidato(
                regra, f"R09|termo={_k(it['termo'])}|colocado={_k(c['termo'])}", valores,
                {k: c[k] for k in ("o11", "c1", "e11", "ll", "mi", "p")} | {"janela": janela},
                c["ll"], _evid_kwic(ctx, it["termo"], None, junto=c["termo"], janela_junto=janela)))
    return saida


# ---------- R10 grupo pequeno ----------

def _r10(ctx: Contexto, regra: Regra) -> list[Candidato]:
    snap = ctx.snapshot("resumo")
    if not snap:
        return []
    cond = regra.condicao
    por_grupo: dict[str, list[dict]] = {}
    for d in snap["documentos"]:
        por_grupo.setdefault(d["grupo"] or SEM_GRUPO, []).append(d)
    definidos = [g for g in por_grupo if g != SEM_GRUPO]
    if len(definidos) < cond["min_grupos"]:
        return []
    total = sum(d["tokens"] for d in snap["documentos"]) or 1
    saida = []
    for g in definidos:
        docs = por_grupo[g]
        tokens = sum(d["tokens"] for d in docs)
        pct = 100 * tokens / total
        if len(docs) > cond["docs_max"] and pct > cond["pct_tokens_max"]:
            continue
        valores = {"grupo": g, "n_docs": len(docs), "tokens": tokens, "pct": pct, "n_total": len(snap["documentos"])}
        longos = sorted(docs, key=lambda d: (-d["tokens"], d["arquivo"]))

        def evid(n, longos=longos):
            return [_evid_documento(d["documento_id"], f"{d['rotulo']}: {_pt(d['tokens'])} palavras no corpo") for d in longos[:n]]

        saida.append(Candidato(regra, f"R10|grupo={_k(g)}", valores, {k: valores[k] for k in ("n_docs", "tokens", "pct", "n_total")},
                               100 - pct, evid))
    return saida


# ---------- registro ----------

def _spec(analise, params, campos, funcao):
    return {"analise": analise, "params": params, "campos": campos, "funcao": funcao}


_I, _F = int, float
AVALIADORES: dict[str, dict] = {
    "R01": _spec("resumo", {"min_documentos": (_I, 1, 0)},
                 {"n_docs": 10, "tokens": 1000, "tokens_total": 1200, "periodo": "x", "grupos": "x"}, _r01),
    "R02": _spec("resumo", {"min_documentos": (_I, 1, 1)},
                 {"n_pend": 1, "n_total": 10, "n_excl": 1, "n_av": 0, "excluidos": "x"}, _r02),
    "R03": _spec("resumo", {"z_min": (_F, 2.0, 0.0), "min_documentos": (_I, 8, 3)},
                 {"rotulo": "x", "mattr": 0.5, "media": 0.6, "desvio": 0.05, "z": 2.0, "direcao": "x", "leitura": "x", "n_comparaveis": 10}, _r03),
    "R04": _spec("frequencias", {"top_n": (_I, 5, 1)},
                 {"termo": "x", "posicao": 1, "freq": 100, "por_10k": 10.5, "docs": 5, "n_docs": 10}, _r04),
    "R05": _spec("frequencias", {"min_freq": (_I, 30, 1), "max_docs": (_I, 3, 1), "min_documentos_corpus": (_I, 8, 1)},
                 {"termo": "x", "freq": 100, "por_10k": 10.5, "docs": 2, "n_docs": 10, "onde": "x"}, _r05),
    "R06": _spec("tendencias", {"razao_min": (_F, 2.0, 1.0), "min_freq": (_I, 20, 1), "min_freq_ultimo": (_I, 5, 1),
                                "min_anos": (_I, 2, 2), "min_docs_ultimo_ano": (_I, 2, 1), "min_tokens_ultimo_ano": (_I, 2000, 0),
                                "top_termos": (_I, 50, 1)},
                 {"termo": "x", "ano_ultimo": "2026", "rel_ultimo": 10.5, "razao": 2.5, "rel_media": 4.2, "anos_anteriores": "x",
                  "freq_ultimo": 10, "docs_ultimo": 2}, _r06),
    "R07": _spec("keyness", {"p_max": (_F, 0.01, 0.0), "log_ratio_min": (_F, 1.0, 0.0), "docs_a_min": (_I, 2, 1), "min_freq_a": (_I, 5, 1)},
                 {"termo": "x", "razao": 2.5, "grupo_a": "x", "contra": "x", "g2": 20.5, "p_txt": "x", "docs_a": 3, "n_a": 5,
                  "freq_a": 10, "por_10k_a": 5.5, "por_10k_b": 1.5, "log_ratio": 1.2}, _r07),
    "R08": _spec("keyness", {"p_max": (_F, 0.01, 0.0), "log_ratio_min": (_F, 1.0, 0.0), "docs_b_min": (_I, 2, 1), "min_grupos": (_I, 3, 2)},
                 {"termo": "x", "razao": 2.5, "grupo_a": "x", "contra": "x", "g2": 20.5, "p_txt": "x", "docs_b": 3, "n_b": 5,
                  "freq_b": 10, "por_10k_a": 1.5, "por_10k_b": 5.5, "log_ratio": -1.2}, _r08),
    "R09": _spec("colocacoes", {"n_termos": (_I, 3, 1), "por_termo": (_I, 2, 1), "ll_min": (_F, 10.83, 0.0), "mi_min": (_F, 3.0, 0.0),
                                "o11_min": (_I, 5, 1)},
                 {"termo": "x", "colocado": "x", "o11": 10, "janela": 5, "ll": 20.5, "mi": 3.5, "p_txt": "x"}, _r09),
    "R10": _spec("resumo", {"docs_max": (_I, 10, 1), "pct_tokens_max": (_F, 25.0, 0.0), "min_grupos": (_I, 2, 2)},
                 {"grupo": "x", "n_docs": 5, "tokens": 1000, "pct": 10.5, "n_total": 10}, _r10),
}


def avaliar(ctx: Contexto, regra: Regra) -> list[Candidato]:
    candidatos = AVALIADORES[regra.avaliador]["funcao"](ctx, regra)
    for c in candidatos:
        # chave sempre começa pelo id da regra do catálogo (permite duplicar um avaliador com outro id)
        c.chave = regra.id + c.chave[len(c.chave.split("|")[0]):]
    return candidatos
