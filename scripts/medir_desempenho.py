"""EAP 12.3: mede o pipeline MVP sobre uma pasta de artigos (somente leitura).

Uso (a partir da pasta raio-x):
    .venv\\Scripts\\python scripts\\medir_desempenho.py "C:\\caminho\\da\\pasta_de_artigos"

O script cria uma pasta temporária de projetos (RAIOX_PROJETOS_DIR), cria um projeto apontando para a pasta
informada, executa o pipeline duas vezes de forma síncrona medindo cada uma, lê as execuções de cada rodada
para somar o tempo por etapa, imprime uma tabela, grava docs/desempenho.md e apaga a pasta temporária.

A pasta de artigos só é lida. O script confere isso comparando nomes, tamanhos e datas de modificação antes
e depois da medição.
"""
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Precisa vir antes de importar o app: a pasta de projetos é lida pelo app a cada chamada.
_TEMP = Path(tempfile.mkdtemp(prefix="raiox_desempenho_"))
os.environ["RAIOX_PROJETOS_DIR"] = str(_TEMP / "projetos")
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding="utf-8")

import datetime as dt  # noqa: E402
import platform  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402

META_SEGUNDOS = 10 * 60
LIMITE_EXECUCOES = 1000  # máximo aceito por GET /execucoes


def memoria_gb():
    """Memória física total em GB (Windows, via API do sistema); None se não for possível ler."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return round(status.ullTotalPhys / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001
        return None


def informacoes_maquina() -> dict:
    return {
        "sistema": platform.platform(),
        "processador": platform.processor() or platform.machine(),
        "nucleos_logicos": os.cpu_count(),
        "memoria_gb": memoria_gb(),
        "python": platform.python_version(),
    }


def instantaneo(pasta: Path) -> dict:
    """Nome relativo -> (tamanho, data de modificação) de todos os arquivos da pasta."""
    estado = {}
    for p in pasta.rglob("*"):
        if p.is_file():
            st = p.stat()
            estado[str(p.relative_to(pasta))] = (st.st_size, st.st_mtime_ns)
    return estado


def segundos_entre(inicio: str, fim: str | None) -> float | None:
    if not fim:
        return None
    return (dt.datetime.fromisoformat(fim) - dt.datetime.fromisoformat(inicio)).total_seconds()


def rodada(client, slug: str, ultimo_id: int, rotulo: str) -> dict:
    """Executa o pipeline (síncrono), mede o tempo e lê as execuções geradas por esta rodada."""
    inicio = time.perf_counter()
    r = client.post(f"/api/projetos/{slug}/executar?sincrono=1")
    total = time.perf_counter() - inicio
    if r.status_code != 200:
        raise SystemExit(f"{rotulo}: executar devolveu {r.status_code}: {r.text}")
    resumo = r.json()

    execucoes = client.get(f"/api/projetos/{slug}/execucoes", params={"limite": LIMITE_EXECUCOES}).json()
    novas = [e for e in execucoes if e["id"] > ultimo_id]
    aviso = None
    if len(execucoes) >= LIMITE_EXECUCOES and len(novas) >= LIMITE_EXECUCOES:
        aviso = "a listagem de execuções pode ter sido cortada; o tempo por etapa está subestimado"

    por_etapa: dict = defaultdict(lambda: {"itens": 0, "ok": 0, "pulado": 0, "erro": 0, "segundos": 0.0})
    for e in novas:
        acc = por_etapa[e["etapa"]]
        acc["itens"] += 1
        acc[e["status"]] = acc.get(e["status"], 0) + 1
        s = segundos_entre(e["iniciado_em"], e["finalizado_em"])
        if s:
            acc["segundos"] += s
    return {
        "rotulo": rotulo,
        "segundos": total,
        "erros": resumo["erros"],
        "por_etapa": dict(por_etapa),
        "execucoes": len(novas),
        "aviso": aviso,
        "ultimo_id": max([e["id"] for e in execucoes], default=ultimo_id),
    }


def formatar_tempo(segundos: float) -> str:
    minutos, resto = divmod(segundos, 60)
    return f"{int(minutos)} min {resto:04.1f} s" if minutos else f"{resto:.1f} s"


def tabela_etapas(r1: dict, r2: dict) -> list[str]:
    etapas = list(dict.fromkeys(list(r1["por_etapa"]) + list(r2["por_etapa"])))
    linhas = ["| Etapa | Execuções (1ª) | ok | pulado | erro | Tempo 1ª (s) | Tempo 2ª (s) |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for nome in etapas:
        a = r1["por_etapa"].get(nome, {"itens": 0, "ok": 0, "pulado": 0, "erro": 0, "segundos": 0.0})
        b = r2["por_etapa"].get(nome, {"segundos": 0.0})
        linhas.append(f"| {nome} | {a['itens']} | {a['ok']} | {a['pulado']} | {a['erro']} | "
                      f"{a['segundos']:.2f} | {b['segundos']:.2f} |")
    return linhas


def escrever_relatorio(dados: dict, r1: dict, r2: dict) -> Path:
    destino = RAIZ / "docs" / "desempenho.md"
    m = dados["maquina"]
    ok_meta = r1["segundos"] < META_SEGUNDOS
    veredito = (
        f"**Atingido.** A primeira execução completa levou {formatar_tempo(r1['segundos'])}, abaixo da meta de 10 min."
        if ok_meta else
        f"**Não atingido.** A primeira execução completa levou {formatar_tempo(r1['segundos'])}, acima da meta de 10 min."
    )
    if r1["erros"] or r2["erros"]:
        veredito += f" Houve erros registrados (1ª: {r1['erros']}, 2ª: {r2['erros']}); ver a tabela de etapas."
    linhas = [
        "# Desempenho do pipeline MVP (EAP 12.3)",
        "",
        f"- **Data da medição:** {dados['data']}",
        f"- **Máquina:** {m['sistema']}; processador {m['processador']}; {m['nucleos_logicos']} núcleos lógicos; "
        f"memória {m['memoria_gb'] or 'não lida'} GB; Python {m['python']}",
        f"- **Pasta medida:** `{dados['pasta']}` (somente leitura; {dados['arquivos']} arquivos antes e depois, "
        f"{'sem alterações' if dados['sem_alteracoes'] else 'ALTERAÇÃO DETECTADA'})",
        f"- **Documentos:** {dados['documentos']} (todos `.md`, sem conversão por Docling)",
        f"- **Tokens:** {dados['tokens']:,} no corpo; {dados['tokens_total']:,} com referências e apêndices".replace(",", "."),
        "- **Meta (EAP 12.3):** pipeline MVP em menos de 10 min",
        "",
        "## Tempos",
        "",
        "| Execução | Tempo total | Erros | Execuções registradas |",
        "|---|---:|---:|---:|",
        f"| 1ª (sem cache) | {formatar_tempo(r1['segundos'])} | {r1['erros']} | {r1['execucoes']} |",
        f"| 2ª (com cache) | {formatar_tempo(r2['segundos'])} | {r2['erros']} | {r2['execucoes']} |",
        "",
        "## Tempo por etapa",
        "",
        "Soma de `finalizado_em - iniciado_em` das execuções de cada rodada (por documento e por corpus). "
        "Na 2ª rodada, as etapas com cache aparecem como `pulado`.",
        "",
        *tabela_etapas(r1, r2),
        "",
        "## Veredito",
        "",
        veredito,
        "",
        f"Reproduzir: `.venv\\Scripts\\python scripts\\medir_desempenho.py \"{dados['pasta']}\"`.",
    ]
    for r in (r1, r2):
        if r["aviso"]:
            linhas += ["", f"> Aviso ({r['rotulo']}): {r['aviso']}."]
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")
    return destino


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python scripts\\medir_desempenho.py \"pasta_de_artigos\"")
        return 2
    origem = Path(sys.argv[1]).resolve()
    if not origem.is_dir():
        print(f"Pasta não encontrada: {origem}")
        return 2

    from fastapi.testclient import TestClient

    from app import database
    from app.main import app

    antes = instantaneo(origem)
    try:
        with TestClient(app) as client:
            r = client.post("/api/projetos", json={"nome": "Medição de desempenho", "pasta_origem": str(origem)})
            if r.status_code != 201:
                print(f"Não foi possível criar o projeto: {r.status_code} {r.text}")
                return 1
            slug = r.json()["slug"]
            print(f"Projeto temporário: {slug}")
            r1 = rodada(client, slug, 0, "1ª execução")
            print(f"1ª execução: {formatar_tempo(r1['segundos'])} (erros: {r1['erros']})")
            r2 = rodada(client, slug, r1["ultimo_id"], "2ª execução")
            print(f"2ª execução: {formatar_tempo(r2['segundos'])} (erros: {r2['erros']})")
            documentos = client.get(f"/api/projetos/{slug}/documentos").json()
            corpus = client.get(f"/api/projetos/{slug}/analises/resumo").json()["corpus"]

        depois = instantaneo(origem)
        dados = {
            "data": dt.date.today().isoformat(),
            "maquina": informacoes_maquina(),
            "pasta": str(origem),
            "arquivos": len(depois),
            "sem_alteracoes": antes == depois,
            "documentos": len(documentos),
            "tokens": corpus["tokens"],
            "tokens_total": corpus["tokens_total"],
        }
        print()
        print("\n".join(tabela_etapas(r1, r2)))
        print()
        destino = escrever_relatorio(dados, r1, r2)
        print(f"Relatório gravado em {destino}")
        if not dados["sem_alteracoes"]:
            print("ATENÇÃO: a pasta de artigos foi alterada durante a medição.")
            return 1
        return 0
    finally:
        for engine in list(database._engines.values()):
            engine.dispose()
        database._engines.clear()
        shutil.rmtree(_TEMP, ignore_errors=True)
        print(f"Pasta temporária removida: {not _TEMP.exists()}")


if __name__ == "__main__":
    sys.exit(main())
