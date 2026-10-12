"""8.1 - Leitura e validação do catálogo de regras (catalogo.yaml) e renderização dos modelos em pt-BR.

O catálogo é editável sem programar. Erros (YAML inválido, regra sem campo, limiar de tipo errado, campo
inexistente no modelo) levantam ``CatalogoInvalido`` com a regra e o campo na mensagem, para o usuário corrigir.
"""
import hashlib
import os
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

CATALOGO_PADRAO = Path(__file__).with_name("catalogo.yaml")
ANALISES = ("resumo", "frequencias", "tendencias", "keyness", "colocacoes")
_TROCA_PTBR = str.maketrans({",": ".", ".": ","})


class CatalogoInvalido(ValueError):
    """Catálogo ou regra inválidos (mensagem em português, pronta para mostrar ao usuário)."""


def caminho_catalogo() -> Path:
    """Catálogo em uso: ``RAIOX_CATALOGO`` (testes ou instalação própria) ou o padrão do pacote."""
    return Path(os.getenv("RAIOX_CATALOGO") or CATALOGO_PADRAO)


def hash_catalogo(caminho: Path | None = None) -> str:
    """Hash do arquivo (entra na chave de cache da etapa: editar o YAML regenera os comentários)."""
    caminho = caminho or caminho_catalogo()
    try:
        return hashlib.sha256(caminho.read_bytes()).hexdigest()
    except OSError:
        return "catalogo-ausente"


# ---------- renderização pt-BR ----------

class _FormatadorPtBR(string.Formatter):
    """Como ``str.format``, mas inteiros e decimais saem com ponto de milhar e vírgula decimal."""

    def format_field(self, value, format_spec):
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, (int, float)):
            padrao = ",d" if isinstance(value, int) else ",.2f"
            if re.fullmatch(r"\.?\d*[fd]", format_spec or ""):  # ".1f" e "d" ganham o ponto de milhar
                format_spec = "," + format_spec
            return format(value, format_spec or padrao).translate(_TROCA_PTBR)
        return format(value, format_spec)


_FORMATADOR = _FormatadorPtBR()


def renderizar(modelo: str, valores: dict) -> str:
    return _FORMATADOR.vformat(modelo, (), valores)


def campos_do_modelo(modelo: str) -> set[str]:
    return {nome.split(".")[0].split("[")[0] for _, nome, _, _ in string.Formatter().parse(modelo) if nome}


def valor_p_texto(p: float) -> str:
    """"p < 0,001" ou "p = 0,004" (sem notação científica no texto corrido)."""
    return "p < 0,001" if p < 0.001 else f"p = {p:.3f}".replace(".", ",")


# ---------- tipos ----------

@dataclass
class Regra:
    id: str
    avaliador: str
    analise: str
    descricao: str
    condicao: dict[str, Any]
    modelo: str
    max_comentarios: int
    evidencias: int
    ativa: bool


@dataclass
class Candidato:
    """Comentário em potencial, antes da reconciliação com a revisão humana."""

    regra: Regra
    chave: str
    valores: dict[str, Any]  # campos do modelo
    metricas: dict[str, Any]
    forca: float
    # n -> evidências (dicts documento_id/pagina/trecho/termo/posicao); chamado só para os selecionados.
    buscar_evidencias: Callable[[int], list[dict]]
    cota: str = ""  # max_comentarios vale por cota (ex.: por grupo)
    texto: str = ""
    evidencias: list[dict] = field(default_factory=list)
    hash_evidencia: str = ""


# ---------- leitura ----------

def _tipo_ok(valor, tipo) -> bool:
    if isinstance(valor, bool):
        return tipo is bool
    if tipo is float:
        return isinstance(valor, (int, float))
    return isinstance(valor, tipo)


def _validar_condicao(rid: str, spec: dict, condicao: Any) -> dict:
    if condicao is None:
        condicao = {}
    if not isinstance(condicao, dict):
        raise CatalogoInvalido(f"Regra {rid}: 'condicao' deve ser uma lista de limiares (nome: valor).")
    desconhecidos = sorted(set(condicao) - set(spec["params"]))
    if desconhecidos:
        raise CatalogoInvalido(
            f"Regra {rid}: limiar desconhecido em 'condicao': {', '.join(desconhecidos)}. "
            f"Válidos: {', '.join(spec['params']) or 'nenhum'}.")
    final = {}
    for nome, (tipo, padrao, minimo) in spec["params"].items():
        valor = condicao.get(nome, padrao)
        if not _tipo_ok(valor, tipo):
            raise CatalogoInvalido(
                f"Regra {rid}: o limiar '{nome}' deve ser {'inteiro' if tipo is int else 'numérico'} (recebido: {valor!r}).")
        if minimo is not None and valor < minimo:
            raise CatalogoInvalido(f"Regra {rid}: o limiar '{nome}' deve ser >= {minimo} (recebido: {valor}).")
        final[nome] = float(valor) if tipo is float else valor
    return final


def _validar_modelo(rid: str, spec: dict, modelo: str) -> None:
    try:
        usados = campos_do_modelo(modelo)
    except ValueError as exc:
        raise CatalogoInvalido(f"Regra {rid}: modelo mal formado ({exc}).") from exc
    invalidos = sorted(usados - set(spec["campos"]))
    if invalidos:
        raise CatalogoInvalido(
            f"Regra {rid}: o modelo usa campos inexistentes: {', '.join('{' + c + '}' for c in invalidos)}. "
            f"Campos válidos: {', '.join('{' + c + '}' for c in spec['campos'])}.")
    try:
        renderizar(modelo, spec["campos"])  # valores de exemplo: pega formatação incompatível com o tipo
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise CatalogoInvalido(f"Regra {rid}: o modelo não pôde ser preenchido ({exc}).") from exc


def _inteiro(rid: str, item: dict, campo: str, padrao: int) -> int:
    valor = item.get(campo, padrao)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise CatalogoInvalido(f"Regra {rid}: '{campo}' deve ser um número inteiro >= 0 (recebido: {valor!r}).")
    return valor


def interpretar(dados: Any) -> list[Regra]:
    """Valida o conteúdo já lido do YAML e devolve as regras (ativas e inativas)."""
    from app.services.regras.avaliadores import AVALIADORES

    if not isinstance(dados, dict) or not isinstance(dados.get("regras"), list):
        raise CatalogoInvalido("Catálogo inválido: esperado um item 'regras' com a lista de regras.")
    regras: list[Regra] = []
    vistos: set[str] = set()
    for pos, item in enumerate(dados["regras"], start=1):
        if not isinstance(item, dict):
            raise CatalogoInvalido(f"Regra nº {pos}: deve ser um bloco com id, analise, modelo etc.")
        rid = str(item.get("id") or "").strip()
        if not rid:
            raise CatalogoInvalido(f"Regra nº {pos}: falta o campo 'id'.")
        if rid in vistos:
            raise CatalogoInvalido(f"Regra {rid}: id repetido no catálogo.")
        vistos.add(rid)
        for obrigatorio in ("analise", "modelo"):
            if not item.get(obrigatorio):
                raise CatalogoInvalido(f"Regra {rid}: falta o campo '{obrigatorio}'.")
        analise = str(item["analise"])
        if analise not in ANALISES:
            raise CatalogoInvalido(f"Regra {rid}: analise '{analise}' inválida. Use: {', '.join(ANALISES)}.")
        avaliador = str(item.get("avaliador") or rid)
        spec = AVALIADORES.get(avaliador)
        if spec is None:
            raise CatalogoInvalido(
                f"Regra {rid}: não há lógica para '{avaliador}'. Use 'avaliador: <id>' com um de: {', '.join(AVALIADORES)}.")
        if spec["analise"] != analise:
            raise CatalogoInvalido(
                f"Regra {rid}: a lógica {avaliador} trabalha com a análise '{spec['analise']}', não '{analise}'.")
        ativa = item.get("ativa", True)
        if not isinstance(ativa, bool):
            raise CatalogoInvalido(f"Regra {rid}: 'ativa' deve ser true ou false.")
        modelo = str(item["modelo"])
        _validar_modelo(rid, spec, modelo)
        regras.append(Regra(
            id=rid, avaliador=avaliador, analise=analise, descricao=str(item.get("descricao") or ""),
            condicao=_validar_condicao(rid, spec, item.get("condicao")), modelo=modelo,
            max_comentarios=_inteiro(rid, item, "max_comentarios", 5),
            evidencias=_inteiro(rid, item, "evidencias", 3), ativa=ativa))
    return regras


def carregar_catalogo(caminho: Path | None = None) -> list[Regra]:
    caminho = caminho or caminho_catalogo()
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogoInvalido(f"Catálogo de regras não encontrado ou ilegível: {caminho} ({exc.strerror or exc}).") from exc
    try:
        dados = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        raise CatalogoInvalido(f"O catálogo {caminho.name} não é um YAML válido: {exc}") from exc
    return interpretar(dados)
