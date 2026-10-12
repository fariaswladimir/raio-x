"""9.1 - Laudo HTML: um único arquivo autossuficiente (CSS e JS embutidos, sem recursos externos).

Princípio 4: o texto do laudo vem **só** de comentários ``aceito`` ou ``editado`` (o editado mostra o texto humano),
mais métricas calculadas e parâmetros. Comentários ``sugerido``/``revisar``/``rejeitado``/``obsoleto`` não entram;
um aviso no topo conta os que aguardam revisão. Rastreabilidade: cada número de um comentário é um link para as
evidências dele, e cada evidência traz "(rótulo, p. N)". Rodapé: "gerado sem LLM" (D1), a menos que um comentário
redigido com LLM (Frente 14, origem "llm") tenha sido aceito: então o rodapé e a seção Métodos declaram o provedor e o modelo.
"""
import html
import json
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import VERSAO
from app.models import Comentario, Documento, Execucao, Projeto, agora
from app.services import parametros as svc_parametros
from app.services.analises import dados, frequencias, resumo
from app.services.exportar import comum
from app.services.exportar.metodos import METODOS, ORDEM, ROTULO_METRICA, parametros_do_metodo, referencias
from app.services.metodologia import formatos as formatos_ref
from app.services.regras import checagem
from app.services.regras.catalogo import ANALISES, hash_catalogo
from app.services.texto import ler_qualidade

TOP_FREQUENCIAS = 20
TOP_KEYNESS = 15
TOP_COLOCADOS = 8
MAX_TERMOS_TENDENCIA = 6
MAX_TERMOS_COLOCACAO = 6
TITULOS_RESULTADO = {
    "resumo": "Resumo do corpus", "frequencias": "Frequências", "tendencias": "Tendências no tempo",
    "keyness": "Palavras-chave entre grupos", "colocacoes": "Colocações", "outros": "Outros comentários",
}


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def fmt(v, casas: int = 2) -> str:
    """Número em pt-BR (ponto de milhar, vírgula decimal)."""
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, float):
        if v != 0 and abs(v) < 10 ** -casas:
            return f"{v:.2e}".replace(".", ",")
        return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return esc(v)


def _data(d) -> str:
    return d.strftime("%d/%m/%Y %H:%M") + " UTC" if d else "—"


# ---------- coleta ----------

def _json(texto):
    try:
        return json.loads(texto) if texto else {}
    except ValueError:
        return {}


def _snapshot(db: Session, tipo: str):
    from app.models import Analise
    linha = db.scalars(select(Analise).where(Analise.tipo == tipo).order_by(Analise.id.desc()).limit(1)).first()
    return (_json(linha.resultado_json), linha.criado_em) if linha and linha.resultado_json else (None, None)


def modelos_llm(comentarios) -> list[str]:
    """"provedor: modelo" de cada comentário de origem LLM da lista, sem repetição (vazio = laudo sem LLM)."""
    vistos: list[str] = []
    for c in comentarios:
        if c.origem != "llm":
            continue
        llm = _json(c.metricas_json).get("llm") or {}
        nome = f"{llm.get('provedor', 'LLM')}: {llm.get('modelo') or c.regra.removeprefix('LLM:')}"
        if nome not in vistos:
            vistos.append(nome)
    return vistos


def coletar(db: Session, pasta: Path) -> dict:
    """Tudo o que o laudo mostra, em um dicionário (levanta ``comum.SemDados`` se o pipeline não rodou)."""
    ctx = comum.contexto(db, pasta)
    params, metas = ctx["params"], ctx["metas"]
    # 8.3: nenhum comentário com evidência ou número inválido entra no laudo (vai para "revisar" com o motivo)
    checagem_resultado = checagem.checar_todos(db, pasta, params)
    todos = list(db.scalars(select(Comentario).order_by(Comentario.analise_tipo, Comentario.forca.desc(), Comentario.id)))
    ordem = {a: i for i, a in enumerate(ANALISES)}
    todos.sort(key=lambda c: (ordem.get(c.analise_tipo, len(ordem)), -(c.forca or 0), c.id))
    aceitos = [c for c in todos if c.status in comum.STATUS_NO_LAUDO]
    contagem = Counter(c.status for c in todos)
    res = resumo.resumo_do_projeto(pasta, metas, params)
    snap_key, snap_key_em = _snapshot(db, "keyness")
    execucoes: dict[str, Execucao] = {}
    for e in db.scalars(select(Execucao).order_by(Execucao.id.desc())):
        execucoes.setdefault(e.etapa, e)
    projeto = db.scalars(select(Projeto).limit(1)).first()
    return {
        "ctx": ctx, "projeto": projeto, "params": params, "hash": svc_parametros.hash_parametros(params),
        "documentos": list(db.scalars(select(Documento).order_by(Documento.arquivo))), "resumo": res,
        "aceitos": aceitos, "llm_usados": modelos_llm(aceitos), "contagem": contagem, "pendentes": contagem["sugerido"] + contagem["revisar"],
        "snap_keyness": snap_key, "snap_keyness_em": snap_key_em, "execucoes": list(execucoes.values()),
        "gerado_em": agora(), "pasta": pasta, "checagem": checagem_resultado,
    }


# ---------- peças de HTML ----------

def tabela(cabecalho: list[str], linhas: list[list], num_de: int = 99, classe: str = "") -> str:
    """Tabela HTML; ``linhas`` com células já em HTML; colunas a partir de ``num_de`` alinhadas à direita."""
    if not linhas:
        return ""
    cab = "".join(f"<th{' class=\"n\"' if i >= num_de else ''}>{esc(c)}</th>" for i, c in enumerate(cabecalho))
    corpo = "".join("<tr>" + "".join(f"<td{' class=\"n\"' if i >= num_de else ''}>{c}</td>" for i, c in enumerate(l)) + "</tr>"
                    for l in linhas)
    return f'<div class="tab"><table class="{classe}"><thead><tr>{cab}</tr></thead><tbody>{corpo}</tbody></table></div>'


def svg_barras(itens: list[tuple[str, float, str]], titulo: str) -> str:
    """Barras horizontais. ``itens`` = (rótulo, valor, classe 'a'|'b'); valores negativos crescem para a esquerda (divergente)."""
    if not itens:
        return ""
    maximo = max(abs(v) for _r, v, _c in itens) or 1
    alt, larg, rot = 20, 640, 170
    divergente = any(v < 0 for _r, v, _c in itens)
    area = larg - rot - 90
    meio = rot + (area / 2 if divergente else 0)
    escala = (area / 2 if divergente else area) / maximo
    linhas = []
    for i, (r, v, c) in enumerate(itens):
        y = i * alt + 4
        w = abs(v) * escala
        x = meio - w if v < 0 else meio
        linhas.append(
            f'<text x="{rot - 6}" y="{y + 12}" text-anchor="end" class="rot">{esc(r[:26])}</text>'
            f'<rect x="{x:.1f}" y="{y}" width="{max(w, 1):.1f}" height="{alt - 6}" class="barra-{c}"><title>{esc(r)}: {esc(fmt(v))}</title></rect>'
            f'<text x="{(x + w + 4) if v >= 0 else (x - 4):.1f}" y="{y + 12}" text-anchor="{"start" if v >= 0 else "end"}" class="val">{esc(fmt(abs(v), 1 if abs(v) < 100 else 0))}</text>')
    eixo = f'<line x1="{meio:.1f}" y1="0" x2="{meio:.1f}" y2="{len(itens) * alt + 4}" class="eixo"/>' if divergente else ""
    return (f'<svg class="grafico" viewBox="0 0 {larg} {len(itens) * alt + 8}" role="img" aria-label="{esc(titulo)}">'
            f'{eixo}{"".join(linhas)}</svg>')


_NUMERO = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*")


def texto_com_ancoras(texto: str, cid: int) -> str:
    """Escapa o texto e transforma cada número num link para as evidências do comentário."""
    seguro = html.escape(texto, quote=False)
    return _NUMERO.sub(lambda m: f'<a class="num" href="#ev-{cid}">{m.group(0)}</a>', seguro)


def trecho_destacado(trecho: str, termo: str | None) -> str:
    formas = [t for t in (termo or "").split("|") if t.strip()]
    if not formas:
        return esc(trecho)
    padrao = re.compile("(" + "|".join(re.escape(f) for f in sorted(formas, key=len, reverse=True)) + ")", re.IGNORECASE)
    return "".join(f"<mark>{esc(p)}</mark>" if i % 2 else esc(p) for i, p in enumerate(padrao.split(trecho)))


def comentario_html(c: Comentario) -> str:
    evid = []
    for e in sorted(c.evidencias, key=lambda e: e.id):
        rotulo = dados.rotulo_do_documento(e.documento)
        pag = f"p. {e.pagina}" if e.pagina is not None else "p. n/d"
        evid.append(f'<li><q>{trecho_destacado(e.trecho, e.termo)}</q> <span class="cit">({esc(rotulo)}, {esc(pag)})</span></li>')
    bloco_ev = (f'<details class="evid" id="ev-{c.id}"><summary>Evidências ({len(evid)})</summary><ul>{"".join(evid)}</ul></details>'
                if evid else f'<p class="evid-vazia" id="ev-{c.id}">Sem trechos de evidência: o comentário se apoia só nas métricas abaixo.</p>')
    m = {k: v for k, v in _json(c.metricas_json).items() if v is None or isinstance(v, (int, float, str))}
    met = ""
    if m:
        itens = "".join(f"<dt>{esc(ROTULO_METRICA.get(k, k))}</dt><dd>{esc(fmt(v, 3 if isinstance(v, float) and abs(v) < 10 else 1))}</dd>"
                        for k, v in m.items())
        met = f'<details class="met"><summary>Métricas</summary><dl>{itens}</dl></details>'
    quem = f"{'Editado' if c.status == 'editado' else 'Aceito'} por {esc(c.revisor)}" if c.revisor else ("Editado" if c.status == "editado" else "Aceito")
    quem += f" em {esc(_data(c.atualizado_em))}"
    original = ""
    if c.status == "editado" and c.texto_original and c.texto_original != c.texto:
        original = f'<details class="met"><summary>Texto gerado pela regra (antes da edição)</summary><p>{esc(c.texto_original)}</p></details>'
    nota = f'<p class="nota"><b>Nota do revisor:</b> {esc(c.nota)}</p>' if c.nota else ""
    marca_llm = ('<span class="tag llm" title="Texto redigido com auxílio de LLM e revisado por humano">redigido com LLM</span>'
                 if c.origem == "llm" else "")
    return (f'<article class="cm" id="c-{c.id}" data-regra="{esc(c.regra)}">'
            f'<p class="cm-topo"><span class="tag">{esc(c.regra)}</span>{marca_llm}<span class="st st-{esc(c.status)}">{esc(c.status)}</span></p>'
            f'<p class="texto">{texto_com_ancoras(c.texto, c.id)}</p>{nota}{bloco_ev}{met}{original}'
            f'<p class="meta">{quem}</p></article>')


# ---------- seções ----------

def _identificacao(d: dict) -> str:
    p = d["projeto"]
    linhas = [
        ("Projeto", esc(p.nome if p else "—")),
        ("Pasta de origem", f"<code>{esc(p.pasta_origem if p else '—')}</code>"),
        ("Gerado em", esc(_data(d["gerado_em"]))),
        ("Versão do Raio-X", esc(VERSAO)),
        ("Versão dos parâmetros", f"{esc(d['params'].get('versao_parametros'))}"),
        ("Hash dos parâmetros (sha256)", f"<code>{esc(d['hash'])}</code>"),
        ("Catálogo de regras (hash)", f"<code>{esc(hash_catalogo()[:16])}</code>"),
    ]
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in linhas)
    return f'<section id="identificacao"><h2>1. Identificação</h2><dl class="ident">{dl}</dl></section>'


def _corpus(d: dict) -> str:
    res = d["resumo"] or {"corpus": {}, "documentos": []}
    c = res["corpus"]
    por_id = {x["documento_id"]: x for x in res["documentos"]}
    anos = [m["ano"] for m in d["ctx"]["metas"] if m.get("ano")]
    periodo = f"{min(anos)}–{max(anos)}" if anos else "sem ano informado"
    grupos = ", ".join(f"{esc(g['grupo'])} ({g['documentos']})" for g in c.get("documentos_por_grupo", [])) or "—"
    cartoes = [("Documentos analisados", fmt(c.get("n_documentos"))), ("Palavras (corpo do texto)", fmt(c.get("tokens"))),
               ("Período", periodo), ("Grupos", grupos)]
    cards = "".join(f'<div class="cartao"><span class="rot">{k}</span><b>{v}</b></div>' for k, v in cartoes)
    linhas, excluidos = [], []
    for doc in d["documentos"]:
        q = ler_qualidade(doc)
        meta = dados.meta_do_documento(doc)
        r = por_id.get(doc.id)
        situ = doc.status
        linhas.append([esc(meta["rotulo"]), esc(doc.ano or "—"), esc(doc.grupo or "—"), esc(q.get("paginas") if q.get("paginas") is not None else "—"),
                       fmt(r["tokens"]) if r else "—", esc(q.get("idioma") or "—"), esc(situ)])
        if doc.status in ("com_problema", "removido") or doc.excluido:
            motivo = " | ".join(q.get("problemas") or []) or ("removido da pasta de origem" if doc.status == "removido" else (
                "excluído da análise pelo usuário" if doc.excluido else "sem motivo registrado"))
            excluidos.append([esc(meta["rotulo"]), esc(doc.arquivo), esc("excluido" if doc.excluido else doc.status), esc(motivo)])
    tab = tabela(["Documento", "Ano", "Grupo", "Páginas", "Palavras", "Idioma", "Situação"], linhas, classe="ordenavel")
    exc = ""
    if excluidos:
        exc = (f'<h3>Documentos fora das análises ({len(excluidos)})</h3>'
               + tabela(["Documento", "Arquivo", "Situação", "Motivo"], excluidos))
    return (f'<section id="corpus"><h2>2. Corpus</h2><div class="cartoes">{cards}</div>'
            f'<h3>Documentos ({len(linhas)})</h3>{tab}{exc}</section>')


def _analises_usadas(d: dict, por_analise: dict[str, list[Comentario]]) -> list[str]:
    usadas = {a for a, lista in por_analise.items() if lista and a in METODOS}
    if d["resumo"]:
        usadas.add("resumo")
        usadas.add("frequencias")
    if d["snap_keyness"]:
        usadas.add("keyness")
    if any(c.evidencias for c in d["aceitos"]):
        usadas.add("kwic")
    return [a for a in ORDEM if a in usadas]


def _metodos(d: dict, usadas: list[str]) -> str:
    partes, refs_usadas = [], []
    for a in usadas:
        m = METODOS[a]
        params = "".join(f"<li>{esc(p)}</li>" for p in parametros_do_metodo(a, d["params"], d["snap_keyness"]))
        citacoes = "; ".join(esc(f"{formatos_ref.sobrenome_primeiro_autor(r)} ({r['ano']})") for r in referencias(m["refs"]))
        partes.append(
            f'<article class="metodo" id="metodo-{a}"><h3>{esc(m["titulo"])}</h3><dl>'
            f'<dt>O que mede</dt><dd>{esc(m["mede"])}</dd><dt>Métrica</dt><dd>{esc(m["metrica"])}</dd>'
            f'<dt>Parâmetros</dt><dd><ul>{params}</ul></dd>'
            f'<dt>Equivale a</dt><dd>{esc(m["equivale"])}</dd><dt>Não é igual a</dt><dd>{esc(m["nao_igual"])}</dd>'
            f'<dt>Referências</dt><dd>{citacoes}</dd></dl></article>')
        refs_usadas.extend(k for k in m["refs"] if k not in refs_usadas)
    if d.get("llm_usados"):
        partes.append(
            '<article class="metodo" id="metodo-llm"><h3>Redação assistida por LLM</h3>'
            f'<p>Parte dos comentários foi redigida com auxílio de modelo de linguagem ({esc("; ".join(d["llm_usados"]))}). '
            'O modelo recebeu apenas as métricas calculadas pelo Raio-X, o parágrafo-modelo e até cinco trechos do corpus, com instrução de '
            'não acrescentar números, fontes nem afirmações causais. Cada texto passou por conferência automática (números contra as métricas '
            'fornecidas, citações "(rótulo, p. N)" e trechos entre aspas contra as evidências) e por revisão humana: só entram neste laudo os '
            'comentários aceitos ou editados por um revisor, e os redigidos com LLM aparecem marcados.</p></article>')
    lista = "".join(f"<li>{esc(formatos_ref.formatar(r, 'abnt'))}</li>" for r in (referencias(refs_usadas) if refs_usadas else []))
    return (f'<section id="metodos"><h2>3. Métodos</h2>'
            f'<p class="discreto">Cada número do laudo vem destas análises; os parâmetros são os do projeto (seção 6).</p>'
            f'{"".join(partes)}<h3>Referências</h3><ol class="refs">{lista}</ol>'
            f'<p class="discreto">Conferir DOI, páginas e edição antes de citar em um artigo.</p></section>')


def _tabela_resumo(d: dict) -> str:
    c = (d["resumo"] or {}).get("corpus") or {}
    if not c:
        return ""
    linhas = [["Documentos", fmt(c["n_documentos"])], ["Palavras no corpo (sem referências)", fmt(c["tokens"])],
              ["Palavras no total", fmt(c["tokens_total"])], ["Tipos (lemas)", fmt(c["tipos_lema"])],
              ["Densidade vocabular (lemas/palavras)", fmt(c["densidade_lema"], 4)],
              [f"MATTR médio (janela {c['mattr_janela']}; {c['mattr_documentos_comparaveis']} docs comparáveis)", fmt(c["mattr_media"], 3)],
              ["Mediana de palavras por documento", fmt(c["mediana_tokens"], 0)]]
    por_grupo = tabela(["Grupo", "Documentos"], [[esc(g["grupo"]), fmt(g["documentos"])] for g in c["documentos_por_grupo"]], 1)
    return tabela(["Medida", "Valor"], linhas, 1) + f"<h4>Documentos por grupo</h4>{por_grupo}"


def _tabela_frequencias(d: dict) -> str:
    ctx = d["ctx"]
    r = frequencias.listar(ctx["voc"], ctx["metas"], ctx["filtro"], por="lema", filtrar=True, limite=TOP_FREQUENCIAS)
    linhas = [[str(i + 1), esc(t["termo"]), fmt(t["freq"]), fmt(t["por_10k"]), fmt(t["docs"])] for i, t in enumerate(r["itens"])]
    graf = svg_barras([(t["termo"], float(t["freq"]), "a") for t in r["itens"][:15]], "Frequência dos termos mais frequentes")
    return (f"<h4>Os {TOP_FREQUENCIAS} lemas mais frequentes ({fmt(r['documentos'])} documentos, {fmt(r['tokens'])} palavras)</h4>"
            + graf + tabela(["#", "Lema", "Frequência", "Por 10 mil", "Documentos"], linhas, 2))


def _tabela_tendencias(d: dict, comentarios: list[Comentario]) -> str:
    termos = comum.termos_dos_comentarios(comentarios)[:MAX_TERMOS_TENDENCIA]
    if not termos:
        return ""
    ctx = d["ctx"]
    r = frequencias.distribuicao(ctx["voc"], ctx["metas"], termos, por="lema", agrupar="ano", metrica="rel")
    cab = ["Lema", *[c["rotulo"] for c in r["categorias"]]]
    linhas = [[esc(s["termo"]), *[fmt(v) for v in s["rel"]]] for s in r["series"]]
    return "<h4>Frequência por 10 mil palavras, por ano (termos comentados)</h4>" + tabela(cab, linhas, 1)


def _tabela_keyness(d: dict) -> str:
    snap = d["snap_keyness"]
    if not snap:
        return ""
    saida = [f'<p class="discreto">Cada grupo contra os demais documentos; instantâneo de {esc(_data(d["snap_keyness_em"]))}. '
             f'Mostra as {TOP_KEYNESS} palavras-chave de maior G² de cada lado (A = o grupo; B = os demais).</p>']
    for comp in snap["comparacoes"]:
        a, b = comp["lado_a"], comp["lado_b"]
        saida.append(f'<h4>{esc(a["valor"])} ({fmt(a["documentos"])} docs, {fmt(a["tokens"])} palavras) contra {esc(b["valor"])} '
                     f'({fmt(b["documentos"])} docs, {fmt(b["tokens"])} palavras)</h4>')
        pos, neg = comp["positivas"][:TOP_KEYNESS], comp["negativas"][:TOP_KEYNESS]
        itens = [(k["termo"], k["log_ratio"], "a") for k in pos] + [(k["termo"], k["log_ratio"], "b") for k in neg]
        saida.append('<p class="discreto">Barras: Log Ratio (efeito); à direita, mais frequente em ' + esc(a["valor"]) + "; à esquerda, nos demais.</p>")
        saida.append(svg_barras(itens, f"Palavras-chave de {a['valor']}"))
        for rot, lista in (("sobre-representadas em " + a["valor"], pos), ("sub-representadas em " + a["valor"], neg)):
            linhas = [[esc(k["termo"]), fmt(k["a"]), fmt(k["b"]), fmt(k["g2"], 1), fmt(k["p"]), fmt(k["log_ratio"]),
                       f"{fmt(k['docs_a'])} / {fmt(k['docs_b'])}"] for k in lista]
            if linhas:
                saida.append(f"<h5>{esc(rot)}</h5>" + tabela(["Lema", "Freq. A", "Freq. B", "G²", "p", "Log Ratio", "Docs A / B"], linhas, 1))
    return "".join(saida)


def _tabela_colocacoes(d: dict, comentarios: list[Comentario]) -> str:
    termos = comum.termos_dos_comentarios(comentarios, ("colocacoes",))[:MAX_TERMOS_COLOCACAO]
    if not termos:
        return ""
    saida = ['<p class="discreto">Colocados dos termos comentados (janela e filtros do projeto, ordenados por log-likelihood).</p>']
    for termo, r in comum.colocados_dos_termos(d["pasta"], d["ctx"], termos, limite=TOP_COLOCADOS):
        linhas = [[esc(c["termo"]), fmt(c["o11"]), fmt(c["ll"], 1), fmt(c["mi"]), fmt(c["p"])] for c in r["colocados"]]
        saida.append(f"<h4>Colocados de ‘{esc(termo)}’</h4>" + (tabela(["Colocado", "Coocorrências", "LL", "MI", "p"], linhas, 1)
                                                               or '<p class="discreto">Nenhum colocado acima dos limites mínimos.</p>'))
    return "".join(saida)


def _resultados(d: dict, usadas: list[str], por_analise: dict[str, list[Comentario]]) -> str:
    blocos = []
    for chave in (*ANALISES, "outros"):
        lista = por_analise.get(chave, [])
        if chave == "resumo":
            tab = _tabela_resumo(d)
        elif chave == "frequencias":
            tab = _tabela_frequencias(d)
        elif chave == "tendencias":
            tab = _tabela_tendencias(d, lista)
        elif chave == "keyness":
            tab = _tabela_keyness(d)
        elif chave == "colocacoes":
            tab = _tabela_colocacoes(d, lista)
        else:
            tab = ""
        if not lista and not tab:
            continue
        cms = "".join(comentario_html(c) for c in lista) or '<p class="vazio">Nenhum comentário aceito para esta análise.</p>'
        blocos.append(f'<section class="analise" id="res-{chave}"><h3>{esc(TITULOS_RESULTADO[chave])}</h3>'
                      f'<div class="comentarios">{cms}</div><div class="numeros">{tab}</div></section>')
    if not d["aceitos"]:
        blocos.insert(0, '<p class="vazio">Nenhum comentário foi aceito ainda: abaixo só aparecem as métricas do corpus.</p>')
    return f'<section id="resultados"><h2>4. Resultados</h2>{"".join(blocos)}</section>'


def _notas(d: dict) -> str:
    com_nota = [c for c in d["aceitos"] if c.nota]
    revisores = sorted({c.revisor for c in d["aceitos"] if c.revisor})
    rev = ", ".join(esc(r) for r in revisores) or "não informado"
    if com_nota:
        linhas = [[f'<a href="#c-{c.id}">{esc(c.regra)}</a>', esc(c.nota), esc(c.revisor or "—"), esc(_data(c.atualizado_em))]
                  for c in com_nota]
        notas = tabela(["Comentário", "Nota", "Revisor", "Data"], linhas)
    else:
        notas = '<p class="vazio">Nenhuma anotação do revisor nos comentários incluídos.</p>'
    return f'<section id="notas"><h2>5. Notas do revisor</h2><p>Revisores: {rev}.</p>{notas}</section>'


def _parametros(d: dict) -> str:
    log = []
    for e in sorted(d["execucoes"], key=lambda e: e.iniciado_em):
        log.append([esc(e.etapa), esc(e.status), esc(_data(e.iniciado_em)), esc(_data(e.finalizado_em)),
                    esc((e.mensagem or "")[:160])])
    js = json.dumps(d["params"], ensure_ascii=False, indent=2)
    return (f'<section id="parametros"><h2>6. Parâmetros e registro de execução</h2><h3>parametros.json</h3>'
            f'<p class="discreto">Versão {esc(d["params"].get("versao_parametros"))}; sha256 do conteúdo: <code>{esc(d["hash"])}</code>.</p>'
            f'<pre class="codigo">{esc(js)}</pre><h3>Última execução de cada etapa</h3>'
            + (tabela(["Etapa", "Status", "Início", "Fim", "Mensagem"], log) or '<p class="vazio">Sem execuções registradas.</p>')
            + "</section>")


def _aviso_checagem(d: dict) -> str:
    falhas = d["checagem"]["falhas"]
    if not falhas:
        return ""
    itens = "".join(f"<li>#{f['id']} ({esc(f['regra'])}): {esc('; '.join(f['motivos']))}</li>" for f in falhas)
    return (f'<div class="aviso" role="note"><b>{len(falhas)} comentário{"s" if len(falhas) != 1 else ""} reprovado{"s" if len(falhas) != 1 else ""} '
            f'na checagem de evidência — não entraram no laudo e voltaram para revisão.</b><ul>{itens}</ul></div>')


def _aviso_pendentes(d: dict) -> str:
    n = d["pendentes"]
    c = d["contagem"]
    extras = []
    if c["rejeitado"]:
        extras.append(f"{c['rejeitado']} rejeitado(s)")
    if c["obsoleto"]:
        extras.append(f"{c['obsoleto']} obsoleto(s)")
    detalhe = f" ({c['sugerido']} sugerido(s), {c['revisar']} a revisar)" if n else ""
    resto = f" Também ficam de fora: {', '.join(extras)}." if extras else ""
    if n:
        return (f'<div class="aviso" role="note"><b>{n} comentário{"s" if n != 1 else ""} aguarda{"m" if n != 1 else ""} revisão — '
                f'não entraram no laudo.</b>{detalhe}{resto}</div>')
    return f'<div class="aviso ok" role="note">Nenhum comentário aguarda revisão.{resto}</div>'


CSS = """
:root{--fundo:#f7f7f5;--painel:#fff;--texto:#1e1e1e;--suave:#5f5f5f;--borda:#d8d8d2;--destaque:#1f5fbf;--a:#1f5fbf;--b:#c2571a;--marca:#fff2a8;--aviso-f:#fff4dc;--aviso-b:#e0b25a;--ok-f:#e6f4ea;--ok-b:#7bbf8e}
@media (prefers-color-scheme:dark){:root:not([data-tema=claro]){--fundo:#16181b;--painel:#1e2126;--texto:#e6e6e6;--suave:#a0a0a0;--borda:#33373d;--destaque:#6ea8fe;--a:#6ea8fe;--b:#f0a060;--marca:#5c4d00;--aviso-f:#33290f;--aviso-b:#8a6d2a;--ok-f:#14301c;--ok-b:#2f7a45}}
:root[data-tema=escuro]{--fundo:#16181b;--painel:#1e2126;--texto:#e6e6e6;--suave:#a0a0a0;--borda:#33373d;--destaque:#6ea8fe;--a:#6ea8fe;--b:#f0a060;--marca:#5c4d00;--aviso-f:#33290f;--aviso-b:#8a6d2a;--ok-f:#14301c;--ok-b:#2f7a45}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font:16px/1.55 system-ui,"Segoe UI",Roboto,sans-serif;background:var(--fundo);color:var(--texto);overflow-wrap:anywhere}
header.topo{padding:18px 16px 8px;max-width:1000px;margin:0 auto}
header.topo h1{margin:0 0 4px;font-size:1.6rem}
.sub{color:var(--suave);margin:0}
nav.sumario{position:sticky;top:0;z-index:5;background:var(--painel);border-bottom:1px solid var(--borda);padding:8px 16px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:.9rem}
nav.sumario a{color:var(--destaque);text-decoration:none}
nav.sumario .esp{flex:1}
button{font:inherit;font-size:.85rem;padding:3px 10px;border:1px solid var(--destaque);border-radius:5px;background:transparent;color:var(--destaque);cursor:pointer}
main{max-width:1000px;margin:0 auto;padding:8px 16px 32px}
section{background:var(--painel);border:1px solid var(--borda);border-radius:8px;padding:14px 16px;margin:16px 0;min-width:0}
section.analise{border:0;border-top:1px solid var(--borda);border-radius:0;padding:12px 0;margin:8px 0;background:transparent}
h2{font-size:1.25rem;margin:0 0 8px}h3{font-size:1.05rem;margin:14px 0 6px}h4{font-size:.95rem;margin:14px 0 6px}h5{font-size:.9rem;margin:10px 0 4px;color:var(--suave)}
code{font:.85em ui-monospace,Consolas,monospace;overflow-wrap:anywhere}
.aviso{background:var(--aviso-f);border:1px solid var(--aviso-b);border-radius:6px;padding:10px 12px;margin:12px 0}
.aviso.ok{background:var(--ok-f);border-color:var(--ok-b)}
.discreto,.vazio{color:var(--suave);font-size:.9rem}
.cartoes{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.cartao{border:1px solid var(--borda);border-radius:6px;padding:8px 10px}.cartao .rot{display:block;color:var(--suave);font-size:.8rem}.cartao b{font-size:1.1rem}
dl.ident{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0}dl.ident dt{color:var(--suave)}dl.ident dd{margin:0}
.tab{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--borda);vertical-align:top}
th{color:var(--suave);font-weight:600;white-space:nowrap}th.n,td.n{text-align:right}
table.ordenavel th{cursor:pointer}
.cm{border:1px solid var(--borda);border-left:4px solid var(--destaque);border-radius:6px;padding:8px 12px;margin:10px 0}
.cm:target{outline:2px solid var(--destaque)}
.cm-topo{margin:0 0 4px;display:flex;gap:8px;align-items:center}
.tag.llm{background:transparent;color:var(--aviso);border-color:var(--aviso);margin-left:6px;font-family:inherit;font-weight:500}
.tag{font:600 .75rem ui-monospace,Consolas,monospace;background:var(--fundo);border:1px solid var(--borda);border-radius:4px;padding:1px 6px}
.st{font-size:.75rem;color:var(--suave)}.st-editado{color:var(--b)}
.texto{margin:4px 0 8px;font-size:1.02rem}
a.num{color:var(--destaque);text-decoration:underline dotted;text-underline-offset:2px}
details{margin:4px 0}summary{cursor:pointer;color:var(--destaque);font-size:.9rem}
.evid ul{margin:6px 0;padding-left:20px}.evid li{margin:6px 0}.evid q{quotes:"“" "”"}
.evid:target,.evid-vazia:target{background:var(--marca)}
mark{background:var(--marca);color:inherit;padding:0 2px;border-radius:2px}
.cit{color:var(--suave);font-size:.85rem;white-space:normal}
dl.met,.met dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:6px 0;font-size:.85rem}.met dd{margin:0}
.meta{margin:6px 0 0;color:var(--suave);font-size:.8rem}.nota{margin:4px 0;font-size:.9rem}
.metodo dl{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;margin:0}.metodo dt{color:var(--suave)}.metodo dd{margin:0}.metodo ul{margin:0;padding-left:18px}
ol.refs li{margin:4px 0;font-size:.9rem}
.grafico{width:100%;height:auto;max-width:640px;display:block;margin:6px 0}
.grafico .rot,.grafico .val{font-size:11px;fill:currentColor}.grafico .barra-a{fill:var(--a)}.grafico .barra-b{fill:var(--b)}.grafico .eixo{stroke:var(--suave);stroke-width:1}
pre.codigo{background:var(--fundo);border:1px solid var(--borda);border-radius:6px;padding:10px;overflow:auto;max-height:360px;font:.8rem/1.45 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
footer{max-width:1000px;margin:0 auto;padding:8px 16px 40px;color:var(--suave);font-size:.85rem}
.busca{padding:4px 8px;border:1px solid var(--borda);border-radius:5px;background:var(--fundo);color:var(--texto);font:inherit;font-size:.85rem;width:12rem;max-width:100%}
@media (max-width:600px){body{font-size:15px}dl.ident,.metodo dl{grid-template-columns:1fr}dl.ident dt,.metodo dt{margin-top:6px}section{padding:12px}}
@media print{body{background:#fff;color:#000;font-size:11pt}nav.sumario,.busca,button{display:none}section{border:0;padding:0;break-inside:auto}.cm{break-inside:avoid}.tab{overflow:visible}a.num{text-decoration:none;color:inherit}:root{--fundo:#fff;--painel:#fff;--texto:#000;--suave:#444;--borda:#bbb;--marca:#eee}}
"""

JS = """
(function () {
  var raiz = document.documentElement;
  function lerTema() { try { return localStorage.getItem('raiox-laudo-tema'); } catch (e) { return null; } }
  function gravarTema(t) { try { localStorage.setItem('raiox-laudo-tema', t); } catch (e) { /* sem armazenamento: segue sem lembrar */ } }
  var tema = lerTema(); if (tema) raiz.setAttribute('data-tema', tema);
  var btnTema = document.getElementById('btn-tema');
  if (btnTema) btnTema.addEventListener('click', function () {
    var atual = raiz.getAttribute('data-tema') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'escuro' : 'claro');
    var novo = atual === 'escuro' ? 'claro' : 'escuro'; raiz.setAttribute('data-tema', novo); gravarTema(novo);
  });
  function abrirAlvo() {
    var el = location.hash ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : null;
    if (el && el.tagName === 'DETAILS') el.open = true;
  }
  window.addEventListener('hashchange', abrirAlvo); abrirAlvo();
  var btnTodas = document.getElementById('btn-evid');
  if (btnTodas) btnTodas.addEventListener('click', function () {
    var ds = document.querySelectorAll('details.evid'); var abrir = btnTodas.dataset.estado !== 'aberto';
    ds.forEach(function (d) { d.open = abrir; }); btnTodas.dataset.estado = abrir ? 'aberto' : ''; btnTodas.textContent = abrir ? 'Recolher evidências' : 'Expandir evidências';
  });
  var busca = document.getElementById('busca');
  if (busca) busca.addEventListener('input', function () {
    var q = busca.value.trim().toLowerCase();
    document.querySelectorAll('article.cm').forEach(function (a) { a.hidden = q && a.textContent.toLowerCase().indexOf(q) < 0; });
  });
  window.addEventListener('beforeprint', function () { document.querySelectorAll('details').forEach(function (d) { d.open = true; }); });
  document.querySelectorAll('table.ordenavel').forEach(function (t) {
    t.querySelectorAll('th').forEach(function (th, i) {
      th.addEventListener('click', function () {
        var corpo = t.tBodies[0]; var linhas = Array.prototype.slice.call(corpo.rows);
        var asc = th.dataset.asc !== '1'; th.dataset.asc = asc ? '1' : '0';
        function valor(l) { var x = l.cells[i].textContent.trim(); var n = parseFloat(x.replace(/\\./g, '').replace(',', '.')); return isNaN(n) ? x.toLowerCase() : n; }
        linhas.sort(function (a, b) { var va = valor(a), vb = valor(b); return (va < vb ? -1 : va > vb ? 1 : 0) * (asc ? 1 : -1); });
        linhas.forEach(function (l) { corpo.appendChild(l); });
      });
    });
  });
})();
"""


def _declaracao_llm_texto(d: dict) -> str:
    if d.get("llm_usados"):
        return (f"Comentários produzidos por regras e, quando indicado, redigidos com auxílio de LLM ({'; '.join(d['llm_usados'])}), "
                "revisados por humano.")
    return "Gerado sem LLM; comentários produzidos por regras e revisados por humano."


def _declaracao_llm(d: dict) -> str:
    return esc(_declaracao_llm_texto(d))


def renderizar(d: dict) -> str:
    por_analise: dict[str, list[Comentario]] = {}
    for c in d["aceitos"]:
        por_analise.setdefault(c.analise_tipo if c.analise_tipo in ANALISES else "outros", []).append(c)
    usadas = _analises_usadas(d, por_analise)
    nome = d["projeto"].nome if d["projeto"] else "projeto"
    n_ac = len(d["aceitos"])
    nav = ('<a href="#identificacao">Identificação</a><a href="#corpus">Corpus</a><a href="#metodos">Métodos</a>'
           '<a href="#resultados">Resultados</a><a href="#notas">Notas</a><a href="#parametros">Parâmetros</a>')
    corpo = (_aviso_checagem(d) + _aviso_pendentes(d) + _identificacao(d) + _corpus(d) + _metodos(d, usadas) + _resultados(d, usadas, por_analise)
             + _notas(d) + _parametros(d))
    return (f'<!doctype html>\n<html lang="pt-BR"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Laudo Raio-X — {esc(nome)}</title><style>{CSS}</style></head><body>'
            f'<header class="topo"><h1>Laudo Raio-X — {esc(nome)}</h1>'
            f'<p class="sub">{n_ac} comentário{"s" if n_ac != 1 else ""} revisado{"s" if n_ac != 1 else ""} por humano · '
            f'gerado em {esc(_data(d["gerado_em"]))}</p></header>'
            f'<nav class="sumario">{nav}<span class="esp"></span>'
            f'<input id="busca" class="busca" type="search" placeholder="Buscar nos comentários" aria-label="Buscar nos comentários">'
            f'<button id="btn-evid" type="button">Expandir evidências</button>'
            f'<button id="btn-tema" type="button" title="Alternar claro/escuro">Tema</button></nav>'
            f'<main>{corpo}</main>'
            f'<footer>{_declaracao_llm(d)} '
            f'Raio-X {esc(VERSAO)} · parâmetros v{esc(d["params"].get("versao_parametros"))} · sha256 {esc(d["hash"][:12])}…</footer>'
            f'<script>{JS}</script></body></html>\n')


def gerar_laudo(db: Session, pasta: Path) -> dict:
    """Gera ``saidas/laudo.html`` e devolve um resumo (caminho, tamanho, contagens)."""
    d = coletar(db, pasta)
    texto = renderizar(d)
    saidas = pasta / "saidas"
    saidas.mkdir(parents=True, exist_ok=True)
    destino = saidas / "laudo.html"
    destino.write_text(texto, encoding="utf-8")
    from app.services.exportar import laudo_docx  # 9.3: o .docx sai do mesmo estado e da mesma checagem
    tamanho_docx = laudo_docx.escrever(d, saidas / "laudo.docx")
    return {"arquivo": "saidas/laudo.html", "arquivo_docx": "saidas/laudo.docx", "tamanho_docx_bytes": tamanho_docx,
            "tamanho_bytes": len(texto.encode("utf-8")), "gerado_em": d["gerado_em"].isoformat(timespec="seconds"),
            "aceitos": len(d["aceitos"]), "pendentes": d["pendentes"], "contagem": dict(d["contagem"]),
            "hash_parametros": d["hash"], "checagem": d["checagem"]}
