@echo off
REM ============================================================================
REM  setup.bat — Configura o ambiente PDF-OCR no Windows
REM
REM  Usa uv (gerenciador de pacotes Python) em vez de pip/venv.
REM  Baixa e extrai:
REM    1. Poppler     (pdftoppm)  → .deps\poppler
REM    2. Tesseract   (tesseract) → .deps\tesseract
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ====== PDF-OCR: Configuracao automatica (uv) ======
echo.

REM ----------------------------------------------------------------------
REM  0. Verificar uv
REM ----------------------------------------------------------------------
where uv >nul 2>nul
if errorlevel 1 (
    echo [1/5] uv nao encontrado. Instalando via pip...
    pip install uv
    if errorlevel 1 (
        echo ERRO: Nao foi possivel instalar uv. Instale manualmente:
        echo   pip install uv
        exit /b 1
    )
) else (
    echo [1/5] uv encontrado.
)

REM ----------------------------------------------------------------------
REM  1. Instalar pacotes Python com uv
REM ----------------------------------------------------------------------
echo [2/5] Instalando dependencias Python com uv...
uv sync
if errorlevel 1 (
    echo ERRO: Falha ao sincronizar dependencias.
    exit /b 1
)
echo     Dependencias instaladas.

set DEPS_DIR=%~dp0.deps

REM ----------------------------------------------------------------------
REM  2. Baixar Poppler
REM ----------------------------------------------------------------------
set POPPLER_DIR=%DEPS_DIR%\poppler
set POPPLER_ZIP=%DEPS_DIR%\poppler.zip

if exist "%POPPLER_DIR%\Library\bin\pdftoppm.exe" (
    echo [3/5] Poppler ja baixado em .deps\poppler.
) else (
    echo [3/5] Baixando Poppler (26.02.0)...

    if not exist "%DEPS_DIR%" mkdir "%DEPS_DIR%"

    REM Download via PowerShell com TLS 1.2
    powershell -NoProfile -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/oschwartz10612/poppler-windows/releases/download/v26.02.0-0/Release-26.02.0-0.zip' -OutFile '%POPPLER_ZIP%' -UseBasicParsing }"

    if not exist "%POPPLER_ZIP%" (
        echo ERRO: Falha no download do Poppler.
        echo       Baixe manualmente de:
        echo       https://github.com/oschwartz10612/poppler-windows/releases
        exit /b 1
    )

    echo     Extraindo...
    powershell -NoProfile -Command "& { Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%POPPLER_ZIP%', '%DEPS_DIR%\poppler_temp') }"

    if not exist "%DEPS_DIR%\poppler_temp" (
        echo ERRO: Falha ao extrair Poppler.
        exit /b 1
    )

    for /d %%d in ("%DEPS_DIR%\poppler_temp\*") do (
        move "%%d" "%POPPLER_DIR%" >nul
    )
    rmdir /s /q "%DEPS_DIR%\poppler_temp" 2>nul
    del "%POPPLER_ZIP%" 2>nul

    if exist "%POPPLER_DIR%\Library\bin\pdftoppm.exe" (
        echo     Poppler extraido com sucesso em .deps\poppler
    ) else (
        echo AVISO: Estrutura do Poppler diferente do esperado.
        echo        Verifique .deps\poppler\
    )
)

REM ----------------------------------------------------------------------
REM  3. Verificar Tesseract
REM ----------------------------------------------------------------------
set TESSERACT_DEFAULT=%ProgramFiles%\Tesseract-OCR\tesseract.exe
if exist "%TESSERACT_DEFAULT%" (
    echo [4/5] Tesseract encontrado em Program Files.
) else (
    echo [4/5] Tesseract nao encontrado em Program Files.
    echo        Baixe e instale manualmente de:
    echo        https://github.com/UB-Mannheim/tesseract/wiki
    echo.
    echo        Instale com suporte a Portuguese (Brasil).
    echo.
    echo        Ou extraia em .deps\tesseract\ e configure manualmente.
)

REM ----------------------------------------------------------------------
REM  4. Gerar .env com os caminhos detectados
REM ----------------------------------------------------------------------
echo [5/5] Gerando arquivo .env...

set POPPLER_PATH=
if exist "%POPPLER_DIR%\Library\bin\pdftoppm.exe" (
    set "POPPLER_PATH=%POPPLER_DIR%\Library\bin"
)
set TESSERACT_CMD=
if exist "%TESSERACT_DEFAULT%" (
    set "TESSERACT_CMD=%TESSERACT_DEFAULT%"
)

(
    echo POPPLER_PATH=%POPPLER_PATH%
    echo TESSERACT_CMD=%TESSERACT_CMD%
) > ".env"

echo.
echo ====== Configuracao concluida! ======
echo.
echo Para executar:
echo   uv run main.py
echo.
echo Ou pelo atalho:
echo   run
echo.
pause
