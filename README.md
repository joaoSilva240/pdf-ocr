# PDF-OCR

Converte PDFs em texto usando OCR com **preservação de layout**.

## Fluxo

```
  pdf/          data/                  saida/
  ┌────┐       ┌──────┐               ┌──────┐
  │.pdf│ ──►   │.png  │ ──► OCR ──►   │.txt  │
  └────┘       └──────┘               └──────┘
  (input)      (imagens)              (resultado)
```

1. **Busca** PDFs na pasta `pdf/` (fallback: `data/`)
2. **Pergunta** quais páginas converter (ex: `1-5, 7, 10-12` ou `all`)
3. **Converte** páginas selecionadas para PNG em `data/` (via pdf2image)
4. **Aplica OCR** com pytesseract (tenta preservar parágrafos e colunas)
5. **Gera** arquivo `.txt` no diretório raiz do projeto

## Dependências externas

### 1. Python

```bash
pip install pdf2image pytesseract Pillow
```

### 2. Poppler (para pdf2image converter PDF → imagem)

- Download: https://github.com/oschwartz10612/poppler-windows
- Extraia e adicione a pasta `Library/bin` ao PATH
- Ou use `--poppler-path` apontando para a pasta bin

### 3. Tesseract OCR (para pytesseract)

- Download: https://github.com/UB-Mannheim/tesseract/wiki
- Instale **COM suporte a Português (Brasil)** marcado
- Ou use `--tesseract-cmd` apontando para o executável

> **Setup automático**: Execute `setup.bat` para baixar e configurar
> Poppler + Tesseract automaticamente.

## Uso

### Modo interativo (recomendado)

```bash
python main.py
```

Coloque os PDFs na pasta `pdf/` e o script guiará o resto.

### Modo CLI (argumentos diretos)

```bash
python main.py --pdf documento.pdf --pages 1-10
python main.py --pdf doc.pdf --pages "1-5, 7, 10-12" --lang por
python main.py --pdf doc.pdf --pages all --dpi 400
```

### Caminhos manuais (sem PATH)

```bash
python main.py ^
    --poppler-path "C:\poppler\Library\bin" ^
    --tesseract-cmd "C:\Tesseract-OCR\tesseract.exe"
```

### Opções

| Flag              | Default | Descrição                                      |
|-------------------|---------|------------------------------------------------|
| `--pdf`           | auto    | Caminho do PDF (opcional, busca em pdf/)       |
| `--pages`         | pergunta| Páginas: `1-5,7` / `all`                       |
| `-o` / `--output` | auto    | Arquivo .txt de saída                          |
| `--dpi`           | 300     | Resolução da conversão PDF → imagem            |
| `--lang`          | por     | Idioma do OCR (`por`, `eng`, `por+eng`)        |
| `--psm`           | 6       | Segmentação: 1=auto, 3=sem OSD, 4=coluna, 6=bloco |
| `--poppler-path`  | PATH    | Caminho da pasta bin do Poppler                |
| `--tesseract-cmd` | PATH    | Caminho do executável Tesseract                |
| `--no-keep-images`| mantém  | Remove imagens intermediárias após OCR         |
| `--check-deps`    | -       | Apenas verifica dependências e sai             |

## Exemplos de segmentação (--psm)

| PSM | Uso recomendado                               |
|-----|-----------------------------------------------|
| 1   | Documentos complexos com OSD automático       |
| 3   | Totalmente automático, sem OSD                |
| 4   | Coluna única de texto                         |
| **6**| **Bloco uniforme de texto (default, ideal)** |

## Estrutura do projeto

```
pdf-ocr/
├── main.py           # Script principal
├── setup.bat         # Download automático de Poppler + Tesseract
├── run.bat           # Atalho para executar com caminhos do setup
├── pyproject.toml    # Dependências Python
├── pdf/              # Coloque seus PDFs aqui
├── data/             # Imagens PNG (geradas) + PDFs fallback
├── .deps/            # Dependências baixadas (via setup.bat)
└── ocr_*.txt         # Resultado do OCR (gerado)
```
