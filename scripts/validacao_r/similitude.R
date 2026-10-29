# 12.2 (f) - Similitude 7.2 (índice de coocorrência, 60 formas, árvore máxima) contra o igraph.
#
# Uso: Rscript similitude.R <pasta de dados>
# Unidades = segmentos de texto (ST) sem os de ruído; formas = lemas fora das vazias; as 60 mais frequentes em
# ocorrências (empate: ordem por ponto de código); c_ij = nº de ST com as duas formas. Árvore geradora máxima pelo
# igraph::mst (pesos negados; só pares com c_ij > 0). Com empates de peso, mais de uma árvore é máxima: compara-se
# o peso total (tem de ser igual) e, nas arestas que diferem, se a troca é entre arestas de mesmo peso no ciclo.
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "comum.R"))
suppressPackageStartupMessages(library(igraph))

b <- carregar_base()
u <- b$tk[seg >= 0 & ruido == 0 & vazia == FALSE]
fr <- u[, .N, by = lema][order(-N, lema, method = "radix")][1:60]
formas <- fr$lema
u <- unique(u[lema %chin% formas, .(st = paste(doc, seg), lema)])
st <- unique(u$st)
X <- sparseMatrix(i = match(u$st, st), j = match(u$lema, formas), x = 1, dims = c(length(st), 60),
                  dimnames = list(NULL, formas))
C <- as.matrix(crossprod(X))
ij <- which(upper.tri(C) & C > 0, arr.ind = TRUE)
ar <- data.table(a = formas[ij[, 1]], b = formas[ij[, 2]], w = C[ij])
g <- graph_from_data_frame(ar[, .(a, b)], directed = FALSE, vertices = data.frame(name = formas))
E(g)$w <- ar$w
arv <- mst(g, weights = -E(g)$w)
ed_r <- as.data.table(as_data_frame(arv))[, .(a = pmin(from, to), b = pmax(from, to), w)]

sim <- ler_raiox("raiox_similitude.json")
nos_rx <- vapply(sim$nos, function(n) n$forma, "")
ed_rx <- rbindlist(lapply(sim$arestas, function(e) list(a = min(e$a, e$b), b = max(e$a, e$b), w = e$peso)))
k_r <- paste(ed_r$a, ed_r$b); k_rx <- paste(ed_rx$a, ed_rx$b)
so_r <- ed_r[!k_r %in% k_rx]; so_rx <- ed_rx[!k_rx %in% k_r]
grau <- function(ed) { t <- table(c(ed$a, ed$b)); t[order(-t, names(t))] }

r <- list(
  formas_iguais = setequal(formas, nos_rx), mesma_ordem_formas = identical(formas, nos_rx),
  segmentos = length(st), arestas_r = nrow(ed_r), arestas_rx = nrow(ed_rx),
  jaccard_arestas = jaccard(k_r, k_rx), arestas_so_r = nrow(so_r), arestas_so_rx = nrow(so_rx),
  peso_total_r = sum(ed_r$w), peso_total_rx = sum(ed_rx$w),
  pesos_das_arestas_comuns_iguais = {
    m <- merge(ed_r, ed_rx, by = c("a", "b")); all(m$w.x == m$w.y)
  },
  pesos_so_r = sort(so_r$w), pesos_so_rx = sort(so_rx$w),
  grau_max_r = as.list(head(grau(ed_r), 5)), grau_max_rx = as.list(head(grau(ed_rx), 5)),
  versao_igraph = as.character(packageVersion("igraph"))
)
str(r)
gravar(r, "r_similitude.json")
