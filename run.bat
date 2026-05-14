@echo off
cd /d "%~dp0"

REM ============================================================================
REM  run.bat — Executa o OCR usando uv
REM ============================================================================

REM Carregar .env se existir (suportado pelo uv)
if exist ".env" (
    echo Carregando configuracoes de .env
)

REM Executa com uv (auto-detecta .venv, instala deps se necessario)
uv run main.py %*

echo.
pause
