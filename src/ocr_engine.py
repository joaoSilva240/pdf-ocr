"""
Motor de OCR: funções para extrair texto de imagens.

Fornece:
  - ocr_image_with_layout(): OCR com preservação de layout.
  - ocr_image_multi_pass(): OCR em duas passadas (c/ e s/ preprocessing).
  - clean_text(): pós-processamento para remover ruído.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.image_processing import preprocess_image
from src.layout_reconstructor import reconstruct_layout

log = logging.getLogger("pdf-ocr")


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

    from PIL import Image

    # Configurar caminho do executável, se fornecido
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # Montar configuração do Tesseract
    config = f"--psm {psm}"
    if tessdata_dir:
        config += f" --tessdata-dir {tessdata_dir}"

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
        data = pytesseract.image_to_data(
            img, lang=lang, config=config, output_type=Output.DICT
        )
    except Exception as exc:
        log.warning("OCR com image_to_data falhou (%s); tentando fallback…", exc)
        data = None

    if data and data.get("text"):
        return reconstruct_layout(data, auto_columns=auto_columns)

    # ── Abordagem 2 (fallback): image_to_string ──
    log.info("  Usando fallback image_to_string para %s", image_path.name)
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


# ---------------------------------------------------------------------------
# 5C. Multi-pass OCR (títulos decorativos + corpo do texto)
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
        l.strip() for l in lines_full if l.strip() and len(l.strip()) <= 40
    }

    def _is_noise(line: str) -> bool:
        """Retorna True se a linha parece ruído (não texto válido)."""
        s = line.strip()
        if len(s) < 4:
            return True
        # Conta caracteres alfanuméricos
        alpha = sum(
            1
            for c in s
            if c.isalnum()
            or c
            in "áéíóúâêîôûãõàçÀÁÉÍÓÚÂÊÎÔÛÃÕÇüÜñÑ"
        )
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
            1
            for c in line
            if c.isalnum()
            or unicodedata.category(c) in ("Ll", "Lu", "Lt", "Lo", "Nd")
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
