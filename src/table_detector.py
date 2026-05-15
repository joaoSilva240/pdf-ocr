"""
Detecção e formatação de tabelas via coordenadas do Tesseract.

Fornece:
  - detect_and_format_tables(): detecta tabelas analisando gaps entre palavras.
  - table_to_markdown(): converte DataFrame para Markdown pipes.
  - mask_table_regions(): pinta de branco regiões de tabela na imagem.
"""

from __future__ import annotations

import logging
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger("pdf-ocr")


# ---------------------------------------------------------------------------
# 5B. Detecção e formatação de tabelas via coordenadas do Tesseract
# ---------------------------------------------------------------------------
def detect_and_format_tables(
    image_path: Path,
    lang: str = "por",
    tesseract_cmd: str | None = None,
    min_rows: int = 3,
    gap_threshold: int = 500,
) -> list[dict]:
    """Detecta tabelas na imagem analisando gaps entre palavras.

    Estratégia:
      1. Roda ``image_to_data`` com ``--psm 6`` para obter cada
         palavra com coordenada X.
      2. Divide cada linha em **colunas visuais**: sempre que o
         gap entre duas palavras consecutivas for > ``gap_threshold``
         pixels, considera que começou uma nova coluna.
      3. Detecta **sequências de linhas** consecutivas que tenham
         o mesmo padrão de colunas (≥ 3 colunas).
      4. Filtra falsos positivos (texto de duas colunas): verifica
         se as posições dos gaps são **consistentes** entre linhas.
      5. Extrai células e retorna uma representação em DataFrame.

    Args:
        image_path: Caminho da imagem PNG.
        lang: Idioma do OCR.
        tesseract_cmd: Caminho do executável Tesseract.
        min_rows: Mínimo de linhas para considerar tabela.
        gap_threshold: Gap mínimo (px) entre palavras para
                       considerar nova coluna.

    Returns:
        Lista de dicionários com "df" (DataFrame), "y_start",
        "y_end" e "title".
    """
    import pytesseract
    from pytesseract import Output

    from PIL import Image

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    img = Image.open(str(image_path))
    data = pytesseract.image_to_data(
        img, lang=lang, config="--psm 6", output_type=Output.DICT
    )

    tables_found: list[dict] = []

    if not data or not data.get("text"):
        return tables_found

    n = len(data["level"])

    # 1. Agrupar palavras por linha (global, ignorando block_num)
    lines: dict[int, list[dict]] = defaultdict(list)
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        lines[data["line_num"][i]].append({
            "x": data["left"][i],
            "y": data["top"][i],
            "text": word,
        })

    sorted_lines = sorted(lines.items(), key=lambda kv: kv[0])

    def _split_columns(words_list: list[dict]) -> tuple[list[str], list[int]]:
        """Divide palavras em colunas por gaps > gap_threshold."""
        sw = sorted(words_list, key=lambda w: w["x"])
        cols_text: list[str] = []
        cols_x_start: list[int] = []
        cur_group = [sw[0]["text"]]
        prev_x = sw[0]["x"]

        for w in sw[1:]:
            if w["x"] - prev_x >= gap_threshold:
                cols_text.append(" ".join(cur_group))
                cols_x_start.append(prev_x)
                cur_group = [w["text"]]
            else:
                cur_group.append(w["text"])
            prev_x = w["x"]

        cols_text.append(" ".join(cur_group))
        cols_x_start.append(prev_x)
        return cols_text, cols_x_start

    # 2. Extrair perfil de colunas de cada linha
    line_profiles: list[dict] = []
    for line_num, words in sorted_lines:
        cols_text, cols_x = _split_columns(words)
        line_profiles.append({
            "line_num": line_num,
            "num_cols": len(cols_text),
            "cols_text": cols_text,
            "cols_x": cols_x[:3],  # primeiras 3 colunas
        })

    # 3. Detectar sequências com 3+ colunas consistentes
    i = 0
    while i < len(line_profiles):
        if line_profiles[i]["num_cols"] >= 3:
            start = i
            while i < len(line_profiles) and line_profiles[i]["num_cols"] >= 2:
                i += 1
            end = i
            seq = line_profiles[start:end]

            if len(seq) < min_rows:
                continue

            # 4. Filtrar falsos positivos
            valid_lines = [lp for lp in seq if lp["num_cols"] >= 3]

            if len(valid_lines) < min_rows:
                continue

            # Critério A: pelo menos 50% das linhas têm 3+ colunas
            if len(valid_lines) / len(seq) < 0.5:
                continue

            # Critério B: coluna 1 SEMPRE começa antes de x=2000
            # (tabela: nomes na esquerda; texto 2 col: pode começar na direita)
            all_col1 = [
                lp["cols_x"][0]
                for lp in valid_lines
                if len(lp["cols_x"]) >= 1
            ]
            if not all_col1 or not all(c1 < 2000 for c1 in all_col1):
                continue

            # 5. Extrair dados da tabela
            # Pula linhas iniciais curtas que pareçam título/artefato
            data_start = 0
            for idx, lp in enumerate(seq):
                first_col = lp["cols_text"][0] if lp["cols_text"] else ""
                if len(first_col) > 3:  # primeira coluna com conteúdo real
                    data_start = idx
                    break

            # Primeira linha de dados real = cabeçalho
            data_rows_raw = [lp["cols_text"] for lp in seq[data_start:]]

            if len(data_rows_raw) < 2:
                continue

            # Agrupa colunas: as 3 primeiras colunas reais são as relevantes
            # (ignora fragmentos causados por gaps intra-célula)
            header = (
                data_rows_raw[0][:3]
                if len(data_rows_raw[0]) >= 3
                else data_rows_raw[0]
            )
            data_rows = [
                row[:3] if len(row) >= 3 else row
                for row in data_rows_raw[1:]
            ]

            if len(data_rows) < 2:
                continue

            # Normalizar para 3 colunas
            def _normalize(row, n=3):
                while len(row) < n:
                    row.append("")
                # Mesclar colunas extras de volta na 3ª coluna
                if len(row) > n:
                    row[n - 1] = " ".join(row[n - 1:])
                    row = row[:n]
                return row

            header = _normalize(header)
            data_rows = [_normalize(r) for r in data_rows]

            import pandas as pd

            df = pd.DataFrame(data_rows, columns=header)

            # y_start / y_end para posicionamento
            y_vals = [
                w["y"]
                for _, words in sorted_lines[start:end]
                for w in words
            ]
            y_start_val = min(y_vals) if y_vals else 0
            y_end_val = max(y_vals) + 20 if y_vals else 0

            tables_found.append({
                "df": df,
                "y_start": y_start_val,
                "y_end": y_end_val,
                "title": "",
            })

        else:
            i += 1

    return tables_found


def table_to_markdown(table_df: "pd.DataFrame") -> str:
    """Converte um DataFrame de tabela para formato Markdown pipes."""
    rows = table_df.values.tolist()
    headers = list(table_df.columns)

    lines: list[str] = []
    # Cabeçalho
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    # Separador
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    # Dados
    for row in rows:
        # Garantir que a linha tenha o mesmo número de colunas
        padded = [str(c) if c is not None else "" for c in row]
        while len(padded) < len(headers):
            padded.append("")
        lines.append("| " + " | ".join(padded[: len(headers)]) + " |")

    return "\n".join(lines)


def mask_table_regions(image_path: Path, tables: list[dict]) -> Path:
    """Pinta de branco as regiões de tabela na imagem.

    Isso evita que o OCR leia o texto das tabelas duas vezes:
    uma pelo OCR normal e outra pela extração estruturada.

    Args:
        image_path: Caminho da imagem original.
        tables: Lista de tabelas detectadas com coordenadas.

    Returns:
        Path da imagem mascarada (temp file).
    """
    from PIL import Image, ImageDraw

    img = Image.open(str(image_path))
    draw = ImageDraw.Draw(img)

    for table in tables:
        y_start = table["y_start"] - 5  # margem mínima
        y_end = table["y_end"] + 5
        # Pinta apenas a faixa horizontal onde está a tabela
        draw.rectangle(
            [(0, max(0, y_start)), (img.width, min(img.height, y_end))],
            fill="white",
        )

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    masked_path = Path(tmp.name)
    img.save(str(masked_path), "PNG")
    tmp.close()
    return masked_path
