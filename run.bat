@echo off
cd /d "%~dp0"

REM Carregar config do setup se existir
if exist ".deps\config.txt" (
    for /f "tokens=1,* delims==" %%a in (.deps\config.txt) do set %%a=%%b
)

set POPPLER_PATH_ARG=
if not "%POPPLER_PATH%"=="" set POPPLER_PATH_ARG=--poppler-path "%POPPLER_PATH%"

set TESSERACT_CMD_ARG=
if not "%TESSERACT_CMD%"=="" set TESSERACT_CMD_ARG=--tesseract-cmd "%TESSERACT_CMD%"

.venv\Scripts\python.exe main.py %POPPLER_PATH_ARG% %TESSERACT_CMD_ARG% %*

pause
