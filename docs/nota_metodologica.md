# Nota metodológica do Raio-X

> Documento geral (não é de um projeto). Descreve o que o Raio-X calcula, como, e **cada convenção decidida** ao longo do desenvolvimento, com as referências do catálogo (`app/services/metodologia/catalogo.yaml`, também em Metodologia na interface). A fonte de cada convenção é o docstring do módulo citado; em caso de divergência, vale o código. Itens **(planejado)** ainda não existem. Versão de 11/10/2026.

## 1. Princípios

- Tudo roda localmente; o texto não sai da máquina. Os comentários do laudo vêm de regras (e, só se ligado, de um LLM) e **só entram no laudo se um humano aceitar**; cada comentário traz a evidência (métrica + trecho + página) e passa por uma checagem automática (seção 10).
- Determinismo: o mesmo corpus e os mesmos parâmetros dão sempre o mesmo resultado (as sementes fixas estão indicadas).
- Cada análise informa a ferramenta equivalente e o que **não** é equivalente (catálogo e seção 12).

## 2. Preparação do corpus

- **Conversão**: PDF para Markdown com Docling (CPU), com marcador de página para citação exata; OCR opcional por documento (RapidOCR) (Auer et al., 2024). `.md`, `.txt` e `.docx` entram direto.
- **Limpeza** (`limpeza_texto.py`): remove cabeçalhos e rodapés repetidos (linhas em pelo menos 50% das páginas, a partir de 4 páginas), números de página, URLs, e-mails e DOI; junta palavras hifenizadas no fim da linha (prefixos de composto como `non-` e `self-` mantêm o hífen).
- **Seções e referências**: detecção por título (EN/PT/ES) ou heurística; seções excluídas da contagem por padrão: referências, apêndice, agradecimentos, declarações (cerca de 35% dos tokens do corpus de teste).
- **Duplicatas**: idênticas em bytes, de mesmo título e quase idênticas por cosseno TF-IDF de 0,95 ou mais (Salton & Buckley, 1988); nada é excluído sozinho.
- **Segmentos de ruído (3.4)**: listas de autores e afiliações, tabelas de regressão e estatística, texto repetitivo e cláusulas repetidas entre documentos são marcados por regras conservadoras (`ruido.py`) e saem da CHD, da similitude e dos n-gramas (`limpeza.excluir_ruido`); continuam no KWIC, com marca, e nas pendências do documento.

## 3. Universo de tokens (convenção central)

Todas as contagens usam os mesmos tokens: **só o corpo do texto** (`incluir` = 1, sem seções excluídas), com **2 letras ou mais**, por **lema** (padrão; simplemma) ou forma minúscula, e as palavras vazias filtradas **na consulta** (a lista de termos) mas **contadas nos tamanhos** (N, c, d, t, T), como no denominador de "por 10 mil" do Voyant (Sinclair & Rockwell, 2016). Assim N, a frequência de um nó e o painel Frequências batem entre si. Termos compostos (`por=termo`) ocupam uma posição e contam uma vez.

- **Lematização**: `simplemma` (tabela de consulta) com lista de exceções; limitação conhecida: radicais inválidos do dicionário EN em alguns verbos; erros reais raros (no máximo 0,85% dos tokens com lema ausente do corpus de teste). O spaCy (Honnibal & Montani, 2020) fica para a v0.3 se a validação cruzada pedir.
- **Palavras vazias**: listas EN/PT/ES, lista acadêmica ("et", "al"...) e lista própria do projeto.
- **Termos compostos** (4.3): candidatos contíguos de 2 a 3 lemas no mesmo bloco, sem vazia nas bordas, pontuados pelo G² de Dunning (1993) do par adjacente (trigramas: mínimo dos bigramas); filtros de frequência (10 ou mais), documentos (3 ou mais), concentração (até 0,8) e regex de ruído; lista curada e bloqueados do usuário.
- **Segmentos de texto (4.4)**: cerca de 40 palavras, janela de 30 a 50, corte preferencial em `. ? !` antes de `; :` antes de `,`, nunca atravessando bloco (página ou seção) (Reinert, 1983; Camargo & Justo, 2013). Não coincidem um a um com os do IRaMuTeQ (contagem de palavras do corpo com as vazias; fim de página fecha o segmento).

## 4. Descritivo

- **Frequências**: contagem e "por 10 mil palavras"; amplitude em documentos (Luhn, 1960; Sinclair, 1991).
- **Diversidade lexical**: densidade (tipos por palavra) e **MATTR** com janela de 500 (Covington & McFall, 2010); só documentos com 500 palavras ou mais são comparáveis.
- **KWIC**: N palavras de cada lado, sem atravessar seção excluída; a quebra de bloco aparece como " … ". Consulta por frase entre aspas.
- **N-gramas** (5.5): contíguos, dentro do bloco, de 2 a 6 palavras; a pontuação quebra a sequência (opcional); palavras vazias: todas, sem bordas (padrão) ou sem vazias; `concentracao` = parcela das ocorrências no documento onde mais aparece (em vez do D de Juilland) (Biber et al., 2004). Diferem dos termos compostos: lista exaustiva, sem teste de associação.
- **TF-IDF** (termos distintivos): sublinear com idf suavizado e norma L2 (Sparck Jones, 1972; Salton & Buckley, 1988).

## 5. Associações

- **Colocações** (5.4): janela posicional (padrão 5 à esquerda e 5 à direita); **palavras vazias ocupam posição** (só não são candidatas); a janela não atravessa documento nem bloco (página ou seção). **Janelas sobrepostas são unidas**: cada token conta no máximo uma vez como coocorrência (Evert, 2008), de modo que O11 não passa de C1 e as quatro células são não negativas; a contagem por pares (como o Freq(LR) do AntConc) é informada à parte. Medidas: **G² de 4 células** (Dunning, 1993) com sinal (negativo = repulsão), MI = log2(O11/E11) (Church & Hanks, 1990), t-score, logDice (Rychlý, 2008) e p de 1 g.l. Ver Evert (2005).
- **Links** (rede em torno do termo, por janela) não é a similitude (seção 7).

## 6. Comparativo

- **Keyness** (6.1): lados A e B por partição (grupo ou ano; B = grupo específico ou "resto"). **G² de 2 células** (Rayson & Garside, 2000), a forma do AntConc e do Wmatrix, que **difere do G² de 4 células** usado nos colocados e no scipy (a de 2 células omite as células "não é o termo", que pesam pouco quando o termo é raro). Sinal: positivo = sobre-representado em A. **Log Ratio** (Hardie, 2014): log2((a/c)/(b/d)); se a ou b é zero, usa-se **0,5 no lugar do zero**, só nesse cálculo. **%DIFF** (Gabrielatos & Marchi, 2012): indefinido quando b = 0 (marca "só em A"). Filtros padrão: frequência total de 5 ou mais, p < 0,01 (ou Bonferroni, com m = termos testados) e dispersão de 2 ou mais documentos por lado.
- **Especificidades** (6.2): modelo hipergeométrico exato (Lafon, 1980; Lebart et al., 1998). Escore = -log10 P(X >= f) se f for maior ou igual à esperada (cauda superior) e +log10 P(X <= f) se menor (cauda inferior; o TXM decide pela moda, e as listas de específicos coincidem). **Teto de 50** (P < 1e-50; "acima do teto" marcado) e cálculo em escala logarítmica abaixo de 1e-250. Banal: |escore| < 2. Não há correção para comparações múltiplas: o escore é indicador de ordenação, não teste.
- **Similaridade entre documentos** (6.3): TF-IDF e cosseno; agrupamento padrão **Ward** (Ward, 1963; no corpus de teste a ligação média separou por idioma), k automático por silhueta, mapa por MDS clássico.
- **Dicionário/codebook** (6.4): contagem de categorias definidas pelo usuário (curingas e frases), com a G² de 2 células e o Log Ratio da keyness por categoria (Grimmer & Stewart, 2013).

## 7. Temático

- **AFC** (7.3): SVD dos resíduos padronizados de uma tabela termo por parte (grupo, ano, documento ou classe); inércia total = χ²/n; ctr e cos² (Benzécri, 1973; Greenacre, 2017; Lebart et al., 1998). **Convenção de sinal**: em cada eixo, a parte de maior |coordenada| fica positiva (empate: menor índice); outros programas podem mostrar o mapa espelhado. Com 2 partes há um único eixo.
- **CHD de Reinert** (7.1): tabela binária segmento por forma plena (lema fora das vazias, frequência 3 ou mais, até 3.000 formas). Bipartição: eixo 1 da AFC da classe, **corte de maior χ²** da tabela 2 por formas e **realocação gulosa** (só troca que aumenta o χ²; ótimo local exato). Divide **sempre a maior classe** até 10 classes terminais (Reinert, 1983, 1990; Ratinaud, 2009; Camargo & Justo, 2013). **Diferença em relação ao IRaMuTeQ (ramos pequenos)**: folhas com menos segmentos que o mínimo (o maior entre 5 e 2,5% dos segmentos classificáveis) são **descartadas** (seus segmentos ficam não classificados) **e não contam como classe**; a retenção (% de segmentos classificados) é informada, e abaixo de 75% pede cautela. As classes não coincidem uma a uma com as do IRaMuTeQ; a comparação forma a forma está em `docs/validacao_iramuteq.md` (12.2). Classificação dupla opcional (UC de 40 e 60 palavras; só classes estáveis, χ² de 3,84 ou mais). Descrição por χ² 2 por 2, sem correção, com sinal.
- **Similitude** (7.2): grafo das 60 formas mais frequentes por índice de **coocorrência** nos segmentos (padrão do IRaMuTeQ), Jaccard, cosseno ou PMI (só PMI > 0), reduzido à **árvore geradora máxima** por Kruskal (empate: menor par na ordem das formas) (Flament, 1981; Marchand & Ratinaud, 2012); ou rede com as 3 arestas mais fortes por forma, ao estilo do KH Coder (Higuchi, 2016; Jaccard, 1912). Comunidades por **Louvain** (Blondel et al., 2008; semente 42; o Leiden de Traag et al., 2019 não está disponível sem `leidenalg`), centralidades (grau, intermediação, PageRank) e layout Fruchterman-Reingold, só para desenhar.
- **Tópicos LDA** (7.4) **(planejado)**: semente fixa e coerência (Blei et al., 2003; Röder et al., 2015).

## 8. Laudo e métodos

O laudo (HTML e DOCX) leva só comentários aceitos ou editados, com evidências "(rótulo, p. N)", métodos com referências ABNT do catálogo, notas do revisor, parâmetros e hash. O texto de Métodos para o artigo (9.4) é determinístico (sem LLM) e sai do catálogo e dos parâmetros do projeto.

## 9. Comentários por regra

Dez regras em `regras/catalogo.yaml` (limiares editáveis). Cada comentário tem chave estável, e a revisão humana é **reconciliada** a cada geração: novo vira sugerido; aceito ou editado com número ou evidência alterados vira revisar; rejeitado nunca ressuscita; chave que some vira obsoleto.

## 10. Checagem de evidência (8.3) e verificação de texto de LLM (14.3)

- **Evidência**: cada trecho precisa existir no texto limpo atual, na página declarada (o fragmento do termo; fragmentos vizinhos podem estar na página adjacente). Números do texto de regra têm de coincidir com as métricas atuais; comentários editados e de LLM passam por `verificar()`.
- **`verificar()`**: confere números (pt-BR e en, com arredondamento; "p < 0,05" e similares são isentos), citações "(rótulo, p. N)" e trechos entre aspas contra o que foi enviado ao modelo. Falha leva o comentário a `revisar` com o motivo; texto de LLM nunca é aceito automaticamente, e a revisão humana declara o modelo. **Limite**: a conferência não detecta afirmação causal ou interpretação indevida sem números.

## 11. Planejado

Classes gramaticais (4.5), LDA (7.4), legibilidade, palavras-chave por documento, sumarização, sentimento, estilometria, codificação por LLM com kappa e alfa, e keyness com corpus externo (Frente 15).

## 12. O que o Raio-X **não** é equivalente a

Voyant Collocates (só conta coocorrências), "termos distintivos" do Voyant (TF-IDF, sem teste), KH Coder (agrupamento aglomerativo de palavras), LDA (tópicos) e a CHD do IRaMuTeQ um a um (segmentação, lematização, realocação e tratamento de ramos pequenos diferem). Cada convenção acima existe para tornar o resultado auditável e reproduzível, não para igualar outra ferramenta.

## 13. Referências

AUER, C. et al. Docling Technical Report. arXiv, arXiv:2408.09869. 2024. Disponível em: https://arxiv.org/abs/2408.09869.

BENZÉCRI, J.-P. L'analyse des données. Tome 2 : L'analyse des correspondances. Paris: Dunod, 1973.

BIBER, D.; CONRAD, S.; CORTES, V. If you look at...: lexical bundles in university teaching and textbooks. Applied Linguistics, v. 25, n. 3, p. 371-405, 2004.

BLEI, D. M.; NG, A. Y.; JORDAN, M. I. Latent Dirichlet allocation. Journal of Machine Learning Research, v. 3, p. 993-1022, 2003.

BLONDEL, V. D. et al. Fast unfolding of communities in large networks. Journal of Statistical Mechanics, p. P10008, 2008.

CAMARGO, B. V.; JUSTO, A. M. IRAMUTEQ: um software gratuito para análise de dados textuais. Temas em Psicologia, v. 21, n. 2, p. 513-518, 2013.

CHURCH, K. W.; HANKS, P. Word association norms, mutual information, and lexicography. Computational Linguistics, v. 16, n. 1, p. 22-29, 1990.

COVINGTON, M. A.; MCFALL, J. D. Cutting the Gordian knot: the moving-average type-token ratio (MATTR). Journal of Quantitative Linguistics, v. 17, n. 2, p. 94-100, 2010.

DUNNING, T. Accurate methods for the statistics of surprise and coincidence. Computational Linguistics, v. 19, n. 1, p. 61-74, 1993.

EVERT, S. The Statistics of Word Cooccurrences: Word Pairs and Collocations. 2005. Tese (Doutorado) – Universität Stuttgart, Stuttgart, 2005.

EVERT, S. Corpora and collocations. In: LÜDELING, A.; KYTÖ, M. (orgs.). Corpus Linguistics: An International Handbook. v. 2. Berlin: Mouton de Gruyter, 2008. p. 1212-1248.

FLAMENT, C. L'analyse de similitude : une technique pour les recherches sur les représentations sociales. Cahiers de Psychologie Cognitive, v. 1, n. 4, p. 375-395, 1981.

GABRIELATOS, C.; MARCHI, A. Keyness: appropriate metrics and practical issues. In: CADS INTERNATIONAL CONFERENCE, UNIVERSITY OF BOLOGNA, 2012.

GREENACRE, M. Correspondence Analysis in Practice. 3. ed. Boca Raton: CRC Press, 2017.

GRIMMER, J.; STEWART, B. M. Text as data: the promise and pitfalls of automatic content analysis methods for political texts. Political Analysis, v. 21, n. 3, p. 267-297, 2013.

HARDIE, A. Log Ratio – an informal introduction. ESRC Centre for Corpus Approaches to Social Science (CASS), Lancaster University [blog]. 2014.

HIGUCHI, K. A two-step approach to quantitative content analysis: KH Coder tutorial using Anne of Green Gables (Part I). Ritsumeikan Social Sciences Review, v. 52, n. 3, p. 77-91, 2016.

HONNIBAL, M. et al. spaCy: Industrial-strength Natural Language Processing in Python [software]. Zenodo, 2020. DOI: 10.5281/zenodo.1212303.

JACCARD, P. The distribution of the flora in the alpine zone. New Phytologist, v. 11, n. 2, p. 37-50, 1912.

LAFON, P. Sur la variabilité de la fréquence des formes dans un corpus. Mots, n. 1, p. 127-165, 1980.

LEBART, L.; SALEM, A.; BERRY, L. Exploring Textual Data. Dordrecht: Kluwer, 1998.

LUHN, H. P. Key word-in-context index for technical literature (KWIC index). American Documentation, v. 11, n. 4, p. 288-295, 1960.

MARCHAND, P.; RATINAUD, P. L'analyse de similitude appliquée aux corpus textuels : les primaires socialistes pour l'élection présidentielle française. In: ACTES DES JADT 2012, 2012. p. 687-699.

RATINAUD, P. IRAMUTEQ: Interface de R pour les Analyses Multidimensionnelles de Textes et de Questionnaires [software]. 2009. Disponível em: http://www.iramuteq.org.

RAYSON, P.; GARSIDE, R. Comparing corpora using frequency profiling. In: PROCEEDINGS OF THE WORKSHOP ON COMPARING CORPORA (ACL 2000), 2000. p. 1-6.

REINERT, M. Une méthode de classification descendante hiérarchique : application à l'analyse lexicale par contexte. Les Cahiers de l'Analyse des Données, v. 8, n. 2, p. 187-198, 1983.

REINERT, M. Alceste, une méthodologie d'analyse des données textuelles et une application : Aurélia de Gérard de Nerval. Bulletin de Méthodologie Sociologique, v. 26, p. 24-54, 1990.

ROCKWELL, G.; SINCLAIR, S. Hermeneutica: Computer-Assisted Interpretation in the Humanities. Cambridge, MA: MIT Press, 2016.

RÖDER, M.; BOTH, A.; HINNEBURG, A. Exploring the space of topic coherence measures. In: PROCEEDINGS OF WSDM 2015, 2015. p. 399-408.

RYCHLÝ, P. A lexicographer-friendly association score. In: PROCEEDINGS OF RECENT ADVANCES IN SLAVONIC NATURAL LANGUAGE PROCESSING (RASLAN 2008), 2008. p. 6-9.

SALTON, G.; BUCKLEY, C. Term-weighting approaches in automatic text retrieval. Information Processing & Management, v. 24, n. 5, p. 513-523, 1988.

SINCLAIR, J. Corpus, Concordance, Collocation. Oxford: Oxford University Press, 1991.

SINCLAIR, S.; ROCKWELL, G. Voyant Tools [software]. 2016. Disponível em: https://voyant-tools.org.

TRAAG, V. A.; WALTMAN, L.; ECK, N. J. van. From Louvain to Leiden: guaranteeing well-connected communities. Scientific Reports, v. 9, p. 5233, 2019.

WARD, J. H. Hierarchical grouping to optimize an objective function. Journal of the American Statistical Association, v. 58, n. 301, p. 236-244, 1963.
