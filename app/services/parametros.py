"""1.4 - parametros.json versionado dentro de cada projeto.

Salvar com conteúdo diferente incrementa "versao_parametros" e guarda a versão
anterior em parametros_historico/parametros_v<N>.json.
"""
import copy
import hashlib
import json
import shutil
from pathlib import Path

ARQUIVO = "parametros.json"
HISTORICO = "parametros_historico"

PADRAO: dict = {
    "versao_parametros": 1,
    "idioma": ["en", "pt"],
    # excecoes: {palavra: lema} sobrepõe a lista padrão de exceções (app/services/tokenizacao.py).
    "lematizacao": {"ativa": True, "metodo": "simplemma", "excecoes": {}},
    "palavras_vazias": {"en": True, "pt": True, "es": True, "academico": True, "proprias": []},
    "conversao": {"ocr": False},  # repassado ao Docling (OCR de PDFs escaneados: Frente 2.6)
    "excluir_referencias": True,
    # Seções que saem da contagem quando excluir_referencias é verdadeiro (Frente 3.2).
    "excluir_secoes": ["referencias", "apendice", "agradecimentos", "declaracoes"],
    # 3.4 detector de segmentos de ruído (autores, tabelas, cláusulas repetidas): ``excluir_ruido`` tira os marcados da
    # CHD, da similitude e dos n-gramas; limiares em ``ruido`` (padrões e significado em services/ruido.py).
    "limpeza": {"excluir_ruido": True, "ruido": {}},
    "kwic_janela": 10,
    "colocacao_janela": 5,
    "segmento_palavras": 40,
    # 4.3: "lista"/"bloqueados" guardam sequências de lemas separadas por espaço ("agentic ai").
    "termos_compostos": {"ativa": True, "automaticos": True, "n_max": 3, "min_freq": 10, "min_docs": 3,
                         "max_automaticos": 200, "lista": [], "bloqueados": [],
                         "internas_permitidas": ["of", "on", "for", "in", "to", "de", "da", "do"],
                         "excluir_regex": [r"\b(\w+) \1\b", r"^(\w{1,2} )+\w{1,2}$"], "max_concentracao": 0.8},
    # 7.1 CHD de Reinert (etapa reinert): classes terminais, freq. mínima das formas ativas, classificação dupla e os
    # dois tamanhos de UC (palavras); min_classe 0 = automático; max_formas = formas ativas mais frequentes.
    "reinert": {"classes": 10, "min_freq": 3, "dupla": False, "tamanhos": [40, 60], "min_classe": 0, "max_formas": 3000},
    # 7.2 similitude (etapa similitude): formas mais frequentes, índice e árvore máxima (False = rede top-k).
    "similitude": {"n_formas": 60, "indice": "coocorrencia", "arvore": True},
    # 15.7 tópicos (etapa topicos): modelo lda/nmf/lsa, nº de tópicos, unidade documento/segmento, semente e iterações.
    "topicos": {"modelo": "lda", "k": 8, "unidade": "documento", "semente": 42, "iteracoes": 1000},
    # 15.3-15.5 raio-x por documento (etapa documento_extra): legibilidade, palavras-chave (RAKE/YAKE/TextRank) e
    # resumo extrativo (TextRank/LexRank/MMR); None em min_freq = automático (2 em documentos de 1.500+ palavras).
    "documento_extra": {"resumo_frases": 5, "n_palavras_chave": 10, "silabas_en": "heuristica",
                        "rake": {"max_palavras": 4, "min_freq": None},
                        "yake": {"ngrama_max": 3, "dedup": 0.8, "min_freq": None},
                        "textrank": {"janela": 4, "max_palavras": 4, "min_freq": None},
                        "sumarizacao": {"lambda": 0.7, "limiar": 0.1}},
    # 15.6 estilometria (etapa estilometria): nº de palavras mais frequentes (formas, com palavras vazias), culling (%),
    # distância (delta_classico/argamon/eder/eder_simples/cosine_delta/cosseno) e unidade documento/amostra (tokens).
    "estilometria": {"mfw": 100, "culling": 0, "distancia": "delta_classico", "unidade": "documento", "tamanho_amostra": 2000},
}


def parametros_padrao() -> dict:
    return copy.deepcopy(PADRAO)


def _completar(dados: dict) -> dict:
    """Preenche chaves ausentes com o padrão (compatibilidade com versões antigas)."""
    base = parametros_padrao()
    for chave, valor in dados.items():
        if isinstance(valor, dict) and isinstance(base.get(chave), dict):
            base[chave].update(valor)
        else:
            base[chave] = valor
    return base


def _escrever(caminho: Path, dados: dict) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar(pasta_projeto: Path) -> dict:
    caminho = pasta_projeto / ARQUIVO
    if not caminho.is_file():
        return parametros_padrao()
    return _completar(json.loads(caminho.read_text(encoding="utf-8")))


def _conteudo(dados: dict) -> dict:
    return {k: v for k, v in dados.items() if k != "versao_parametros"}


def salvar(pasta_projeto: Path, novos: dict) -> dict:
    """Grava os parâmetros. Se o conteúdo mudou, sobe a versão e arquiva a anterior."""
    pasta_projeto.mkdir(parents=True, exist_ok=True)
    caminho = pasta_projeto / ARQUIVO
    novos = _completar({k: v for k, v in novos.items() if k != "versao_parametros"})
    if not caminho.is_file():
        novos["versao_parametros"] = 1
        _escrever(caminho, novos)
        return novos

    atuais = carregar(pasta_projeto)
    if _conteudo(atuais) == _conteudo(novos):
        return atuais  # nada mudou: mantém a versão

    historico = pasta_projeto / HISTORICO
    historico.mkdir(exist_ok=True)
    shutil.copyfile(caminho, historico / f"parametros_v{atuais['versao_parametros']}.json")
    novos["versao_parametros"] = int(atuais["versao_parametros"]) + 1
    _escrever(caminho, novos)
    return novos


def listar_historico(pasta_projeto: Path) -> list[int]:
    historico = pasta_projeto / HISTORICO
    if not historico.is_dir():
        return []
    versoes = []
    for f in historico.glob("parametros_v*.json"):
        try:
            versoes.append(int(f.stem.removeprefix("parametros_v")))
        except ValueError:
            pass
    return sorted(versoes)


def hash_parametros(dados: dict, chaves: list[str] | None = None) -> str:
    """sha256 do conteúdo (JSON estável, sem o número da versão) - usado nas chaves de cache.

    ``chaves`` restringe o hash às chaves de primeiro nível indicadas (parâmetros relevantes de
    uma etapa); ``None`` = todos os parâmetros.
    """
    conteudo = _conteudo(dados)
    if chaves is not None:
        conteudo = {k: conteudo.get(k) for k in sorted(set(chaves))}
    texto = json.dumps(conteudo, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
