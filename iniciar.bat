@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Descobre o comando do Python (py = launcher do instalador oficial; python = Microsoft Store)
set PY=
where py >nul 2>nul && set PY=py
if "%PY%"=="" ( where python >nul 2>nul && set PY=python )
if "%PY%"=="" (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Criando o ambiente virtual...
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"

echo Instalando dependencias (so demora na primeira vez)...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo Rodando os testes...
python -m pytest -q

echo.
echo Abrindo o app em http://localhost:8501 (feche esta janela para encerrar)
start "" cmd /c "timeout /t 8 >nul & start http://localhost:8501"
python -m streamlit run app.py --server.headless true
pause
