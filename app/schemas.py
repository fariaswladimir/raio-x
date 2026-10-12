"""Esquemas Pydantic da API."""
import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjetoCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    pasta_origem: str = Field(min_length=1)


class ProjetoOut(BaseModel):
    slug: str
    nome: str
    pasta_origem: str
    criado_em: datetime.datetime | None = None
    versao_parametros: int | None = None


class LematizacaoParametros(BaseModel):
    ativa: bool = True
    metodo: str = "simplemma"
    excecoes: dict[str, str] = {}  # palavra -> lema (ex.: {"llms": "llm"}); sobrepõe a lista padrão


class PalavrasVaziasParametros(BaseModel):
    en: bool = True
    pt: bool = True
    es: bool = True
    academico: bool = True
    proprias: list[str] = []


class ConversaoParametros(BaseModel):
    ocr: bool = False


class TermosCompostosParametros(BaseModel):
    ativa: bool = True
    automaticos: bool = True
    n_max: int = Field(default=3, ge=2, le=6)
    min_freq: int = Field(default=10, ge=1)
    min_docs: int = Field(default=3, ge=1)
    max_automaticos: int = Field(default=200, ge=0, le=5000)
    lista: list[str] = []
    bloqueados: list[str] = []
    internas_permitidas: list[str] = ["of", "on", "for", "in", "to", "de", "da", "do"]
    excluir_regex: list[str] = [r"\b(\w+) \1\b", r"^(\w{1,2} )+\w{1,2}$"]
    max_concentracao: float = Field(default=0.8, gt=0, le=1)


class ReinertParametros(BaseModel):
    """7.1 CHD de Reinert (etapa reinert)."""

    classes: int = Field(default=10, ge=2, le=30)
    min_freq: int = Field(default=3, ge=1)
    dupla: bool = False
    tamanhos: list[int] = Field(default=[40, 60], min_length=2, max_length=2)
    min_classe: int = Field(default=0, ge=0)
    max_formas: int = Field(default=3000, ge=0, le=50000)


class SimilitudeParametros(BaseModel):
    """7.2 similitude / rede de coocorrência (etapa similitude)."""

    n_formas: int = Field(default=60, ge=3, le=300)
    indice: Literal["coocorrencia", "jaccard", "cosseno", "pmi"] = "coocorrencia"
    arvore: bool = True


class TopicosParametros(BaseModel):
    """15.7 tópicos (etapa topicos)."""

    modelo: Literal["lda", "nmf", "lsa"] = "lda"
    k: int = Field(default=8, ge=2, le=40)
    unidade: Literal["documento", "segmento"] = "documento"
    semente: int = 42
    iteracoes: int = Field(default=1000, ge=10, le=20000)


class LimpezaParametros(BaseModel):
    """3.4 detector de segmentos de ruído: ``excluir_ruido`` e limiares opcionais (chaves de services/ruido.py PADRAO)."""

    excluir_ruido: bool = True
    ruido: dict[str, float] = {}


class ParametrosIn(BaseModel):
    """Parâmetros editáveis. A versão é controlada pelo servidor."""

    idioma: list[str] = ["en", "pt"]
    lematizacao: LematizacaoParametros = LematizacaoParametros()
    palavras_vazias: PalavrasVaziasParametros = PalavrasVaziasParametros()
    conversao: ConversaoParametros = ConversaoParametros()
    excluir_referencias: bool = True
    excluir_secoes: list[str] = ["referencias", "apendice", "agradecimentos", "declaracoes"]
    limpeza: LimpezaParametros = LimpezaParametros()
    kwic_janela: int = Field(default=10, ge=1, le=100)
    colocacao_janela: int = Field(default=5, ge=1, le=100)
    segmento_palavras: int = Field(default=40, ge=5, le=500)
    termos_compostos: TermosCompostosParametros = TermosCompostosParametros()
    reinert: ReinertParametros = ReinertParametros()
    similitude: SimilitudeParametros = SimilitudeParametros()
    topicos: TopicosParametros = TopicosParametros()


class ParametrosOut(ParametrosIn):
    versao_parametros: int
    hash_parametros: str


class DocumentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    arquivo: str
    hash_sha256: str | None = None
    tamanho: int | None = None
    modificado_em: datetime.datetime | None = None
    status: str
    grupo: str | None = None
    ano: int | None = None
    autor: str | None = None
    id_estudo: str | None = None
    qp: str | None = None
    # OCR por documento (None = segue o projeto) e "excluir da análise" (2.6 / 2.5).
    ocr: bool | None = None
    excluido: bool = False
    convertido_em: datetime.datetime | None = None
    caminho_md: str | None = None
    # Derivados de qualidade_json (preenchidos por app/routers/documentos.py).
    paginas: int | None = None
    idioma: str | None = None
    problemas: list[str] = []
    avisos: list[str] = []
    # Derivados da limpeza (Frente 3): "titulo" | "heuristica" | "nenhum" e % do texto que é corpo.
    referencias: str | None = None
    pct_corpo: float | None = None


class DocumentoEditar(BaseModel):
    """Edição manual parcial: só os campos enviados são alterados (null limpa o campo)."""

    grupo: str | None = None
    ano: int | None = Field(default=None, ge=1000, le=2200)
    autor: str | None = None
    id_estudo: str | None = None
    # OCR deste documento: true/false força, null volta a seguir ``conversao.ocr`` do projeto.
    ocr: bool | None = None
    # true tira o documento das etapas e análises; false reinclui (reversível).
    excluido: bool | None = None


class SecaoOut(BaseModel):
    tipo: str
    titulo: str | None = None
    pagina_inicio: int | None = None
    pagina_fim: int | None = None
    palavras: int = 0
    incluir: bool = True


class SecoesOut(BaseModel):
    documento_id: int
    arquivo: str
    secoes: list[SecaoOut]
    estatisticas: dict


class GrupoOut(BaseModel):
    grupo: str | None = None
    documentos: int


class PendenciaOut(BaseModel):
    id: int
    arquivo: str
    status: str
    problemas: list[str] = []
    avisos: list[str] = []
    ocr: bool | None = None
    excluido: bool = False
    # True quando o problema é de texto ausente (escaneado/sem texto): a interface oferece "Reconverter com OCR".
    pode_ocr: bool = False


class ExecucaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    etapa: str
    iniciado_em: datetime.datetime
    finalizado_em: datetime.datetime | None = None
    hash_entrada: str | None = None
    status: str
    mensagem: str | None = None


class ResumoEtapa(BaseModel):
    etapa: str
    escopo: str
    ok: int
    pulado: int
    erro: int
    mensagens: list[str] = []


class ResumoExecucao(BaseModel):
    etapas: list[ResumoEtapa]
    erros: int
    versao_parametros: int
    hash_parametros: str
    documentos: dict[str, int]


class TermoOut(BaseModel):
    termo: str
    freq: int
    por_10k: float
    docs: int


class VocabularioOut(BaseModel):
    por: str
    filtradas: bool
    documentos: int
    tokens: int
    tipos: int
    itens: list[TermoOut]


class TokenOut(BaseModel):
    i: int
    forma: str
    norm: str
    lema: str
    pagina: int | None = None
    secao: str
    incluir: bool
    bloco: int
    offset_inicio: int
    offset_fim: int


class TokensOut(BaseModel):
    documento_id: int
    arquivo: str
    idioma: str | None = None
    lematizacao: dict = {}
    n: int
    inicio: int
    fim: int
    tokens: list[TokenOut]
