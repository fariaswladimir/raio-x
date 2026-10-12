"""Exportações para validação externa (5.4 / 12.2): corpus limpo para o AntConc e o IRaMuTeQ.

``GET /api/projetos/{slug}/exportar/corpus-iramuteq.txt`` devolve o corpus no formato do IRaMuTeQ (12.2; ver
docs/validacao_iramuteq.md). ``GET /api/projetos/{slug}/exportar/corpus-limpo.zip`` gera, em memória:

- ``textos/<arquivo>.txt``: um .txt UTF-8 por documento ativo, só com os blocos do corpo (``incluir``),
  **texto original** (caixa e pontuação preservadas), um bloco por parágrafo (linha em branco entre blocos;
  quebras de linha internas viram espaço). Títulos de seção, referências e seções excluídas ficam de fora.
- ``stoplist.txt``: palavras vazias ativas no projeto, uma por linha (formato de stoplist do AntConc).
- ``lemas.txt``: lista de lemas no formato ``lema -> forma1, forma2`` (só lemas com formas diferentes do
  próprio lema), para a comparação por lema no AntConc.
- ``LEIAME.txt``: parâmetros usados e o roteiro resumido (ver docs/validacao_antconc.md).
"""
import io
import re
import zipfile
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services import parametros as svc_parametros
from app.services.analises import dados
from app.services.exportar import comum, pacote, planilhas
from app.services.palavras_vazias import COMPRIMENTO_MINIMO, filtro_palavras_vazias

router = APIRouter(prefix="/api/projetos/{slug}/exportar", tags=["exportacao"])

_ESPACOS = re.compile(r"\s+")
_INVALIDO = re.compile(r"[^\w.\-]+")


def _nome_txt(arquivo: str, usados: set[str]) -> str:
    base = _INVALIDO.sub("_", arquivo.rsplit(".", 1)[0].replace("/", "__").replace("\\", "__"))[:120] or "documento"
    nome, i = f"{base}.txt", 2
    while nome in usados:
        nome, i = f"{base}_{i}.txt", i + 1
    usados.add(nome)
    return nome


def texto_do_corpo(blocos: list[dict]) -> str:
    """Texto original dos blocos do corpo, um bloco por parágrafo."""
    return "\n\n".join(_ESPACOS.sub(" ", b["texto"]).strip() for b in blocos if b.get("incluir", True) and b["texto"].strip()) + "\n"


def _leiame(params: dict, n_docs: int) -> str:
    j = params.get("colocacao_janela", 5)
    return f"""Raio-X - corpus limpo para validação no AntConc / IRaMuTeQ
==========================================================

Documentos: {n_docs} (pasta textos/, um .txt por documento, UTF-8, só o corpo: sem títulos de seção,
referências e seções excluídas {params.get('excluir_secoes')}).

Configuração equivalente do Raio-X (colocados, 5.4):
- janela {j}L / {j}R; tokens de >= {COMPRIMENTO_MINIMO} letras; palavras vazias ocupam posição;
- lematização: {'ligada' if (params.get('lematizacao') or {}).get('ativa', True) else 'desligada'} (lemas.txt para o AntConc);
- palavras vazias: stoplist.txt;
- no Raio-X use fronteira=documento para a comparação exata (o AntConc não respeita página/seção).

Passo a passo: docs/validacao_antconc.md no repositório do Raio-X.
"""


@router.get("/corpus-limpo.zip")
def corpus_limpo_zip(slug: str, db: Session = Depends(get_db)):
    pasta = pasta_do_projeto(slug)
    params = svc_parametros.carregar(pasta)
    metas = dados.documentos_do_corpus(db, pasta)
    if not metas:
        raise HTTPException(status_code=404, detail="Nenhum documento processado: execute o pipeline primeiro.")
    formas_por_lema: dict[str, set[str]] = defaultdict(set)
    usados: set[str] = set()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for m in metas:
            blocos = dados.carregar_blocos(pasta, m["id"]) or []
            z.writestr(f"textos/{_nome_txt(m['arquivo'], usados)}", texto_do_corpo(blocos).encode("utf-8"))
            tk = dados.carregar_tokens(pasta, m["id"])
            if tk:
                for nm, lm, inc in zip(tk["norm"], tk["lema"], tk["incluir"]):
                    if inc and len(nm) >= COMPRIMENTO_MINIMO and nm != lm:
                        formas_por_lema[lm].add(nm)
        z.writestr("stoplist.txt", "\n".join(sorted(filtro_palavras_vazias(params))) + "\n")
        z.writestr("lemas.txt", "".join(f"{lm} -> {', '.join(sorted(fs))}\n" for lm, fs in sorted(formas_por_lema.items())))
        z.writestr("LEIAME.txt", _leiame(params, len(metas)))
    return Response(content=buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="corpus-limpo.zip"'})


def _modalidade(valor) -> str:
    """Modalidade de variável estrelada do IRaMuTeQ: só letras, dígitos e _ (sem espaços nem acentos problemáticos)."""
    texto = re.sub(r"[^0-9A-Za-z]+", "_", str(valor or "").strip()).strip("_")
    return texto or "na"


@router.get("/corpus-iramuteq.txt")
def corpus_iramuteq(slug: str, db: Session = Depends(get_db)):
    """Corpus no formato do IRaMuTeQ (12.2): um texto por documento ativo, com a linha de cabeçalho
    ``**** *doc_<id> *grupo_<g> *ano_<a>`` e o mesmo texto do corpo do ``corpus-limpo.zip`` (um bloco por parágrafo).
    Asteriscos do texto viram espaço (o IRaMuTeQ os reserva para as variáveis). Ver docs/validacao_iramuteq.md."""
    pasta = pasta_do_projeto(slug)
    metas = dados.documentos_do_corpus(db, pasta)
    if not metas:
        raise HTTPException(status_code=404, detail="Nenhum documento processado: execute o pipeline primeiro.")
    partes = []
    for m in metas:
        blocos = dados.carregar_blocos(pasta, m["id"]) or []
        corpo = texto_do_corpo(blocos).replace("*", " ").strip()
        if not corpo:
            continue
        doc = _modalidade(m.get("id_estudo") or f"{m['id']:03d}")
        cab = f"**** *doc_{doc} *grupo_{_modalidade(dados.chave_grupo(m))} *ano_{_modalidade(dados.chave_ano(m))}"
        partes.append(f"{cab}\n{corpo}\n")
    return Response(content="\n".join(partes).encode("utf-8"), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="corpus-iramuteq.txt"'})


@router.get("/{nome}.csv")
def exportar_csv(slug: str, nome: str, db: Session = Depends(get_db)):
    """Planilha CSV (UTF-8 com BOM, ``;``, decimais com ponto): documentos, frequencias, keyness, colocacoes, comentarios, evidencias."""
    if nome not in planilhas.NOMES:
        raise HTTPException(status_code=404, detail=f"Planilha '{nome}' inexistente. Use: {', '.join(planilhas.NOMES)}.")
    try:
        conteudo = planilhas.gerar(nome, db, pasta_do_projeto(slug))
    except comum.SemDados as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return Response(content=conteudo, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}.csv"'})


@router.post("/pacote.zip")
def exportar_pacote(slug: str, db: Session = Depends(get_db)):
    """Gera laudo.html, os CSV e parametros.json em ``saidas/`` e devolve tudo em um zip (também gravado em ``saidas/pacote.zip``)."""
    try:
        conteudo = pacote.montar_pacote(db, pasta_do_projeto(slug))
    except comum.SemDados as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return Response(content=conteudo, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="pacote.zip"'})
