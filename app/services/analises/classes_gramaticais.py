"""4.5 - Frequências por classe gramatical e entidades nomeadas (consultas sobre o arquivo lateral do spaCy).

Os dados vêm de ``cache/spacy/<id>.json`` (ver ``services/spacy_nlp.py``); documentos sem o arquivo (spaCy ausente, idioma
sem modelo ou etapa ainda não executada) ficam fora e são listados em ``sem_classes``.

Frequências por classe: mesmo universo do vocabulário (tokens do corpo, >= 2 letras; as palavras vazias saem na consulta, como
no painel Frequências); o denominador do /10k são os tokens contados *com* vazias, como no painel Frequências. Um termo
recebe a classe em que mais aparece (``classe``) e a distribuição (``classes``). Filtro ``classes``: lista de UPOS ou atalhos
(``substantivos``, ``adjetivos``, ``verbos``, ``plenas``); só entram tokens cuja classe está no conjunto.

Entidades: só as do corpo (``incluir``), sem iniciais soltas nem palavras vazias/acadêmicas ("al", "pp"); as do NER do spaCy (``en_core_web_sm`` / ``pt_core_news_sm``; os rótulos diferem entre modelos: PERSON/PER, ORG,
GPE/LOC). Agrupadas por texto (sem diferenciar maiúsculas) e tipo. Os modelos pequenos erram bastante em texto acadêmico
(títulos e termos técnicos viram "ORG"): use como pista, confira no contexto. ``kwic`` = consulta de frase para abrir no KWIC.
"""
from collections import Counter

from app.services import spacy_nlp
from app.services.analises import dados
from app.services.palavras_vazias import COMPRIMENTO_MINIMO, token_vazio

AVISO_NER = ("Os modelos pequenos do spaCy erram bastante em prosa acadêmica (títulos, siglas e termos técnicos viram ORG ou PERSON): "
             "trate a lista como pista e confira no contexto (KWIC).")


def frequencias(pasta, metas: list[dict], filtro, classes, por: str = "lema", filtrar: bool = True, limite: int = 200) -> dict:
    """Termos mais frequentes restritos às ``classes`` (ver docstring do módulo). Levanta ValueError (classe inválida)."""
    conjunto = spacy_nlp.expandir_classes(classes)
    if not conjunto:
        raise ValueError("Informe ao menos uma classe gramatical (ex.: substantivos, adjetivos, verbos).")
    campo = "lema" if por == "lema" else "norm"
    freq: Counter = Counter()
    df: Counter = Counter()
    por_classe: dict[str, Counter] = {}
    tokens_total = 0
    usados, sem_classes = 0, []
    for m in metas:
        tk = dados.carregar_tokens(pasta, m["id"])
        if tk is None:
            continue
        ann = spacy_nlp.sidecar_valido(pasta, m["id"], tk, tk["idioma"])
        pos = spacy_nlp.classes_do_documento(ann)
        norm, lema, inc = tk["norm"], tk["lema"], tk["incluir"]
        tokens_total += sum(1 for i in range(tk["n"]) if inc[i] and len(norm[i]) >= COMPRIMENTO_MINIMO)
        if pos is None:
            sem_classes.append({"id": m["id"], "rotulo": m["rotulo"]})
            continue
        usados += 1
        local: Counter = Counter()
        for i in range(tk["n"]):
            if not inc[i] or len(norm[i]) < COMPRIMENTO_MINIMO or pos[i] not in conjunto:
                continue
            if filtrar and token_vazio(norm[i], lema[i], filtro):
                continue
            t = (lema if campo == "lema" else norm)[i]
            local[t] += 1
            por_classe.setdefault(t, Counter())[pos[i]] += 1
        freq.update(local)
        df.update(local.keys())
    ordenados = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    itens = [{"termo": t, "freq": c, "por_10k": round(c / tokens_total * 10000, 2) if tokens_total else 0.0, "docs": df[t],
              "classe": por_classe[t].most_common(1)[0][0], "classes": dict(por_classe[t])}
             for t, c in ordenados[: max(0, limite)]]
    return {"por": por, "classes": sorted(conjunto), "filtradas": filtrar, "documentos": usados, "tokens": tokens_total,
            "tipos": len(freq), "itens": itens, "sem_classes": sem_classes}


def _consulta_kwic(texto: str) -> str:
    palavras = [p for p in texto.lower().replace('"', " ").split() if p]
    return f'"{" ".join(palavras)}"' if len(palavras) > 1 else (palavras[0] if palavras else "")


def entidades(pasta, metas: list[dict], tipos=None, min_freq: int = 1, limite: int = 200, documento_id: int | None = None,
              filtro=frozenset()) -> dict:
    """Entidades por tipo no corpus (ou num documento). ``tipos`` vazio/None = ORG, PERSON, GPE (+ PER/LOC dos modelos PT)."""
    tipos = [t.strip().upper() for t in (tipos or []) if t.strip()] or list(spacy_nlp.TIPOS_ENTIDADE_PADRAO)
    if "PERSON" in tipos and "PER" not in tipos:
        tipos.append("PER")  # rótulo do modelo português
    if "GPE" in tipos and "LOC" not in tipos:
        tipos.append("LOC")
    alvo = set(tipos)
    if documento_id is not None:
        metas = [m for m in metas if m["id"] == documento_id]
    contagem: Counter = Counter()
    docs: dict[tuple, set] = {}
    forma_comum: dict[tuple, Counter] = {}
    exemplos: dict[tuple, list] = {}
    por_doc: dict[int, Counter] = {}
    rotulos = {m["id"]: m["rotulo"] for m in metas}
    sem_ner, tipos_vistos = [], Counter()
    for m in metas:
        tk = dados.carregar_tokens(pasta, m["id"])
        ann = spacy_nlp.sidecar_valido(pasta, m["id"], tk, tk["idioma"]) if tk else None
        if ann is None:
            sem_ner.append({"id": m["id"], "rotulo": m["rotulo"]})
            continue
        incl = tk["incluir"]
        for e in ann["ents"]:
            if not incl[e["inicio_token"]]:
                continue  # só o corpo: referências e apêndices geram entidades-lixo (iniciais de autores, "et al.")
            tipos_vistos[e["tipo"]] += 1
            if e["tipo"] not in alvo:
                continue
            letras = [ch for ch in e["texto"] if ch.isalpha()]
            if len(letras) < 2 or (filtro and e["texto"].lower().strip(" .") in filtro):
                continue  # iniciais soltas ("Y.") e palavras vazias/acadêmicas ("al", "pp")
            chave = (" ".join(e["texto"].lower().split()), e["tipo"])
            contagem[chave] += 1
            docs.setdefault(chave, set()).add(m["id"])
            forma_comum.setdefault(chave, Counter())[e["texto"]] += 1
            lst = exemplos.setdefault(chave, [])
            if len(lst) < 5:
                lst.append({"documento_id": m["id"], "rotulo": m["rotulo"], "pagina": e["pagina"]})
            por_doc.setdefault(m["id"], Counter())[chave] += 1
    itens = [{"texto": forma_comum[k].most_common(1)[0][0], "tipo": k[1], "freq": c, "docs": len(docs[k]),
              "kwic": _consulta_kwic(k[0]), "exemplos": exemplos[k]}
             for k, c in sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0])) if c >= min_freq][: max(0, limite)]
    resumo_docs = [{"id": i, "rotulo": rotulos[i], "entidades": sum(c.values()), "distintas": len(c)} for i, c in sorted(por_doc.items())]
    return {"tipos": sorted(alvo), "tipos_no_corpus": dict(tipos_vistos.most_common()), "itens": itens,
            "total_distintas": len(contagem), "por_documento": resumo_docs, "sem_ner": sem_ner, "aviso": AVISO_NER}
