# 12.2 (a) - CHD de Reinert 7.1 contra o rainette (Barnier), nos MESMOS segmentos e nas MESMAS formas ativas.
#
# Uso: Rscript reinert.R <pasta de dados>
# - ST = segmentos do Raio-X sem os de ruído (segmentos.tsv); formas ativas = lemas fora das vazias, F >= 3 (em
#   ocorrências nos ST), as 3.000 mais frequentes (empate por ponto de código); tabela binária ST × forma; só os
#   ST com alguma forma ativa entram (os "classificáveis" do Raio-X).
# - rainette(k = 10, min_segment_size = 0: sem fundir ST; min_split_members = 5, cc_test = 0,3, tsj = 3: padrões).
# - Descrição das classes igual para os dois lados: χ² 2 × 2 de Pearson sem correção (forma presente no ST × ST na
#   classe), só associação positiva com χ² >= 3,84; 20 formas de maior χ² por classe; documentos idem.
# - Pareamento: Jaccard das 20 formas, atribuição ótima (húngaro, clue::solve_LSAP); ARI (mclust) nos ST
#   classificados pelos dois; documentos mais associados (top 3) de cada par.
# - Extra: rainette2 (classificação dupla, min_segment_size 10 e 15 formas, full = FALSE) × dupla do Raio-X.
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "comum.R"))
suppressPackageStartupMessages({ library(quanteda); library(rainette); library(clue); library(mclust) })

b <- carregar_base()
sg <- b$sg[ruido == 0]
sg[, id := paste(doc, seg)]
u <- b$tk[seg >= 0 & ruido == 0 & vazia == FALSE]
fr <- u[, .N, by = lema][N >= 3]
fr <- fr[order(-N, lema, method = "radix")][seq_len(min(.N, 3000))]
vocab <- sort(fr$lema, method = "radix")
uu <- unique(u[lema %chin% vocab, .(id = paste(doc, seg), lema)])
X <- sparseMatrix(i = match(uu$id, sg$id), j = match(uu$lema, vocab), x = 1, dims = c(nrow(sg), length(vocab)),
                  dimnames = list(sg$id, vocab))
classif <- which(rowSums(X) > 0)
Xa <- X[classif, ]
dtm <- as.dfm(Xa)
docvars(dtm, "doc") <- sg$doc[classif]

# ---- Raio-X: classe de cada ST ----
rx <- ler_raiox("raiox_reinert.json")
cl_rx_todos <- unlist(lapply(seq_len(nrow(sg)), function(i) rx$classes_por_documento[[as.character(sg$doc[i])]][[sg$seg[i] + 1]]))
cl_rx <- cl_rx_todos[classif]
conferencia <- list(st_total_r = nrow(sg), st_total_rx = rx$segmentos_total,
                    classificaveis_r = length(classif), classificaveis_rx = rx$segmentos_classificaveis,
                    formas_r = length(vocab), formas_rx = rx$formas_ativas)
print(conferencia)

# ---- rainette ----
# Uma execução com k = 40: a sequência de bipartições do rainette não depende de k (k só limita o laço), então os
# cortes em 10 classes e em K classes saem da mesma hierarquia (conferido abaixo contra uma execução com k = 10).
t0 <- Sys.time()
res10 <- rainette(dtm, k = 10, min_segment_size = 0, min_split_members = 5, cc_test = 0.3, tsj = 3)
t_rain <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
res40 <- rainette(dtm, k = 40, min_segment_size = 0, min_split_members = 5, cc_test = 0.3, tsj = 3)
corte <- function(res, k) { g <- cutree_rainette(res, k = k); g[is.na(g)] <- 0L; g }
cl_r <- corte(res10, 10)
hierarquia_igual <- identical(cl_r, corte(res40, 10))

# Variante "rainette + regra das folhas pequenas do Raio-X": menor K em que há 10 folhas com >= min_classe ST
# (o mínimo automático do Raio-X); as folhas menores ficam sem classe e não contam (como em reinert.py).
minc <- rx$min_classe
K_reg <- NA_integer_; cl_reg <- NULL
for (K in 10:40) {
  g <- corte(res40, K); tam <- table(g[g > 0])
  if (sum(tam >= minc) >= 10) {
    validas <- as.integer(names(tam)[tam >= minc])
    g[!(g %in% validas)] <- 0L
    g[g > 0] <- match(g[g > 0], sort(validas))
    K_reg <- K; cl_reg <- g; break
  }
}

# ---- descrição das classes (mesma função para os dois) ----
descrever <- function(cl, Xb, rotulos, n = 20) {
  ok <- cl > 0; Xc <- Xb[ok, , drop = FALSE]; cl <- cl[ok]; N <- nrow(Xc)
  tot <- colSums(Xc)
  lapply(sort(unique(cl)), function(k) {
    nk <- sum(cl == k); a <- colSums(Xc[cl == k, , drop = FALSE])
    # tabela 2×2: a (na classe, com), nk − a, tot − a, N − nk − tot + a
    e <- nk * tot / N
    chi <- N * (a * (N - nk - tot + a) - (nk - a) * (tot - a))^2 / (nk * (N - nk) * tot * (N - tot))
    chi[!is.finite(chi)] <- 0
    pos <- which(a > e & chi >= 3.84)
    o <- pos[order(-chi[pos], rotulos[pos], method = "radix")]
    list(classe = k, n_st = nk, top = rotulos[o][seq_len(min(n, length(o)))], chi = unname(chi[o][seq_len(min(n, length(o)))]))
  })
}
D <- sparseMatrix(i = seq_along(classif), j = match(sg$doc[classif], b$docs$doc), x = 1,
                  dims = c(length(classif), nrow(b$docs)))
rot_doc <- ifelse(nzchar(b$docs$id_estudo), b$docs$id_estudo, b$docs$arquivo)
desc_rx <- descrever(cl_rx, Xa, vocab)
docs_rx <- descrever(cl_rx, D, rot_doc, 3)

# conferência: as 20 formas do Raio-X recalculadas aqui = as do JSON?
top_json <- lapply(rx$classes, function(c) vapply(c$formas[seq_len(min(20, length(c$formas)))], function(f) f$forma, ""))
conf_top <- mapply(function(a, b) identical(a, b$top), top_json, desc_rx)

# ---- pareamento (húngaro sobre Jaccard das 20 formas), ARI e documentos ----
comparar <- function(cl_r) {
  desc_r <- descrever(cl_r, Xa, vocab); docs_r <- descrever(cl_r, D, rot_doc, 3)
  J <- outer(seq_along(desc_rx), seq_along(desc_r), Vectorize(function(i, j) jaccard(desc_rx[[i]]$top, desc_r[[j]]$top)))
  if (nrow(J) <= ncol(J)) {
    atr <- as.integer(solve_LSAP(J, maximum = TRUE)); pares <- cbind(seq_len(nrow(J)), atr)
  } else {
    atr <- as.integer(solve_LSAP(t(J), maximum = TRUE)); pares <- cbind(atr, seq_len(ncol(J)))
  }
  tab <- rbindlist(lapply(seq_len(nrow(pares)), function(p) {
    i <- pares[p, 1]; j <- pares[p, 2]
    list(classe_rx = desc_rx[[i]]$classe, classe_r = desc_r[[j]]$classe,
         n_rx = desc_rx[[i]]$n_st, n_r = desc_r[[j]]$n_st, jaccard20 = J[i, j],
         docs_rx = paste(docs_rx[[i]]$top, collapse = ", "), docs_r = paste(docs_r[[j]]$top, collapse = ", "),
         docs_comuns_top3 = length(intersect(docs_rx[[i]]$top, docs_r[[j]]$top)),
         doc1_igual = identical(docs_rx[[i]]$top[1], docs_r[[j]]$top[1]),
         formas_rx = paste(head(desc_rx[[i]]$top, 6), collapse = " "), formas_r = paste(head(desc_r[[j]]$top, 6), collapse = " "))
  }))
  ambos <- cl_rx > 0 & cl_r > 0
  list(k = length(desc_r), retencao_pct = 100 * sum(cl_r > 0) / nrow(sg),
       tamanhos = vapply(desc_r, function(d) d$n_st, 0),
       pares = tab, jaccard_ge_03 = sum(tab$jaccard20 >= 0.3), n_pares = nrow(tab),
       jaccard_mediana = median(tab$jaccard20),
       docs_top3_2oumais = sum(tab$docs_comuns_top3 >= 2), doc1_igual = sum(tab$doc1_igual),
       ari = adjustedRandIndex(cl_rx[ambos], cl_r[ambos]), st_nos_dois = sum(ambos),
       tabela_cruzada = unclass(as.matrix(table(raiox = cl_rx[ambos], rainette = cl_r[ambos]))),
       formas_classes_r = lapply(desc_r, function(d) list(classe = d$classe, n_st = d$n_st, top6 = head(d$top, 6))))
}
cmp10 <- comparar(cl_r)
cmp_reg <- if (!is.null(cl_reg)) comparar(cl_reg) else NULL

# ---- extra: classificação dupla ----
dupla <- tryCatch({
  dtm2 <- dtm
  docvars(dtm2, "segment_source") <- as.character(sg$doc[classif])
  r1 <- rainette(dtm2, k = 10, min_segment_size = 10, doc_id = "segment_source")
  r2 <- rainette(dtm2, k = 10, min_segment_size = 15, doc_id = "segment_source")
  rr <- rainette2(r1, r2, max_k = 10, full = FALSE)
  ks <- sort(unique(rr$k))
  por_k <- lapply(ks, function(k) { g <- cutree_rainette2(rr, k); list(k = k, retencao_pct = 100 * mean(!is.na(g)) * length(classif) / nrow(sg)) })
  rxd <- ler_raiox("raiox_reinert_dupla.json")
  list(rainette2 = por_k, raiox_k = rxd$k, raiox_retencao_pct = rxd$retencao_pct)
}, error = function(e) list(erro = conditionMessage(e)))

r <- list(
  conferencia = conferencia, conferencia_top20_raiox = unname(conf_top),
  raiox = list(k = rx$k, retencao_pct = rx$retencao_pct, min_classe = rx$min_classe,
               tamanhos = vapply(desc_rx, function(d) d$n_st, 0)),
  rainette = list(versao = as.character(packageVersion("rainette")), segundos_k10 = t_rain,
                  hierarquia_k40_igual_k10 = hierarquia_igual),
  rainette_k10 = cmp10,
  rainette_regra_folhas = c(list(K_rainette = K_reg), cmp_reg),
  dupla = dupla
)
for (nome in c("rainette_k10", "rainette_regra_folhas")) {
  x <- r[[nome]]; cat("
=====", nome, "K =", x$K_rainette, " k =", x$k, " retenção =", round(x$retencao_pct, 2),
                      " ARI =", round(x$ari, 3), " Jaccard>=0,3:", x$jaccard_ge_03, "/", x$n_pares,
                      " docs top3 >=2:", x$docs_top3_2oumais, " doc1 igual:", x$doc1_igual, "
")
  print(x$tamanhos); print(x$pares[, !c("formas_rx", "formas_r")]); print(x$pares[, .(classe_rx, classe_r, formas_rx, formas_r)])
  print(x$tabela_cruzada)
}
str(dupla)
gravar(r, "r_reinert.json")
