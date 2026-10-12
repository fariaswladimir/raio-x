@echo off
rem Raio-X: instalacao TOTALMENTE OFFLINE (EAP 11.2). Nao usa a internet em nenhum momento.
rem Requer o pacote raio-x-offline-*.zip extraido (pastas wheels\ e modelos\ ao lado deste arquivo)
rem e o Python 3.12 (64 bits) instalado: as rodas (wheels) do pacote sao para CPython 3.12 / Windows x64.
setlocal
cd /d "%~dp0"

rem Passo 1: Python instalado e acessivel pelo PATH? (no Windows, o atalho da Microsoft Store tambem falha aqui)
python -c "import sys" >nul 2>&1
if errorlevel 1 goto sem_python

rem Passo 2: versao 3.11 ou mais nova.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto versao_antiga

rem Passo 3: as rodas do pacote offline sao para o Python 3.12 de 64 bits.
python -c "import sys, struct; sys.exit(0 if (sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8) else 1)" >nul 2>&1
if errorlevel 1 goto versao_errada

if not exist "%~dp0wheels\" goto sem_wheels

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [Raio-X] Criando ambiente virtual em .venv ...
    python -m venv "%~dp0.venv"
    if errorlevel 1 goto erro
)

echo [Raio-X] Instalando as dependencias a partir da pasta wheels (sem internet) ...
"%~dp0.venv\Scripts\python.exe" -m pip install --no-index --find-links "%~dp0wheels" -r "%~dp0requirements.txt"
if errorlevel 1 goto erro

if exist "%~dp0wheels\docling-*.whl" (
    echo [Raio-X] Instalando o Docling, o PyTorch CPU e o OCR, sem internet ...
    "%~dp0.venv\Scripts\python.exe" -m pip install --no-index --find-links "%~dp0wheels" -r "%~dp0requirements-docling.txt"
    if errorlevel 1 goto erro
) else (
    echo [Raio-X] Este pacote nao inclui o Docling: PDF e DOCX nao serao convertidos. Arquivos .md e .txt funcionam normalmente.
)

echo [Raio-X] Instalando o spaCy e os modelos de ingles e portugues (sem internet) ...
"%~dp0.venv\Scripts\python.exe" -m pip install --no-index --find-links "%~dp0wheels" -r "%~dp0requirements-spacy.txt"
if errorlevel 1 goto erro
"%~dp0.venv\Scripts\python.exe" -m pip install --no-index --find-links "%~dp0wheels" en_core_web_sm pt_core_news_sm
if errorlevel 1 goto erro

if not exist "%~dp0projetos\" mkdir "%~dp0projetos"

rem Liga o modo offline: o Raio-X le este arquivo ao iniciar (HF_HUB_OFFLINE, modelos locais, sem consulta online, sem LLM remoto).
echo Modo offline do Raio-X (EAP 11.2). Apague este arquivo para voltar ao modo normal (precisa de internet).> "%~dp0raiox_offline.flag"

echo [Raio-X] Conferindo a instalacao ...
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\verificar_offline.py" --rapido
if errorlevel 1 goto erro

echo.
echo [Raio-X] Instalacao offline concluida. Rode iniciar.bat para abrir o sistema (selo "Offline" no topo da tela).
goto fim

:sem_python
echo.
echo [Raio-X] Python nao encontrado neste computador.
echo   1. Instale o Python 3.12 (64 bits) (o instalador baixado de python.org em outro computador, copiado por pendrive, serve).
echo   2. Na instalacao, marque a opcao "Add python.exe to PATH" (Adicionar python.exe ao PATH).
echo   3. Feche esta janela, abra uma nova e rode instalar_offline.bat de novo.
goto fim

:versao_antiga
echo.
echo [Raio-X] O Python instalado e mais antigo que a versao 3.11, exigida pelo Raio-X.
echo   Versao encontrada:
python --version
echo   Instale o Python 3.12 (64 bits) e marque "Add python.exe to PATH" na instalacao. Rode instalar_offline.bat de novo.
goto fim

:versao_errada
echo.
echo [Raio-X] O pacote offline foi preparado para o Python 3.12 de 64 bits.
echo   Versao encontrada:
python --version
echo   Instale o Python 3.12 (64 bits), deixe-o no PATH e rode instalar_offline.bat de novo.
goto fim

:sem_wheels
echo.
echo [Raio-X] A pasta wheels nao foi encontrada ao lado deste arquivo.
echo   Extraia o pacote raio-x-offline-*.zip inteiro (nao so o instalar_offline.bat) e rode de novo.
goto fim

:erro
echo.
echo [Raio-X] Falha na instalacao offline.
echo   - Confira se o pacote foi extraido por completo (pastas wheels e modelos) e se ha espaco livre em disco.
echo   - Se a pasta .venv veio de outro computador ou a instalacao foi interrompida, apague a pasta .venv e rode de novo.

:fim
pause
