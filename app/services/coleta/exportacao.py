"""17.3 - Exportações da coleta: larga (.xlsx/.csv), longa (.xlsx/.csv) e envio dos valores aceitos à planilha de coleta da MLR (9.5).

Versões
-------
- ``final``: só células **aceitas ou editadas** (mais "não se aplica", decisão do revisor, escrita assim); o resto sai em branco;
- ``auditoria``: todas as células com valor, evidência, status, origem, confiança e justificativa (inclui sugeridas, rejeitadas e não encontradas).

Larga: uma linha por documento; para cada item, a coluna do valor e, **ao lado**, a coluna "evidência" com "[p. N] trecho" (trechos separados por linha em branco);
na auditoria, mais a coluna "status". Longa: uma linha por documento x item x trecho com todos os campos (célula sem trecho = uma linha com trecho vazio).
Os dois .xlsx têm a aba "Protocolo" (o protocolo da execução) e a "LEIA-ME". Textos que começam com = + - @ ganham apóstrofo (injeção de fórmula): reuso de
``corpus.planilha._txt`` e ``exportar.planilhas.csv_bytes``.

Envio à planilha da MLR: os trechos das células aceitas/editadas viram itens do formato da 9.5 (``exportacao_coleta.gerar``): arquivo novo, cabeçalho e
detecção de duplicatas contra a planilha do usuário (somente leitura), ``Motivo da coleta`` = "Raio-X: coleta guiada (<item>: <valor>)".
"""
import io
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from app.services.analises import dados as svc_dados
from app.services.coleta import celulas as C
from app.services.coleta import motor as M
from app.services.coleta import protocolo as PR
from app.services.concordancia import exportacao_coleta as X
from app.services.corpus import planilha as svc_planilha
from app.services.corpus import projeto as svc_projeto
from app.services.exportar.planilhas import csv_bytes

VERSOES = ("final", "auditoria")
_txt = svc_planilha._txt


def visivel(cel: dict | None, versao: str) -> bool:
    if cel is None:
        return False
    if versao == "auditoria":
        return True
    return cel["status"] in C.FINAIS or cel["status"] == "nao_se_aplica"


def texto_evidencia(cel: dict | None) -> str:
    if not cel:
        return ""
    return "\n\n".join((f"[p. {t['pagina']}] " if t.get("pagina") is not None else "") + t["texto"] for t in cel.get("trechos") or [])


def _valor_celula(cel: dict, tipo: str):
    v = cel.get("valor")
    if cel.get("status") == "nao_se_aplica":
        return C.NAO_SE_APLICA
    if v is None:
        return None
    if tipo == "numero" and isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    return C.valor_como_texto(cel, tipo)


def _status_texto(cel: dict) -> str:
    partes = [C.ROTULO_STATUS.get(cel["status"], cel["status"]), cel.get("origem") or ""]
    if cel.get("confianca") is not None and cel["status"] != "nao_encontrado":
        partes.append(f"{cel['confianca']:.2f}".replace(".", ","))
    if cel.get("revisar"):
        partes.append("REVISAR")
    return " · ".join(p for p in partes if p)


def _dados(db, pasta: Path):
    prot = PR.carregar(pasta)
    docs = [d for d in svc_projeto.documentos_ativos(db)]
    return prot, docs, C.carregar(pasta)


def cabecalho_larga(itens: list[dict], versao: str) -> list[str]:
    cab = ["Rótulo", "Arquivo", "Ano", "Grupo"]
    for i in itens:
        cab += [f"{i['id']} {i['nome']}", f"{i['id']} evidência"]
        if versao == "auditoria":
            cab.append(f"{i['id']} status")
    return cab


def linhas_larga(db, pasta: Path, versao: str) -> tuple[list[str], list[list], dict]:
    prot, docs, dados = _dados(db, pasta)
    itens = prot["itens"]
    linhas = []
    for d in docs:
        if d.arquivo not in dados["celulas"]:
            continue
        linha = [svc_dados.rotulo_do_documento(d), d.arquivo, d.ano, d.grupo]
        for i in itens:
            cel = C.celula_de(dados, d.arquivo, i["id"])
            ok = visivel(cel, versao)
            linha += [_valor_celula(cel, i["tipo"]) if ok else None, texto_evidencia(cel) if ok else None]
            if versao == "auditoria":
                linha.append(_status_texto(cel) if cel else None)
        linhas.append(linha)
    return cabecalho_larga(itens, versao), linhas, prot


CABECALHO_LONGA = ["Documento", "Arquivo", "Grupo", "Ano", "Item", "Nome do item", "Tipo", "Valor", "Unidade", "Status", "Origem", "Confiança", "Justificativa",
                   "Trecho", "Página", "Seção", "Nota do revisor", "Revisar", "Valor automático", "Decidido em"]


def linhas_longa(db, pasta: Path, versao: str) -> tuple[list[str], list[list], dict]:
    prot, docs, dados = _dados(db, pasta)
    linhas = []
    for d in docs:
        rotulo = svc_dados.rotulo_do_documento(d)
        for i in prot["itens"]:
            cel = C.celula_de(dados, d.arquivo, i["id"])
            if not visivel(cel, versao):
                continue
            auto = (cel.get("automatico") or {}).get("valor")
            base = [rotulo, d.arquivo, d.grupo, d.ano, i["id"], i["nome"], i["tipo"], _valor_celula(cel, i["tipo"]), cel.get("unidade"), C.ROTULO_STATUS.get(cel["status"], cel["status"]),
                    cel.get("origem"), cel.get("confianca"), cel.get("justificativa")]
            fim = [cel.get("nota"), cel.get("revisar"), (", ".join(auto) if isinstance(auto, list) else auto) if auto is not None else None, cel.get("decidido_em")]
            trechos = cel.get("trechos") or [None]
            for t in trechos:
                linhas.append(base + ([t["texto"], t.get("pagina"), t.get("secao")] if t else [None, None, None]) + fim)
    return CABECALHO_LONGA, linhas, prot


def _leia_me(versao: str, prot: dict, n_docs: int, n_linhas: int, formato: str) -> list[tuple[str, str]]:
    return [
        ("Coleta guiada por protocolo (Raio-X, Frente 17)", ""),
        ("", ""),
        ("Versão", "FINAL: só valores aceitos ou editados pelo revisor (e \"não se aplica\", decisão do revisor)." if versao == "final" else
         "AUDITORIA: todos os valores, inclusive sugeridos, rejeitados e não encontrados, com status, origem e confiança."),
        ("Formato", {"larga": "Uma linha por documento; ao lado de cada valor, a coluna de evidência com \"[p. N] trecho\".",
                     "longa": "Uma linha por documento x item x trecho, com todos os campos."}[formato]),
        ("Protocolo", f"Versão {prot['versao_protocolo']} com {len(prot['itens'])} item(ns); a aba \"Protocolo\" tem as definições."),
        ("Documentos / linhas", f"{n_docs} documento(s); {n_linhas} linha(s)."),
        ("Origem", "regra = seção e palavras-chave; padrao = padrões de linguagem da planilha do corpus (16.1); llm = modelo, com trecho conferido literalmente no documento; "
                   "humano = valor digitado pelo revisor."),
        ("Cuidados", "Valores sugeridos são heurísticos e precisam de revisão humana; \"não encontrado\" não prova que o documento não trata do item. Trechos são frases literais do documento "
                     "(podem terminar em \"(…)\" quando a seção foi cortada)."),
    ]


def _estilizar(ws, larguras: dict[int, int] | None = None) -> None:
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    for j, w in (larguras or {}).items():
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = w
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions


def gerar_xlsx(db, pasta: Path, formato: str, versao: str) -> bytes:
    if versao not in VERSOES:
        raise ValueError("Versão inválida: use final ou auditoria.")
    cab, linhas, prot = (linhas_larga if formato == "larga" else linhas_longa)(db, pasta, versao)
    wb = Workbook()
    ws = wb.active
    ws.title = "Larga" if formato == "larga" else "Longa"
    ws.append([_txt(c) for c in cab])
    for l in linhas:
        ws.append([_txt(v) if isinstance(v, str) else v for v in l])
    larguras = {1: 22, 2: 30, 3: 7, 4: 12}
    if formato == "larga":
        passo = 3 if versao == "auditoria" else 2
        for k in range(len(prot["itens"])):
            larguras[5 + k * passo] = 28
            larguras[6 + k * passo] = 60
            if versao == "auditoria":
                larguras[7 + k * passo] = 22
    else:
        larguras = {1: 22, 2: 30, 3: 12, 4: 7, 5: 10, 6: 24, 7: 12, 8: 28, 9: 12, 10: 14, 11: 10, 12: 10, 13: 34, 14: 80, 15: 8, 16: 22, 17: 24, 18: 28, 19: 24, 20: 18}
    _estilizar(ws, larguras)
    PR.adicionar_aba_protocolo(wb, prot["itens"])
    wl = wb.create_sheet("LEIA-ME")
    wl.column_dimensions["A"].width = 24
    wl.column_dimensions["B"].width = 120
    for a, b in _leia_me(versao, prot, len({l[1] for l in linhas}) if linhas else 0, len(linhas), formato):
        wl.append([a, b])
    wl["A1"].font = Font(bold=True, size=14)
    for row in wl.iter_rows(min_row=2):
        row[0].font = Font(bold=True)
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def gerar_csv(db, pasta: Path, formato: str, versao: str) -> bytes:
    if versao not in VERSOES:
        raise ValueError("Versão inválida: use final ou auditoria.")
    cab, linhas, _prot = (linhas_larga if formato == "larga" else linhas_longa)(db, pasta, versao)
    return csv_bytes(cab, [["" if v is None else v for v in l] for l in linhas])


# ---------- envio à planilha de coleta da MLR (9.5) ----------

def itens_para_mlr(db, pasta: Path, item_ids: list[str] | None = None) -> list[dict]:
    prot, docs, dados = _dados(db, pasta)
    por_id = {i["id"]: i for i in prot["itens"]}
    saida = []
    for d in docs:
        for iid, it in por_id.items():
            if item_ids and iid not in item_ids:
                continue
            cel = C.celula_de(dados, d.arquivo, iid)
            if not cel or cel["status"] not in C.FINAIS:
                continue
            for t in cel.get("trechos") or []:
                texto = " ".join(M._sem_marcas(t["texto"]).split())
                if not texto:
                    continue
                saida.append({"texto": texto, "documento_id": d.id, "pagina": t.get("pagina"), "secao": t.get("secao"),
                              "motivo": f"Raio-X: coleta guiada ({it['nome']}: {C.valor_como_texto(cel, it['tipo'])[:80]})", "codigo": None, "tema": None, "origem": "coleta"})
    return saida


def enviar_para_mlr(db, pasta: Path, planilha_referencia: str | None = None, aba: str | None = None, incluir_duplicados: bool = True,
                    item_ids: list[str] | None = None) -> tuple[bytes, dict]:
    itens = itens_para_mlr(db, pasta, item_ids)
    if not itens:
        raise ValueError("Nenhuma célula aceita ou editada com trecho: aceite valores na matriz antes de enviar à planilha de coleta.")
    referencia = X.ler_planilha_referencia(planilha_referencia, aba) if planilha_referencia else None
    return X.gerar(db, pasta, itens, referencia, incluir_duplicados)
