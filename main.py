"""
PDF → OCR → TXT

Fluxo completo:
  1. Busca PDFs na pasta ./pdf/ (fallback: ./data/)
  2. Usuário seleciona o PDF e informa as páginas desejadas
  3. Converte páginas para imagens PNG via pdf2image
  4. Aplica OCR com pytesseract preservando layout
  5. Gera arquivo .txt com o resultado

Dependências do sistema (instalar antes):
  - Poppler (para pdf2image): https://github.com/oschwartz10612/poppler-windows
  - Tesseract OCR (para pytesseract): https://github.com/UB-Mannheim/tesseract/wiki
    → Durante instalação, adicione ao PATH ou anote o caminho.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pdf-ocr")

# ---------------------------------------------------------------------------
# Pastas do projeto
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
PDF_DIR = PROJECT_ROOT / "pdf"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Validação de dependências externas
# ---------------------------------------------------------------------------
DEPENDENCY_HELP = """
================================================================================
  DEPENDENCIAS EXTERNAS NECESSARIAS

  1. Poppler (para pdf2image converter PDF -> imagem)
     -> Download: https://github.com/oschwartz10612/poppler-windows
     -> Extraia e adicione a pasta Library/bin ao PATH
     -> Ou configure poppler_path no script

  2. Tesseract OCR (para pytesseract)
     -> Download: https://github.com/UB-Mannheim/tesseract/wiki
     -> Instale COM suporte a portugues (por default)
     -> Adicione ao PATH ou configure tesseract_cmd no script

  Para instalar pacotes Python:
     pip install pdf2image pytesseract Pillow
================================================================================
"""


def check_dependencies() -> tuple[bool, bool]:
    """Verifica se pdftoppm (poppler) e tesseract estão acessíveis.

    Returns:
        (poppler_ok, tesseract_ok)
    """
    import shutil

    poppler_ok = shutil.which("pdftoppm") is not None
    tesseract_ok = shutil.which("tesseract") is not None

    return poppler_ok, tesseract_ok


def ensure_poppler_path(poppler_path: str | None = None) -> str | None:
    """Retorna o caminho do Poppler se configurado, ou None para PATH."""
    if poppler_path:
        resolved = Path(poppler_path).resolve()
        if resolved.is_dir():
            return str(resolved)
        log.warning("Caminho poppler_path inválido: %s", poppler_path)
    return None


# ---------------------------------------------------------------------------
# 1. Busca de PDFs
# ---------------------------------------------------------------------------
def find_pdf_files() -> list[Path]:
    """Procura arquivos .pdf nas pastas `pdf/` e (fallback) `data/`.

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
    """Converte string como '1-5, 7, 10-12' em lista de páginas 1‑indexed.

    A lista retornada é deduplicada e ordenada.
    Páginas fora de [1, total_pages] são ignoradas com aviso.
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


def ask_pages(total_pages: int) -> list[int]:
    """Pergunta interativamente quais páginas converter."""
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


# ---------------------------------------------------------------------------
# 4. Conversão PDF → Imagens
# ---------------------------------------------------------------------------
def convert_pages_to_images(
    pdf_path: Path,
    pages: list[int],
    output_dir: Path,
    dpi: int = 300,
    poppler_path: str | None = None,
) -> list[Path]:
    """Converte páginas selecionadas do PDF para PNG.

    Converte página por página (first_page/last_page) para eficiência.

    Args:
        pdf_path: Caminho do PDF.
        pages: Lista 1-indexed de páginas.
        output_dir: Diretório onde salvar as imagens.
        dpi: Resolução da conversão (default 300).
        poppler_path: Caminho da pasta bin do Poppler (ou None para PATH).

    Returns:
        Lista de paths das imagens geradas.
    """
    from pdf2image import convert_from_path

    image_paths: list[Path] = []
    log.info(
        "Convertendo %d pagina(s) para imagens (%d DPI)...",
        len(pages),
        dpi,
    )

    for page in pages:
        page_images = convert_from_path(
            pdf_path=str(pdf_path),
            dpi=dpi,
            first_page=page,
            last_page=page,
            fmt="png",
            poppler_path=poppler_path,
        )
        if not page_images:
            log.warning("Pagina %d: conversao gerou imagem vazia.", page)
            continue

        out_path = output_dir / f"pagina_{page:04d}.png"
        page_images[0].save(str(out_path), "PNG")
        image_paths.append(out_path)
        log.info("  Pagina %d salva: %s", page, out_path.name)

    log.info("Conversao concluida: %d imagem(ns) em '%s/'", len(image_paths), output_dir.name)
    return image_paths


# ---------------------------------------------------------------------------
# 5. OCR com preservação de layout
# ---------------------------------------------------------------------------
def ocr_image_with_layout(
    image_path: Path,
    lang: str = "por",
    psm: int = 6,
    tessdata_dir: str | None = None,
    tesseract_cmd: str | None = None,
) -> str:
    """Aplica OCR em uma imagem e retorna o texto com layout preservado.

    A estratégia de layout usa `image_to_data()` para obter coordenadas
    de cada palavra e reconstruir o texto com indentação, parágrafos e
    colunas aproximados.

    Args:
        image_path: Caminho da imagem PNG.
        lang: Código do idioma (padrão 'por' = português).
        psm: Modo de segmentação do Tesseract.
              6 = bloco uniforme (ideal para textos limpos)
              3 = automático sem OSD
              1 = automático com OSD
              4 = coluna única
        tessdata_dir: Caminho para tessdata (se não estiver no PATH).
        tesseract_cmd: Caminho do executável tesseract.

    Returns:
        Texto extraído com layout preservado.
    """
    from PIL import Image
    import pytesseract
    from pytesseract import Output

    # Configurar caminho do executável, se fornecido
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # Montar configuração do Tesseract
    config = f"--psm {psm}"
    if tessdata_dir:
        config += f" --tessdata-dir {tessdata_dir}"

    img = Image.open(str(image_path))

    # ── Abordagem 1: image_to_data (melhor para layout) ──
    try:
        data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=Output.DICT)
    except Exception as exc:
        log.warning("OCR com image_to_data falhou (%s); tentando fallback…", exc)
        data = None

    if data and data.get("text"):
        return _reconstruct_layout(data)

    # ── Abordagem 2 (fallback): image_to_string ──
    log.info("  Usando fallback image_to_string para %s", image_path.name)
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    # Remove caracteres de controle estranhos mas mantém \n
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def _reconstruct_layout(data: dict) -> str:
    """Versão aprimorada da reconstrução de layout.

    Usa o bloco e parágrafo do Tesseract para agrupar e preservar
    estrutura de parágrafos, listas e colunas.
    """
    from collections import defaultdict

    n = len(data["level"])

    # Estrutura: block -> para -> line -> [(left, word)]
    blocks: dict[int, dict[int, dict[int, list[tuple[int, str]]]]] = (
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
        blocks[block][para][line].append((left, word))

    text_parts: list[str] = []

    # Ordenar blocos por posição Y (pegar o y médio)
    block_order = sorted(
        blocks.keys(),
        key=lambda b: _block_median_y(data, b),
    )

    for block in block_order:
        paras = blocks[block]
        para_order = sorted(paras.keys())

        for pi, para in enumerate(para_order):
            lines = paras[para]
            line_order = sorted(lines.keys())

            for li, line in enumerate(line_order):
                words = lines[line]
                words.sort(key=lambda x: x[0])  # ordenar por X
                line_text = " ".join(w for _, w in words)
                text_parts.append(line_text)

            # Espaço entre parágrafos dentro do mesmo bloco
            if pi < len(para_order) - 1:
                text_parts.append("")

        # Espaço entre blocos (como um separador de página)
        text_parts.append("")
        text_parts.append("")

    return "\n".join(text_parts).strip()


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


# ---------------------------------------------------------------------------
# 6. Pós-processamento do texto
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Limpeza básica do texto OCR."""
    # Remover linhas que são só espaços/tabs
    lines = text.split("\n")
    cleaned = [line.rstrip() for line in lines]
    # Remover linhas duplicadas consecutivas vazias (máx 2 seguidas)
    result: list[str] = []
    empty_count = 0
    for line in cleaned:
        if line == "":
            empty_count += 1
            if empty_count <= 2:
                result.append(line)
        else:
            empty_count = 0
            result.append(line)
    return "\n".join(result).strip()


# ---------------------------------------------------------------------------
# 7. Pipeline principal
# ---------------------------------------------------------------------------
def run_pipeline(
    pdf_path: Path,
    pages: list[int],
    dpi: int = 300,
    lang: str = "por",
    psm: int = 6,
    output_txt: Path | None = None,
    poppler_path: str | None = None,
    tessdata_dir: str | None = None,
    tesseract_cmd: str | None = None,
    keep_images: bool = True,
) -> Path:
    """Executa o pipeline completo: PDF → imagens → OCR → TXT.

    Returns:
        Path do arquivo .txt gerado.
    """
    # 4. Converter páginas para imagens
    images = convert_pages_to_images(
        pdf_path=pdf_path,
        pages=pages,
        output_dir=DATA_DIR,
        dpi=dpi,
        poppler_path=poppler_path,
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
        try:
            text = ocr_image_with_layout(
                image_path=img_path,
                lang=lang,
                psm=psm,
                tessdata_dir=tessdata_dir,
                tesseract_cmd=tesseract_cmd,
            )
            text = clean_text(text)
            if text:
                # Mostrar preview
                preview = text[:200].replace("\n", " | ")
                print(f"  Preview: {preview}{'...' if len(text) > 200 else ''}")
            else:
                print("  (texto vazio ou ilegível)")
        except Exception as exc:
            log.error("Falha no OCR da página %d: %s", page_num, exc)
            text = f"[ERRO NA PÁGINA {page_num}: {exc}]"

        # Cabeçalho da página no resultado final
        page_header = f"\n{'='*70}\nPÁGINA {page_num}\n{'='*70}\n"
        all_text_parts.append(page_header + text + "\n")

    # 6. Gerar arquivo TXT
    if output_txt is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_txt = DATA_DIR / f"ocr_{pdf_path.stem}_{timestamp}.txt"

    full_text = "".join(all_text_parts)
    output_txt.write_text(full_text, encoding="utf-8")
    log.info("Arquivo TXT gerado: %s (%d caracteres)", output_txt, len(full_text))

    # Limpar imagens intermediárias (opcional)
    if not keep_images:
        for img_path in images:
            img_path.unlink(missing_ok=True)
        log.info("Imagens intermediárias removidas (--no-keep-images).")
    else:
        log.info("Imagens mantidas em '%s/'", DATA_DIR.name)

    return output_txt


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
        default=6,
        choices=[1, 3, 4, 6],
        help=(
            "Modo de segmentação Tesseract (default: 6):\n"
            "  1 = automático com OSD\n"
            "  3 = automático sem OSD\n"
            "  4 = coluna única\n"
            "  6 = bloco uniforme (recomendado)"
        ),
    )
    parser.add_argument(
        "--poppler-path",
        help="Caminho da pasta bin do Poppler (ex: C:/poppler/Library/bin)",
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
    # Forcar UTF-8 na saida do terminal (Windows cp1252 nao suporta Unicode)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args()

    # ── Auto-detecção de dependências comuns ──
    if not args.poppler_path:
        candidates_poppler = [
            PROJECT_ROOT / ".deps" / "poppler" / "Library" / "bin",
            Path("C:/poppler/Library/bin"),
            Path("C:/Program Files/poppler/Library/bin"),
        ]
        for p in candidates_poppler:
            if p.is_dir() and (p / "pdftoppm.exe").is_file():
                args.poppler_path = str(p.resolve())
                log.info("Poppler auto-detectado em: %s", args.poppler_path)
                break

    if not args.tesseract_cmd:
        candidates_tesseract = [
            Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
            Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
            PROJECT_ROOT / ".deps" / "tesseract" / "tesseract.exe",
        ]
        for c in candidates_tesseract:
            if c.is_file():
                args.tesseract_cmd = str(c.resolve())
                log.info("Tesseract auto-detectado em: %s", args.tesseract_cmd)
                break

    # ── Apenas check de dependências ──
    if args.check_deps:
        poppler_ok, tesseract_ok = check_dependencies()
        print("\n[CHECK] Verificacao de dependencias:\n")
        print(f"  Poppler (pdftoppm):  {'[OK]' if poppler_ok else '[FALTA] NAO ENCONTRADO'}")
        print(f"  Tesseract:           {'[OK]' if tesseract_ok else '[FALTA] NAO ENCONTRADO'}")
        if args.poppler_path:
            print(f"  Poppler (--poppler-path): {args.poppler_path}")
        if args.tesseract_cmd:
            print(f"  Tesseract (--tesseract-cmd): {args.tesseract_cmd}")
        if not poppler_ok and not args.poppler_path:
            print(DEPENDENCY_HELP)
        if not tesseract_ok and not args.tesseract_cmd:
            print(DEPENDENCY_HELP)
        sys.exit(0 if (poppler_ok or args.poppler_path) and (tesseract_ok or args.tesseract_cmd) else 1)

    # ── Verificar dependências ──
    poppler_ok, tesseract_ok = check_dependencies()
    if not poppler_ok and not args.poppler_path:
        log.error("Poppler não encontrado no PATH nem em locais comuns.")
        print(DEPENDENCY_HELP)
        sys.exit(1)
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
            # Garantir que a pasta pdf/ existe com instrução
            PDF_DIR.mkdir(exist_ok=True)
            print(f"\n  A pasta '{PDF_DIR.name}/' foi criada.")
            print(f"     Coloque seus PDFs lá e execute novamente.")
            sys.exit(1)

        if len(pdfs) == 1:
            pdf_path = pdfs[0]
            log.info("PDF único encontrado: %s", pdf_path.name)
        else:
            pdf_path = select_pdf(pdfs)

    # ── 2. Obter número de páginas ──
    try:
        from pdf2image import pdfinfo_from_path

        info = pdfinfo_from_path(
            str(pdf_path),
            poppler_path=ensure_poppler_path(args.poppler_path),
        )
        total_pages = info["Pages"]
    except Exception as exc:
        log.warning("Não foi possível detectar número de páginas: %s", exc)
        # Fallback: contar convertendo 1 página
        total_pages = 0  # sera ignorado

    # ── 3. Selecionar páginas ──
    if args.pages:
        if args.pages.lower() == "all":
            if total_pages == 0:
                log.error("Use --pages 'all' requer detecção automática de páginas.")
                sys.exit(1)
            pages = list(range(1, total_pages + 1))
        else:
            if total_pages == 0:
                # Tentou detectar e falhou; converte string mas sem validação de range
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

    # ── Executar pipeline ──
    log.info(
        "Iniciando pipeline: %s | %d página(s) | lang=%s | psm=%d | dpi=%d",
        pdf_path.name,
        len(pages),
        args.lang,
        args.psm,
        args.dpi,
    )

    try:
        output = run_pipeline(
            pdf_path=pdf_path,
            pages=pages,
            dpi=args.dpi,
            lang=args.lang,
            psm=args.psm,
            output_txt=args.output,
            poppler_path=ensure_poppler_path(args.poppler_path),
            tessdata_dir=args.tessdata_dir,
            tesseract_cmd=args.tesseract_cmd,
            keep_images=args.keep_images,
        )
        print(f"\n[OK] OCR concluido! Arquivo: {output}")
    except Exception as exc:
        log.exception("Falha no pipeline: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
