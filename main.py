"""
PDF → OCR → TXT

Fluxo completo:
  1. Busca PDFs na pasta ./pdf/ (fallback: ./data/)
  2. Usuário seleciona o PDF e informa as páginas desejadas
  3. Converte páginas para imagens PNG via PyMuPDF
  4. Aplica OCR com pytesseract preservando layout
  5. Gera arquivo .txt com o resultado

Dependência do sistema:
  - Tesseract OCR (para pytesseract): https://github.com/UB-Mannheim/tesseract/wiki
    → Durante instalação, adicione ao PATH ou anote o caminho.

Uso:
  python main.py                        # modo interativo
  python main.py --pdf doc.pdf --pages 1-10
  python main.py --lang eng --psm 4
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import (
    DATA_DIR,
    PDF_DIR,
    DEPENDENCY_HELP,
    PROJECT_ROOT,
    check_tesseract,
    auto_detect_tesseract,
    ensure_utf8_stdout,
    log,
)
from src.pdf_utils import find_pdf_files, select_pdf, parse_pages, ask_pages
from src.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PDF → OCR → TXT — Converte PDF em texto com preservação de layout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python main.py                        # modo interativo\n"
            "  python main.py --pdf doc.pdf --pages 1-10\n"
            "  python main.py --lang eng --psm 4\n"
            "  python main.py --dpi 400\n"
            "  python main.py --no-keep-images       # limpa imagens após OCR\n"
        ),
    )

    parser.add_argument(
        "--pdf",
        help="Caminho do PDF (opcional; se omitido, busca em pdf/ e data/)",
    )
    parser.add_argument(
        "--pages",
        help="Páginas no formato '1-5, 7, 10-12' ou 'all' (opcional no modo interativo)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Arquivo .txt de saída (opcional; auto-nomeado se omitido)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Resolução da conversão PDF→imagem (default: 300)",
    )
    parser.add_argument(
        "--lang",
        default="por",
        help="Idioma do OCR (default: por). Ex: eng, por+eng",
    )
    parser.add_argument(
        "--psm",
        type=int,
        default=3,
        choices=[1, 3, 4, 6],
        help=(
            "Modo de segmentação Tesseract (default: 3):\n"
            "  1 = automático com OSD\n"
            "  3 = automático sem OSD (recomendado)\n"
            "  4 = coluna única\n"
            "  6 = bloco uniforme (uma coluna)"
        ),
    )
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Desativa pré-processamento da imagem (escala de cinza, contraste, binarização)",
    )
    parser.add_argument(
        "--no-binarize",
        action="store_true",
        help="Desativa binarização no pré-processamento",
    )
    parser.add_argument(
        "--no-denoise",
        action="store_true",
        help="Desativa remoção de ruído no pré-processamento",
    )
    parser.add_argument(
        "--no-auto-columns",
        action="store_true",
        help="Desativa detecção automática de colunas no layout",
    )
    parser.add_argument(
        "--no-multi-pass",
        action="store_true",
        help="Desativa multi-pass OCR (rodar apenas 1 passada de OCR)",
    )
    parser.add_argument(
        "--table-detect",
        action="store_true",
        help="Ativa detecção e formatação automática de tabelas",
    )
    parser.add_argument(
        "--tesseract-cmd",
        help="Caminho do executável tesseract (ex: C:/Tesseract-OCR/tesseract.exe)",
    )
    parser.add_argument(
        "--tessdata-dir",
        help="Caminho da pasta tessdata do Tesseract",
    )
    parser.add_argument(
        "--keep-images",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Manter imagens após OCR (default: True)",
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Apenas verifica dependências e sai",
    )

    return parser


def main() -> None:
    ensure_utf8_stdout()

    parser = build_parser()
    args = parser.parse_args()

    # ── Auto-detecção do Tesseract ──
    args.tesseract_cmd = auto_detect_tesseract(args.tesseract_cmd)

    # ── Apenas check de dependências ──
    if args.check_deps:
        tesseract_ok = check_tesseract()
        print("\n[CHECK] Verificacao de dependencias:\n")
        print(
            f"  Tesseract:           {'[OK]' if tesseract_ok else '[FALTA] NAO ENCONTRADO'}"
        )
        if args.tesseract_cmd:
            print(f"  Tesseract (--tesseract-cmd): {args.tesseract_cmd}")
        if not tesseract_ok and not args.tesseract_cmd:
            print(DEPENDENCY_HELP)
        sys.exit(0 if (tesseract_ok or args.tesseract_cmd) else 1)

    # ── Verificar dependência ──
    tesseract_ok = check_tesseract()
    if not tesseract_ok and not args.tesseract_cmd:
        log.error("Tesseract não encontrado no PATH nem em locais comuns.")
        print(DEPENDENCY_HELP)
        sys.exit(1)

    # ── 1. Selecionar PDF ──
    if args.pdf:
        pdf_path = Path(args.pdf).resolve()
        if not pdf_path.is_file():
            log.error("PDF não encontrado: %s", pdf_path)
            sys.exit(1)
    else:
        pdfs = find_pdf_files()
        if not pdfs:
            log.error(
                "Nenhum PDF encontrado em 'pdf/' ou 'data/'.\n"
                "  → Coloque arquivos .pdf na pasta 'pdf/' ou use --pdf CAMINHO"
            )
            PDF_DIR.mkdir(exist_ok=True)
            print(f"\n  A pasta '{PDF_DIR.name}/' foi criada.")
            print(f"     Coloque seus PDFs lá e execute novamente.")
            sys.exit(1)

        if len(pdfs) == 1:
            pdf_path = pdfs[0]
            log.info("PDF único encontrado: %s", pdf_path.name)
        else:
            pdf_path = select_pdf(pdfs)

    # ── 2. Obter número de páginas via PyMuPDF ──
    try:
        import pymupdf

        doc = pymupdf.open(str(pdf_path))
        total_pages = doc.page_count
        doc.close()
    except Exception as exc:
        log.warning("Não foi possível detectar número de páginas: %s", exc)
        total_pages = 0

    # ── 3. Selecionar páginas ──
    if args.pages:
        if args.pages.lower() == "all":
            if total_pages == 0:
                log.error("Use --pages 'all' requer detecção automática de páginas.")
                sys.exit(1)
            pages = list(range(1, total_pages + 1))
        else:
            if total_pages == 0:
                pages = parse_pages(args.pages, 999999)
            else:
                pages = parse_pages(args.pages, total_pages)
            if not pages:
                log.error("Nenhuma página válida na expressão: %s", args.pages)
                sys.exit(1)
    else:
        if total_pages == 0:
            log.error(
                "Não foi possível detectar o número de páginas.\n"
                "  Use --pages para especificar manualmente."
            )
            sys.exit(1)
        pages = ask_pages(total_pages)

    # ── Flags (--no-* invertem o default True) ──
    preprocess = not args.no_preprocess
    binarize = not args.no_binarize
    denoise = not args.no_denoise
    auto_columns = not args.no_auto_columns
    multi_pass = not args.no_multi_pass
    table_detect = args.table_detect

    # ── Log dos parâmetros ──
    log.info(
        "Iniciando pipeline: %s | %d página(s) | lang=%s | psm=%d | dpi=%d",
        pdf_path.name,
        len(pages),
        args.lang,
        args.psm,
        args.dpi,
    )
    if preprocess:
        log.info("Pré-processamento: binarizar=%s | remover ruído=%s", binarize, denoise)
    else:
        log.info("Pré-processamento desligado.")
    log.info("Detecção de colunas: %s", "ligada" if auto_columns else "desligada")
    log.info("Multi-pass OCR: %s", "ligado" if multi_pass else "desligado")
    log.info("Detecção de tabelas: %s", "ligada" if table_detect else "desligada")

    # ── Executar pipeline ──
    try:
        output = run_pipeline(
            pdf_path=pdf_path,
            pages=pages,
            dpi=args.dpi,
            lang=args.lang,
            psm=args.psm,
            output_txt=args.output,
            tessdata_dir=args.tessdata_dir,
            tesseract_cmd=args.tesseract_cmd,
            keep_images=args.keep_images,
            preprocess=preprocess,
            binarize=binarize,
            denoise=denoise,
            auto_columns=auto_columns,
            multi_pass=multi_pass,
            table_detect=table_detect,
            use_cache=True,
        )
        print(f"\n[OK] OCR concluido! Arquivo: {output}")
    except Exception as exc:
        log.exception("Falha no pipeline: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
