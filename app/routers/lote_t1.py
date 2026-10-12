"""Rotas do lote T1 (15.8 keyness contra referência, 15.10 sentimento, 4.5 spaCy, 9.5 exportação para a planilha da MLR).

Um único ponto de entrada para o ``main.py`` incluir (cada módulo tem o próprio ``router``)."""
from app.routers import coleta_mlr, keyness_referencia, sentimento, spacy_pos

ROUTERS = [keyness_referencia.router, sentimento.router_config, sentimento.router, spacy_pos.router_config, spacy_pos.router,
           coleta_mlr.router]
