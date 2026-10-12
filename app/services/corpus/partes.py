"""16.1 - Planilha do corpus: partes do artigo por documento, preenchidas **sem LLM** por regras determinísticas.

Cada documento recebe, para cada uma das 13 partes (``PARTES``), de zero a N trechos, cada um com página, seção de origem, regra
(``regra``), método (``secao`` | ``padrao`` | ``llm``) e nota. Nada é inventado: sem trecho a célula diz "não encontrado".

Texto-base: as frases do corpo de ``analises/texto_documento.py`` (sem referências/apêndice/agradecimentos e **sem os segmentos de
ruído** marcados na etapa 3.4: autores, tabelas, cláusulas repetidas), com página e seção (3.1). Só frases "elegíveis"
(6 a 90 palavras, terminadas em pontuação, sem URL/DOI, menos de 15% de dígitos, fora de legendas e sumários).

Partes por seção (``Resumo``, ``Introdução``, ``Referencial teórico``, ``Método``, ``Resultados``, ``Discussão``, ``Conclusão``)
-----------------------------------------------------------------------------------------------------------------------------
Todas as frases da seção detectada com o tipo correspondente (``resumo``, ``introducao``, ``referencial``, ``metodos``,
``resultados``, ``discussao``, ``conclusao``), na ordem do texto, até ``max_caracteres`` (padrão **1500**) cortando **no fim de uma
frase**; se cortou, acrescenta " (…)". A página é a da primeira frase (ou "pp. a-b" quando o trecho cobre mais de uma).

Partes por padrão (``Objetivo``, ``Perguntas de pesquisa/hipóteses``, ``Dados/amostra/contexto``, ``Limitações``, ``Trabalhos futuros``,
``Contribuições/implicações``)
-------------------------------------------------------------------------------------------------------------------------------
Cada frase elegível é pontuada pelos padrões da parte (``PADROES``; EN/PT/ES; força de 1 a 3, soma 0,5 por padrão adicional distinto):

    nota = força do melhor padrão + 0,5 x (outros padrões distintos, no máximo 2) + bônus da seção + bônus de posição

- bônus de seção (``PREFERENCIA``): ex. Objetivo prefere resumo (+1,5) e introdução (+1); Limitações prefere discussão e conclusão (+1,5);
  Dados/amostra prefere método (+1,5);
- bônus de posição (0 a 0,5): Objetivo/Perguntas/Dados/Contribuições favorecem o começo do documento; Limitações/Trabalhos futuros, o fim;
- só entra quem tem nota >= ``nota_minima`` (padrão 2,0); as ``max_frases`` (padrão **3**) de maior nota ficam, ordenadas pela posição no
  texto; cada uma vai prefixada por "[p. N]" na célula. Seções cujo **título** é de limitações ou trabalhos futuros ("Limitations",
  "Future work", "Limitações"...) contam como método ``secao`` (as primeiras frases da seção, até ``max_frases``).
Refinamento de Limitações (12/10/2026; antes: 1 de 5 corretas na conferência manual): os padrões exigem **cue + semântica de limitação** ("limitations of
this study", "this study has several limitations", "a limitation is", "must be acknowledged", "interpreted with caution", "limitação deste estudo",
"este estudo possui limitações"...); a palavra solta "limitation" saiu. Padrões **fracos** (força < 2,8: "we acknowledge", "is limited to/by", "caveat",
"cannot be generalized", "may not capture") só valem em seções de discussão/conclusão ou de título de limitações; frases com referência cruzada
("see Section 7") e itens de checklist/tabela/lista ficam de fora, e páginas de **checklist de conferência** (>= 2 frases-padrão, como "Guidelines:
The authors are encouraged...") são ignoradas por inteiro, inclusive na rota por título de seção.
Frases são citadas **literalmente** do documento; nunca reescritas.

Rastreabilidade: uma linha por (documento, parte, trecho): página, seção de origem, regra/padrão usado, método e nota. A mesma
estrutura alimenta a aba "Corpus" e a tela "Planilha do corpus".
"""
import re
from pathlib import Path

from app.services.analises import sumarizacao, texto_documento

PARTES = (
    ("resumo", "Resumo", "secao", "resumo"),
    ("introducao", "Introdução", "secao", "introducao"),
    ("objetivo", "Objetivo", "padrao", None),
    ("perguntas", "Perguntas de pesquisa/hipóteses", "padrao", None),
    ("referencial", "Referencial teórico", "secao", "referencial"),
    ("metodo", "Método", "secao", "metodos"),
    ("dados", "Dados/amostra/contexto", "padrao", None),
    ("resultados", "Resultados", "secao", "resultados"),
    ("discussao", "Discussão", "secao", "discussao"),
    ("conclusao", "Conclusão", "secao", "conclusao"),
    ("limitacoes", "Limitações", "padrao", None),
    ("futuros", "Trabalhos futuros", "padrao", None),
    ("contribuicoes", "Contribuições/implicações", "padrao", None),
)
ROTULO = {k: r for k, r, _m, _t in PARTES}
CHAVES = tuple(k for k, *_ in PARTES)
NAO_ENCONTRADO = "não encontrado"
PADRAO_PARAMETROS = {"max_caracteres": 1500, "max_frases": 3, "nota_minima": 2.0}

_I = re.IGNORECASE
_SUJ_EN = r"(?:this|the present|the current|our)\s+(?:\w+\s+)?(?:paper|study|article|research|work|report|survey|review|thesis|investigation|analysis|manuscript|chapter|essay|project)"
_SUJ_PT = r"(?:este|esta|o presente|a presente|nosso|nossa|o|a)\s+(?:\w+\s+)?(?:artigo|estudo|trabalho|pesquisa|texto|relat[óo]rio|investiga[çc][ãa]o|revis[ãa]o|an[áa]lise)"
_SUJ_ES = r"(?:este|esta|el presente|la presente|nuestro|nuestra|el|la)\s+(?:\w+\s+)?(?:art[ií]culo|estudio|trabajo|investigaci[óo]n|documento|informe|revisi[óo]n|an[áa]lisis)"

# parte -> [(nome da regra, regex, força)]
PADROES: dict[str, list[tuple[str, re.Pattern, float]]] = {
    "objetivo": [
        ("this paper aims/seeks/investigates...", re.compile(_SUJ_EN + r"\b[^.;]{0,40}?\b(?:aims?|seeks?|investigates?|examines?|explores?|proposes?|analy[sz]es?|studies|evaluates?|assesses?|sets out|intends?|attempts?|asks|tests?|documents?|estimates?|measures?)\b", _I), 3.0),
        ("this paper presents/introduces...", re.compile(_SUJ_EN + r"\b[^.;]{0,30}?\b(?:presents?|introduces?|develops?|reviews?|surveys?|addresses|focus(?:es)? on|offers?|provides?|reports?)\b", _I), 2.0),
        ("the aim/purpose/objective of this", re.compile(r"\b(?:the\s+)?(?:main\s+|primary\s+|overall\s+|general\s+|central\s+)?(?:aim|purpose|objective|goal)s?\s+of\s+(?:this|the present|our|the current|the)\b", _I), 3.0),
        ("our goal/aim is", re.compile(r"\b(?:our|the\s+(?:main|primary|overall|central|general))\s+(?:goal|aim|objective|purpose)\s+(?:is|was)\b", _I), 3.0),
        ("in this paper, we", re.compile(r"\bin\s+this\s+(?:paper|study|article|work|research|report)\s*,?\s+we\b", _I), 2.5),
        ("we aim/seek/investigate/examine...", re.compile(r"\bwe\s+(?:aim|seek|investigate|examine|propose|study|explore|analy[sz]e|evaluate|assess|ask|test|document|estimate)\b", _I), 2.0),
        ("to investigate/examine how...", re.compile(r"\bto\s+(?:investigate|examine|explore|understand|assess|evaluate|analy[sz]e|test)\s+(?:how|whether|the|what|why|if)\b", _I), 1.5),
        ("este artigo/estudo tem como objetivo/busca...", re.compile(_SUJ_PT + r"\b[^.;]{0,40}?\b(?:tem como objetivo|objetiva|busca|visa|analisa|investiga|prop[õo]e|apresenta|examina|explora|avalia|discute|procura|pretende|teve como objetivo)\b", _I), 3.0),
        ("o objetivo deste/do presente", re.compile(r"\bo\s+(?:principal\s+|presente\s+)?objetivo\s+(?:deste|do presente|da presente|desta|principal|geral|central)\b|\bobjetivo\s+(?:geral|principal|central)\b", _I), 3.0),
        ("objetivo", re.compile(r"\bobjetivo\b", _I), 2.0),
        ("este artículo/estudio busca...", re.compile(_SUJ_ES + r"\b[^.;]{0,40}?\b(?:tiene como objetivo|busca|analiza|investiga|propone|presenta|examina|explora|eval[úu]a|pretende|se propone|tuvo como objetivo)\b", _I), 3.0),
        ("el objetivo de este/del presente", re.compile(r"\bel\s+(?:principal\s+|presente\s+)?objetivo\s+(?:de este|del presente|de la presente|principal|general|central)\b|\bobjetivo\s+(?:general|principal)\b", _I), 3.0),
    ],
    "perguntas": [
        ("RQ1", re.compile(r"\bRQ\s?\d\b|\bRQ[1-9]\b"), 3.0),
        ("research question", re.compile(r"\bresearch\s+questions?\b", _I), 2.5),
        ("we hypothesize", re.compile(r"\bwe\s+hypothesi[sz]e\b", _I), 3.0),
        ("H1:", re.compile(r"(?<![\w-])H\d[a-z]?\s*[:.)]"), 3.0),
        ("hypothesis N", re.compile(r"\bhypothes[ie]s\s*(?:\d|\(|[ivx]+\b)", _I), 2.5),
        ("hypothes(i|e)s", re.compile(r"\bhypothes[ie]s\b", _I), 2.0),
        ("questão/pergunta de pesquisa", re.compile(r"\b(?:quest[ãa]o|quest[õo]es|pergunta|perguntas)\s+(?:de\s+)?(?:pesquisa|investiga[çc][ãa]o)\b|\bproblema de pesquisa\b", _I), 2.5),
        ("hipótese", re.compile(r"\bhip[óo]teses?\b", _I), 2.5),
        ("pregunta de investigación", re.compile(r"\bpreguntas?\s+de\s+investigaci[óo]n\b|\bhip[óo]tesis\b", _I), 2.5),
        ("pergunta direta", re.compile(r"\?\s*$"), 2.0),
    ],
    "dados": [
        ("our sample", re.compile(r"\b(?:our|the|final|total|analytic)\s+(?:\w+\s+)?sample\b", _I), 2.5),
        ("the sample consists of", re.compile(r"\bthe\s+(?:\w+\s+)?sample\s+(?:consist|comprise|include|contain|was|were|is|are)", _I), 3.0),
        ("data were collected", re.compile(r"\bdata\s+(?:were|was|are|is|come|comes)\s+(?:\w+\s+)?(?:collected|gathered|obtained|drawn|sourced|extracted|retrieved|compiled|scraped|derived|taken)\b", _I), 3.0),
        ("we surveyed/interviewed/collected", re.compile(r"\bwe\s+(?:surveyed|interviewed|collected|recruited|sampled|obtained|gathered|scraped|assembled|compiled|use|used|draw on|analy[sz]ed)\s+(?:\w+\s+){0,3}?(?:data|dataset|sample|respondents|participants|firms|companies|startups|interviews|documents|articles|papers|studies|observations|users|entrepreneurs)\b", _I), 3.0),
        ("dataset of/comprising", re.compile(r"\b(?:data\s?set|corpus|database)\s+(?:of|comprising|consisting|containing|that|which|includes?|covers?)\b|\bpanel\s+(?:of|comprising)\s+\d", _I), 2.5),
        ("participants were recruited", re.compile(r"\b(?:participants|respondents|firms|companies|startups|observations|entrepreneurs|interviewees|documents|articles|papers|studies|users|subjects)\s+(?:\w+\s+){0,2}?(?:were|was)\s+(?:\w+\s+){0,2}?(?:recruited|selected|surveyed|interviewed|sampled|included|drawn|randomly assigned|assigned)\b", _I), 3.0),
        ("N = ", re.compile(r"\b[Nn]\s*=\s*\d"), 2.0),
        ("using data on/from", re.compile(r"\b(?:using|use|uses|based on|draw(?:s|ing)? on)\s+(?:\w+\s+)?data\s+(?:on|from|of|for)\b", _I), 2.5),
        ("N respondents/firms/...", re.compile(r"\b\d[\d,.]*\s+(?:respondents|participants|firms|companies|startups|observations|interviews|entrepreneurs|articles|studies|documents|users|launches|SMEs|businesses|cities|countries|workers|employees)\b", _I), 2.0),
        ("a amostra / dados coletados", re.compile(r"\b(?:a|nossa|amostra)\s+amostra\b|\bamostra\s+(?:foi|foram|[ée]|compreende|consiste)\b|\bos\s+dados\s+(?:foram|s[ãa]o)\s+(?:coletados|obtidos|extra[ií]dos|levantados|gerados)\b", _I), 3.0),
        ("entrevistamos/aplicamos questionário", re.compile(r"\b(?:entrevistamos|pesquisamos|aplicamos\s+(?:um\s+)?question[áa]rio|coletamos|analisamos\s+dados|foram\s+entrevistad[oa]s)\b", _I), 3.0),
        ("la muestra / datos recolectados", re.compile(r"\bla\s+muestra\b|\blos\s+datos\s+(?:fueron|son)\s+(?:recolectados|recopilados|obtenidos|extra[ií]dos)\b|\bencuestamos\b|\bentrevistamos\b", _I), 3.0),
    ],
    "limitacoes": [
        # Refinamento (12/10/2026): exige "cue + semântica de limitação". A palavra solta "limitation" (que casava "limitações de recursos",
        # "limitaciones de datos de entrenamiento") e "should be noted"/"single platform"/"caution" soltos saíram. Força >= 2,8 vale em qualquer
        # seção; abaixo disso só em discussão/conclusão ou em seção de título de limitações (ver pontuar_frase).
        ("limitation(s) of this/our study", re.compile(r"\blimitations?\s+(?:of|in|to|with)\s+(?:this|our|the present|the current|the)\s+(?:\w+\s+){0,2}?(?:study|work|paper|research|analysis|approach|design|review|survey|investigation|experiment|evidence|findings|data|sample|model|method|framework|benchmark)\b", _I), 3.0),
        ("this study has/is subject to limitations", re.compile(_SUJ_EN + r"\b[^.;]{0,40}?\b(?:has|have|had|is subject to|suffers? from|faces|is not without|are subject to)\s+(?:\w+\s+){0,3}?limitations?\b|\bthe\s+(?:experiment|analysis|sample|design|approach|model|framework|benchmark|dataset|data)\s+(?:has|have)\s+(?:\w+\s+){0,3}?limitations?\b", _I), 3.0),
        ("a/one/another/several limitation(s)", re.compile(r"\b(?:a|an|one|another|the\s+(?:first|second|third|main|key|major|primary|principal)|several|some|a\s+few|a\s+number\s+of|important|key|main|major|inherent|notable|certain|potential|methodological|obvious|clear|significant)\s+(?:\([\w\s]+\)\s+)?(?:\w+\s+){0,2}?limitations?\b(?!\s+(?:of|on|in)\s+(?:resources?|data|time|capital|funding|access|budget|training|capacity|skills?|infrastructure|technology|technologies|computing|models?\b))", _I), 3.0),
        ("limitations must/should be acknowledged", re.compile(r"\blimitations?\b[^.;]{0,50}\b(?:must|should|need to|ought to|have to)\s+(?:be\s+)?(?:\w+\s+)?(?:acknowledged|noted|mentioned|considered|recognized|recognised|addressed|discussed|kept in mind)\b|\b(?:acknowledge|recognize|recognise|note|admit)\s+(?:that\s+)?(?:\w+\s+){0,3}?limitations?\b", _I), 3.0),
        ("interpreted with caution", re.compile(r"\b(?:should|must|need to|ought to|have to)\s+(?:be\s+)?(?:interpreted|treated|taken|viewed|read|considered)\s+(?:\w+\s+){0,2}?(?:with\s+)?(?:caution|care)\b|\b(?:interpret|treat|read)\s+(?:\w+\s+){0,3}?with\s+(?:caution|care)\b|\bwith\s+caution\b(?=[^.]{0,40}\b(?:results?|findings?|estimates?|conclusions?|evidence)\b)", _I), 2.8),
        ("we acknowledge (that)", re.compile(r"\bwe\s+(?:acknowledge|recogni[sz]e|admit)\s+(?:that\s+)?(?:this|our|the present|the current|the study|several|some|a few|important|certain|key)\b", _I), 2.2),
        ("is limited to/by", re.compile(_SUJ_EN + r"\b[^.;]{0,30}?\bis\s+limited\s+(?:to|by|in)\b|\b(?:our|the)\s+(?:\w+\s+){0,2}?(?:sample|data|dataset|evidence|analysis|setting|scope|design|experiment|sample size|findings|results)\s+(?:is|are)\s+(?:\w+\s+)?limited\s+(?:to|by|in)\b", _I), 2.2),
        ("caveat(s)", re.compile(r"\b(?:an?|some|several|important|key|one|another|these|the)\s+(?:\w+\s+)?caveats?\b|\bcaveats?\s+(?:to|of|include|apply|are|is)\b", _I), 2.2),
        ("cannot be generalized", re.compile(r"\b(?:cannot|can\s?not|may not|might not|do(?:es)? not|not)\s+(?:\w+\s+)?(?:be\s+)?(?:necessarily\s+)?(?:generali[sz]ed?|extrapolated|generali[sz]able)\b|\bgenerali[sz]ability\b|\bexternal validity\b", _I), 2.2),
        ("may not capture/represent", re.compile(r"\bmay\s+not\s+(?:fully\s+)?(?:capture|reflect|represent)\b|\bbeyond\s+the\s+scope\s+of\s+(?:this|our|the present|the current)\b", _I), 2.0),
        ("a limitação deste estudo", re.compile(r"\blimita[çc](?:ão|ões)\s+(?:d[eo]s?|da|das|desta|deste|do presente)\s+(?:\w+\s+)?(?:este|esta|presente|nosso|nossa)?\s*(?:estudo|trabalho|pesquisa|artigo|an[áa]lise|investiga[çc][ãa]o|amostra|abordagem|revis[ãa]o|design|desenho)\b|\b(?:este|esta|nosso|nossa|o presente|a presente)\s+(?:\w+\s+)?(?:estudo|trabalho|pesquisa|artigo|an[áa]lise|investiga[çc][ãa]o)\s+(?:possui|apresenta|tem|teve|t[êe]m|enfrenta)\s+(?:\w+\s+){0,3}?limita[çc](?:ão|ões)\b|\b(?:uma|outra|principal|importante|algumas|diversas|v[áa]rias|as seguintes)\s+(?:\w+\s+)?limita[çc](?:ão|ões)\b|\bcomo\s+limita[çc](?:ão|ões)\b", _I), 3.0),
        ("deve ser interpretado com cautela", re.compile(r"\b(?:devem?|precisam?)\s+ser\s+(?:interpretad|lid|tomad|vist|considerad)[oa]s?\s+(?:\w+\s+)?com\s+(?:cautela|cuidado|ressalvas?)\b|\bn[ãa]o\s+(?:pode|podem)\s+ser\s+generalizad[oa]s?\b|\breconhecemos\s+(?:que|algumas|as)\b", _I), 2.8),
        ("la limitación de este estudio", re.compile(r"\blimitaci[óo]n(?:es)?\s+(?:de|del)\s+(?:este|esta|presente|nuestro|nuestra|el presente|la presente)?\s*(?:estudio|trabajo|investigaci[óo]n|art[ií]culo|an[áa]lisis|muestra|enfoque)\b|\b(?:este|esta|nuestro|nuestra|el presente)\s+(?:\w+\s+)?(?:estudio|trabajo|investigaci[óo]n|art[ií]culo)\s+(?:tiene|presenta|posee|tuvo)\s+(?:\w+\s+){0,3}?limitaci[óo]n(?:es)?\b|\b(?:una|otra|principal|importante|algunas|varias)\s+(?:\w+\s+)?limitaci[óo]n(?:es)?\b|\bno\s+(?:puede|pueden)\s+generalizarse\b", _I), 3.0),
    ],
    "futuros": [
        ("future research/work", re.compile(r"\bfuture\s+(?:\w+\s+)?(?:research|work|studies|investigations?|directions?|scholarship|avenues|extensions?)\b|\bfurther\s+(?:research|work|studies|investigation|empirical|evidence)\b", _I), 3.0),
        ("avenues for", re.compile(r"\bavenues?\s+for\b|\b(?:research|work|studies)\s+(?:is|are)\s+(?:needed|warranted|required)\b|\bleave\s+(?:this|these|it)\s+for\s+future\b", _I), 2.8),
        ("future ... should/could", re.compile(r"\bfuture\b[^.]{0,40}\b(?:should|could|may|might|can|will|needs?\s+to|would)\b|\b(?:scholars|researchers)\s+(?:\w+\s+){0,2}?(?:could|should|might|may)\s+(?:explore|examine|investigate|extend|test|address)\b", _I), 2.2),
        ("pesquisas/trabalhos futuros", re.compile(r"\b(?:pesquisas?|trabalhos?|estudos?|investiga[çc](?:ão|ões))\s+futur[oa]s?\b|\bfuturas\s+(?:pesquisas|investiga[çc][õo]es|linhas)\b|\bsugere-se\s+(?:que\s+)?(?:estudos|pesquisas|trabalhos)\b|\bnovas\s+(?:pesquisas|investiga[çc][õo]es|estudos)\b", _I), 3.0),
        ("investigaciones/trabajos futuros", re.compile(r"\b(?:investigaciones|trabajos|estudios|l[ií]neas\s+de\s+investigaci[óo]n)\s+futur[oa]s?\b|\bfuturas\s+(?:l[ií]neas|investigaciones)\b|\bfuturos?\s+(?:trabajos|estudios)\b", _I), 3.0),
    ],
    "contribuicoes": [
        ("we contribute", re.compile(r"\bwe\s+(?:contribute|advance|extend|add to|complement|offer|provide)\b", _I), 3.0),
        ("this paper makes/offers/contributes", re.compile(_SUJ_EN + r"\b[^.;]{0,20}?\b(?:makes?|offers?|contributes?|adds?|extends?|advances?|sheds?|complements?|provides?)\b", _I), 3.0),
        ("contribution(s)", re.compile(r"\bcontributions?\b", _I), 2.5),
        ("implications for/of", re.compile(r"\bimplications?\s+(?:for|of)\b|\b(?:theoretical|practical|managerial|policy|empirical|methodological)\s+(?:implications?|contributions?|insights?)\b", _I), 2.8),
        ("sheds light / extends the literature", re.compile(r"\bshed(?:s|ding)?\s+light\b|\bextends?\s+(?:the\s+)?(?:literature|research|prior work|existing)\b|\bcontribut\w+\s+to\s+(?:the\s+)?(?:literature|debate|growing)\b", _I), 2.5),
        ("contribui / implicações", re.compile(r"\bcontribui(?:[çc](?:ão|ões)|\s+para)\b|\bcontribuições\b|\bimplica[çc](?:ão|ões)\s+(?:para|pr[áa]tica|te[óo]rica|gerencia)", _I), 3.0),
        ("aporta / implicaciones", re.compile(r"\baportes?\b|\baporta\b|\bcontribuci[óo]n(?:es)?\b|\bimplicaciones\b", _I), 3.0),
    ],
}

# parte -> {tipo de seção: bônus} e direção da posição (+1 favorece o começo, -1 favorece o fim)
PREFERENCIA = {
    "objetivo": ({"resumo": 1.5, "introducao": 1.0, "resultados": -1.0, "discussao": -0.5, "*": -0.7}, 1),
    "perguntas": ({"introducao": 1.0, "referencial": 1.0, "resumo": 0.5, "resultados": -0.5}, 1),
    "dados": ({"metodos": 1.5, "resumo": 0.5, "introducao": 0.3}, 1),
    "limitacoes": ({"discussao": 1.5, "conclusao": 1.5, "resultados": 0.5, "resumo": -1.0, "*": -0.3}, -1),
    "futuros": ({"discussao": 1.5, "conclusao": 1.5}, -1),
    "contribuicoes": ({"conclusao": 1.5, "discussao": 1.0, "introducao": 0.8, "resumo": 0.5}, 1),
}
TITULO_SECAO = {
    "limitacoes": re.compile(r"\blimitations?\b|\blimita[çc](?:ão|ões)\b|\blimitaci[óo]n", _I),
    "futuros": re.compile(r"\bfuture\s+(?:work|research|directions|studies)\b|\bfurther research\b|\btrabalhos?\s+futuros?\b|\bpesquisas?\s+futuras?\b|\btrabajos?\s+futuros?\b|\bl[ií]neas\s+futuras\b", _I),
}
SECOES_LIMITACOES = ("discussao", "conclusao")  # onde os padrões "fracos" de limitação (força < 2,8) são aceitos
FORCA_FORTE_LIMITACOES = 2.8
# Referência cruzada ("... limitations are discussed in Section 7"): aponta, não declara a limitação.
_PONTEIRO = re.compile(r"\b(?:see|in|at|cf\.?|discussed in|described in|presented in|detailed in)\s+(?:section|sec\.|appendix|§)\s*[\dA-Z]|\(§\s*\d|\bse[çc][ãa]o\s+\d", _I)
MAX_PALAVRAS_FRASE = 90
MIN_PALAVRAS_FRASE = 6


_CHECKLIST = re.compile(r"^\s*(?:(?:question|answer|justification|guidelines?|pergunta|resposta)\s*:|the answer\b|the authors (?:should|are encouraged)|(?:the )?authors should|the paper should)", re.IGNORECASE)
# Texto-padrão de checklists de conferência (NeurIPS/ICML/ACL: "Limitations: Question: ... Guidelines: ..."): quem tem >= 2 destas frases numa
# página marca a página inteira como checklist; seus itens e orientações nunca são trechos do artigo.
_CHECKLIST_FORTE = re.compile(
    r"\b(?:the answer (?:na|yes|no)\b|answer:\s*\[?(?:yes|no|na)|justification:|guidelines?:|the authors are encouraged|authors should (?:reflect|discuss|describe|state|provide|clearly|include|make sure|be honest)|"
    r"reviewers will|neurips code of ethics|if (?:your|the) (?:paper|work) (?:does not|doesn't)|empirical results often depend on implicit assumptions|"
    r"facial recognition algorithm may perform poorly|speech-to-text system ?might not|it is (?:fine|ok|acceptable) to|checklist|do the main claims made in the abstract|"
    r"does the paper discuss the limitations)\b", re.IGNORECASE)
# item de tabela/lista (não é frase corrida do artigo)
_ITEM_LISTA = re.compile(r"^\s*(?:[-•*▪·]\s|\(?[ivx]+\)\s|\(?[a-z]\)\s|\d+[.)]\s)|\s\|\s")


def _elegivel(f: dict) -> bool:
    return (not _CHECKLIST.match(f["texto"]) and not _CHECKLIST_FORTE.search(f["texto"]) and not _ITEM_LISTA.search(f["texto"])
            and sumarizacao.elegivel(f["texto"], MIN_PALAVRAS_FRASE, MAX_PALAVRAS_FRASE))


def paginas_de_checklist(frases: list[dict]) -> set:
    """Páginas com >= 2 frases de texto-padrão de checklist de conferência (todas as frases delas são ignoradas nos padrões)."""
    cont: dict = {}
    for f in frases:
        if f.get("pagina") is not None and _CHECKLIST_FORTE.search(f["texto"]):
            cont[f["pagina"]] = cont.get(f["pagina"], 0) + 1
    return {p for p, n in cont.items() if n >= 2}


def _paginas(frases: list[dict]) -> str:
    ps = [f["pagina"] for f in frases if f.get("pagina") is not None]
    if not ps:
        return ""
    return f"p. {min(ps)}" if min(ps) == max(ps) else f"pp. {min(ps)}-{max(ps)}"


def preencher_secao(frases: list[dict], tipo: str, max_caracteres: int) -> dict | None:
    """Parte por seção: frases da seção (ordem do texto) até ``max_caracteres`` no fim de uma frase."""
    sel = [f for f in frases if f["secao"] == tipo]
    if not sel:
        return None
    usadas, total = [], 0
    for f in sel:
        extra = len(f["texto"]) + (1 if usadas else 0)
        if usadas and total + extra > max_caracteres:
            break
        usadas.append(f)
        total += extra
    cortou = len(usadas) < len(sel)
    texto = " ".join(f["texto"] for f in usadas) + (" (…)" if cortou else "")
    titulo = usadas[0].get("titulo_secao") or tipo
    return {"trechos": [{"texto": texto, "pagina": usadas[0]["pagina"], "paginas": _paginas(usadas), "secao": tipo, "titulo_secao": titulo,
                         "regra": f"seção detectada: {titulo}", "metodo": "secao", "nota": None, "frase_i": usadas[0]["i"],
                         "truncado": cortou, "n_frases": len(usadas)}],
            "metodo": "secao"}


def pontuar_frase(parte: str, f: dict, pos_rel: float) -> tuple[float, list[str]]:
    padroes = PADROES[parte]
    achados = [(nome, forca) for nome, rx, forca in padroes if rx.search(f["texto"])]
    if not achados:
        return 0.0, []
    achados.sort(key=lambda x: -x[1])
    base = achados[0][1] + 0.5 * min(2, len(achados) - 1)
    if base < 2.0:  # sinal fraco sozinho não basta (os bônus de seção e posição só ordenam)
        return 0.0, []
    if parte == "perguntas" and achados[0][0] == "pergunta direta" and len(achados) == 1 and f["secao"] not in ("introducao", "resumo"):
        return 0.0, []
    if parte == "limitacoes":
        if _PONTEIRO.search(f["texto"]):
            return 0.0, []  # "ver Seção 7": aponta para a limitação, não a declara
        no_titulo = bool(f.get("titulo_secao")) and bool(TITULO_SECAO["limitacoes"].search(f["titulo_secao"]))
        if achados[0][1] < FORCA_FORTE_LIMITACOES and f["secao"] not in SECOES_LIMITACOES and not no_titulo:
            return 0.0, []  # cue fraco fora de discussão/conclusão/seção de limitações: não é limitação do estudo
    bonus, direcao = PREFERENCIA[parte]
    nota = base + bonus.get(f["secao"], bonus.get("*", 0.0))
    nota += 0.5 * ((1 - pos_rel) if direcao > 0 else pos_rel)
    return nota, [n for n, _ in achados]


def preencher_padrao(frases: list[dict], parte: str, max_frases: int, nota_minima: float, n_total: int | None = None,
                     paginas_checklist: set | frozenset = frozenset()) -> dict | None:
    n = max(1, n_total or (max((f["i"] for f in frases), default=0) + 1))
    # seções cujo título já é "Limitações"/"Trabalhos futuros": as primeiras frases da seção
    rx_titulo = TITULO_SECAO.get(parte)
    if rx_titulo:
        da_secao = [f for f in frases if f.get("titulo_secao") and rx_titulo.search(f["titulo_secao"]) and f.get("pagina") not in paginas_checklist]
        titulo_curto = bool(da_secao) and len(re.sub(r"^[\d.\s]+", "", da_secao[0]["titulo_secao"]).split()) <= 4
        if da_secao and titulo_curto:
            sel = da_secao[:max_frases]
            return {"trechos": [{"texto": f["texto"], "pagina": f["pagina"], "paginas": f"p. {f['pagina']}" if f["pagina"] else "", "secao": f["secao"],
                                 "titulo_secao": f.get("titulo_secao"), "regra": f"título da seção: {f.get('titulo_secao')}", "metodo": "secao",
                                 "nota": None, "frase_i": f["i"]} for f in sel], "metodo": "secao"}
    candidatas = []
    for f in frases:
        if f.get("pagina") in paginas_checklist:
            continue
        nota, regras = pontuar_frase(parte, f, f["i"] / n)
        if regras and nota >= nota_minima:
            candidatas.append((nota, f, regras))
    if not candidatas:
        return None
    candidatas.sort(key=lambda x: (-x[0], x[1]["i"]))
    top = sorted(candidatas[:max_frases], key=lambda x: x[1]["i"])
    return {"trechos": [{"texto": f["texto"], "pagina": f["pagina"], "paginas": f"p. {f['pagina']}" if f["pagina"] else "", "secao": f["secao"],
                         "titulo_secao": f.get("titulo_secao"), "regra": "; ".join(regras[:3]), "metodo": "padrao", "nota": round(nota, 2),
                         "frase_i": f["i"]} for nota, f, regras in top], "metodo": "padrao"}


def frases_elegiveis(pasta: Path, documento_id: int, excluir_ruido: bool = True) -> list[dict] | None:
    frases = texto_documento.frases_do_documento(pasta, documento_id, excluir_ruido=excluir_ruido)
    if frases is None:
        return None
    return [f for f in frases if _elegivel(f)]


def analisar_documento(pasta: Path, documento_id: int, parametros: dict | None = None, excluir_ruido: bool = True) -> dict | None:
    """``{parte: {"trechos": [...], "metodo": "secao"|"padrao"} | None}`` (None = não encontrado). ``None`` se o documento não tem texto limpo."""
    p = {**PADRAO_PARAMETROS, **(parametros or {})}
    todas = texto_documento.frases_do_documento(pasta, documento_id, excluir_ruido=excluir_ruido)
    if todas is None:
        return None
    # seções: usa todas as frases do corpo (a seção "resumo" tem frases curtas legítimas); padrões: só as elegíveis
    checklist = paginas_de_checklist(todas)
    elegiveis = [f for f in todas if _elegivel(f)]
    saida: dict = {}
    for chave, _rotulo, modo, tipo in PARTES:
        if modo == "secao":
            saida[chave] = preencher_secao([f for f in todas if len(f["texto"]) >= 15], tipo, int(p["max_caracteres"]))
        else:
            saida[chave] = preencher_padrao(elegiveis, chave, int(p["max_frases"]), float(p["nota_minima"]), len(todas), checklist)
    return saida


def texto_da_celula(parte: dict | None) -> str:
    """Texto da célula: trechos com "[p. N]" na frente (separados por linha em branco) ou "não encontrado"."""
    if not parte or not parte["trechos"]:
        return NAO_ENCONTRADO
    saida = []
    for t in parte["trechos"]:
        pref = f"[{t['paginas']}] " if t.get("paginas") else ""
        saida.append(pref + t["texto"])
    return "\n\n".join(saida)
