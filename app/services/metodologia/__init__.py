"""Catálogo de metodologia: método e referências por análise (fonte única: catalogo.yaml).

``carregar()`` lê e valida o YAML (cache por mtime), expandindo as chaves de ``referencias`` em dicionários
completos. ``marcar_uso_no_projeto()`` acrescenta, para um projeto, quais análises foram usadas e os valores
atuais dos parâmetros. A formatação ABNT/APA/BibTeX está em ``formatos.py``.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from threading import Lock

import yaml

from app.config import RAIZ
from app.services.metodologia import formatos

CAMINHO = Path(__file__).with_name("catalogo.yaml")

STATUS = ("implementado", "parcial", "planejado")
TIPOS_REFERENCIA = ("livro", "artigo", "congresso", "capitulo", "tese", "software", "relatorio", "web", "preprint")
CAMPOS_ANALISE = ("id", "nome", "familia", "o_que_mede", "metrica", "parametros_padrao", "equivale_a",
                  "nao_e_igual_a", "cuidados", "status", "eap_id", "referencias")
DETALHES_VALIDOS = {"volume", "numero", "paginas", "edicao", "local", "editora", "organizadores", "evento", "grau"}
DETECCAO_VALIDA = {"snapshots", "arquivos", "tabelas"}
NOTA_CONFERIR = "conferir antes de citar"


class CatalogoInvalido(ValueError):
    """O catalogo.yaml não passou na validação (a mensagem lista todos os problemas)."""


_cache: dict = {"mtime": None, "dados": None}
_trava = Lock()


def _validar_referencia(chave: str, ref, erros: list[str]) -> None:
    onde = f"referencias.{chave}"
    if not isinstance(ref, dict):
        erros.append(f"{onde}: deve ser um dicionário")
        return
    autores = ref.get("autores")
    if not isinstance(autores, list) or not autores or not all(isinstance(a, str) and a.strip() for a in autores):
        erros.append(f"{onde}: 'autores' deve ser uma lista não vazia de textos")
    if not isinstance(ref.get("ano"), int) or not 1000 <= ref["ano"] <= 2100:
        erros.append(f"{onde}: 'ano' deve ser um inteiro entre 1000 e 2100")
    if not isinstance(ref.get("titulo"), str) or not ref["titulo"].strip():
        erros.append(f"{onde}: 'titulo' é obrigatório")
    if ref.get("tipo") not in TIPOS_REFERENCIA:
        erros.append(f"{onde}: 'tipo' deve ser um de {', '.join(TIPOS_REFERENCIA)}")
    if ref.get("tipo") in ("artigo", "congresso", "capitulo") and not ref.get("veiculo"):
        erros.append(f"{onde}: 'veiculo' é obrigatório para {ref.get('tipo')}")
    detalhes = ref.get("detalhes", {})
    if not isinstance(detalhes, dict) or set(detalhes) - DETALHES_VALIDOS:
        erros.append(f"{onde}: 'detalhes' só aceita {', '.join(sorted(DETALHES_VALIDOS))}")


def _validar_analise(a, i: int, ids: set, chaves_ref: set, erros: list[str]) -> None:
    if not isinstance(a, dict):
        erros.append(f"analises[{i}]: deve ser um dicionário")
        return
    id_ = a.get("id")
    onde = f"analises[{id_ or i}]"
    for campo in CAMPOS_ANALISE:
        if a.get(campo) in (None, "", []) and campo != "referencias":
            erros.append(f"{onde}: campo obrigatório ausente ou vazio: {campo}")
    if not isinstance(id_, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", id_ or ""):
        erros.append(f"{onde}: 'id' deve usar minúsculas, dígitos e _")
    elif id_ in ids:
        erros.append(f"{onde}: id duplicado")
    ids.add(id_)
    if a.get("status") not in STATUS:
        erros.append(f"{onde}: 'status' deve ser um de {', '.join(STATUS)}")
    cuidados = a.get("cuidados")
    if not isinstance(cuidados, list) or not 1 <= len(cuidados) <= 3 or not all(isinstance(c, str) and c for c in cuidados):
        erros.append(f"{onde}: 'cuidados' deve ter de 1 a 3 itens de texto")
    params = a.get("parametros_padrao")
    if not isinstance(params, list) or any(not isinstance(p, dict) or not p.get("nome") or p.get("valor") in (None, "") for p in params or []):
        erros.append(f"{onde}: cada item de 'parametros_padrao' precisa de nome e valor")
    refs = a.get("referencias")
    if not isinstance(refs, list):
        erros.append(f"{onde}: 'referencias' deve ser uma lista")
    else:
        for chave in refs:
            if chave not in chaves_ref:
                erros.append(f"{onde}: referência '{chave}' não existe no pool 'referencias'")
    if a.get("status") == "implementado" and not a.get("modulo") and a.get("familia") != "Referências gerais":
        erros.append(f"{onde}: análise implementada precisa de 'modulo'")
    if a.get("modulo") and not (RAIZ / a["modulo"]).exists():
        erros.append(f"{onde}: modulo '{a['modulo']}' não existe no repositório")
    det = a.get("deteccao", {})
    if not isinstance(det, dict) or set(det) - DETECCAO_VALIDA:
        erros.append(f"{onde}: 'deteccao' só aceita {', '.join(sorted(DETECCAO_VALIDA))}")


def validar(dados) -> None:
    """Levanta CatalogoInvalido com todos os problemas encontrados."""
    erros: list[str] = []
    if not isinstance(dados, dict) or not isinstance(dados.get("analises"), list) or not isinstance(dados.get("referencias"), dict):
        raise CatalogoInvalido("catalogo.yaml deve ter as chaves 'referencias' (dicionário) e 'analises' (lista)")
    for chave, ref in dados["referencias"].items():
        _validar_referencia(str(chave), ref, erros)
    ids: set = set()
    chaves_ref = set(dados["referencias"])
    for i, a in enumerate(dados["analises"]):
        _validar_analise(a, i, ids, chaves_ref, erros)
    if erros:
        raise CatalogoInvalido("catalogo.yaml inválido:\n- " + "\n- ".join(erros))


def _expandir(dados: dict) -> dict:
    pool = {}
    for chave, ref in dados["referencias"].items():
        r = copy.deepcopy(ref)
        r["chave"] = chave
        r["bibtex_chave"] = formatos.chave_bibtex(r)
        pool[chave] = r
    analises = []
    for a in dados["analises"]:
        b = copy.deepcopy(a)
        b["referencias"] = [copy.deepcopy(pool[k]) for k in a.get("referencias", [])]
        b.setdefault("modulo", None)
        b.setdefault("formula", None)
        b.setdefault("deteccao", {})
        analises.append(b)
    familias: list[str] = []
    for a in analises:
        if a["familia"] not in familias:
            familias.append(a["familia"])
    return {"analises": analises, "referencias": pool, "familias": familias}


def carregar() -> dict:
    """Catálogo validado e expandido: {"analises": [...], "referencias": {chave: ref}, "familias": [...]}.

    Devolve uma cópia profunda (o chamador pode alterá-la). Recarrega quando o arquivo muda.
    """
    mtime = CAMINHO.stat().st_mtime_ns
    with _trava:
        if _cache["mtime"] != mtime:
            dados = yaml.safe_load(CAMINHO.read_text(encoding="utf-8"))
            validar(dados)
            _cache.update(mtime=mtime, dados=_expandir(dados))
        return copy.deepcopy(_cache["dados"])


def listar(familia: str | None = None, status: str | None = None) -> list[dict]:
    cat = carregar()["analises"]
    if familia:
        cat = [a for a in cat if a["familia"].lower() == familia.lower()]
    if status:
        cat = [a for a in cat if a["status"] == status.lower()]
    return cat


def obter(id_: str) -> dict | None:
    return next((a for a in carregar()["analises"] if a["id"] == id_), None)


def referencias_de(ids: list[str] | None = None) -> list[dict]:
    """Referências das análises indicadas (todas se vazio), sem duplicatas e em ordem alfabética.

    Cada item traz ``analises`` = ids das análises que a citam. Levanta KeyError para id desconhecido.
    """
    cat = carregar()
    por_id = {a["id"]: a for a in cat["analises"]}
    if ids:
        faltam = [i for i in ids if i not in por_id]
        if faltam:
            raise KeyError(faltam[0])
        escolhidas = [por_id[i] for i in dict.fromkeys(ids)]
    else:
        escolhidas = cat["analises"]
    unicas: dict[str, dict] = {}
    for a in escolhidas:
        for r in a["referencias"]:
            item = unicas.setdefault(r["chave"], {**r, "analises": []})
            item["analises"].append(a["id"])
    return formatos.ordenar(list(unicas.values()))


def texto_referencias(refs: list[dict], formato: str) -> str:
    """Lista de referências em um formato, uma por parágrafo (BibTeX com chaves únicas)."""
    if formato == "bibtex":
        chaves = formatos.chaves_bibtex_unicas(refs)
        return "\n\n".join(formatos.formatar_bibtex(r, c) for r, c in zip(refs, chaves)) + ("\n" if refs else "")
    return "\n\n".join(formatos.formatar(r, formato) for r in refs) + ("\n" if refs else "")


# ---------------------------------------------------------------- uso em um projeto
def _valor_em(dados: dict, caminho: str):
    atual = dados
    for parte in caminho.split("."):
        if not isinstance(atual, dict) or parte not in atual:
            return None
        atual = atual[parte]
    return atual


def _usada(det: dict, pasta: Path, tipos: set[str], tabelas: dict[str, int]) -> list[str]:
    """Evidências de que a análise foi usada no projeto (lista vazia = não usada)."""
    ev = []
    for tipo in det.get("snapshots", []):
        if tipo in tipos:
            ev.append(f"resultado '{tipo}' gravado")
    for rel in det.get("arquivos", []):
        alvo = pasta / rel
        if alvo.is_file() or (alvo.is_dir() and any(alvo.iterdir())):
            ev.append(f"arquivo {rel}")
    for tabela in det.get("tabelas", []):
        if tabelas.get(tabela, 0) > 0:
            ev.append(f"{tabelas[tabela]} registros em '{tabela}'")
    return ev


def marcar_uso_no_projeto(catalogo: list[dict], pasta: Path, parametros: dict, tipos_gravados: set[str],
                          contagens: dict[str, int]) -> list[dict]:
    """Acrescenta a cada análise ``usada_no_projeto``, ``evidencia_de_uso`` e, nos parâmetros que têm
    ``parametro``, ``valor_projeto`` (valor atual do parametros.json) e ``difere_do_padrao``."""
    from app.services import parametros as svc_parametros  # import tardio: evita ciclo na carga

    padrao = svc_parametros.parametros_padrao()
    for a in catalogo:
        ev = _usada(a.get("deteccao", {}), pasta, tipos_gravados, contagens)
        a["usada_no_projeto"] = bool(ev)
        a["evidencia_de_uso"] = ev
        for p in a["parametros_padrao"]:
            caminho = p.get("parametro")
            if caminho:
                atual = _valor_em(parametros, caminho)
                p["valor_projeto"] = atual
                p["difere_do_padrao"] = atual != _valor_em(padrao, caminho)
    return catalogo
