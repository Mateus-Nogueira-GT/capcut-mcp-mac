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
git clone --recurse-submodules <este repositório> && cd capcut-mcp-mac
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
PYTHONPATH=src ./.venv/bin/python -m capcut_mcp.server   # fala MCP por stdio
```

Se clonou sem `--recurse-submodules`, rode `git submodule update --init
--recursive` antes — sem o L0 em `vendor/VectCutAPI` nada importa.

Requer FFmpeg (`brew install ffmpeg`), CapCut Desktop instalado, e **pelo menos um
projeto criado à mão** no CapCut — ele serve de esqueleto real da sua versão.

Para transcrever, também `brew install whisper-cpp` e um modelo baixado em
`~/Library/Application Support/capcut-mcp/models/`. O `capcut.system.doctor` diz
o que falta e o comando exato. A transcrição roda **local**: nada sai da máquina.

## Escopo

Transcrever a fala, cortar vídeo, legendar e colocar textos em momentos
pré-determinados. Nada além disso.

## Tools expostas (11)

| Tool | O que faz |
|---|---|
| `capcut.system.doctor` | Diagnóstico: versão do app, diretório de drafts, projeto de referência, ffprobe, disco, whisper.cpp e modelos |
| `capcut.media.probe` | Duração, dimensões e formato reais, via ffprobe, em lote |
| `capcut.media.transcribe` | Transcreve a fala com timestamps (whisper.cpp local), com cache e paginação |
| `capcut.draft.create` | Cria o draft e devolve o `draft_id` |
| `capcut.video.cut` | Corta declarando os trechos que **ficam**: `keep=[[0,3],[5,8]]`; `snap="speech"` não parte palavra |
| `capcut.subtitle.add` | Legendas de SRT (arquivo, URL ou inline) ou de `segments=[{start,end,text}]` |
| `capcut.subtitle.from_transcript` | Legendas do transcript **remapeadas** para a timeline cortada |
| `capcut.text.add` | Um texto, com estilo completo |
| `capcut.text.add_many` | Vários textos em momentos pré-determinados, estilo compartilhado |
| `capcut.draft.validate` | 13 regras de verificação antes de gravar |
| `capcut.draft.save` | Valida e grava no formato multi-timeline que o CapCut 9.x exige |

### A armadilha de tempo, que vale ler antes de usar

O transcript está em tempo da **mídia original**. Depois de um corte, a timeline
tem outros tempos. Passar os blocos do `transcribe` direto para o `subtitle.add`
produz legenda dessincronizada **com JSON perfeitamente válido** — nada acusa.
Por isso existe o `from_transcript`, que remapeia, descarta o que caiu em trecho
removido e conta quantos. O `validate` avisa (`V_CAPTION_DESYNC_RISK`) quando há
corte e legenda que não passou por ele.

**Não existe:** editar, mover ou remover segmento já adicionado; imagem, áudio,
efeitos, transições e keyframes; renderizar vídeo; recarregar o CapCut. A
**escolha** dos trechos também não é da ferramenta: ela transcreve e corta o que
você pedir — o critério está nas `instructions` do servidor.

Imagem, áudio, catálogos, `inspect` e `rebuild` continuam **implementados e testados**,
fora da superfície MCP. Para expô-los: `CAPCUT_ENABLE_ALL_TOOLS=1`.

## Front local (chat + anexo de vídeo)

```sh
uv pip install --python .venv/bin/python -r web/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
PYTHONPATH=src ./.venv/bin/python web/app.py     # http://127.0.0.1:5151
```

Interface de chat: anexa o vídeo, escreve o pedido, e a tela mostra cada tool que
rodou com o resultado e os avisos. **Roda local, em `127.0.0.1` só** — ele escreve
na pasta de projetos do CapCut desta máquina.

**Não há OAuth do CapCut**, e não é limitação de esforço: a plataforma aberta deles
é para plugins que rodam dentro do editor, e a API pública é de texto-para-vídeo e
templates. Como o adaptador entrega projeto **escrevendo arquivos no disco local**,
um servidor hospedado não alcançaria o Mac de outra pessoa de qualquer forma. Cada
pessoa roda o front na sua máquina, onde o CapCut dela já está logado.

A transcrição é local e grátis; a LLM é paga e serve para **escolher** os trechos.
Medido: ~$0,37 por vídeo de 30 min no Opus 5 com cache de prompt (~$0,15 no
Sonnet 5). Detalhes, tabela por duração e o desenho em [web/LEIA.md](web/LEIA.md).

## Testes

```sh
PYTHONPATH=src ./.venv/bin/python -m pytest tests/ -q
```

220 testes. Os que gravam de verdade exigem espaço em disco proporcional aos
assets (piso de 512 MiB), senão o guarda `DISK_FULL` os reprova de propósito.
Medições e verificações visuais ficam em `evidence/`.
