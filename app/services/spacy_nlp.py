"""4.5 - Classes gramaticais (POS) e entidades nomeadas (NER) com spaCy, opcional.

spaCy **não é dependência obrigatória**: ``requirements-spacy.txt`` e ``instalar_spacy.bat`` instalam o pacote e os
modelos pequenos ``en_core_web_sm`` e ``pt_core_news_sm`` (espanhol não tem modelo aqui: documentos em ``es`` seguem sem
POS/NER e com a lematização padrão). Sem o spaCy (ou sem o modelo do idioma) nada quebra: as etapas registram "não
instalado" e as telas escondem os filtros.

Arquivo lateral ``cache/spacy/<id>.json`` (``cache/tokens`` **não** é reescrito, como nos termos compostos e nos segmentos)::

    {"formato": 1, "modelo": "en_core_web_sm", "versao": "3.8.0", "idioma": "en", "n": 15234, "assinatura": "<sha1>",
     "pos_tabela": ["NOUN", "VERB", ...],         # UPOS (Universal Dependencies)
     "pos":  [0, 1, ...],                         # índice em pos_tabela por token (-1 = não alinhado)
     "lema": ["agent", "", ...],                  # lema do spaCy (minúsculo) só onde o token coincide com um token do spaCy
     "ents": [{"tipo": "ORG", "texto": "OpenAI", "inicio_token": 12, "fim_token": 12, "bloco": 3, "pagina": 2}, ...]}

Alinhamento: os tokens do Raio-X (``tokenizacao.py``) e os do spaCy diferem (hífens, apóstrofos). Cada token do Raio-X
recebe a classe do token do spaCy que o cobre (o último, se cobrir vários: ``multi-agent`` -> classe de ``agent``) e só
recebe o **lema do spaCy** quando coincide exatamente com um token do spaCy; senão mantém o lema da simplemma. A
``assinatura`` (modelo + formas + deslocamentos) diz se o arquivo ainda corresponde ao arquivo de tokens.

Lematização "spacy" (``parametros.lematizacao.metodo``): parte do resultado da simplemma (``Lematizador``) e troca o lema pelo do
spaCy nos tokens que coincidem, **exceto** exceções do projeto/padrão, siglas, compostos com hífen e contrações
(que seguem as regras da 4.1) e nomes próprios que o spaCy deixa sem lematizar ("Models" em título: vale a simplemma). O padrão continua ``simplemma``.

Classes aceitas nos filtros (UPOS): NOUN, PROPN, VERB, AUX, ADJ, ADV, ... Atalhos: ``substantivos`` = NOUN+PROPN,
``adjetivos`` = ADJ, ``verbos`` = VERB (sem AUX), ``plenas`` = NOUN+PROPN+ADJ+VERB (as "formas ativas" do IRaMuTeQ).
"""
import bisect
import hashlib
import importlib.util
import json
import time
from pathlib import Path

from app.services.tokenizacao import normalizar

FORMATO = 1
MODELOS = {"en": "en_core_web_sm", "pt": "pt_core_news_sm"}
ATALHOS = {"substantivos": ["NOUN", "PROPN"], "adjetivos": ["ADJ"], "verbos": ["VERB"], "plenas": ["NOUN", "PROPN", "ADJ", "VERB"]}
UPOS = ("ADJ", "ADP", "ADV", "AUX", "CCONJ", "DET", "INTJ", "NOUN", "NUM", "PART", "PRON", "PROPN", "PUNCT", "SCONJ", "SYM", "VERB", "X")
TIPOS_ENTIDADE_PADRAO = ("ORG", "PERSON", "GPE")
MENSAGEM_NAO_INSTALADO = "spaCy não instalado (execute instalar_spacy.bat)"

_NLP: dict[str, object] = {}


def spacy_instalado() -> bool:
    return importlib.util.find_spec("spacy") is not None


def modelo_instalado(idioma: str) -> bool:
    nome = MODELOS.get(idioma)
    return bool(nome) and spacy_instalado() and importlib.util.find_spec(nome) is not None


def status() -> dict:
    """Situação para a tela: pacote, versão e modelos por idioma."""
    versao = None
    if spacy_instalado():
        try:
            import spacy
            versao = spacy.__version__
        except Exception:  # noqa: BLE001 - instalação quebrada conta como não instalado
            versao = None
    return {"instalado": versao is not None, "versao": versao,
            "modelos": {i: {"nome": n, "instalado": modelo_instalado(i)} for i, n in MODELOS.items()},
            "mensagem": None if versao else MENSAGEM_NAO_INSTALADO}


def opcoes(parametros: dict | None) -> dict:
    """Bloco ``spacy`` de parametros.json: ``pos_ner`` (padrão: ligado se instalado)."""
    p = (parametros or {}).get("spacy") or {}
    return {"pos_ner": bool(p.get("pos_ner", True))}


def lematizacao_spacy_pedida(parametros: dict | None) -> bool:
    return str(((parametros or {}).get("lematizacao") or {}).get("metodo", "simplemma")).lower() == "spacy"


def carregar_modelo(idioma: str):
    """Pipeline do spaCy do idioma (sem o analisador sintático: não é usado), em cache no processo."""
    nlp = _NLP.get(idioma)
    if nlp is None:
        import spacy
        nlp = spacy.load(MODELOS[idioma], exclude=["parser", "senter"])
        nlp.max_length = 3_000_000
        _NLP[idioma] = nlp
    return nlp


def caminho_sidecar(pasta_projeto: Path, documento_id: int) -> Path:
    return pasta_projeto / "cache" / "spacy" / f"{documento_id}.json"


def ler_sidecar(pasta_projeto: Path, documento_id: int) -> dict | None:
    c = caminho_sidecar(pasta_projeto, documento_id)
    return json.loads(c.read_text(encoding="utf-8")) if c.is_file() else None


def assinatura(modelo: str, tk: dict) -> str:
    h = hashlib.sha1(modelo.encode("utf-8"))
    h.update(str(tk["n"]).encode())
    h.update("\x1f".join(tk["forma"]).encode("utf-8"))
    h.update(",".join(map(str, tk["inicio"])).encode())
    return h.hexdigest()


def anotar(blocos: list[dict], tk: dict, idioma: str) -> dict:
    """Roda o spaCy sobre os blocos e alinha POS, lema e entidades aos tokens ``tk``. Levanta RuntimeError sem modelo."""
    if not modelo_instalado(idioma):
        raise RuntimeError(f"Modelo do spaCy indisponível para o idioma '{idioma}'.")
    import spacy
    nlp = carregar_modelo(idioma)
    n = tk["n"]
    pos_tabela: list[str] = []
    indice: dict[str, int] = {}
    pos = [-1] * n
    lema = [""] * n
    ents: list[dict] = []
    por_bloco: dict[int, list[int]] = {}
    for i, b in enumerate(tk["bloco"]):
        por_bloco.setdefault(b, []).append(i)
    ordem = sorted(por_bloco)
    textos = [blocos[b]["texto"] for b in ordem]
    for b, doc in zip(ordem, nlp.pipe(textos, batch_size=16)):
        toks = por_bloco[b]
        inicios_sp = [t.idx for t in doc]
        for i in toks:
            a, z = tk["inicio"][i], tk["fim"][i]
            j = bisect.bisect_right(inicios_sp, z - 1) - 1  # último token do spaCy que começa antes do fim do nosso
            if j < 0:
                continue
            t = doc[j]
            if t.idx + len(t.text) <= a:
                continue  # sem sobreposição
            p = t.pos_ or "X"
            if p not in indice:
                indice[p] = len(pos_tabela)
                pos_tabela.append(p)
            pos[i] = indice[p]
            if t.idx == a and t.idx + len(t.text) == z:
                lema[i] = normalizar(t.lemma_)
        inicios_nossos = [tk["inicio"][i] for i in toks]
        for e in doc.ents:
            k0 = bisect.bisect_left(inicios_nossos, e.start_char)
            k1 = bisect.bisect_left(inicios_nossos, e.end_char) - 1
            if k0 >= len(toks) or k1 < k0:
                continue
            i0, i1 = toks[k0], toks[k1]
            ents.append({"tipo": e.label_, "texto": " ".join(e.text.split()), "inicio_token": i0, "fim_token": i1,
                         "bloco": b, "pagina": tk["pagina"][i0]})
    modelo = MODELOS[idioma]
    return {"formato": FORMATO, "modelo": modelo, "versao": spacy.__version__, "idioma": idioma, "n": n,
            "assinatura": assinatura(modelo, tk), "pos_tabela": pos_tabela, "pos": pos, "lema": lema, "ents": ents}


def gravar_sidecar(pasta_projeto: Path, documento_id: int, ann: dict) -> None:
    c = caminho_sidecar(pasta_projeto, documento_id)
    c.parent.mkdir(parents=True, exist_ok=True)
    c.write_text(json.dumps(ann, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")


def sidecar_valido(pasta_projeto: Path, documento_id: int, tk: dict, idioma: str) -> dict | None:
    """O arquivo lateral atual, se corresponde ao arquivo de tokens (mesma assinatura); senão ``None``."""
    ann = ler_sidecar(pasta_projeto, documento_id)
    if ann and ann.get("assinatura") == assinatura(MODELOS.get(idioma, ""), tk):
        return ann
    return None


def aplicar_lemas(tk: dict, ann: dict, lematizador) -> int:
    """Troca em ``tk["lema"]`` o lema da simplemma pelo do spaCy (regras no docstring). Devolve quantos lemas mudaram."""
    mudou = 0
    tabela = ann["pos_tabela"]
    for i, ls in enumerate(ann["lema"]):
        if not ls:
            continue
        norm, forma = tk["norm"][i], tk["forma"][i]
        if ann["pos"][i] >= 0 and tabela[ann["pos"][i]] == "PROPN" and ls == norm and tk["lema"][i] != norm:
            continue  # nome próprio: o spaCy não lematiza ("Models", "Tasks" em título); vale a simplemma
        if (lematizador._excecao(norm) is not None or lematizador._eh_sigla(forma, norm) or "-" in norm or "'" in norm
                or not lematizador.ativa):
            continue
        if tk["lema"][i] != ls:
            tk["lema"][i] = ls
            mudou += 1
    return mudou


def classes_do_documento(ann: dict | None) -> list[str] | None:
    """POS por token como lista de strings ("" = não alinhado), ou ``None`` sem arquivo lateral."""
    if not ann:
        return None
    tabela = ann["pos_tabela"]
    return [tabela[p] if p >= 0 else "" for p in ann["pos"]]


def expandir_classes(classes) -> frozenset[str]:
    """Lista de classes/atalhos ("substantivos", "NOUN", ...) -> conjunto de UPOS. Levanta ValueError se inválida."""
    saida: set[str] = set()
    for c in classes or []:
        c = str(c).strip()
        if not c:
            continue
        if c.lower() in ATALHOS:
            saida.update(ATALHOS[c.lower()])
        elif c.upper() in UPOS:
            saida.add(c.upper())
        else:
            raise ValueError(f"Classe gramatical inválida '{c}': use {', '.join(UPOS)} ou {', '.join(ATALHOS)}.")
    return frozenset(saida)


def medir(idioma: str, texto: str = "The founders built an agentic startup with OpenAI in London. " * 200) -> dict:
    """Pequeno teste de velocidade (palavras por segundo) para a documentação."""
    nlp = carregar_modelo(idioma)
    t = time.time()
    doc = nlp(texto)
    dt = time.time() - t
    return {"palavras": len(doc), "segundos": round(dt, 3), "palavras_por_s": int(len(doc) / dt) if dt else None}


def lematizar_com_spacy(pasta_projeto: Path, documento_id: int, blocos: list[dict], dados: dict, idioma: str, lematizador) -> dict:
    """Usado pela etapa ``linguistica`` com ``lematizacao.metodo = "spacy"``: anota, grava o arquivo lateral e troca os lemas
    de ``dados`` (arrays de tokens, ainda sem gravar). Devolve o bloco ``lematizacao`` complementar (metodo efetivo e motivo)."""
    if not modelo_instalado(idioma):
        motivo = MENSAGEM_NAO_INSTALADO if not spacy_instalado() else f"modelo {MODELOS.get(idioma, 'do idioma')} não instalado"
        return {"metodo": "simplemma", "solicitado": "spacy", "motivo": motivo}
    ann = anotar(blocos, dados, idioma)
    gravar_sidecar(pasta_projeto, documento_id, ann)
    return {"metodo": "spacy", "modelo": ann["modelo"], "lemas_trocados": aplicar_lemas(dados, ann, lematizador)}
