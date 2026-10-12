"""9.3 - Laudo DOCX (python-docx): o mesmo conteúdo do laudo HTML, com estilos nativos do Word.

Seções: 1. Identificação, 2. Corpus, 3. Métodos (com referências ABNT do catálogo único), 4. Resultados (só comentários
``aceito``/``editado`` com as evidências "(rótulo, p. N)" e as tabelas dos números principais), 5. Notas do revisor,
6. Parâmetros. Títulos usam os estilos ``Title`` e ``Heading 1-3`` (navegação e sumário do Word), tabelas usam
``Table Grid`` com cabeçalho em negrito e listas usam ``List Bullet``/``List Number``.

Reaproveita a coleta do laudo HTML (``laudo_html.coletar``): o laudo DOCX e o HTML saem do mesmo estado e da mesma
checagem de evidência (8.3). Gráficos não são embutidos (as tabelas trazem os mesmos números; o HTML tem as barras).
"""
import json
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.config import VERSAO
from app.models import Comentario
from app.services.analises import dados, frequencias
from app.services.exportar import comum
from app.services.exportar.laudo_html import (MAX_TERMOS_COLOCACAO, MAX_TERMOS_TENDENCIA, TITULOS_RESULTADO, TOP_COLOCADOS,
                                              TOP_FREQUENCIAS, TOP_KEYNESS, _data, _declaracao_llm_texto, fmt)
from app.services.exportar.metodos import METODOS, ORDEM, ROTULO_METRICA, parametros_do_metodo, referencias
from app.services.metodologia import formatos as formatos_ref
from app.services.regras.catalogo import ANALISES, hash_catalogo
from app.services.texto import ler_qualidade


def _txt(v) -> str:
    return "—" if v is None or v == "" else str(v)


def _nova_tabela(doc, cabecalho: list[str], linhas: list[list], largura_num_de: int = 99):
    tab = doc.add_table(rows=1, cols=len(cabecalho))
    tab.style = "Table Grid"
    for i, titulo in enumerate(cabecalho):
        celula = tab.rows[0].cells[i]
        celula.text = ""
        r = celula.paragraphs[0].add_run(titulo)
        r.bold = True
    for linha in linhas:
        cels = tab.add_row().cells
        for i, v in enumerate(linha):
            cels[i].text = _txt(v)
            if i >= largura_num_de:
                cels[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in (r for c in tab.rows[0].cells for p in c.paragraphs for r in p.runs):
        run.font.size = Pt(9.5)
    for row in tab.rows[1:]:
        for c in row.cells:
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9.5)
    doc.add_paragraph()
    return tab


def _par_discreto(doc, texto: str):
    p = doc.add_paragraph()
    r = p.add_run(texto)
    r.italic = True
    r.font.size = Pt(9.5)
    r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    return p


def _ev_texto(e) -> str:
    rotulo = dados.rotulo_do_documento(e.documento)
    pag = f"p. {e.pagina}" if e.pagina is not None else "p. n/d"
    return f"“{e.trecho}” ({rotulo}, {pag})"


def _comentario(doc, c: Comentario):
    _par_discreto(doc, f"{c.regra} · {c.status}" + (" · redigido com LLM" if c.origem == "llm" else ""))
    doc.add_paragraph(c.texto)
    if c.nota:
        p = doc.add_paragraph()
        p.add_run("Nota do revisor: ").bold = True
        p.add_run(c.nota)
    evid = sorted(c.evidencias, key=lambda e: e.id)
    if evid:
        p = doc.add_paragraph()
        p.add_run(f"Evidências ({len(evid)}):").bold = True
        for e in evid:
            doc.add_paragraph(_ev_texto(e), style="List Bullet")
    else:
        _par_discreto(doc, "Sem trechos de evidência: o comentário se apoia só nas métricas.")
    m = {k: v for k, v in dados_json(c).items() if v is None or isinstance(v, (int, float, str))}
    if m:
        metr = "; ".join(f"{ROTULO_METRICA.get(k, k)}: {fmt(v, 3 if isinstance(v, float) and abs(v) < 10 else 1)}" for k, v in m.items())
        _par_discreto(doc, "Métricas: " + metr)
    quem = ("Editado" if c.status == "editado" else "Aceito") + (f" por {c.revisor}" if c.revisor else "") + f" em {_data(c.atualizado_em)}"
    if c.status == "editado" and c.texto_original and c.texto_original != c.texto:
        _par_discreto(doc, "Texto gerado pela regra (antes da edição): " + c.texto_original)
    _par_discreto(doc, quem)


def dados_json(c: Comentario) -> dict:
    try:
        v = json.loads(c.metricas_json) if c.metricas_json else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


# ---------- seções ----------

def _identificacao(doc, d: dict):
    p = d["projeto"]
    doc.add_heading("1. Identificação", level=1)
    linhas = [["Projeto", p.nome if p else "—"], ["Pasta de origem", p.pasta_origem if p else "—"],
              ["Gerado em", _data(d["gerado_em"])], ["Versão do Raio-X", VERSAO],
              ["Versão dos parâmetros", d["params"].get("versao_parametros")],
              ["Hash dos parâmetros (sha256)", d["hash"]], ["Catálogo de regras (hash)", hash_catalogo()[:16]]]
    _nova_tabela(doc, ["Item", "Valor"], linhas)


def _corpus(doc, d: dict):
    res = d["resumo"] or {"corpus": {}, "documentos": []}
    c = res["corpus"]
    por_id = {x["documento_id"]: x for x in res["documentos"]}
    anos = [m["ano"] for m in d["ctx"]["metas"] if m.get("ano")]
    periodo = f"{min(anos)}–{max(anos)}" if anos else "sem ano informado"
    grupos = ", ".join(f"{g['grupo']} ({g['documentos']})" for g in c.get("documentos_por_grupo", [])) or "—"
    doc.add_heading("2. Corpus", level=1)
    _nova_tabela(doc, ["Medida", "Valor"], [["Documentos analisados", fmt(c.get("n_documentos"))],
                                            ["Palavras (corpo do texto)", fmt(c.get("tokens"))], ["Período", periodo],
                                            ["Grupos", grupos]])
    linhas, excluidos = [], []
    for dc in d["documentos"]:
        q = ler_qualidade(dc)
        meta = dados.meta_do_documento(dc)
        r = por_id.get(dc.id)
        linhas.append([meta["rotulo"], dc.ano or "—", dc.grupo or "—", q.get("paginas") if q.get("paginas") is not None else "—",
                       fmt(r["tokens"]) if r else "—", q.get("idioma") or "—", dc.status])
        if dc.status in ("com_problema", "removido") or dc.excluido:
            motivo = " | ".join(q.get("problemas") or []) or ("removido da pasta de origem" if dc.status == "removido" else (
                "excluído da análise pelo usuário" if dc.excluido else "sem motivo registrado"))
            excluidos.append([meta["rotulo"], dc.arquivo, "excluido" if dc.excluido else dc.status, motivo])
    doc.add_heading(f"Documentos ({len(linhas)})", level=2)
    _nova_tabela(doc, ["Documento", "Ano", "Grupo", "Páginas", "Palavras", "Idioma", "Situação"], linhas, 4)
    if excluidos:
        doc.add_heading(f"Documentos fora das análises ({len(excluidos)})", level=2)
        _nova_tabela(doc, ["Documento", "Arquivo", "Situação", "Motivo"], excluidos)


def _analises_usadas(d: dict, por_analise: dict[str, list[Comentario]]) -> list[str]:
    usadas = {a for a, lista in por_analise.items() if lista and a in METODOS}
    if d["resumo"]:
        usadas.update({"resumo", "frequencias"})
    if d["snap_keyness"]:
        usadas.add("keyness")
    if any(c.evidencias for c in d["aceitos"]):
        usadas.add("kwic")
    return [a for a in ORDEM if a in usadas]


def _metodos(doc, d: dict, usadas: list[str]):
    doc.add_heading("3. Métodos", level=1)
    _par_discreto(doc, "Cada número do laudo vem destas análises; os parâmetros são os do projeto (seção 6).")
    refs_usadas: list[str] = []
    for a in usadas:
        m = METODOS[a]
        doc.add_heading(m["titulo"], level=2)
        for rot, chave in (("O que mede", "mede"), ("Métrica", "metrica")):
            p = doc.add_paragraph()
            p.add_run(rot + ": ").bold = True
            p.add_run(m[chave])
        p = doc.add_paragraph()
        p.add_run("Parâmetros:").bold = True
        for par in parametros_do_metodo(a, d["params"], d["snap_keyness"]):
            doc.add_paragraph(par, style="List Bullet")
        for rot, chave in (("Equivale a", "equivale"), ("Não é igual a", "nao_igual")):
            p = doc.add_paragraph()
            p.add_run(rot + ": ").bold = True
            p.add_run(m[chave])
        cit = "; ".join(f"{formatos_ref.sobrenome_primeiro_autor(r)} ({r['ano']})" for r in referencias(m["refs"]))
        p = doc.add_paragraph()
        p.add_run("Referências: ").bold = True
        p.add_run(cit)
        refs_usadas.extend(k for k in m["refs"] if k not in refs_usadas)
    if d.get("llm_usados"):
        doc.add_heading("Redação assistida por LLM", level=2)
        doc.add_paragraph(
            f"Parte dos comentários foi redigida com auxílio de modelo de linguagem ({'; '.join(d['llm_usados'])}). O modelo recebeu apenas "
            "as métricas calculadas pelo Raio-X, o parágrafo-modelo e até cinco trechos do corpus, com instrução de não acrescentar números, "
            "fontes nem afirmações causais. Cada texto passou por conferência automática (números contra as métricas fornecidas, citações "
            "\"(rótulo, p. N)\" e trechos entre aspas contra as evidências) e por revisão humana: só entram neste laudo os comentários aceitos "
            "ou editados por um revisor, e os redigidos com LLM aparecem marcados.")
    doc.add_heading("Referências", level=2)
    for r in (referencias(refs_usadas) if refs_usadas else []):
        doc.add_paragraph(formatos_ref.formatar(r, "abnt"), style="List Number")
    _par_discreto(doc, "Conferir DOI, páginas e edição antes de citar em um artigo.")


def _tabelas(doc, d: dict, chave: str, lista: list[Comentario]):
    ctx = d["ctx"]
    if chave == "resumo":
        c = (d["resumo"] or {}).get("corpus") or {}
        if not c:
            return
        _nova_tabela(doc, ["Medida", "Valor"], [
            ["Documentos", fmt(c["n_documentos"])], ["Palavras no corpo (sem referências)", fmt(c["tokens"])],
            ["Palavras no total", fmt(c["tokens_total"])], ["Tipos (lemas)", fmt(c["tipos_lema"])],
            ["Densidade vocabular (lemas/palavras)", fmt(c["densidade_lema"], 4)],
            [f"MATTR médio (janela {c['mattr_janela']}; {c['mattr_documentos_comparaveis']} docs comparáveis)", fmt(c["mattr_media"], 3)],
            ["Mediana de palavras por documento", fmt(c["mediana_tokens"], 0)]], 1)
        doc.add_heading("Documentos por grupo", level=4)
        _nova_tabela(doc, ["Grupo", "Documentos"], [[g["grupo"], fmt(g["documentos"])] for g in c["documentos_por_grupo"]], 1)
    elif chave == "frequencias":
        r = frequencias.listar(ctx["voc"], ctx["metas"], ctx["filtro"], por="lema", filtrar=True, limite=TOP_FREQUENCIAS)
        doc.add_heading(f"Os {TOP_FREQUENCIAS} lemas mais frequentes ({fmt(r['documentos'])} documentos, {fmt(r['tokens'])} palavras)", level=4)
        _nova_tabela(doc, ["#", "Lema", "Frequência", "Por 10 mil", "Documentos"],
                     [[i + 1, t["termo"], fmt(t["freq"]), fmt(t["por_10k"]), fmt(t["docs"])] for i, t in enumerate(r["itens"])], 2)
    elif chave == "tendencias":
        termos = comum.termos_dos_comentarios(lista)[:MAX_TERMOS_TENDENCIA]
        if termos:
            r = frequencias.distribuicao(ctx["voc"], ctx["metas"], termos, por="lema", agrupar="ano", metrica="rel")
            doc.add_heading("Frequência por 10 mil palavras, por ano (termos comentados)", level=4)
            _nova_tabela(doc, ["Lema", *[c["rotulo"] for c in r["categorias"]]],
                         [[s["termo"], *[fmt(v) for v in s["rel"]]] for s in r["series"]], 1)
    elif chave == "keyness":
        snap = d["snap_keyness"]
        if not snap:
            return
        _par_discreto(doc, f"Cada grupo contra os demais documentos; instantâneo de {_data(d['snap_keyness_em'])}. "
                           f"Mostra as {TOP_KEYNESS} palavras-chave de maior G² de cada lado (A = o grupo; B = os demais).")
        for comp in snap["comparacoes"]:
            a, b = comp["lado_a"], comp["lado_b"]
            doc.add_heading(f"{a['valor']} ({fmt(a['documentos'])} docs, {fmt(a['tokens'])} palavras) contra {b['valor']} "
                            f"({fmt(b['documentos'])} docs, {fmt(b['tokens'])} palavras)", level=4)
            for rot, itens in ((f"sobre-representadas em {a['valor']}", comp["positivas"][:TOP_KEYNESS]),
                               (f"sub-representadas em {a['valor']}", comp["negativas"][:TOP_KEYNESS])):
                if itens:
                    doc.add_paragraph().add_run(rot).bold = True
                    _nova_tabela(doc, ["Lema", "Freq. A", "Freq. B", "G²", "p", "Log Ratio", "Docs A / B"],
                                 [[k["termo"], fmt(k["a"]), fmt(k["b"]), fmt(k["g2"], 1), fmt(k["p"]), fmt(k["log_ratio"]),
                                   f"{fmt(k['docs_a'])} / {fmt(k['docs_b'])}"] for k in itens], 1)
    elif chave == "colocacoes":
        termos = comum.termos_dos_comentarios(lista, ("colocacoes",))[:MAX_TERMOS_COLOCACAO]
        if termos:
            _par_discreto(doc, "Colocados dos termos comentados (janela e filtros do projeto, ordenados por log-likelihood).")
            for termo, r in comum.colocados_dos_termos(d["pasta"], ctx, termos, limite=TOP_COLOCADOS):
                doc.add_heading(f"Colocados de ‘{termo}’", level=4)
                linhas = [[c["termo"], fmt(c["o11"]), fmt(c["ll"], 1), fmt(c["mi"]), fmt(c["p"])] for c in r["colocados"]]
                if linhas:
                    _nova_tabela(doc, ["Colocado", "Coocorrências", "LL", "MI", "p"], linhas, 1)
                else:
                    _par_discreto(doc, "Nenhum colocado acima dos limites mínimos.")


def _resultados(doc, d: dict, por_analise: dict[str, list[Comentario]]):
    doc.add_heading("4. Resultados", level=1)
    if not d["aceitos"]:
        _par_discreto(doc, "Nenhum comentário foi aceito ainda: abaixo só aparecem as métricas do corpus.")
    for chave in (*ANALISES, "outros"):
        lista = por_analise.get(chave, [])
        tem_tabela = (chave in ("resumo", "frequencias") and bool(d["resumo"])) or (chave == "keyness" and bool(d["snap_keyness"]))
        if not lista and not tem_tabela:
            continue
        doc.add_heading(TITULOS_RESULTADO[chave], level=2)
        for c in lista:
            _comentario(doc, c)
        if not lista:
            _par_discreto(doc, "Nenhum comentário aceito para esta análise.")
        _tabelas(doc, d, chave, lista)


def _notas(doc, d: dict):
    doc.add_heading("5. Notas do revisor", level=1)
    com_nota = [c for c in d["aceitos"] if c.nota]
    revisores = sorted({c.revisor for c in d["aceitos"] if c.revisor})
    doc.add_paragraph("Revisores: " + (", ".join(revisores) or "não informado") + ".")
    if com_nota:
        _nova_tabela(doc, ["Comentário", "Nota", "Revisor", "Data"],
                     [[c.regra, c.nota, c.revisor or "—", _data(c.atualizado_em)] for c in com_nota])
    else:
        _par_discreto(doc, "Nenhuma anotação do revisor nos comentários incluídos.")


def _parametros(doc, d: dict):
    doc.add_heading("6. Parâmetros e registro de execução", level=1)
    doc.add_paragraph(f"Versão {d['params'].get('versao_parametros')}; sha256 do conteúdo: {d['hash']}.")
    doc.add_heading("parametros.json", level=2)
    for linha in json.dumps(d["params"], ensure_ascii=False, indent=2).splitlines():
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(linha)
        r.font.name = "Consolas"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
        r.font.size = Pt(8)
    doc.add_paragraph()
    doc.add_heading("Última execução de cada etapa", level=2)
    log = [[e.etapa, e.status, _data(e.iniciado_em), _data(e.finalizado_em), (e.mensagem or "")[:160]]
           for e in sorted(d["execucoes"], key=lambda e: e.iniciado_em)]
    if log:
        _nova_tabela(doc, ["Etapa", "Status", "Início", "Fim", "Mensagem"], log)
    else:
        _par_discreto(doc, "Sem execuções registradas.")


def _avisos(doc, d: dict):
    falhas = d["checagem"]["falhas"]
    if falhas:
        p = doc.add_paragraph()
        p.add_run(f"{len(falhas)} comentário(s) reprovado(s) na checagem de evidência — não entraram no laudo e voltaram para revisão.").bold = True
        for f in falhas:
            doc.add_paragraph(f"#{f['id']} ({f['regra']}): " + "; ".join(f["motivos"]), style="List Bullet")
    n, c = d["pendentes"], d["contagem"]
    extras = [t for t in (f"{c['rejeitado']} rejeitado(s)" if c["rejeitado"] else "", f"{c['obsoleto']} obsoleto(s)" if c["obsoleto"] else "") if t]
    resto = f" Também ficam de fora: {', '.join(extras)}." if extras else ""
    if n:
        p = doc.add_paragraph()
        p.add_run(f"{n} comentário(s) aguarda(m) revisão — não entraram no laudo.").bold = True
        p.add_run(f" ({c['sugerido']} sugerido(s), {c['revisar']} a revisar).{resto}")
    else:
        _par_discreto(doc, "Nenhum comentário aguarda revisão." + resto)


def montar(d: dict) -> Document:
    """Documento Word a partir da coleta do laudo (``laudo_html.coletar``)."""
    doc = Document()
    nome = d["projeto"].nome if d["projeto"] else "projeto"
    doc.core_properties.title = f"Laudo Raio-X — {nome}"
    doc.core_properties.author = "Raio-X"
    doc.core_properties.language = "pt-BR"
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(f"Laudo Raio-X — {nome}", level=0)
    n_ac = len(d["aceitos"])
    _par_discreto(doc, f"{n_ac} comentário{'s' if n_ac != 1 else ''} revisado{'s' if n_ac != 1 else ''} por humano · gerado em {_data(d['gerado_em'])}")
    por_analise: dict[str, list[Comentario]] = defaultdict(list)
    for c in d["aceitos"]:
        por_analise[c.analise_tipo if c.analise_tipo in ANALISES else "outros"].append(c)
    _avisos(doc, d)
    _identificacao(doc, d)
    _corpus(doc, d)
    _metodos(doc, d, _analises_usadas(d, por_analise))
    _resultados(doc, d, por_analise)
    _notas(doc, d)
    _parametros(doc, d)
    rodape = doc.sections[0].footer.paragraphs[0]
    rodape.text = (f"{_declaracao_llm_texto(d)} Raio-X {VERSAO} · parâmetros v{d['params'].get('versao_parametros')} · "
                   f"sha256 {d['hash'][:12]}…")
    for r in rodape.runs:
        r.font.size = Pt(8)
    return doc


def escrever(d: dict, destino: Path) -> int:
    """Grava o .docx em ``destino`` e devolve o tamanho em bytes."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    montar(d).save(str(destino))
    return destino.stat().st_size
