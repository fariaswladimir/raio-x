# Validação cruzada no corpus MLR (EAP 12.2)

Data: 14/10/2026. Corpus: MLR sobre empreendedorismo agêntico (projeto de teste `teste-val`, removido ao fim).
Este relatório traz só números agregados, listas de termos e rótulos curtos; nenhum texto do corpus.

## 1. Objetivo

Conferir, no mesmo corpus e nas **mesmas unidades**, se as análises estatísticas do Raio-X dão os mesmos resultados
de implementações de referência independentes, e explicar cada divergência. Critério de aceite da 12.2: relatório de
divergências explicadas; para a CHD (7.1), o critério de `docs/validacao_iramuteq.md` (a maioria das classes pareadas
com Jaccard das 20 formas ≥ 0,3 e os mesmos 2–3 documentos mais associados).

## 2. Ferramentas e versões

As ferramentas de interface gráfica previstas (IRaMuTeQ, AntConc, TXM, Voyant) não estão instaladas nesta máquina.
Com a aprovação do usuário, a validação foi feita **em R**, com os pacotes que implementam os mesmos métodos (o
rainette reimplementa a CHD do IRaMuTeQ a partir do código dele; o textometry é o pacote R da equipe do TXM). A
vantagem é a reprodutibilidade: os scripts rodam sem cliques e recebem exatamente as unidades do Raio-X (ST, formas
ativas, tokens), o que separa diferenças de **método** de diferenças de **pré-processamento**. As comparações com o
IRaMuTeQ (`docs/validacao_iramuteq.md`), o AntConc (`docs/validacao_antconc.md`) e o TXM continuam disponíveis e são
**opcionais** para o usuário.

| Ferramenta | Versão | Uso |
|---|---|---|
| R | 4.6.1 | ambiente |
| rainette (Barnier) | 0.3.3 | CHD de Reinert simples e dupla (7.1) |
| quanteda / quanteda.textstats (Benoit et al. 2018) | 4.5.0 / 0.97.2 | `textstat_keyness(measure = "lr")` (6.1); leitura do corpus IRaMuTeQ |
| textometry (equipe do TXM) | 0.1.7 | `specificities()` de Lafon (6.2) |
| FactoMineR (Lê, Josse & Husson 2008) / ca | 2.17 / 0.72 | AFC (7.3) |
| igraph (Csardi & Nepusz 2006) | 2.3.3 | árvore geradora máxima (7.2) |
| clue / mclust | 0.3-68 / 6.1.3 | pareamento húngaro e ARI |
| data.table, Matrix, jsonlite | 1.18.6.1, 1.7-5, 2.0.0 | leitura e tabelas |

Scripts em `scripts/validacao_r/` (só código; os dados ficam numa pasta temporária apagada ao fim):
`exportar_referencia.py` (cria o projeto, roda o pipeline pela API com `?sincrono=1`, define os grupos e exporta),
`comum.R`, `reinert.R`, `keyness.R`, `especificidades.R`, `afc.R`, `colocacoes.R`, `similitude.R` e
`iramuteq_import.R`. Uso: `Rscript <script>.R <pasta de dados>`.

## 3. Dados e unidades

- 52 arquivos `.md` (Docling); **51 documentos** no corpus (o 063 é escaneado, sem texto, e fica fora no Raio-X).
  Grupos: cinzenta = 011, 047, 051, 057, 059, 060, 061 (7 com texto; o 063 seria o 8º); acadêmica = os outros 44.
- Universo de tokens (4.2/5.4/6.1/6.2/7.3): corpo (`incluir`), forma com ≥ 2 caracteres: **N = 426.926** tokens.
  Exportados com forma, lema, bloco (página/seção), segmento e marca de ruído; o R refaz **todas** as contagens.
- Palavras vazias: a lista ativa do projeto (`stoplist.txt`), com a regra do Raio-X (forma **ou** lema na lista).
- Segmentos de texto (4.4): 11.388, dos quais 166 de ruído (3.4) ficam fora da CHD e da similitude: **11.222 ST**,
  11.210 com alguma forma ativa; 3.000 formas ativas (lemas plenos, F ≥ 3). R e Raio-X chegam aos mesmos números.
- O documento 029 tem 0 palavras de corpo: o arquivo de origem contém só o **apêndice** do artigo (toda a página é
  seção "apêndice", excluída pela limpeza). Ele não entra em nenhuma análise; ver a seção 11 (pendências).

## 4. (a) CHD de Reinert (7.1) × rainette

Mesmos ST, mesmas 3.000 formas, tabela binária; rainette com `k = 10`, `min_segment_size = 0` (não funde ST),
`min_split_members = 5`, `cc_test = 0,3`, `tsj = 3` (padrões). As classes dos dois lados são descritas pela **mesma**
função (χ² 2 × 2 sem correção, associação positiva, χ² ≥ 3,84); as 20 formas recalculadas no R para as classes do
Raio-X são idênticas às do Raio-X nas 10 classes. Pareamento ótimo (húngaro) pelo Jaccard das 20 formas.

| Variante | Classes | Retenção | Pares com Jaccard ≥ 0,3 | Pares com ≥ 2 dos 3 docs mais associados em comum | 1º doc igual | Jaccard mediano | ARI |
|---|---|---|---|---|---|---|---|
| Raio-X (simples, mín. 281 ST) | 10 | 92,22% | — | — | — | — | — |
| rainette, 10 classes (padrão) | 10 | 99,88% | 4/10 | 3/10 | 3/10 | 0,13 | 0,33 |
| rainette + regra das folhas pequenas do Raio-X (K = 23 → 10 folhas ≥ 281 ST) | 10 | 90,04% | **8/10** | **7/10** | 6/10 | 0,54 | 0,47 |

Pares da 2ª variante (6 primeiras formas de cada lado; documentos pelo id do estudo):

| Raio-X (ST) | Formas Raio-X | rainette (ST) | Formas rainette | Jaccard 20 | Docs Raio-X | Docs rainette |
|---|---|---|---|---|---|---|
| 1 (1.266) | agentic system opac smme organization accountability | 7 (1.361) | agentic system opac organization organisation governance | 0,60 | 059, 051, 073 | 059, 069, 051 |
| 2 (1.424) | entrepreneurship research entrepreneurial ai startup innovation | 8 (985) | innovation startup entrepreneurship entrepreneurial business learning | 0,38 | 071, 047, 007 | 071, s13, 007 |
| 3 (498) | aiet entry venture sdg manioudis meramveliotakis | 9 (800) | entrepreneurship implication research ai ecosystem empirical | 0,05 | s13, 001, 002 | 047, 007, 071 |
| 4 (1.694) | worker sme occupation generative chat labour | 6 (1.492) | sme generative worker occupation country labour | 0,74 | 057, 014, 061 | 057, 061, 014 |
| 5 (1.086) | memory backbone agent generalizability unit store | 1 (1.419) | memory backbone action agent attack component | 0,38 | 033, 041, 069 | 033, 069, 041 |
| 6 (973) | benchmark web environment task realistic real-world | 2 (1.424) | benchmark web task environment real-world realistic | 0,67 | 038, 017, 024 | 020, 028, 018 |
| 7 (791) | action click database message list element | 3 (400) | competition kaggle mle-bench submission medal original | 0,00 | 020, 025, 019 | 026, 017, 030 |
| 8 (1.376) | gpt model score claude success competition | 4 (1.096) | gpt claude model score achieve accuracy | 0,48 | 026, 030, 031 | 031, 030, 032 |
| 9 (614) | participant reliance lm advice privacy leakage | 5 (512) | participant advice reliance involvement calibrate confidence | 0,82 | 040, 035, 034 | 040, 034, 035 |
| 10 (627) | grid firm patent coefficient quarter city | 10 (615) | grid firm coefficient patent quarter small | 0,90 | 002, 013, 003 | 002, 013, 001 |

**Classificação dupla (extra).** Raio-X (UC de 40 e 60 palavras): 8 classes estáveis, retenção 50,1%. rainette2
(`min_segment_size` 10 e 15 formas, `full = FALSE`, até 10 classes): partições de 2 a 9 classes, com retenção de 82%
a 99,8% (8 classes: 94,6%). Não são comparáveis número a número: o rainette2 cruza clusters de **qualquer nível** das
duas hierarquias e escolhe a partição de maior soma de χ² entre os cruzamentos disjuntos (então ancestrais grandes
entram), enquanto o Raio-X (como o ALCESTE "clássico") só cruza as classes **terminais** e retém só as interseções
estáveis; as UC também são medidas de modo diferente (formas × palavras).

**Veredito: ≈ equivalente com divergências explicadas** (critério de aceite atingido na comparação de mesma regra:
8/10 pares com Jaccard ≥ 0,3 e 7/10 com 2–3 documentos mais associados em comum).

Por que o rainette "puro" difere (lido no código do rainette 0.3.3 e na vinheta *Algorithms description*):

1. **Folhas pequenas.** O rainette, como a fase 1 do IRaMuTeQ, conta toda folha como classe. Nas 10 classes padrão,
   4 são folhas de 2, 2, 3 e 16 ST (pelas formas: cabeçalho de *discussion paper*, lista de autores, cláusula
   contratual repetida, enunciado de tarefa de reserva de voo) e 1 tem 239 ST dos 3 textos em português/espanhol
   (005, 008, 011); sobram 5 classes substantivas (4.358, 3.860, 1.602, 615 e 512 ST), e cada uma reúne quase
   inteiras classes do Raio-X (a de 4.358 ST, as classes 5, 6, 7 e 8; a de 3.860, as classes 1, 2 e 3). O Raio-X descarta folhas menores que máx(5; 2,5%) e
   continua dividindo até 10 classes válidas — aplicada ao rainette, essa regra precisa de 23 bipartições e reproduz
   a estrutura do Raio-X.
2. **Seleção de formas a cada divisão.** Depois de cada bipartição, o rainette tira das sub-tabelas as formas com
   frequência < 3 (`tsj`) e, se o coeficiente de contingência passa de 0,3 (`cc_test`), mantém a forma só no lado em
   que ela é sobre-representada (regra do IRaMuTeQ). O Raio-X mantém todas as formas presentes na classe. ST que
   ficam sem formas numa sub-tabela saem da classificação no rainette.
3. **Realocação.** O rainette troca, a cada passo, só o ST de **maior** ganho de χ² (subida mais íngreme, uma troca
   por iteração) até nenhuma troca melhorar; o Raio-X faz varreduras em ordem de índice aceitando toda troca que
   aumenta o χ². Os dois param num ótimo local exato (nenhuma troca isolada melhora), mas podem parar em ótimos
   diferentes. O eixo 1 da AFC e o corte de χ² máximo são o mesmo cálculo nos dois.
4. As duas classes sem par (Raio-X 3, "aiet/venture/sdg", e 7, "action/click/database") são classes "de documento"
   (poucos textos concentram a classe); o rainette distribui esses ST entre classes vizinhas e cria outra classe de
   documento (Kaggle/MLE-bench). Pequenas diferenças de seleção de formas mudam qual documento atípico vira classe.

## 5. (b) Keyness (6.1) × quanteda.textstats

Cinzenta (7 docs, c = 62.841 tokens) × acadêmica (44 docs, d = 364.085), lema, palavras vazias filtradas na lista
(c e d com todos os tokens), a + b ≥ 5: **4.845 termos** nos dois lados.

| Conferência | Resultado |
|---|---|
| Contagens a, b, c, d (recontadas no R) | idênticas nos 4.845 termos |
| G² de 2 células (R) × Raio-X | diferença máxima **2,8e-14** |
| G² de 4 células à mão × `textstat_keyness(measure = "lr", correction = "none")` | \|G²\| do quanteda = \|G²\| à mão **+ 0,000854** (deslocamento constante em todos os termos, de uma suavização interna do quanteda) |
| 2 células × 4 células: Spearman em todos os termos | 0,9999998 |
| 4 células / 2 células nos termos com p < 0,001 | mediana 1,00014; máximo 1,014 |
| Top 20 / 50 / 100 de cada lado (2 × 4 células) | 100% em comum; Spearman ≥ 0,9999 |
| Top 10 cinzenta (iguais nas duas formas) | generative, sme, ai, labour, organisation, oecd, survey, country, use, skill |
| Top 10 acadêmica (iguais nas duas formas) | agent, benchmark, llm, entrepreneurial, environment, grid, chat, model, privacy, lm |

**Veredito: ✅ equivalente.** O Raio-X usa o G² de 2 células (AntConc/Wmatrix) e o quanteda o de 4 células; a
diferença é a convenção documentada em `keyness.py` e não muda a ordem das listas. (Na lista padrão do painel, com
dispersão mínima de 2 documentos, *sme* sai do top da cinzenta: é filtro de dispersão, não de estatística.)

## 6. (c) Especificidades (6.2) × textometry

Partição por ano (2023: 16.085 tokens; 2024: 99.351; 2025: 212.297; 2026: 92.543; s/ano: 6.650; T = 426.926), lema,
4.845 termos com F ≥ 5. Comparados os 50 positivos e até 50 negativos de cada ano (495 células).

| Conferência | Resultado |
|---|---|
| f e F recontados no R | idênticos |
| Raio-X × `phyper` em escala log (independente), abaixo do teto | diferença máxima **5,0e-4** (o Raio-X arredonda a 3 casas) |
| Raio-X × `textometry::specificities` (finitos) | diferença máxima **5,0e-4**; textometry × phyper: 5e-5 (o textometry arredonda a 4 casas) |
| Teto ±50 | 32 células acima do teto no Raio-X; todas com \|score\| ≥ 50 no R (o textometry não chegou a infinito em nenhuma) |
| Listas dos 50 positivos por ano | as mesmas 50 e na **mesma ordem** nos 5 anos |
| Lado da cauda | o textometry 0.1.7 decide pela **média** F·t/T, como o Raio-X; numa decisão pela moda, só mudariam células com \|score\| ≤ 0,43 (zona banal) |

**Veredito: ✅ equivalente.** Correção feita na documentação: o docstring de `especificidades.py` e o catálogo
diziam que o pacote textometry decide o lado pela moda; o código da versão 0.1.7 usa a média.

## 7. (d) AFC (7.3) × FactoMineR::CA e ca::ca

Tabela termo × ano com os 100 lemas mais frequentes (F ≥ 5; mesma lista e mesmas frequências no R), 5 partes, 4 eixos.

| Conferência | Resultado |
|---|---|
| Autovalores | 0,08627 / 0,05376 / 0,04299 / 0,01899 nos três; diferença máxima 4,5e-9 |
| % de inércia | 42,71 / 26,61 / 21,28 / 9,40; diferença máxima 4,9e-5 (arredondamento) |
| Inércia total (χ²/n) | 0,2019972 nos dois |
| Coordenadas (termos e partes), por eixo | \|r\| = 1 − 1e-12; diferença máxima 5e-7 depois de alinhar o sinal (o Raio-X arredonda a 6 casas) |
| Contribuições (ctr) e cos² | diferença máxima 5e-5 (arredondamento a 4 casas) |
| Sinal dos eixos | igual ao do FactoMineR nos 4 eixos; o `ca::ca` espelha os eixos 1 e 3 |

**Veredito: ✅ equivalente.** O sinal de um eixo é arbitrário; o Raio-X fixa a parte de maior |coordenada| positiva.

## 8. (e) Colocados (5.4) × implementação independente em R

O quanteda não tem colocados por janela com LL (o `textstat_collocations` mede expressões de várias palavras); a
referência é uma reimplementação em R com as mesmas convenções (janela 5/5, vazias ocupam posição mas não são
candidatas, nó não é colocado de si mesmo, janelas **unidas**, O11 ≥ 3, C1 ≥ 5, só atração), a partir dos tokens.

| Nó | Fronteira | N | f(nó) | R1 | Colocados | O11, C1, pares | máx \|ΔLL\|, \|ΔMI\| | Top 20 | Top 5 |
|---|---|---|---|---|---|---|---|---|---|
| agent | bloco | 426.926 | 3.470 | 32.547 | 900 | idênticos | 5e-5 | mesma ordem | lm, web, llm-based, llm, generalizability |
| agent | documento | 426.926 | 3.470 | 32.939 | 903 | idênticos | 5e-5 | mesma ordem | idem |
| task | bloco | 426.926 | 3.613 | 32.531 | 841 | idênticos | 5e-5 | mesma ordem | perform, complete, solve, complex, require |
| task | documento | 426.926 | 3.613 | 32.884 | 841 | idênticos | 5e-5 | mesma ordem | idem |
| human | bloco | 426.926 | 1.261 | 12.019 | 506 | idênticos | 5e-5 | mesma ordem | oversight, capital, ai-specific, judgment, intervention |
| human | documento | 426.926 | 1.261 | 12.188 | 509 | idênticos | 5e-5 | mesma ordem | idem |

(5e-5 = arredondamento a 4 casas do Raio-X.) **Veredito: ✅ equivalente (exato nas contagens).**

**Contagem por pares (estilo AntConc, Freq(LR)).** Para medir o efeito da convenção documentada em
`docs/validacao_antconc.md`, o R recalculou o LL contando cada par (ocorrência do nó × posição) e com janela
f(nó) × 10 (sem descontar sobreposições). Isto **simula** a convenção; não é o AntConc.

| Nó (bloco) | Σ pares / Σ O11 | máx pares/O11 | Colocados com pares > O11 | Top 20 em comum com o Raio-X | Spearman nos comuns |
|---|---|---|---|---|---|
| agent | 1,043 | 2 | 282/900 | 19/20 | 0,96 |
| task | 1,095 | 4 | 391/841 | 17/20 | 0,75 |
| human | 1,029 | 2,25 | 85/506 | 18/20 | 0,98 |

Com fronteira = documento os números são quase os mesmos (19/20, 0,97; 17/20, 0,73; 18/20, 0,98). Se o AntConc for
rodado, espera-se o mesmo padrão: ordem quase igual para *agent* e *human* e diferenças maiores para *task*, que
se repete perto de si mesmo (janelas sobrepostas contam duas vezes no AntConc).

## 9. (f) Similitude (7.2) × igraph

60 lemas plenos mais frequentes nos ST sem ruído (a mesma lista e a mesma ordem no R), índice de coocorrência por
ST, árvore geradora máxima pelo `igraph::mst` com pesos negados.

| Conferência | Resultado |
|---|---|
| Arestas | 59 nos dois; Jaccard das arestas **1,0** (nenhuma diferença) |
| Peso total da árvore | 15.543 nos dois; pesos das arestas idênticos |
| Graus mais altos | ai 43, agent 11, task 6, firm 2 (iguais) |

**Veredito: ✅ equivalente.** Empates de peso poderiam trocar arestas entre árvores máximas igualmente válidas
(o peso total seria o mesmo); neste corpus não houve troca. Comunidades (Louvain × algoritmos do igraph) não foram
comparadas: dependem de semente e algoritmo e não fazem parte do critério.

## 10. Exportação para o IRaMuTeQ (`corpus-iramuteq.txt`)

Lida pelo `rainette::import_corpus_iramuteq`: 50 textos (os 51 documentos menos o 029, sem corpo), variáveis
`doc`, `grupo` (43 acadêmicos, 7 cinzenta) e `ano` (2023: 2; 2024: 13; 2025: 22; 2026: 12; s_ano: 1).
**Defeito encontrado e corrigido:** o documento sem id do estudo recebia `*doc_052` (o número do banco), que coincidia
com o id do estudo de outro documento (052): o IRaMuTeQ juntaria os dois textos na mesma modalidade. Agora o rótulo de
reserva é `id<nº>` e ids repetidos ganham `_2`, `_3`... (`exportacao.py`; teste
`test_exportacao_corpus_iramuteq_doc_unico`). Segmentação do rainette (`split_segments`, 40 palavras) no mesmo texto:
11.722 ST × 11.388 do Raio-X — referência só para lembrar que cada ferramenta segmenta com regras próprias.

## 11. Relatório de divergências explicadas

| Análise | Referência | Veredito | Divergência | Explicação |
|---|---|---|---|---|
| Keyness (6.1) | quanteda.textstats 0.97.2 | ✅ | G² de 2 × 4 células (razão ≤ 1,014); quanteda + 0,000854 | convenção do Raio-X (AntConc/Wmatrix); suavização interna do quanteda; ordem idêntica |
| Especificidades (6.2) | textometry 0.1.7; phyper | ✅ | ≤ 5e-4 | arredondamento; teto ±50 só na exibição; lado pela média nos dois |
| AFC (7.3) | FactoMineR 2.17; ca 0.72 | ✅ | ≤ 5e-7 (coord.), sinal | arredondamento; sinal arbitrário (convenção fixa no Raio-X) |
| Colocados (5.4) | reimplementação em R | ✅ | nenhuma nas contagens; ≤ 5e-5 | arredondamento |
| Colocados × convenção AntConc | simulação por pares | ≈ | top 20: 17–19 em comum | janelas unidas (Raio-X) × contagem por pares (AntConc) |
| Similitude (7.2) | igraph 2.3.3 | ✅ | nenhuma | — |
| CHD (7.1) | rainette 0.3.3 | ≈ | 8/10 pares (mesma regra de folhas); 4/10 sem ela | folhas pequenas, seleção de formas (`tsj`, `cc_test`), realocação de maior ganho |
| CHD dupla | rainette2 | ≈ (extra) | 8 classes, 50% × 82–99,8% | rainette2 cruza todos os níveis e escolhe a melhor partição |
| Exportação IRaMuTeQ | rainette (leitor) | corrigido | `*doc_` repetido | rótulo de reserva colidia com id do estudo |

**Pendências (não bloqueiam a 12.2):** (1) rodar, se quiser, as ferramentas de interface (IRaMuTeQ, AntConc, TXM,
Voyant) pelos roteiros, para registrar a comparação com as ferramentas citadas no artigo; (2) o arquivo de origem do
documento 029 contém só o apêndice do artigo (0 palavras de corpo): substitua pelo texto completo se ele deve contar;
(3) o 063 é escaneado (sem texto).

## 12. Parágrafo para a seção de Métodos ("Validação cruzada")

> **Validação cruzada.** As análises estatísticas do Raio-X foram conferidas no próprio corpus da revisão (51
> documentos; 426.926 tokens; 11.222 segmentos de texto) contra implementações independentes em R 4.6.1, alimentadas
> com as mesmas unidades (tokens, lemas, palavras vazias e segmentos). As contagens e as estatísticas de colocados
> (G² e MI, janela 5/5), keyness (G² de 2 células; Rayson & Garside, 2000), especificidades de Lafon (pacote
> textometry 0.1.7), análise de correspondência (FactoMineR 2.17; Lê, Josse & Husson, 2008) e árvore máxima de
> similitude (igraph 2.3.3; Csardi & Nepusz, 2006) coincidiram até o arredondamento (diferenças ≤ 5 × 10⁻⁴); o G² de
> 4 células do quanteda.textstats (Benoit et al., 2018) produziu a mesma ordenação das palavras-chave. A
> classificação hierárquica descendente foi comparada com o rainette 0.3.3 (Barnier), reimplementação do método de
> Reinert do IRaMuTeQ: aplicando a mesma regra de descarte de classes pequenas (< 2,5% dos segmentos), 8 das 10
> classes tiveram correspondência (Jaccard ≥ 0,3 entre as 20 formas de maior χ²) e 7 compartilharam ao menos 2 dos 3
> documentos mais associados (ARI = 0,47); as diferenças restantes decorrem da seleção de formas a cada divisão e do
> procedimento de realocação, documentados. Scripts e resultados agregados estão em `docs/validacao_cruzada.md`.

(Confira as referências marcadas "conferir antes de citar" no catálogo de metodologia antes da submissão.)
