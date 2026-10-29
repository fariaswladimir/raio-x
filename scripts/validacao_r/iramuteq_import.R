# 12.2 - Conferência da exportação corpus-iramuteq.txt com o leitor de corpus IRaMuTeQ do rainette.
#
# Uso: Rscript iramuteq_import.R <pasta de dados>
# Lê o arquivo com rainette::import_corpus_iramuteq (o mesmo formato "**** *var_mod" do IRaMuTeQ), confere o nº de
# textos e as variáveis estreladas (doc, grupo, ano) contra documentos.tsv e mede a segmentação do rainette
# (split_segments, 40 palavras) só como referência: o IRaMuTeQ e o rainette segmentam com regras próprias.
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "comum.R"))
suppressPackageStartupMessages({ library(quanteda); library(rainette) })

b <- carregar_base()
corp <- import_corpus_iramuteq(arq("corpus-iramuteq.txt"))
dv <- docvars(corp)
# só documentos com corpo (os outros não entram na exportação); sem id do estudo o rótulo é id<nº do banco>
com_corpo <- unique(b$tk$doc)
docs_tsv <- b$docs[doc %in% com_corpo, .(doc_mod = ifelse(nzchar(id_estudo), id_estudo, sprintf("id%03d", doc)), grupo, ano)]
seg <- split_segments(corp, segment_size = 40)
r <- list(
  textos = ndoc(corp), documentos_tsv = nrow(b$docs), documentos_com_corpo = nrow(docs_tsv),
  doc_unicos = !anyDuplicated(as.character(dv$doc)),
  variaveis = names(dv),
  grupos = as.list(table(dv$grupo)), anos = as.list(table(dv$ano)),
  docs_iguais = setequal(as.character(dv$doc), gsub("[^0-9A-Za-z]+", "_", docs_tsv$doc_mod)),
  segmentos_rainette_40 = ndoc(seg), segmentos_raiox = nrow(b$sg), segmentos_raiox_sem_ruido = b$sg[ruido == 0, .N]
)
str(r)
gravar(r, "r_iramuteq_import.json")
