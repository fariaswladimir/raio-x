@echo off
rem Raio-X: instala o Docling (conversao de PDF/DOCX) no ambiente virtual .venv.
rem ATENCAO: o download e grande (~2 GB, inclui o PyTorch) e pode demorar varios minutos.
setlocal
cd /d "%~dp0"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

if not exist "%~dp0.venv\Scripts\python.exe" goto sem_venv

rem Confere se o .venv responde (uma pasta .venv copiada de outro computador nao funciona).
"%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto venv_quebrado

echo [Raio-X] O Docling baixa cerca de 2 GB (PyTorch e modelos). Ctrl+C para cancelar.
pause

echo [Raio-X] Instalando PyTorch (versao CPU) ...
"%~dp0.venv\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto erro

echo [Raio-X] Instalando Docling e o motor de OCR (RapidOCR + onnxruntime) ...
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements-docling.txt"
if errorlevel 1 goto erro

echo.
echo [Raio-X] Docling instalado (inclui RapidOCR + onnxruntime para o OCR por documento: modelos PP-OCR ja vem no pacote).
echo [Raio-X] Os modelos de layout do Docling sao baixados na 1a conversao de PDF/DOCX (precisa de internet nessa vez).
goto fim

:sem_venv
echo.
echo [Raio-X] Ambiente virtual nao encontrado (.venv).
echo   Rode iniciar.bat primeiro: ele cria o ambiente e instala as dependencias basicas.
echo   Depois rode este arquivo de novo.
goto fim

:venv_quebrado
echo.
echo [Raio-X] O ambiente .venv existe, mas nao funciona neste computador.
echo   Apague a pasta .venv, rode iniciar.bat (que recria o ambiente) e depois este arquivo.
goto fim

:erro
echo.
echo [Raio-X] Falha na instalacao do Docling.
echo   Confira a conexao com a internet e o espaco livre em disco (cerca de 3 GB). Pode rodar de novo.

:fim
pause
