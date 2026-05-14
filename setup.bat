@echo off
REM ============================================================================
REM  setup.bat — Configura o ambiente PDF-OCR no Windows
REM
REM  Baixa e extrai:
REM    1. Poppler     (pdftoppm)  → .deps\poppler
REM    2. Tesseract   (tesseract) → .deps\tesseract
REM
REM  E instala os pacotes Python via pip.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ====== PDF-OCR: Configuracao automatica ======
echo.

REM ----------------------------------------------------------------------
REM  0. Ativar virtualenv (criar se nao existir)
REM ----------------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Criando ambiente virtual...
    python -m venv .venv
    if errorlevel 1 (
        echo ERRO: Nao foi possivel criar o virtualenv. Instale Python 3.13+.
        exit /b 1
    )
) else (
    echo [1/5] Ambiente virtual ja existe.
)

set VENV_PYTHON=%~dp0.venv\Scripts\python.exe
set VENV_PIP=%~dp0.venv\Scripts\pip.exe

REM ----------------------------------------------------------------------
REM  1. Instalar pacotes Python
REM ----------------------------------------------------------------------
echo [2/5] Instalando pacotes Python (pdf2image, pytesseract, Pillow)...
"%VENV_PIP%" install pdf2image pytesseract Pillow
if errorlevel 1 (
    echo ERRO: Falha ao instalar pacotes Python.
    exit /b 1
)

REM ----------------------------------------------------------------------
REM  2. Baixar Poppler
REM ----------------------------------------------------------------------
set DEPS_DIR=%~dp0.deps
set POPPLER_DIR=%DEPS_DIR%\poppler
set POPPLER_ZIP=%DEPS_DIR%\poppler.zip

if exist "%POPPLER_DIR%\Library\bin\pdftoppm.exe" (
    echo [3/5] Poppler ja baixado em .deps\poppler.
) else (
    echo [3/5] Baixando Poppler (26.02.0)...
    if not exist "%DEPS_DIR%" mkdir "%DEPS_DIR%"

    echo     Download de ~16 MB...
    powershell -Command "& {
        $url = 'https://github.com/oschwartz10612/poppler-windows/releases/download/v26.02.0-0/Release-26.02.0-0.zip'
        $out = '%POPPLER_ZIP%'
        Write-Host '       Baixando...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
    }"

    if not exist "%POPPLER_ZIP%" (
        echo ERRO: Falha no download do Poppler.
        echo       Baixe manualmente de:
        echo       https://github.com/oschwartz10612/poppler-windows/releases
        exit /b 1
    )

    echo     Extraindo...
    powershell -Command "& {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory('%POPPLER_ZIP%', '%DEPS_DIR%\poppler_temp')
    }"

    if not exist "%DEPS_DIR%\poppler_temp" (
        echo ERRO: Falha ao extrair Poppler.
        exit /b 1
    )

    REM Mover de dentro da pasta com versao para .deps\poppler
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
REM  3. Baixar Tesseract
REM ----------------------------------------------------------------------
set TESSERACT_DIR=%DEPS_DIR%\tesseract
set TESSERACT_EXE=%TESSERACT_DIR%\tesseract.exe
set TESSERACT_INSTALLER=%DEPS_DIR%\tesseract-installer.exe

if exist "%TESSERACT_EXE%" (
    echo [4/5] Tesseract ja baixado em .deps\tesseract.
) else (
    echo [4/5] Baixando Tesseract OCR (5.5.0)...

    if not exist "%DEPS_DIR%" mkdir "%DEPS_DIR%"

    REM Tesseract installer with Portuguese support
    powershell -Command "& {
        $url = 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe'
        $out = '%TESSERACT_INSTALLER%'
        Write-Host '       Baixando ~65 MB (pode levar alguns minutos)...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
    }"

    if not exist "%TESSERACT_INSTALLER%" (
        echo ERRO: Falha no download do Tesseract.
        echo       Baixe manualmente de:
        echo       https://github.com/UB-Mannheim/tesseract/releases
        exit /b 1
    )

    echo     Extraindo via instalador silencioso...
    REM Tentar extrair sem GUI: /S ou /verysilent
    REM Se falhar, orientar o usuario
    "%TESSERACT_INSTALLER%" /verysilent /dir="%TESSERACT_DIR%" /components="core,langs_por"

    if exist "%TESSERACT_EXE%" (
        echo     Tesseract instalado em .deps\tesseract
        del "%TESSERACT_INSTALLER%" 2>nul
    ) else (
        echo.
        echo Instalacao silenciosa pode ter falhado. Tentando modo alternativo...
        REM Modo alternativo: extrair o 7z embutido
        "%TESSERACT_INSTALLER%" /S /D="%TESSERACT_DIR%"
        if exist "%TESSERACT_EXE%" (
            echo     Tesseract instalado em .deps\tesseract
        )
    )

    if not exist "%TESSERACT_EXE%" (
        echo.
        echo AVISO: Nao foi possivel instalar Tesseract automaticamente.
        echo        Baixe manualmente de:
        echo        https://github.com/UB-Mannheim/tesseract/releases
        echo.
        echo        Instale EM: %TESSERACT_DIR%
        echo        E marque a opcao de suporte a Portuguese (Brasil).
    )
)

REM ----------------------------------------------------------------------
REM  4. Criar atalhos / config
REM ----------------------------------------------------------------------
echo [5/5] Gerando arquivo de configuracao...

REM Salvar caminhos para o script Python usar
set CONFIG_FILE=%~dp0.deps\config.txt
echo POPPLER_PATH=%POPPLER_DIR%\Library\bin > "%CONFIG_FILE%"
echo TESSERACT_CMD=%TESSERACT_EXE% >> "%CONFIG_FILE%"

echo.
echo ====== Configuracao concluida! ======
echo.
echo Para processar um PDF:
echo   %VENV_PYTHON% main.py
echo.
echo Ou com caminhos explicitos:
echo   %VENV_PYTHON% main.py --poppler-path "%POPPLER_DIR%\Library\bin" --tesseract-cmd "%TESSERACT_EXE%"
echo.
echo Ou via run.bat (ja configurado):
echo   run
echo.
pause
