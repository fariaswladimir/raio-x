# Raio-X de Textos: guia de uso (1 página)

**O que faz:** lê uma pasta de artigos, prepara o texto e mostra análises de palavras e um laudo com comentários.
Não usa inteligência artificial: os comentários são feitos por regras, e você decide o que entra no laudo.
A pasta dos artigos **nunca é alterada**; tudo o que o sistema gera fica em `projetos\<nome>\`.

## 1. Abrir
1. Dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o ambiente e instala as dependências (alguns minutos).
   O navegador abre em http://localhost:8800.
2. Só se precisar ler PDF ou DOCX: dê dois cliques em `instalar_docling.bat` uma vez. Ele baixa cerca de **2 GB**.
   Artigos já em `.md` ou `.txt` não precisam disso.

## 2. Criar o projeto (tela inicial, "Novo projeto")
- Digite um nome e cole o caminho da pasta de artigos (ex.: `C:\Users\...\Artigos`). Clique em **Criar projeto**.

## 3. Definir grupos (aba Visão geral, tabela Documentos)
- Edite a coluna **Grupo** (ex.: `academica`, `cinzenta`), **Id**, **Ano** ou **Autor**. Saia do campo para salvar.
- Ou envie um `documentos.csv` pelo botão **Enviar CSV**, com separador `;` e colunas `arquivo;grupo;id_estudo;qp`
  (`qp` é opcional). Exemplo de linha:
  `001_2026_Kim_Titulo.md;academica;E001;`
- Valores preenchidos no CSV valem sobre o que foi editado à mão, a cada execução.

## 4. Executar (aba Executar)
- Clique em **Executar**. As etapas aparecem em ordem, com o progresso.
- O que não mudou é pulado (cache), então a segunda execução é bem mais rápida.
- Erros aparecem na própria aba; documentos com problema aparecem em **Pendências**.

## 5. Analisar (aba Análises)
- **Cirrus** (nuvem de palavras) e **Termos** (lista de frequências): palavras mais usadas no escopo escolhido.
- **Tendências**: como um termo se distribui por documento, ano ou grupo.
- **Links** e **Colocações**: palavras que aparecem perto de um termo central, com a rede e a força da associação.
- **Resumo** e **Documentos**: tamanho do corpus e de cada documento, variedade de vocabulário e termos distintivos.
- **Contextos (KWIC)**: cada ocorrência de uma palavra com o texto ao redor.
- **Keyness** (comparação entre grupos): palavras que distinguem dois grupos, por exemplo acadêmica × cinzenta.

## 6. Revisar comentários (aba Comentários)
- Cada comentário traz os trechos que o sustentam. Ações: **Aceitar**, **Editar**, **Rejeitar** ou **Anotar**.
- Informe seu nome em **Revisor**: ele fica gravado em cada ação.
- Só os comentários **aceitos** ou **editados** vão para o laudo. Se os dados mudarem, um aceito volta para **revisar**.

## 7. Laudo e exportação (aba Laudo e exportação)
- **Gerar laudo** cria um HTML que abre offline, com métricas, evidências e parâmetros usados.
- **Baixar pacote (.zip)** reúne o laudo e as planilhas CSV (separador `;`, abrem no Excel em português).

## 8. Onde ficam os arquivos
- `projetos\<nome>\saidas\`: `laudo.html`, os CSV e `pacote.zip`.
- `projetos\<nome>\projeto.sqlite`: grupos, comentários e revisões. Faça cópia antes de apagar qualquer coisa.
- `projetos\<nome>\cache\`: texto convertido e tokens. Pode ser apagado; é recriado na próxima execução.

## 9. Problemas comuns
- **"documento sem texto"**: menos de 200 palavras foram extraídas. Em PDF, quase sempre é digitalização (imagem).
  O Raio-X ainda não faz OCR: use uma cópia com texto pesquisável.
- **"provável PDF escaneado"**: o mesmo caso, com páginas quase sem texto.
- **"idioma 'xx' fora dos esperados"**: o texto não está nos idiomas configurados. Confira se o arquivo é o certo
  ou ajuste a lista de idiomas nos parâmetros do projeto.
- **Referências não detectadas (✗ na coluna Ref.)**: não achamos a seção de referências. Confira se o texto tem o
  título "Referências" ou "References". Sem isso, a bibliografia entra na contagem.
