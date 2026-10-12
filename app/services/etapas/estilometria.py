"""Etapa 69 (depois de documento_extra) - instantâneo da estilometria (15.6).

Escopo corpus. Parâmetros no bloco ``estilometria`` de parametros.json (padrão: 100 MFW, culling 0, Delta clássico,
unidade documento, amostras de 2.000 tokens), ligação Ward (ward.D, como o stylo), k automático e PCA de correlação.
Grava **uma** linha da tabela ``analise`` (tipo ``estilometria``), substituída a cada execução; com menos de 3 unidades
nada é gravado e a linha antiga é removida.

Cache: depende de ``vocabulario`` (que vem depois da linguística) e ``ruido`` e de ``entrada_extra`` = hash dos
metadados editáveis (rótulos, ano e grupo entram no resultado).
"""
import time

from sqlalchemy import delete

from app.models import Analise
from app.services.etapas.descritivo import _metadados_assinatura
from app.services.etapas.especificidades import _gravar
from app.services.orquestrador import ContextoExecucao, Etapa, registrar_etapa

VERSAO_ETAPA = "1"
PARAMETROS_RELEVANTES = ["estilometria", "idioma", "excluir_referencias", "excluir_secoes", "limpeza"]


def parametros_estilometria(parametros: dict | None) -> dict:
    from app.services.analises import estilometria

    p = {**estilometria.PADRAO, **((parametros or {}).get("estilometria") or {})}
    return {"mfw": int(p["mfw"]), "culling": float(p["culling"]), "distancia_": str(p["distancia"]),
            "unidade": str(p["unidade"]), "tamanho_amostra": int(p["tamanho_amostra"])}


def calcular_estilometria(ctx: ContextoExecucao):
    from app.services import ruido as svc_ruido
    from app.services.analises import dados, estilometria

    inicio = time.time()
    metas = dados.documentos_do_corpus(ctx.db, ctx.pasta_projeto)
    ctx.db.execute(delete(Analise).where(Analise.tipo == "estilometria"))
    p = parametros_estilometria(ctx.parametros)
    try:
        res = estilometria.calcular(ctx.pasta_projeto, metas, excluir_ruido=svc_ruido.excluir_ruido(ctx.parametros), **p)
    except ValueError as exc:
        ctx.db.commit()
        return {"unidades": 0, "mensagem": str(exc)}
    bloco = {("distancia" if k == "distancia_" else k): v for k, v in p.items()}
    _gravar(ctx, "estilometria", {"estilometria": bloco}, res["ferramenta_equivalente"], res)
    ctx.db.commit()
    return {"unidades": res["n_unidades"], "documentos": res["n_documentos"], "mfw": res["mfw_efetivo"], "k": res["k"],
            "distancia": res["distancia"], "segundos": round(time.time() - inicio, 2)}


registrar_etapa(Etapa(
    nome="estilometria", ordem=69, escopo="corpus", funcao=calcular_estilometria, versao=VERSAO_ETAPA,
    parametros_relevantes=PARAMETROS_RELEVANTES, depende_de=["vocabulario", "ruido"],
    entrada_extra=_metadados_assinatura,
))
