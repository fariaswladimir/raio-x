"""9.2 - Exportação CSV (documentos, frequências, keyness, colocações, comentários, evidências).

Convenções (todas as planilhas):
- UTF-8 **com BOM** (o Excel abre com acentos corretos), separador ``;``, fim de linha CRLF;
- decimais com **ponto** (``0.0123``), sem separador de milhar: os números continuam números em qualquer
  configuração regional e não dependem de a vírgula decimal do Excel pt-BR (os CSV de ``/analises/*.csv`` usam vírgula,
  pensados para abrir direto no Excel pt-BR; estes são para análise e arquivamento);
- campos com ``;``, aspas ou quebras de linha entram entre aspas (aspas duplicadas), como manda o RFC 4180;
- datas em ISO 8601 (UTC); valores ausentes = campo vazio.

Reusa as funções das análises (``resumo``, ``frequencias``, ``keyness``, ``colocacoes``): nada é recalculado de outro jeito.
"""
import csv
import io
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Comentario, Documento
from app.services.analises import dados, frequencias, keyness, resumo
from app.services.exportar import comum
from app.services.texto import ler_qualidade

NOMES = ("documentos", "frequencias", "keyness", "colocacoes", "comentarios", "evidencias")
SEPARADOR = ";"


def _n(x):
    """Número para CSV: ponto decimal, até 10 algarismos significativos; ``None`` -> vazio."""
    if x is None:
        return ""
    if isinstance(x, bool):
        return "sim" if x else "não"
    if isinstance(x, float):
        return f"{x:.10g}"
    return x


def _data(d):
    return d.isoformat(timespec="seconds") if d else ""


def _seguro(v):
    """Neutraliza injeção de fórmula no Excel: texto que começa com = + - @ ganha um apóstrofo.

    Números (inclusive negativos, como G² de repulsão) passam intactos.
    """
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        try:
            float(v.replace(",", "."))
            return v
        except ValueError:
            return "'" + v
    return v


def csv_bytes(cabecalho: list[str], linhas) -> bytes:
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=SEPARADOR, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(cabecalho)
    w.writerows([_seguro(v) for v in linha] for linha in linhas)
    return ("﻿" + saida.getvalue()).encode("utf-8")


# ---------- documentos ----------

def _documentos(db: Session, pasta: Path):
    ctx = comum.contexto(db, pasta)
    res = resumo.resumo_do_projeto(pasta, ctx["metas"], ctx["params"]) or {"documentos": []}
    por_id = {d["documento_id"]: d for d in res["documentos"]}
    cab = ["id", "arquivo", "rotulo", "id_estudo", "autor", "ano", "grupo", "qp", "status", "paginas", "idioma", "caracteres",
           "problemas", "avisos", "palavras_corpo", "palavras_total", "tipos_lema", "tipos_forma", "densidade", "mattr",
           "mattr_ttr_simples", "pct_corpo", "hash_sha256", "convertido_em"]
    linhas = []
    for d in db.scalars(select(Documento).order_by(Documento.arquivo)):
        q = ler_qualidade(d)
        r = por_id.get(d.id) or {}
        linhas.append([
            d.id, d.arquivo, dados.rotulo_do_documento(d), d.id_estudo or "", d.autor or "", d.ano or "", d.grupo or "", d.qp or "",
            d.status, _n(q.get("paginas")), q.get("idioma") or "", _n(q.get("caracteres")),
            " | ".join(q.get("problemas") or []), " | ".join(q.get("avisos") or []),
            _n(r.get("tokens")), _n(r.get("tokens_total")), _n(r.get("tipos_lema")), _n(r.get("tipos_forma")),
            _n(r.get("densidade")), _n(r.get("mattr")), _n(r.get("mattr_ttr")) if r else "", _n(r.get("pct_corpo")),
            d.hash_sha256 or "", _data(d.convertido_em)])
    return cab, linhas


# ---------- frequências ----------

def _frequencias(db: Session, pasta: Path):
    ctx = comum.contexto(db, pasta)
    r = frequencias.listar(ctx["voc"], ctx["metas"], ctx["filtro"], por="lema", filtrar=True, limite=10 ** 9)
    cab = ["posicao", "lema", "frequencia", "por_10_mil", "documentos"]
    return cab, ([i + 1, t["termo"], t["freq"], _n(t["por_10k"]), t["docs"]] for i, t in enumerate(r["itens"]))


# ---------- keyness ----------

def _keyness(db: Session, pasta: Path):
    ctx = comum.contexto(db, pasta)
    cab = ["grupo_a", "contra", "lado", "posicao", "lema", "freq_a", "freq_b", "por_10k_a", "por_10k_b", "g2", "p",
           "p_bonferroni", "log_ratio", "pct_diff", "docs_a", "docs_b"]
    res = keyness.comparar_grupos(ctx["voc"], ctx["metas"], ctx["filtro"], limite=10 ** 9)
    linhas = []
    for comp in (res or {}).get("comparacoes", []):
        ga, contra = comp["lado_a"]["valor"], comp["lado_b"]["valor"]
        for lado, itens in (("A sobre-representado", comp["positivas"]), ("B sobre-representado", comp["negativas"])):
            for i, k in enumerate(itens):
                linhas.append([ga, contra, lado, i + 1, k["termo"], k["a"], k["b"], _n(k["por_10k_a"]), _n(k["por_10k_b"]),
                               _n(k["g2"]), _n(k["p"]), _n(k["p_bonferroni"]), _n(k["log_ratio"]), _n(k["pct_diff"]),
                               k["docs_a"], k["docs_b"]])
    return cab, linhas


# ---------- colocações ----------

def _colocacoes(db: Session, pasta: Path):
    ctx = comum.contexto(db, pasta)
    aceitos = list(db.scalars(select(Comentario).where(Comentario.status.in_(comum.STATUS_NO_LAUDO)).order_by(Comentario.id)))
    termos = comum.termos_dos_comentarios(aceitos)
    if not termos:  # sem comentários aceitos com termo: os 10 termos mais frequentes
        top = frequencias.listar(ctx["voc"], ctx["metas"], ctx["filtro"], por="lema", filtrar=True, limite=10)
        termos = [t["termo"] for t in top["itens"]]
    cab = ["no", "posicao", "colocado", "o11", "c1", "e11", "ll", "p", "mi", "t", "logdice", "pares"]
    linhas = []
    for termo, r in comum.colocados_dos_termos(pasta, ctx, termos, limite=50):
        for i, c in enumerate(r["colocados"]):
            linhas.append([termo, i + 1, c["termo"], c["o11"], c["c1"], _n(c["e11"]), _n(c["ll"]), _n(c["p"]), _n(c["mi"]),
                           _n(c["t"]), _n(c["logdice"]), c["pares"]])
    return cab, linhas


# ---------- comentários e evidências ----------

def _comentarios(db: Session, pasta: Path):
    lista = list(db.scalars(select(Comentario).order_by(Comentario.analise_tipo, Comentario.forca.desc(), Comentario.id)))
    metricas = []
    for c in lista:
        try:
            m = json.loads(c.metricas_json) if c.metricas_json else {}
        except ValueError:
            m = {}
        metricas.append({k: v for k, v in m.items() if v is None or isinstance(v, (int, float, str, bool))})
    colunas: list[str] = []
    for m in metricas:
        colunas.extend(k for k in m if k not in colunas)
    cab = ["id", "chave", "regra", "analise", "status", "texto", "texto_original", "forca", "revisor", "nota", "criado_em",
           "atualizado_em", "n_evidencias", *[f"m_{k}" for k in colunas]]
    linhas = [[c.id, c.chave or "", c.regra, c.analise_tipo or "", c.status, c.texto, c.texto_original or "", _n(c.forca),
               c.revisor or "", c.nota or "", _data(c.criado_em), _data(c.atualizado_em), len(c.evidencias),
               *[_n(m.get(k)) for k in colunas]] for c, m in zip(lista, metricas)]
    return cab, linhas


def _evidencias(db: Session, pasta: Path):
    cab = ["comentario_id", "comentario_chave", "regra", "status", "documento_id", "documento", "arquivo", "pagina", "trecho", "termo"]
    linhas = []
    for c in db.scalars(select(Comentario).order_by(Comentario.id)):
        for e in sorted(c.evidencias, key=lambda e: e.id):
            linhas.append([c.id, c.chave or "", c.regra, c.status, e.documento_id, dados.rotulo_do_documento(e.documento),
                           e.documento.arquivo, _n(e.pagina), e.trecho, (e.termo or "").replace("|", ", ")])
    return cab, linhas


_GERADORES = {"documentos": _documentos, "frequencias": _frequencias, "keyness": _keyness, "colocacoes": _colocacoes,
              "comentarios": _comentarios, "evidencias": _evidencias}


def gerar(nome: str, db: Session, pasta: Path) -> bytes:
    """CSV (bytes, UTF-8 com BOM) da planilha ``nome`` (ver ``NOMES``). Levanta ``KeyError`` se o nome não existe e ``SemDados``."""
    cab, linhas = _GERADORES[nome](db, pasta)
    return csv_bytes(cab, linhas)
