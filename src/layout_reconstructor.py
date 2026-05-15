"""
Reconstrução de layout a partir dos dados do Tesseract.

Funções públicas:
  - reconstruct_layout(): reconstrói texto preservando parágrafos e
    colunas detectadas automaticamente.
"""

from __future__ import annotations

from collections import defaultdict


def _block_median_y(data: dict, block_num: int) -> float:
    """Calcula a mediana do eixo Y para um bloco."""
    y_vals = [
        data["top"][i]
        for i in range(len(data["level"]))
        if data["block_num"][i] == block_num
    ]
    if not y_vals:
        return 0.0
    y_vals.sort()
    mid = len(y_vals) // 2
    return float(y_vals[mid])


def reconstruct_layout(data: dict, auto_columns: bool = True) -> str:
    """Reconstrói o texto preservando layout e detectando colunas.

    Cada bloco detectado pelo Tesseract é classificado em uma coluna
    de acordo com sua posição horizontal. Depois as colunas são
    processadas da esquerda para a direita, cada uma de cima para baixo.

    Args:
        data: Dicionário retornado por ``image_to_data(…, Output.DICT)``.
        auto_columns: Se True, tenta detectar e agrupar colunas.

    Returns:
        Texto reconstruído com parágrafos e colunas preservados.
    """
    n = len(data["level"])

    # ── 1. Agrupar palavras: block -> para -> line -> [(left, word)] ──
    blocks_raw: dict[int, dict[int, dict[int, list[tuple[int, str]]]]] = (
        defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )

    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        block = data["block_num"][i]
        para = data["par_num"][i]
        line = data["line_num"][i]
        left = data["left"][i]
        blocks_raw[block][para][line].append((left, word))

    if not blocks_raw:
        return ""

    # ── 2. Detectar colunas (Opção B) ──
    if auto_columns and len(blocks_raw) > 1:
        # Coletar centro X de cada bloco
        block_centers: list[tuple[int, float]] = []
        for blk in blocks_raw:
            xs = [
                data["left"][i] + data["width"][i] / 2
                for i in range(n)
                if data["block_num"][i] == blk and (data["text"][i] or "").strip()
            ]
            if xs:
                block_centers.append((blk, sum(xs) / len(xs)))

        if len(block_centers) > 1:
            # Agrupar blocos em colunas por proximidade no eixo X
            # Usa largura total da página para calcular o limiar
            widths = [
                data["width"][i]
                for i in range(n)
                if data["text"][i] and data["text"][i].strip()
            ]
            page_width = (
                max(
                    data["left"][i] + data["width"][i]
                    for i in range(n)
                    if data["text"][i] and data["text"][i].strip()
                )
                if widths
                else 1000
            )

            # Limiar: metade da largura da página
            threshold = page_width / 2

            # Classificar blocos em colunas (esquerda / direita)
            colunas: dict[int, list[int]] = {0: [], 1: []}
            for blk, cx in block_centers:
                col = 0 if cx < threshold else 1
                colunas[col].append(blk)

            # Se uma das colunas ficou vazia, cai no fallback linear
            if colunas[0] and colunas[1]:
                text_parts: list[str] = []

                for col_id in sorted(colunas.keys()):
                    blocos_col = sorted(
                        colunas[col_id],
                        key=lambda b: _block_median_y(data, b),
                    )

                    for bi, blk in enumerate(blocos_col):
                        paras = blocks_raw[blk]
                        para_order = sorted(paras.keys())

                        for pi, para in enumerate(para_order):
                            lines = paras[para]
                            line_order = sorted(lines.keys())

                            for _li, line in enumerate(line_order):
                                words = lines[line]
                                words.sort(key=lambda x: x[0])
                                line_text = " ".join(w for _, w in words)
                                text_parts.append(line_text)

                            if pi < len(para_order) - 1:
                                text_parts.append("")

                        # Espaço entre blocos da mesma coluna
                        if bi < len(blocos_col) - 1:
                            text_parts.append("")
                            text_parts.append("")

                    # Espaço entre colunas
                    text_parts.append("")
                    text_parts.append("")

                result = "\n".join(text_parts).strip()
                # Se o resultado for muito maior que o esperado, cai no fallback
                if len(result) > 100:
                    return result

    # ── 3. Fallback: ordenação linear por Y (comportamento original) ──
    text_parts = []
    block_order = sorted(
        blocks_raw.keys(),
        key=lambda b: _block_median_y(data, b),
    )

    for block in block_order:
        paras = blocks_raw[block]
        para_order = sorted(paras.keys())

        for pi, para in enumerate(para_order):
            lines = paras[para]
            line_order = sorted(lines.keys())

            for _li, line in enumerate(line_order):
                words = lines[line]
                words.sort(key=lambda x: x[0])
                line_text = " ".join(w for _, w in words)
                text_parts.append(line_text)

            if pi < len(para_order) - 1:
                text_parts.append("")

        text_parts.append("")
        text_parts.append("")

    return "\n".join(text_parts).strip()
