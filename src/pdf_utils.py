"""
Utilitários para PDF: descoberta, seleção, parsing de páginas e conversão para imagens.

Funções públicas:
  - find_pdf_files()
  - select_pdf()
  - parse_pages()
  - ask_pages()
  - convert_pages_to_images()
"""

from __future__ import annotations

import io
import logging
import re
import sys
from pathlib import Path

from PIL import Image

from src.config import DATA_DIR, PDF_DIR

log = logging.getLogger("pdf-ocr")


# ---------------------------------------------------------------------------
# 1. Busca de PDFs
# ---------------------------------------------------------------------------
def find_pdf_files() -> list[Path]:
    """Procura arquivos .pdf nas pastas ``pdf/`` e (fallback) ``data/``.

    Returns:
        Lista de paths absolutos dos PDFs encontrados.
    """
    found: list[Path] = []

    # Prioridade 1: pasta pdf/
    if PDF_DIR.is_dir():
        found.extend(sorted(PDF_DIR.glob("*.pdf")))
        if found:
            log.info(
                "Encontrado(s) %d PDF(s) em 'pdf/': %s",
                len(found),
                ", ".join(p.name for p in found),
            )
            return found

    # Prioridade 2: pasta data/ (fallback)
    if DATA_DIR.is_dir():
        found.extend(sorted(DATA_DIR.glob("*.pdf")))
        if found:
            log.info(
                "Nenhum PDF em 'pdf/'. Usando PDF(s) de 'data/': %s",
                ", ".join(p.name for p in found),
            )
            return found

    return found


# ---------------------------------------------------------------------------
# 2. Seleção interativa
# ---------------------------------------------------------------------------
def select_pdf(pdfs: list[Path]) -> Path:
    """Exibe lista numerada e retorna o path do PDF escolhido."""
    print("\n>>> PDFs encontrados:\n")
    for i, path in enumerate(pdfs, start=1):
        size = path.stat().st_size
        size_str = (
            f"{size / 1_000_000:.2f} MB" if size > 1_000_000 else f"{size / 1_000:.1f} kB"
        )
        print(f"  [{i}] {path.name}  ({size_str})")

    while True:
        try:
            choice = input(f"\n>>> Escolha o numero do PDF (1-{len(pdfs)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(pdfs):
                selected = pdfs[idx]
                log.info("PDF selecionado: %s", selected.name)
                return selected
            print(f"  [!] Numero invalido. Digite entre 1 e {len(pdfs)}.")
        except (ValueError, EOFError):
            print("  [!] Entrada invalida. Digite um numero.")


# ---------------------------------------------------------------------------
# 3. Input de páginas
# ---------------------------------------------------------------------------
def parse_pages(page_input: str, total_pages: int) -> list[int]:
    """Converte string como ``'1-5, 7, 10-12'`` em lista de páginas 1‑indexed.

    A lista retornada é deduplicada e ordenada.
    Páginas fora de ``[1, total_pages]`` são ignoradas com aviso.
    """
    pages: set[int] = set()
    parts = [p.strip() for p in page_input.replace(";", ",").split(",")]

    for part in parts:
        if not part:
            continue
        range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        single_match = re.match(r"^(\d+)$", part)

        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        elif single_match:
            pages.add(int(single_match.group(1)))
        else:
            log.warning("Intervalo ignorado (formato inválido): %s", part)

    # Filtrar páginas dentro do range
    valid = sorted(p for p in pages if 1 <= p <= total_pages)
    invalid = sorted(p for p in pages if p < 1 or p > total_pages)
    if invalid:
        log.warning(
            "Páginas ignoradas (fora do range 1-%d): %s", total_pages, invalid
        )
    return valid


def _fmt_pages(pages: list[int]) -> str:
    """Formata lista de páginas para exibição amigável."""
    if len(pages) <= 6:
        return ", ".join(str(p) for p in pages)

    # Agrupa intervalos consecutivos
    ranges: list[tuple[int, int]] = []
    start = pages[0]
    end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append((start, end))
            start = p
            end = p
    ranges.append((start, end))

    parts = []
    for s, e in ranges:
        if s == e:
            parts.append(str(s))
        elif e - s <= 2:
            parts.append(", ".join(str(x) for x in range(s, e + 1)))
        else:
            parts.append(f"{s}-{e}")
    return ", ".join(parts)


def ask_pages(total_pages: int) -> list[int]:
    """Pergunta interativamente quais páginas converter.

    Args:
        total_pages: Número total de páginas do PDF.

    Returns:
        Lista 1-indexed de páginas selecionadas.
    """
    print(f"\n>>> O PDF tem {total_pages} pagina(s).")
    print("     Exemplos: '1-5, 7, 10-12'  |  '1,3,5'  |  '1-10'  |  'all'\n")

    while True:
        try:
            raw = input(f"\n>>> Quais paginas converter? ").strip().lower()
            if not raw:
                print("  [!] Digite algo.")
                continue
            if raw == "all":
                return list(range(1, total_pages + 1))

            pages = parse_pages(raw, total_pages)
            if not pages:
                print(f"  [!] Nenhuma pagina valida no range 1-{total_pages}. Tente novamente.")
                continue

            log.info("Paginas selecionadas: %s", _fmt_pages(pages))
            return pages
        except (EOFError, KeyboardInterrupt):
            print("\n  Operacao cancelada.")
            sys.exit(0)


# ---------------------------------------------------------------------------
# 4. Conversão PDF → Imagens
# ---------------------------------------------------------------------------
def convert_pages_to_images(
    pdf_path: Path,
    pages: list[int],
    output_dir: Path,
    dpi: int = 300,
    use_cache: bool = True,
) -> list[Path]:
    """Converte páginas selecionadas do PDF para PNG usando PyMuPDF.

    Se ``use_cache`` for True (padrão), verifica se o PNG da página
    já existe em ``output_dir`` e reaproveita, evitando conversões
    repetidas do mesmo PDF.

    Args:
        pdf_path: Caminho do PDF.
        pages: Lista 1-indexed de páginas.
        output_dir: Diretório onde salvar as imagens.
        dpi: Resolução da conversão (default 300).
        use_cache: Se True, reaproveita PNGs já existentes.

    Returns:
        Lista de paths das imagens geradas.
    """
    image_paths: list[Path] = []
    pages_to_convert: list[int] = []

    # ── Verificar cache ──
    if use_cache and output_dir.is_dir():
        for page in pages:
            cached = output_dir / f"pagina_{page:04d}.png"
            if cached.is_file():
                image_paths.append(cached)
                log.info("  Pagina %d: usando cache (%s)", page, cached.name)
            else:
                pages_to_convert.append(page)
    else:
        pages_to_convert = list(pages)

    if not pages_to_convert:
        log.info(
            "Todas as %d pagina(s) ja estao em cache em '%s/'.",
            len(pages),
            output_dir.name,
        )
        return image_paths

    log.info(
        "Convertendo %d pagina(s) para imagens (%d DPI) via PyMuPDF...",
        len(pages_to_convert),
        dpi,
    )

    import pymupdf

    doc = pymupdf.open(str(pdf_path))

    try:
        for page in pages_to_convert:
            page_idx = page - 1  # PyMuPDF é 0-indexed
            if page_idx < 0 or page_idx >= doc.page_count:
                log.warning("Pagina %d: indice fora do range.", page)
                continue

            pix = doc[page_idx].get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))

            out_path = output_dir / f"pagina_{page:04d}.png"
            img.save(str(out_path), "PNG")
            image_paths.append(out_path)
            log.info("  Pagina %d salva: %s", page, out_path.name)
    finally:
        doc.close()

    log.info(
        "Conversao concluida: %d imagem(ns) em '%s/'",
        len(image_paths),
        output_dir.name,
    )
    return image_paths
