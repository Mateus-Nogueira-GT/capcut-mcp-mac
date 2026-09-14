# capcut-mcp-mac

Adaptador MCP (camada L1) que gera projetos do CapCut Desktop no macOS, sobre o
VectCutAPI (L0) fixado como submodule em `b83be74` e **nunca modificado**.

## Por que existe

O caminho MCP do upstream não serve como está no macOS:

- `capcut_server.py` / `web_preview.py` não importam (`ctypes.windll`);
- o perfil `capcut_legacy` gera projetos que o CapCut 9.x **lista mas recusa abrir**;
- `save_draft` de um draft ausente retorna sucesso sem escrever nada;
- o stdout do L0, onde vão todos os avisos, é descartado.

Este adaptador corrige isso numa camada só, preservando o upstream intacto.

## Uso

```sh
git submodule update --init --recursive
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r vendor/VectCutAPI/requirements.txt
PYTHONPATH=src ./.venv/bin/python -m capcut_mcp.server   # fala MCP por stdio
```

Requer FFmpeg (`brew install ffmpeg`), CapCut Desktop instalado, e **pelo menos um
projeto criado à mão** no CapCut — ele serve de esqueleto real da sua versão.

## Escopo

Cortar vídeo, legendar, e colocar textos em momentos pré-determinados. Nada além disso.

## Tools expostas (9)

| Tool | O que faz |
|---|---|
| `capcut.system.doctor` | Diagnóstico: versão do app, diretório de drafts, projeto de referência, ffprobe, disco |
| `capcut.media.probe` | Duração, dimensões e formato reais, via ffprobe, em lote |
| `capcut.draft.create` | Cria o draft e devolve o `draft_id` |
| `capcut.video.cut` | Corta declarando os trechos que **ficam**: `keep=[[0,3],[5,8]]` |
| `capcut.subtitle.add` | Legendas de SRT (arquivo, URL ou inline) ou de `segments=[{start,end,text}]` |
| `capcut.text.add` | Um texto, com estilo completo |
| `capcut.text.add_many` | Vários textos em momentos pré-determinados, estilo compartilhado |
| `capcut.draft.validate` | 11 regras de verificação antes de gravar |
| `capcut.draft.save` | Valida e grava no formato multi-timeline que o CapCut 9.x exige |

**Não existe:** editar, mover ou remover segmento já adicionado; imagem, áudio,
efeitos, transições e keyframes; renderizar vídeo; recarregar o CapCut.

Imagem, áudio, catálogos, `inspect` e `rebuild` continuam **implementados e testados**,
fora da superfície MCP. Para expô-los: `CAPCUT_ENABLE_ALL_TOOLS=1`.

## Testes

```sh
./.venv/bin/python -m pytest tests/ -q
```
