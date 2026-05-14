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
"""

from __future__ import annotations

import argparse
import logging
import os
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
  DEPENDENCIA EXTERNA NECESSARIA

  Tesseract OCR (para pytesseract)
    -> Download: https://github.com/UB-Mannheim/tesseract/wiki
    -> Instale COM suporte a portugues (por default)
    -> Adicione ao PATH ou configure tesseract_cmd no script

  Para instalar pacotes Python:
     uv sync
================================================================================
"""


# ---------------------------------------------------------------------------
# Pré-processamento de imagem (Opção A)
# ---------------------------------------------------------------------------
def preprocess_image(
    image: Image.Image,
    binarize: bool = True,
    denoise: bool = True,
    contrast_boost: float = 1.8,
) -> Image.Image:
    """Melhora a imagem antes do OCR para aumentar a taxa de acerto.

    Etapas:
      1. Escala de cinza (remove interferência de cor)
      2. Auto‑contraste (equaliza histograma para separar texto do fundo)
      3. Sharpen (realça bordas das letras)
      4. Binarização adaptativa (preto e branco)
      5. Remoção de ruído (filtro mediano)

    Args:
        image: Imagem PIL original.
        binarize: Se True, converte para preto e branco.
        denoise: Se True, aplica filtro mediano.
        contrast_boost: Fator de aumento de contraste (1.0 = original).

    Returns:
        Imagem processada.
    """
    from PIL import ImageEnhance, ImageFilter, ImageOps

    # 1. Escala de cinza
    img = image.convert("L")

    # 2. Auto‑contraste: corta 2% de cada extremidade para evitar ruído
    img = ImageOps.autocontrast(img, cutoff=2)

    # 3. Aumento de contraste
    if contrast_boost != 1.0:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(contrast_boost)

    # 4. Sharpen suave para realçar bordas das letras
    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=2))

    # 5. Binarização adaptativa
    if binarize:
        # Usa o percentil 85 como threshold (mais tolerante que média simples)
        extrema = img.getextrema()
        if extrema[0] < extrema[1]:
            # Calcula um threshold que preserva traços finos
            threshold = int(extrema[0] + (extrema[1] - extrema[0]) * 0.70)
            img = img.point(lambda x: 255 if x > threshold else 0)

    # 6. Remoção de ruído (aplicada por último, depois da binarização)
    if denoise:
        img = img.filter(ImageFilter.MedianFilter(size=3))

    return img


def check_tesseract() -> bool:
    """Verifica se o tesseract está acessível no PATH."""
    import shutil
    return shutil.which("tesseract") is not None


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
    import io
    from PIL import Image

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

    log.info("Conversao concluida: %d imagem(ns) em '%s/'", len(image_paths), output_dir.name)
    return image_paths


# ---------------------------------------------------------------------------
# 5. OCR com preservação de layout
# ---------------------------------------------------------------------------
def ocr_image_with_layout(
    image_path: Path,
    lang: str = "por",
    psm: int = 3,
    tessdata_dir: str | None = None,
    tesseract_cmd: str | None = None,
    preprocess: bool = True,
    binarize: bool = True,
    denoise: bool = True,
    auto_columns: bool = True,
) -> str:
    """Aplica OCR em uma imagem e retorna o texto com layout preservado.

    Antes do OCR, aplica pré-processamento opcional (escala de cinza,
    contraste, binarização, remoção de ruído) para melhorar a acurácia.

    A estratégia de layout usa ``image_to_data()`` para obter coordenadas
    de cada palavra e reconstruir o texto com indentação, parágrafos e
    colunas aproximados.

    Args:
        image_path: Caminho da imagem PNG.
        lang: Código do idioma (padrão 'por' = português).
        psm: Modo de segmentação do Tesseract.
              3 = automático sem OSD (recomendado para layouts variados)
              6 = bloco uniforme (texto simples, uma coluna)
              4 = coluna única
              1 = automático com OSD
        tessdata_dir: Caminho para tessdata (se não estiver no PATH).
        tesseract_cmd: Caminho do executável tesseract.
        preprocess: Se True, aplica pré-processamento na imagem.
        binarize: Se True (e preprocess=True), converte para P&B.
        denoise: Se True (e preprocess=True), remove ruído.
        auto_columns: Se True, tenta detectar colunas automaticamente.

    Returns:
        Texto extraído com layout preservado.
    """
    import pytesseract
    from pytesseract import Output

    # Configurar caminho do executável, se fornecido
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # Montar configuração do Tesseract
    config = f"--psm {psm}"
    if tessdata_dir:
        config += f" --tessdata-dir {tessdata_dir}"

    from PIL import Image
    img = Image.open(str(image_path))

    # ── Pré-processamento (Opção A) ──
    if preprocess:
        img = preprocess_image(
            img,
            binarize=binarize,
            denoise=denoise,
            contrast_boost=1.5,
        )

    # ── Abordagem 1: image_to_data (melhor para layout) ──
    try:
        data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=Output.DICT)
    except Exception as exc:
        log.warning("OCR com image_to_data falhou (%s); tentando fallback…", exc)
        data = None

    if data and data.get("text"):
        return _reconstruct_layout(data, auto_columns=auto_columns)

    # ── Abordagem 2 (fallback): image_to_string ──
    log.info("  Usando fallback image_to_string para %s", image_path.name)
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def _reconstruct_layout(data: dict, auto_columns: bool = True) -> str:
    """Reconstroi o texto preservando layout e detectando colunas.

    Cada bloco detectado pelo Tesseract é classificado em uma coluna
    de acordo com sua posição horizontal. Depois as colunas são
    processadas da esquerda para a direita, cada uma de cima para baixo.

    Args:
        data: Dicionário retornado por ``image_to_data(…, Output.DICT)``.
        auto_columns: Se True, tenta detectar e agrupar colunas.

    Returns:
        Texto reconstruído com parágrafos e colunas preservados.
    """
    from collections import defaultdict

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
            page_width = max(
                data["left"][i] + data["width"][i]
                for i in range(n)
                if data["text"][i] and data["text"][i].strip()
            ) if widths else 1000

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

                            for li, line in enumerate(line_order):
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

            for li, line in enumerate(line_order):
                words = lines[line]
                words.sort(key=lambda x: x[0])
                line_text = " ".join(w for _, w in words)
                text_parts.append(line_text)

            if pi < len(para_order) - 1:
                text_parts.append("")

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
# 5B. Multi-pass OCR (títulos decorativos + corpo do texto)
# ---------------------------------------------------------------------------
def ocr_image_multi_pass(
    image_path: Path,
    lang: str = "por",
    psm: int = 3,
    tessdata_dir: str | None = None,
    tesseract_cmd: str | None = None,
    preprocess: bool = True,
    binarize: bool = True,
    denoise: bool = True,
    auto_columns: bool = True,
) -> str:
    """Executa OCR em duas passadas e mescla os resultados.

    Estratégia:
      1. **Passada 1 — corpo (com pré-processamento):**
         Imagem binarizada/limpa → captura o corpo do texto com
         máximo de acurácia. Títulos decorativos podem ser perdidos.

      2. **Passada 2 — títulos (sem pré-processamento):**
         Imagem original → preserva fontes decorativas e títulos
         que a binarização destruiria.

      3. **Mesclagem:**
         - Linhas curtas (≤ 40 caracteres) que SÓ existem na
           passada 2 são tratadas como **títulos** e inseridas.
         - Linhas que existem em ambas são deduplicadas.
         - A ordem original da passada 2 é preservada.

    Args:
        Mesmos parâmetros de ``ocr_image_with_layout``.

    Returns:
        Texto mesclado com títulos + corpo limpo.
    """
    # ── Passada 1: com pré-processamento (corpo limpo, sem títulos) ──
    text_clean = ocr_image_with_layout(
        image_path=image_path,
        lang=lang,
        psm=psm,
        tessdata_dir=tessdata_dir,
        tesseract_cmd=tesseract_cmd,
        preprocess=True,
        binarize=binarize,
        denoise=denoise,
        auto_columns=auto_columns,
    )

    # ── Passada 2: sem pré-processamento (títulos preservados) ──
    text_full = ocr_image_with_layout(
        image_path=image_path,
        lang=lang,
        psm=psm,
        tessdata_dir=tessdata_dir,
        tesseract_cmd=tesseract_cmd,
        preprocess=False,
        binarize=False,
        denoise=False,
        auto_columns=auto_columns,
    )

    # ── Mesclagem inteligente ──
    return _merge_ocr_passes(text_clean, text_full)


def _merge_ocr_passes(text_clean: str, text_full: str) -> str:
    """Mescla texto limpo (pass 1) com texto completo (pass 2).

    Estratégia:
      - Linhas que existem em ambos os textos → usa versão do
        texto limpo (pass 1), que tem menos ruído.
      - Linhas curtas (≤ 40 chars) que SÓ existem na pass 2
        → consideradas títulos decorativos → mantidas.
      - Linhas muito curtas (< 4 chars) ou com alta densidade
        de caracteres especiais são descartadas (ruído).
    """
    import unicodedata

    lines_clean = [l.rstrip() for l in text_clean.split("\n")]
    lines_full = [l.rstrip() for l in text_full.split("\n")]

    # Conjuntos para consulta rápida
    set_clean_lines = {l for l in lines_clean if l.strip()}
    set_clean_stripped = {l.strip() for l in lines_clean if l.strip()}

    # Linhas curtas na pass 2 (candidatas a título)
    short_full = {
        l.strip() for l in lines_full
        if l.strip() and len(l.strip()) <= 40
    }

    def _is_noise(line: str) -> bool:
        """Retorna True se a linha parece ruído (não texto válido)."""
        s = line.strip()
        if len(s) < 4:
            return True
        # Conta caracteres alfanuméricos
        alpha = sum(1 for c in s if c.isalnum() or c in "áéíóúâêîôûãõàçÀÁÉÍÓÚÂÊÎÔÛÃÕÇüÜñÑ")
        return (alpha / len(s)) < 0.4 if len(s) > 0 else True

    result: list[str] = []
    seen: set[str] = set()

    for line in lines_full:
        key = line.strip()
        if not key:
            result.append(line)
            continue

        # Pular ruído óbvio
        if _is_noise(key):
            continue

        # Título decorativo: curto, só existe na pass 2
        is_title = (
            len(key) <= 40
            and key not in set_clean_stripped
            and key in short_full
        )

        if key in set_clean_stripped and not is_title:
            # Linha existe nos dois textos → usa versão do texto limpo
            if key not in seen:
                # Encontra a versão correspondente em text_clean
                for cl in lines_clean:
                    if cl.strip() == key and cl.strip() not in seen:
                        result.append(cl)
                        seen.add(cl.strip())
                        break
            continue

        # Linha nova (título ou texto que pass 1 não capturou)
        if key not in seen:
            result.append(line)
            seen.add(key)

    return "\n".join(result)


# ---------------------------------------------------------------------------
# 6. Pós-processamento do texto
# ---------------------------------------------------------------------------
def clean_text(text: str, min_alpha_ratio: float = 0.3) -> str:
    """Limpeza do texto OCR: remove ruído e linhas de lixo.

    Estratégias:
      1. Linhas com baixa densidade de caracteres alfanuméricos são descartadas.
      2. Espaços duplicados no início/fim são removidos.
      3. Máximo de 2 linhas vazias consecutivas.

    Args:
        text: Texto bruto do OCR.
        min_alpha_ratio: Proporção mínima de letras/números para
            considerar a linha válida (default 0.3 = 30%).

    Returns:
        Texto limpo.
    """
    import unicodedata

    lines = text.split("\n")
    cleaned: list[str] = []

    # Contador de linhas vazias consecutivas
    empty_count = 0

    for raw_line in lines:
        line = raw_line.rstrip()

        # ── Linha vazia ──
        if not line:
            empty_count += 1
            if empty_count <= 2:
                cleaned.append(line)
            continue

        empty_count = 0

        # ── Pular linhas que são apenas separadores visuais ──
        if re.match(r"^[\s=\-_\|\.\,\:\;]+$", line):
            continue

        # ── Pular linhas com alta densidade de caracteres especiais ──
        # Conta caracteres alfanuméricos (letras com acento inclusas)
        alpha_count = sum(
            1 for c in line
            if c.isalnum() or unicodedata.category(c) in ("Ll", "Lu", "Lt", "Lo", "Nd")
        )
        total_visible = sum(1 for c in line if not c.isspace())

        if total_visible > 0 and (alpha_count / total_visible) < min_alpha_ratio:
            continue

        # ── Linha válida ──
        cleaned.append(line)

    # Junta e remove espaços/tabs duplicados dentro das linhas
    result = "\n".join(cleaned)
    result = re.sub(r"[ \t]+", " ", result)
    return result.strip()


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
    use_cache: bool = True,
) -> Path:
    """Executa o pipeline completo: PDF → imagens → OCR → TXT.

    Args:
        preprocess: Aplica pré-processamento na imagem antes do OCR.
        binarize: Converte para preto e branco.
        denoise: Remove ruído com filtro mediano.
        auto_columns: Tenta detectar colunas no layout.
        multi_pass: Se True, roda OCR em 2 passadas (c/ e s/ preprocess)
                    e mescla para capturar títulos decorativos.
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
        try:
            if multi_pass:
                text = ocr_image_multi_pass(
                    image_path=img_path,
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
                    image_path=img_path,
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

    # ── Auto-detecção do Tesseract ──
    # Prioridade: 1) CLI args  2) variável de ambiente  3) caminhos fixos
    if not args.tesseract_cmd:
        env_tesseract = os.environ.get("TESSERACT_CMD")
        if env_tesseract:
            c = Path(env_tesseract)
            if c.is_file():
                args.tesseract_cmd = str(c.resolve())
                log.info("Tesseract via TESSERACT_CMD: %s", args.tesseract_cmd)

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
        tesseract_ok = check_tesseract()
        print("\n[CHECK] Verificacao de dependencias:\n")
        print(f"  Tesseract:           {'[OK]' if tesseract_ok else '[FALTA] NAO ENCONTRADO'}")
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

    # Flags (--no-* invertem o default True)
    preprocess = not args.no_preprocess
    binarize = not args.no_binarize
    denoise = not args.no_denoise
    auto_columns = not args.no_auto_columns
    multi_pass = not args.no_multi_pass

    if preprocess:
        log.info(
            "Pré-processamento: binarizar=%s | remover ruído=%s",
            binarize,
            denoise,
        )
    else:
        log.info("Pré-processamento desligado.")
    log.info("Detecção de colunas: %s", "ligada" if auto_columns else "desligada")
    log.info("Multi-pass OCR: %s", "ligado" if multi_pass else "desligado")

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
            use_cache=True,
        )
        print(f"\n[OK] OCR concluido! Arquivo: {output}")
    except Exception as exc:
        log.exception("Falha no pipeline: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
