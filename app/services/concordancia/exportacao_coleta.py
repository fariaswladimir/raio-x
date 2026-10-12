"""9.5 - Exportação para a planilha de coleta da MLR: trechos do Raio-X no formato da aba ``T_Trechos_Tematicos``.

Produz um **novo** .xlsx (nunca altera a planilha do usuário, que só é lida, com ``read_only``): mesma ordem de colunas da aba de
trechos (o cabeçalho é copiado da planilha de referência, se indicada; senão vale ``COLUNAS_PADRAO``), uma linha por trecho
selecionado e a aba ``Resumo`` com contagens e o que foi marcado como duplicado.

Origens selecionáveis (cada item da seleção)
--------------------------------------------
- ``comentario``: evidências de comentários **aceitos/editados** (``comentario_id`` ou todos os aceitos);
- ``kwic``: ocorrências de uma consulta (``consulta``, ``por``, ``escopo``/``valor``; ``posicoes`` = lista de ``"documento:posição"``,
  ou até ``limite``); o trecho exportado é a **frase** que contém a ocorrência (texto do documento, sem edição);
- ``celula``: trechos de uma célula da planilha do corpus (16.1) (``documento_id`` + ``parte``);
- ``codificacao``: trechos codificados pelo LLM (15.1) (``ids`` ou todos os ``codificado``), com o código sugerido;
- ``trecho``: trecho livre (``documento_id``, ``texto``, ``pagina``, ``codigo``, ``tema``).

Preenchimento (por nome de coluna, sem acento e minúsculo; coluna desconhecida fica em branco)
-----------------------------------------------------------------------------------------------
``ID registro`` = ``RX-<ID fonte>-NN`` (prefixo próprio para não colidir com os da planilha); ``ID fonte`` = prefixo detectado na planilha
(``R``) + id do estudo com 3 dígitos; ``Fonte (autor, ano)`` = "autor (ano)" dos metadados; ``Página``; ``Seção``; ``Trecho original`` = o
trecho **literal**; ``Trecho traduzido`` = **vazio**; ``Código``/``Tema`` quando conhecidos (codificação LLM); ``Motivo da coleta`` =
"Raio-X: <análise>"; ``Sentença verificada (auto)`` = "verbatim (Raio-X)" se o trecho foi localizado no texto do documento, senão
"não localizado no texto"; ``Observação`` = "DUPLICADO: ..." quando o trecho já está na planilha. ``Trilha``, ``Rótulo do código``,
``QP``, ``Tipo de alegação``, ``Evidência``, ``Transferibilidade``, ``Decisão do revisor`` e ``Conferido por`` ficam em branco: são julgamento do revisor.

Duplicatas
----------
Comparação por **texto normalizado** (sem acento, minúsculas, só letras e dígitos): igual, ou mesmo início de 60 caracteres normalizados
(cobre cortes e reticências no fim). O trecho duplicado vem **marcado** (linha amarela, ``Observação`` com o ID do registro existente);
com ``incluir_duplicados = false`` ele é omitido (e contado no Resumo). Duplicatas dentro da própria seleção são removidas.
"""
import io
import re
import unicodedata
from collections import Counter
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodificacaoTrecho, Comentario, Documento
from app.services.analises import dados, kwic, texto_documento
from app.services.concordancia.importacao import PlanilhaInvalida, _cabecalho
from app.services.corpus import llm_partes as L
from app.services.corpus import partes as P
from app.services.exportar.planilhas import _seguro

ABA_PADRAO = "T_Trechos_Tematicos"
COLUNAS_PADRAO = ["ID registro", "ID fonte", "Fonte (autor, ano)", "Trilha", "Página", "Seção", "Trecho original (sentença)",
                  "Trecho traduzido (PT-BR)", "Código", "Rótulo do código", "Tema", "Tema de ordem superior", "QP",
                  "Códigos secundários", "Motivo da coleta", "Tipo de alegação", "Evidência", "Transferibilidade",
                  "Sentença verificada (auto)", "Observação", "Decisão do revisor", "Conferido por / data"]
TAMANHO_PREFIXO = 60
MIN_CHARS = 20
MAX_ITENS = 5000
TIPOS = ("comentario", "kwic", "celula", "codificacao", "trecho")
AMARELO = PatternFill("solid", fgColor="FFF2CC")


# ---------- normalização e duplicatas ----------

def _sa(s) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch)).lower().strip()


def normalizar_trecho(texto: str) -> str:
    """Minúsculas, sem acento, só letras/dígitos separados por espaço simples (reticências e colchetes de página somem)."""
    t = re.sub(r"^\s*\[(?:pp?\.\s*[\d\-–, ]+)\]\s*", "", texto or "")
    return " ".join(re.findall(r"[a-z0-9]+", _sa(t)))


class IndiceExistentes:
    """Trechos já presentes na planilha do usuário (``norm`` -> ID registro), com busca exata e por prefixo de 60 caracteres."""

    def __init__(self):
        self.exatos: dict[str, str] = {}
        self.prefixos: dict[str, str] = {}
        self.total = 0

    def adicionar(self, texto: str, registro: str):
        n = normalizar_trecho(texto)
        if len(n) < MIN_CHARS:
            return
        self.total += 1
        self.exatos.setdefault(n, registro)
        if len(n) >= TAMANHO_PREFIXO:
            self.prefixos.setdefault(n[:TAMANHO_PREFIXO], registro)

    def achar(self, texto: str) -> str | None:
        n = normalizar_trecho(texto)
        if n in self.exatos:
            return self.exatos[n]
        if len(n) >= TAMANHO_PREFIXO:
            return self.prefixos.get(n[:TAMANHO_PREFIXO])
        return None


def ler_planilha_referencia(caminho: str | Path, aba: str | None = None) -> dict:
    """Lê (somente leitura) a aba de trechos da planilha do usuário: ``cabecalho``, ``indice`` (IndiceExistentes), ``aba``, ``prefixo_fonte``."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise PlanilhaInvalida(f"Planilha de referência não encontrada: {caminho}")
    try:
        wb = load_workbook(str(caminho), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise PlanilhaInvalida(f"Não foi possível ler o .xlsx: {type(e).__name__}: {e}")
    try:
        nomes = wb.sheetnames
        escolhida = aba if aba in nomes else (ABA_PADRAO if ABA_PADRAO in nomes else next((n for n in nomes if "trecho" in _sa(n)), None))
        if escolhida is None:
            raise PlanilhaInvalida(f"Aba de trechos não encontrada (abas: {', '.join(nomes)}).")
        linhas = list(wb[escolhida].iter_rows(values_only=True))
    finally:
        wb.close()
    i, mapa = _cabecalho(linhas)
    if i is None:
        raise PlanilhaInvalida(f"Cabeçalho com colunas de trecho e código não reconhecido na aba '{escolhida}'.")
    cab = ["" if h is None else str(h) for h in linhas[i]]
    while cab and not cab[-1]:
        cab.pop()
    indice = IndiceExistentes()
    prefixos = Counter()
    for k, linha in enumerate(linhas[i + 1:], i + 2):
        texto = linha[mapa["texto"]] if mapa["texto"] < len(linha) else None
        if not texto:
            continue
        reg = linha[mapa["registro"]] if "registro" in mapa and mapa["registro"] < len(linha) else None
        indice.adicionar(str(texto), str(reg) if reg else f"linha {k}")
        fonte = linha[mapa["fonte"]] if "fonte" in mapa and mapa["fonte"] < len(linha) else None
        m = re.match(r"^([A-Za-z]+)\d+$", str(fonte or "").strip())
        if m:
            prefixos[m.group(1)] += 1
    return {"cabecalho": cab, "indice": indice, "aba": escolhida, "prefixo_fonte": prefixos.most_common(1)[0][0] if prefixos else "R",
            "linhas": len(linhas) - i - 1}


# ---------- itens da seleção ----------

def _meta(db: Session, doc_id: int | None) -> dict:
    d = db.get(Documento, doc_id) if doc_id else None
    if d is None:
        return {"id": doc_id, "id_estudo": None, "autor": None, "ano": None, "rotulo": None}
    return {"id": d.id, "id_estudo": d.id_estudo, "autor": d.autor, "ano": d.ano, "rotulo": dados.rotulo_do_documento(d)}


def frase_do_token(pasta: Path, documento_id: int, posicao: int) -> dict | None:
    """Frase do documento que contém o token ``posicao`` (texto do bloco, espaços colapsados) com página e seção."""
    tk = dados.carregar_tokens(pasta, documento_id)
    blocos = dados.carregar_blocos(pasta, documento_id)
    if tk is None or blocos is None or not (0 <= posicao < tk["n"]):
        return None
    b, off = tk["bloco"][posicao], tk["inicio"][posicao]
    bloco = blocos[b]
    escolhida = None
    for o, f in texto_documento.dividir_frases(bloco["texto"]):
        if o <= off:
            escolhida = f
        else:
            break
    if escolhida is None:
        return None
    return {"texto": escolhida, "pagina": bloco.get("pagina"), "secao": bloco.get("titulo_secao") or tk["secoes"][tk["secao"][posicao]]}


def _item(texto, doc_id, pagina, secao, motivo, codigo=None, tema=None, origem="") -> dict:
    return {"texto": " ".join(str(texto).split()), "documento_id": doc_id, "pagina": pagina, "secao": secao, "motivo": motivo,
            "codigo": codigo, "tema": tema, "origem": origem}


def coletar_itens(db: Session, pasta: Path, metas: list[dict], selecao: list[dict]) -> list[dict]:
    """Resolve a seleção em itens ``{texto, documento_id, pagina, secao, motivo, codigo, tema, origem}``. Levanta ValueError."""
    itens: list[dict] = []
    for s in selecao:
        tipo = s.get("tipo")
        if tipo not in TIPOS:
            raise ValueError(f"Tipo de seleção inválido '{tipo}': use {', '.join(TIPOS)}.")
        if tipo == "comentario":
            q = select(Comentario).where(Comentario.status.in_(("aceito", "editado"))).order_by(Comentario.id)
            if s.get("comentario_id"):
                q = q.where(Comentario.id == s["comentario_id"])
            for c in db.scalars(q):
                for ev in c.evidencias:
                    itens.append(_item(ev.trecho, ev.documento_id, ev.pagina, None,
                                       f"Raio-X: comentário {c.status} ({c.regra} #{c.id})", origem="comentario"))
        elif tipo == "kwic":
            escopo, valor = s.get("escopo") or "corpus", s.get("valor")
            docs = dados.filtrar_escopo(metas, escopo, valor)
            por = s.get("por") or "lema"
            if s.get("posicoes"):
                pares = []
                for p in s["posicoes"]:
                    try:
                        d, pos = str(p).split(":")
                        pares.append((int(d), int(pos)))
                    except ValueError:
                        raise ValueError(f"Posição inválida '{p}': use 'documento:posição'.")
            else:
                r = kwic.buscar(pasta, docs, s.get("consulta") or "", por=por, janela=1, limit=int(s.get("limite") or 50))
                pares = [(h["documento_id"], h["posicao"]) for h in r["itens"] if h.get("corpo", True)]
            for d, pos in pares:
                f = frase_do_token(pasta, d, pos)
                if f:
                    itens.append(_item(f["texto"], d, f["pagina"], f["secao"], ("Raio-X: KWIC \"" + str(s["consulta"]) + "\"") if s.get("consulta") else "Raio-X: KWIC",
                                       origem="kwic"))
        elif tipo == "celula":
            from app.services.corpus import planilha as svc_planilha
            r = svc_planilha.celula(db, pasta, int(s["documento_id"]), s.get("parte") or "")
            if r is None:
                if db.get(Documento, int(s["documento_id"])) is None or s.get("parte") not in P.CHAVES:
                    raise ValueError(f"Célula não encontrada (documento {s.get('documento_id')}, parte '{s.get('parte')}').")
                continue  # documento sem texto processado (fora da planilha do corpus): nada a exportar
            for t in r["trechos"]:
                itens.append(_item(t["texto"], r["documento_id"], t.get("pagina"), t.get("titulo_secao") or t.get("secao"),
                                   f"Raio-X: planilha do corpus ({r['rotulo_parte']}; {t.get('regra') or t.get('metodo')})", origem="celula"))
        elif tipo == "codificacao":
            q = select(CodificacaoTrecho).where(CodificacaoTrecho.status == "codificado").order_by(CodificacaoTrecho.id)
            if s.get("ids"):
                q = select(CodificacaoTrecho).where(CodificacaoTrecho.id.in_([int(i) for i in s["ids"]])).order_by(CodificacaoTrecho.id)
            for t in db.scalars(q):
                if not t.documento_id:
                    continue
                itens.append(_item(t.texto, t.documento_id, t.pagina, t.secao,
                                   f"Raio-X: codificação LLM ({t.modelo or 'modelo?'}, confiança {t.confianca if t.confianca is not None else '?'})",
                                   codigo=t.codigo_llm or t.codigo_humano, tema=t.tema_humano, origem="codificacao"))
        else:  # trecho livre
            if not (s.get("texto") or "").strip():
                raise ValueError("Trecho livre sem texto.")
            itens.append(_item(s["texto"], s.get("documento_id"), s.get("pagina"), s.get("secao"), s.get("motivo") or "Raio-X: trecho selecionado",
                               codigo=s.get("codigo"), tema=s.get("tema"), origem="trecho"))
        if len(itens) > MAX_ITENS:
            raise ValueError(f"Seleção grande demais (mais de {MAX_ITENS} trechos).")
    return itens


# ---------- geração ----------

def _papel(nome: str) -> str | None:
    h = _sa(nome)
    if h == "id registro":
        return "registro"
    if h == "id fonte":
        return "fonte"
    if h.startswith("fonte"):
        return "fonte_rotulo"
    if h.startswith("pagina"):
        return "pagina"
    if h.startswith("secao"):
        return "secao"
    if "original" in h and ("trecho" in h or "citac" in h):
        return "texto"
    if "traduz" in h or "translat" in h:
        return "traducao"
    if h == "codigo":
        return "codigo"
    if h == "tema":
        return "tema"
    if h.startswith("motivo"):
        return "motivo"
    if "verificada" in h:
        return "verificada"
    if h.startswith("observ"):
        return "observacao"
    return None


def _verificar(pasta: Path, cache: dict, doc_id, texto: str) -> str:
    if not doc_id:
        return "documento não informado"
    if doc_id not in cache:
        blocos = dados.carregar_blocos(pasta, doc_id)
        cache[doc_id] = L.TextoDoDocumento(blocos) if blocos else None
    td = cache[doc_id]
    if td is None:
        return "documento sem texto"
    return "verbatim (Raio-X)" if td.localizar(texto) is not None else "não localizado no texto"


def _rotulo_fonte(meta: dict) -> str:
    if meta.get("autor") and meta.get("ano"):
        return f"{meta['autor']} ({meta['ano']})"
    return meta.get("rotulo") or ""


def _id_fonte(meta: dict, prefixo: str) -> str:
    digitos = re.sub(r"\D", "", str(meta.get("id_estudo") or ""))
    if digitos:
        return f"{prefixo}{int(digitos):03d}"
    return str(meta.get("id_estudo") or "")


def gerar(db: Session, pasta: Path, itens: list[dict], referencia: dict | None = None, incluir_duplicados: bool = True) -> tuple[bytes, dict]:
    """Monta o .xlsx novo. Devolve (bytes, resumo)."""
    cabecalho = list(referencia["cabecalho"]) if referencia else list(COLUNAS_PADRAO)
    indice = referencia["indice"] if referencia else IndiceExistentes()
    prefixo = referencia["prefixo_fonte"] if referencia else "R"
    papeis = [_papel(c) for c in cabecalho]
    for obrig in ("texto",):
        if obrig not in papeis:
            raise PlanilhaInvalida("O cabeçalho da planilha de referência não tem a coluna do trecho original.")
    vistos: dict[str, int] = {}
    linhas, dup_planilha, dup_selecao, contador = [], [], 0, Counter()
    verif_cache: dict = {}
    metas_cache: dict = {}
    for it in itens:
        n = normalizar_trecho(it["texto"])
        if not n:
            continue
        if n in vistos:
            dup_selecao += 1
            continue
        vistos[n] = 1
        meta = metas_cache.setdefault(it["documento_id"], _meta(db, it["documento_id"]))
        fonte = _id_fonte(meta, prefixo)
        existente = indice.achar(it["texto"])
        if existente and not incluir_duplicados:
            dup_planilha.append({"registro": existente, "texto": it["texto"][:160]})
            continue
        contador[fonte] += 1
        obs = f"DUPLICADO: já consta na planilha ({existente})" if existente else ""
        if existente:
            dup_planilha.append({"registro": existente, "texto": it["texto"][:160]})
        valores = {"registro": f"RX-{fonte or 'S'}-{contador[fonte]:02d}", "fonte": fonte, "fonte_rotulo": _rotulo_fonte(meta),
                   "pagina": it["pagina"], "secao": it["secao"], "texto": it["texto"], "traducao": "", "codigo": it["codigo"] or "",
                   "tema": it["tema"] or "", "motivo": it["motivo"], "observacao": obs,
                   "verificada": _verificar(pasta, verif_cache, it["documento_id"], it["texto"])}
        linhas.append(([valores.get(p, "") if p else "" for p in papeis], bool(existente)))

    wb = Workbook()
    ws = wb.active
    ws.title = (referencia or {}).get("aba", ABA_PADRAO)[:31]
    ws.append(cabecalho)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="305496")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    j_texto = papeis.index("texto")
    for valores, dup in linhas:
        ws.append([_seguro(v) if isinstance(v, str) else v for v in valores])
        if dup:
            for c in ws[ws.max_row]:
                c.fill = AMARELO
    for j, nome in enumerate(cabecalho, 1):
        ws.column_dimensions[get_column_letter(j)].width = 70 if j - 1 == j_texto or papeis[j - 1] in ("traducao",) else min(30, max(12, len(nome) + 2))
    for linha in ws.iter_rows(min_row=2):
        for c in linha:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    resumo = {"selecionados": len(itens), "exportados": len(linhas), "duplicados_na_planilha": len(dup_planilha),
              "duplicados_na_selecao": dup_selecao, "incluir_duplicados": incluir_duplicados,
              "planilha_referencia": bool(referencia), "trechos_na_planilha": indice.total,
              "por_origem": dict(Counter(i["origem"] for i in itens)), "duplicados": dup_planilha[:200]}
    rs = wb.create_sheet("Resumo")
    rs.append(["Exportação do Raio-X para a coleta da MLR"])
    rs["A1"].font = Font(bold=True, size=13)
    for k, v in (("Trechos selecionados", resumo["selecionados"]), ("Linhas exportadas", resumo["exportados"]),
                 ("Já constavam na planilha do usuário (marcados em amarelo)" if incluir_duplicados else "Já constavam na planilha (omitidos)", resumo["duplicados_na_planilha"]),
                 ("Repetidos dentro da seleção (removidos)", dup_selecao), ("Trechos na planilha de referência", indice.total),
                 ("Planilha de referência usada", "sim (somente leitura)" if referencia else "não: cabeçalho padrão, sem checagem de duplicatas")):
        rs.append([k, v])
    rs.append([])
    rs.append(["Como foi preenchido"])
    rs[f"A{rs.max_row}"].font = Font(bold=True)
    for linha in ("Trecho original = texto literal do documento (nenhuma edição); Trecho traduzido = vazio.",
                  "Motivo da coleta = 'Raio-X: <análise de origem>'. Código e Tema só quando conhecidos (codificação LLM).",
                  "Sentença verificada (auto) = o trecho foi localizado no texto do documento (verbatim) ou não.",
                  "Trilha, Rótulo do código, QP, Tipo de alegação, Evidência, Transferibilidade e Decisão do revisor ficam em branco: são do revisor.",
                  "ID registro 'RX-...' é provisório: renumere ao colar na planilha de coleta. Esta exportação não altera a planilha do usuário."):
        rs.append([linha])
    rs.column_dimensions["A"].width = 70
    if resumo["duplicados"]:
        rs.append([])
        rs.append(["Duplicados", "Registro existente"])
        for d in resumo["duplicados"]:
            rs.append([_seguro(d["texto"]), _seguro(str(d["registro"]))])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), resumo
