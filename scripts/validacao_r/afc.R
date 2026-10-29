# 12.2 (d) - AFC 7.3 (termo × ano, 100 lemas mais frequentes) contra FactoMineR::CA e ca::ca.
#
# Uso: Rscript afc.R <pasta de dados>
# Tabela recontada de tokens.tsv: lemas fora das vazias com F >= 5, os 100 mais frequentes (empate: ordem
# alfabética por ponto de código, como no Raio-X); partes sem nenhuma ocorrência saem.
# O sinal de cada eixo é arbitrário: compara-se |correlação| das coordenadas e a diferença máxima depois de alinhar
# o sinal; contribuições e autovalores não dependem do sinal.
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "comum.R"))
suppressPackageStartupMessages({ library(FactoMineR); library(ca) })

b <- carregar_base()
tk <- merge(b$tk[vazia == FALSE], b$docs[, .(doc, ano)], by = "doc")
fr <- tk[, .N, by = lema][N >= 5]
fr <- fr[order(-N, lema, method = "radix")][1:100]
cont <- dcast(tk[lema %chin% fr$lema, .N, by = .(lema, ano)], lema ~ ano, value.var = "N", fill = 0)
anos <- setdiff(names(cont), "lema")
M <- as.matrix(cont[, ..anos]); rownames(M) <- cont$lema
M <- M[, colSums(M) > 0, drop = FALSE]

rx <- ler_raiox("raiox_afc_ano.json")
k <- rx$k
termos_rx <- vapply(rx$linhas, function(x) x$termo, "")
partes_rx <- vapply(rx$colunas, function(x) as.character(x$rotulo), "")
mesmos_termos <- setequal(termos_rx, rownames(M))
M <- M[termos_rx, , drop = FALSE]
chave_partes <- vapply(rx$colunas, function(x) as.character(if (!is.null(x$chave)) x$chave else x$rotulo), "")
M <- M[, match(chave_partes, colnames(M)), drop = FALSE]
freq_rx <- vapply(rx$linhas, function(x) as.numeric(x$freq), 0)

fm <- CA(as.data.frame(M), ncp = k, graph = FALSE)
cc <- ca(M, nd = k)
eig_rx <- vapply(rx$eixos, function(x) as.numeric(x$autovalor), 0)
pct_rx <- vapply(rx$eixos, function(x) as.numeric(x$pct), 0)
mat_rx <- function(itens, campo) t(vapply(itens, function(x) as.numeric(unlist(x[[campo]])), numeric(k)))

comparar <- function(A, B) {  # A = Raio-X, B = R; por eixo
  sapply(seq_len(k), function(e) {
    r <- cor(A[, e], B[, e]); s <- sign(r)
    c(abs_cor = abs(r), max_dif_sinal_alinhado = max(abs(A[, e] - s * B[, e])), sinal = s)
  })
}
lin_rx <- mat_rx(rx$linhas, "coord"); col_rx <- mat_rx(rx$colunas, "coord")
ctr_l_rx <- mat_rx(rx$linhas, "ctr"); ctr_c_rx <- mat_rx(rx$colunas, "ctr")
r <- list(
  dimensao = dim(M), mesmos_termos = mesmos_termos, freq_iguais = all(rowSums(M) == freq_rx), partes = partes_rx,
  autovalores_raiox = eig_rx, autovalores_factominer = unname(fm$eig[1:k, 1]), autovalores_ca = unname(cc$sv[1:k]^2),
  max_dif_autovalor = max(abs(eig_rx - fm$eig[1:k, 1])),
  max_dif_autovalor_ca = max(abs(eig_rx - cc$sv[1:k]^2)),
  pct_raiox = pct_rx, pct_factominer = unname(fm$eig[1:k, 2]),
  max_dif_pct = max(abs(pct_rx - fm$eig[1:k, 2])),
  inercia_total_raiox = rx$inercia_total, inercia_total_r = sum(fm$eig[, 1]),
  coord_termos = comparar(lin_rx, fm$row$coord[, 1:k, drop = FALSE]),
  coord_partes = comparar(col_rx, fm$col$coord[, 1:k, drop = FALSE]),
  coord_termos_ca = comparar(lin_rx, (cc$rowcoord %*% diag(cc$sv))[, 1:k, drop = FALSE]),
  max_dif_ctr_termos = max(abs(ctr_l_rx - fm$row$contrib[, 1:k])),
  max_dif_ctr_partes = max(abs(ctr_c_rx - fm$col$contrib[, 1:k])),
  max_dif_cos2_termos = max(abs(mat_rx(rx$linhas, "cos2") - fm$row$cos2[, 1:k])),
  versoes = list(FactoMineR = as.character(packageVersion("FactoMineR")), ca = as.character(packageVersion("ca")))
)
str(r)
gravar(r, "r_afc.json")
