# Raio-X de Textos

Sistema local de análise textual de corpus (sem LLM por padrão; redação assistida opcional em Configurações, com conferência e revisão humana). Lê uma pasta de artigos
(somente leitura) e, nas próximas frentes, produz um laudo comentado com
evidências. Plano completo e EAP em [EAP.md](EAP.md). Estado atual: **Frente 1 (Fundação)**.

## Como rodar

Dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o `.venv`, instala as
dependências, sobe o servidor e abre http://localhost:8800.

Manualmente:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8800
```

Na página: informe o nome do projeto e o caminho da pasta de artigos, crie o
projeto e clique em **Executar**.

Guia de uso (1 página, para quem não programa): [docs/guia_de_uso.md](docs/guia_de_uso.md).

Nota metodológica (o que é calculado, convenções e referências): [docs/nota_metodologica.md](docs/nota_metodologica.md).
Instalação em outro computador: [docs/instalacao.md](docs/instalacao.md).

## Testes

```
.venv\Scripts\python -m pytest
```

## Estrutura

```
raio-x/
├── iniciar.bat
├── app/
│   ├── main.py  config.py  database.py  models.py  schemas.py
│   ├── routers/   projetos.py  pipeline.py
│   └── services/
│       ├── orquestrador.py     etapas registradas + cache por hash
│       ├── parametros.py       parametros.json versionado
│       └── etapas/varredura.py
├── frontend/      index.html  app.js  styles.css
├── tests/
└── projetos/<slug>/            (ignorado pelo git)
    ├── projeto.sqlite  parametros.json  parametros_historico/
    ├── cache/
    └── saidas/
```

- `RAIOX_PROJETOS_DIR` troca a pasta de projetos (usado nos testes).
- A pasta de artigos nunca é alterada; tudo que o sistema gera fica em `projetos/<slug>/`.
- Para criar uma etapa nova, veja a docstring de `app/services/orquestrador.py`.
