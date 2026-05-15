# syntax=docker/dockerfile:1

# ==============================================================================
#  PDF → OCR → TXT — Dockerfile
#
#  Multi-stage build:
#    builder  → instala dependências Python via uv
#    runtime  → Tesseract OCR + app num container único (pytesseract chama
#               o binário tesseract diretamente, precisa estar no mesmo
#               ambiente)
# ==============================================================================

# ── Stage 1: Builder ───────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instala uv (gestor de dependências mais rápido que pip)
RUN pip install --quiet --root-user-action=ignore uv
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copia apenas os arquivos de definição de dependências para aproveitar cache
COPY pyproject.toml uv.lock ./

# Instala dependências num virtual environment dentro de /app/.venv
# --frozen: usa uv.lock como está (sem resolver de novo)
# --no-install-project: não instala o projeto em si (só deps)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project


# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# ── 1. System dependencies ─────────────────────────────────────────────────────
# Tesseract OCR + language packs (português e inglês)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-por \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# ── 2. Python environment ──────────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copia o virtual environment do builder (contém todas as deps Python)
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# ── 3. Aplicação ───────────────────────────────────────────────────────────────
WORKDIR /app

# Cria diretórios de dados com permissão correta
RUN mkdir -p pdf data

# Copia o código-fonte (excluindo o que está em .dockerignore)
COPY . .

# ── 4. Health check (verifica se tesseract está acessível) ─────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import shutil; exit(0 if shutil.which('tesseract') else 1)"

# ── 5. Entrypoint ──────────────────────────────────────────────────────────────
# Suporta tanto modo interativo (docker run -it) quanto não-interativo
ENTRYPOINT ["python", "main.py"]
