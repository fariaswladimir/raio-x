"""17.1 - Modelos prontos de protocolo.

``partes_artigo`` ("Partes do artigo"): as 13 partes da planilha do corpus (16.1). Cada item está **ligado** à parte (``parte_planilha``) e usa **as mesmas
regras** (``corpus/partes.py``: seção detectada ou padrões de linguagem, via ``planilha.analise_do_documento``): o resultado é idêntico ao da planilha do corpus.
``onde_procurar`` e ``palavras_chave`` mostram as seções e as expressões típicas da parte; valem só se a ligação for removida (aí o item vira uma regra comum).

``revisao_sistematica`` ("Revisão sistemática (genérico)"): 12 itens típicos de extração de dados de uma RSL/MLR, com tipos e categorias (cada categoria com
palavras-chave para a coleta por regras). Ajuste ao seu protocolo; objetivo, perguntas e limitações reaproveitam as regras da 16.1.
"""
from app.services.coleta import protocolo as PR
from app.services.corpus import partes as P

DEFINICOES_PARTES = {
    "resumo": "Resumo (abstract) do documento. Texto da seção, copiado sem reescrita.",
    "introducao": "Introdução do documento, com contexto e justificativa. Texto da seção detectada, até 1.500 caracteres.",
    "objetivo": "O que os autores dizem querer fazer, investigar ou propor. Frases que declaram o objetivo do estudo.",
    "perguntas": "Perguntas de pesquisa ou hipóteses formuladas pelos autores. Frases com RQ, hipótese ou pergunta direta.",
    "referencial": "Referencial teórico ou revisão de literatura. Texto da seção detectada.",
    "metodo": "Desenho, procedimentos e técnicas de análise do estudo. Texto da seção de método.",
    "dados": "Dados, amostra ou contexto empírico: de onde vêm, quantos e quem. Frases como \"the sample consists\" ou \"os dados foram coletados\".",
    "resultados": "Principais resultados apresentados. Texto da seção de resultados.",
    "discussao": "Discussão dos resultados pelos autores. Texto da seção de discussão.",
    "conclusao": "Conclusão do documento. Texto da seção de conclusão.",
    "limitacoes": "Limitações que os autores reconhecem no próprio estudo. Exige expressão de limitação, não só a palavra.",
    "futuros": "Sugestões de pesquisas ou trabalhos futuros. Frases com \"future research\" ou \"trabalhos futuros\".",
    "contribuicoes": "Contribuições e implicações teóricas, práticas ou de política declaradas pelos autores. Frases como \"we contribute\" ou \"implicações para\".",
}
PALAVRAS_PARTES = {
    "objetivo": ["this paper aims", "the aim of this", "our goal is", "in this paper we", "tem como objetivo", "objetivo"],
    "perguntas": ["research question", "RQ1", "we hypothesize", "hypothesis", "pergunta de pesquisa", "hipótese"],
    "dados": ["data were collected", "the sample consists", "our sample", "dataset", "a amostra", "participants"],
    "limitacoes": ["limitations of this study", "a limitation", "interpreted with caution", "cannot be generalized", "limitações deste estudo"],
    "futuros": ["future research", "future work", "further research", "pesquisas futuras", "trabalhos futuros"],
    "contribuicoes": ["we contribute", "contribution*", "implications for", "contribui", "implicações"],
}


def _partes_artigo() -> list[dict]:
    itens = []
    for chave, rotulo, modo, tipo_secao in P.PARTES:
        if modo == "secao":
            onde = [tipo_secao]
        else:
            pref = P.PREFERENCIA[chave][0]
            onde = [s for s, b in sorted(pref.items(), key=lambda kv: -kv[1]) if b > 0 and s != "*"]
        itens.append({"id": chave, "nome": rotulo, "definicao": DEFINICOES_PARTES[chave], "tipo": "texto", "onde_procurar": onde,
                      "palavras_chave": PALAVRAS_PARTES.get(chave, []), "obrigatorio": False, "max_trechos": 3, "parte_planilha": chave})
    return itens


def _cat(valor: str, definicao: str, palavras: list[str] | None = None) -> dict:
    return {"valor": valor, "definicao": definicao, "palavras_chave": palavras or []}


def _revisao_sistematica() -> list[dict]:
    return [
        {"id": "objetivo", "nome": "Objetivo", "definicao": "O objetivo declarado pelos autores. Frase que diz o que o estudo pretende fazer.", "tipo": "texto",
         "onde_procurar": ["resumo", "introducao"], "palavras_chave": [], "obrigatorio": True, "max_trechos": 3, "parte_planilha": "objetivo"},
        {"id": "perguntas", "nome": "Perguntas de pesquisa", "definicao": "Perguntas de pesquisa ou hipóteses do estudo. Frases com RQ, hipótese ou pergunta direta.", "tipo": "texto",
         "onde_procurar": ["introducao", "referencial", "resumo"], "palavras_chave": [], "obrigatorio": False, "max_trechos": 3, "parte_planilha": "perguntas"},
        {"id": "desenho", "nome": "Desenho do estudo", "definicao": "Estratégia metodológica principal do estudo. Escolha a categoria que melhor descreve como os dados foram produzidos.", "tipo": "categoria",
         "categorias": [
             _cat("Experimento", "Intervenção com atribuição controlada ou aleatória.", ["experiment*", "randomi*", "field experiment", "ensaio"]),
             _cat("Quase-experimento", "Efeito causal sem aleatorização, por comparação de grupos ou períodos.", ["quasi-experiment*", "difference-in-differences", "regression discontinuity", "quase-experiment*"]),
             _cat("Survey", "Questionário aplicado a uma amostra.", ["survey*", "questionnaire*", "questionário*", "respondents", "Likert", "encuesta"]),
             _cat("Estudo de caso", "Análise aprofundada de um ou poucos casos.", ["case study", "case studies", "estudo de caso", "estudos de caso", "estudio de caso"]),
             _cat("Entrevistas/qualitativo", "Coleta e análise qualitativa de falas ou observações.", ["interview*", "semi-structured", "thematic analysis", "grounded theory", "entrevista*", "focus group"]),
             _cat("Revisão de literatura", "Síntese de estudos anteriores.", ["systematic review", "literature review", "scoping review", "meta-analysis", "revisão sistemática", "revisão da literatura"]),
             _cat("Modelagem/simulação", "Modelo formal ou simulação computacional.", ["simulation*", "agent-based", "theoretical model", "formal model", "simulação", "modelo teórico"]),
             _cat("Dados secundários", "Análise de bases já existentes.", ["panel data", "secondary data", "archival", "econometric", "administrative data", "dados secundários"]),
             _cat("Métodos mistos", "Combinação planejada de métodos qualitativos e quantitativos.", ["mixed methods", "mixed-methods", "métodos mistos"]),
             _cat("Outro", "Nenhuma das anteriores."),
         ], "onde_procurar": ["resumo", "metodos"], "palavras_chave": [], "obrigatorio": True, "max_trechos": 3},
        {"id": "coleta", "nome": "Método de coleta de dados", "definicao": "Como os dados foram obtidos. Marque todas as formas de coleta citadas.", "tipo": "multipla",
         "categorias": [
             _cat("Entrevistas", "Conversas com participantes.", ["interview*", "entrevista*"]),
             _cat("Questionário", "Instrumento aplicado a respondentes.", ["questionnaire*", "survey*", "questionário*", "respondents"]),
             _cat("Observação/campo", "Observação direta ou trabalho de campo.", ["observation*", "ethnograph*", "fieldwork", "field study", "observação"]),
             _cat("Dados secundários/registros", "Bases e registros preexistentes.", ["secondary data", "administrative data", "archival", "dataset", "registros administrativos"]),
             _cat("Coleta automatizada", "Extração por API ou raspagem.", ["scrap*", "crawl*", "API", "web data", "raspagem"]),
             _cat("Experimento", "Tarefa ou intervenção controlada.", ["experiment*", "randomi*", "laboratory"]),
             _cat("Análise documental/literatura", "Leitura de documentos ou de artigos.", ["document analysis", "content analysis", "literature search", "análise documental"]),
             _cat("Grupo focal/oficina", "Discussão em grupo.", ["focus group*", "workshop*", "grupo focal", "oficina"]),
             _cat("Outro", "Nenhuma das anteriores."),
         ], "onde_procurar": ["metodos", "resumo"], "palavras_chave": [], "obrigatorio": False, "max_trechos": 3},
        {"id": "amostra", "nome": "Amostra/tamanho", "definicao": "Número de unidades analisadas (participantes, empresas, documentos ou observações). Registrar o total da amostra final.", "tipo": "numero",
         "onde_procurar": ["metodos", "resumo"],
         "palavras_chave": ["sample*", "respondent*", "participant*", "firm*", "compan*", "startup*", "interview*", "observation*", "studies", "articles", "amostra",
                            "respondente*", "empresa*", "entrevistad*", "/\\bn\\s*=\\s*\\d/"], "obrigatorio": True, "max_trechos": 3},
        {"id": "contexto", "nome": "Contexto/país", "definicao": "País, região ou contexto institucional em que o estudo ocorre. Copiar a frase que o indica.", "tipo": "texto",
         "onde_procurar": ["metodos", "resumo", "introducao"],
         "palavras_chave": ["countries", "country", "Brazil", "Brasil", "\"United States\"", "USA", "China", "India", "Germany", "\"United Kingdom\"", "France", "Canada",
                            "Japan", "Korea", "Australia", "Europe*", "Africa*", "Asia*", "\"Latin America\"", "Portugal", "Spain", "Mexico"], "obrigatorio": False, "max_trechos": 2},
        {"id": "setor", "nome": "Setor/indústria", "definicao": "Setor econômico em que se concentra o estudo. Escolha o predominante.", "tipo": "categoria",
         "categorias": [
             _cat("Tecnologia/software", "Empresas e produtos digitais.", ["software", "tech", "SaaS", "\"digital platform*\"", "\"technology sector\"", "tecnologia"]),
             _cat("Saúde", "Serviços e pesquisa em saúde.", ["health*", "hospital*", "clinical", "saúde"]),
             _cat("Educação", "Ensino e aprendizagem.", ["education*", "school*", "universit*", "student*", "educação"]),
             _cat("Finanças", "Bancos, investimento e crédito.", ["financ*", "bank*", "fintech", "\"venture capital\"", "finanças"]),
             _cat("Indústria/manufatura", "Produção industrial.", ["manufactur*", "industrial", "factory", "indústria"]),
             _cat("Varejo/comércio", "Comércio e consumo.", ["retail*", "e-commerce", "varejo", "comércio"]),
             _cat("Setor público", "Governo e políticas públicas.", ["government*", "\"public sector\"", "municipal", "setor público"]),
             _cat("Agricultura", "Agro e alimentos.", ["agricultur*", "farm*", "agro*"]),
             _cat("Serviços profissionais", "Consultoria, direito, marketing.", ["consulting", "\"professional services\"", "marketing", "serviços profissionais"]),
             _cat("Multissetorial", "Vários setores sem predominância.", ["multi-sector", "cross-sector", "\"across industries\"", "\"various industries\"", "\"several industries\"", "multissetorial"]),
             _cat("Outro", "Nenhum dos anteriores."),
         ], "onde_procurar": ["resumo", "metodos", "introducao"], "palavras_chave": [], "obrigatorio": False, "max_trechos": 3},
        {"id": "tecnologia", "nome": "Tecnologia/IA estudada", "definicao": "Tipo de tecnologia ou de IA que o estudo investiga. Marque todas as que forem objeto do estudo.", "tipo": "multipla",
         "categorias": [
             _cat("IA generativa/LLM", "Modelos de linguagem e geradores de conteúdo.", ["LLM*", "\"large language model*\"", "\"generative AI\"", "GenAI", "ChatGPT", "GPT*", "\"IA generativa\""]),
             _cat("Agentes de IA", "Sistemas que agem de forma autônoma.", ["agent*", "agentic", "multi-agent", "\"AI agent*\"", "autonomous", "agentes de IA"]),
             _cat("Aprendizado de máquina", "Modelos preditivos clássicos.", ["\"machine learning\"", "\"deep learning\"", "\"neural network*\"", "aprendizado de máquina"]),
             _cat("Chatbots/assistentes", "Interfaces conversacionais.", ["chatbot*", "assistant*", "copilot*", "\"virtual assistant*\""]),
             _cat("Automação/robótica", "Automação de processos e robôs.", ["automation", "RPA", "robot*", "automação"]),
             _cat("Visão/linguagem natural", "Visão computacional e PLN.", ["\"computer vision\"", "NLP", "\"natural language processing\""]),
             _cat("Outro", "Nenhuma das anteriores."),
         ], "onde_procurar": ["resumo", "introducao", "metodos"], "palavras_chave": [], "obrigatorio": True, "max_trechos": 3},
        {"id": "achados", "nome": "Principais achados", "definicao": "Resultados centrais relatados pelos autores. Copiar as frases que enunciam o achado principal.", "tipo": "texto",
         "onde_procurar": ["resumo", "resultados", "conclusao"],
         "palavras_chave": ["\"we find\"", "\"results show\"", "findings", "\"our results\"", "\"results indicate\"", "mostram que", "encontramos", "\"we conclude\""], "obrigatorio": True, "max_trechos": 3},
        {"id": "limitacoes", "nome": "Limitações", "definicao": "Limitações que os autores reconhecem no próprio estudo. Exige expressão de limitação, não só a palavra.", "tipo": "texto",
         "onde_procurar": ["discussao", "conclusao"], "palavras_chave": [], "obrigatorio": False, "max_trechos": 3, "parte_planilha": "limitacoes"},
        {"id": "financiamento", "nome": "Financiamento/conflito de interesses", "definicao": "Fonte de financiamento e conflitos de interesse declarados. Copiar a declaração, inclusive \"sem financiamento\".", "tipo": "texto",
         "onde_procurar": ["agradecimentos", "declaracoes", "outro", "conclusao"],
         "palavras_chave": ["funding", "funded", "\"financial support\"", "grant*", "\"conflict of interest\"", "\"conflicts of interest\"", "\"competing interests\"", "\"supported by\"",
                            "financiamento", "bolsa", "\"conflito de interesse\""], "obrigatorio": False, "max_trechos": 2},
        {"id": "evidencia", "nome": "Nível de evidência", "definicao": "Força da evidência empírica do estudo, da mais forte à mais fraca. Classifique pelo desenho e pela análise relatados.", "tipo": "categoria",
         "categorias": [
             _cat("Experimental/causal", "Atribuição controlada ou identificação causal.", ["randomi*", "\"field experiment\"", "causal", "difference-in-differences", "\"instrumental variable*\""]),
             _cat("Observacional quantitativo", "Dados observados com análise estatística.", ["\"panel data\"", "regression*", "\"cross-sectional\"", "longitudinal", "observational", "econometric"]),
             _cat("Qualitativo/estudo de caso", "Casos, entrevistas ou análise temática.", ["\"case study\"", "interview*", "\"thematic analysis\"", "qualitative", "estudo de caso"]),
             _cat("Revisão/síntese", "Síntese de outros estudos.", ["\"systematic review\"", "meta-analysis", "\"literature review\"", "\"scoping review\""]),
             _cat("Relato prático/opinião", "Relatório de prática, blog ou opinião.", ["\"white paper\"", "\"industry report\"", "practitioner*", "opinion", "relatório"]),
             _cat("Conceitual/teórico", "Argumento ou modelo sem dados empíricos.", ["conceptual", "\"theoretical framework\"", "\"we propose a framework\"", "teórico"]),
         ], "onde_procurar": ["resumo", "metodos"], "palavras_chave": [], "obrigatorio": False, "max_trechos": 3},
    ]


MODELOS = {
    "partes_artigo": {"nome": "Partes do artigo", "descricao": "As 13 partes da planilha do corpus (16.1), com as mesmas regras (seção detectada ou padrões de linguagem).", "construtor": _partes_artigo},
    "revisao_sistematica": {"nome": "Revisão sistemática (genérico)", "descricao": "12 itens típicos de extração de dados de uma RSL/MLR: objetivo, perguntas, desenho, coleta, amostra, contexto, setor, tecnologia, achados, limitações, financiamento e nível de evidência.",
                            "construtor": _revisao_sistematica},
}


def listar() -> list[dict]:
    return [{"id": k, "nome": v["nome"], "descricao": v["descricao"], "itens": len(v["construtor"]())} for k, v in MODELOS.items()]


def obter(modelo_id: str) -> dict:
    """Modelo com os itens já normalizados (mesma validação do salvar). Levanta KeyError."""
    if modelo_id not in MODELOS:
        raise KeyError(f"Modelo '{modelo_id}' não existe. Use: {', '.join(MODELOS)}.")
    m = MODELOS[modelo_id]
    itens, problemas = PR.validar_itens(m["construtor"]())
    return {"id": modelo_id, "nome": m["nome"], "descricao": m["descricao"], "itens": itens, "erros": PR.so_erros(problemas), "avisos": [p for p in problemas if p["gravidade"] == "aviso"]}
