# Modo totalmente offline (EAP 11.2)

O Raio-X instala e roda em um computador Windows **sem internet**. Este documento lista tudo o que usa a rede, quando, quanto baixa e como o modo offline trata cada caso.

## Como usar

**Em um computador com internet** (o mesmo Python 3.12 do Raio-X, com o `.venv` e o Docling instalados):

```
.venv\Scripts\python scripts\preparar_offline.py --variante-sem-docling
```

Gera dois pacotes em `dist\`:

| Arquivo | Conteúdo |
|---|---|
| `raio-x-offline-<versao>-<data>.zip` | Código + rodas (wheels) de tudo, inclusive Docling e PyTorch CPU + modelos do Docling + modelos do spaCy |
| `raio-x-offline-sem-docling-<versao>-<data>.zip` | Sem Docling/PyTorch/modelos: só `.md` e `.txt` (e spaCy). Bem menor |

**No computador sem internet:**

1. Instale o **Python 3.12 (64 bits)**, marcando *Add python.exe to PATH* (baixe o instalador antes e leve por pendrive).
2. Extraia o `.zip` em uma pasta local (ex.: `C:\Raio-X`).
3. Dê dois cliques em `instalar_offline.bat`. Ele cria o `.venv`, roda `pip install --no-index --find-links wheels`, instala os modelos do spaCy, grava `raiox_offline.flag` e confere a instalação.
4. Dê dois cliques em `iniciar.bat`. O selo **Offline** aparece no topo da tela.

Observação: as rodas são para **CPython 3.12 / win_amd64**. Com outra versão do Python, o `instalar_offline.bat` avisa e para. (O `iniciar.bat` comum aceita Python 3.11 ou mais novo, porque baixa a roda certa.)

## O que o modo offline faz

O modo liga quando existe `raiox_offline.flag` na pasta do Raio-X, **ou** a variável `RAIOX_OFFLINE=1`, **ou** `{"modo_offline": true}` em `%APPDATA%\RaioX\config_offline.json`. `RAIOX_OFFLINE=0` desliga mesmo com a flag.

1. `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1` são definidos **antes** de importar o Docling (`app/main.py`).
2. O Docling recebe `artifacts_path` = `modelos\docling` (ou `DOCLING_ARTIFACTS_PATH`) nas opções do pipeline de PDF. Com `artifacts_path` o Docling e o RapidOCR não resolvem nem baixam nada.
3. A consulta online de metadados (Crossref/OpenAlex) responde 409 com a mensagem "Modo offline: a consulta online de metadados está desativada." e a caixa da tela fica desmarcada e bloqueada.
4. Provedores de LLM **remotos** (Anthropic, OpenAI-compatível) são recusados com a mensagem "Modo offline: provedores de LLM remotos ... estão desativados." (categoria `offline`; as opções ficam desabilitadas em Configurações). **Ollama** (neste computador) continua permitido.
5. O selo "Offline" vem de `GET /api` (campo `offline`); `GET /api/offline` mostra a origem do modo e a pasta de modelos.

## Inventário de dependências de rede

### Na instalação

| O quê | Quando | Tamanho | Tratamento offline |
|---|---|---|---|
| Rodas do núcleo e do spaCy (`pip install -r requirements.txt` / `requirements-spacy.txt`) | `iniciar.bat` (1ª vez e a cada início: `pip install -q -r`), `instalar_spacy.bat` | ~120 MB (já com os 2 modelos do spaCy) | `preparar_offline.py` baixa com `pip download --only-binary=:all: --platform win_amd64 --python-version 3.12`; `instalar_offline.bat` instala com `--no-index --find-links wheels`; com a flag, `iniciar.bat` **não** roda mais o pip |
| PyTorch/torchvision CPU | `instalar_docling.bat` (índice `download.pytorch.org/whl/cpu`) | ~130 MB | Baixado pelo mesmo índice em `preparar_offline.py` e guardado em `wheels\` |
| Docling, RapidOCR, onnxruntime | `instalar_docling.bat` | ~90 MB (com o PyTorch: ~290 MB no total) | Rodas em `wheels\` (`requirements-docling.txt`) |
| Modelos do spaCy `en_core_web_sm`, `pt_core_news_sm` | `instalar_spacy.bat` (`spacy download`, GitHub) | ~13 MB cada | Baixados como rodas (GitHub releases, 3.8.0) e instalados por nome com `--no-index` |
| Python 3.12 | Antes de tudo | ~27 MB | Fora do pacote: leve o instalador do python.org por pendrive |
| Dados do `simplemma` (lematização) | — | 19 MB | **Já dentro da roda** (59 arquivos em `simplemma\dictionaries`): nenhum download |
| Léxico do VADER (sentimento) | — | pequeno | Já dentro do pacote `vaderSentiment` |

### Em tempo de execução

| O quê | Quando | Tamanho | Tratamento offline |
|---|---|---|---|
| Modelos do Docling (layout `docling-layout-heron`, tabelas `docling-models/TableFormer`) | 1ª conversão de PDF/DOCX (Hugging Face) | ~510 MB (tabelas ~340 MB, layout ~165 MB); o `docling-tools` traz também a variante ONNX do layout (+165 MB), total de ~700 MB com o OCR | `docling-tools models download -o dist\offline\modelos\docling`; no modo offline: `artifacts_path` + `HF_HUB_OFFLINE=1` |
| Modelos do RapidOCR (PP-OCR det/rec/cls, onnx) | 1ª conversão com OCR | ~31 MB | Incluídos em `modelos\docling\RapidOcr` (idiomas en, pt, es); lidos via `artifacts_path` |
| Consulta de metadados por DOI (Crossref, OpenAlex) | Só se o usuário marca "consulta online" e informa e-mail | KB | Desativada (409 + caixa bloqueada) |
| LLM Anthropic / OpenAI-compatível | Só se o usuário liga o LLM (vem desligado) e escolhe o provedor | — | Recusado com mensagem; opções desabilitadas em Configurações |
| Ollama (LLM e embeddings) | Só se escolhido; `127.0.0.1:11434` | — | **Permitido** (roda neste computador; o modelo deve já estar baixado com `ollama pull`). Uma URL de outro host seria rede e é responsabilidade de quem configura |
| `keyring` (cofre de credenciais) | Chave de API | — | Local (Windows Credential Manager); não usa rede |
| Frontend (HTML/JS/CSS) | Navegador em `localhost:8800` | — | Sem CDN, sem fontes externas: tudo servido pelo próprio app (loopback) |

Nada mais: o código não faz `pip install`, `spacy download`, nem `nltk.download` em tempo de execução; telemetria do Hugging Face fica desligada no modo offline (`HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK`).

## Verificação

- `scripts\verificar_offline.py --rapido` (chamado por `instalar_offline.bat`): confere núcleo, simplemma, spaCy com os dois modelos, modelos do Docling e RapidOCR.
- `scripts\verificar_offline.py --corpus tests\corpus_referencia --pdf arquivo.pdf`: liga o modo offline, instala a **guarda de rede** (qualquer conexão fora do loopback, inclusive DNS, vira erro e é contada) e roda o pipeline completo em um projeto `teste-off`, apagado ao fim. Sai com código 1 se algo falhar ou houver tentativa de rede.
- Testes: `tests\test_frente112_offline.py` usa a fixture `sem_rede` (`tests\guarda_rede.py`) e roda o pipeline do corpus de referência e de um PDF pequeno sem rede (o do PDF é pulado, com o motivo, se os modelos do Docling não estiverem em cache).

## Pendências e limites

- Sem pinagem de versões: as rodas baixadas são as mais novas disponíveis no dia (`requirements.txt` não fixa versões). O pacote offline é uma "foto" daquele dia; para reproduzir exatamente, gere um `pip freeze` e fixe-o antes de preparar.
- Pacote com Docling: cerca de 1,1 GB (rodas 425 MB, modelos 700 MB); instalado, o `.venv` fica com cerca de 1,7 GB e os modelos mais 700 MB.
- O pacote não inclui o instalador do Python.
