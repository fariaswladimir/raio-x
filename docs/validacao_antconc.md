# Validação dos colocados (5.4) contra o AntConc

Critério de aceite da 5.4: **ranking conferido contra o AntConc em 3 termos**. Este roteiro também serve de base para a validação cruzada da 12.2 (AntConc e IRaMuTeQ).

> Conferência independente em R (mesmas convenções, contagens idênticas, e simulação da contagem por pares do AntConc): ver `docs/validacao_cruzada.md`.

## 1. O que comparar

| | Raio-X | AntConc 4 |
|---|---|---|
| Ferramenta | painel **Colocações** (`/analises/colocacoes`) | aba **Collocate** |
| Estatística principal | LL = G² da tabela 2×2 (Dunning 1993), com sinal | *Likelihood Measure*: **Log-Likelihood (4-term)** |
| Tamanho de efeito | MI = log2(O11/E11) | *Effect Size Measure*: **MI** |
| Frequência | `o11` (cada token conta 1 vez) e `pares` (por par nó × posição) | *Freq(LR)* ≈ `pares` |

O critério é a **ordem** (top 20), não a igualdade dos números: as duas ferramentas não montam a tabela 2×2 exatamente do mesmo jeito (seção 5).

## 2. Exportar o corpus do Raio-X

1. Execute o pipeline do projeto.
2. Baixe `http://127.0.0.1:8800/api/projetos/<slug>/exportar/corpus-limpo.zip` e descompacte numa pasta nova.

Conteúdo do zip:

- `textos/*.txt`: um arquivo por documento, UTF-8, **só o corpo** (sem títulos de seção, referências, apêndices, agradecimentos e declarações), texto original (caixa e pontuação preservadas), um bloco (página/seção) por parágrafo.
- `stoplist.txt`: as palavras vazias ativas no projeto (EN, PT, ES, acadêmicas e próprias), uma por linha.
- `lemas.txt`: lista de lemas do Raio-X no formato `lema -> forma1, forma2`.
- `LEIAME.txt`: os parâmetros usados.

## 3. Configurar o AntConc (4.x)

Os nomes dos menus podem variar entre versões; confira na sua.

1. **Corpus:** *File → Open Files* → os `.txt` de `textos/` (codificação UTF-8).
2. **Token definition** (*Global Settings → Token/Word*):
   - letras (*Letter*) ligadas, números (*Number*) desligados;
   - acrescente aos caracteres de palavra o apóstrofo (`'` e `’`) e o hífen (`-`), para `multi-agent` e `agent's` ficarem inteiros;
   - se a sua versão aceitar expressão regular, use a mesma do Raio-X, que já descarta tokens de 1 letra:
     `(?=\p{L}[\p{L}\p{M}\p{N}'’\-‐‑])\p{L}[\p{L}\p{M}\p{N}]*(?:['’\-‐‑]\p{L}[\p{L}\p{M}\p{N}]*)*`
   - deixe a distinção de maiúsculas desligada (tudo em minúsculas).
3. **Palavras vazias:** *Global Settings → Word List Range → use a stop list* → carregue `stoplist.txt`.
4. **Lemas** (só na comparação por lema): *Global Settings → Lemma list* → carregue `lemas.txt`.
5. **Collocate:**
   - *Window Span*: **From 5L To 5R**;
   - *Min. Collocate Freq.*: **3**; *Min. Collocate Range*: **1**;
   - *Likelihood Measure*: **Log-Likelihood (4-term)**; *Effect Size Measure*: **MI**;
   - *Sort by*: **Likelihood**.

## 4. Configurar o Raio-X igual

Use a API (ou o painel) com:

```
/api/projetos/<slug>/analises/colocacoes?q=agent&por=forma&esquerda=5&direita=5&vazias=filtrar
    &min_freq=3&min_freq_colocado=1&ordem=ll&fronteira=documento&limite=20
```

- `fronteira=documento`: a janela corre livre pelo documento, como no AntConc (o padrão do Raio-X, `bloco`, para em quebra de página e de seção);
- `min_freq_colocado=1`: o AntConc não tem limite de frequência do colocado no corpus;
- `por=forma` sem a lista de lemas no AntConc; `por=lema` com `lemas.txt` carregado;
- o CSV (`colocacoes.csv`, mesmos parâmetros) facilita a comparação na planilha.

## 5. Diferenças esperadas (não são erro)

| Diferença | Raio-X | AntConc | Efeito |
|---|---|---|---|
| Janelas sobrepostas | unidas: cada token conta 1 vez em O11; R1 = posições distintas cobertas, sem o nó (Evert 2008) | conta por par (nó × posição) | Freq(LR) do AntConc ≈ `pares` do Raio-X; LL um pouco diferente quando o nó se repete perto de si mesmo |
| Tamanho da janela (R1) | após truncar nas fronteiras e sem as posições do nó | em geral, freq(nó) × span | E11 e MI mudam um pouco; a ordem quase não |
| Tokens de 1 letra (`a`, `I`) | não existem (não ocupam posição) | ocupam posição, se a definição de token os aceitar | use a regex do passo 3.2 |
| Palavras vazias | ocupam posição, não são candidatas | conferir na sua versão se a *stop list* remove o token do texto ou só da lista | se removerem do texto, o AntConc "alcança" mais longe |
| Lematização | `simplemma` + exceções do projeto | lista `lemas.txt` | iguais se a lista for carregada |

## 6. Comparação (3 termos)

Termos sugeridos: **agent**, **task**, **human** (por forma: `agent`, `task`, `human`; por lema: os mesmos com `lemas.txt`).

Para cada termo, copie o top 20 de cada ferramenta e preencha:

| Termo | Top 20 em comum (n/20) | Correlação de Spearman nos itens comuns | Maiores diferenças de posição (e causa) |
|---|---|---|---|
| agent | | | |
| task | | | |
| human | | | |

**Critério sugerido:** ≥ 16/20 em comum e Spearman ≥ 0,8 em cada termo; divergências explicadas pela seção 5. Registre o resultado no EAP (5.4 e, depois, 12.2).

## 7. Referências

- Anthony, L. (2024). *AntConc* (versão 4) [software]. Tokyo: Waseda University.
- Church, K. W.; Hanks, P. (1990). Word association norms, mutual information, and lexicography. *Computational Linguistics*, 16(1), 22–29.
- Dunning, T. (1993). Accurate methods for the statistics of surprise and coincidence. *Computational Linguistics*, 19(1), 61–74.
- Evert, S. (2005). *The Statistics of Word Cooccurrences: Word Pairs and Collocations*. Tese (Doutorado), Universität Stuttgart.
- Evert, S. (2008). Corpora and collocations. In: Lüdeling, A.; Kytö, M. (orgs.). *Corpus Linguistics: An International Handbook*, v. 2. Berlin: Mouton de Gruyter, 1212–1248.
- Rychlý, P. (2008). A lexicographer-friendly association score. In: *Proceedings of Recent Advances in Slavonic Natural Language Processing (RASLAN 2008)*, 6–9.
