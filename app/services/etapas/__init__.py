"""Etapas do pipeline. Importar um módulo aqui o registra no orquestrador.

Ordem: varredura (10), metadados_csv (11), conversao (20), qualidade (25),
qualidade_duplicados (26), limpeza (30), linguistica (40), spacy (41, opcional), segmentos (42), ruido (43), vocabulario (45), termos_compostos (46), duplicatas_proximas (47), descritivo (50), comparativo (60), similaridade (62), dicionario (63), especificidades (64), afc (65), reinert (66), similitude (67), topicos (68), documento_extra (69), estilometria (69), comentarios (70).
"""
from app.services.etapas import varredura  # noqa: F401
from app.services.etapas import metadados_csv  # noqa: F401
from app.services.etapas import conversao  # noqa: F401
from app.services.etapas import qualidade  # noqa: F401
from app.services.etapas import limpeza  # noqa: F401
from app.services.etapas import linguistica  # noqa: F401
from app.services.etapas import spacy_pos  # noqa: F401  (opcional: POS/NER com spaCy, etapa 41)
from app.services.etapas import segmentos  # noqa: F401
from app.services.etapas import ruido  # noqa: F401
from app.services.etapas import vocabulario  # noqa: F401
from app.services.etapas import termos_compostos  # noqa: F401
from app.services.etapas import duplicatas  # noqa: F401
from app.services.etapas import descritivo  # noqa: F401
from app.services.etapas import comparativo  # noqa: F401
from app.services.etapas import similaridade  # noqa: F401
from app.services.etapas import dicionario  # noqa: F401
from app.services.etapas import especificidades  # noqa: F401
from app.services.etapas import tematico  # noqa: F401
from app.services.etapas import topicos  # noqa: F401
from app.services.etapas import documento_extra  # noqa: F401
from app.services.etapas import comentarios  # noqa: F401
from app.services.etapas import estilometria  # noqa: F401
