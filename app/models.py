"""Modelo de dados de CADA projeto (um projeto.sqlite por projeto).

Páginas, seções e tokens não ficam aqui: os tokens irão para arquivos em
cache/ (frentes 3 e 4).
"""
import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def agora() -> datetime.datetime:
    """Data/hora UTC (sem fuso) usada em todos os carimbos."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


STATUS_DOCUMENTO = ("novo", "alterado", "sem_mudanca", "removido", "com_problema", "processado")
STATUS_EXECUCAO = ("ok", "erro", "pulado")
# sugerido: gerado pelo motor, ainda não revisado; revisar: aceito/editado cuja evidência mudou; obsoleto: a regra
# deixou de gerar o comentário (corpus mudou ou regra desativada).
STATUS_COMENTARIO = ("sugerido", "aceito", "editado", "rejeitado", "revisar", "obsoleto")


class Projeto(Base):
    __tablename__ = "projeto"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    pasta_origem: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime.datetime] = mapped_column(default=agora)


class Documento(Base):
    __tablename__ = "documento"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Caminho relativo a pasta_origem (sempre com "/").
    arquivo: Mapped[str] = mapped_column(Text, unique=True, index=True)
    hash_sha256: Mapped[str | None] = mapped_column(String(64))
    tamanho: Mapped[int | None] = mapped_column(Integer)
    modificado_em: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="novo", index=True)
    grupo: Mapped[str | None] = mapped_column(String(100))
    ano: Mapped[int | None] = mapped_column(Integer)
    autor: Mapped[str | None] = mapped_column(String(200))
    # Identificador do estudo (ex.: "001" do nome do arquivo ou id no rsl-ia-system).
    id_estudo: Mapped[str | None] = mapped_column(String(50))
    # Questão de pesquisa (QP1, QP2...), vinda do documentos.csv.
    qp: Mapped[str | None] = mapped_column(Text)
    # Preenchidos pela etapa de conversão (Frente 2): MD em cache/md/<id>.md.
    convertido_em: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    caminho_md: Mapped[str | None] = mapped_column(Text)
    qualidade_json: Mapped[str | None] = mapped_column(Text)
    # OCR por documento (Frente 2.6): None = segue conversao.ocr do projeto; True/False = força para este documento.
    ocr: Mapped[bool | None] = mapped_column(Boolean)
    # "Excluir da análise" (decisão do usuário, reversível): o documento fica no banco, mas sai das etapas e análises.
    excluido: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    criado_em: Mapped[datetime.datetime] = mapped_column(default=agora)
    atualizado_em: Mapped[datetime.datetime] = mapped_column(default=agora, onupdate=agora)

    evidencias: Mapped[list["Evidencia"]] = relationship(back_populates="documento")


class Execucao(Base):
    __tablename__ = "execucao"

    id: Mapped[int] = mapped_column(primary_key=True)
    etapa: Mapped[str] = mapped_column(String(50), index=True)
    # Sobre o que a etapa rodou: "corpus" ou "doc:<id>". O cache compara com a última execução do mesmo alvo.
    alvo: Mapped[str | None] = mapped_column(String(40), index=True)
    iniciado_em: Mapped[datetime.datetime] = mapped_column(default=agora)
    finalizado_em: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    hash_entrada: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(10))
    mensagem: Mapped[str | None] = mapped_column(Text)


class Analise(Base):
    __tablename__ = "analise"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(50), index=True)
    parametros_json: Mapped[str | None] = mapped_column(Text)
    ferramenta_equivalente: Mapped[str | None] = mapped_column(String(200))
    resultado_json: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime.datetime] = mapped_column(default=agora)


class Evidencia(Base):
    __tablename__ = "evidencia"

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documento.id"))
    pagina: Mapped[int | None] = mapped_column(Integer)
    trecho: Mapped[str] = mapped_column(Text)
    # Forma(s) a destacar no trecho (separadas por "|") e posição do token no documento (abre o KWIC ampliado).
    termo: Mapped[str | None] = mapped_column(Text)
    posicao: Mapped[int | None] = mapped_column(Integer)

    documento: Mapped[Documento] = relationship(back_populates="evidencias")


comentario_evidencia = Table(
    "comentario_evidencia",
    Base.metadata,
    Column("comentario_id", ForeignKey("comentario.id"), primary_key=True),
    Column("evidencia_id", ForeignKey("evidencia.id"), primary_key=True),
)


class Comentario(Base):
    __tablename__ = "comentario"

    id: Mapped[int] = mapped_column(primary_key=True)
    regra: Mapped[str] = mapped_column(String(100), index=True)
    texto: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="sugerido")
    revisor: Mapped[str | None] = mapped_column(String(200))
    criado_em: Mapped[datetime.datetime] = mapped_column(default=agora)
    atualizado_em: Mapped[datetime.datetime] = mapped_column(default=agora, onupdate=agora)
    # Frente 8: identidade estável do comentário (ex.: "R07|grupo=cinzenta|termo=labour"), usada para reconciliar
    # a revisão humana com o que o motor gera de novo; NULL em comentários anteriores à Frente 8.
    chave: Mapped[str | None] = mapped_column(String(300), index=True)
    analise_tipo: Mapped[str | None] = mapped_column(String(50), index=True)
    metricas_json: Mapped[str | None] = mapped_column(Text)
    forca: Mapped[float | None] = mapped_column(Float)
    hash_evidencia: Mapped[str | None] = mapped_column(String(64))
    # Último texto gerado pelo motor (o `texto` pode ser o editado ou o aceito antes da última geração).
    texto_original: Mapped[str | None] = mapped_column(Text)
    nota: Mapped[str | None] = mapped_column(Text)
    historico_json: Mapped[str | None] = mapped_column(Text)
    # Frente 14: quem redigiu o texto: "regra" (padrão, motor de regras), "llm" (sugestão de LLM) ou "humano".
    origem: Mapped[str] = mapped_column(String(10), default="regra", server_default="regra", index=True)

    evidencias: Mapped[list[Evidencia]] = relationship(secondary=comentario_evidencia)


STATUS_CODIFICACAO = ("pendente", "codificado", "erro")


class CodificacaoTrecho(Base):
    """15.1 - Trecho codificado por humano (importado da planilha de coleta) e, depois, pelo LLM como 2º codificador."""

    __tablename__ = "codificacao_trecho"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Documento do corpus, quando a fonte da planilha casou com um arquivo (ver services/concordancia/importacao.py).
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documento.id"), index=True)
    registro: Mapped[str | None] = mapped_column(String(100), index=True)  # "ID registro" da planilha
    fonte: Mapped[str | None] = mapped_column(String(100))  # "ID fonte" (ex.: R001)
    fonte_rotulo: Mapped[str | None] = mapped_column(String(300))  # "Kim et al. (2026)"
    aba: Mapped[str | None] = mapped_column(String(100))
    pagina: Mapped[int | None] = mapped_column(Integer)
    secao: Mapped[str | None] = mapped_column(Text)
    texto: Mapped[str] = mapped_column(Text)
    traducao: Mapped[str | None] = mapped_column(Text)
    codigo_humano: Mapped[str | None] = mapped_column(String(50), index=True)
    tema_humano: Mapped[str | None] = mapped_column(String(200))
    codigo_llm: Mapped[str | None] = mapped_column(String(50), index=True)
    justificativa_llm: Mapped[str | None] = mapped_column(Text)
    confianca: Mapped[float | None] = mapped_column(Float)
    modelo: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(15), default="pendente", index=True)
    resposta_bruta: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime.datetime] = mapped_column(default=agora)
    atualizado_em: Mapped[datetime.datetime] = mapped_column(default=agora, onupdate=agora)
