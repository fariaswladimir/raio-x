@echo off
rem Raio-X: cria o ambiente virtual na 1a vez, instala dependencias e sobe o servidor.
setlocal
cd /d "%~dp0"

rem Passo 1: Python instalado e acessivel pelo PATH? (no Windows, o atalho da Microsoft Store tambem falha aqui)
python -c "import sys" >nul 2>&1
if errorlevel 1 goto sem_python

rem Passo 2: versao 3.11 ou mais nova.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto versao_antiga

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [Raio-X] Criando ambiente virtual em .venv ...
    python -m venv "%~dp0.venv"
    if errorlevel 1 goto erro
)

echo [Raio-X] Verificando dependencias ...
"%~dp0.venv\Scripts\python.exe" -m pip install -q -r "%~dp0requirements.txt"
if errorlevel 1 goto erro

rem Abre o navegador depois de alguns segundos (o servidor leva um instante para subir).
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start "" http://localhost:8800"

echo [Raio-X] Servidor em http://localhost:8800  (Ctrl+C para encerrar)
"%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8800
goto fim

:sem_python
echo.
echo [Raio-X] Python nao encontrado neste computador.
echo   1. Baixe o Python 3.11 ou mais novo em: https://www.python.org/downloads/
echo   2. Na instalacao, marque a opcao "Add python.exe to PATH" (Adicionar python.exe ao PATH).
echo   3. Feche esta janela, abra uma nova e rode iniciar.bat de novo.
goto fim

:versao_antiga
echo.
echo [Raio-X] O Python instalado e mais antigo que a versao 3.11, exigida pelo Raio-X.
echo   Versao encontrada:
python --version
echo   Instale o Python 3.11 ou mais novo em: https://www.python.org/downloads/
echo   Marque "Add python.exe to PATH" na instalacao e rode iniciar.bat de novo.
goto fim

:erro
echo.
echo [Raio-X] Falha ao preparar o ambiente.
echo   - Confira a conexao com a internet (a 1a execucao baixa as dependencias).
echo   - Se a pasta .venv veio de outro computador ou a instalacao foi interrompida, apague a pasta .venv e rode de novo.
echo   - Se o Python estiver instalado mas nao for reconhecido, confira a opcao "Add python.exe to PATH".

:fim
pause
