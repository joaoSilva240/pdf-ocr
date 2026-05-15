"""
Configurações do projeto: paths, constantes e validação de dependências.

Fornece:
  - PROJECT_ROOT, PDF_DIR, DATA_DIR
  - DEPENDENCY_HELP
  - check_tesseract()
  - auto_detect_tesseract()
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger("pdf-ocr")

# ---------------------------------------------------------------------------
# Pastas do projeto
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
"""Raiz do projeto (onde fica main.py, pyproject.toml, etc)."""

PDF_DIR = PROJECT_ROOT / "pdf"
"""Pasta onde o usuário coloca os PDFs."""

DATA_DIR = PROJECT_ROOT / "data"
"""Pasta de saída para imagens e TXT."""

DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Documentação de dependência externa
# ---------------------------------------------------------------------------
DEPENDENCY_HELP = """
===============================================================================
  DEPENDENCIA EXTERNA NECESSARIA

  Tesseract OCR (para pytesseract)
    -> Download: https://github.com/UB-Mannheim/tesseract/wiki
    -> Instale COM suporte a portugues (por default)
    -> Adicione ao PATH ou configure tesseract_cmd no script

  Para instalar pacotes Python:
     uv sync
===============================================================================
"""


# ---------------------------------------------------------------------------
# Validação de dependências
# ---------------------------------------------------------------------------
def check_tesseract() -> bool:
    """Verifica se o tesseract está acessível no PATH."""
    return shutil.which("tesseract") is not None


def auto_detect_tesseract(tesseract_cmd: str | None = None) -> str | None:
    """Auto-detecção do executável Tesseract.

    Prioridade:
      1. ``tesseract_cmd`` passado como argumento (já resolvido)
      2. Variável de ambiente ``TESSERACT_CMD``
      3. Caminhos fixos comuns (Program Files, .deps/)

    Returns:
        Caminho resolvido ou ``None`` se não encontrado.
    """
    if tesseract_cmd:
        return tesseract_cmd

    # Prioridade 2: variável de ambiente
    env_tesseract = os.environ.get("TESSERACT_CMD")
    if env_tesseract:
        c = Path(env_tesseract)
        if c.is_file():
            resolved = str(c.resolve())
            log.info("Tesseract via TESSERACT_CMD: %s", resolved)
            return resolved

    # Prioridade 3: caminhos fixos
    candidates = [
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
        PROJECT_ROOT / ".deps" / "tesseract" / "tesseract.exe",
    ]
    for c in candidates:
        if c.is_file():
            resolved = str(c.resolve())
            log.info("Tesseract auto-detectado em: %s", resolved)
            return resolved

    return None


def ensure_utf8_stdout() -> None:
    """Força UTF-8 na saída do terminal (Windows cp1252 não suporta Unicode)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
