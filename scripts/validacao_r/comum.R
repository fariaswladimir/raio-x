# 12.2 - Funções comuns da validação cruzada em R (docs/validacao_cruzada.md).
#
# Lê a pasta gerada por exportar_referencia.py (tokens contados, segmentos, palavras vazias e resultados do Raio-X)
# e refaz as contagens de forma independente. Nenhum dado do corpus fica nesta pasta de scripts: o caminho da pasta
# de dados (temporária) vem na linha de comando ou na variável de ambiente RAIOX_VAL_DADOS.

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(Matrix)
})

pasta_dados <- function() {
  a <- commandArgs(trailingOnly = TRUE)
  p <- if (length(a) >= 1) a[1] else Sys.getenv("RAIOX_VAL_DADOS")
  if (!nzchar(p) || !dir.exists(p)) stop("Informe a pasta de dados (argumento ou RAIOX_VAL_DADOS).")
  normalizePath(p, winslash = "/")
}

DADOS <- pasta_dados()
arq <- function(nome) file.path(DADOS, nome)
ler_raiox <- function(nome) fromJSON(arq(nome), simplifyVector = FALSE)

# Ordenação por pontos de código (como o sorted() do Python), independente da localidade do R.
ordem_c <- function(x) order(x, method = "radix")

carregar_base <- function() {
  docs <- fread(arq("documentos.tsv"), sep = "\t", quote = "", colClasses = "character", encoding = "UTF-8")
  docs[, doc := as.integer(doc)]
  tk <- fread(arq("tokens.tsv"), sep = "\t", quote = "", encoding = "UTF-8",
              colClasses = c(doc = "integer", i = "integer", norm = "character", lema = "character",
                             bloco = "integer", seg = "integer", ruido = "integer"), na.strings = NULL)
  sg <- fread(arq("segmentos.tsv"), sep = "\t", quote = "", encoding = "UTF-8")
  stop_ <- readLines(arq("stoplist.txt"), encoding = "UTF-8")
  stop_ <- stop_[nzchar(stop_)]
  # Filtro de palavras vazias do Raio-X: forma OU lema na lista (tokens de 1 caractere já não foram exportados).
  tk[, vazia := nchar(norm) < 2L | norm %chin% stop_ | lema %chin% stop_]
  # ordem do corpus = ordem dos documentos no arquivo (a mesma do Raio-X) e, dentro dele, a posição do token
  tk[, ord_doc := match(doc, docs$doc)]
  setorder(tk, ord_doc, i)
  sg[, ord_doc := match(doc, docs$doc)]
  setorder(sg, ord_doc, seg)
  list(docs = docs, tk = tk, sg = sg, stop = stop_)
}

gravar <- function(obj, nome) {
  write_json(obj, arq(nome), auto_unbox = TRUE, digits = NA, pretty = TRUE)
  cat("-> ", nome, "\n", sep = "")
}

# G² da tabela 2×2 completa (4 células), com 0·ln 0 = 0.
g2_4 <- function(o11, o12, o21, o22) {
  o11 <- as.numeric(o11); o12 <- as.numeric(o12); o21 <- as.numeric(o21); o22 <- as.numeric(o22)  # evita estouro de inteiro
  n <- o11 + o12 + o21 + o22
  r1 <- o11 + o12; r2 <- o21 + o22; c1 <- o11 + o21; c2 <- o12 + o22
  xl <- function(o, e) ifelse(o > 0, o * log(o / e), 0)
  2 * (xl(o11, r1 * c1 / n) + xl(o12, r1 * c2 / n) + xl(o21, r2 * c1 / n) + xl(o22, r2 * c2 / n))
}

jaccard <- function(a, b) if (length(union(a, b)) == 0) NA_real_ else length(intersect(a, b)) / length(union(a, b))
