"""14.2 - Modelos de parágrafo por tipo de análise, métricas do projeto e pré-visualização sem LLM.

Os modelos padrão ficam em ``app/services/regras/modelos_paragrafo.yaml`` (nunca editado em execução). Cada projeto
pode ter ``projetos/<slug>/modelos_paragrafo.yaml``: um modelo do projeto com o mesmo ``id`` substitui o padrão; os
outros são modelos novos (duplicatas). ``coletar`` calcula, de forma determinística e com os parâmetros padrão da API,
as métricas que viram os ``{placeholders}`` e, para o LLM, o JSON de métricas e até 5 trechos de evidência.
"""
import os
import re
import string
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.services import dicionario as svc_dicionario
from app.services.analises import afc, colocacoes, dados, dicionario, especificidades, frequencias, keyness, kwic, ngramas, resumo, similaridade
from app.services.exportar import comum
from app.services.regras.avaliadores import montar_trecho
from app.services.regras.catalogo import renderizar, valor_p_texto

PADRAO = Path(__file__).with_name("regras") / "modelos_paragrafo.yaml"
ARQUIVO_PROJETO = "modelos_paragrafo.yaml"
ANALISES_PARAGRAFO = ("resumo", "frequencias", "tendencias", "kwic", "colocacoes", "ngramas", "keyness",
                      "especificidades", "afc", "similaridade", "dicionario")
ESTILOS_SUGERIDOS = ("descritivo", "interpretativo cauteloso", "resultado para artigo")
MAX_EVIDENCIAS = 5


class ModeloInvalido(ValueError):
    """Modelo de parágrafo inválido (mensagem em português para a tela)."""


class AnaliseIndisponivel(ValueError):
    """A análise não tem dados neste projeto (ex.: sem grupos definidos ou dicionário vazio)."""


def caminho_padrao() -> Path:
    return Path(os.getenv("RAIOX_MODELOS_PARAGRAFO") or PADRAO)


# ---------- modelos ----------

def campos_do_texto(texto: str) -> set[str]:
    return {nome.split(".")[0].split("[")[0] for _, nome, _, _ in string.Formatter().parse(texto) if nome}


def _ler_yaml(caminho: Path) -> list[dict]:
    try:
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    except yaml.YAMLError as exc:
        raise ModeloInvalido(f"YAML inválido em {caminho.name}: {exc}") from exc
    lista = bruto.get("modelos") if isinstance(bruto, dict) else None
    if not isinstance(lista, list):
        raise ModeloInvalido(f"{caminho.name}: esperado 'modelos:' com uma lista.")
    return lista


def normalizar(m: dict) -> dict:
    """Valida e devolve o modelo só com os campos conhecidos (levanta ModeloInvalido)."""
    if not isinstance(m, dict):
        raise ModeloInvalido("Cada modelo deve ser um objeto.")
    mid = str(m.get("id") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", mid):
        raise ModeloInvalido(f"Id inválido '{mid}': use letras minúsculas, números, '-' e '_' (até 64).")
    analise = str(m.get("analise") or "").strip()
    if analise not in ANALISES_PARAGRAFO:
        raise ModeloInvalido(f"Modelo {mid}: análise '{analise}' inválida. Use: {', '.join(ANALISES_PARAGRAFO)}.")
    texto = str(m.get("texto_modelo") or "").strip()
    if not texto:
        raise ModeloInvalido(f"Modelo {mid}: o texto do modelo está vazio.")
    try:
        campos = campos_do_texto(texto)
    except ValueError as exc:
        raise ModeloInvalido(f"Modelo {mid}: chaves {{}} mal formadas ({exc}).") from exc
    desconhecidos = sorted(campos - set(PLACEHOLDERS[analise]))
    if desconhecidos:
        raise ModeloInvalido(f"Modelo {mid}: campos desconhecidos para '{analise}': {', '.join(desconhecidos)}.")
    return {"id": mid, "analise": analise, "titulo": str(m.get("titulo") or mid).strip()[:150],
            "estilo": str(m.get("estilo") or "descritivo").strip()[:60], "idioma": str(m.get("idioma") or "pt").strip()[:5],
            "texto_modelo": texto, "notas": str(m.get("notas") or "").strip()}


def modelos_padrao() -> list[dict]:
    lista = [normalizar(m) for m in _ler_yaml(caminho_padrao())]
    ids = [m["id"] for m in lista]
    if len(ids) != len(set(ids)):
        raise ModeloInvalido("Ids repetidos em modelos_paragrafo.yaml.")
    return lista


def modelos_do_projeto(pasta: Path) -> list[dict]:
    arq = pasta / ARQUIVO_PROJETO
    return [normalizar(m) for m in _ler_yaml(arq)] if arq.is_file() else []


def listar(pasta: Path) -> list[dict]:
    """Padrões + projeto. ``origem``: padrao | projeto (novo) | padrao_editado (projeto com o id de um padrão)."""
    padrao = {m["id"]: m for m in modelos_padrao()}
    do_projeto = {m["id"]: m for m in modelos_do_projeto(pasta)}
    saida = []
    for mid, m in padrao.items():
        if mid in do_projeto:
            saida.append({**do_projeto[mid], "origem": "padrao_editado", "padrao": m})
        else:
            saida.append({**m, "origem": "padrao"})
    saida += [{**m, "origem": "projeto"} for mid, m in do_projeto.items() if mid not in padrao]
    ordem = {a: i for i, a in enumerate(ANALISES_PARAGRAFO)}
    saida.sort(key=lambda m: ordem[m["analise"]])
    return saida


def salvar_do_projeto(pasta: Path, modelos: list[dict]) -> list[dict]:
    """Grava a lista de modelos do projeto (substitui a anterior). Nunca toca no arquivo padrão."""
    limpos = [normalizar(m) for m in modelos]
    ids = [m["id"] for m in limpos]
    if len(ids) != len(set(ids)):
        raise ModeloInvalido("Ids repetidos na lista de modelos do projeto.")
    arq = pasta / ARQUIVO_PROJETO
    if not limpos:
        arq.unlink(missing_ok=True)
    else:
        pasta.mkdir(parents=True, exist_ok=True)
        arq.write_text(yaml.safe_dump({"modelos": limpos}, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
    return listar(pasta)


def buscar(pasta: Path, modelo_id: str) -> dict:
    for m in listar(pasta):
        if m["id"] == modelo_id:
            return m
    raise KeyError(modelo_id)


def preencher(modelo: dict, metricas: dict) -> str:
    """Texto do modelo com os números do projeto (pt-BR). Determinístico: o mesmo projeto dá o mesmo texto."""
    try:
        return renderizar(modelo["texto_modelo"], metricas)
    except KeyError as exc:
        raise ModeloInvalido(f"O modelo usa o campo {exc} que não existe nas métricas desta análise.") from exc
    except (ValueError, TypeError) as exc:
        raise ModeloInvalido(f"Não consegui preencher o modelo: {exc}") from exc


# ---------- métricas (placeholders por análise) ----------

def _grupo(prefixo: str, n: int, campos: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{prefixo}{c}_{i}" if prefixo else f"{c}_{i}" for i in range(1, n + 1) for c in campos)


PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "resumo": ("n_documentos", "tokens", "tokens_total", "tipos_lema", "densidade_lema", "mattr_media", "mattr_mediana",
               "mattr_janela", "mattr_documentos_comparaveis", "media_tokens", "mediana_tokens"),
    "frequencias": ("n_documentos", "tokens", "tipos", "termos_top", *_grupo("", 3, ("termo", "freq", "por_10k", "docs"))),
    "tendencias": ("termo", "n_anos", "ano_inicial", "ano_final", "rel_inicial", "rel_final", "bruto_inicial", "bruto_final", "razao"),
    "kwic": ("termo", "total", "documentos_com_ocorrencias", "n_documentos", "janela"),
    "colocacoes": ("termo", "ocorrencias_no", "documentos_com_no", "janela", "colocados_top",
                   *_grupo("", 3, ("colocado", "o11", "ll", "mi"))),
    "ngramas": ("n_total", "n_min", "n_max", "min_freq", "n_documentos", "ngramas_top", *_grupo("", 3, ("ngrama", "freq", "docs", "por_10k"))),
    "keyness": ("particao", "lado_a", "lado_b", "docs_a", "docs_b", "tokens_a", "tokens_b", "total_positivas", "total_negativas",
                *_grupo("pos_", 3, ("termo", "a", "b", "por_10k_a", "por_10k_b", "g2", "log_ratio", "p_texto")),
                *_grupo("neg_", 2, ("termo", "a", "b", "por_10k_a", "por_10k_b", "g2", "log_ratio", "p_texto"))),
    "especificidades": ("particao", "n_partes", "parte", "parte_documentos", "parte_tokens", "limiar", "teto",
                        *_grupo("pos_", 3, ("termo", "f", "F", "score")), *_grupo("neg_", 2, ("termo", "f", "F", "score"))),
    "afc": ("particao", "n_linhas", "n_colunas", "n_eixos", "inercia_total", "chi2", "autovalor_1", "pct_1", "autovalor_2", "pct_2",
            "pct_acumulado_2", "eixo1_positivo", "eixo1_negativo", "eixo2_positivo", "eixo2_negativo"),
    "similaridade": ("n_documentos", "n_termos", "n_excluidos", "metodo", "k", "modo_k", "silhueta",
                     *_grupo("grupo_", 3, ("docs", "termos"))),
    "dicionario": ("agrupar", "n_documentos", "tokens", "n_categorias", *_grupo("cat_", 3, ("nome", "total", "por_10k", "docs", "termos"))),
}


def _r(x, casas=2):
    return round(float(x), casas) if x is not None else 0.0


def _mais(_, itens: list, campo: str, n: int = 5) -> str:
    return ", ".join(str(i[campo]) for i in itens[:n]) or "—"


def _contexto(db: Session, pasta: Path) -> dict:
    return comum.contexto(db, pasta)


def _top_termos(ctx: dict, n: int = 10) -> list[dict]:
    return frequencias.listar(ctx["voc"], ctx["metas"], ctx["filtro"], por="lema", filtrar=True, limite=n)["itens"]


def _m_resumo(db, pasta, ctx):
    res = resumo.resumo_do_projeto(pasta, ctx["metas"], ctx["params"])
    if not res:
        raise AnaliseIndisponivel("Resumo indisponível: execute o pipeline.")
    c = res["corpus"]
    m = {k: c.get(k) for k in ("tokens", "tokens_total", "tipos_lema", "densidade_lema", "mattr_media", "mattr_mediana", "mattr_janela",
                               "mattr_documentos_comparaveis", "media_tokens", "mediana_tokens")}
    m["n_documentos"] = c["n_documentos"]
    m = {k: (v if v is not None else 0) for k, v in m.items()}
    return m, [i["termo"] for i in _top_termos(ctx, 3)], "lema"


def _m_frequencias(db, pasta, ctx):
    r = frequencias.listar(ctx["voc"], ctx["metas"], ctx["filtro"], por="lema", filtrar=True, limite=10)
    itens = r["itens"]
    m = {"n_documentos": r["documentos"], "tokens": r["tokens"], "tipos": r["tipos"], "termos_top": _mais("", itens, "termo", 5), "top": itens}
    for i in range(3):
        it = itens[i] if i < len(itens) else {"termo": "—", "freq": 0, "por_10k": 0.0, "docs": 0}
        m.update({f"termo_{i+1}": it["termo"], f"freq_{i+1}": it["freq"], f"por_10k_{i+1}": it["por_10k"], f"docs_{i+1}": it["docs"]})
    return m, [i["termo"] for i in itens[:3]], "lema"


def _m_tendencias(db, pasta, ctx):
    candidatos = [i["termo"] for i in _top_termos(ctx, 5)]
    if not candidatos:
        raise AnaliseIndisponivel("Sem termos frequentes: execute o pipeline.")
    r = frequencias.distribuicao(ctx["voc"], ctx["metas"], candidatos, por="lema", agrupar="ano")
    anos = [i for i, c in enumerate(r["categorias"]) if c["chave"] != dados.SEM_ANO and c["tokens"] > 0]
    if len(anos) < 2:
        raise AnaliseIndisponivel("Tendência precisa de documentos de pelo menos 2 anos diferentes (metadado 'ano').")
    serie = r["series"][0]
    i0, i1 = anos[0], anos[-1]
    rel0, rel1 = serie["rel"][i0], serie["rel"][i1]
    m = {"termo": serie["termo"], "n_anos": len(anos), "ano_inicial": r["categorias"][i0]["chave"], "ano_final": r["categorias"][i1]["chave"],
         "rel_inicial": rel0, "rel_final": rel1, "bruto_inicial": serie["brutos"][i0], "bruto_final": serie["brutos"][i1],
         "razao": round(rel1 / rel0, 2) if rel0 else 0.0,
         "serie": [{"ano": r["categorias"][i]["chave"], "por_10k": serie["rel"][i], "freq": serie["brutos"][i]} for i in anos]}
    return m, [serie["termo"]], "lema"


def _m_kwic(db, pasta, ctx):
    termo = (_top_termos(ctx, 1) or [{"termo": ""}])[0]["termo"]
    if not termo:
        raise AnaliseIndisponivel("Sem termos frequentes: execute o pipeline.")
    janela = int(ctx["params"].get("kwic_janela") or 10)
    r = kwic.buscar(pasta, ctx["metas"], termo, por="lema", janela=janela, limit=1)
    return ({"termo": termo, "total": r["total"], "documentos_com_ocorrencias": r["documentos_com_ocorrencias"],
             "n_documentos": len(ctx["metas"]), "janela": janela}, [termo], "lema")


def _m_colocacoes(db, pasta, ctx):
    termo = (_top_termos(ctx, 1) or [{"termo": ""}])[0]["termo"]
    if not termo:
        raise AnaliseIndisponivel("Sem termos frequentes: execute o pipeline.")
    j = min(int(ctx["params"].get("colocacao_janela") or 5), colocacoes.JANELA_MAXIMA)
    r = colocacoes.calcular(pasta, ctx["metas"], termo, por="lema", esquerda=j, direita=j, filtro=ctx["filtro"], filtrar=True,
                            min_freq=3, min_freq_colocado=5, ordem="ll", limite=10)
    cols = [{k: c[k] for k in ("termo", "o11", "c1", "ll", "mi", "p")} for c in r["colocados"]]
    m = {"termo": termo, "ocorrencias_no": r["ocorrencias_no"], "documentos_com_no": r["documentos_com_no"], "janela": j,
         "colocados_top": _mais("", cols, "termo", 5), "top": [{**c, "ll": _r(c["ll"], 1), "p": valor_p_texto(c["p"])} for c in cols]}
    for i in range(3):
        c = cols[i] if i < len(cols) else {"termo": "—", "o11": 0, "ll": 0.0, "mi": 0.0}
        m.update({f"colocado_{i+1}": c["termo"], f"o11_{i+1}": c["o11"], f"ll_{i+1}": _r(c["ll"], 1), f"mi_{i+1}": _r(c["mi"], 2)})
    return m, [termo, *[c["termo"] for c in cols[:2]]], "lema"


def _m_ngramas(db, pasta, ctx):
    r = ngramas.listar(pasta, ctx["metas"], ctx["filtro"], por="forma", n_min=2, n_max=4, stop="sem_bordas", quebrar_pontuacao=True,
                       min_freq=3, min_docs=2, ordem="freq", limite=10)
    itens = r["itens"]
    if not itens:
        raise AnaliseIndisponivel("Nenhum n-grama atinge a frequência mínima.")
    m = {"n_total": r["total"], "n_min": r["n_min"], "n_max": r["n_max"], "min_freq": r["min_freq"], "n_documentos": r["documentos"],
         "ngramas_top": _mais("", itens, "ngrama", 5), "top": itens}
    for i in range(3):
        it = itens[i] if i < len(itens) else {"ngrama": "—", "freq": 0, "docs": 0, "por_10k": 0.0}
        m.update({f"ngrama_{i+1}": it["ngrama"], f"freq_{i+1}": it["freq"], f"docs_{i+1}": it["docs"], f"por_10k_{i+1}": it["por_10k"]})
    return m, [f'"{i["ngrama"]}"' for i in itens[:3]], "forma"


def _lado_maior(lados: list[dict], excluir: str | None = None) -> str | None:
    cand = [x for x in lados if x["valor"] != excluir and x["documentos"] >= 2]
    return max(cand, key=lambda x: (x["tokens"], x["valor"]))["valor"] if cand else None


def _m_keyness(db, pasta, ctx):
    lados = keyness.lados_disponiveis(ctx["voc"], ctx["metas"])
    if lados["grupos_definidos"] >= 1:
        particao, a = "grupo", _lado_maior(lados["grupos"], dados.SEM_GRUPO)
    else:
        particao, a = "ano", _lado_maior(lados["anos"], dados.SEM_ANO)
    if a is None:
        raise AnaliseIndisponivel("Keyness precisa de um grupo (ou ano) com pelo menos 2 documentos, contra os demais.")
    try:
        r = keyness.calcular(ctx["voc"], ctx["metas"], ctx["filtro"], particao=particao, a=a, b=keyness.RESTO, por="lema", limite=10)
    except ValueError as exc:
        raise AnaliseIndisponivel(str(exc)) from exc
    pos, neg = r["positivas"], r["negativas"]
    m = {"particao": particao, "lado_a": a, "lado_b": "restante do corpus", "docs_a": r["lado_a"]["documentos"], "docs_b": r["lado_b"]["documentos"],
         "tokens_a": r["lado_a"]["tokens"], "tokens_b": r["lado_b"]["tokens"], "total_positivas": r["total_positivas"], "total_negativas": r["total_negativas"]}

    def linha(it):
        return {"termo": it["termo"], "a": it["a"], "b": it["b"], "por_10k_a": it["por_10k_a"], "por_10k_b": it["por_10k_b"],
                "g2": _r(abs(it["g2"]), 1), "log_ratio": _r(it["log_ratio"], 2), "p_texto": valor_p_texto(it["p"])}

    vazio = {"termo": "—", "a": 0, "b": 0, "por_10k_a": 0.0, "por_10k_b": 0.0, "g2": 0.0, "log_ratio": 0.0, "p_texto": "—"}
    for pref, itens, n in (("pos_", pos, 3), ("neg_", neg, 2)):
        for i in range(n):
            it = linha(itens[i]) if i < len(itens) else vazio
            m.update({f"{pref}{k}_{i+1}": v for k, v in it.items()})
    m["positivas"] = [linha(i) for i in pos[:10]]
    m["negativas"] = [linha(i) for i in neg[:5]]
    return m, [i["termo"] for i in pos[:2]] + [i["termo"] for i in neg[:1]], "lema"


def _m_especificidades(db, pasta, ctx):
    lados = keyness.lados_disponiveis(ctx["voc"], ctx["metas"])
    particao = "grupo" if lados["grupos_definidos"] >= 2 else "ano"
    try:
        r = especificidades.calcular(ctx["voc"], ctx["metas"], ctx["filtro"], particao=particao, por="lema", filtrar=True,
                                     min_freq=5, limiar=especificidades.LIMIAR_PADRAO, limite=5)
    except ValueError as exc:
        raise AnaliseIndisponivel(str(exc)) from exc
    if not r["partes"]:
        raise AnaliseIndisponivel("Especificidades precisa de pelo menos 2 partes com documentos.")
    parte = max(r["partes"], key=lambda x: (x["tokens"], x["chave"]))
    m = {"particao": particao, "n_partes": len(r["partes"]), "parte": parte["rotulo"], "parte_documentos": parte["documentos"],
         "parte_tokens": parte["tokens"], "limiar": r["limiar"], "teto": r["teto"]}
    vazio = {"termo": "—", "f": 0, "F": 0, "score": 0.0}
    for pref, itens, n in (("pos_", parte["positivas"], 3), ("neg_", parte["negativas"], 2)):
        for i in range(n):
            it = itens[i] if i < len(itens) else vazio
            m.update({f"{pref}{k}_{i+1}": (_r(it[k], 1) if k == "score" else it[k]) for k in ("termo", "f", "F", "score")})
    m["positivas"] = [{k: i[k] for k in ("termo", "f", "F", "score", "por_10k")} for i in parte["positivas"]]
    m["negativas"] = [{k: i[k] for k in ("termo", "f", "F", "score", "por_10k")} for i in parte["negativas"]]
    return m, [i["termo"] for i in parte["positivas"][:3]], "lema"


def _lado_eixo(linhas: list[dict], eixo: int, sinal: int, n: int = 4) -> str:
    sel = [l for l in linhas if l["coord"][eixo] * sinal > 0]
    sel.sort(key=lambda l: -l["ctr"][eixo])
    return ", ".join(l["termo"] for l in sel[:n]) or "—"


def _m_afc(db, pasta, ctx):
    lados = keyness.lados_disponiveis(ctx["voc"], ctx["metas"])
    particao = "grupo" if lados["grupos_definidos"] >= 2 else "ano"
    try:
        r = afc.calcular(ctx["voc"], ctx["metas"], ctx["filtro"], particao=particao, por="lema", filtrar=True, n_termos=100,
                         selecao="freq", eixos=afc.EIXOS_MAX, min_freq=5)
    except ValueError as exc:
        raise AnaliseIndisponivel(str(exc)) from exc
    if not r.get("eixos"):
        raise AnaliseIndisponivel(r.get("mensagem") or "A AFC não tem eixos neste corpus.")
    e = r["eixos"]
    e2 = e[1] if len(e) > 1 else {"autovalor": 0.0, "pct": 0.0, "pct_acumulado": e[0]["pct_acumulado"]}
    m = {"particao": particao, "n_linhas": r["n_linhas"], "n_colunas": r["n_colunas"], "n_eixos": r["k"], "inercia_total": _r(r["inercia_total"], 4),
         "chi2": _r(r["chi2"], 1), "autovalor_1": _r(e[0]["autovalor"], 4), "pct_1": _r(e[0]["pct"], 1), "autovalor_2": _r(e2["autovalor"], 4),
         "pct_2": _r(e2["pct"], 1), "pct_acumulado_2": _r(e2["pct_acumulado"], 1),
         "eixo1_positivo": _lado_eixo(r["linhas"], 0, 1), "eixo1_negativo": _lado_eixo(r["linhas"], 0, -1),
         "eixo2_positivo": _lado_eixo(r["linhas"], 1, 1) if len(e) > 1 else "—", "eixo2_negativo": _lado_eixo(r["linhas"], 1, -1) if len(e) > 1 else "—"}
    ordenados = sorted(r["linhas"], key=lambda l: -l["ctr"][0])
    return m, [l["termo"] for l in ordenados[:3]], "lema"


def _m_similaridade(db, pasta, ctx):
    try:
        r = similaridade.calcular(ctx["voc"], ctx["metas"], ctx["filtro"], por="lema", metodo="ward", k=None, min_df=2, max_df=0.9, sublinear=True)
    except ValueError as exc:
        raise AnaliseIndisponivel(str(exc)) from exc
    sil = next((s["silhueta"] for s in r.get("silhuetas", []) if s["k"] == r["k"]), 0.0)
    grupos = sorted(r["grupos"], key=lambda g: (-g["documentos"], g["cluster"]))
    m = {"n_documentos": r["n_documentos"], "n_termos": r["n_termos"], "n_excluidos": len(r.get("excluidos", [])), "metodo": "Ward", "k": r["k"],
         "modo_k": "escolhido automaticamente pela silhueta" if r.get("k_automatico") else "definido pelo usuário", "silhueta": _r(sil, 3)}
    for i in range(3):
        g = grupos[i] if i < len(grupos) else {"documentos": 0, "termos": []}
        m[f"grupo_docs_{i+1}"] = g["documentos"]
        m[f"grupo_termos_{i+1}"] = ", ".join(t["termo"] for t in g["termos"][:5]) or "—"
    m["grupos"] = [{"documentos": g["documentos"], "termos": [t["termo"] for t in g["termos"][:5]]} for g in grupos[:5]]
    primeiros = [t["termo"] for t in (grupos[0]["termos"] if grupos else [])[:3]]
    return m, primeiros, "lema"


def _m_dicionario(db, pasta, ctx):
    try:
        dic = svc_dicionario.carregar(pasta)
        r = dicionario.calcular(pasta, ctx["voc"], ctx["metas"], dic, por="lema", agrupar="grupo")
    except (svc_dicionario.DicionarioInvalido, ValueError) as exc:
        raise AnaliseIndisponivel(f"Dicionário inválido: {exc}") from exc
    cats = sorted([c for c in r["categorias"] if c["total"] > 0], key=lambda c: (-c["total"], c["id"]))
    if not cats:
        raise AnaliseIndisponivel("Dicionário vazio ou sem ocorrências: defina categorias e termos na aba Análises, seção Dicionário.")
    m = {"agrupar": r["agrupar"], "n_documentos": r["documentos"], "tokens": r["tokens"], "n_categorias": len(r["categorias"])}
    for i in range(3):
        c = cats[i] if i < len(cats) else {"nome": "—", "total": 0, "por_10k": 0.0, "docs": 0, "termos_top": []}
        m.update({f"cat_nome_{i+1}": c["nome"], f"cat_total_{i+1}": c["total"], f"cat_por_10k_{i+1}": c["por_10k"], f"cat_docs_{i+1}": c["docs"],
                  f"cat_termos_{i+1}": ", ".join(t["termo"] for t in c["termos_top"][:5]) or "—"})
    m["categorias"] = [{"nome": c["nome"], "total": c["total"], "por_10k": c["por_10k"], "docs": c["docs"]} for c in cats[:6]]
    return m, [t["termo"] for t in cats[0]["termos_top"][:3]], "lema"


_COLETORES = {"resumo": _m_resumo, "frequencias": _m_frequencias, "tendencias": _m_tendencias, "kwic": _m_kwic, "colocacoes": _m_colocacoes,
              "ngramas": _m_ngramas, "keyness": _m_keyness, "especificidades": _m_especificidades, "afc": _m_afc,
              "similaridade": _m_similaridade, "dicionario": _m_dicionario}


# ---------- evidências ----------

def _com_espaco(esq: str, dir_: str) -> str:
    """O KWIC devolve esquerda/direita sem espaços nas bordas: restaura o espaço entre o termo e as palavras vizinhas
    (sem espaço antes de pontuação de fechamento nem depois de abertura)."""
    if esq:
        return esq + ("" if esq[-1] in "([{“\"'" else " ")
    if dir_:
        return ("" if dir_[0] in ".,;:)]}?!%”\"'" else " ") + dir_
    return ""


def _evidencias(pasta: Path, ctx: dict, consultas: list[str], por: str) -> list[dict]:
    """Até 5 trechos KWIC (um por documento, com página), alternando entre as consultas."""
    janela = int(ctx["params"].get("kwic_janela") or 10)
    por_consulta: list[list[dict]] = []
    for q in consultas:
        try:
            r = kwic.buscar(pasta, ctx["metas"], q, por=por, janela=janela, limit=40)
        except ValueError:
            continue
        itens = []
        vistos: set[int] = set()
        for it in r["itens"]:
            if it.get("pagina") is None or it["documento_id"] in vistos:
                continue
            vistos.add(it["documento_id"])
            itens.append({"documento_id": it["documento_id"], "rotulo": it["rotulo"], "pagina": it["pagina"],
                          "trecho": montar_trecho(_com_espaco(it["esquerda"], ""), it["termo"], _com_espaco("", it["direita"])), "termo": it["termo"], "posicao": it["posicao"]})
        por_consulta.append(itens)
    saida: list[dict] = []
    usados: set[int] = set()
    i = 0
    while len(saida) < MAX_EVIDENCIAS and any(i < len(l) for l in por_consulta):
        for l in por_consulta:
            if i < len(l) and l[i]["documento_id"] not in usados and len(saida) < MAX_EVIDENCIAS:
                usados.add(l[i]["documento_id"])
                saida.append(l[i])
        i += 1
    return saida


def coletar(db: Session, pasta: Path, analise: str) -> dict:
    """{"metricas": {...}, "evidencias": [...]}. Levanta comum.SemDados ou AnaliseIndisponivel."""
    if analise not in _COLETORES:
        raise AnaliseIndisponivel(f"Análise desconhecida: {analise}.")
    ctx = _contexto(db, pasta)
    metricas, consultas, por = _COLETORES[analise](db, pasta, ctx)
    return {"metricas": metricas, "evidencias": _evidencias(pasta, ctx, consultas, por)}
