# 12.2 (e) - Colocados 5.4 (agent, task, human; lema; janela 5/5) por implementação independente em R.
#
# Uso: Rscript colocacoes.R <pasta de dados>
# O quanteda não tem colocados por janela com LL (textstat_collocations mede expressões de várias palavras), então
# a referência é uma reimplementação com as MESMAS convenções do Raio-X (colocacoes.py), a partir de tokens.tsv:
# - universo = tokens contados (corpo, >= 2 caracteres); palavras vazias ocupam posição, mas não são candidatas;
# - janela 5/5 truncada na fronteira (bloco = página/seção, padrão; ou documento); o nó não é colocado de si mesmo;
# - janelas sobrepostas UNIDAS: O11 = tokens do colocado na região; R1 = posições distintas da região sem o nó;
#   C1 = frequência do colocado (fora das vazias); N = tokens contados; LL = G² 4 células com sinal; MI = log2(O11/E11);
# - mínimos O11 >= 3 e C1 >= 5; só atração.
# À parte, a contagem por pares (Freq(LR) do AntConc) e um LL "estilo AntConc" (O11 = pares, R1 = f(nó) × 10) para
# medir o efeito da convenção documentada em docs/validacao_antconc.md.
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "comum.R"))

b <- carregar_base()
tk <- b$tk
N <- nrow(tk)
C1_tab <- tk[vazia == FALSE, .N, by = lema]
C1_de <- setNames(C1_tab$N, C1_tab$lema)
por_doc <- split(tk[, .(lema, bloco, vazia)], tk$doc)

colocar <- function(no, fronteira, E = 5, D = 5) {
  o11 <- list(); pares <- list(); R1 <- 0; f_no <- 0
  for (d in por_doc) {
    nos <- which(d$lema == no)
    if (!length(nos)) next
    f_no <- f_no + length(nos)
    n <- nrow(d); seg <- if (fronteira == "bloco") d$bloco else rep(0L, n)
    cob <- integer(0)
    for (k in nos) {
      for (passo in c(-1L, 1L)) {
        lim <- if (passo < 0) E else D
        for (s in seq_len(lim)) {
          j <- k + passo * s
          if (j < 1 || j > n || seg[j] != seg[k]) break
          cob <- c(cob, j)
        }
      }
    }
    cob <- cob[!(cob %in% nos)]
    tab_pares <- table(cob)                     # vezes que cada posição foi coberta (contagem por pares)
    pos <- as.integer(names(tab_pares)); vezes <- as.integer(tab_pares)
    R1 <- R1 + length(pos)
    ok <- !d$vazia[pos]
    o11[[length(o11) + 1]] <- data.table(lema = d$lema[pos[ok]], o = 1L, p = vezes[ok])
  }
  x <- rbindlist(o11)[, .(o11 = sum(o), pares = sum(p)), by = lema]
  x[, C1 := C1_de[lema]]
  x[, `:=`(N = N, R1 = R1, f_no = f_no)]
  x[, e11 := R1 * C1 / N]
  x[, ll := sign(o11 - e11) * g2_4(o11, R1 - o11, C1 - o11, N - R1 - (C1 - o11))]
  x[, mi := log2(o11 / e11)]
  # estilo AntConc: cada par conta; janela = f(nó) × (E + D)
  R1a <- f_no * (E + D)
  x[, e11_ant := R1a * C1 / N]
  x[, ll_ant := sign(pares - e11_ant) * g2_4(pares, R1a - pares, pmax(C1 - pares, 0), N - R1a - pmax(C1 - pares, 0))]
  x[o11 >= 3 & C1 >= 5 & ll > 0][order(-ll, -o11, lema, method = "radix")]
}

col_rx <- ler_raiox("raiox_colocacoes.json")
saida <- list()
for (chave in names(col_rx)) {
  pr <- strsplit(chave, "|", fixed = TRUE)[[1]]
  rx <- col_rx[[chave]]
  x <- colocar(pr[1], pr[2])
  rxt <- rbindlist(lapply(rx$colocados, function(c) list(lema = c$termo, o11_rx = c$o11, c1_rx = c$c1,
                                                          ll_rx = c$ll, mi_rx = c$mi, pares_rx = c$pares)))
  m <- merge(x[seq_len(min(.N, nrow(rxt)))], rxt, by = "lema", all = TRUE)  # o Raio-X devolve até 1000
  ambos <- m[!is.na(ll) & !is.na(ll_rx)]
  top_rx <- rxt$lema[1:20]; top_ant <- x[order(-ll_ant, lema, method = "radix")]$lema[1:20]
  comuns <- intersect(top_rx, top_ant)
  saida[[chave]] <- list(
    no = pr[1], fronteira = pr[2],
    N_r = N, N_rx = rx$N, R1_r = x$R1[1], R1_rx = rx$R1, f_no_r = x$f_no[1], f_no_rx = rx$ocorrencias_no,
    colocados_r = nrow(x), colocados_rx = rx$total_candidatos, so_r = m[is.na(ll_rx), .N], so_rx = m[is.na(ll), .N],
    o11_diferentes = ambos[o11 != o11_rx, .N], c1_diferentes = ambos[C1 != c1_rx, .N],
    pares_diferentes = ambos[pares != pares_rx, .N],
    max_dif_ll = max(abs(ambos$ll - ambos$ll_rx)), max_dif_mi = max(abs(ambos$mi - ambos$mi_rx)),
    mesma_ordem_top20 = identical(x$lema[1:20], top_rx),
    top5 = x$lema[1:5],
    pares_sobre_o11 = list(total = sum(x$pares) / sum(x$o11), max = max(x$pares / x$o11),
                           colocados_com_pares_maior = x[pares > o11, .N]),
    antconc_top20_comuns = length(comuns),
    antconc_spearman = cor(match(comuns, top_rx), match(comuns, top_ant), method = "spearman")
  )
}
print(rbindlist(lapply(saida, function(s) s[c("no", "fronteira", "N_r", "N_rx", "R1_r", "R1_rx", "colocados_r",
                                               "colocados_rx", "o11_diferentes", "max_dif_ll", "max_dif_mi",
                                               "mesma_ordem_top20", "antconc_top20_comuns", "antconc_spearman")])))
gravar(unname(saida), "r_colocacoes.json")
