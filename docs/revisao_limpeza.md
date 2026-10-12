# Revisão da limpeza de texto (EAP 3.3) — 11/10/2026

Revisão por amostra feita por Claude (Sonnet) em 11/10/2026 sobre o corpus MLR (`Corpus_Docling`, 51 documentos com texto) e sobre o PDF 063 convertido com OCR. As caixas de cada documento abaixo continuam em branco de propósito: são para a conferência humana do usuário; o parecer a seguir é a minha leitura item a item. Os blocos "Amostra" foram gerados por `scripts/revisar_limpeza.py` (10 documentos, semente 26) e as varreduras do corpus inteiro por scripts avulsos sobre `cache/limpo`.

## Parecer item a item (corpus MLR, amostra de 10)

| Item | Veredito | Observação |
|---|---|---|
| Cabeçalho/rodapé repetidos | Correto (nada a remover) | O Docling já descarta os cabeçalhos correntes: 8 dos 10 documentos não têm nenhuma linha repetida. Varredura do corpus todo: sobraram só 3 candidatos, todos em < 50% das páginas (abaixo do limiar de 50% / 4 páginas) ou títulos curtos (`ILO Brief`), que de qualquer forma não entram no texto limpo. |
| Números de página | Correto | 057 (`11`, p. 6) e 071 (`25`, p. 27) removidos; eram números de página. |
| Hifenização | **Problema (corrigido)** | Único caso da amostra: `non-` + `experiment` virava `nonexperiment` (047, p. 53). Prefixos que formam compostos reais (`non`, `self`, `semi`, `quasi`, `pseudo`, `cross`, `well`, `ill`, `vice`, `all`, `half`) agora mantêm o hífen; quebras de sílaba (`entrepre-neurship`, `pre-vious`) continuam sendo juntadas. Depois do Docling quase não há quebras de linha hifenizadas (0 em 9 dos 10 documentos). |
| URLs / e-mails / DOI | **Problema (corrigido)** | A contagem confere com o texto bruto (46/46, 120/120, 5/5...). Mas a varredura do corpus achou restos: e-mails com chaves (`{fangzhex, gneubig}@cs.cmu.edu`), e-mail com espaço depois do `@` (`shuyan.zhou@ duke.edu`) e URLs partidas (`https: //nips.cc/...`, `https:// creativecommons.org`). As três formas agora são removidas; `pass@k`/`Recall@k` não são tocados. Efeito colateral aceito: sobra uma vírgula ou espaço onde a URL estava (`ACT-1: Transformer for Actions. , 2022.`). |
| Início da página, antes → depois | Correto | Títulos Markdown (`##`) saem do texto (por desenho: título não entra na contagem), o resto da prosa fica idêntico. Marcas `<!-- image -->` e `*` somem. Ressalva pequena: `1,*` vira `1, ,` nas filiações de autores (071). |
| Fronteira das referências | Correto (9 de 9 onde há referências) | O corpo termina em conclusão/agradecimentos/nota de fonte e a primeira entrada da lista começa exatamente em `References`. Detecção por título nos 9. |
| Página de amostra vazia | Problema do script (corrigido) | 057 caiu numa página em branco; o script agora escolhe a primeira página (a partir da 2ª) com ao menos 200 caracteres. |
| Documento sem corpo | **Problema (corrigido com aviso)** | 029 (`Appendix to "Measuring AI agent autonomy..."`) é inteiro apêndice: corpo = 0 palavras e nenhum aviso. Pela regra está certo (apêndices fora da contagem), mas o usuário não era avisado. Agora aparece "nenhum texto no corpo: tudo caiu em seções excluídas" nas pendências. Decisão (incluir `apendice` em `excluir_secoes`, ou excluir o documento) é do usuário. |

Correções com testes em `tests/test_frente26.py`; versão da etapa `limpeza` subiu para 2 (o cache é refeito).

## Limpeza sobre texto de OCR (063 Federal Reserve, 32 páginas)

| Item | Veredito | Observação |
|---|---|---|
| Cabeçalho/rodapé | Correto | O OCR de página inteira não reproduz cabeçalhos repetidos (maior repetição: 2 de 32 páginas); 1 linha removida (`100`, p. 18) era rótulo de gráfico, não número de página: perda irrelevante. |
| Hifenização | Correto | 0 quebras hifenizadas (o OCR do Docling junta as linhas de cada parágrafo). |
| URLs / e-mails | Correto | O relatório não tem. |
| Ruído do OCR | **Problema aberto** | Texto sobre imagem/estilizado sai truncado ou embaralhado (`Alig g g g s te important tasks...` na p. 2; `wie d l o s nd organizations` na p. 3). Pouca coisa (cerca de 2 linhas por página nas páginas de destaque), mas gera tokens soltos de 1 letra. `AI` sai como `Al` em todo o documento (confusão I/l do modelo PP-OCR). Sugestão: ajustar `text_score` do RapidOCR (hoje 0,5) e/ou normalizar `Al` → `AI` num passo próprio; não feito agora. |
| Seções/referências | Sem referências detectadas | O relatório não tem lista de referências (notas de rodapé); aviso "referências não detectadas" é correto. |

---

## Amostra: corpus MLR (projeto `teste-f26b`)

Amostra de 10 de 52 documentos convertidos (semente 26; estratificada por grupo: sem grupo). Gerado por `scripts/revisar_limpeza.py`; marque as caixas à mão e anote os problemas.

Legenda: *antes* = Markdown convertido (cache/md); *depois* = texto limpo (3.3).

#### 006_2026_AlNassr_Maha_From_Ideation_to_Growth_The_Impact_of_Generative_AI.md

Grupo: sem grupo · palavras: 7958 (corpo 6833, referências 1125) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 46 (no texto bruto: 46 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `Despite the global emergence and rapid growth of GenAI, its potential consequences on entrepreneurial processes in emerging markets like Qatar remain underexplored. Much of the existing research cente…`
- depois: `Despite the global emergence and rapid growth of GenAI, its potential consequences on entrepreneurial processes in emerging markets like Qatar remain underexplored. Much of the existing research cente…`

**Fronteira das referências** (título: References, p. 14):
- últimos 150 caracteres antes: `lated and under researched sectors such as healthcare, finance and traditional services, where ethical issues and compliance pressures are most acute.`
- primeiros 150 caracteres depois: `Al-Kwifi, O. S., Tien Khoa, T., Ongsakul, V., & Ahmed, Z. U. (2020). Determinants of female entrepreneurship success across Saudi Arabia. Journal of T`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 020_2024_QP1_QP4_Xie_Tianbao_et_al_OSWorld_Benchmarking_Multimodal_Agents.md

Grupo: sem grupo · palavras: 18935 (corpo 10282, referências 1874) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 120 (no texto bruto: 121 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `Task instruction 1: Update the bookkeeping sheet with my recent transactions over the past few days in the provided folder. <!-- image --> Figure 1: OSWORLD is a first-of-its-kind scalable, real compu…`
- depois: `Task instruction 1: Update the bookkeeping sheet with my recent transactions over the past few days in the provided folder. Figure 1: OSWORLD is a first-of-its-kind scalable, real computer environment…`

**Fronteira das referências** (título: References, p. 18):
- últimos 150 caracteres antes: `nry Wu, Pengcheng Yin, Shunyu Yao, Xing Han Lu, Siva Reddy, Ruoxi Sun, Zhiyuan Zeng, Chengyou Jia, and Lei Li for their helpful feedback on this work.`
- primeiros 150 caracteres depois: `[1] Adept. ACT-1: Transformer for Actions. , 2022. [2] Anthropic. Introducing the next generation of claude. claude-3-family, 2023. Accessed: 2024-03-`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 027_2024_QP2_Yoran_Ori_et_al_AssistantBench_Can_Web_Agents_Solve_Realisti.md

Grupo: sem grupo · palavras: 14001 (corpo 5840, referências 3123) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 7 (no texto bruto: 7 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `Figure 2: A gold trajectory for a task in ASSISTANTBENCH. A web agent can solve the task by first interacting with a map tool (e.g., Google Maps) to find nearby gyms and then browsing each website to …`
- depois: `Figure 2: A gold trajectory for a task in ASSISTANTBENCH. A web agent can solve the task by first interacting with a map tool (e.g., Google Maps) to find nearby gyms and then browsing each website to …`

**Fronteira das referências** (título: References, p. 10):
- últimos 150 caracteres antes: `zon 2020 research and innovation programme (grant ERC DELPHI 802800). This work was completed in partial fulfillment of the Ph.D. of the first author.`
- primeiros 150 caracteres depois: `Anthropic. 2024. Claude 3.5: Technical specifications and usage. Technical report, Anthropic. Mark Chen, Jerry Tworek, Heewoo Jun, Qiming Yuan, Henri`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 029_2026_QP3_McCain_Miles_et_al_Measuring_AI_Agent_Autonomy_in_Practice.md

Grupo: sem grupo · palavras: 6605 (corpo 0, referências 0) · detecção de referências: nenhum

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 0 (no texto bruto: 3 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `This appendix contains additional details, analyses, and results for "Measuring AI agent autonomy in practice." Updated Feb 19, 2026 to correct the final tool call sample size, from 995,621 to 998,481…`
- depois: `This appendix contains additional details, analyses, and results for "Measuring AI agent autonomy in practice." Updated Feb 19, 2026 to correct the final tool call sample size, from 995,621 to 998,481…`

**Fronteira das referências:** não detectada neste documento.

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 033_2025_Zhang_Minxing_et_al_Generalizability_of_LLM_Based_Agents_arXiv.md

Grupo: sem grupo · palavras: 23191 (corpo 18748, referências 4221) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 13 (no texto bruto: 13 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `Fig. 1. LLM-based agent ecosystem and architecture. (a) Shows different stakeholders and their interactions with the agent, including regulators and policy makers, consumers (end users, deploying orga…`
- depois: `Fig. 1. LLM-based agent ecosystem and architecture. (a) Shows different stakeholders and their interactions with the agent, including regulators and policy makers, consumers (end users, deploying orga…`

**Fronteira das referências** (título: References, p. 35):
- últimos 150 caracteres antes: `mber P0362134 SUB00004699. Roy Xie is also supported by the Apple Scholars in AIML Fellowship and the NSF Graduate Research Fellowship Program (GRFP).`
- primeiros 150 caracteres depois: `[1] 2024. [2] Josh Achiam, Steven Adler, Sandhini Agarwal, Lama Ahmad, Ilge Akkaya, Florencia Leoni Aleman, Diogo Almeida, Janko Altenschmidt, Sam Alt`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 047_2025_QP2_OECD_The_Effects_of_Generative_AI_on_Productivity_Innovation.md

Grupo: sem grupo · palavras: 23652 (corpo 15559, referências 3096) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (1 dentro da página; 0 na virada de página)
- p. 53: `non-↵experiment` → `non-experiment`

**URLs / e-mails / DOI removidos:** 144 (no texto bruto: 144 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `## OECD Artificial Intelligence Papers OECD Working Papers should not be reported as representing the official views of the OECD or of its member countries. The opinions expressed and arguments employ…`
- depois: `OECD Working Papers should not be reported as representing the official views of the OECD or of its member countries. The opinions expressed and arguments employed are those of the authors. Working Pa…`

**Fronteira das referências** (título: References, p. 34):
- últimos 150 caracteres antes: `other predictive AI tools, it offers valuable insights into AI's impact on entrepreneurship, with potentially broader implications for generative AI.`
- primeiros 150 caracteres depois: `Acemoglu, D. et al. (2022), Automation and the Workforce: A Firm-Level View from the 2019 Annual Business Survey, National Bureau of Economic Research`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 057_2025_OECD_Generative_AI_and_the_SME_Workforce.md

Grupo: sem grupo · palavras: 17572 (corpo 16414, referências 1158) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 1 (números de página: 1)
- `11` — 1× (págs. 6)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 61 (no texto bruto: 61 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 4):**
- antes: `This work is published under the responsibility of the Secretary-General of the OECD. The opinions expressed and arguments employed herein do not necessarily reflect the official views of the Member c…`
- depois: `This work is published under the responsibility of the Secretary-General of the OECD. The opinions expressed and arguments employed herein do not necessarily reflect the official views of the Member c…`

**Fronteira das referências** (título: References, p. 16):
- últimos 150 caracteres antes: `ring) described in Chapter 4. Source: (Bianchini and Lasheras Sancho, 2025[2]), "SME digitalisation for competitiveness: The 2025 OECD D4SME Survey".`
- primeiros 150 caracteres depois: `Bianchini, M. and M. Lasheras Sancho (2025), "SME digitalisation for competitiveness: The 2025 OECD D4SME Survey", OECD SME and Entrepreneurship Paper`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 060_2026_QP3_ILO_The_impact_of_GenAI_on_jobs_productivity_and_work_organi.md

Grupo: sem grupo · palavras: 4251 (corpo 2967, referências 1284) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 8 (no texto bruto: 8 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `##  ILO Brief The impact of GenAI on jobs, productivity and work organization: a review of the empirical evidence experienced workers to perform tasks previously reserved for specialists, flattening …`
- depois: `The impact of GenAI on jobs, productivity and work organization: a review of the empirical evidence experienced workers to perform tasks previously reserved for specialists, flattening skill hierarchi…`

**Fronteira das referências** (título:  References, p. 5):
- últimos 150 caracteres antes: `ests that the impact of artificial intelligence on jobs and productivity might be multi-faceted and depend on factors other than the technology alone.`
- primeiros 150 caracteres depois: `Agarwal, N. et al. (2023). Combining Human Expertise with Artificial Intelligence: Experimental Evidence from Radiology, NBER Working Paper 31422 (Cam`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 071_2025_Kusetogullari_Anna_GenAI_in_Entrepreneurship_systematic_review.md

Grupo: sem grupo · palavras: 13383 (corpo 10304, referências 3079) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 1 (números de página: 1)
- `25` — 1× (págs. 27)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 5 (no texto bruto: 5 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `## GenAI in Entrepreneurship ## a systematic review of generative artificial intelligence in entrepreneurship research: current issues and future directions Anna Kusetogullari 1,* , Huseyin Kusetogull…`
- depois: `Anna Kusetogullari 1, , Huseyin Kusetogullari 2 , Martin Andersson 3 , Tony Gorschek 1 1 Department of Software Engineering, Blekinge Institute of Technology, Karlskrona, Sweden 2 Department of Comput…`

**Fronteira das referências** (título: References, p. 32):
- últimos 150 caracteres antes: `blers for entrepreneurship and effective regulatory frameworks that allow for business experimentation, innovation and further technology development.`
- primeiros 150 caracteres depois: `Abaddi, S. (2024). GPT revolution and digital entrepreneurial intentions. Journal of Entrepreneurship in Emerging Economies, 16(6), 1903-1930. Al Hal`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 

#### 072_2026_Pop_Cohut_Ioana_Hybrid_Artisan.md

Grupo: sem grupo · palavras: 16000 (corpo 10022, referências 1718) · detecção de referências: titulo

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 0 (números de página: 0)
- (nenhuma)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 36 (no texto bruto: 37 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `## 1. Introduction ## 1.1. Context and Significance The rapid advancement of artificial intelligence (AI) technologies poses major challenges for traditional craftsmen: how to innovate using digital t…`
- depois: `The rapid advancement of artificial intelligence (AI) technologies poses major challenges for traditional craftsmen: how to innovate using digital tools without compromising cultural authenticity and …`

**Fronteira das referências** (título: References, p. 36):
- últimos 150 caracteres antes: `ness of interpretive lens. Transparency about positionality is not a weakness but a methodological strength in qualitative research. Date: July 2026.`
- primeiros 150 caracteres depois: `1. Yang, H.; Sui, Q.; Hu, B.; Shi, K.; Wang, R.; Li, M. A Semantic Reconstruction and AI-Controlled Generation Method for the Cultural Genes of Qing D`

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações:

## Amostra: PDF 063 com OCR (projeto `teste-f26`)

#### 063_2026_QP2_QP3_Federal_Reserve_Bank_of_Philadelphia_How_Is_AI_Impacting.pdf

Grupo: sem grupo · palavras: 5785 (corpo 4436, referências 0) · detecção de referências: nenhum

**Linhas removidas como cabeçalho/rodapé ou nº de página:** 1 (números de página: 1)
- `100` — 1× (págs. 18)

**Hifenizações corrigidas:** 0 no total (0 dentro da página; 0 na virada de página)
- (nenhuma amostra)

**URLs / e-mails / DOI removidos:** 0 (no texto bruto: 0 URLs e e-mails fora de comentários)

**Primeiros 200 caracteres (página 2):**
- antes: `## Note from the Chief Economist Alig g g g s te important tasks, reshaping how we work, and expanding what individuals and organizations can do. Those capabilities also create important questions for…`
- depois: `Alig g g g s te important tasks, reshaping how we work, and expanding what individuals and organizations can do. Those capabilities also create important questions for the broader economy and job mark…`

**Fronteira das referências:** não detectada neste documento.

- [ ] Cabeçalho/rodapé e nº de página: ok   - [ ] Hifenização: ok   - [ ] URLs/e-mails: ok   - [ ] Fronteira das referências: ok   — Observações: 
