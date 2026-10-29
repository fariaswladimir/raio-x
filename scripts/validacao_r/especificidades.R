# 12.2 (c) - Especificidades 6.2 (Lafon, partição por ano, lema) contra textometry::specificities e contra uma
# implementação independente com phyper em escala logarítmica.
#
# Uso: Rscript especificidades.R <pasta de dados>
# Tabela termo × ano recontada de tokens.tsv: termos fora das vazias com F >= 5; tamanhos t e T com todos os tokens
# contados (com as vazias). Para o textometry usar os mesmos t e T, a tabela recebe uma linha "__resto__" (vazias e
# termos raros), que só completa as margens.
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "comum.R"))
suppressPackageStartupMessages(library(textometry))

b <- carregar_base()
tk <- merge(b$tk, b$docs[, .(doc, ano)], by = "doc")
tam <- tk[, .N, by = ano]
T_ <- sum(tam$N)
cont <- dcast(tk[vazia == FALSE, .N, by = .(lema, ano)], lema ~ ano, value.var = "N", fill = 0)
anos <- setdiff(names(cont), "lema")
M <- as.matrix(cont[, ..anos]); rownames(M) <- cont$lema
M <- M[rowSums(M) >= 5, , drop = FALSE]
t_ <- tam$N[match(anos, tam$ano)]
resto <- t_ - colSums(M)
L <- rbind(M, "__resto__" = resto)
stopifnot(all(colSums(L) == t_), sum(L) == T_)

# ---- textometry (CRAN): lado pela média F·t/T; P(X >= f) somando dhyper; arredondado a 4 casas; Inf se P = 0 ----
spe_tm <- specificities(L)[rownames(M), , drop = FALSE]

# ---- independente: phyper com log.p (sem estouro por baixo), lado pela média (convenção do Raio-X) ----
score_log <- function(f, F, t, T) {
  esp <- F * t / T
  ifelse(f >= esp,
         -phyper(f - 1, F, T - F, t, lower.tail = FALSE, log.p = TRUE) / log(10),
         phyper(f, F, T - F, t, lower.tail = TRUE, log.p = TRUE) / log(10))
}
Fv <- rowSums(M)
spe_ph <- sapply(seq_along(anos), function(j) score_log(M[, j], Fv, t_[j], T_))
dimnames(spe_ph) <- dimnames(M)
# convenção alternativa (moda da hipergeométrica) só para medir quantas células mudariam de lado
moda <- sapply(seq_along(anos), function(j) floor((Fv + 1) * (t_[j] + 1) / (T_ + 2)))
entre <- sum((M >= sapply(seq_along(anos), function(j) Fv * t_[j] / T_)) != (M >= moda))

# ---- Raio-X: 50 positivos e 50 negativos por ano ----
esp <- ler_raiox("raiox_especificidades_ano.json")
linhas <- list()
for (p in esp$partes) {
  for (s in c("positivas", "negativas")) for (k in p[[s]])
    linhas[[length(linhas) + 1]] <- list(ano = p$chave, lema = k$termo, f = k$f, F = k$F, score_rx = k$score,
                                         teto = isTRUE(k$acima_do_teto), lado = s)
}
rx <- rbindlist(linhas)
rx[, ano := as.character(ano)]
rx[, f_r := M[cbind(match(lema, rownames(M)), match(ano, anos))]]
rx[, sc_ph := spe_ph[cbind(match(lema, rownames(M)), match(ano, anos))]]
rx[, sc_tm := spe_tm[cbind(match(lema, rownames(M)), match(ano, anos))]]
rx[, sc_ph_teto := pmax(pmin(sc_ph, 50), -50)]
abaixo <- rx[teto == FALSE]
acima <- rx[teto == TRUE]

# listas: os 50 positivos de cada ano pelo phyper (sem teto) = os do Raio-X?
iguais <- sapply(unique(rx$ano), function(a) {
  r_rx <- rx[ano == a & lado == "positivas", lema]
  v <- spe_ph[, a]; o <- order(-v, -Fv, rownames(M), method = "radix")
  r_r <- rownames(M)[o][v[o] >= 2][seq_along(r_rx)]
  c(n = length(r_rx), comuns = length(intersect(r_rx, r_r)), mesma_ordem = identical(r_rx, r_r))
})

tm_fin <- abaixo[is.finite(sc_tm)]
r <- list(
  T = T_, partes = setNames(as.list(t_), anos), termos = nrow(M), linhas_comparadas = nrow(rx),
  contagens_diferentes = rx[f != f_r, .N],
  max_dif_phyper_sem_teto = max(abs(abaixo$score_rx - abaixo$sc_ph)),
  teto_concorda = all(abs(acima$sc_ph) >= 50),
  n_acima_do_teto = nrow(acima),
  max_dif_textometry_finitos = max(abs(tm_fin$score_rx - tm_fin$sc_tm)),
  textometry_infinito_abaixo_do_teto = abaixo[!is.finite(sc_tm), .N],
  textometry_infinito_acima_do_teto = acima[!is.finite(sc_tm), .N],
  textometry_vs_phyper_max_dif = {
    ok <- is.finite(spe_tm) & abs(spe_ph) < 300
    max(abs(spe_tm[ok] - spe_ph[ok]))
  },
  celulas_media_vs_moda = entre, celulas_total = length(M),
  max_abs_score_nessas_celulas = {
    lado_media <- M >= sapply(seq_along(anos), function(j) Fv * t_[j] / T_)
    dif <- lado_media != (M >= moda)
    if (any(dif)) max(abs(spe_ph[dif])) else 0
  },
  listas_positivas_por_ano = lapply(as.data.frame(iguais), as.list),
  versao_textometry = as.character(packageVersion("textometry"))
)
str(r)
gravar(r, "r_especificidades.json")
