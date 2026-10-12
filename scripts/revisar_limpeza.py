"""EAP 3.3: gera a revisão por amostra da limpeza de texto de um projeto (docs/revisao_limpeza.md).

Uso (a partir da pasta raio-x):
    .venv\\Scripts\\python scripts\\revisar_limpeza.py <slug-do-projeto> [--n 10] [--semente 26]
        [--saida docs\\revisao_limpeza.md] [--projetos-dir DIR]

Sorteia N documentos já convertidos (semente fixa; estratificado por ``grupo``: sorteio em rodízio entre os grupos, na
ordem alfabética) e, para cada um, mostra o que a limpeza (``app/services/limpeza_texto.py``) fez, para um humano conferir:

- linhas repetidas (cabeçalho/rodapé) e números de página removidos, com as páginas;
- hifenizações corrigidas (antes -> depois), amostra;
- URLs / e-mails / DOI removidos (contagem);
- os primeiros 200 caracteres de uma página antes e depois da limpeza;
- a fronteira das referências: últimos 150 caracteres antes e primeiros 150 depois;
- uma linha de checklist para marcar à mão.

Só lê o projeto (cache/md e o banco); a única coisa escrita é o arquivo de saída.
"""
import argparse
import os
import random
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PADRAO_SAIDA = RAIZ / "docs" / "revisao_limpeza.md"
AMOSTRAS_HIFEN = 6


def sortear(docs: list, n: int, semente: int) -> list:
    """Amostra estratificada por grupo, reprodutível: embaralha cada grupo com a semente e retira em rodízio."""
    por_grupo: dict[str, list] = {}
    for d in sorted(docs, key=lambda d: d.arquivo):
        por_grupo.setdefault(d.grupo or "sem grupo", []).append(d)
    rnd = random.Random(semente)
    filas = {g: rnd.sample(lista, len(lista)) for g, lista in sorted(por_grupo.items())}
    escolhidos = []
    while len(escolhidos) < n and any(filas.values()):
        for g in sorted(filas):
            if filas[g] and len(escolhidos) < n:
                escolhidos.append(filas[g].pop())
    return sorted(escolhidos, key=lambda d: d.arquivo)


def _uma_linha(texto: str, limite: int, do_fim: bool = False) -> str:
    t = re.sub(r"\s+", " ", texto).strip()
    if len(t) > limite:
        t = ("…" + t[-limite:]) if do_fim else (t[:limite] + "…")
    return t


def analisar(md: str, parametros: dict) -> dict:
    """Tudo o que o relatório mostra sobre um documento (função pura, usada também nos testes)."""
    from app.services import limpeza_texto as lt
    from app.services.texto import COMENTARIO_HTML, paginar, texto_visivel

    linhas = lt.extrair_linhas(md)
    lt.remover_repetidas(linhas)
    removidas: dict[str, dict] = {}
    for l in linhas:
        if l.removida:
            item = removidas.setdefault(l.texto, {"texto": l.texto, "paginas": []})
            item["paginas"].append(l.pagina)

    # texto que entra na limpeza de cada página (o mesmo montado por ``processar``) para achar as hifenizações
    por_pagina: dict[int | None, list[str]] = {}
    for l in linhas:
        if not l.removida and l.tipo != "titulo":
            por_pagina.setdefault(l.pagina, []).append(l.texto if l.tipo != "vazio" else "")
    hifens = []
    for pg, ls in por_pagina.items():
        texto = "\n".join(ls)
        for m in lt._RE_HIFEN.finditer(texto):
            antes = m.group(0).replace("\n", "↵")
            if texto[max(0, m.start() - 1):m.start()] == "-":  # "state-of-the-\nart": composto, o hífen fica
                depois = f"{m.group(1)}-{m.group(2)}"
            else:
                depois = lt.corrigir_hifenizacao(m.group(0))[0]
            hifens.append({"pagina": pg, "antes": antes, "depois": depois.strip()})

    brutos_urls = sum(len(p.findall(COMENTARIO_HTML.sub(" ", md))) for p in (lt._RE_EMAIL, lt._RE_URL))
    dados = lt.processar(md, parametros)
    est = dados["estatisticas"]

    # página de amostra: a 2ª (a 1ª costuma ser capa/título); sem marcadores, o texto todo
    paginas = paginar(md)
    pagina_amostra = None
    antes_pagina = md
    if paginas:
        # primeira página, a partir da 2ª, com texto de verdade (a 1ª costuma ser capa; algumas ficam em branco)
        candidatas = paginas[1:] + paginas[:1]
        numero, texto = next(((n, t) for n, t in candidatas if len(texto_visivel(t).strip()) >= 200), candidatas[0])
        pagina_amostra, antes_pagina = numero, texto
    depois_pagina = "\n\n".join(b["texto"] for b in dados["blocos"] if pagina_amostra is None or b["pagina"] == pagina_amostra)

    # fronteira das referências
    blocos = dados["blocos"]
    fronteira = None
    for i, b in enumerate(blocos):
        if b["secao"] == "referencias":
            antes_ref = "\n\n".join(x["texto"] for x in blocos[:i])
            fronteira = {"antes": antes_ref[-150:], "depois": b["texto"][:150], "titulo": b["titulo_secao"], "pagina": b["pagina"]}
            break
    return {
        "repetidas": list(removidas.values()), "hifenizacoes": hifens, "urls_brutas": brutos_urls,
        "estatisticas": est, "pagina_amostra": pagina_amostra,
        "antes_pagina": antes_pagina, "depois_pagina": depois_pagina, "fronteira": fronteira,
        "secoes": dados["secoes"],
    }


CHECKLIST = ("- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   "
             "- [ ] Fronteira das referências: ok   — Observações: ")


def _secao_documento(doc, a: dict) -> list[str]:
    est = a["estatisticas"]
    q = [f"### {doc.arquivo}", "",
         f"Grupo: {doc.grupo or 'sem grupo'} · palavras: {est['palavras_total']} (corpo {est['palavras_corpo']}, "
         f"referências {est['palavras_referencias']}) · detecção de referências: {est['metodo_deteccao']}", ""]
    # 1. repetidas
    q.append(f"**Linhas removidas como cabeçalho/rodapé ou nº de página:** {est['linhas_repetidas_removidas']} "
             f"(números de página: {est['numeros_pagina_removidos']})")
    if a["repetidas"]:
        for r in sorted(a["repetidas"], key=lambda r: -len(r["paginas"]))[:12]:
            pgs = ", ".join(str(p) for p in r["paginas"][:8]) + ("…" if len(r["paginas"]) > 8 else "")
            q.append(f"- `{_uma_linha(r['texto'], 90)}` — {len(r['paginas'])}× (págs. {pgs})")
    else:
        q.append("- (nenhuma)")
    q.append("")
    # 2. hifenização
    total_h = est["hifenizacoes_corrigidas"]
    q.append(f"**Hifenizações corrigidas:** {total_h} no total ({len(a['hifenizacoes'])} dentro da página; "
             f"{max(0, total_h - len(a['hifenizacoes']))} na virada de página)")
    for h in a["hifenizacoes"][:AMOSTRAS_HIFEN]:
        q.append(f"- p. {h['pagina']}: `{h['antes']}` → `{h['depois']}`")
    if not a["hifenizacoes"]:
        q.append("- (nenhuma amostra)")
    q.append("")
    # 3. URLs
    q.append(f"**URLs / e-mails / DOI removidos:** {est['urls_removidas']} (no texto bruto: {a['urls_brutas']} URLs e e-mails fora de comentários)")
    q.append("")
    # 4. antes/depois
    rotulo = f"página {a['pagina_amostra']}" if a["pagina_amostra"] is not None else "texto todo"
    q.append(f"**Primeiros 200 caracteres ({rotulo}):**")
    q.append(f"- antes: `{_uma_linha(a['antes_pagina'], 200)}`")
    q.append(f"- depois: `{_uma_linha(a['depois_pagina'], 200)}`")
    q.append("")
    # 5. fronteira
    f = a["fronteira"]
    if f:
        q.append(f"**Fronteira das referências** (título: {f['titulo'] or '(sem título)'}, p. {f['pagina']}):")
        q.append(f"- últimos 150 caracteres antes: `{_uma_linha(f['antes'], 150, do_fim=True)}`")
        q.append(f"- primeiros 150 caracteres depois: `{_uma_linha(f['depois'], 150)}`")
    else:
        q.append("**Fronteira das referências:** não detectada neste documento.")
    q += ["", CHECKLIST, ""]
    return q


def gerar_revisao(slug: str, n: int = 10, semente: int = 26, saida: Path | None = None) -> Path:
    """Gera o markdown da revisão para o projeto ``slug`` e devolve o caminho do arquivo."""
    from sqlalchemy import select

    from app.database import pasta_do_projeto, projeto_existe, sessao_do_projeto
    from app.models import Documento
    from app.services import parametros as svc_parametros

    if not projeto_existe(slug):
        raise SystemExit(f"Projeto '{slug}' não encontrado.")
    pasta = pasta_do_projeto(slug)
    params = svc_parametros.carregar(pasta)
    db = sessao_do_projeto(slug)
    try:
        docs = [d for d in db.scalars(select(Documento).where(Documento.status != "removido").order_by(Documento.arquivo))
                if d.caminho_md and (pasta / d.caminho_md).is_file() and not d.excluido]
        escolhidos = sortear(docs, n, semente)
        grupos = sorted({d.grupo or "sem grupo" for d in docs})
        linhas = [
            f"# Revisão por amostra da limpeza de texto — projeto `{slug}`", "",
            f"Amostra de {len(escolhidos)} de {len(docs)} documentos convertidos (semente {semente}; estratificada por grupo: "
            f"{', '.join(grupos)}). Gerado por `scripts/revisar_limpeza.py`; marque as caixas à mão e anote os problemas.", "",
            "Legenda: *antes* = Markdown convertido (cache/md); *depois* = texto limpo (3.3).", "",
        ]
        for d in escolhidos:
            md = (pasta / d.caminho_md).read_text(encoding="utf-8")
            linhas += _secao_documento(d, analisar(md, params))
    finally:
        db.close()
    destino = Path(saida) if saida else PADRAO_SAIDA
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(linhas), encoding="utf-8", newline="\n")
    return destino


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Revisão por amostra da limpeza de texto (EAP 3.3).")
    ap.add_argument("slug", help="slug do projeto (pasta em projetos/)")
    ap.add_argument("--n", type=int, default=10, help="documentos na amostra (padrão 10)")
    ap.add_argument("--semente", type=int, default=26, help="semente do sorteio (padrão 26)")
    ap.add_argument("--saida", type=Path, default=None, help="arquivo de saída (padrão docs/revisao_limpeza.md)")
    ap.add_argument("--projetos-dir", type=Path, default=None, help="pasta de projetos (padrão projetos/)")
    a = ap.parse_args(argv)
    if a.projetos_dir:
        os.environ["RAIOX_PROJETOS_DIR"] = str(a.projetos_dir)
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Revisão gravada em {gerar_revisao(a.slug, a.n, a.semente, a.saida)}")


if __name__ == "__main__":
    main()
