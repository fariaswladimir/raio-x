"""15.6 Estilometria: distâncias Delta conferidas à mão e contra o pacote stylo (R), MFW/culling/amostras, agrupamento
(ward.D/average), consenso entre faixas de MFW, PCA e MDS; API, CSV e etapa com um corpus sintético. Sem Docling.

As conferências com o R rodam só se o Rscript e o pacote ``stylo`` estiverem instalados (senão são puladas)."""
import csv
import json
import os
import random
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from app import database
from app.models import Analise
from app.services.analises import agrupamento, estilometria as est, similaridade

# ---------- valores conferidos à mão ----------
# f (em %): a = (1, 2), b = (3, 2), c = (5, 8). Coluna 1: média 3, dp amostral 2 -> z = (-1, 0, 1).
# Coluna 2: média 4, dp = sqrt((4 + 4 + 16)/2) = sqrt(12) -> z = (-1/sqrt3, -1/sqrt3, 2/sqrt3).
F = np.array([[1.0, 2.0], [3.0, 2.0], [5.0, 8.0]])
R3 = np.sqrt(3.0)


def test_escores_z_usam_desvio_amostral():
    z, ok = est.escores_z(F)
    assert ok.all()
    assert np.allclose(z[:, 0], [-1, 0, 1])
    assert np.allclose(z[:, 1], [-1 / R3, -1 / R3, 2 / R3])


def test_distancias_a_mao():
    d = est.distancia(F, "delta_classico")
    assert d[0, 1] == pytest.approx(0.5) and d[0, 2] == pytest.approx((2 + R3) / 2) and d[1, 2] == pytest.approx((1 + R3) / 2)
    assert np.allclose(d, d.T) and np.allclose(np.diag(d), 0)
    assert est.distancia(F, "argamon")[0, 2] == pytest.approx(np.sqrt(4 + 3) / 2)  # euclidiana / n (como o stylo)
    e = est.distancia(F, "eder")  # pesos (n - i + 2)/n = 1,5 e 1,0
    assert e[0, 1] == pytest.approx(1.5) and e[0, 2] == pytest.approx(1.5 * 2 + 1.0 * R3)
    s = est.distancia(F, "eder_simples")
    assert s[0, 2] == pytest.approx((np.sqrt(5) - 1) + (np.sqrt(8) - np.sqrt(2)))
    # Cosine Delta: z_a = (-1, -1/sqrt3), z_b = (0, -1/sqrt3): cos = (1/3) / (sqrt(4/3) * sqrt(1/3)) = 0,5
    assert est.distancia(F, "cosine_delta")[0, 1] == pytest.approx(0.5)
    assert est.distancia(F, "cosseno")[0, 1] == pytest.approx(1 - 7 / np.sqrt(65))


def test_coluna_constante_sai_dos_escores_z():
    f = np.array([[1.0, 2.0, 4.0], [3.0, 2.0, 4.0], [5.0, 8.0, 4.0]])
    assert np.allclose(est.distancia(f, "delta_classico"), est.distancia(F, "delta_classico"))
    with pytest.raises(ValueError):
        est.distancia(np.ones((3, 2)), "delta_classico")
    with pytest.raises(ValueError):
        est.distancia(F, "manhattan")


def test_ward_d_e_media_a_mao():
    # pontos numa reta: 0, 1, 5 (distância absoluta). ward.D: funde 0-1 (h = 1); d(5, {0,1}) pela fórmula de
    # Lance-Williams sobre a própria distância = ((1+1)·5 + (1+1)·4 − 1·1)/3 = 17/3.
    d = np.array([[0, 1, 5], [1, 0, 4], [5, 4, 0]], dtype=float)
    z = est.ligar(d, "ward")
    assert z[0, 2] == pytest.approx(1) and z[1, 2] == pytest.approx(17 / 3)
    za = est.ligar(d, "average")
    assert za[1, 2] == pytest.approx(4.5)


def test_clados_e_consenso():
    d1 = np.array([[0, 1, 5, 6], [1, 0, 5, 6], [5, 5, 0, 1], [6, 6, 1, 0]], dtype=float)
    d2 = np.array([[0, 1, 2, 6], [1, 0, 2, 6], [2, 2, 0, 5], [6, 6, 5, 0]], dtype=float)
    a1, a2 = est.ligar(d1, "average"), est.ligar(d2, "average")
    assert set(est.clados(a1)) == {frozenset({0, 1}), frozenset({2, 3})}
    assert set(est.clados(a2)) == {frozenset({0, 1}), frozenset({0, 1, 2})}
    freq, junto = est.consenso([a1, a1, a2], 2)
    assert freq[frozenset({0, 1})] == pytest.approx(1.0)
    assert freq[frozenset({2, 3})] == pytest.approx(2 / 3) and freq[frozenset({0, 1, 2})] == pytest.approx(1 / 3)
    assert junto[0, 1] == pytest.approx(1.0) and junto[2, 3] == pytest.approx(2 / 3) and junto[0, 2] == pytest.approx(1 / 3)


# ---------- MFW, culling e amostras ----------

def test_lista_mfw_ordem_e_culling():
    c = [Counter("a a a b b c".split()), Counter("a b b d d d d".split()), Counter("a c e".split())]
    # totais: a 5, d 4, b 4, c 2, e 1 -> empate b/d pela ordem alfabética
    assert est.lista_de_palavras(c) == ["a", "b", "d", "c", "e"]
    assert est.lista_de_palavras(c, maximo=2) == ["a", "b"]
    # presença: a 3/3, b 2/3, c 2/3, d 1/3, e 1/3
    assert est.lista_de_palavras(c, culling=60) == ["a", "b", "c"]
    assert est.lista_de_palavras(c, culling=100) == ["a"]
    f = est.tabela_relativa(c, [6, 7, 3], ["a", "d"])
    assert np.allclose(f, [[50, 0], [100 / 7, 400 / 7], [100 / 3, 0]])


def test_amostras_de_tamanho_fixo():
    m1, m2 = {"id": 1, "rotulo": "A"}, {"id": 2, "rotulo": "B"}
    u, exc = est.montar_unidades([(m1, list("abcdefghij")), (m2, list("abc"))], "amostra", 4)
    assert [x["tokens"] for x in u] == [list("abcd"), list("efgh")] and [x["parte"] for x in u] == [1, 2]
    assert exc and exc[0]["id"] == 2
    u, exc = est.montar_unidades([(m1, list("abc")), (m2, [])], "documento", 4)
    assert len(u) == 1 and exc[0]["id"] == 2


# ---------- corpus sintético de "estilos" ----------

FUNCIONAIS = "the of and to in a is that for it as with be on this by".split()
CONTEUDO = "agent market model founder startup data risk value firm task user system design cost tool policy".split()


def _texto_estilo(estilo: int, semente: int, n: int = 3000) -> list[str]:
    """Estilo 0 usa muito "the/of/and"; estilo 1 muito "that/it/this"; o conteúdo é sorteado igual nos dois."""
    rnd = random.Random(semente)
    pesos = [8, 7, 6, 3, 3, 3, 2, 1, 2, 1, 2, 2, 1, 1, 1, 1] if estilo == 0 else [3, 2, 2, 3, 3, 3, 2, 7, 2, 6, 2, 2, 1, 1, 6, 1]
    saida = []
    for _ in range(n):
        if rnd.random() < 0.55:
            saida.append(rnd.choices(FUNCIONAIS, pesos)[0])
        else:
            saida.append(rnd.choice(CONTEUDO))
    return saida


def _textos(n_por_estilo: int = 4) -> list[tuple[dict, list[str]]]:
    textos = []
    for estilo in range(2):
        for i in range(n_por_estilo):
            k = len(textos) + 1
            meta = {"id": k, "rotulo": f"{k:03d}", "arquivo": f"{k:03d}.md", "ano": 2025, "grupo": f"g{estilo}", "idioma": "en"}
            textos.append((meta, _texto_estilo(estilo, 1000 * estilo + i)))
    return textos


@pytest.mark.parametrize("medida", est.DISTANCIAS)
def test_estilos_plantados_sao_recuperados(medida):
    r = est.calcular_textos(_textos(), mfw=30, distancia_=medida, k=2, bandas=(10, 15, 20, 25, 30))
    rot = [u["cluster"] for u in r["unidades"]]
    assert agrupamento.ari(rot, [0] * 4 + [1] * 4) == pytest.approx(1.0)
    assert all(g["clado"] == pytest.approx(1.0) and g["pares_juntos"] == pytest.approx(1.0) for g in r["consenso"]["grupos"])
    for u in r["unidades"]:
        assert u["vizinhos"][0]["cluster"] == u["cluster"]


def test_duplicata_tem_distancia_zero_e_e_o_vizinho():
    textos = _textos(3)
    meta = {**textos[0][0], "id": 99, "rotulo": "099"}
    textos.append((meta, list(textos[0][1])))
    r = est.calcular_textos(textos, mfw=30)
    i0 = next(u["i"] for u in r["unidades"] if u["id"] == 1)
    i99 = next(u["i"] for u in r["unidades"] if u["id"] == 99)
    assert r["matriz"][i0][i99] == pytest.approx(0, abs=1e-12)
    assert r["unidades"][i0]["vizinhos"][0]["id"] == 99


def test_saida_completa_pca_mds_perfis_e_amostras():
    r = est.calcular_textos(_textos(), mfw=30, k=2, pca_="correlacao")
    assert r["mfw_efetivo"] == len(r["palavras"]) <= 30 and r["palavras"][0] in FUNCIONAIS
    assert sum(r["pca"]["variancia_explicada"]) <= 1 + 1e-9 and r["pca"]["cargas"][0]["positivas"]
    assert len(r["pca"]["cargas_todas"]) == r["pca"]["n_palavras"]
    # palavras plantadas: "that/it/this" e "the/of/and" puxam o PC1 em sentidos opostos
    p1 = {c["palavra"]: c["pc1"] for c in r["pca"]["cargas_todas"]}
    assert np.sign(p1["the"]) == np.sign(p1["of"]) and np.sign(p1["that"]) == np.sign(p1["this"]) != np.sign(p1["the"])
    perfil = next(p for p in r["perfis"] if p["id"] == 1)
    acima, abaixo = {x["palavra"] for x in perfil["acima"]}, {x["palavra"] for x in perfil["abaixo"]}
    assert not acima & {"that", "it", "this"} and not abaixo & {"the", "of", "and"}
    assert all(x["z"] > 0 for x in perfil["acima"]) and all(x["z"] < 0 for x in perfil["abaixo"])
    assert 0 < perfil["cobertura_mfw"] <= 1
    assert r["aviso"] and "autoria" in r["aviso"]
    am = est.calcular_textos(_textos(), mfw=30, unidade="amostra", tamanho_amostra=1000, k=2)
    assert am["n_unidades"] == 24 and am["n_documentos"] == 8
    assert am["coesao"]["vizinho_do_mesmo_documento"] >= 0  # definida
    assert all(v["id"] != u["id"] for u in am["unidades"] for v in u["vizinhos"])  # vizinhos de outros documentos
    rot = [u["cluster"] for u in am["unidades"]]
    assert agrupamento.ari(rot, [0] * 12 + [1] * 12) == pytest.approx(1.0)


def test_validacoes():
    t = _textos(2)
    with pytest.raises(ValueError):
        est.calcular_textos(t, mfw=1)
    with pytest.raises(ValueError):
        est.calcular_textos(t, culling=150)
    with pytest.raises(ValueError):
        est.calcular_textos(t, unidade="paragrafo")
    with pytest.raises(ValueError):
        est.calcular_textos(t[:2], mfw=10)
    with pytest.raises(ValueError):
        est.calcular_textos(t, k=4)


# ---------- conferência com o pacote stylo (R) ----------

RSCRIPT = os.environ.get("RAIOX_RSCRIPT") or next((c for c in ("C:/Program Files/R/R-4.6.1/bin/Rscript.exe", shutil.which("Rscript") or "")
                                                     if c and Path(c).is_file()), None)


def _tem_stylo() -> bool:
    if not RSCRIPT:
        return False
    try:
        r = subprocess.run([RSCRIPT, "-e", 'cat(requireNamespace("stylo", quietly=TRUE) && requireNamespace("ape", quietly=TRUE))'],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip().endswith("TRUE")


precisa_stylo = pytest.mark.skipif(not _tem_stylo(), reason="Rscript ou pacote stylo/ape indisponível")

SCRIPT_R = r"""
suppressMessages({library(stylo); library(ape)})
args <- commandArgs(TRUE)
x <- as.matrix(read.csv(args[1], header=TRUE, row.names=1, check.names=FALSE))
out <- args[2]
w <- function(m, nome) write.table(as.matrix(m), file.path(out, paste0(nome, ".csv")), sep=",", row.names=FALSE, col.names=FALSE)
w(dist.delta(x), "delta_classico"); w(dist.argamon(x), "argamon"); w(dist.eder(x), "eder")
w(dist.simple(x), "eder_simples"); w(dist.wurzburg(x), "cosine_delta"); w(dist.cosine(x), "cosseno")
d <- dist.delta(x)
hw <- suppressMessages(hclust(d, method="ward"))
ha <- hclust(d, method="average")
w(hw$height, "altura_ward"); w(ha$height, "altura_average")
w(cophenetic(hw), "cof_ward"); w(cophenetic(ha), "cof_average")
pr <- prcomp(x, scale.=TRUE); w(pr$x[,1:2], "pca_cor_x"); w(pr$rotation[,1:2], "pca_cor_rot"); w(pr$sdev^2/sum(pr$sdev^2), "pca_cor_var")
pv <- prcomp(x); w(pv$x[,1:2], "pca_cov_x"); w(pv$rotation[,1:2], "pca_cov_rot")
w(cmdscale(as.matrix(d)), "mds")
arv <- lapply(c(4,6,8,10,12), function(m) as.phylo(suppressMessages(hclust(dist.delta(x[,1:m]), method="ward"))))
class(arv) <- "multiPhylo"
pp <- prop.part(arv)
lab <- attr(pp, "labels")
writeLines(sapply(seq_along(pp), function(i) paste(paste(sort(lab[pp[[i]]]), collapse="|"), attr(pp,"number")[i]/length(arv))),
           file.path(out, "clados.txt"))
# tabela completa a partir de tokens (make.frequency.list + make.table.of.frequencies + perform.culling)
linhas <- readLines(args[3])
corpus <- lapply(strsplit(linhas, " "), function(v) v)
names(corpus) <- paste0("t", seq_along(corpus))
fl <- make.frequency.list(corpus)
tab <- make.table.of.frequencies(corpus, fl)
tab <- perform.culling(tab, as.numeric(args[4]))
tab <- tab[, 1:min(as.numeric(args[5]), ncol(tab))]
writeLines(colnames(tab), file.path(out, "mfw.txt"))
w(dist.delta(tab), "tokens_delta")
w(dist.wurzburg(tab), "tokens_cosine_delta")
"""


def _cofenetica(z: np.ndarray) -> np.ndarray:
    from scipy.cluster import hierarchy
    from scipy.spatial.distance import squareform
    return squareform(hierarchy.cophenet(z))


@precisa_stylo
def test_confere_com_stylo(tmp_path):
    rng = np.random.default_rng(7)
    n, m = 8, 12
    contagens = rng.poisson(lam=np.linspace(60, 3, m) * rng.uniform(0.5, 1.5, (n, m)))
    f = 100 * contagens / (contagens.sum(1, keepdims=True) + 500)
    with open(tmp_path / "tab.csv", "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow([""] + [f"w{j}" for j in range(m)])
        for i in range(n):
            wr.writerow([f"d{i}"] + [format(float(v), ".17g") for v in f[i]])
    textos = _textos(3)
    (tmp_path / "tokens.txt").write_text("\n".join(" ".join(t) for _m, t in textos), encoding="utf-8")
    (tmp_path / "comp.R").write_text(SCRIPT_R, encoding="utf-8")
    r = subprocess.run([RSCRIPT, str(tmp_path / "comp.R"), str(tmp_path / "tab.csv"), str(tmp_path), str(tmp_path / "tokens.txt"),
                        "50", "14"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    ler = lambda nome: np.loadtxt(tmp_path / f"{nome}.csv", delimiter=",")  # noqa: E731
    for medida in est.DISTANCIAS:
        assert np.abs(est.distancia(f, medida) - ler(medida)).max() < 1e-9, medida
    d = est.distancia(f, "delta_classico")
    for metodo in ("ward", "average"):
        z = est.ligar(d, metodo)
        assert np.abs(np.sort(z[:, 2]) - np.sort(ler(f"altura_{metodo}"))).max() < 1e-9
        assert np.abs(_cofenetica(z) - ler(f"cof_{metodo}")).max() < 1e-9  # mesma topologia e alturas
    zs, _ok = est.escores_z(f)
    x, cargas, var = est.pca(zs)
    assert np.abs(np.array(var) - ler("pca_cor_var")).max() < 1e-9
    assert np.abs(np.abs(x) - np.abs(ler("pca_cor_x"))).max() < 1e-9 and np.abs(np.abs(cargas.T) - np.abs(ler("pca_cor_rot"))).max() < 1e-9
    x2, cargas2, _ = est.pca(f)
    assert np.abs(np.abs(x2) - np.abs(ler("pca_cov_x"))).max() < 1e-9 and np.abs(np.abs(cargas2.T) - np.abs(ler("pca_cov_rot"))).max() < 1e-9
    mds, _ = similaridade.mds_classico(d)
    assert np.abs(np.abs(mds) - np.abs(ler("mds"))).max() < 1e-9
    freq, _ = est.consenso([est.ligar(est.distancia(f[:, :b], "delta_classico"), "ward") for b in (4, 6, 8, 10, 12)], 3)
    r_clados = {}
    for linha in (tmp_path / "clados.txt").read_text().splitlines():
        a, v = linha.split()
        s = frozenset(int(t[1:]) for t in a.split("|"))
        if 1 < len(s) < n:
            r_clados[s] = float(v)
    assert set(r_clados) == set(freq) and all(abs(r_clados[c] - freq[c]) < 1e-9 for c in freq)
    # do texto à distância: MFW, culling 50% e 14 palavras
    res = est.calcular_textos(textos, mfw=14, culling=50)
    assert res["palavras"] == (tmp_path / "mfw.txt").read_text().split()
    assert np.abs(np.array(res["matriz"]) - ler("tokens_delta")).max() < 1e-5  # a saída é arredondada a 6 casas
    res_c = est.calcular_textos(textos, mfw=14, culling=50, distancia_="cosine_delta")
    assert np.abs(np.array(res_c["matriz"]) - ler("tokens_cosine_delta")).max() < 1e-5


# ---------- API, CSV e etapa ----------

@pytest.fixture()
def corpus_estilo(client, tmp_path):
    pasta = tmp_path / "estilos"
    pasta.mkdir()
    for meta, toks in _textos(3):
        frases = [" ".join(toks[k:k + 15]).capitalize() + "." for k in range(0, len(toks), 15)]
        corpo = "\n\n".join(" ".join(frases[k:k + 6]) for k in range(0, len(frases), 6))
        (pasta / f"{meta['id']:03d}_2025_Autor{meta['id']}_Titulo_{meta['grupo']}.md").write_text("# Study\n\n" + corpo, encoding="utf-8")
    r = client.post("/api/projetos", json={"nome": "estilos", "pasta_origem": str(pasta)})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    assert r.status_code == 200, r.text
    return slug, r.json()


def test_api_estilometria_csv_e_etapa(client, corpus_estilo):
    slug, execucao = corpus_estilo
    etapa = next(e for e in execucao["etapas"] if e["etapa"] == "estilometria")
    assert etapa["erro"] == 0
    base = f"/api/projetos/{slug}/analises/estilometria"
    r = client.get(base, params={"mfw": 30, "k": 2}).json()
    assert r["n_unidades"] == 6 and r["distancia"] == "delta_classico" and r["unidade"] == "documento"
    rot = [u["cluster"] for u in r["unidades"]]
    assert agrupamento.ari(rot, [0, 0, 0, 1, 1, 1]) == pytest.approx(1.0)
    assert len(r["matriz"]) == 6 and r["consenso"]["bandas"] and r["aviso"]
    rc = client.get(base, params={"mfw": 30, "distancia": "cosine_delta", "metodo": "average", "pca": "covariancia", "bandas": "10,20,30"}).json()
    assert rc["distancia"] == "cosine_delta" and rc["pca"]["tipo"] == "covariancia" and rc["consenso"]["bandas"] == [10, 20, 30]
    am = client.get(base, params={"mfw": 20, "unidade": "amostra", "tamanho_amostra": 1000}).json()
    assert am["n_unidades"] >= 12 and am["coesao"] is not None
    for sufixo in ("distancias.csv", "cargas.csv", "unidades.csv"):
        c = client.get(f"{base}/{sufixo}", params={"mfw": 30})
        assert c.status_code == 200 and c.content.startswith(b"\xef\xbb\xbf"), sufixo
    assert b"carga_pc1" in client.get(f"{base}/cargas.csv").content
    assert client.get(base, params={"distancia": "manhattan"}).status_code == 422
    assert client.get(base, params={"mfw": 1}).status_code == 422
    assert client.get(base, params={"bandas": "abc"}).status_code == 422
    assert client.get(base, params={"unidade": "amostra", "tamanho_amostra": 50000}).status_code == 422
    db = database.sessao_do_projeto(slug)
    try:
        linhas = db.query(Analise).filter(Analise.tipo == "estilometria").all()
        assert len(linhas) == 1
        snap = json.loads(linhas[0].resultado_json)
        assert snap["n_unidades"] == 6 and snap["mfw"] == 100
        assert json.loads(linhas[0].parametros_json)["estilometria"]["distancia"] == "delta_classico"
    finally:
        db.close()


def test_api_sem_pipeline_devolve_404(client, projeto):
    assert client.get(f"/api/projetos/{projeto}/analises/estilometria").status_code == 404
