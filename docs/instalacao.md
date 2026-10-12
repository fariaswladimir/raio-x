# Instalação do Raio-X em outro computador

## Requisitos
- Windows 10 ou 11.
- Python 3.11 ou mais novo, de [python.org](https://www.python.org/downloads/). Na instalação, marque **Add python.exe to PATH**.
- Espaço em disco: cerca de 1 GB sem o Docling; cerca de 3 GB com o Docling.
- Internet: na primeira execução do `iniciar.bat` (baixa as dependências). Para PDF e DOCX, também na primeira conversão, quando o Docling baixa os modelos de layout.

## Passo a passo
1. Extraia o `.zip` em uma pasta local, por exemplo `C:\Raio-X`. Evite pastas sincronizadas pelo OneDrive (Documentos e Área de Trabalho, se estiverem sob o OneDrive).
2. Dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o `.venv` e instala as dependências, o que leva alguns minutos. O navegador abre em http://localhost:8800.
3. Só se for ler PDF ou DOCX: dê dois cliques em `instalar_docling.bat` (baixa cerca de 2 GB). Ele precisa do passo 2 concluído antes.
4. Para encerrar, feche a janela preta do `iniciar.bat` (ou tecle Ctrl+C nela).

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
