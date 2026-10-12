"""9.5 Exportação para a planilha de coleta da MLR (.xlsx novo, no formato da aba de trechos).

Rotas: GET/POST /api/projetos/{slug}/exportar/coleta.xlsx e POST /api/projetos/{slug}/exportar/coleta/previa.
A planilha de referência do usuário (para copiar o cabeçalho e achar duplicatas) é só lida; o arquivo devolvido é novo.
Regras de preenchimento e de duplicatas em services/concordancia/exportacao_coleta.py.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, pasta_do_projeto
from app.services.analises import dados
from app.services.concordancia import exportacao_coleta as X
from app.services.concordancia.importacao import PlanilhaInvalida

router = APIRouter(prefix="/api/projetos/{slug}/exportar", tags=["exportacao"])
MEDIA_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ItemSelecao(BaseModel):
    tipo: Literal["comentario", "kwic", "celula", "codificacao", "trecho"]
    comentario_id: int | None = Field(None, description="Um comentário aceito (omitido = todos os aceitos/editados)")
    consulta: str | None = None
    por: Literal["lema", "forma", "termo"] = "lema"
    escopo: Literal["corpus", "documento", "grupo", "ano"] = "corpus"
    valor: str | None = None
    posicoes: list[str] | None = Field(None, description="Ocorrências do KWIC escolhidas: 'documento:posição'")
    limite: int = Field(50, ge=1, le=1000)
    documento_id: int | None = None
    parte: str | None = Field(None, description="Parte da planilha do corpus (ex.: limitacoes)")
    ids: list[int] | None = Field(None, description="Ids de codificacao_trecho (omitido = todos os codificados)")
    texto: str | None = None
    pagina: int | None = None
    secao: str | None = None
    codigo: str | None = None
    tema: str | None = None
    motivo: str | None = None


class ExportacaoIn(BaseModel):
    selecao: list[ItemSelecao] = Field(min_length=1, max_length=200)
    planilha_referencia: str | None = Field(None, description="Caminho da planilha de coleta do usuário (só leitura)")
    aba: str | None = None
    incluir_duplicados: bool = True


def _montar(slug: str, db: Session, corpo: ExportacaoIn) -> tuple[bytes, dict]:
    pasta = pasta_do_projeto(slug)
    metas = dados.documentos_do_corpus(db, pasta)
    try:
        referencia = X.ler_planilha_referencia(corpo.planilha_referencia, corpo.aba) if corpo.planilha_referencia else None
        itens = X.coletar_itens(db, pasta, metas, [i.model_dump(exclude_none=True) for i in corpo.selecao])
        if not itens:
            raise ValueError("A seleção não tem nenhum trecho (confira os comentários aceitos, a consulta ou a célula).")
        return X.gerar(db, pasta, itens, referencia, corpo.incluir_duplicados)
    except (PlanilhaInvalida, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _resposta(conteudo: bytes, resumo: dict, slug: str) -> Response:
    return Response(content=conteudo, media_type=MEDIA_XLSX, headers={
        "Content-Disposition": f'attachment; filename="coleta_raiox_{slug}.xlsx"',
        "X-Raiox-Resumo": json.dumps({k: v for k, v in resumo.items() if k != "duplicados"}, ensure_ascii=True)})


@router.post("/coleta.xlsx")
def exportar_coleta(slug: str, corpo: ExportacaoIn, db: Session = Depends(get_db)):
    """Novo .xlsx com os trechos selecionados no formato da aba de trechos (resumo no cabeçalho ``X-Raiox-Resumo``)."""
    conteudo, resumo = _montar(slug, db, corpo)
    return _resposta(conteudo, resumo, slug)


@router.post("/coleta/previa")
def previa_coleta(slug: str, corpo: ExportacaoIn, db: Session = Depends(get_db)):
    """Mesma seleção, só com as contagens (selecionados, exportados, duplicados com o registro existente)."""
    _conteudo, resumo = _montar(slug, db, corpo)
    return resumo


@router.get("/coleta.xlsx")
def exportar_coleta_get(slug: str, origens: str = Query("comentario", description="comentario, codificacao (separados por vírgula)"),
                        planilha_referencia: str | None = None, aba: str | None = None, incluir_duplicados: bool = True,
                        db: Session = Depends(get_db)):
    """Atalho: todos os comentários aceitos (e/ou trechos codificados pelo LLM) no formato da planilha de coleta."""
    tipos = [t.strip() for t in origens.split(",") if t.strip()]
    if not tipos or any(t not in ("comentario", "codificacao") for t in tipos):
        raise HTTPException(status_code=422, detail="origens: use comentario e/ou codificacao (para kwic, célula ou trecho use o POST com a seleção).")
    corpo = ExportacaoIn(selecao=[ItemSelecao(tipo=t) for t in tipos], planilha_referencia=planilha_referencia, aba=aba,
                         incluir_duplicados=incluir_duplicados)
    conteudo, resumo = _montar(slug, db, corpo)
    return _resposta(conteudo, resumo, slug)
