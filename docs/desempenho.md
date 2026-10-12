# Desempenho do pipeline MVP (EAP 12.3)

- **Data da medição:** 2026-10-10
- **Máquina:** Windows-11-10.0.26200-SP0; processador Intel64 Family 6 Model 170 Stepping 4, GenuineIntel; 14 núcleos lógicos; memória 15.5 GB; Python 3.12.10
- **Pasta medida:** `C:\Users\WladimirFarias\Documents\Desenvolver RSL multivocal sobre empreendedorismo agêntico\03_Fontes\Corpus_Docling` (somente leitura; 52 arquivos antes e depois, sem alterações)
- **Documentos:** 52 (todos `.md`, sem conversão por Docling)
- **Tokens:** 439.894 no corpo; 699.679 com referências e apêndices
- **Meta (EAP 12.3):** pipeline MVP em menos de 10 min

## Tempos

| Execução | Tempo total | Erros | Execuções registradas |
|---|---:|---:|---:|
| 1ª (sem cache) | 30.4 s | 0 | 213 |
| 2ª (com cache) | 3.7 s | 0 | 211 |

## Tempo por etapa

Soma de `finalizado_em - iniciado_em` das execuções de cada rodada (por documento e por corpus). Na 2ª rodada, as etapas com cache aparecem como `pulado`.

| Etapa | Execuções (1ª) | ok | pulado | erro | Tempo 1ª (s) | Tempo 2ª (s) |
|---|---:|---:|---:|---:|---:|---:|
| comentarios | 1 | 1 | 0 | 0 | 1.89 | 0.77 |
| comparativo | 1 | 1 | 0 | 0 | 0.02 | 0.00 |
| descritivo | 1 | 1 | 0 | 0 | 1.97 | 0.00 |
| vocabulario | 1 | 1 | 0 | 0 | 2.18 | 0.00 |
| linguistica | 51 | 51 | 0 | 0 | 8.99 | 0.00 |
| limpeza | 51 | 51 | 0 | 0 | 7.01 | 0.00 |
| qualidade_duplicados | 1 | 1 | 0 | 0 | 0.01 | 0.01 |
| qualidade | 52 | 52 | 0 | 0 | 3.32 | 0.00 |
| conversao | 52 | 52 | 0 | 0 | 1.08 | 0.00 |
| metadados_csv | 1 | 1 | 0 | 0 | 0.00 | 0.00 |
| varredura | 1 | 1 | 0 | 0 | 0.09 | 0.08 |

## Veredito

**Atingido.** A primeira execução completa levou 30.4 s, abaixo da meta de 10 min.

Reproduzir: `.venv\Scripts\python scripts\medir_desempenho.py "C:\Users\WladimirFarias\Documents\Desenvolver RSL multivocal sobre empreendedorismo agêntico\03_Fontes\Corpus_Docling"`.
