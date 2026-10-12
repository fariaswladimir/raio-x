"""Frente 14 - LLM opcional (redação assistida). Desligado por padrão; as regras (D1) continuam sendo o caminho padrão.

Módulos: ``config`` (configuração global e chave de API no cofre do Windows), ``provedores`` (Ollama, Anthropic,
compatível com OpenAI), ``prompts``, ``gerador`` (monta o pedido, chama o provedor e confere o texto com ``verificar``).
"""
