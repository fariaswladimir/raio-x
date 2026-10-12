@echo off
rem Raio-X: instala o spaCy (opcional) e os modelos pequenos de ingles e portugues no ambiente virtual .venv.
rem Usado para classes gramaticais (POS), entidades nomeadas (NER) e a lematizacao "spacy" (4.5).
rem Download: cerca de 170 MB no total (spaCy e dependencias ~140 MB; cada modelo ~15 MB).
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" goto sem_venv

"%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto venv_quebrado

echo [Raio-X] Instalando o spaCy ...
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements-spacy.txt"
if errorlevel 1 goto erro

echo [Raio-X] Baixando o modelo de ingles (en_core_web_sm) ...
"%~dp0.venv\Scripts\python.exe" -m spacy download en_core_web_sm
if errorlevel 1 goto erro

echo [Raio-X] Baixando o modelo de portugues (pt_core_news_sm) ...
"%~dp0.venv\Scripts\python.exe" -m spacy download pt_core_news_sm
if errorlevel 1 goto erro

echo.
echo [Raio-X] spaCy instalado. Execute o pipeline de novo para gerar as classes gramaticais e as entidades.
echo [Raio-X] Para usar o lematizador do spaCy: parametros.json, "lematizacao": {"metodo": "spacy"}. Espanhol segue sem modelo.
goto fim

:sem_venv
echo.
echo [Raio-X] Ambiente virtual nao encontrado (.venv). Rode iniciar.bat primeiro e depois este arquivo.
goto fim

:venv_quebrado
echo.
echo [Raio-X] O ambiente .venv existe, mas nao funciona neste computador.
echo   Apague a pasta .venv, rode iniciar.bat (que recria o ambiente) e depois este arquivo.
goto fim

:erro
echo.
echo [Raio-X] Falha na instalacao do spaCy. Confira a conexao com a internet e rode de novo.

:fim
pause
