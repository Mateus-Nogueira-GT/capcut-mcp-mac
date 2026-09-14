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

## Tools (Phase 2)

| Tool | O que faz |
|---|---|
| `capcut.system.doctor` | Diagnóstico: versão do app, diretório de drafts, referência, ffprobe, disco |
| `capcut.draft.create` | Cria o draft em memória e devolve o `draft_id` |
| `capcut.draft.save` | Grava no diretório do CapCut no formato multi-timeline correto |

Não existem (e não são expostas): reordenar clipes, editar segmento, renderizar vídeo,
recarregar o CapCut.

## Testes

```sh
./.venv/bin/python -m pytest tests/ -q
```
