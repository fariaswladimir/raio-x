"""Calcula os valores esperados do corpus de referência (EAP 12.1).

Script independente: NÃO importa o app. Lê os .md desta pasta e grava ``esperado.json``.

Regras (devem espelhar o que a análise do Raio-X deve fazer com estes textos):
1. Descarta tudo a partir do título "## References" (ou "## Referências") até o fim.
2. Remove as linhas de marcador de página ``<!-- página N -->``.
3. Remove as linhas de título (começam com ``#``).
4. Tokeniza em minúsculas com a regex r"[^\\W\\d_]+(?:['’-][^\\W\\d_]+)*"
   (palavras de letras, com apóstrofo ou hífen interno; números ficam de fora).
5. Conta: tokens por documento, total do corpus e as formas minúsculas "agent", "agents" e "tasks".

Uso: python calcular_esperado.py   (executar a partir de qualquer pasta)
"""
import json
import re
from pathlib import Path

PASTA = Path(__file__).resolve().parent
SAIDA = PASTA / "esperado.json"
PADRAO_TOKEN = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
PADRAO_REFERENCIAS = re.compile(r"^##\s+(References|Referências)\s*$", re.IGNORECASE | re.MULTILINE)
PADRAO_MARCADOR = re.compile(r"^\s*<!--\s*página\s+\d+\s*-->\s*$", re.IGNORECASE)
TERMOS_CONTADOS = ["agent", "agents", "tasks"]


def corpo(texto: str) -> str:
    """Texto do corpo: sem referências, marcadores de página e títulos."""
    m = PADRAO_REFERENCIAS.search(texto)
    if m:
        texto = texto[: m.start()]
    linhas = [
        ln for ln in texto.splitlines()
        if not PADRAO_MARCADOR.match(ln) and not ln.lstrip().startswith("#")
    ]
    return "\n".join(linhas)


def main() -> None:
    arquivos = sorted(PASTA.glob("[0-9][0-9][0-9]_*.md"))
    if len(arquivos) != 4:
        raise SystemExit(f"Esperados 4 documentos, encontrados {len(arquivos)}.")
    documentos = {}
    total = 0
    contagem_termos = {t: 0 for t in TERMOS_CONTADOS}
    for arquivo in arquivos:
        tokens = PADRAO_TOKEN.findall(corpo(arquivo.read_text(encoding="utf-8")).lower())
        documentos[arquivo.name] = {"tokens": len(tokens)}
        total += len(tokens)
        for t in tokens:
            if t in contagem_termos:
                contagem_termos[t] += 1
    esperado = {
        "descricao": "Valores esperados do corpus de referência (calcular_esperado.py, sem o app).",
        "regex": PADRAO_TOKEN.pattern,
        "documentos": documentos,
        "total_tokens": total,
        "termos": contagem_termos,
        "agent_mais_agents": contagem_termos["agent"] + contagem_termos["agents"],
    }
    SAIDA.write_text(json.dumps(esperado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(esperado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
