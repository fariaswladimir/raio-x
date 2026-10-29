# Validação da CHD (7.1) e da similitude (7.2) no IRaMuTeQ (EAP 12.2)

Roteiro para rodar o IRaMuTeQ (Ratinaud 2009; Camargo & Justo 2013) no **mesmo corpus** do Raio-X, com
configurações equivalentes, e comparar classes, retenção, formas características e a árvore de similitude.
O Raio-X não distribui o texto do corpus: o arquivo é gerado na sua máquina, a partir do seu projeto.

> Validação automática já feita em R (rainette, igraph) nas mesmas unidades: ver `docs/validacao_cruzada.md` (12.2); este roteiro é opcional.

## 1. Exportar o corpus no formato do IRaMuTeQ

Com o pipeline executado, baixe:

    GET http://127.0.0.1:8800/api/projetos/<slug>/exportar/corpus-iramuteq.txt

O arquivo (UTF-8) tem um texto por documento ativo, com a linha de cabeçalho

    **** *doc_<id do estudo> *grupo_<grupo> *ano_<ano>

e o mesmo texto do corpo do `corpus-limpo.zip` (sem títulos de seção, referências e seções excluídas; um bloco
por parágrafo). Asteriscos do texto viram espaço (o IRaMuTeQ os reserva para as variáveis); modalidades de variável
só com letras, dígitos e `_` (`sem grupo` → `sem_grupo`, `s/ano` → `s_ano`).

## 2. Configuração equivalente no IRaMuTeQ (0.7 alpha 2 ou 0.8)

1. *Arquivo → Abrir um corpus textual*: codificação **utf-8**, idioma **english** (o corpus MLR é quase todo em
   inglês; os 3 documentos em português/espanhol ficam com o dicionário inglês, como no Raio-X, onde o lema vem do
   `simplemma` com en+pt).
2. *Construir segmentos de texto*: **sim**, tamanho **40** ocorrências, cortes pela pontuação (padrão).
3. *Análise → Classificação → Método de Reinert*:
   - **Classificação simples sobre segmentos de texto** (padrão do Raio-X; `dupla=false`);
   - número de classes terminais da fase 1: **10**;
   - número mínimo de segmentos por classe: **0 (automático)** — o Raio-X usa máx(5; 2,5% dos segmentos);
   - número máximo de formas analisadas: **3000**;
   - lematização **sim**; formas ativas: adjetivos, advérbios, nomes, verbos e não reconhecidas; as demais
     (artigos, preposições, pronomes...) como suplementares (o Raio-X não tem etiquetagem morfológica: usa as listas
     de palavras vazias en/pt/es/acadêmico como filtro de palavras "plenas").
4. Para a classificação dupla, use *classificação dupla sobre RST* com rst1 = 12 e rst2 = 14 formas ativas (padrão
   do IRaMuTeQ) e, no Raio-X, `dupla=true` com UC de 40 e 60 palavras (as unidades são medidas de modo diferente;
   compare só o número de classes estáveis e a retenção).

No Raio-X, as mesmas escolhas estão em *Parâmetros* (`reinert`: classes 10, min_freq 3, dupla false, tamanhos
[40, 60], min_classe 0, max_formas 3000) e no painel *Classes (Reinert)*. Os resultados completos saem em
`/analises/reinert/classes.csv` e `/analises/reinert/segmentos.csv`.

## 3. O que comparar (registre na tabela do fim)

| Item | Onde no IRaMuTeQ | Onde no Raio-X |
|---|---|---|
| Nº de classes finais | dendrograma | `k`, dendrograma do painel |
| Retenção (% de ST classificados) | "x segments classés sur y (z%)" no relatório | `retencao_pct` (aviso abaixo de 75%) |
| Tamanho de cada classe (%) | dendrograma | `classes[].pct` |
| 20 formas de maior χ² por classe | aba *Profils* | colunas do painel / `classes.csv` (tipo = forma) |
| Variáveis associadas (`*doc_`, `*grupo_`, `*ano_`) | *Profils*, parte das variáveis estreladas | `classes.csv` (tipo = documento/grupo/ano) |
| Segmentos típicos | *Segments de texte caractéristiques* | painel, "Segmentos típicos" |

**Pareamento das classes.** Os segmentos não coincidem um a um (ver abaixo), então não cruze segmento a segmento.
Pareie cada classe do IRaMuTeQ com a do Raio-X de maior sobreposição das 20 formas de maior χ² (índice de
Jaccard das duas listas) e confirme pelo perfil das variáveis (os documentos mais associados devem ser os mesmos).
Critério de aceite da 7.1 na 12.2: a maioria das classes pareadas com Jaccard das 20 formas ≥ 0,3 e os mesmos
2–3 documentos mais associados; diferenças de tamanho de até ~5 pontos percentuais são esperadas.

## 4. Similitude

*Análise → Análise de similitude*: formas ativas, **índice de coocorrência**, **árvore máxima**, as **60** formas mais
frequentes (seleção pela frequência), comunidades e halos ligados. No Raio-X: painel *Similitude / Rede* com
"árvore máxima" e "coocorrência", 60 formas. Compare: palavras centrais (grau e intermediação), vizinhos imediatos das
5 formas mais frequentes e a composição das comunidades. O IRaMuTeQ usa os algoritmos de comunidade do `igraph`
(por padrão *edge betweenness* ou *fast greedy*, conforme a versão); o Raio-X usa Louvain com semente fixa, então os
cortes entre comunidades podem diferir mesmo com a mesma árvore. A árvore em si depende só da ordem dos pesos: com
os mesmos segmentos e as mesmas formas, ela seria igual (empates à parte).

## 5. Divergências esperadas (explicadas)

- **Segmentação**: o Raio-X conta palavras do corpo (com as vazias) e fecha o segmento no fim de página/seção; o
  IRaMuTeQ conta ocorrências com as próprias regras (4.4, `segmentacao.py`).
- **Lematização e formas ativas**: `simplemma` + palavras vazias × dicionário do IRaMuTeQ + classes gramaticais.
- **Realocação**: o Raio-X documenta uma varredura gulosa que só aceita trocas que aumentam o χ² (ver
  `reinert.py`); a troca do IRaMuTeQ pode convergir para outro ótimo local.
- **Classes minúsculas**: no Raio-X, folhas com menos que o mínimo (segmentos atípicos: listas de autores,
  tabelas, textos repetidos) são descartadas e **não contam** como classe, e a divisão continua até 10 classes
  válidas (teto de 50 bipartições). No IRaMuTeQ, as 9 bipartições da fase 1 contam essas folhas, e o número final
  de classes tende a ser menor; a retenção do IRaMuTeQ na classificação simples costuma ser menor que a do Raio-X.
- **Comunidades**: Louvain (Raio-X) × algoritmos do igraph (IRaMuTeQ).

## 6. Registro

| Data | Corpus / projeto | Versão do IRaMuTeQ | Classes (IRaMuTeQ × Raio-X) | Retenção | Classes pareadas (Jaccard das 20 formas) | Observações |
|---|---|---|---|---|---|---|
| | | | | | | |
