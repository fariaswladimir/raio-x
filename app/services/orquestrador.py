"""1.3 - Orquestrador do pipeline com cache por hash.

Uma *etapa* é um objeto registrado com nome, ordem, escopo e uma função:

- escopo "documento": a função roda uma vez por documento (``funcao(ctx, doc)``).
  Chave de cache = sha256(caminho + hash do arquivo + hash dos parâmetros + versão da etapa).
  O caminho entra na chave para que dois arquivos idênticos não compartilhem cache.
- escopo "corpus": a função roda uma vez sobre o corpus inteiro (``funcao(ctx)``).
  Chave de cache = sha256(hashes dos documentos, ordenados + hash dos parâmetros + versão da etapa).

Chave de cache por parâmetros relevantes
----------------------------------------
Cada etapa declara ``parametros_relevantes`` (lista de chaves de primeiro nível de
parametros.json; ``None`` = todos, o padrão antigo). A chave de cache usa só o hash
dessas chaves: mudar ``kwic_janela`` ou ``palavras_vazias`` não invalida o que não os lê.
Para que a mudança de uma etapa se propague às seguintes (ex.: ``conversao.ocr`` muda o
Markdown e, portanto, a limpeza), a etapa declara ``depende_de`` (nomes de etapas de
escopo "documento" anteriores): a chave de cada documento inclui as chaves das
dependências. Etapas de escopo "corpus" que dependem de etapas por documento incluem as
chaves de todos os documentos ativos; as que dependem de outra etapa "corpus" (ex.: descritivo
-> vocabulario) incluem a chave dessa etapa, recursivamente.

Cada execução registra o seu *alvo* ("corpus" ou "doc:<id>"). A etapa é pulada
(status "pulado") só se a **última** execução da mesma etapa sobre o mesmo alvo
terminou bem (ok/pulado) com o mesmo hash_entrada. Comparar com qualquer execução
antiga não basta: ligar → desligar → ligar um parâmetro deixaria no cache os
arquivos da versão "desligada". Toda tentativa é registrada em ``execucao``.
Etapas com ``cacheavel=False`` (ex.: varredura, que precisa olhar a pasta de
novo a cada vez) sempre rodam e gravam hash_entrada vazio.

Como adicionar uma etapa nova (frentes seguintes)
-------------------------------------------------
1. Criar app/services/etapas/<nome>.py com a função e registrar:

       from app.services.orquestrador import Etapa, registrar_etapa

       def converter(ctx, doc):          # escopo "documento"
           ...                           # ler ctx.pasta_origem / doc.arquivo (SOMENTE LEITURA)
           return {"paginas": 12}        # dict opcional: vira o texto de execucao.mensagem

       registrar_etapa(Etapa(nome="conversao", ordem=20, escopo="documento",
                             funcao=converter, versao="1"))

2. Importar o módulo em app/services/etapas/__init__.py.
3. Mudar ``versao`` quando a lógica da etapa mudar, para invalidar o cache.

Ordens: varredura=10, conversao=20, qualidade=25, limpeza=30, linguistica=40 (documento),
vocabulario=45, descritivo=50 (corpus).
Arquivos gerados devem ir para ctx.pasta_projeto / "cache" ou "saidas",
nunca para a pasta de origem.
"""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Documento, Execucao, Projeto, agora
from app.services import parametros as svc_parametros

ESCOPOS = ("documento", "corpus")
# Documentos nestes status não entram nas etapas por documento.
STATUS_IGNORADOS = ("removido", "com_problema")


def condicao_ativo():
    """Cláusula SQL dos documentos que entram nas etapas e análises: fora os ignorados e os excluídos pelo usuário
    (``documento.excluido``, reversível). Use no lugar de ``Documento.status.not_in(STATUS_IGNORADOS)``."""
    return and_(Documento.status.not_in(STATUS_IGNORADOS), Documento.excluido.is_not(True))


@dataclass
class ContextoExecucao:
    """O que cada etapa recebe para trabalhar."""

    db: Session
    pasta_projeto: Path
    pasta_origem: Path  # somente leitura
    parametros: dict
    hash_parametros: str


@dataclass
class Etapa:
    nome: str
    ordem: int
    escopo: str
    funcao: Callable
    versao: str = "1"
    cacheavel: bool = True
    # Chaves de parametros.json que a etapa lê (None = todas: compatível com o comportamento antigo).
    parametros_relevantes: list[str] | None = None
    # Etapas por documento cujo resultado esta etapa consome: entram na chave de cache.
    depende_de: list[str] = field(default_factory=list)
    # Só escopo "corpus": função (db) -> str com dados que não estão nos parâmetros nem nos hashes dos
    # arquivos (ex.: ano/grupo editados à mão). Entra na chave de cache.
    entrada_extra: Callable | None = None
    # Só escopo "documento": função (doc) -> str com dados do próprio documento que não estão nos parâmetros do projeto
    # nem no hash do arquivo (ex.: o override de OCR por documento). Entra na chave de cache só desse documento.
    entrada_doc: Callable | None = None

    def __post_init__(self):
        if self.escopo not in ESCOPOS:
            raise ValueError(f"Escopo inválido '{self.escopo}': use 'documento' ou 'corpus'.")


_REGISTRO: dict[str, Etapa] = {}


def registrar_etapa(etapa: Etapa) -> Etapa:
    _REGISTRO[etapa.nome] = etapa
    return etapa


def remover_etapa(nome: str) -> None:
    _REGISTRO.pop(nome, None)


def _carregar_etapas_padrao() -> None:
    import app.services.etapas  # noqa: F401  (o import registra as etapas)


def etapas_registradas() -> list[Etapa]:
    _carregar_etapas_padrao()
    return sorted(_REGISTRO.values(), key=lambda e: (e.ordem, e.nome))


def _sha(*partes: str) -> str:
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()


def hash_params_da_etapa(etapa: Etapa, params: dict) -> str:
    """Hash só dos parâmetros relevantes da etapa (todos, se ela não declarou)."""
    return svc_parametros.hash_parametros(params, etapa.parametros_relevantes)


def chave_documento(etapa: Etapa, arquivo: str, hash_arquivo: str, hash_params: str, dependencias: tuple[str, ...] = ()) -> str:
    return _sha(arquivo, hash_arquivo or "", hash_params, etapa.versao, *dependencias)


def chave_corpus(etapa: Etapa, hashes_documentos: list[str], hash_params: str, dependencias: tuple[str, ...] = ()) -> str:
    return _sha(",".join(sorted(h or "" for h in hashes_documentos)), hash_params, etapa.versao, *dependencias)


def _chave_doc_completa(etapas: dict[str, Etapa], etapa: Etapa, doc: Documento, params: dict) -> str:
    """Chave de uma etapa por documento, incluindo (recursivamente) as chaves das dependências."""
    deps = tuple(
        _chave_doc_completa(etapas, etapas[nome], doc, params) for nome in etapa.depende_de if nome in etapas
    )
    if etapa.entrada_doc is not None:
        deps = (*deps, str(etapa.entrada_doc(doc)))
    return chave_documento(etapa, doc.arquivo, doc.hash_sha256, hash_params_da_etapa(etapa, params), deps)


def _chave_corpus_completa(etapas: dict[str, Etapa], etapa: Etapa, docs: list[Documento], params: dict,
                           db: Session) -> str:
    """Chave de uma etapa de corpus: hashes dos documentos + parâmetros relevantes + chaves das dependências."""
    deps: list[str] = []
    for nome in etapa.depende_de:
        dep = etapas.get(nome)
        if dep is None:
            continue
        if dep.escopo == "documento":
            deps.extend(_chave_doc_completa(etapas, dep, d, params) for d in docs)
        else:
            deps.append(_chave_corpus_completa(etapas, dep, docs, params, db))
    if etapa.entrada_extra is not None:
        deps.append(str(etapa.entrada_extra(db)))
    return chave_corpus(etapa, [d.hash_sha256 for d in docs], hash_params_da_etapa(etapa, params), tuple(deps))


def _ja_executada(db: Session, etapa: str, alvo: str, hash_entrada: str) -> bool:
    ultima = db.scalars(
        select(Execucao)
        .where(Execucao.etapa == etapa, Execucao.alvo == alvo)
        .order_by(Execucao.id.desc())
        .limit(1)
    ).first()
    return ultima is not None and ultima.status in ("ok", "pulado") and ultima.hash_entrada == hash_entrada


def _texto(resultado) -> str | None:
    if resultado is None:
        return None
    if isinstance(resultado, str):
        return resultado
    return json.dumps(resultado, ensure_ascii=False)


def _rodar(ctx: ContextoExecucao, etapa: Etapa, alvo: str, hash_entrada: str | None, args: tuple, rotulo: str = "") -> Execucao:
    """Executa a função da etapa e registra a execução (ok ou erro)."""
    db = ctx.db
    execucao = Execucao(etapa=etapa.nome, alvo=alvo, iniciado_em=agora(), hash_entrada=hash_entrada, status="ok")
    try:
        resultado = etapa.funcao(ctx, *args)
        execucao.mensagem = _texto(resultado) if not rotulo else _texto({"documento": rotulo, "resultado": resultado})
    except Exception as exc:  # a falha de um documento não derruba o pipeline
        db.rollback()
        execucao.status = "erro"
        execucao.mensagem = f"{rotulo + ': ' if rotulo else ''}{type(exc).__name__}: {exc}"
    execucao.finalizado_em = agora()
    db.add(execucao)
    db.commit()
    return execucao


def _pular(db: Session, etapa: Etapa, alvo: str, hash_entrada: str, rotulo: str = "") -> Execucao:
    agora_ = agora()
    execucao = Execucao(
        etapa=etapa.nome,
        alvo=alvo,
        iniciado_em=agora_,
        finalizado_em=agora_,
        hash_entrada=hash_entrada,
        status="pulado",
        mensagem=(f"{rotulo}: " if rotulo else "") + "sem mudanças (cache)",
    )
    db.add(execucao)
    db.commit()
    return execucao


def executar_pipeline(db: Session, pasta_projeto: Path, somente: list[str] | None = None,
                      progresso: Callable[[dict], None] | None = None) -> dict:
    """Roda as etapas registradas em ordem e devolve um resumo.

    ``somente`` limita a execução às etapas com esses nomes.
    ``progresso`` (opcional) recebe dicts: ``{"evento": "etapa", "nome", "escopo", "total"}`` ao iniciar cada
    etapa e ``{"evento": "item", "nome", "status"}`` a cada execução registrada (ok/pulado/erro).
    A API síncrona e o valor devolvido não mudam; o callback não pode derrubar o pipeline.
    """
    def avisar(evento: dict) -> None:
        if progresso is not None:
            try:
                progresso(evento)
            except Exception:  # noqa: BLE001  (a interface não pode quebrar o pipeline)
                pass

    projeto = db.scalars(select(Projeto).limit(1)).first()
    if projeto is None:
        raise ValueError("Projeto sem registro no banco.")
    params = svc_parametros.carregar(pasta_projeto)
    hash_params = svc_parametros.hash_parametros(params)
    ctx = ContextoExecucao(
        db=db,
        pasta_projeto=pasta_projeto,
        pasta_origem=Path(projeto.pasta_origem),
        parametros=params,
        hash_parametros=hash_params,
    )

    todas = etapas_registradas()
    por_nome = {e.nome: e for e in todas}
    resumo_etapas = []
    for etapa in todas:
        if somente and etapa.nome not in somente:
            continue
        item = {"etapa": etapa.nome, "escopo": etapa.escopo, "ok": 0, "pulado": 0, "erro": 0, "mensagens": []}

        if etapa.escopo == "corpus":
            docs = _documentos_ativos(db)
            avisar({"evento": "etapa", "nome": etapa.nome, "escopo": etapa.escopo, "total": 1})
            hash_entrada = None
            if etapa.cacheavel:
                hash_entrada = _chave_corpus_completa(por_nome, etapa, docs, params, db)
            if etapa.cacheavel and _ja_executada(db, etapa.nome, "corpus", hash_entrada):
                execucao = _pular(db, etapa, "corpus", hash_entrada)
            else:
                execucao = _rodar(ctx, etapa, "corpus", hash_entrada, ())
            _contar(item, execucao)
            avisar({"evento": "item", "nome": etapa.nome, "status": execucao.status})
        else:
            ativos = _documentos_ativos(db)
            avisar({"evento": "etapa", "nome": etapa.nome, "escopo": etapa.escopo, "total": len(ativos)})
            for doc in ativos:
                hash_entrada = _chave_doc_completa(por_nome, etapa, doc, params)
                alvo = f"doc:{doc.id}"
                if etapa.cacheavel and _ja_executada(db, etapa.nome, alvo, hash_entrada):
                    execucao = _pular(db, etapa, alvo, hash_entrada, doc.arquivo)
                else:
                    execucao = _rodar(ctx, etapa, alvo, hash_entrada, (doc,), rotulo=doc.arquivo)
                _contar(item, execucao)
                avisar({"evento": "item", "nome": etapa.nome, "status": execucao.status})
        resumo_etapas.append(item)

    return {
        "etapas": resumo_etapas,
        "erros": sum(e["erro"] for e in resumo_etapas),
        "versao_parametros": params["versao_parametros"],
        "hash_parametros": hash_params,
        "documentos": _contagem_status(db),
    }


def _documentos_ativos(db: Session) -> list[Documento]:
    return list(
        db.scalars(
            select(Documento).where(condicao_ativo()).order_by(Documento.arquivo)
        )
    )


def _contar(item: dict, execucao: Execucao) -> None:
    item[execucao.status] += 1
    if execucao.mensagem and execucao.status != "pulado":
        item["mensagens"].append(execucao.mensagem)


def _contagem_status(db: Session) -> dict:
    contagem: dict[str, int] = {}
    for (status,) in db.execute(select(Documento.status)):
        contagem[status] = contagem.get(status, 0) + 1
    return contagem
