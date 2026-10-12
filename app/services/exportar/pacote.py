"""Pacote de exportação: laudo.html + todos os CSV + parametros.json (+ LEIAME.txt), gravado em saidas/ e zipado."""
import io
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import VERSAO
from app.services import parametros as svc_parametros
from app.services.exportar import laudo_html, planilhas

LEIAME = f"""Raio-X {VERSAO} - pacote de exportação
=========================================

laudo.html        laudo autossuficiente (abra com dois cliques; funciona offline). Só comentários aceitos/editados.
laudo.docx        o mesmo laudo em Word (títulos e tabelas editáveis; evidências "(rótulo, p. N)").
documentos.csv    metadados, qualidade e estatísticas de cada documento (inclui os fora das análises)
frequencias.csv   lemas do corpus (sem palavras vazias): frequência, por 10 mil palavras, nº de documentos
keyness.csv       palavras-chave de cada grupo contra os demais (todas as linhas significativas)
colocacoes.csv    colocados dos termos citados em comentários aceitos (ou dos 10 termos mais frequentes)
comentarios.csv   todos os comentários, com status, texto, texto original, regra, métricas, revisor, nota e datas
evidencias.csv    trechos de evidência de cada comentário: documento, página, trecho
parametros.json   parâmetros do projeto (reproduz o resultado com a mesma pasta de artigos)

Formato dos CSV: UTF-8 com BOM (o Excel abre com acentos corretos), separador ";" (ponto e vírgula), decimais com
PONTO (0.05), sem separador de milhar, campos com ";", aspas ou quebras de linha entre aspas, datas em ISO 8601 (UTC).
No Excel pt-BR, para ler os decimais como número: Dados > De Texto/CSV e escolha "Ponto" como separador decimal.
"""


def montar_pacote(db: Session, pasta: Path) -> bytes:
    """Gera laudo e planilhas em ``saidas/``, grava ``saidas/pacote.zip`` e devolve os bytes do zip."""
    saidas = pasta / "saidas"
    saidas.mkdir(parents=True, exist_ok=True)
    laudo_html.gerar_laudo(db, pasta)
    arquivos: dict[str, bytes] = {"laudo.html": (saidas / "laudo.html").read_bytes(),
                                  "laudo.docx": (saidas / "laudo.docx").read_bytes()}
    for nome in planilhas.NOMES:
        conteudo = planilhas.gerar(nome, db, pasta)
        (saidas / f"{nome}.csv").write_bytes(conteudo)
        arquivos[f"{nome}.csv"] = conteudo
    params = (pasta / svc_parametros.ARQUIVO)
    arquivos["parametros.json"] = params.read_bytes() if params.is_file() else b"{}"
    arquivos["LEIAME.txt"] = LEIAME.encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    (saidas / "pacote.zip").write_bytes(buffer.getvalue())
    return buffer.getvalue()
