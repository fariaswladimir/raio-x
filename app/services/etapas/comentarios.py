"""Etapa 70 - Comentários por regra (entregável 8.1).

Escopo corpus, depois de ``descritivo`` e ``comparativo``. Lê o catálogo de regras (``catalogo.yaml``), gera os
comentários a partir dos instantâneos da tabela ``analise`` (e de colocados/tendências sob demanda) e os
reconcilia com a revisão humana (ver ``app/services/regras/motor.py``).

Cache: depende de ``descritivo`` e ``comparativo`` (chaves encadeadas) e de ``entrada_extra`` = hash do arquivo
do catálogo + status dos documentos; editar o YAML regenera os comentários na próxima execução.
"""
import hashlib
import time

from sqlalchemy import select

from app.models import Documento
from app.services.etapas.descritivo import PARAMETROS_RELEVANTES as _PARAMETROS_DESCRITIVO
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa
from app.services.regras import catalogo

VERSAO_ETAPA = "2"
PARAMETROS_RELEVANTES = [*_PARAMETROS_DESCRITIVO, "colocacao_janela", "kwic_janela"]


def _entrada_extra(db) -> str:
    status = repr([(d.arquivo, d.status, bool(d.excluido)) for d in db.scalars(select(Documento).order_by(Documento.arquivo))])
    return hashlib.sha256(f"{catalogo.hash_catalogo()}|{status}".encode("utf-8")).hexdigest()


def comentar(ctx: ContextoExecucao):
    from app.services.regras import motor  # import tardio: evita ciclo com app.services.analises

    inicio = time.time()
    regras = catalogo.carregar_catalogo()  # CatalogoInvalido (ValueError) vira erro da etapa, com a regra e o campo
    resultado = motor.comentar(ctx.db, ctx.pasta_projeto, ctx.parametros, regras)
    resultado["segundos"] = round(time.time() - inicio, 2)
    return resultado


registrar_etapa(Etapa(
    nome="comentarios", ordem=70, escopo="corpus", funcao=comentar, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["descritivo", "comparativo"],
    entrada_extra=_entrada_extra,
))
