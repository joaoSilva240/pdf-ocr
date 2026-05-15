"""
Pré-processamento de imagens para OCR.

Funções:
  - preprocess_image(): melhora a imagem antes do OCR.
"""

from __future__ import annotations

import logging

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

log = logging.getLogger("pdf-ocr")


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
