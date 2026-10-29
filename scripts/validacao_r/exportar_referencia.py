"""12.2 - Exporta as entradas de referência para a validação cruzada em R (docs/validacao_cruzada.md).

Cria um projeto de teste (pasta de projetos temporária, via ``RAIOX_PROJETOS_DIR``), executa o pipeline pela API
(``TestClient``, ``?sincrono=1``), define os grupos (cinzenta × acadêmica) e grava em ``--saida``:

- ``tokens.tsv``: a sequência de tokens **contados** de cada documento (universo da 4.2/5.4/6.1/6.2/7.3: corpo,
  ``incluir`` = 1, ``norm`` com >= 2 caracteres), com forma (``norm``), lema, bloco (página/seção), segmento (−1 =
  fora de segmento) e a marca de segmento de ruído (3.4). O R refaz todas as contagens a partir daqui;
- ``documentos.tsv``, ``segmentos.tsv`` (todos os ST, com ruído e nº de palavras) e ``stoplist.txt`` (palavras vazias
  ativas do projeto, o mesmo filtro da consulta);
- ``corpus-iramuteq.txt`` (exportação da 12.2);
- ``raiox_*.json``: os resultados do Raio-X a comparar (CHD simples e dupla com o mapa segmento → classe, keyness
  de todos os termos testados, colocados de agent/task/human, especificidades e AFC por ano, similitude).

**Contém texto do corpus**: a pasta de saída é temporária e deve ser apagada ao fim (não versionar).
Uso (na raiz do raio-x, com o .venv):
    .venv\\Scripts\\python.exe scripts\\validacao_r\\exportar_referencia.py --origem <pasta com .md> --saida <pasta temp>
"""
import argparse
import csv
import json
import os
import shutil
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

# arquivos (prefixo de 3 dígitos) da literatura cinzenta no corpus MLR; os demais são acadêmicos
CINZENTA = {"011", "047", "051", "057", "059", "060", "061", "063"}
TERMOS_COLOCACAO = ("agent", "task", "human")


def _json(caminho: Path, obj) -> None:
    caminho.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origem", required=True, type=Path, help="pasta com os .md do corpus (só leitura: é copiada)")
    ap.add_argument("--saida", required=True, type=Path, help="pasta temporária de saída")
    ap.add_argument("--slug", default="teste-val")
    args = ap.parse_args()

    saida = args.saida.resolve()
    saida.mkdir(parents=True, exist_ok=True)
    projetos = saida / "projetos"
    projetos.mkdir(exist_ok=True)
    os.environ["RAIOX_PROJETOS_DIR"] = str(projetos)  # antes de importar o app
    copia = saida / "origem"
    if not copia.exists():
        shutil.copytree(args.origem, copia)  # o original nunca é tocado

    from fastapi.testclient import TestClient

    from app.database import pasta_do_projeto, sessao_do_projeto
    from app.main import app
    from app.services import parametros as svc_parametros
    from app.services import ruido, segmentacao
    from app.services import vocabulario as svc_vocabulario
    from app.services.analises import dados, especificidades, keyness
    from app.services.palavras_vazias import filtro_palavras_vazias

    t0 = time.time()
    with TestClient(app) as client:
        slug = args.slug
        if not (pasta_do_projeto(slug) / "parametros.json").is_file():
            r = client.post("/api/projetos", json={"nome": slug, "pasta_origem": str(copia)})
            r.raise_for_status()
            slug = r.json()["slug"]
            r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
            r.raise_for_status()
            print(f"pipeline: {time.time() - t0:.0f} s")
        base = f"/api/projetos/{slug}"
        docs = client.get(f"{base}/documentos").json()
        for d in docs:
            prefixo = Path(d["arquivo"]).name[:3]
            grupo = "cinzenta" if prefixo in CINZENTA else "academica"
            if d.get("grupo") != grupo:
                client.patch(f"{base}/documentos/{d['id']}", json={"grupo": grupo}).raise_for_status()

        pasta = pasta_do_projeto(slug)
        params = svc_parametros.carregar(pasta)
        filtro = filtro_palavras_vazias(params)
        with sessao_do_projeto(slug) as db:
            metas = dados.documentos_do_corpus(db, pasta)
        voc = svc_vocabulario.ler_vocabulario(pasta)

        # ---------- documentos, tokens, segmentos, stoplist ----------
        with open(saida / "documentos.tsv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\")
            w.writerow(["doc", "arquivo", "id_estudo", "ano", "grupo"])
            for m in metas:
                w.writerow([m["id"], Path(m["arquivo"]).name[:3], m.get("id_estudo") or "", dados.chave_ano(m),
                            dados.chave_grupo(m)])
        n_tok = 0
        with open(saida / "tokens.tsv", "w", encoding="utf-8", newline="") as ft, \
                open(saida / "segmentos.tsv", "w", encoding="utf-8", newline="") as fs:
            wt = csv.writer(ft, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\")
            ws = csv.writer(fs, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\")
            wt.writerow(["doc", "i", "norm", "lema", "bloco", "seg", "ruido"])
            ws.writerow(["doc", "seg", "pagina", "n_tokens", "ruido"])
            for m in metas:
                tk = dados.carregar_tokens(pasta, m["id"])
                sg = segmentacao.ler_segmentos(pasta, m["id"])
                fora = ruido.segmentos_de_ruido(pasta, m["id"]) if ruido.excluir_ruido(params) else {}
                segs = sg["seg"] if sg and sg.get("n") == tk["n"] else [-1] * tk["n"]
                for s in (sg["segmentos"] if sg else []):
                    ws.writerow([m["id"], s["seg"], s["pagina"], s["n_tokens"], int(s["seg"] in fora)])
                for i in range(tk["n"]):
                    nm = tk["norm"][i]
                    if not tk["incluir"][i] or len(nm) < 2:
                        continue
                    s = segs[i]
                    wt.writerow([m["id"], i, nm, tk["lema"][i], tk["bloco"][i], s, int(s >= 0 and s in fora)])
                    n_tok += 1
        (saida / "stoplist.txt").write_text("\n".join(sorted(filtro)) + "\n", encoding="utf-8")
        print(f"tokens contados: {n_tok}; documentos: {len(metas)}")

        r = client.get(f"{base}/exportar/corpus-iramuteq.txt")
        r.raise_for_status()
        (saida / "corpus-iramuteq.txt").write_bytes(r.content)

        # ---------- resultados do Raio-X ----------
        def get(caminho, **q):
            r = client.get(f"{base}/analises/{caminho}", params=q)
            r.raise_for_status()
            return r.json()

        _json(saida / "raiox_reinert.json", get("reinert", mapa=1, classes=10, min_freq=3, max_formas=3000,
                                                min_classe=0, dupla=False))
        _json(saida / "raiox_reinert_dupla.json", get("reinert", mapa=1, classes=10, min_freq=3, max_formas=3000,
                                                      min_classe=0, dupla=True))
        # keyness: todos os termos testados (p = 1, sem dispersão mínima), para comparar termo a termo
        kn = keyness.calcular(voc, metas, filtro, particao="grupo", a="cinzenta", b="academica", por="lema",
                              filtrar=True, min_freq=5, min_docs_a=1, min_docs_b=1, p=1.0, limite=10 ** 7)
        _json(saida / "raiox_keyness.json", kn)
        kn_padrao = get("keyness", particao="grupo", a="cinzenta", b="academica", limite=50)
        _json(saida / "raiox_keyness_padrao.json", kn_padrao)
        col = {}
        for termo in TERMOS_COLOCACAO:
            for fronteira in ("bloco", "documento"):
                col[f"{termo}|{fronteira}"] = get("colocacoes", q=termo, por="lema", esquerda=5, direita=5,
                                                  vazias="filtrar", min_freq=3, min_freq_colocado=5, ordem="ll",
                                                  fronteira=fronteira, limite=1000)
        _json(saida / "raiox_colocacoes.json", col)
        esp = especificidades.calcular(voc, metas, filtro, particao="ano", por="lema", filtrar=True, min_freq=5,
                                       limiar=2.0, limite=50)
        _json(saida / "raiox_especificidades_ano.json", esp)
        _json(saida / "raiox_afc_ano.json", get("afc", particao="ano", por="lema", n_termos=100, selecao="freq",
                                               eixos=5, min_freq=5))
        _json(saida / "raiox_similitude.json", get("similitude", indice="coocorrencia", n_formas=60, arvore=True))
    print(f"exportação concluída em {time.time() - t0:.0f} s -> {saida}")


if __name__ == "__main__":
    main()
