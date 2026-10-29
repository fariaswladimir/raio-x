# 12.2 (b) - Keyness 6.1 (cinzenta × acadêmica, lema) contra o quanteda.textstats::textstat_keyness(measure = "lr").
#
# Uso: Rscript keyness.R <pasta de dados>
# - Recontagem independente a partir de tokens.tsv: a = frequência do lema na cinzenta, b = na acadêmica, c e d =
#   todos os tokens contados de cada lado (com as palavras vazias, como no Raio-X); termos fora das vazias, a + b >= 5.
# - G² de 2 células (Rayson & Garside 2000; convenção do Raio-X/AntConc) calculado aqui e comparado ao do Raio-X.
# - G² de 4 células: à mão e pelo quanteda (dfm agrupada com uma coluna extra "__vazias__" para que os totais de
#   cada lado sejam c e d, os mesmos do Raio-X); correction = "none".
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "comum.R"))
suppressPackageStartupMessages({ library(quanteda); library(quanteda.textstats) })

b <- carregar_base()
tk <- merge(b$tk, b$docs[, .(doc, grupo)], by = "doc")
lados <- tk[, .N, by = grupo]
c_ <- lados[grupo == "cinzenta", N]; d_ <- lados[grupo == "academica", N]
cont <- dcast(tk[vazia == FALSE, .N, by = .(lema, grupo)], lema ~ grupo, value.var = "N", fill = 0)
setnames(cont, c("academica", "cinzenta"), c("b", "a"))
cont <- cont[a + b >= 5]

xl <- function(o, e) ifelse(o > 0, o * log(o / e), 0)
e1 <- c_ * (cont$a + cont$b) / (c_ + d_); e2 <- d_ * (cont$a + cont$b) / (c_ + d_)
sinal <- sign(cont$a * d_ - cont$b * c_)
cont[, g2_2 := sinal * pmax(2 * (xl(a, e1) + xl(b, e2)), 0)]
cont[, g2_4 := sinal * g2_4(a, b, c_ - a, d_ - b)]

# ---- Raio-X (todos os termos testados; os de G² = 0 não vêm na lista) ----
kn <- ler_raiox("raiox_keyness.json")
rx <- rbindlist(lapply(c(kn$positivas, kn$negativas), function(x) list(lema = x$termo, a_rx = x$a, b_rx = x$b, g2_rx = x$g2)))
cmp <- merge(cont, rx, by = "lema", all = TRUE)
so_r <- cmp[is.na(g2_rx) & g2_2 != 0, .N]
so_rx <- cmp[is.na(g2_2), .N]
cmp2 <- cmp[!is.na(g2_rx) & !is.na(g2_2)]
dif_cont <- cmp2[a != a_rx | b != b_rx, .N]
dif_g2 <- max(abs(cmp2$g2_2 - cmp2$g2_rx))

# ---- quanteda: dfm cinzenta/acadêmica com a coluna das vazias, para os mesmos totais c e d ----
lemas <- cont$lema
m <- rbind(cinzenta = c(cont$a, c_ - sum(cont$a)), academica = c(cont$b, d_ - sum(cont$b)))
colnames(m) <- c(lemas, "__vazias__")
# "__vazias__" = vazias + termos com a + b < 5 (só completa os totais; não entra na comparação)
x <- as.dfm(as(m, "CsparseMatrix"))
qk <- as.data.table(textstat_keyness(x, target = "cinzenta", measure = "lr", correction = "none", sort = FALSE))
qk <- qk[feature != "__vazias__", .(lema = feature, g2_q = G2)]
cmp3 <- merge(cont, qk, by = "lema")
dif_q4 <- max(abs(cmp3$g2_q - cmp3$g2_4))
# o quanteda soma um deslocamento constante a |G²| (suavização interna): medir mínimo e máximo de |G²_q| − |G²_4|
desloc <- range(abs(cmp3$g2_q) - abs(cmp3$g2_4))

# ---- 2 células × 4 células: ordem das listas ----
topo <- function(dt, col, n, pos) { v <- dt[[col]]; o <- if (pos) order(-v, dt$lema) else order(v, dt$lema); dt$lema[o][1:n] }
res_top <- list()
for (lado in c("cinzenta", "academica")) {
  pos <- lado == "cinzenta"
  for (n in c(20, 50, 100)) {
    t2 <- topo(cont, "g2_2", n, pos); t4 <- topo(cont, "g2_4", n, pos)
    comuns <- intersect(t2, t4)
    rho <- cor(match(comuns, t2), match(comuns, t4), method = "spearman")
    res_top[[paste(lado, n)]] <- list(lado = lado, n = n, comuns = length(comuns), spearman = rho)
  }
}
rho_todos <- cor(cont$g2_2, cont$g2_4, method = "spearman")
rel <- cont[abs(g2_2) > 10.83, .(razao = g2_4 / g2_2)]

r <- list(
  c = c_, d = d_, termos_r = nrow(cont), termos_raiox = nrow(rx), so_no_r_com_g2 = so_r, so_no_raiox = so_rx,
  contagens_diferentes = dif_cont, max_dif_g2_2celulas = dif_g2,
  max_dif_g2_4celulas_quanteda_vs_mao = dif_q4, deslocamento_abs_quanteda = desloc,
  spearman_2x4_todos = rho_todos, razao_g2_4_sobre_2_p001 = as.list(summary(rel$razao)),
  topo = unname(res_top),
  top10_cinzenta_2 = topo(cont, "g2_2", 10, TRUE), top10_cinzenta_4 = topo(cont, "g2_4", 10, TRUE),
  top10_academica_2 = topo(cont, "g2_2", 10, FALSE), top10_academica_4 = topo(cont, "g2_4", 10, FALSE),
  versoes = list(quanteda = as.character(packageVersion("quanteda")),
                 quanteda.textstats = as.character(packageVersion("quanteda.textstats")))
)
str(r[setdiff(names(r), "topo")])
print(rbindlist(r$topo))
gravar(r, "r_keyness.json")
