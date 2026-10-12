"""14.3 - Prompts (em português) para redigir um parágrafo a partir de dados já calculados."""
import json

SYSTEM = """Você redige um parágrafo para uma revisão sistemática / multivocal da literatura, em português acadêmico, a partir de dados já calculados por um programa de análise textual.

Regras obrigatórias:
1. Use SOMENTE os números e os trechos fornecidos na mensagem. Não invente números, fontes, autores, anos nem afirmações causais.
2. Mantenha cada número exatamente como foi dado (mesmo valor e mesma precisão). Não calcule novos números (somas, médias, razões, percentuais) que não estejam nos dados.
3. Cite os trechos de evidência no formato (rótulo, p. N), copiando o rótulo e a página exatamente como fornecidos. Se transcrever um trecho entre aspas, copie-o literalmente, sem alterar nenhuma palavra.
4. Siga a estrutura e o estilo do parágrafo-modelo fornecido, adaptando-o aos dados. Respeite as notas do modelo sobre o que NÃO pode ser afirmado.
5. Não afirme causalidade, intenção dos autores nem generalizações para fora do corpus analisado.
6. Responda apenas com o parágrafo, em texto corrido: sem título, sem listas, sem comentários, sem explicar o que fez."""


def _compacto(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def montar_usuario(modelo: dict, metricas: dict, evidencias: list[dict], instrucoes: str | None = None) -> str:
    """Mensagem do usuário: modelo + notas, métricas (JSON compacto), até 5 trechos e instruções opcionais."""
    ev = [{"n": i + 1, "rotulo": e["rotulo"], "pagina": e["pagina"], "trecho": e["trecho"]} for i, e in enumerate(evidencias)]
    partes = [
        f"## Análise\n{modelo['analise']} — modelo \"{modelo['titulo']}\" (estilo: {modelo['estilo']}; idioma: {modelo.get('idioma', 'pt')})",
        f"## Parágrafo-modelo (estrutura e estilo a seguir)\n{modelo['texto_modelo']}",
        f"## Notas do modelo (o que NÃO afirmar)\n{modelo.get('notas') or '(nenhuma)'}",
        f"## Métricas calculadas (JSON; use só estes números)\n{_compacto(metricas)}",
        "## Trechos de evidência (cite como (rótulo, p. N))\n" + (_compacto(ev) if ev else "(nenhum trecho disponível: não cite trechos)"),
    ]
    if instrucoes and instrucoes.strip():
        partes.append(f"## Instruções adicionais do usuário\n{instrucoes.strip()}")
    partes.append("Escreva agora o parágrafo.")
    return "\n\n".join(partes)
