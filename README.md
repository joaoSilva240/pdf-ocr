# PDF-OCR

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Tesseract%20OCR-5.5-008080?style=for-the-badge&logo=tesseract&logoColor=white" />
  <img src="https://img.shields.io/badge/PyMuPDF-1.27-0B0B0B?style=for-the-badge&logo=readthedocs&logoColor=white" />
  <img src="https://img.shields.io/badge/uv-0.9-5391FE?style=for-the-badge&logo=uv&logoColor=white" />
  <br>
  <img src="https://img.shields.io/badge/OCR-pytesseract-00B4AB?style=flat-square" />
  <img src="https://img.shields.io/badge/Layout-OpenCV%20%7C%20Pandas-5C3EE8?style=flat-square" />
  <img src="https://img.shields.io/badge/PDF-PyMuPDF-800000?style=flat-square" />
</p>

Converte PDFs em texto usando OCR com **preservação de layout**, **detecção de colunas**, **multi-pass para títulos decorativos** e **formatação de tabelas**.

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
3. **Converte** páginas selecionadas para PNG em `data/` (via PyMuPDF)
4. **Aplica OCR** com pytesseract (multi-pass, colunas, tabelas)
5. **Gera** arquivo `.txt` na pasta `data/`

## Dependência externa

Apenas **Tesseract OCR** (para pytesseract):

- Download: https://github.com/UB-Mannheim/tesseract/wiki
- Instale **COM suporte a Português (Brasil)** marcado
- Ou use `--tesseract-cmd` apontando para o executável

> Setup automático: execute `setup.bat` para configurar o ambiente com uv.

## Uso

### Modo interativo (recomendado)

```bash
uv run main.py
```

Coloque os PDFs na pasta `pdf/` e o script guiará o resto.

### Modo CLI (argumentos diretos)

```bash
uv run main.py --pdf documento.pdf --pages 1-10
uv run main.py --pdf doc.pdf --pages "1-5, 7, 10-12" --lang por
uv run main.py --pdf doc.pdf --pages all --dpi 400
```

### Via atalho

```bash
run.bat
```

## Flags de ativação

| Flag | Default | Descrição |
|------|---------|-----------|
| **Entrada/Saída** | | |
| `--pdf CAMINHO` | auto | Caminho do PDF (busca em `pdf/` se omitido) |
| `--pages "1-5,7"` | pergunta | Páginas para converter ou `all` |
| `-o` / `--output` | auto | Arquivo .txt de saída |
| | | |
| **Qualidade do OCR** | | |
| `--dpi` | 300 | Resolução da conversão PDF → imagem |
| `--lang` | por | Idioma do OCR (`por`, `eng`, `por+eng`) |
| `--psm` | 3 | Modo de segmentação Tesseract |
| | | |
| **Pré-processamento** | | |
| `--no-preprocess` | desliga | Desativa pré-processamento da imagem (escala de cinza, contraste, binarização) |
| `--no-binarize` | desliga | Desativa binarização no pré-processamento |
| `--no-denoise` | desliga | Desativa remoção de ruído no pré-processamento |
| | | |
| **Layout** | | |
| `--no-auto-columns` | desliga | Desativa detecção automática de colunas |
| `--no-multi-pass` | desliga | Desativa multi-pass OCR (usa apenas 1 passada) |
| | | |
| **Tabelas** | | |
| `--table-detect` | **ativa** 🎯 | Ativa detecção e formatação automática de tabelas |
| | | |
| **Configuração** | | |
| `--tesseract-cmd` | auto | Caminho do executável Tesseract |
| `--tessdata-dir` | auto | Caminho da pasta tessdata |
| `--check-deps` | — | Apenas verifica dependências e sai |
| `--no-keep-images` | mantém | Remove imagens intermediárias após o OCR |

## Exemplos de segmentação (--psm)

| PSM | Uso recomendado |
|-----|-----------------|
| 1 | Documentos complexos com OSD automático |
| **3** | **Automático sem OSD (default, recomendado)** |
| 4 | Coluna única de texto |
| 6 | Bloco uniforme (texto simples, uma coluna) |

## Funcionalidades especiais

### Multi-pass OCR (`--no-multi-pass` para desligar)

Roda o OCR em duas passadas:
1. **Com pré-processamento** → corpo do texto limpo
2. **Sem pré-processamento** → títulos com fontes decorativas preservados

Os resultados são mesclados automaticamente.

### Detecção de tabelas (`--table-detect` para ativar)

Analisa as coordenadas das palavras para detectar estruturas tabulares.
Quando encontra uma tabela:
1. Extrai células e formata como tabela Markdown (pipes)
2. Remove a região da tabela do OCR normal (evita duplicação)
3. Insere a tabela formatada no texto final

## Cache de páginas

As imagens PNG são cacheadas em `data/`. Se você já processou uma página, a
conversão PDF → imagem é pulada em execuções seguintes. Para forçar a
reconversão, apague os PNGs de `data/`.

## Estrutura do projeto

```
pdf-ocr/
├── main.py           # Script principal
├── setup.bat         # Configuração do ambiente (uv + dependências)
├── run.bat           # Atalho para execução
├── pyproject.toml    # Dependências Python
├── uv.lock           # Lockfile do uv
├── .env              # Variáveis de ambiente locais
├── .env.example      # Template do .env
├── pdf/              # Coloque seus PDFs aqui
├── data/             # Imagens PNG + TXTs gerados
└── .venv/            # Virtualenv gerenciado pelo uv
```
