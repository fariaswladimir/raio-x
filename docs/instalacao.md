# Instalação do Raio-X em outro computador

> Manual completo (GitHub, .zip, offline, migração de projetos, R e Claude Code): [manual_outro_computador.md](manual_outro_computador.md).

## Requisitos
- Windows 10 ou 11.
- Python 3.11 ou mais novo, de [python.org](https://www.python.org/downloads/). Na instalação, marque **Add python.exe to PATH**.
- Espaço em disco: cerca de 1 GB sem o Docling; cerca de 3 GB com o Docling.
- Internet: na primeira execução do `iniciar.bat` (baixa as dependências). Para PDF e DOCX, também na primeira conversão, quando o Docling baixa os modelos de layout. **Sem internet:** use o pacote offline (seção abaixo).

## Passo a passo
1. Extraia o `.zip` em uma pasta local, por exemplo `C:\Raio-X`. Evite pastas sincronizadas pelo OneDrive (Documentos e Área de Trabalho, se estiverem sob o OneDrive).
2. Dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o `.venv` e instala as dependências, o que leva alguns minutos. O navegador abre em http://localhost:8800.
3. Só se for ler PDF ou DOCX: dê dois cliques em `instalar_docling.bat` (baixa cerca de 2 GB). Ele precisa do passo 2 concluído antes.
4. Para encerrar, feche a janela preta do `iniciar.bat` (ou tecle Ctrl+C nela).

## Instalação sem internet (modo offline)
Para um computador **sem internet**, gere o pacote offline em um computador **com** internet (o mesmo Python 3.12, com o `.venv` e o Docling instalados):

```
.venv\Scripts\python scripts\preparar_offline.py --variante-sem-docling
```

Saem dois arquivos em `dist\`: `raio-x-offline-<versao>-<data>.zip` (cerca de 1,1 GB: rodas de tudo, inclusive PyTorch CPU e Docling, mais os modelos do Docling e do spaCy) e `raio-x-offline-sem-docling-<versao>-<data>.zip` (cerca de 130 MB: só `.md` e `.txt`). Leve o `.zip` por pendrive e, no computador sem internet:

1. Instale o **Python 3.12 (64 bits)** com *Add python.exe to PATH* (o `instalar_offline.bat` exige o 3.12, porque as rodas são para CPython 3.12).
2. Extraia o `.zip` em uma pasta local e dê dois cliques em `instalar_offline.bat`. Ele instala tudo com `pip --no-index` a partir de `wheels\`, grava `raiox_offline.flag` e confere a instalação.
3. Dê dois cliques em `iniciar.bat`. O selo **Offline** aparece no topo da tela; a consulta online de metadados e os LLMs remotos ficam desativados (o Ollama local continua).

O que usa rede, quando e como cada caso é tratado: [offline.md](offline.md). Para sair do modo offline, apague `raiox_offline.flag`.

## Verificar a instalação
Na pasta do Raio-X, no Prompt de Comando:

```
.venv\Scripts\python -m pytest -q tests\test_corpus_referencia.py
```

O resultado esperado é sem falhas. Os testes usam o corpus de referência incluído no pacote.

## Atualizar
Feche o Raio-X e extraia o `.zip` novo por cima da pasta antiga, substituindo os arquivos. **Não apague `projetos\`**: ela guarda os seus projetos e é mantida. Depois, rode `iniciar.bat` normalmente.

## Levar projetos para outro computador
Copie a pasta `projetos\<nome>` do computador antigo para `projetos\` do novo. Ela tem o banco `projeto.sqlite`, os parâmetros, o cache e as saídas.
A pasta dos artigos precisa existir no novo computador **no mesmo caminho** guardado no projeto. Hoje não há tela nem API para trocar esse caminho. Se ele não existir, a execução para com "Pasta de origem não encontrada". Opções:
- copiar os artigos para o mesmo caminho do computador antigo; ou
- trocar o caminho direto na tabela `projeto` do `projeto.sqlite`, com uma cópia de segurança antes.

## Problemas comuns
- **"Python nao encontrado"**: instale o Python 3.11+ marcando *Add python.exe to PATH*, feche a janela e rode de novo.
- **"versao mais antiga que a 3.11"**: instale uma versão nova do Python. Se houver mais de uma, deixe a nova no PATH.
- **Falha ao instalar dependências**: confira a internet. Antivírus ou proxy corporativo podem bloquear o pip. Depois, rode de novo.
- **`.venv` de outro computador ou instalação interrompida**: apague a pasta `.venv` e rode `iniciar.bat`.
- **Navegador não abre**: acesse http://localhost:8800 manualmente.
- **Porta 8800 ocupada**: feche outra janela do Raio-X.
