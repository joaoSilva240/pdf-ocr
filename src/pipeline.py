"""
Pipeline principal: coordena PDF → imagens → OCR → TXT.

Funções públicas:
  - run_pipeline(): executa o pipeline completo.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR, log
from src.ocr_engine import clean_text, ocr_image_multi_pass, ocr_image_with_layout
from src.pdf_utils import convert_pages_to_images
from src.table_detector import (
    detect_and_format_tables,
    mask_table_regions,
    table_to_markdown,
)


# ---------------------------------------------------------------------------
# 7. Pipeline principal
# ---------------------------------------------------------------------------
def run_pipeline(
    pdf_path: Path,
    pages: list[int],
    dpi: int = 300,
    lang: str = "por",
    psm: int = 3,
    output_txt: Path | None = None,
    tessdata_dir: str | None = None,
    tesseract_cmd: str | None = None,
    keep_images: bool = True,
    preprocess: bool = True,
    binarize: bool = True,
    denoise: bool = True,
    auto_columns: bool = True,
    multi_pass: bool = True,
    table_detect: bool = False,
    use_cache: bool = True,
) -> Path:
    """Executa o pipeline completo: PDF → imagens → OCR → TXT.

    Args:
        pdf_path: Caminho do arquivo PDF.
        pages: Lista 1-indexed de páginas para processar.
        dpi: Resolução da conversão PDF→imagem.
        lang: Idioma do OCR.
        psm: Modo de segmentação Tesseract.
        output_txt: Path opcional do arquivo .txt de saída.
        tessdata_dir: Diretório tessdata do Tesseract.
        tesseract_cmd: Caminho do executável Tesseract.
        keep_images: Manter imagens intermediárias após OCR.
        preprocess: Aplica pré-processamento na imagem antes do OCR.
        binarize: Converte para preto e branco.
        denoise: Remove ruído com filtro mediano.
        auto_columns: Tenta detectar colunas no layout.
        multi_pass: Se True, roda OCR em 2 passadas (c/ e s/ preprocess)
                    e mescla para capturar títulos decorativos.
        table_detect: Se True, detecta e formata tabelas via
                      coordenadas do Tesseract.
        use_cache: Reaproveita PNGs já existentes na pasta data/.

    Returns:
        Path do arquivo .txt gerado.
    """
    # 4. Converter páginas para imagens via PyMuPDF
    images = convert_pages_to_images(
        pdf_path=pdf_path,
        pages=pages,
        output_dir=DATA_DIR,
        dpi=dpi,
        use_cache=use_cache,
    )

    if not images:
        log.error("Nenhuma imagem foi gerada. Abortando.")
        sys.exit(1)

    # 5. Aplicar OCR em cada imagem
    print("\n[OCR] Aplicando OCR nas imagens...")
    all_text_parts: list[str] = []

    for i, img_path in enumerate(images, start=1):
        page_num = pages[i - 1]
        print(f"\n--- Pagina {page_num} ---")

        # ── (opcional) Detectar tabelas ──
        tables = []
        masked_path = img_path
        if table_detect:
            try:
                tables = detect_and_format_tables(
                    image_path=img_path,
                    lang=lang,
                    tesseract_cmd=tesseract_cmd,
                )
                if tables:
                    log.info(
                        "  %d tabela(s) detectada(s) na pagina %d",
                        len(tables),
                        page_num,
                    )
                    # Mascarar regiões das tabelas para não duplicar no OCR
                    masked_path = mask_table_regions(img_path, tables)
            except Exception as exc:
                log.warning("  Falha na detecção de tabelas: %s", exc)
                tables = []

        try:
            if multi_pass:
                text = ocr_image_multi_pass(
                    image_path=masked_path,
                    lang=lang,
                    psm=psm,
                    tessdata_dir=tessdata_dir,
                    tesseract_cmd=tesseract_cmd,
                    preprocess=preprocess,
                    binarize=binarize,
                    denoise=denoise,
                    auto_columns=auto_columns,
                )
            else:
                text = ocr_image_with_layout(
                    image_path=masked_path,
                    lang=lang,
                    psm=psm,
                    tessdata_dir=tessdata_dir,
                    tesseract_cmd=tesseract_cmd,
                    preprocess=preprocess,
                    binarize=binarize,
                    denoise=denoise,
                    auto_columns=auto_columns,
                )
            text = clean_text(text)

            # ── Inserir tabelas formatadas depois do texto ──
            if tables:
                tables_section = "\n\n---\n\n### Tabelas detectadas\n\n"
                for idx, tbl in enumerate(tables, start=1):
                    title = tbl.get("title") or f"Tabela {idx}"
                    tables_section += (
                        f"**{title}**\n\n" + table_to_markdown(tbl["df"]) + "\n\n"
                    )
                text += tables_section.strip()

            if text:
                preview = text[:200].replace("\n", " | ")
                print(
                    f"  Preview: {preview}{'...' if len(text) > 200 else ''}"
                )
            else:
                print("  (texto vazio ou ilegível)")

            # Limpar imagem mascarada temporária
            if masked_path != img_path:
                masked_path.unlink(missing_ok=True)

        except Exception as exc:
            log.error("Falha no OCR da página %d: %s", page_num, exc)
            text = f"[ERRO NA PÁGINA {page_num}: {exc}]"

        # Cabeçalho da página no resultado final
        page_header = (
            f"\n{'='*70}\nPÁGINA {page_num}\n{'='*70}\n"
        )
        all_text_parts.append(page_header + text + "\n")

    # 6. Gerar arquivo TXT
    if output_txt is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_txt = DATA_DIR / f"ocr_{pdf_path.stem}_{timestamp}.txt"

    full_text = "".join(all_text_parts)
    output_txt.write_text(full_text, encoding="utf-8")
    log.info(
        "Arquivo TXT gerado: %s (%d caracteres)",
        output_txt,
        len(full_text),
    )

    # Limpar imagens intermediárias (opcional)
    if not keep_images:
        for img_path in images:
            img_path.unlink(missing_ok=True)
        log.info("Imagens intermediárias removidas (--no-keep-images).")
    else:
        log.info("Imagens mantidas em '%s/'", DATA_DIR.name)

    return output_txt
