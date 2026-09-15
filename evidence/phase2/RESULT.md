# Phase 2 — MCP baseline · RESULTADO: **PORTÃO 1 PASSOU**

**Data:** 2026-09-14 · **Repo L1:** `capcut-mcp-mac` @ `5e7558f` · **L0:** submodule fixado em `b83be74`, intocado

---

## Situação

| Portão 1 da spec | Situação |
|---|---|
| AC1.1 — `tools/list` só as tools do inventário, schemas estritos, descrições com o que o agente não adivinha | ✅ |
| AC1.2 — nenhuma tool proibida exposta | ✅ teste automatizado |
| AC1.3 — envelope padrão, `isError` + `ok:false` | ✅ |
| AC1.4 — sem mensagem crua do Python, sem CJK, sem URL externa | ✅ teste automatizado |
| AC1.5 — handshake com o cliente MCP do Codex | ⏳ configurado; falta reiniciar o Codex e chamar as tools de lá |
| Critério de conclusão — o caminho L1 → CapCut produz projeto que abre | ✅ **verificado no app** |

**18 testes de contrato passando**, todos falando JSON-RPC com o processo pelo stdio, como o Codex faria.

### Verificação no CapCut (2026-09-14, 19:32)

| Projeto | Origem | Aparece | Abre | Conteúdo conferido |
|---|---|---|---|---|
| `VectCut MCP Content` | `deployer.save` do L1 | ✅ 00:08 | ✅ | texto "MCP" 0–3 s · vídeo 0–5 s · imagem 5–8 s · áudio 0–8 s · total `00:00:08:00` |
| `VectCut MCP Baseline` | `capcut.draft.create` + `capcut.draft.save` pelo MCP | ✅ 00:00 | ✅ | vazio; painel Detalhes do app confirma **Proporção 9:16** e **30.00fps** |

O CapCut **revarreu o diretório sozinho** e encontrou os dois projetos sem nenhuma intervenção — confirmando de novo que o `root_meta_info.json` não precisa ser escrito. Depois de abrir, o app regravou `VectCut MCP Content` e gerou miniatura própria (4.9K → 483.1K): adoção completa, não tolerância.

O painel *Detalhes* do projeto vazio é a prova mais direta de que a configuração de canvas atravessou toda a pilha: o `draft.create` recebeu 1080×1920/30fps e o app exibe "Proporção de aspecto: 9:16" e "Taxa de quadros: 30.00fps".

---

## O que foi construído

```
capcut-mcp-mac/
├── vendor/VectCutAPI        submodule @ b83be74 (L0, nunca modificado)
├── src/capcut_mcp/
│   ├── upstream.py          único ponto de import do L0 + guarda de módulos proibidos
│   ├── profile.py           detecta a instalação, deriva o perfil híbrido
│   ├── deployer.py          grava no CapCut com as 5 correções da Phase 1
│   ├── registry.py          persistência do draft + replay do plano
│   ├── obs.py               warning bus (stdout do L0 → warnings) + log JSONL
│   ├── errors.py            códigos, envelope, tradução de exceções do upstream
│   ├── tools.py             3 tools com schemas estritos
│   └── server.py            loop JSON-RPC stdio
└── tests/contract/          18 testes
```

### As 3 tools (walking skeleton, deliberadamente três)

| Tool | Papel |
|---|---|
| `capcut.system.doctor` | versão do app, diretório de drafts, projeto de referência, ffprobe, disco, projetos existentes, `ready`/`blocker` |
| `capcut.draft.create` | cria o draft em memória, devolve `draft_id`, valida dimensão e rótulo de proporção |
| `capcut.draft.save` | grava no diretório real do CapCut no formato multi-timeline, com metadados reescritos, e devolve manifest |

---

## Bug encontrado pelo próprio verificador

A primeira execução do esqueleto gerou um projeto **sem `Timelines/`** — exatamente o formato que a Phase 1 provou que o CapCut recusa abrir. Causa: eu havia escrito `inject_profile()` mas **nunca o chamava**, então `save_draft_impl` resolvia `get_draft_profile()` pelo default do upstream (`capcut_legacy`).

O manifest de verificação pós-escrita detectou (`timeline_dir: None`, warning `NO_TIMELINES_DIR`) antes de qualquer teste no app. Isso valida a decisão de a spec exigir verificação pós-escrita (O5/WI-6.12) em vez de confiar no retorno do upstream: o `save_draft_impl` reportou `success: true` para um projeto inutilizável.

---

## Decisões fechadas

| Q | Decisão | Base |
|---|---|---|
| **Q5** — save sincrono ou assíncrono? | **Sincrono.** | 1,41 s para projeto com 4 segmentos e 3 assets locais; 0,01 s vazio. Revisar se entrarem downloads remotos, que dominam o tempo. |
| **Q7** — onde fica o registry? | `~/Library/Application Support/capcut-mcp/registry.json`, escrita atômica via `os.replace` | convenção do macOS |
| **Q8** — repo próprio ou dentro do fork? | **Repo próprio** com o L0 como submodule fixado | mantém o merge do upstream trivial |

### Contrato de protocolo

- `initialize` **ecoa** a `protocolVersion` do cliente quando suportada (2025-06-18, 2025-03-26, 2024-11-05); cai para 2024-11-05 se desconhecida. O upstream fixava 2024-11-05 e ignorava o pedido.
- `prompts/list`, `resources/list`, `resources/templates/list` → lista **vazia**, não `-32601`.
- `ping` respondido.
- Erro nos dois níveis: `isError: true` no resultado MCP **e** `ok: false` no envelope.
- `instructions` no `initialize` explica o fluxo e a unidade de tempo.

---

## Verificação estrutural (sem UI)

O projeto gerado pelo caminho do L1 foi comparado com a variante B da Phase 1, que **comprovadamente abre**:

| | MCP (L1) | Baseline B (Phase 1) |
|---|---|---|
| `new_version` | 185.0.0 | 185.0.0 |
| `canvas_config.ratio` | 9:16 | 9:16 |
| `platform.app_version` | 9.4.1 | 9.4.1 |
| `draft_meta_info.draft_name` | próprio | próprio |
| `Timelines/<id>/draft_info.json` == raiz | sim | sim |
| árvore de diretórios | idêntica | idêntica |

As únicas diferenças de arquivos: B tem `assets/` com mídia e ganhou `draft_cover.jpg` e `attachment_plugin_draft.json` **depois** que o CapCut a abriu e regravou — enriquecimento do app, não divergência de formato.

Dois projetos ficaram prontos no diretório do CapCut para a verificação visual:

| Projeto | Conteúdo |
|---|---|
| `VectCut MCP Baseline` | vazio (prova o caminho) |
| `VectCut MCP Content` | 4 tracks, 4 segmentos, 3 assets, 8 s — vídeo 0–5 s, imagem 5–8 s, áudio 0–8 s, texto "MCP" 0–3 s |

---

## Configuração do Codex aplicada (WI-2.13)

Adicionado ao fim de `~/.codex/config.toml`, com backup em `config.toml.bak-20260914-192151`:

```toml
[mcp_servers.capcut]
command = ".../capcut-mcp-mac/.venv/bin/python"
args = ["-m", "capcut_mcp.server"]
cwd = ".../capcut-mcp-mac"
enabled = true
startup_timeout_sec = 60

[mcp_servers.capcut.env]
PYTHONPATH = ".../capcut-mcp-mac/src"
CAPCUT_PROJECTS_DIR = "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"
```

TOML validado; os servidores `node_repl` e `computer-use` que já existiam continuam intactos. Para reverter: restaurar o backup.

---

## Pendente

**AC1.5 — exercitar pelo Codex.** A configuração está escrita e validada, mas o Codex precisa ser reiniciado para carregar o servidor. Só então o handshake real do cliente dele é exercido. Tudo o que o Codex faria já foi exercido por um cliente stdio equivalente (os 18 testes), então o risco residual é de integração do cliente, não do servidor.

## Limpeza sugerida

Sete projetos de teste estão no diretório do CapCut. Os que já cumpriram seu papel:

| Projeto | Ainda útil? |
|---|---|
| `0914` | **sim** — é o projeto de referência de onde o template é derivado. Não apagar. |
| `0914 (1)` | sim, segunda referência (com conteúdo) |
| `VectCut Baseline A` | não (prova negativa já registrada) |
| `VectCut Baseline B` / `C` | não |
| `VectCut MCP Baseline` / `Content` | não |
