# Manual: levar o Raio-X para outro computador

Este manual cobre os três jeitos de instalar o Raio-X em outro computador, como levar seus projetos junto e como continuar o desenvolvimento com o Claude Code na máquina nova. Os detalhes do pacote `.zip` e do modo offline estão em [instalacao.md](instalacao.md) e [offline.md](offline.md).

---

## 1. Escolha o caminho

| Situação | Caminho | Seção |
|---|---|---|
| O computador tem internet e você quer receber atualizações (ou continuar desenvolvendo) | **GitHub** (`git clone`) | 2 |
| O computador tem internet, mas não tem Git, ou é só para usar | **Pacote `.zip`** | 3 |
| O computador **não** tem internet | **Pacote offline** | 4 |

Em qualquer caminho, você precisa do **Windows 10 ou 11** e do **Python 3.11 ou mais novo** ([python.org](https://www.python.org/downloads/)). Na instalação do Python, marque **Add python.exe to PATH**. Para o pacote offline, use o **Python 3.12 de 64 bits**.

---

## 2. Pelo GitHub (recomendado)

Repositório: `https://github.com/fariaswladimir/raio-x`.

1. Instale o **Git for Windows** ([git-scm.com](https://git-scm.com/download/win)), se ainda não tiver.
2. Abra o Prompt de Comando numa pasta **fora do OneDrive** (por exemplo `C:\dev`) e clone o repositório:

   ```
   git clone https://github.com/fariaswladimir/raio-x.git
   cd raio-x
   ```

3. Dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria o `.venv`, instala as dependências (alguns minutos) e abre http://localhost:8800.
4. Componentes opcionais, conforme o uso:
   - **PDF e DOCX** (Docling e OCR, cerca de 2 GB): dê dois cliques em `instalar_docling.bat`.
   - **Classes gramaticais e entidades** (spaCy, cerca de 30 MB): dê dois cliques em `instalar_spacy.bat`.
5. Confira a instalação:

   ```
   .venv\Scripts\python -m pytest -q tests\test_corpus_referencia.py
   ```

**Para atualizar depois:** feche o Raio-X, rode `git pull` na pasta e abra o `iniciar.bat` de novo. A pasta `projetos\` não vai para o Git e não é afetada.

> Se o trabalho mais recente estiver numa branch (por exemplo `validacao-cruzada-r`), entre nela com `git checkout <nome-da-branch>` ou junte-a à `main` no GitHub.

---

## 3. Pelo pacote `.zip`

1. No computador atual, gere o pacote:

   ```
   .venv\Scripts\python scripts\empacotar.py
   ```

   O arquivo sai em `dist\raio-x-<versao>-<data>.zip` (cerca de 0,7 MB, só o código). Ele **nunca** inclui seus projetos, suas chaves nem arquivos gerados do seu corpus.
2. Leve o `.zip` para o outro computador, extraia numa pasta local (fora do OneDrive) e siga os passos 3 a 5 da seção 2.

---

## 4. Sem internet (pacote offline)

1. No computador **com** internet, que já tem o `.venv` e o Docling instalados, gere os pacotes:

   ```
   .venv\Scripts\python scripts\preparar_offline.py --variante-sem-docling
   ```

   Saem dois arquivos em `dist\`: um com o Docling (cerca de 1,1 GB) e um sem o Docling (cerca de 130 MB, só para `.md` e `.txt`).
2. Leve o `.zip` por pendrive. No computador sem internet, instale o **Python 3.12 (64 bits)**, extraia o pacote e dê dois cliques em **`instalar_offline.bat`**.
3. Abra o **`iniciar.bat`**. O selo **Offline** aparece no topo da tela.

---

## 5. Levar seus projetos (por exemplo, `mlr-agentes`)

Cada projeto é uma pasta autocontida em `projetos\<nome>` (banco `projeto.sqlite`, `parametros.json`, `cache\` e `saidas\`).

1. Feche o Raio-X nos dois computadores.
2. Copie `projetos\<nome>` do computador antigo para `projetos\` do novo.
3. **A pasta dos artigos precisa existir no mesmo caminho** que o projeto guardou, por exemplo `C:\Users\<você>\Documents\...\Corpus_Docling`. Há duas opções:
   - copiar os artigos para exatamente o mesmo caminho; ou
   - trocar o caminho no banco. Faça antes uma cópia de segurança do `projeto.sqlite` e rode:

     ```
     .venv\Scripts\python -c "import sqlite3; c=sqlite3.connect(r'projetos\NOME\projeto.sqlite'); c.execute('update projeto set pasta_origem=?', (r'C:\NOVO\CAMINHO',)); c.commit()"
     ```

4. Abra o Raio-X e clique em **Executar**. O cache é reaproveitado no que não mudou.

> O nome de usuário do Windows costuma mudar o caminho (`C:\Users\<nome>\...`). Confira antes de copiar.

---

## 6. Reconfigurar o que fica fora do projeto

Estes itens ficam em `%APPDATA%\RaioX` e no Cofre de Credenciais do Windows. **Não vão junto** com a cópia dos projetos e precisam ser refeitos:

| Item | Como refazer |
|---|---|
| LLM (provedor, modelo, chave) | Tela **Configurações**. A chave de API precisa ser digitada de novo, porque fica no cofre do Windows. |
| Ollama (LLM grátis e local) | Instale em [ollama.com](https://ollama.com) e rode `ollama pull qwen2.5:7b`; para embeddings, `ollama pull nomic-embed-text`. |
| Léxicos de sentimento em português | Importe de novo os arquivos do OpLexicon e do SentiLex-PT na tela de Sentimento. |
| E-mail para a consulta online de metadados | Tela **Corpus → Metadados**. |
| Tabela de preços do LLM | Tela **Configurações**, ou `PUT /api/config/llm/precos`. |

---

## 7. R (validação cruzada e bibliometrix)

O Raio-X funciona sem o R. Ele só é necessário para rodar os scripts de validação (`scripts\validacao_r\`) e para usar o `.bib` no bibliometrix.

1. Instale o R ([cran.r-project.org](https://cran.r-project.org/bin/windows/base/)).
2. No R, instale os pacotes:

   ```r
   install.packages(c("bibliometrix","rainette","quanteda","quanteda.textstats","textometry","FactoMineR","igraph","stylo"))
   ```

3. Como rodar a validação: veja [validacao_cruzada.md](validacao_cruzada.md).

---

## 8. Continuar o desenvolvimento com o Claude Code

1. Instale o **Claude Code** (app desktop ou CLI) e entre com a sua conta.
2. Abra a pasta do repositório (`raio-x`) como pasta de trabalho.
3. O arquivo **[`CLAUDE.md`](../CLAUDE.md)**, na raiz do repositório, é lido automaticamente. Ele explica ao Claude o projeto, as regras, como testar e como atualizar a EAP.
4. Para retomar, peça por exemplo: *"leia o EAP.md e me mostre a EAP"* ou *"continue pela próxima pendência da EAP"*.

> A memória do Claude no computador antigo (preferências, histórico das conversas) **não** é transferida. O que importa para o projeto está no `CLAUDE.md`, no `EAP.md` e nos `docs/`.

---

## 9. Checklist rápido

- [ ] Python 3.11+ (3.12 para o modo offline), com *Add to PATH*
- [ ] Código: `git clone`, ou `.zip` extraído fora do OneDrive
- [ ] `iniciar.bat` abriu http://localhost:8800
- [ ] `instalar_docling.bat` (se for usar PDF) e `instalar_spacy.bat` (opcional)
- [ ] `pytest tests\test_corpus_referencia.py` sem falhas
- [ ] Projetos copiados para `projetos\` e caminho da pasta de artigos conferido
- [ ] LLM, Ollama e léxicos reconfigurados (se usados)
- [ ] R e pacotes (se for validar ou usar o bibliometrix)
