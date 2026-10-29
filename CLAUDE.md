# CLAUDE.md: orientação para o Claude neste repositório

**Raio-X de Textos:** sistema local (Windows) de análise textual de corpus para revisões de literatura (RSL/MLR). O usuário é gerente de projetos de P&D e pesquisador, e conduz uma revisão multivocal sobre agentes de IA no empreendedorismo. **Responda sempre em português do Brasil.**

## Comece por aqui
1. Leia o `EAP.md`: plano, decisões D1–D5 e D1-rev, status por entregável, riscos e histórico. O dicionário dos 74 entregáveis está em `docs/dicionario_eap.md`.
2. Situação (29/10/2026): MVP, v0.2, v0.3, v0.4 e v1.0 implementados, 816 testes. Pendências do usuário: 5.4 e 6.2 (aceitar a conferência feita no R, em `docs/validacao_cruzada.md`, no lugar do AntConc e do TXM?) e o teste dos pacotes em outra máquina e sem internet (11.1 e 11.2).
3. A última branch publicada pode não estar na `main`. Confira com `git branch -a` e `git log`.

## Como rodar e testar
- Para usar: `iniciar.bat`, que abre em http://localhost:8800. Para desenvolver: `.venv\Scripts\python -m uvicorn app.main:app --port 8800` (use outra porta se a 8800 estiver ocupada, e prefira `127.0.0.1` a `localhost`).
- Testes: a suíte completa leva cerca de 14 min (`.venv\Scripts\python -m pytest -q`). Durante o trabalho, rode só os arquivos de teste da área. Rode a suíte completa **uma vez no fim**, em segundo plano.
- Opcionais: `instalar_docling.bat` (PDF e OCR), `instalar_spacy.bat` e o Ollama em `http://127.0.0.1:11434`. O R fica em `C:/Program Files/R/<versão>/bin/Rscript.exe`.

## Arquitetura (resumo)
`app/main.py` (FastAPI) → `app/routers/*` → `app/services/*`. O frontend é uma página única em HTML/JS, sem dependências externas, em `frontend/`.
- `services/orquestrador.py`: 25 etapas registradas em `services/etapas/`. O cache usa o hash por **alvo** (`corpus` ou `doc:<id>`). Cada etapa declara `parametros_relevantes`, `depende_de` e `entrada_extra`.
- Áreas: `services/analises/` (estatística e PLN), `regras/` (comentários por regra e checagem de evidência), `llm/` (provedores, verificação, cache de prompt), `concordancia/` (kappa e alfa), `corpus/` (planilha, metadados, `.bib`), `coleta/` (protocolo de coleta), `busca/` (BM25 e RAG), `metodologia/` e `exportar/`.
- Dados: `projetos/<slug>/` (SQLite, cache, saídas) e `%APPDATA%\RaioX` (configuração). Variáveis de ambiente nos testes: `RAIOX_PROJETOS_DIR`, `RAIOX_CONFIG_DIR`.

## Regras do projeto (não negociáveis)
- **A pasta de artigos só é lida, nunca escrita.** Não grave nada em `C:\Users\...\Documents`.
- **`projetos/` é dado do usuário.** Não altere, não execute e não apague projetos que você não criou (por exemplo `mlr-agentes`). Para testar, crie `teste-<algo>` e apague no fim.
- **Rastreabilidade:** todo número e todo comentário levam documento, página e trecho. Nunca invente valor: quando não houver evidência, use "não encontrado".
- **LLM é opcional e vem desligado (D1-rev).** Texto de LLM entra como "sugerido", passa por `verificar()` (números, citações e trechos literais) e só vai ao laudo se o humano aceitar. Em testes, simule o LLM; **não faça chamadas pagas reais**.
- **Claude via SDK oficial `anthropic`.** Use os IDs exatos `claude-opus-5-5`, `claude-sonnet-5-5` e `claude-haiku-5-5`. Não envie `temperature`, `thinking: disabled` nem `budget_tokens`. Mantenha o prefixo estável em cache (`llm/cache_prompt.py`).
- **Segredos:** a chave fica no keyring do Windows e só aparece mascarada. O `scripts/empacotar.py` exclui `projetos/`, segredos, configurações e arquivos gerados do corpus; mantenha isso (há teste).
- **Direitos autorais:** não copie texto do corpus para `docs/` nem para o repositório. Números agregados e listas de termos podem.
- **Referências bibliográficas:** a fonte única é `app/services/metodologia/catalogo.yaml`. Referências compiladas de memória levam "conferir antes de citar". Rode `tests/test_metodologia.py` depois de editar.
- **CSV e XLSX:** passe pelo helper de `services/exportar/planilhas.py`, que neutraliza fórmulas.
- Idioma do código: comentários, mensagens, interface e documentação em **pt-BR**. Siga o estilo dos módulos vizinhos (docstring com convenções, funções puras para a estatística, depois `calcular()`).

## Fluxo de trabalho que o usuário espera
- **EAP sempre atualizada:** ao concluir uma entrega, atualize a linha do entregável no `EAP.md` (status ✅/🟨/⬜ e evidência), a linha de Status no topo e o "10. Histórico". Atualize também `docs/dicionario_eap.md` e `docs/eap.html`. **Mostre a EAP atualizada** ao usuário ao fim de cada execução.
- **Não use `|` dentro das células das tabelas do `EAP.md`:** isso quebra a tabela. Use "/" no lugar.
- **Escolha de modelo por complexidade:** Opus para estatística delicada (onde um erro passa despercebido); Sonnet para integração, interface e documentação; Haiku para tarefas mecânicas. Agrupe tarefas parecidas num só agente.
- Com agentes em paralelo: só edições pequenas e aditivas nos arquivos compartilhados (`app/main.py`, `routers/*`, `frontend/index.html`, `etapas/__init__.py`, `parametros.py`, `catalogo.yaml`, `EAP.md`), relendo cada arquivo antes de editar.
- **Commit e push só quando o usuário pedir.** Na `main`, crie uma branch antes.

## Armadilhas conhecidas
- A estatística segue convenções documentadas nos módulos e em `docs/nota_metodologica.md`: G² de 2 células na keyness, janelas unidas nas colocações, Lafon com teto de ±50, sinal da AFC, regra de ramos pequenos no Reinert. Não "corrija" essas convenções sem ler a nota e a validação cruzada.
- A `simplemma` gera alguns lemas inválidos em inglês. Use as exceções em `parametros.lematizacao.excecoes` ou o spaCy.
- Ao mudar o significado de um parâmetro, mantenha a chave de cache correta. O caso A→B→A já tem teste.
- Mudar a ordem das etapas afeta `tests/test_frente1.py::test_api_execucoes_e_documentos`.
- Use `PYTHONIOENCODING=utf-8` ao imprimir texto com acentos no shell do Windows.

## Documentos úteis
`README.md` · `docs/guia_de_uso.md` · `docs/instalacao.md` · `docs/manual_outro_computador.md` · `docs/offline.md` · `docs/nota_metodologica.md` · `docs/validacao_cruzada.md` · `docs/validacao_antconc.md` · `docs/validacao_iramuteq.md` · `docs/dicionario_eap.md` · `docs/eap.html`
