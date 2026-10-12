"""Frente 2 (2.6 OCR por documento, 2.5 duplicatas próximas, excluir da análise) e 3.3 (revisão por amostra).
O conversor do Docling é simulado: nenhum teste aqui exige modelos de OCR."""
import itertools
import random
import sys
from pathlib import Path

import pytest

from app.services.etapas import conversao
from app.services.etapas.qualidade import titulo_normalizado
from app.services.limpeza_texto import corrigir_hifenizacao, limpar_texto

TEXTO_EN = (
    "The study of the effects of the new method on the performance of the teams is that it can be used "
    "for all of the projects in which they were involved, and this is what we would also expect. "
) * 12


def _executar(client, slug):
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return r.json()


def _docs(client, slug):
    return {d["arquivo"]: d for d in client.get(f"/api/projetos/{slug}/documentos").json()}


def _etapa(resumo, nome):
    return next(e for e in resumo["etapas"] if e["etapa"] == nome)


def _novo_projeto(client, pasta, nome="Projeto F26"):
    r = client.post("/api/projetos", json={"nome": nome, "pasta_origem": str(pasta)})
    assert r.status_code == 201, r.text
    return r.json()["slug"]


def _patch(client, slug, doc_id, corpo):
    r = client.patch(f"/api/projetos/{slug}/documentos/{doc_id}", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


def _pendencias(client, slug):
    return {p["arquivo"]: p for p in client.get(f"/api/projetos/{slug}/pendencias").json()}


# ---------- apoio: conversor simulado ----------

class DoclingFalso:
    """Substitui ``conversao._converter_com_docling``: sem OCR o PDF 'escaneado' sai vazio; com OCR sai com texto."""

    def __init__(self, escaneados=("a.pdf",)):
        self.chamadas: list[tuple] = []
        self.escaneados = escaneados
        self.erro_ocr: Exception | None = None

    def __call__(self, origem, ocr, pagina_inteira=False, idioma="en"):
        self.chamadas.append((origem.name, bool(ocr), bool(pagina_inteira), idioma))
        if ocr and self.erro_ocr is not None:
            raise self.erro_ocr
        if origem.name in self.escaneados and not ocr:
            return "<!-- página 1 -->\n\n<!-- image -->\n\n<!-- página 2 -->\n\n", {}
        return f"<!-- página 1 -->\n\n{TEXTO_EN}\n\n<!-- página 2 -->\n\n{TEXTO_EN}", {}


@pytest.fixture()
def pasta_pdfs(tmp_path):
    pasta = tmp_path / "pdfs"
    pasta.mkdir()
    (pasta / "a.pdf").write_bytes(b"%PDF-1.4 a")
    (pasta / "b.pdf").write_bytes(b"%PDF-1.4 b")
    return pasta


@pytest.fixture()
def falso(monkeypatch):
    f = DoclingFalso()
    monkeypatch.setattr(conversao, "_converter_com_docling", f)
    return f


# ---------- 2.6 OCR por documento ----------

def test_ocr_por_documento_reconverte_so_ele_e_reavalia_a_qualidade(client, pasta_pdfs, falso):
    slug = _novo_projeto(client, pasta_pdfs)
    _executar(client, slug)
    assert [c[:3] for c in falso.chamadas] == [("a.pdf", False, False), ("b.pdf", False, False)]
    docs = _docs(client, slug)
    assert docs["a.pdf"]["status"] == "com_problema" and docs["a.pdf"]["problemas"] == ["documento sem texto"]
    assert docs["b.pdf"]["status"] == "novo" and docs["a.pdf"]["ocr"] is None
    pend = _pendencias(client, slug)["a.pdf"]
    assert pend["pode_ocr"] is True and pend["ocr"] is None

    # liga o OCR só no a.pdf: o documento volta ao pipeline e só ele é reconvertido (OCR de página inteira)
    d = _patch(client, slug, docs["a.pdf"]["id"], {"ocr": True})
    assert d["ocr"] is True and d["status"] == "alterado"
    falso.chamadas.clear()
    resumo = _executar(client, slug)
    assert falso.chamadas == [("a.pdf", True, True, "en")]
    assert _etapa(resumo, "conversao")["ok"] == 1 and _etapa(resumo, "conversao")["pulado"] == 1

    # a qualidade foi reavaliada: "sem texto" saiu e o documento segue para a limpeza
    a = _docs(client, slug)["a.pdf"]
    assert a["problemas"] == [] and a["status"] != "com_problema" and a["paginas"] == 2
    assert "a.pdf" not in _pendencias(client, slug)
    assert _etapa(resumo, "qualidade")["ok"] >= 1 and _etapa(resumo, "limpeza")["ok"] >= 1

    # nada mudou: tudo pulado
    falso.chamadas.clear()
    resumo = _executar(client, slug)
    assert falso.chamadas == [] and _etapa(resumo, "conversao")["ok"] == 0

    # volta a seguir o projeto (sem OCR): só o a.pdf reconverte, e o problema volta
    _patch(client, slug, docs["a.pdf"]["id"], {"ocr": None})
    falso.chamadas.clear()
    _executar(client, slug)
    assert falso.chamadas == [("a.pdf", False, False, "en")]
    assert _docs(client, slug)["a.pdf"]["status"] == "com_problema"


def test_override_false_vence_ocr_do_projeto_e_modo_do_projeto_e_regioes(client, pasta_pdfs, falso):
    slug = _novo_projeto(client, pasta_pdfs)
    params = client.get(f"/api/projetos/{slug}/parametros").json()
    params["conversao"]["ocr"] = True
    client.put(f"/api/projetos/{slug}/parametros", json=params)
    docs = _executar(client, slug) and _docs(client, slug)
    # projeto com OCR ligado: modo padrão do Docling (só regiões sem texto), não a página inteira
    assert sorted(falso.chamadas) == [("a.pdf", True, False, "en"), ("b.pdf", True, False, "en")]

    _patch(client, slug, docs["b.pdf"]["id"], {"ocr": False})
    falso.chamadas.clear()
    _executar(client, slug)
    assert falso.chamadas == [("b.pdf", False, False, "en")]


def test_ocr_efetivo_e_chave_de_cache_dependem_do_override(client, pasta_pdfs, falso):
    from app.database import sessao_do_projeto
    from app.models import Documento
    from app.services.orquestrador import _chave_doc_completa, etapas_registradas

    slug = _novo_projeto(client, pasta_pdfs)
    _executar(client, slug)
    por_nome = {e.nome: e for e in etapas_registradas()}
    db = sessao_do_projeto(slug)
    try:
        doc = db.query(Documento).filter_by(arquivo="b.pdf").one()
        params = {"conversao": {"ocr": False}, "idioma": ["pt", "en"]}
        assert conversao.ocr_efetivo(doc, params) == (False, False, "pt")
        chave_none = _chave_doc_completa(por_nome, por_nome["conversao"], doc, params)
        chave_qualidade_none = _chave_doc_completa(por_nome, por_nome["qualidade"], doc, params)
        doc.ocr = True
        assert conversao.ocr_efetivo(doc, params) == (True, True, "pt")
        assert _chave_doc_completa(por_nome, por_nome["conversao"], doc, params) != chave_none
        # a mudança se propaga às etapas que dependem da conversão
        assert _chave_doc_completa(por_nome, por_nome["qualidade"], doc, params) != chave_qualidade_none
        doc.ocr = False
        assert conversao.ocr_efetivo(doc, {"conversao": {"ocr": True}}) == (False, False, "en")
    finally:
        db.rollback()
        db.close()


def test_motor_de_ocr_ausente_vira_problema_retentavel(client, pasta_pdfs, falso):
    slug = _novo_projeto(client, pasta_pdfs)
    docs = _executar(client, slug) and _docs(client, slug)
    _patch(client, slug, docs["a.pdf"]["id"], {"ocr": True})
    falso.erro_ocr = ModuleNotFoundError("No module named 'rapidocr'")
    resumo = _executar(client, slug)
    assert _etapa(resumo, "conversao")["erro"] == 1
    assert _docs(client, slug)["a.pdf"]["problemas"] == [conversao.MSG_SEM_OCR]
    assert _docs(client, slug)["a.pdf"]["status"] == "com_problema"

    # instalou o motor: nova execução tenta de novo, sem mexer em nada (caminho "retentar")
    falso.erro_ocr = None
    falso.chamadas.clear()
    _executar(client, slug)
    assert falso.chamadas == [("a.pdf", True, True, "en")]
    assert _docs(client, slug)["a.pdf"]["problemas"] == []
    assert _docs(client, slug)["a.pdf"]["status"] != "com_problema"


# ---------- 2.5 duplicatas próximas ----------

def _palavras_sinteticas(n, semente):
    silabas = ["ba", "ko", "li", "mu", "ra", "te", "vo", "zi", "pe", "su", "na", "do"]
    todas = ["".join(p) for p in itertools.product(silabas, repeat=3)]
    rnd = random.Random(semente)
    return rnd.sample(todas, n)


def _texto(pool, semente, frases=25):
    rnd = random.Random(semente)
    return " ".join(" ".join(rnd.choice(pool) for _ in range(12)).capitalize() + "." for _ in range(frases))


@pytest.fixture()
def corpus_duplicatas(tmp_path):
    pasta = tmp_path / "dup"
    pasta.mkdir()
    pool_a = _palavras_sinteticas(60, 1)
    base = _texto(pool_a, 10)
    (pasta / "001_2025_Cai_Original.md").write_text(f"# Um titulo qualquer sobre agentes\n\n{base}", encoding="utf-8")
    # quase igual: o mesmo texto com uma frase a mais
    (pasta / "002_2025_Cai_Quase_Igual.md").write_text(f"# Outro titulo diferente aqui\n\n{base} {pool_a[0]} {pool_a[1]} {pool_a[2]}.", encoding="utf-8")
    # texto próprio, vocabulário disjunto
    (pasta / "003_2025_Souza_Outro.md").write_text(f"# Estudo independente de caso\n\n{_texto(_palavras_sinteticas(60, 2), 20)}", encoding="utf-8")
    # mesmo título (normalizado) de 003, mas texto diferente e outro vocabulário
    (pasta / "004_2025_Lima_Mesmo_Titulo.md").write_text(
        f"# Estudo Independente de CASO!\n\n{_texto(_palavras_sinteticas(60, 3), 30)}", encoding="utf-8")
    return pasta


def test_duplicata_proxima_por_cosseno_e_por_titulo_sem_excluir(client, corpus_duplicatas):
    slug = _novo_projeto(client, corpus_duplicatas)
    resumo = _executar(client, slug)
    assert _etapa(resumo, "duplicatas_proximas")["ok"] == 1
    docs = _docs(client, slug)
    aviso002 = [a for a in docs["002_2025_Cai_Quase_Igual.md"]["avisos"] if "duplicata" in a]
    assert len(aviso002) == 1 and aviso002[0] in ("provável duplicata de 001_2025_Cai_Original.md (similaridade 1,00)", *[f"provável duplicata de 001_2025_Cai_Original.md (similaridade 0,9{k})" for k in range(5, 10)])
    assert [a for a in docs["004_2025_Lima_Mesmo_Titulo.md"]["avisos"] if "duplicata" in a] == [
        "provável duplicata de 003_2025_Souza_Outro.md (mesmo título)"]
    # o documento anterior e o independente não são marcados; ninguém é excluído nem vira com_problema
    assert not [a for a in docs["001_2025_Cai_Original.md"]["avisos"] if "duplicata" in a]
    assert not [a for a in docs["003_2025_Souza_Outro.md"]["avisos"] if "duplicata" in a]
    assert all(d["status"] != "com_problema" and not d["excluido"] for d in docs.values())
    pend = _pendencias(client, slug)
    assert "002_2025_Cai_Quase_Igual.md" in pend and "004_2025_Lima_Mesmo_Titulo.md" in pend

    # segunda execução: cache; as marcas continuam
    resumo = _executar(client, slug)
    assert _etapa(resumo, "duplicatas_proximas")["pulado"] == 1
    assert any("duplicata" in a for a in _docs(client, slug)["002_2025_Cai_Quase_Igual.md"]["avisos"])


def test_titulo_normalizado():
    assert titulo_normalizado("<!-- página 1 -->\n\n## AI as Co-founder: GenAI for Entrepreneurship!\n\ntexto") == \
        "ai as co founder genai for entrepreneurship"
    assert titulo_normalizado("# Introdução\n\ntexto") is None  # curto demais: não compara
    assert titulo_normalizado("sem título nenhum") is None


# ---------- excluir da análise ----------

def test_excluido_sai_das_etapas_e_e_reversivel(client, corpus_duplicatas):
    slug = _novo_projeto(client, corpus_duplicatas)
    _executar(client, slug)
    docs = _docs(client, slug)
    id003 = docs["003_2025_Souza_Outro.md"]["id"]
    antes = client.get(f"/api/projetos/{slug}/analises/resumo").json()
    n_antes = len(antes["documentos"])

    d = _patch(client, slug, id003, {"excluido": True})
    assert d["excluido"] is True and d["status"] != "com_problema"
    resumo = _executar(client, slug)
    assert _etapa(resumo, "linguistica")["ok"] + _etapa(resumo, "linguistica")["pulado"] == n_antes - 1
    assert len(client.get(f"/api/projetos/{slug}/analises/resumo").json()["documentos"]) == n_antes - 1
    # excluído não participa das comparações de duplicata: o 004 deixa de apontar para o 003
    assert not [a for a in _docs(client, slug)["004_2025_Lima_Mesmo_Titulo.md"]["avisos"] if "duplicata" in a]
    assert _pendencias(client, slug)["003_2025_Souza_Outro.md"]["excluido"] is True

    # reincluir (false ou null) devolve o documento às etapas e às análises
    _patch(client, slug, id003, {"excluido": None})
    assert _docs(client, slug)["003_2025_Souza_Outro.md"]["excluido"] is False
    _executar(client, slug)
    assert len(client.get(f"/api/projetos/{slug}/analises/resumo").json()["documentos"]) == n_antes
    assert [a for a in _docs(client, slug)["004_2025_Lima_Mesmo_Titulo.md"]["avisos"] if "duplicata" in a]
    assert "003_2025_Souza_Outro.md" not in _pendencias(client, slug)


# ---------- 3.3: ajustes da revisão por amostra ----------

def test_hifenizacao_mantem_prefixos_de_composto_real():
    assert corrigir_hifenizacao("a non-\nexperimental design") == ("a non-experimental design", 0)
    assert corrigir_hifenizacao("self-\nemployed workers") == ("self-employed workers", 0)
    # quebra de sílaba continua sendo juntada
    assert corrigir_hifenizacao("entrepre-\nneurship grows") == ("entrepreneurship grows", 1)
    assert corrigir_hifenizacao("pre-\nvious results") == ("previous results", 1)


def test_emails_com_chaves_e_urls_quebradas_sao_removidos():
    texto, info = limpar_texto("Contato {ana, rui}@cs.univ.edu e shuyan.zhou@ duke.edu veja https: //nips.cc/guias/x e "
                               "(https:// creativecommons.org/licenses/by/4.0). O metodo pass@k mede.")
    assert "@cs" not in texto and "duke" not in texto and "nips" not in texto and "creativecommons" not in texto
    assert "pass@k" in texto  # não é e-mail
    assert info["urls"] == 4


def test_aviso_quando_todo_o_texto_caiu_em_secoes_excluidas():
    from app.services.texto import avisos_do_documento

    q = {"limpeza": {"palavras_total": 6605, "palavras_corpo": 0, "palavras_referencias": 0, "referencias_detectadas": False}}
    assert any("nenhum texto no corpo" in a for a in avisos_do_documento(q, None))
    q["limpeza"]["palavras_corpo"] = 10
    assert not any("nenhum texto no corpo" in a for a in avisos_do_documento(q, None))


# ---------- 3.3: script revisar_limpeza ----------

def test_revisar_limpeza_gera_markdown_para_projeto_sintetico(client, tmp_path):
    cab = "Journal of Synthetic Studies Vol 3"
    paginas = []
    for n in range(1, 7):
        corpo = ("The analysis of entrepre-\nneurship shows that the results of the study are consistent. "
                 "See https://exemplo.org/x and write to ana@exemplo.org for details. ") * 4
        paginas.append(f"<!-- página {n} -->\n\n{cab}\n\n{corpo}\n\n{n}\n")
    refs = "\n\n".join(f"Autor{i}, A. ({2000 + i}). Titulo do trabalho numero {i}. Journal of Things, 1(2), 3-4." for i in range(40))
    pasta = tmp_path / "sint"
    pasta.mkdir()
    for i in range(3):
        md = "".join(paginas) + f"<!-- página 7 -->\n\n## Conclusion\n\nFinal remarks of the study number {i}. " * 1 \
            + f"\n\n## References\n\n{refs}\n"
        (pasta / f"00{i}_2025_Autor_Texto.md").write_text(md, encoding="utf-8")
    slug = _novo_projeto(client, pasta, "Sintetico Rev")
    _executar(client, slug)
    for i, d in enumerate(client.get(f"/api/projetos/{slug}/documentos").json()):
        _patch(client, slug, d["id"], {"grupo": "academica" if i < 2 else "cinzenta"})

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import revisar_limpeza

    saida = tmp_path / "revisao.md"
    assert revisar_limpeza.gerar_revisao(slug, n=2, semente=7, saida=saida) == saida
    md = saida.read_text(encoding="utf-8")
    assert md.count("### ") == 2 and md.count("- [ ] Cabeçalho/rodapé") == 2
    assert "Journal of Synthetic Studies Vol 3" in md  # linha repetida listada
    assert "entrepre-↵neurship" in md and "→ `entrepreneurship`" in md  # hifenização antes → depois
    assert "URLs / e-mails / DOI removidos" in md
    assert "Fronteira das referências" in md and "últimos 150 caracteres antes" in md
    # reprodutível, e estratificado: com n=2 sai um de cada grupo
    assert revisar_limpeza.gerar_revisao(slug, n=2, semente=7, saida=tmp_path / "r2.md").read_text(encoding="utf-8") == md
    assert "Grupo: academica" in md and "Grupo: cinzenta" in md


def test_sortear_estratifica_por_grupo_com_semente_fixa():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import revisar_limpeza

    class D:
        def __init__(self, arquivo, grupo):
            self.arquivo, self.grupo = arquivo, grupo

    docs = [D(f"a{i}.md", "academica") for i in range(8)] + [D(f"c{i}.md", "cinzenta") for i in range(2)]
    amostra = revisar_limpeza.sortear(docs, 4, 26)
    assert len(amostra) == 4 and sum(d.grupo == "cinzenta" for d in amostra) == 2
    assert [d.arquivo for d in amostra] == [d.arquivo for d in revisar_limpeza.sortear(docs, 4, 26)]
    assert len(revisar_limpeza.sortear(docs, 50, 26)) == 10
