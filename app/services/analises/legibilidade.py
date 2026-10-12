"""15.3 - Legibilidade por documento: Flesch (EN), Flesch adaptado ao PT, Flesch-Kincaid, Gunning Fog, Coleman-Liau, SMOG.

Texto e unidades
----------------
Corpo do documento (sem referências, apêndice etc., e sem os segmentos de ruído da 3.4 quando ``limpeza.excluir_ruido``
está ligado), dividido em frases pela regra de ``texto_documento.py``. **Palavra** = sequência de letras (hífen e
apóstrofo internos mantêm a palavra: *state-of-the-art*, *don't*); números e símbolos não contam. **Siglas** (2+ letras
todas maiúsculas: *LLM*, *OECD*) ficam fora das contagens de palavras e sílabas por não terem leitura padronizada (a
quantidade aparece em ``siglas``). Sílabas por ``silabas.py`` (EN: heurística; PT/ES: núcleos vocálicos).

Notação: ASL = palavras por frase, ASW = sílabas por palavra, L = letras por 100 palavras, S = frases por 100 palavras.

Fórmulas
--------
- Flesch Reading Ease, inglês (Flesch, 1948): ``206,835 - 1,015·ASL - 84,6·ASW``.
- Flesch adaptado ao português (Martins et al., 1996): ``248,835 - 1,015·ASL - 84,6·ASW`` (mesmos coeficientes, constante
  42 pontos maior porque o português tem mais sílabas por palavra).
- Flesch-Kincaid Grade Level (Kincaid et al., 1975): ``0,39·ASL + 11,8·ASW - 15,59`` (série escolar dos EUA).
- Gunning Fog (Gunning, 1952): ``0,4·(ASL + 100·palavras complexas/palavras)``; complexa = 3+ sílabas, **exceto** nomes
  próprios (capitalizadas fora do início da frase), compostos com hífen e verbos que chegam a 3 sílabas só por ``-ed``/``-es``
  (as sílabas dessas terminações não contam, como no original).
- Coleman-Liau (1975): ``0,0588·L - 0,296·S - 15,8`` (série escolar dos EUA; usa letras, não sílabas).
- SMOG (McLaughlin, 1969): ``1,0430·√(polissílabos·30/frases) + 3,1291``; polissílabo = 3+ sílabas (sem exceções). O original
  usa 30 frases; com mais ou menos frases o número de polissílabos é **reescalado** para 30 frases e há aviso se N < 30.

Fórmula principal = a do idioma do documento (``qualidade.idioma``): inglês -> Flesch EN; português -> Flesch PT.
Documentos em espanhol ou sem idioma definido não têm fórmula principal (sem fórmula de Flesch validada aqui); os demais
índices são calculados sempre, mas **Fog, Kincaid, Coleman-Liau e SMOG foram calibrados para o inglês**: em português
servem só para comparar documentos entre si.

Faixas de interpretação
-----------------------
- Flesch EN: 90-100 muito fácil; 80-90 fácil; 70-80 razoavelmente fácil; 60-70 padrão; 50-60 razoavelmente difícil;
  30-50 difícil (nível universitário); 0-30 muito difícil (pós-graduação); < 0 extremamente difícil.
- Flesch PT (faixas de Martins et al., 1996, aproximadas: conferir antes de citar): 75-100 fácil (ensino fundamental I);
  50-75 médio (fundamental II); 25-50 difícil (ensino médio/graduação); 0-25 muito difícil (nível superior/técnico);
  < 0 extremamente difícil.
- Índices de série (Kincaid, Coleman-Liau, SMOG, Fog): série escolar aproximada; 13+ = nível universitário, 17+ = pós-graduação.

Cuidado
-------
Artigos acadêmicos em PDF têm tabelas, listas, legendas e citações; isso distorce as frases (muito longas ou muito curtas)
e portanto ASL. ``confiavel`` fica falso e há aviso quando: menos de 30 frases; média de palavras por frase fora de
8-35; mais de 5% das frases com mais de 60 palavras; ou mais de 25% das frases terminam sem pontuação final.
"""
import math
from pathlib import Path

from app.services.analises import dados, silabas, texto_documento

IDIOMAS_PRINCIPAL = {"en": "flesch_en", "pt": "flesch_pt"}
MIN_FRASES = 30
FAIXA_ASL = (8.0, 35.0)
NOMES = {
    "flesch_en": "Flesch Reading Ease (EN)", "flesch_pt": "Flesch adaptado ao PT (Martins et al.)",
    "flesch_kincaid": "Flesch-Kincaid (série)", "gunning_fog": "Gunning Fog (série)",
    "coleman_liau": "Coleman-Liau (série)", "smog": "SMOG (série)",
}
METODOLOGIA = (
    "Palavras = sequências de letras do corpo (sem siglas); sílabas por heurística (EN) ou núcleos vocálicos (PT); "
    "Flesch EN 206,835 - 1,015·ASL - 84,6·ASW; Flesch PT 248,835 - 1,015·ASL - 84,6·ASW (Martins et al., 1996); "
    "Flesch-Kincaid 0,39·ASL + 11,8·ASW - 15,59; Gunning Fog 0,4·(ASL + 100·complexas/palavras); Coleman-Liau "
    "0,0588·L - 0,296·S - 15,8; SMOG 1,043·√(polissílabos·30/frases) + 3,1291. Índices de série foram calibrados para o inglês."
)


# ---------- faixas ----------

def faixa_flesch_en(v: float) -> str:
    for limite, texto in ((90, "muito fácil"), (80, "fácil"), (70, "razoavelmente fácil"), (60, "padrão"),
                          (50, "razoavelmente difícil"), (30, "difícil (nível universitário)"), (0, "muito difícil (pós-graduação)")):
        if v >= limite:
            return texto
    return "extremamente difícil"


def faixa_flesch_pt(v: float) -> str:
    for limite, texto in ((75, "fácil (ensino fundamental I)"), (50, "médio (ensino fundamental II)"),
                          (25, "difícil (ensino médio/graduação)"), (0, "muito difícil (nível superior/técnico)")):
        if v >= limite:
            return texto
    return "extremamente difícil"


def faixa_serie(v: float) -> str:
    if v < 6:
        return "fundamental I"
    if v < 9:
        return "fundamental II"
    if v < 12:
        return "ensino médio"
    if v < 17:
        return "universitário"
    return "pós-graduação"


FAIXAS = {"flesch_en": faixa_flesch_en, "flesch_pt": faixa_flesch_pt, "flesch_kincaid": faixa_serie,
          "gunning_fog": faixa_serie, "coleman_liau": faixa_serie, "smog": faixa_serie}


# ---------- fórmulas (funções puras) ----------

def flesch_en(asl: float, asw: float) -> float:
    return 206.835 - 1.015 * asl - 84.6 * asw


def flesch_pt(asl: float, asw: float) -> float:
    return 248.835 - 1.015 * asl - 84.6 * asw


def flesch_kincaid(asl: float, asw: float) -> float:
    return 0.39 * asl + 11.8 * asw - 15.59


def gunning_fog(asl: float, pct_complexas: float) -> float:
    """``pct_complexas`` em % das palavras."""
    return 0.4 * (asl + pct_complexas)


def coleman_liau(letras: int, palavras: int, frases: int) -> float:
    return 0.0588 * (100.0 * letras / palavras) - 0.296 * (100.0 * frases / palavras) - 15.8


def smog(polissilabos: int, frases: int) -> float:
    return 1.0430 * math.sqrt(polissilabos * 30.0 / frases) + 3.1291


# ---------- contagens ----------

def _eh_sigla(p: str) -> bool:
    letras = [c for c in p if c.isalpha()]
    return len(letras) >= 2 and all(c.isupper() for c in letras)


def silabas_gunning(palavra: str, idioma: str, metodo: str) -> int:
    """Sílabas para o Fog: sem a sílaba de ``-ed``/``-es`` (EN)."""
    n = silabas.contar_silabas(palavra, idioma, metodo)
    p = palavra.lower()
    if idioma == "en" and len(p) > 4 and p.endswith(("ed", "es")) and n > silabas.contar_silabas(p[:-2], idioma, metodo):
        n -= 1
    return n


def contar_frases(frases: list[str], idioma: str, metodo: str = "heuristica") -> dict:
    """Contagens brutas sobre uma lista de frases (textos)."""
    palavras = letras = sil = poli = complexas = siglas = sem_final = longas = 0
    for f in frases:
        ws = texto_documento.palavras_da_frase(f)
        if not f.rstrip().rstrip("\"'”’)]").endswith((".", "?", "!", "…")):
            sem_final += 1
        n_f = 0
        for k, w in enumerate(ws):
            if _eh_sigla(w):
                siglas += 1
                continue
            n_f += 1
            s = silabas.contar_silabas(w, idioma, metodo)
            palavras += 1
            letras += sum(1 for c in w if c.isalpha())
            sil += s
            if s >= 3:
                poli += 1
                nome_proprio = k > 0 and w[:1].isupper()
                if not nome_proprio and "-" not in w and silabas_gunning(w, idioma, metodo) >= 3:
                    complexas += 1
        if n_f > 60:
            longas += 1
    return {"frases": len(frases), "palavras": palavras, "letras": letras, "silabas": sil, "polissilabos": poli,
            "palavras_complexas": complexas, "siglas": siglas, "frases_sem_pontuacao_final": sem_final, "frases_longas": longas}


def avaliar_frases(c: dict, idioma: str | None) -> tuple[bool, list[str]]:
    """``(confiavel, avisos)`` para a divisão em frases (regras no docstring do módulo)."""
    avisos: list[str] = []
    n, w = c["frases"], c["palavras"]
    if n < MIN_FRASES:
        avisos.append(f"apenas {n} frases (< {MIN_FRASES}): SMOG e Fog instáveis")
    if n:
        asl = w / n
        if not FAIXA_ASL[0] <= asl <= FAIXA_ASL[1]:
            avisos.append(f"média de {asl:.1f} palavras por frase fora de {FAIXA_ASL[0]:.0f}-{FAIXA_ASL[1]:.0f}: "
                          "a divisão em frases provavelmente falhou (tabelas, listas ou legendas)")
        if c["frases_longas"] / n > 0.05:
            avisos.append(f"{100 * c['frases_longas'] / n:.0f}% das frases têm mais de 60 palavras (tabelas ou listas?)")
        if c["frases_sem_pontuacao_final"] / n > 0.25:
            avisos.append(f"{100 * c['frases_sem_pontuacao_final'] / n:.0f}% das frases terminam sem pontuação final")
    graves = list(avisos)  # problemas da divisão em frases tornam o resultado não confiável; o idioma é só aviso
    if idioma not in IDIOMAS_PRINCIPAL:
        avisos.append("idioma sem fórmula de Flesch validada aqui; índices de série são só comparativos")
    return not graves, avisos


def indices(c: dict, idioma: str | None) -> dict:
    """Todos os índices a partir das contagens (``None`` se não há palavras/frases)."""
    n, w = c["frases"], c["palavras"]
    if n == 0 or w == 0:
        return {}
    asl, asw = w / n, c["silabas"] / w
    valores = {
        "flesch_en": flesch_en(asl, asw), "flesch_pt": flesch_pt(asl, asw), "flesch_kincaid": flesch_kincaid(asl, asw),
        "gunning_fog": gunning_fog(asl, 100.0 * c["palavras_complexas"] / w),
        "coleman_liau": coleman_liau(c["letras"], w, n), "smog": smog(c["polissilabos"], n),
    }
    return {k: {"nome": NOMES[k], "valor": round(v, 2), "faixa": FAIXAS[k](v)} for k, v in valores.items()}


def analisar_texto(frases: list[str], idioma: str | None, metodo_silabas: str = "heuristica") -> dict:
    """Resultado completo para uma lista de frases (usado pelos testes e pelo documento)."""
    lingua = idioma if idioma in ("en", "pt", "es") else "en"
    c = contar_frases(frases, lingua, metodo_silabas)
    ind = indices(c, idioma)
    confiavel, avisos = avaliar_frases(c, idioma)
    principal = IDIOMAS_PRINCIPAL.get(idioma or "")
    n, w = c["frases"], c["palavras"]
    return {
        "idioma": idioma, "silabas_metodo": "pyphen" if (metodo_silabas == "pyphen" and lingua == "en") else "regras",
        **c,
        "palavras_por_frase": round(w / n, 2) if n else None,
        "silabas_por_palavra": round(c["silabas"] / w, 3) if w else None,
        "indices": ind, "formula_principal": principal,
        "principal": ({"id": principal, **ind[principal]} if principal and principal in ind else None),
        "confiavel": bool(confiavel and ind), "avisos": avisos,
    }


def calcular_documento(pasta_projeto: Path, documento_id: int, excluir_ruido: bool = True,
                       metodo_silabas: str = "heuristica") -> dict | None:
    """Legibilidade de um documento (``None`` sem texto limpo)."""
    frases = texto_documento.frases_do_documento(pasta_projeto, documento_id, excluir_ruido)
    if frases is None:
        return None
    tk = dados.carregar_tokens(pasta_projeto, documento_id)
    idioma = (tk or {}).get("idioma")
    return analisar_texto([f["texto"] for f in frases], idioma, metodo_silabas)
