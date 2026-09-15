# CAPCUT_MCP_SPEC — Especificação técnica: Codex → MCP → VectCutAPI → CapCut Desktop

**Versão:** 0.1 (draft para revisão — nada implementado)
**Base factual:** [`vectcut-research.md`](vectcut-research.md) — auditoria do commit `b83be74` de `sun-guannan/VectCutAPI`, verificada empiricamente no macOS
**Plataforma-alvo:** macOS (Apple Silicon), CapCut Desktop International
**Escopo desta versão:** contrato de tools MCP + requisitos funcionais para a v1 do adaptador

> **Regra editorial deste documento:** nenhum suporte é afirmado sem rastro no código. Cada requisito cita `arquivo:linha` ou o teste empírico que o sustenta. Quando o upstream não suporta algo, o status é `REQUIRES_EXTENSION` ou `NOT_SUPPORTED` — nunca `SUPPORTED` "com jeitinho".

---

## Sumário de status

Contagem sobre as **49 funcionalidades pedidas** no escopo da v1:

| Domínio | Pedidas | SUPPORTED | PARTIALLY_SUPPORTED | REQUIRES_EXTENSION | NOT_SUPPORTED |
|---|---|---|---|---|---|
| Projeto | 7 | 2 | 3 | 1 | 1 |
| Vídeo | 9 | 7 | 1 | 0 | 1 |
| Áudio | 5 | 5 | 0 | 0 | 0 |
| Imagem | 4 | 4 | 0 | 0 | 0 |
| Texto | 9 | 7 | 2 | 0 | 0 |
| Legendas | 4 | 1 | 3 | 0 | 0 |
| Efeitos | 3 | 1 | 2 | 0 | 0 |
| Keyframes | 5 | 5 | 0 | 0 | 0 |
| Media analysis | 3 | 1 | 0 | 0 | 2 |
| **Total** | **49** | **33** | **11** | **1** | **4** |

Mais **4 itens adjacentes** que a auditoria expôs e que valem registro por afetarem o desenho (não estavam na lista pedida):

| Item | Status | Onde |
|---|---|---|
| Inspeção de draft (pré-requisito da validação) | `REQUIRES_EXTENSION` | PRJ-07 |
| Fade de áudio (in/out) | `REQUIRES_EXTENSION` | AUD-02 |
| Filtros / LUTs (468 catalogados) | `REQUIRES_EXTENSION` | FX-04 |
| Keyframes em tracks não-vídeo | `PARTIALLY_SUPPORTED` (a verificar) | KF-06 |

Legenda dos status:

| Status | Significado operacional |
|---|---|
| `SUPPORTED` | Funciona hoje no macOS pelo caminho MCP Python, verificado empiricamente. O adaptador apenas normaliza nomes/validações. |
| `PARTIALLY_SUPPORTED` | O mecanismo existe e funciona, mas com bug, default quebrado, semântica enganosa ou cobertura incompleta. Exige correção no adaptador para ser confiável. |
| `REQUIRES_EXTENSION` | A primitiva existe em `pyJianYingDraft` (ou nos metadados) mas **não é alcançável** por nenhuma tool MCP ou rota HTTP. Exige código novo no adaptador; não exige engenharia reversa do CapCut. |
| `NOT_SUPPORTED` | Não existe em nenhuma camada. Exige desenvolvimento do zero e/ou descoberta sobre o formato do CapCut. Fora da v1. |

---

## Goals

| # | Objetivo | Critério de sucesso |
|---|---|---|
| G1 | Permitir que um agente no Codex monte um projeto de vídeo completo do zero por comandos estruturados, sem escrever Python. | Um prompt em linguagem natural produz uma pasta de projeto abrível no CapCut, com vídeo, áudio, texto, legendas, efeito e keyframes nas posições pedidas. |
| G2 | Eliminar as classes de falha silenciosa identificadas na auditoria. | Toda operação que não produz o efeito pedido retorna erro estruturado; nenhuma retorna `success: true` sem efeito. |
| G3 | Tornar os catálogos do CapCut descobríveis pelo agente. | O agente obtém nomes válidos de transição/efeito/animação/fonte/máscara/filtro por tool, sem adivinhar identificadores. |
| G4 | Tornar o tempo explícito e verificável antes de salvar. | Nenhum `save` ocorre sem que durações reais tenham sido resolvidas e conflitos de timeline reportados. |
| G5 | Isolar o adaptador do upstream instável. | Atualizar o fork do VectCutAPI não exige reescrever o adaptador; os bugs conhecidos são corrigidos em um único lugar. |
| G6 | Entregar o projeto no lugar certo do macOS, com metadados próprios. | O projeto aparece na lista do CapCut com o nome pedido e mídia localizável. |
| G7 | Dar ao agente capacidade de auto-verificação. | O agente pode inspecionar o estado do draft e receber um relatório de validação antes de salvar. |

## Non-Goals

| # | Fora de escopo na v1 | Razão |
|---|---|---|
| N1 | Renderizar/exportar vídeo (MP4). | Módulo de render do VectCut é fechado; `jianying_controller.py` é código morto que importa módulo inexistente. |
| N2 | Controlar a UI do CapCut (abrir projeto, clicar, exportar). | `desktop_companion.py` é Win32 puro. Automação de UI no macOS exige Accessibility API — projeto separado. |
| N3 | Hot-reload do CapCut após salvar. | Sem file watcher no app; o autosave em memória sobrescreve o disco. A recarga é ação humana. |
| N4 | Usar `capcut_server.py` (HTTP), `web_preview.py` ou o MCP em TypeScript. | Não importam no macOS (`ctypes.windll`) / dependem do HTTP. Ver Compatibility Strategy. |
| N5 | Preview visual do timeline. | O player em `web_preview.py` é inerte no macOS e lê o arquivo de conteúdo errado para o perfil CapCut. |
| N6 | Upload para OSS / URLs públicas de draft. | `is_upload_draft: false`; `draft_url` atual aponta para domínio de terceiros e é inválida. O adaptador nunca retorna essa URL. |
| N7 | Multi-usuário, concorrência, execução remota. | `DRAFT_CACHE` é global sem lock; o servidor MCP é single-process por sessão. |
| N8 | Edição colaborativa / ida-e-volta com edições humanas no CapCut. | Reescrever um projeto já editado no app o sobrescreve. Fluxo é one-way: agente → CapCut. |
| N9 | Suporte a Jianying (versão chinesa) e a Windows. | Alvo declarado é CapCut International no macOS. Os perfis existem, mas não são testados nem suportados nesta spec. |
| N10 | Geração de mídia (TTS, imagens, vídeo por IA). | O adaptador consome mídia pronta (arquivo local ou URL). |

---

## User Flows

### UF-1 — Montagem de vídeo novo (fluxo principal)

```
Usuário (Codex): "monte um reel 9:16 com estes 3 clipes, música de fundo,
                  título nos 2 primeiros segundos e legendas deste SRT"
   │
   ├─ 1. capcut.catalog.list(kind="transition"|"font")        → nomes válidos
   ├─ 2. capcut.media.probe(paths[])                          → duração/dimensão/formato de cada mídia
   ├─ 3. capcut.draft.create(width, height, name)             → draft_id
   ├─ 4. capcut.video.add ×3 (timeline_start calculado)       → segment_id
   ├─ 5. capcut.audio.add (role="background", volume=0.25)
   ├─ 6. capcut.text.add (0→2s, font válida, size 9.0)
   ├─ 7. capcut.subtitle.add (srt, font explícita)
   ├─ 8. capcut.draft.inspect(draft_id)                       → estado do timeline
   ├─ 9. capcut.draft.validate(draft_id)                      → [] ou lista de problemas
   └─10. capcut.draft.save(draft_id, target="capcut")         → caminho + instrução de recarga
   │
   └─ Humano: abre/volta à Home do CapCut → projeto aparece → refina manualmente
```

Ponto crítico do fluxo: **o passo 2 é obrigatório antes do 4**. Sem duração conhecida, os segmentos nascem com timerange zero e a resolução tardia no save apaga silenciosamente os clipes sobrepostos (verificado: 3 clipes → 1 sobrevivente).

### UF-2 — Modificação incremental na mesma sessão

```
"aumenta o título para 3s e troca a transição do clipe 2"
   │
   ├─ capcut.draft.inspect(draft_id)     → segment_ids e timeranges atuais
   ├─ ⚠️ v1 NÃO tem edit/remove de segmento (ver VID-05, PRJ-05)
   └─ Estratégia v1: REBUILD — recriar o draft do zero com os parâmetros novos
      (o adaptador mantém o "plano" declarativo da sessão para permitir isso)
```

### UF-3 — Recuperação após reinício do servidor MCP

```
"salva o draft que a gente montou" (após o processo MCP ter reiniciado)
   │
   ├─ capcut.draft.save(draft_id)
   └─ ❌ ERRO EXPLÍCITO: DRAFT_NOT_FOUND (upstream retornaria success:true + nada escrito)
      → adaptador instrui: replay do plano (UF-2) ou recriar
```

### UF-4 — Abrir projeto existente do CapCut

```
"ajusta o projeto 'reel_setembro' que já está no CapCut"
   │
   ├─ capcut.project.list()          → REQUIRES_EXTENSION
   ├─ capcut.project.open(name)      → REQUIRES_EXTENSION (load_template existe na lib, não exposto)
   └─ v1: somente leitura/inspeção. Mutação de projeto importado fora de escopo.
```

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Codex (agente)                                                       │
│  • lê o MCP Tool Contract via tools/list                             │
│  • mantém o "plano declarativo" da sessão em contexto                │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ MCP (JSON-RPC 2.0 sobre stdio)
┌───────────────────────────▼──────────────────────────────────────────┐
│ L1 — ADAPTADOR (novo, a especificar aqui)   capcut-mcp-mac           │
│                                                                      │
│  ├─ Tool registry  (capcut.*, schemas estritos)                      │
│  ├─ Normalizador   (nomes de track, escalas, enums case-insensitive) │
│  ├─ Planner        (resolve duração → calcula timeline → detecta      │
│  │                  colisão ANTES de mutar)                          │
│  ├─ Validator      (regras pré-save, ver seção Validation)           │
│  ├─ Catalog        (expõe pyJianYingDraft/metadata/*)                │
│  ├─ Warning bus    (captura stdout do L0 → warnings[] estruturado)   │
│  ├─ Draft registry (draft_id → estado + plano; persistência em disco) │
│  └─ Deployer       (resolve diretório real do CapCut no macOS,        │
│                     reescreve draft_meta_info.json)                  │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ chamadas Python in-process (sem HTTP)
┌───────────────────────────▼──────────────────────────────────────────┐
│ L0 — UPSTREAM (fork com commit fixo, NÃO modificado)                 │
│  add_video_track · add_audio_track · add_image_impl · add_text_impl  │
│  add_subtitle_impl · add_effect_impl · add_sticker_impl              │
│  add_video_keyframe_impl · get_duration_impl · save_draft_impl       │
│  pyJianYingDraft/ (Script_file, tracks, segments, metadata)          │
│  ⛔ NÃO usado: capcut_server.py · web_preview.py ·                   │
│                desktop_companion.py · mcp-server/ (TS)               │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ ffprobe (duração/dimensão) · cópia/download de assets
┌───────────────────────────▼──────────────────────────────────────────┐
│ FILESYSTEM                                                           │
│  ~/Movies/CapCut/User Data/Projects/com.lveditor.draft/<nome>/       │
│     ├─ draft_info.json        (conteúdo do timeline)                 │
│     ├─ draft_meta_info.json   (REESCRITO pelo L1)                    │
│     └─ assets/{video,image,audio}/                                   │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ leitura na abertura do app (sem watcher)
┌───────────────────────────▼──────────────────────────────────────────┐
│ CapCut Desktop (macOS) — ação humana: abrir / voltar à Home          │
└──────────────────────────────────────────────────────────────────────┘
```

**Decisões de arquitetura**

| # | Decisão | Justificativa |
|---|---|---|
| A1 | Transporte: MCP stdio, processo único por sessão do Codex. | É o único caminho que importa no macOS. Sem HTTP, sem porta, sem exposição de rede. |
| A2 | L0 intocado; toda correção no L1. | Merge do upstream permanece trivial; bugs corrigidos em um lugar só. |
| A3 | Namespace `capcut.*` com nomes novos, não reaproveitar os nomes upstream (`add_video`). | Evita que o agente confunda contratos e permita defaults divergentes (`main` vs `video_main`). |
| A4 | Registry de drafts persistido em disco (JSON) fora do repositório. | Remove a falha de "estado só em memória" (L1 da auditoria) e viabiliza UF-3. |
| A5 | Toda mutação registra também o **plano declarativo** (intenção), não só o efeito. | Viabiliza REBUILD (UF-2) sem API de edição/remoção, que não existe no upstream. |
| A6 | `draft_folder` sempre explícito e resolvido pelo L1; nunca o default do upstream. | O default escreve dentro do repositório clonado, que não é ignorado pelo git. |
| A7 | Catálogos servidos a partir dos metadados do L0, nunca de listas escritas à mão. | O `constants.ts` do MCP TypeScript prova o custo de catálogos inventados. |

---

## Functional Requirements

Convenções dos blocos abaixo:

- **Tool (v1)** = nome no contrato do adaptador (a implementar). **Upstream** = função/tool que faz o trabalho hoje.
- **Endpoint** = rota HTTP equivalente. Todas marcadas `⛔macOS` porque `capcut_server.py` não importa no macOS em `b83be74`; listadas para rastreabilidade e para quem usar o commit `71aafc1`.
- **AC** = acceptance criteria, verificáveis.

### 1. Projeto

#### PRJ-01 — Criar novo draft
- **Status:** `SUPPORTED`
- **Implementação atual:** `create_draft.create_draft()` → `Script_file(w,h,fps=30)` carrega `pyJianYingDraft/draft_content_template.json`; registra em `DRAFT_CACHE`. `create_draft.py:6-24`
- **Tool (v1):** `capcut.draft.create` · **Upstream:** `create_draft` · **Endpoint:** `POST /create_draft` ⛔macOS
- **Parâmetros:** `width` int (default 1080), `height` int (default 1920), `name` string *(novo no L1 — usado no `draft_meta_info.json` e no nome da pasta)*, `fps` int *(L0 aceita no construtor mas nenhuma tool expõe → L1 deve expor com default 30)*
- **Retorno:** `{ draft_id, name, width, height, ratio_label, fps, created_at }`
- **Erros:** `INVALID_DIMENSIONS` (≤0, não inteiro, > 4096), `TEMPLATE_MISSING` (template do perfil ausente)
- **Dependências:** nenhuma externa
- **Limitações:** `fps` só 30 na prática (não testado com outros valores); nenhum `draft_url` válido é produzido (o upstream devolve link fictício de domínio de terceiros — o L1 **não** deve propagá-lo)
- **AC:** (a) `create` retorna `draft_id` único no formato `dfd_cat_<unix>_<hex8>`; (b) dois `create` consecutivos retornam ids diferentes; (c) o retorno **não** contém nenhuma URL externa.

#### PRJ-02 — Definir resolução
- **Status:** `SUPPORTED`
- **Implementação atual:** `width`/`height` no construtor; gravados em `canvas_config` por `Script_file.dumps()` (`script_file.py:886`)
- **Tool (v1):** `capcut.draft.create` (`width`,`height`) · **Upstream:** idem · **Endpoint:** `POST /create_draft` ⛔macOS
- **Parâmetros:** `width`, `height` (pixels)
- **Retorno:** ecoado em `capcut.draft.create` e em `capcut.draft.inspect`
- **Erros:** `INVALID_DIMENSIONS`
- **Dependências:** —
- **Limitações:** **`width`/`height` também são aceitos por quase todos os `add_*` do upstream, onde servem para criar um draft novo se o `draft_id` não existir** — fonte de drafts fantasma. O L1 deve fixar a resolução no `create` e **nunca** repassar `width`/`height` nas operações de mídia.
- **AC:** (a) `inspect` reporta a mesma resolução pedida; (b) `draft_info.json` gravado tem `canvas_config.width/height` idênticos; (c) nenhuma tool de mídia aceita `width`/`height` no schema do L1.

#### PRJ-03 — Definir aspect ratio
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** **derivado**, não configurável. `draft_profiles.write_profile_content()` calcula o rótulo no save: `h>w → "9:16"`, `w>h → "16:9"`, `w==h → "1:1"` (`draft_profiles.py:110-118`). `dumps()` grava `ratio: "original"` e o `write_profile_content` sobrescreve.
- **Tool (v1):** `capcut.draft.create` (`aspect_ratio` opcional, derivado por default) · **Upstream:** nenhum parâmetro · **Endpoint:** —
- **Parâmetros:** nenhum no upstream. No L1: `aspect_ratio` string opcional (`"9:16"|"16:9"|"1:1"`) apenas para **validação cruzada** contra `width`/`height`.
- **Retorno:** `ratio_label` + `ratio_is_exact: bool`
- **Erros:** `RATIO_MISMATCH` (o `aspect_ratio` pedido não corresponde a `width/height`)
- **Dependências:** —
- **Limitações:** **qualquer resolução vertical é rotulada `9:16`, mesmo quando não é.** Verificado: 1080×1350 (4:5) → gravado como `"9:16"`. Formatos 4:5, 2:3, 21:9 não têm rótulo correto. O L1 não pode corrigir isso sem saber quais rótulos o CapCut aceita → ver Unknowns da auditoria.
- **AC:** (a) para 1080×1920, 1920×1080 e 1080×1080 o rótulo está correto; (b) para qualquer outra proporção, a tool retorna `ratio_is_exact: false` **e** um `warning` explícito; (c) `RATIO_MISMATCH` é retornado quando o usuário pede um rótulo incompatível.

#### PRJ-04 — Identificar draft
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** `draft_id = f"dfd_cat_{unix_time}_{uuid4().hex[:8]}"` (`create_draft.py:16`). É **apenas** chave de um `OrderedDict` em memória (`draft_cache.py`) e nome de pasta. Sem relação com o `draft_id` interno do CapCut.
- **Tool (v1):** retornado por `capcut.draft.create`; aceito por todas as tools · **Upstream:** idem · **Endpoint:** todas as rotas
- **Parâmetros:** `draft_id` string
- **Retorno:** —
- **Erros:** `DRAFT_NOT_FOUND` *(novo no L1)*
- **Dependências:** —
- **Limitações:** **(a)** o id morre com o processo (sem persistência); **(b)** `get_or_create_draft` com id desconhecido **cria um draft novo em silêncio** (`create_draft.py:37-44`) — o agente acha que editou A e editou B; **(c)** não há tool/rota para listar drafts em memória.
- **AC:** (a) toda tool com `draft_id` desconhecido retorna `DRAFT_NOT_FOUND` e **não** cria draft novo; (b) `capcut.draft.list` lista os drafts da sessão; (c) o `draft_id` sobrevive a um reinício do servidor MCP (registry em disco).

#### PRJ-05 — Abrir / modificar draft existente
- **Status:** `REQUIRES_EXTENSION`
- **Implementação atual:** existe na biblioteca, **inalcançável** por MCP/HTTP: `Script_file.load_template()` (`script_file.py:214`), `Draft_folder.list_drafts/load_template/duplicate_as_template` (`draft_folder.py`), `replace_material_by_name` (`:696`), `replace_material_by_seg` (`:734`), `replace_text` (`:780`), `import_track` (`:641`), `template_mode.Shrink_mode/Extend_mode`. Único consumidor de `load_template` no repositório é `draft_folder.py` — que não é usado por nada.
- **Tool (v1):** `capcut.project.list` / `capcut.project.inspect` (somente leitura) · **Upstream:** `/list_projects`, `/read_project` ⛔macOS **e** com bug: ambos procuram `draft_content.json`, enquanto o perfil CapCut grava `draft_info.json` (`capcut_server.py:850,884`)
- **Parâmetros:** `project_name` | `path`
- **Retorno:** `{ name, path, content_file, duration_us, fps, canvas_config, tracks[], materials_summary, is_locked }`
- **Erros:** `PROJECT_NOT_FOUND`, `CONTENT_FILE_UNRECOGNIZED`, `PROJECT_LOCKED`
- **Dependências:** diretório de projetos do CapCut resolvido (ver File Handling)
- **Limitações:** modificação de projeto importado **fora de escopo na v1**: o modelo de "imported tracks" é separado das tracks nativas, `replace_*` exige índices de segmento, e reescrever um projeto aberto no app é sobrescrito pelo autosave. Mutação em sessão (mesmo `draft_id`) é o caminho suportado.
- **AC:** (a) `project.list` lista projetos do diretório real do macOS reconhecendo **tanto** `draft_info.json` quanto `draft_content.json`/`Timelines/`; (b) `project.inspect` nunca falha por nome de arquivo de conteúdo; (c) projeto com `.locked` é reportado como travado, não lido.

#### PRJ-06 — Salvar draft
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** `save_draft_impl.save_draft_impl()` → `save_draft_background()` (sincrono; o caminho em thread está comentado). Copia o template do perfil, resolve metadados via ffprobe, baixa/copia assets (ThreadPool 16), aplica keyframes pendentes, resolve sobreposições, grava via `write_profile_content`. `save_draft_impl.py:42-278`
- **Tool (v1):** `capcut.draft.save` · **Upstream:** `save_draft` · **Endpoint:** `POST /save_draft` ⛔macOS
- **Parâmetros:** `draft_id` (obrigatório); `target` enum `"capcut"|"path"` *(L1)*; `path` (se `target="path"`); `project_name` *(L1: nome da pasta e do projeto)*; `overwrite` bool *(L1)*. Upstream aceita `draft_folder`, `project_name`, `auto_deploy`, `auto_reload` — `auto_reload` é inútil no macOS.
- **Retorno:** `{ project_path, content_file, files_written[], assets_written[], duration_us, warnings[], next_step }`
- **Erros:** `DRAFT_NOT_FOUND`, `DRAFT_EMPTY`, `VALIDATION_FAILED`, `TARGET_DIR_NOT_FOUND`, `TARGET_EXISTS`, `ASSET_FETCH_FAILED`, `FFPROBE_UNAVAILABLE`, `PROJECT_LOCKED`
- **Dependências:** **ffprobe obrigatório**; diretório do CapCut; espaço em disco (os assets são copiados)
- **Limitações (todas confirmadas):**
  - **`success: true` + `draft_url: null` sem escrever nada** quando o `draft_id` não está no cache (`save_draft_impl.py:46-58` retorna `None`, e `:290` empacota como sucesso). Verificado.
  - Sem `draft_folder`, escreve **dentro do repositório clonado**, que o `.gitignore` não ignora (`save_draft_impl.py:78`).
  - `shutil.rmtree` do destino sem confirmação (`:81-83`).
  - Auto-deploy no macOS procura o container do **JianyingPro** (`:259`) e falha em silêncio.
  - `draft_meta_info.json` copiado sem reescrita: nome `0707`, paths de `/Users/sunguannan/`, **mesmo UUID em todo projeto**, `draft_cover.jpg` inexistente.
  - `new_version` regride para `110.0.0` (template real: `138.0.0`).
  - Bloqueante: downloads com timeout de 180 s por arquivo.
- **AC:** (a) `draft_id` inválido → `DRAFT_NOT_FOUND`, zero bytes escritos; (b) save sempre grava em caminho explícito, nunca no repositório; (c) `draft_meta_info.json` gravado contém `draft_name`, `draft_fold_path`, `draft_root_path` corretos, `draft_id` UUID novo e timestamps atuais; (d) destino existente só é sobrescrito com `overwrite: true`; (e) falha de qualquer asset → `ASSET_FETCH_FAILED` com a lista de falhas, não sucesso parcial mudo.

#### PRJ-07 — Validar draft antes de salvar
- **Status:** `NOT_SUPPORTED` (validação) / `REQUIRES_EXTENSION` (inspeção)
- **Implementação atual:** **não existe nenhuma lógica de validação.** O que existe é inspeção: `query_script_impl()` devolve o JSON completo (`save_draft_impl.py:561-584`), exposto só por `POST /query_script` ⛔macOS. A única "validação" do upstream é destrutiva: o passe O(n²) de sobreposição **apaga** o segmento de índice maior (`save_draft_impl.py:520-544`).
- **Tool (v1):** `capcut.draft.validate` + `capcut.draft.inspect` · **Upstream:** `query_script` (parcial) · **Endpoint:** `POST /query_script` ⛔macOS
- **Parâmetros:** `draft_id`, `level` enum `"error"|"warning"|"info"`
- **Retorno:** `{ ok: bool, issues: [{ code, severity, track, segment_id, message, suggestion }], summary }`
- **Erros:** `DRAFT_NOT_FOUND`
- **Dependências:** ffprobe (para validar durações reais antes do save)
- **Limitações:** a validação será do **modelo**, não do CapCut. Não é possível garantir que o app aceitará o arquivo — ver Compatibility Strategy e os Unknowns da auditoria.
- **AC:** (a) `validate` detecta sobreposição, gap, segmento estourando a duração real da mídia, keyframe fora de segmento, track vazia, texto fora da safe zone e recurso VIP; (b) `save` recusa por default se houver issue de severidade `error`; (c) nenhum segmento é apagado silenciosamente — sobreposição é sempre erro reportado.

---

### 2. Vídeo

#### VID-01 — Adicionar vídeo
- **Status:** `SUPPORTED` (verificado com arquivo local e resolução de metadados via ffprobe)
- **Implementação atual:** `add_video_track()` → `Video_material(material_type='video', remote_url=...)` + `Video_segment` com `source_timerange`/`target_timerange`; cria a track se não existir. `add_video_track.py:10-215`
- **Tool (v1):** `capcut.video.add` · **Upstream:** `add_video` · **Endpoint:** `POST /add_video` ⛔macOS
- **Parâmetros:** `draft_id`, `source` (caminho local **ou** URL), `track` (default `"video_main"` no L1), `source_start`, `source_end`, `timeline_start`, `duration`, `speed`, `volume`, `scale_x/y`, `transform_x/y`, `transition`, `transition_duration`, `mask_*`, `background_blur`, `layer_index`
- **Retorno:** `{ draft_id, segment_id, track, timeline_start_us, timeline_end_us, source_range_us, material_id }` — **nota:** o upstream retorna apenas `{draft_id, draft_url}`; `segment_id` precisa ser capturado pelo L1 a partir do objeto `Video_segment`.
- **Erros:** `DRAFT_NOT_FOUND`, `SOURCE_NOT_FOUND`, `SOURCE_UNREADABLE`, `SEGMENT_OVERLAP`, `INVALID_TIMERANGE`, `UNKNOWN_TRANSITION`, `UNKNOWN_MASK`, `INVALID_BLUR_LEVEL`
- **Dependências:** ffprobe (no save, ou antes via `capcut.media.probe`)
- **Limitações:** cria **sempre uma track de vídeo extra vazia** chamada `video` antes da nomeada (`add_video_track.py:83-88`) — verificado no JSON gerado; o nome do material é sempre `video_<sha256[:16]>.mp4` independentemente do formato real; default de track divergente entre fachadas (`video_main` no HTTP, `main` no MCP).
- **AC:** (a) o segmento aparece no `draft_info.json` com o timerange pedido em µs; (b) o asset é copiado para `assets/video/` e o `path` do material aponta para ele; (c) mesmo source adicionado duas vezes reutiliza um único material (hash estável); (d) nenhuma track vazia espúria no JSON final.

#### VID-02 — Definir posição na timeline
- **Status:** `SUPPORTED`
- **Implementação atual:** `target_start` → `target_timerange = trange(target_start, duration/speed)` (`add_video_track.py:139-141`)
- **Tool (v1):** `capcut.video.add` (`timeline_start`) · **Upstream:** `add_video` (`target_start`) · **Endpoint:** `POST /add_video` ⛔macOS
- **Parâmetros:** `timeline_start` float (segundos, ≥0)
- **Retorno:** `timeline_start_us`, `timeline_end_us`
- **Erros:** `INVALID_TIMERANGE`, `SEGMENT_OVERLAP`
- **Dependências:** —
- **Limitações:** **a primeira track de vídeo (a de baixo) é forçada a começar em 0s pelo CapCut** — documentado em `script_file.py:250-252`; o L1 deve avisar se `timeline_start > 0` na track principal. Conversão para µs pode introduzir drift de arredondamento; não há alinhamento a frame.
- **AC:** (a) `timeline_start=4.0` produz `target_timerange.start == 4000000`; (b) `timeline_start` que colide com segmento existente → `SEGMENT_OVERLAP` (nunca deleção); (c) warning quando `timeline_start > 0` na track base.

#### VID-03 — Definir início/fim (trim de origem)
- **Status:** `SUPPORTED`
- **Implementação atual:** `start`/`end` → `source_timerange`; `target_duration = (end-start)/speed` (`add_video_track.py:135-141`)
- **Tool (v1):** `capcut.video.add` (`source_start`,`source_end`) · **Upstream:** `add_video` (`start`,`end`) · **Endpoint:** `POST /add_video` ⛔macOS
- **Parâmetros:** `source_start`, `source_end` (segundos na mídia de origem)
- **Retorno:** `source_range_us`
- **Erros:** `INVALID_TIMERANGE` (`end <= start`), `SOURCE_RANGE_EXCEEDS_MEDIA`
- **Dependências:** ffprobe para validar contra a duração real
- **Limitações:** **se `source_end` e `duration` forem omitidos, a duração é 0.0 no add** (`add_video_track.py:107-112`) e só é resolvida no save; `source_end` além do fim real da mídia é **silenciosamente encurtado** no save (`save_draft_impl.py:458-478`).
- **AC:** (a) o L1 recusa `add` sem duração resolvível — exige `source_end`, `duration`, ou resolve via probe automático; (b) `source_end` > duração real → `SOURCE_RANGE_EXCEEDS_MEDIA` no add, não ajuste mudo no save.

#### VID-04 — Cortar trecho
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** corte **na inserção** (`start`/`end`). Não existe split, ripple trim, nem alteração de timerange após o add. Nenhum método de mutação de segmento em `Script_file`/`Track` (inventário completo verificado: só `add_*`, e `replace_*` no modo template).
- **Tool (v1):** `capcut.video.add` (corte na inserção) · **Upstream:** `add_video` · **Endpoint:** `POST /add_video` ⛔macOS
- **Parâmetros:** `source_start`, `source_end`
- **Retorno:** ver VID-03
- **Erros:** ver VID-03
- **Dependências:** ffprobe
- **Limitações:** "cortar em dois" = adicionar dois segmentos do mesmo source com ranges distintos (funciona). "Cortar depois de adicionado" = **impossível**; requer REBUILD do draft (UF-2).
- **AC:** (a) dois `add` do mesmo source com ranges `0–3` e `3–6` produzem dois segmentos contíguos sem gap nem overlap; (b) a documentação da tool declara explicitamente que não há edição pós-inserção.

#### VID-05 — Reorganizar clips
- **Status:** `NOT_SUPPORTED`
- **Implementação atual:** **não existe.** Sem `remove_segment`, `move_segment`, `reorder` em nenhuma camada. `Track.segments` é uma lista Python append-only pela API pública; a única remoção é o `pop()` interno do resolvedor de sobreposição (`save_draft_impl.py:543`).
- **Tool (v1):** — (o L1 deve expor `capcut.draft.rebuild`, não uma tool de reordenação) · **Upstream:** — · **Endpoint:** —
- **Parâmetros:** n/a
- **Retorno:** n/a
- **Erros:** `OPERATION_NOT_SUPPORTED` com `suggestion: "use capcut.draft.rebuild"`
- **Dependências:** o plano declarativo da sessão (A5)
- **Limitações:** reordenar = recriar o draft com `timeline_start` recalculados. Custo: novo save completo (recópia de assets). Para v1 isso é aceitável; para projetos grandes, não.
- **AC:** (a) uma tool de reordenação **não** é oferecida ao agente; (b) `capcut.draft.rebuild` reproduz o draft aplicando uma nova ordem ao plano e gera o mesmo conjunto de assets; (c) o agente recebe `OPERATION_NOT_SUPPORTED` acionável se tentar reordenar.

#### VID-06 — Controlar volume
- **Status:** `SUPPORTED`
- **Implementação atual:** `volume` em `Video_segment` (`add_video_track.py:154`); também keyframável (`Keyframe_property.volume`, válido para `Video_segment` e `Audio_segment`)
- **Tool (v1):** `capcut.video.add` (`volume`) / `capcut.keyframe.add` (`property="volume"`) · **Upstream:** `add_video` · **Endpoint:** `POST /add_video` ⛔macOS
- **Parâmetros:** `volume` float (1.0 = original; 0.0 = mudo)
- **Retorno:** ecoado em `inspect`
- **Erros:** `INVALID_VOLUME` (fora de 0.0–2.0 — **limite a definir**, o upstream não valida)
- **Dependências:** —
- **Limitações:** sem validação de faixa no upstream; sem normalização de loudness; sem ducking automático (o skill `capcut-director` recomenda ducking, mas nada no código o implementa).
- **AC:** (a) `volume=0.0` grava mudo no JSON; (b) valor fora da faixa → `INVALID_VOLUME`; (c) volume via keyframe e volume estático coexistem de forma documentada.

#### VID-07 / VID-08 — Alterar escala e posição
- **Status:** `SUPPORTED` (ambos)
- **Implementação atual:** `Clip_settings(scale_x, scale_y, transform_x, transform_y)` (`add_video_track.py:145-151`); também keyframáveis
- **Tool (v1):** `capcut.video.add` (`scale_x`,`scale_y`,`transform_x`,`transform_y`) · **Upstream:** `add_video` · **Endpoint:** `POST /add_video` ⛔macOS
- **Parâmetros:** `scale_x`/`scale_y` float (1.0 = sem escala); `transform_x`/`transform_y` float **normalizados**, 0 = centro
- **Retorno:** ecoado em `inspect`
- **Erros:** `INVALID_TRANSFORM` (fora de −10..10, faixa usada pelo validador de keyframe em `add_video_keyframe_impl.py:150-153`)
- **Dependências:** —
- **Limitações:** **unidade de `transform_*` é "meia tela"** (documentado em `keyframe.py:39-42`: valor exibido no app ÷ dimensão do canvas). `transform_y` positivo = **para cima**. Isso contradiz a intuição de pixels e não é dito em nenhuma doc do repositório — o L1 deve documentar e, opcionalmente, aceitar `transform_x_px`/`transform_y_px` convertendo internamente.
- **AC:** (a) a descrição da tool declara a unidade e o sentido do eixo Y; (b) `transform_y=0.5` desloca o elemento para cima em 1/4 da altura do canvas, confirmado no CapCut; (c) valores fora da faixa → `INVALID_TRANSFORM`.

#### VID-09 — Aplicar transição
- **Status:** `SUPPORTED`
- **Implementação atual:** `getattr(CapCut_Transition_type, nome)` → `Video_segment.add_transition(tipo, duration_us)` (`add_video_track.py:158-175`). 116 transições verificadas; cada uma com `default_duration` nos metadados (ex.: `Mix` = 1.000.000 µs).
- **Tool (v1):** `capcut.video.add` (`transition`,`transition_duration`) · **Upstream:** `add_video`, `add_image` · **Endpoint:** `POST /add_video` ⛔macOS
- **Parâmetros:** `transition` string (**identificador exato do enum**, ex.: `"Mix"`, `"Black_Fade"`), `transition_duration` float segundos (default 0.5)
- **Retorno:** `{ transition: { name, duration_us, is_vip } }`
- **Erros:** `UNKNOWN_TRANSITION` (com sugestão por similaridade), `INVALID_TRANSITION_DURATION`
- **Dependências:** catálogo (`capcut.catalog.list(kind="transition")`)
- **Limitações:** **case-sensitive, sem fuzzy match** — `"fade_in"` falha, `"Mix"` funciona (verificado). A mensagem de erro do upstream em máscaras chega a listar nomes minúsculos que **não** funcionam (`add_video_track.py:189`). A transição é anexada ao segmento e consome tempo do clipe adjacente; não há validação de duração vs. tamanho dos clipes. Flag `is_vip` existe nos metadados e é **ignorada** por todos os `add_*`.
- **AC:** (a) `capcut.catalog.list(kind="transition")` devolve os 116 nomes exatos com `default_duration` e `is_vip`; (b) nome inválido → `UNKNOWN_TRANSITION` com até 3 sugestões; (c) o L1 aceita nome case-insensitive e normaliza para o identificador canônico; (d) transição VIP gera `warning`.

---

### 3. Áudio

#### AUD-01 — Adicionar áudio
- **Status:** `SUPPORTED` (verificado com WAV local)
- **Implementação atual:** `add_audio_track()` → `Audio_material` + `Audio_segment` (`add_audio_track.py:11-151`)
- **Tool (v1):** `capcut.audio.add` · **Upstream:** `add_audio` · **Endpoint:** `POST /add_audio` ⛔macOS
- **Parâmetros:** `draft_id`, `source`, `track` (default `"audio_main"`), `source_start`, `source_end`, `timeline_start`, `duration`, `volume`, `speed`, `sound_effects`
- **Retorno:** `{ draft_id, segment_id, track, timeline_start_us, timeline_end_us, material_id }`
- **Erros:** `DRAFT_NOT_FOUND`, `SOURCE_NOT_FOUND`, `SEGMENT_OVERLAP`, `INVALID_TIMERANGE`, `UNKNOWN_AUDIO_EFFECT`
- **Dependências:** ffprobe
- **Limitações:** o nome do material é sempre `audio_<hash>.mp3` **sem transcodificação** — verificado: um WAV foi copiado como `.mp3`; `sound_effects` exige o formato posicional `[[nome, [params]]]` e efeito desconhecido só emite `print` (engolido pelo MCP), sem erro (`add_audio_track.py:145-147`); 29 efeitos de voz disponíveis.
- **AC:** (a) segmento com timerange correto no JSON; (b) asset em `assets/audio/`; (c) efeito de áudio inválido → `UNKNOWN_AUDIO_EFFECT`, não silêncio; (d) o formato real do arquivo é preservado ou transcodificado de forma declarada.

#### AUD-02 — Música de fundo
- **Status:** `SUPPORTED` (como caso de uso de AUD-01) / **fade:** `REQUIRES_EXTENSION`
- **Implementação atual:** mesma tool, track própria + `volume` baixo. **`Audio_fade` existe** (`audio_segment.py:22`) e `Audio_segment.add_fade()` também (`:189`), mas `add_audio_track()` **não expõe nenhum parâmetro de fade** (0 ocorrências de "fade" no arquivo).
- **Tool (v1):** `capcut.audio.add` com `role="background"` (açúcar: track dedicada, volume default 0.2, `fade_in/fade_out`) · **Upstream:** `add_audio` · **Endpoint:** `POST /add_audio` ⛔macOS
- **Parâmetros:** `role` enum, `fade_in`/`fade_out` float segundos *(novo no L1, chamando `add_fade` diretamente no segmento)*
- **Retorno:** `{ ..., fade: { in_us, out_us } }`
- **Erros:** `INVALID_FADE` (fade maior que o segmento)
- **Dependências:** acesso ao objeto `Audio_segment` (o L1 opera in-process, então é viável)
- **Limitações:** sem ducking/sidechain (recomendado pelo skill `capcut-director`, inexistente no código); sem normalização de loudness; loop/repetição de trilha não existe — repetir exige N `add` manuais.
- **AC:** (a) `role="background"` cria track separada e não colide com a narração; (b) `fade_out=1.0` grava um `audio_fades` no JSON; (c) fade maior que o segmento → `INVALID_FADE`.

#### AUD-03 — Controlar volume
- **Status:** `SUPPORTED` — idem VID-06 (`add_audio_track.py:118`), keyframável por `volume`.
- **AC:** (a) `volume=0.25` refletido no JSON; (b) faixa validada; (c) keyframe de volume em track de áudio **testado empiricamente** antes de ser declarado suportado (ver KF-06).

#### AUD-04 — Definir início/fim
- **Status:** `SUPPORTED`
- **Implementação atual:** `start`/`end` → `source_timerange`; duração = `end - start` (`add_audio_track.py:100-110`)
- **Limitações:** mesmo comportamento de duração diferida do vídeo (0.0 quando omitido). O upstream **reatribui a variável `duration`** (`:107`), sobrescrevendo o parâmetro homônimo — o L1 deve passar sempre `source_end` explícito para evitar ambiguidade.
- **AC:** (a) trim de origem correto no JSON; (b) `source_end` além da mídia → erro, não ajuste mudo.

#### AUD-05 — Posicionar na timeline
- **Status:** `SUPPORTED` — `target_start` (`add_audio_track.py:114`). Erros/limitações idênticos a VID-02, exceto a regra da track base (não se aplica a áudio).
- **AC:** (a) `timeline_start` respeitado em µs; (b) colisão → `SEGMENT_OVERLAP`.

---

### 4. Imagem

#### IMG-01 — Adicionar imagem
- **Status:** `SUPPORTED` (verificado com PNG local)
- **Implementação atual:** `add_image_impl()` → `Video_material(material_type='photo')` + `Video_segment`; dimensões via `imageio.imread` no save, fallback 1920×1080 (`add_image_impl.py:11-238`, `save_draft_impl.py:419-429`)
- **Tool (v1):** `capcut.image.add` · **Upstream:** `add_image` · **Endpoint:** `POST /add_image` ⛔macOS
- **Parâmetros:** `draft_id`, `source`, `track`, `timeline_start`, `duration` (default 3.0 s), `scale_x/y`, `transform_x/y`, `intro_animation`, `outro_animation`, `combo_animation`, `*_duration`, `transition`, `mask_*`, `background_blur`, `layer_index`
- **Retorno:** `{ draft_id, segment_id, track, timeline_start_us, duration_us, width, height }`
- **Erros:** `SOURCE_NOT_FOUND`, `IMAGE_UNREADABLE`, `UNKNOWN_ANIMATION`, `UNKNOWN_TRANSITION`, `SEGMENT_OVERLAP`
- **Dependências:** `imageio` (não ffprobe)
- **Limitações:** nome do material sempre `image_<hash>.png` mesmo para JPEG; `imageio.imread` **baixa a imagem inteira** só para ler dimensões (custo em URLs grandes); falha de leitura cai para 1920×1080 com `print` engolido; a duração do material é fixada em 10800 s (convenção do CapCut) enquanto o segmento usa a duração pedida.
- **AC:** (a) imagem aparece como segmento de vídeo tipo `photo`; (b) dimensões reais no JSON; (c) falha de leitura → `IMAGE_UNREADABLE`, não fallback mudo.

#### IMG-02 — Duração
- **Status:** `SUPPORTED` — `start`/`end`, default 3.0 s (`add_image_impl.py:16-17`).
- **AC:** (a) `duration=5` → `target_timerange.duration == 5000000`; (b) duração ≤ 0 → `INVALID_TIMERANGE`.

#### IMG-03 / IMG-04 — Posição e escala
- **Status:** `SUPPORTED` (ambos) — `Clip_settings` idêntico a VID-07/08, **exceto** os defaults de máscara, que divergem do vídeo (`mask_center_x/y` = 0.0 e `mask_size` = 0.5 na imagem; 0.5 e 1.0 no vídeo). O L1 deve unificar.
- **AC:** (a) mesma semântica e unidade de VID-07/08; (b) defaults de máscara unificados e documentados.

---

### 5. Texto

#### TXT-01 — Adicionar texto
- **Status:** `SUPPORTED` (verificado)
- **Implementação atual:** `add_text_impl()` → `Text_segment` + `Text_style` + `Clip_settings`; ~45 parâmetros (`add_text_impl.py:10-289`)
- **Tool (v1):** `capcut.text.add` · **Upstream:** `add_text` · **Endpoint:** `POST /add_text` ⛔macOS
- **Parâmetros:** ver TXT-02..TXT-09
- **Retorno:** `{ draft_id, segment_id, track, timeline_start_us, duration_us, resolved_font, style_summary }`
- **Erros:** `DRAFT_NOT_FOUND`, `UNKNOWN_FONT`, `INVALID_COLOR`, `INVALID_TIMERANGE`, `SEGMENT_OVERLAP`, `UNKNOWN_ANIMATION`
- **Dependências:** nenhuma externa
- **Limitações:** `track_name` default `"text_main"`; texto longo não é medido nem quebrado (só `fixed_width` como proporção).
- **AC:** (a) o `materials.texts[].content` gravado contém o texto e o estilo; (b) o segmento aparece na track de texto com o timerange pedido.

#### TXT-02 — Início/fim
- **Status:** `SUPPORTED` — `start`/`end` **obrigatórios** (sem default no upstream: `add_text_impl.py:12-13`).
- **Erros:** `MISSING_REQUIRED_PARAM`, `INVALID_TIMERANGE`
- **AC:** (a) omitir `start`/`end` → `MISSING_REQUIRED_PARAM` (não `TypeError` cru).

#### TXT-03 — Fonte
- **Status:** `SUPPORTED`
- **Implementação atual:** `getattr(Font_type, font)`; `font=None` é tratado corretamente aqui (`add_text_impl.py:111-119`) — diferente de `import_srt` (ver SUB-01). **335 fontes**, das quais **214 com nomes não-ASCII** (ex.: `思源粗宋`).
- **Erros:** `UNKNOWN_FONT` (o upstream já lista as disponíveis na mensagem)
- **Limitações:** identificador exato, case-sensitive; **não há garantia de que a fonte exista na instalação do CapCut do usuário** — o catálogo é o do backend do CapCut, não do sistema. Fontes VIP não são sinalizadas.
- **AC:** (a) `capcut.catalog.list(kind="font")` devolve os 335 nomes; (b) nome inválido → `UNKNOWN_FONT` com sugestões; (c) `resolved_font` no retorno diz qual identificador foi efetivamente aplicado (ou `null` = default do CapCut).

#### TXT-04 — Tamanho
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** `font_size` float → `Text_style(size=...)`, default **8.0** (`add_text_impl.py:19`, `text_segment.py:47`)
- **Limitações (crítico):** **a escala é interna do CapCut, aproximadamente 5–15 — não são pontos nem pixels.** O schema MCP do upstream declara `default: 24` e o README/`MCP_Documentation_English.md` usam `48`/`56`, o que produz texto gigantesco. A única referência coerente é a tabela do skill `capcut-director` (`.agents/skills/capcut-director/SKILL.md:66-73`): 9.0–12.0 ≈ título (80–135 pt), 6.5–7.5 ≈ legenda, 5.0–5.5 ≈ micro-labels. **Essa tabela não foi verificada empiricamente.**
- **AC:** (a) a descrição da tool declara a escala e a faixa recomendada; (b) `font_size > 20` gera `warning` explícito; (c) a tabela de conversão é calibrada empiricamente (ver Tests Required da auditoria, item 9) antes do release.

#### TXT-05 — Posição
- **Status:** `SUPPORTED` — `transform_x` (default 0), `transform_y` (default **−0.8**, rodapé). Unidade normalizada, Y positivo para cima (idem VID-07/08).
- **Limitações:** sem safe zones; o skill recomenda evitar `|y| > 0.85` (UI do sistema), mas nada valida.
- **AC:** (a) unidade documentada; (b) `validate` avisa quando o texto cai fora da safe zone.

#### TXT-06 — Cor
- **Status:** `SUPPORTED` — `font_color` hex → `util.hex_to_rgb()` (aceita `#fff` e `#ffffff`), default `#ffffff`.
- **Erros:** `INVALID_COLOR` (o upstream levanta `ValueError` com mensagem clara)
- **AC:** (a) `#FFD700` gravado como RGB normalizado no JSON (verificado: `[1.0, 0.843...]`); (b) hex inválido → `INVALID_COLOR`.

#### TXT-07 — Background
- **Status:** `SUPPORTED` — `background_color`, `background_alpha` (default 0.0 = desligado), `background_style`, `background_round_radius`, `background_height/width`, `background_horizontal/vertical_offset`.
- **Limitações:** o background só aparece se `background_alpha > 0`; `background_style` é um inteiro opaco (o default divergente entre camadas: 1 no impl, 0 no schema MCP) sem enumeração documentada.
- **AC:** (a) `background_alpha=0.8` produz entrada de background no JSON; (b) valores válidos de `background_style` documentados ou o parâmetro é restringido a um subconjunto testado.

#### TXT-08 — Sombra
- **Status:** `SUPPORTED` — `shadow_enabled`, `shadow_alpha`, `shadow_angle`, `shadow_color`, `shadow_distance`, `shadow_smoothing`.
- **Limitações:** defaults divergem entre camadas (`shadow_angle` −45.0 no impl vs 315.0 no schema MCP; `shadow_smoothing` 0.15 vs 0.0). O L1 deve fixar um conjunto único.
- **AC:** (a) `shadow_enabled=true` grava sombra no JSON; (b) defaults do L1 são únicos e documentados.

#### TXT-09 — Estilos disponíveis
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:**
  - `SUPPORTED`: `bold`, `italic`, `underline`, `align` (0/1/2), `line_spacing`, `letter_spacing`, `vertical`, `font_alpha`, borda (`border_*`), `fixed_width`/`fixed_height`, e **multi-estilo por faixa de caracteres** via `text_styles: TextStyleRange[]` (`start`,`end`,`font_size`,`font_color`,`bold`,`italic`,`underline`) — o MCP converte dicts em objetos (`mcp_server.py:274-295`).
  - `SUPPORTED`: animações de entrada/saída de texto (`intro_animation`/`outro_animation`) — 76 intro + 68 outro.
  - `REQUIRES_EXTENSION`: **animação de loop de texto.** Existem 53 opções (`CapCut_Text_loop_anim`) e até um endpoint `/get_text_loop_anim_types`, mas **nenhum parâmetro em `add_text_impl` a aplica** (0 ocorrências de "loop" no arquivo).
  - `PARTIALLY_SUPPORTED`: bolha (`bubble_effect_id` + `bubble_resource_id`) e花字/text-effect (`effect_effect_id`) — exigem IDs internos opacos, sem catálogo nem descoberta (`inspect_material()` só lista IDs de um template já importado).
- **Erros:** `UNKNOWN_ANIMATION`, `INVALID_STYLE_RANGE` (faixas sobrepostas ou fora do texto — **o upstream não valida**), `UNSUPPORTED_STYLE` (loop)
- **Limitações:** `line_spacing` aceita float (0.25–0.32 recomendado pelo skill) mas `Text_style` documenta `int`; semântica ambígua.
- **AC:** (a) multi-estilo com 3 faixas produz 3 estilos no JSON; (b) faixa inválida → `INVALID_STYLE_RANGE`; (c) `capcut.catalog.list(kind="text_animation")` lista intro/outro/loop **marcando loop como não aplicável na v1**; (d) pedir loop → `UNSUPPORTED_STYLE`, nunca silêncio.

---

### 6. Legendas

#### SUB-01 — Adicionar captions/subtitles
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** `add_subtitle_impl()` → `Script_file.import_srt()` cria um `Text_segment` por bloco SRT (`add_subtitle_impl.py:9-169`, `script_file.py:469-604`)
- **Tool (v1):** `capcut.subtitle.add` · **Upstream:** `add_subtitle` · **Endpoint:** `POST /add_subtitle` ⛔macOS
- **Parâmetros:** `draft_id`, `srt` (arquivo | URL | conteúdo inline), `track` (default `"subtitle"`), `time_offset`, `font` **(obrigatório no L1)**, `font_size` (default 8.0), `font_color`, `bold/italic/underline`, `border_*`, `background_*`, `transform_x/y` (default y = −0.8), `scale_x/y`, `rotation`, `vertical`, `alpha`
- **Retorno:** `{ draft_id, track, blocks_imported, first_start_us, last_end_us, resolved_font, warnings[] }` — **nota:** o upstream retorna só `{draft_id, draft_url}`; a contagem de blocos precisa ser derivada pelo L1.
- **Erros:** `MISSING_FONT`, `UNKNOWN_FONT`, `SRT_PARSE_ERROR`, `SRT_NOT_FOUND`, `SRT_FETCH_FAILED`, `SEGMENT_OVERLAP`
- **Dependências:** `requests` (se URL)
- **Limitações (bug confirmado):** **`font_type` só é atribuído dentro de `if font:` (`script_file.py:503-505`) mas é lido na closure em `:547` e `:552` → `NameError` quando `font` é omitido.** Verificado pelo protocolo MCP real:
  `{"success": false, "error": "cannot access free variable 'font_type' ..."}`.
  A rota HTTP escapa porque injeta `font="思源粗宋"` (`capcut_server.py:269`); o **schema MCP declara `font` como opcional**, então a tool falha sempre no uso natural. Com `font="Amigate"` funciona e importa os 2 blocos do SRT de teste. Efeito colateral: a track `subtitle` é criada **antes** da exceção, deixando uma track vazia no draft.
- **AC:** (a) `capcut.subtitle.add` sem `font` → `MISSING_FONT` com sugestão, **nunca** `NameError`; (b) import de N blocos cria exatamente N segmentos; (c) falha de import não deixa track vazia no draft; (d) `blocks_imported` é retornado e conferido contra o SRT de entrada.

#### SUB-02 — Importar conteúdo segmentado
- **Status:** `SUPPORTED`
- **Implementação atual:** três modos no mesmo parâmetro: URL (`http://`/`https://` → `requests.get`), caminho de arquivo (`os.path.isfile` → leitura `utf-8-sig`), ou **conteúdo SRT inline** (fallback, com normalização de `\n` e `/n`) — `add_subtitle_impl.py:71-91`
- **Parâmetros:** `srt` string
- **Erros:** `SRT_PARSE_ERROR`, `SRT_FETCH_FAILED`
- **Limitações:** **só SRT.** Sem VTT, ASS, JSON de transcrição ou lista de segmentos estruturada. O parser é caseiro (`script_file.py:560-604`); robustez com SRT malformado não avaliada. Sem geração automática de legenda (não há ASR).
- **AC:** (a) os três modos de entrada funcionam; (b) SRT com BOM é aceito; (c) SRT malformado → `SRT_PARSE_ERROR` com o número da linha; (d) o L1 aceita também uma lista `[{start,end,text}]` e a serializa para SRT internamente.

#### SUB-03 — Controlar timestamps
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** os timestamps vêm **do SRT**; o único controle programático é `time_offset` global (segundos → µs), aplicado a todos os blocos (`add_subtitle_impl.py:155`)
- **Parâmetros:** `time_offset` float
- **Erros:** `INVALID_TIMERANGE`
- **Limitações:** sem edição por bloco, sem escala/stretch temporal, sem snap a cortes, sem re-timing após import. Ajustar um único bloco exige reimportar o SRT inteiro (e não há como remover a track antiga → REBUILD).
- **AC:** (a) `time_offset=2.5` desloca todos os blocos em 2.500.000 µs; (b) offset que leve algum bloco a tempo negativo → `INVALID_TIMERANGE`; (c) a tool documenta que o controle é global.

#### SUB-04 — Definir estilo visual
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** estilo **uniforme** para todos os blocos, via `Text_style` + `Text_border` + `Text_background` + `Clip_settings`; `style_reference` (copiar estilo de um `Text_segment` existente) existe na assinatura mas **não é exposto** por MCP/HTTP.
- **Parâmetros:** ver SUB-01
- **Erros:** `INVALID_COLOR`, `UNKNOWN_FONT`
- **Limitações:** sem estilo por bloco; sem karaokê/realce palavra-a-palavra; `border_width` default 0.0 e `background_alpha` default 0.0 (ou seja, **sem contraste por default** — ruim sobre vídeo, contra a recomendação do próprio skill); `alpha` default divergente entre camadas (0.4 no impl vs 1 na rota HTTP).
- **AC:** (a) o preset default do L1 garante legibilidade (borda ou background ligados); (b) cor/borda/background refletidos em todos os blocos; (c) estilo por bloco é declarado fora de escopo na descrição da tool.

---

### 7. Efeitos

#### FX-01 — Adicionar efeitos suportados
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** `add_effect_impl()` → track de efeito dedicada + `Script_file.add_effect()` → `Effect_segment` com escopo global (`apply_target_type=2`). Catálogo: **345 efeitos de cena + 95 de personagem** (CapCut).
- **Tool (v1):** `capcut.effect.add` · **Upstream:** `add_effect` · **Endpoint:** `POST /add_effect` ⛔macOS
- **Parâmetros:** `draft_id`, `effect` string (identificador exato), `category` enum `"scene"|"character"` **(obrigatório)**, `timeline_start`, `timeline_end`, `track` (default `"effect_01"`), `params` array
- **Retorno:** `{ draft_id, segment_id, effect: { name, category, is_vip, params_applied[] } }`
- **Erros:** `MISSING_CATEGORY`, `UNKNOWN_EFFECT`, `INVALID_EFFECT_PARAMS`, `SEGMENT_OVERLAP`, `INVALID_TIMERANGE`
- **Dependências:** catálogo
- **Limitações (dois bugs confirmados):**
  1. **`effect_category` é parâmetro obrigatório sem default (`add_effect_impl.py:10-11`) e não existe no schema MCP** → via MCP a tool sempre falha: `add_effect_impl() missing 1 required positional argument: 'effect_category'`. A rota HTTP escapa com default `"scene"`.
  2. **`params=None` explode**: `add_effect_impl.py:85` faz `params[::-1]`, e `None[::-1]` → `TypeError: 'NoneType' object is not subscriptable`. Verificado em **ambas** as fachadas. Só funciona passando `params: []`. Note que a biblioteca subjacente aceita `None` corretamente (`script_file.py:414-416`) — o bug é do wrapper.
  Efeito de personagem tem escopo global no código (`apply_target_type=2`), o que é semanticamente duvidoso para efeitos de rosto.
- **AC:** (a) `capcut.effect.add` funciona sem `params`; (b) `category` é obrigatório no schema e validado; (c) efeito inválido → `UNKNOWN_EFFECT` com sugestões; (d) efeito VIP → `warning`.

#### FX-02 — Definir intervalo na timeline
- **Status:** `SUPPORTED` — `start`/`end` (defaults 0 e 3.0) → `trange` (`add_effect_impl.py:40-42`).
- **Limitações:** dois efeitos na **mesma track** com intervalos sobrepostos → `SegmentOverlap` **na hora do add** (verificado) — comportamento correto, mas o agente precisa usar tracks distintas (`effect_01`, `effect_02`, …) para efeitos simultâneos.
- **AC:** (a) intervalo gravado em µs; (b) sobreposição → `SEGMENT_OVERLAP` com sugestão de usar outra track; (c) o L1 aloca automaticamente `effect_NN` quando `track` é omitido.

#### FX-03 — Configurar parâmetros disponíveis
- **Status:** `PARTIALLY_SUPPORTED`
- **Implementação atual:** `params: List[Optional[float]]`, faixa **0–100** na API (`video_segment.py:113`), convertida internamente. Os metadados expõem, por efeito, `name`, `default_value`, `min_value`, `max_value` — verificado: `Blur` → `[('effects_adjust_blur', 0.5, 0.0, 1.0)]`; `Zoom_Lens` → `[('effects_adjust_speed',…), ('effects_adjust_range',…)]`. A biblioteca valida quantidade e faixa (`ValueError`).
- **Parâmetros:** `params` array de float|null (posicional)
- **Retorno:** `params_applied[]` com nome, valor e default de cada parâmetro
- **Erros:** `INVALID_EFFECT_PARAMS` (quantidade acima do suportado, valor fora da faixa)
- **Dependências:** catálogo de parâmetros
- **Limitações (crítico):** **`add_effect_impl` inverte a lista (`params[::-1]`) antes de passar adiante.** A ordem documentada é a da annotation do enum; logo, para efeitos com 2+ parâmetros, a semântica do wrapper é o **inverso** da biblioteca. Para `Blur` (1 param) é inócuo; para `Zoom_Lens` (2 params) troca velocidade por alcance. Nenhuma documentação menciona isso. Além disso, `params` é **posicional** — não há forma de nomear o parâmetro.
- **AC:** (a) `capcut.catalog.effect_params(effect)` devolve nome/default/min/max na ordem canônica; (b) `capcut.effect.add` aceita `params` **por nome** (`{"effects_adjust_blur": 60}`) e resolve a ordem internamente; (c) a inversão do upstream é compensada e coberta por teste com efeito de 2+ parâmetros; (d) valor fora da faixa → `INVALID_EFFECT_PARAMS`.

#### FX-04 — Filtros (LUTs)
- **Status:** `REQUIRES_EXTENSION`
- **Implementação atual:** **468 filtros** no catálogo (`Filter_type`) e `Script_file.add_filter()` implementado (`script_file.py:443`), mas **nenhum impl, rota ou tool** os expõe (0 referências fora de `pyJianYingDraft/`). Não há nem endpoint de listagem.
- **Tool (v1):** — (candidato a v1.1: `capcut.filter.add`)
- **Parâmetros previstos:** `filter` string, `intensity` float, `timeline_start/end`, `track`
- **Erros previstos:** `UNKNOWN_FILTER`, `INVALID_INTENSITY`
- **Limitações:** exige track de filtro própria (`Filter_segment`); não testado.
- **AC (se entrar no escopo):** (a) catálogo de 468 filtros listável; (b) filtro aplicado aparece no JSON e no CapCut; (c) `intensity` validada.

---

### 8. Keyframes

#### KF-01..KF-04 — Posição, escala, rotação, opacity
- **Status:** `SUPPORTED` (os quatro)
- **Implementação atual:** `add_video_keyframe_impl()` valida e enfileira em `Track.pending_keyframes`; a materialização ocorre **no save**, via `process_pending_keyframes()`, que liga cada keyframe ao segmento que cobre aquele instante (`track.py:95-162`, chamado por `save_draft_impl.py:554-560`). Verificado no JSON gerado (`common_keyframes` no segmento correto).
- **Tool (v1):** `capcut.keyframe.add` · **Upstream:** `add_video_keyframe` · **Endpoint:** `POST /add_video_keyframe` ⛔macOS
- **Parâmetros:** `draft_id`, `track`, e **modo unitário** (`property`, `time`, `value`) **ou modo batch** (`properties[]`, `times[]`, `values[]` — mesmo comprimento)
- **Retorno:** `{ draft_id, keyframes_queued, bound_segments[] }` — o upstream devolve `added_keyframes_count` só no modo batch
- **Erros:** `DRAFT_NOT_FOUND`, `TRACK_NOT_FOUND`, `TRACK_EMPTY`, `UNKNOWN_KEYFRAME_PROPERTY`, `INVALID_KEYFRAME_VALUE`, `BATCH_LENGTH_MISMATCH`, `KEYFRAME_OUTSIDE_SEGMENT`
- **Dependências:** o segmento-alvo já deve existir na track
- **Limitações:**
  - **Unidades não óbvias**: `position_x/y` em "meia tela" (valor do app ÷ dimensão do canvas), Y positivo para cima; `rotation` em graus (aceita `"45deg"`); `alpha`/`volume` aceitam `"50%"`; `saturation/contrast/brightness` aceitam `"+0.5"`/`"-0.5"` (`keyframe.py:36-64`, `add_video_keyframe_impl.py:139-175`).
  - **`scale_x/scale_y` são mutuamente exclusivos com `uniform_scale`** — nada valida.
  - **Se nenhum segmento cobrir o instante, o keyframe é descartado com `print` — engolido pelo `capture_stdout` do MCP.** O agente recebe sucesso.
  - Nome de track errado → erro **em chinês**: `不存在名为 'video_main' 的轨道` (verificado).
  - `add_video_keyframe_impl` chama `get_or_create_draft(draft_id)` **sem** `width`/`height` → com id inválido cria um draft 1080×1920 fantasma.
  - Sem controle de curva/easing (o `Keyframe` tem apenas valor e tempo).
- **AC:** (a) keyframe fora de qualquer segmento → `KEYFRAME_OUTSIDE_SEGMENT`, nunca sucesso mudo; (b) `scale_*` + `uniform_scale` juntos → erro de exclusividade; (c) todas as unidades declaradas na descrição da tool; (d) mensagens de erro em português/inglês, nunca em chinês; (e) batch com listas de tamanhos diferentes → `BATCH_LENGTH_MISMATCH`.

#### KF-05 — Propriedades compatíveis
- **Status:** `SUPPORTED` (enumeração) — 11 propriedades: `position_x`, `position_y`, `rotation`, `scale_x`, `scale_y`, `uniform_scale`, `alpha`, `saturation`, `contrast`, `brightness`, `volume` (`keyframe.py:36-64`).
- **Limitações:** `alpha`, `saturation`, `contrast`, `brightness` são documentados como **válidos só para `Video_segment`**; `volume` para `Audio_segment` e `Video_segment`. Nada impede enfileirar uma propriedade inválida para o tipo de segmento.
- **AC:** (a) `capcut.catalog.list(kind="keyframe_property")` devolve as 11 com unidade, faixa e tipos de segmento compatíveis; (b) propriedade incompatível com o tipo do segmento → erro.

#### KF-06 — Keyframes fora de tracks de vídeo
- **Status:** `PARTIALLY_SUPPORTED` — **requer verificação empírica antes de ser declarado**
- **Implementação atual:** a tool chama `script.get_track(draft.Video_segment, track_name=...)`, mas com `track_name` informado a busca é um lookup direto no dicionário (`script_file.py:285-289`), **sem checar o tipo da track**. Logo, passar o nome de uma track de áudio provavelmente funciona e `volume` é válido para `Audio_segment` — porém isso **não foi testado**.
- **AC:** (a) teste empírico decide entre `SUPPORTED` e `NOT_SUPPORTED` para tracks de áudio/texto/sticker; (b) até então, o L1 aceita apenas tracks de vídeo e retorna `OPERATION_NOT_SUPPORTED` para as demais.

---

### 9. Media analysis

#### MED-01 — Detectar duração
- **Status:** `SUPPORTED` (verificado: WAV de 8 s → 8.00)
- **Implementação atual:** `get_duration_impl.get_video_duration()` → `ffprobe -show_entries stream=duration -show_entries format=duration`; prefere stream, cai para format; 3 tentativas, timeout 10 s, `FileNotFoundError` de ffprobe não é retentado (`get_duration_impl.py:5-99`)
- **Tool (v1):** `capcut.media.probe` · **Upstream:** `get_video_duration` · **Endpoint:** `POST /get_duration` ⛔macOS **e inexistente antes de `e4f45a0`** (retorna 404 em `71aafc1`)
- **Parâmetros:** `sources` array de caminhos/URLs *(o L1 deve aceitar lote; o upstream é unitário)*
- **Retorno:** `[{ source, exists, duration_s, width, height, kind, container, error }]`
- **Erros:** `FFPROBE_UNAVAILABLE`, `SOURCE_NOT_FOUND`, `PROBE_TIMEOUT`, `PROBE_FAILED`
- **Dependências:** **ffprobe no PATH** (presente na máquina auditada: `/opt/homebrew/bin/ffprobe`)
- **Limitações:** a tool upstream devolve só duração — **não** dimensões (que o `save_draft` obtém por um segundo ffprobe interno); URLs são baixadas parcialmente pelo ffprobe a cada chamada (custo de rede repetido, sem cache).
- **AC:** (a) duração correta para mp4/mov/wav/mp3/png; (b) ffprobe ausente → `FFPROBE_UNAVAILABLE` acionável; (c) probe em lote resolve N sources em uma chamada e o resultado é cacheado na sessão; (d) o retorno inclui dimensões.

#### MED-02 — Validar arquivo
- **Status:** `NOT_SUPPORTED`
- **Implementação atual:** **não existe validação.** `add_*` aceita qualquer string como `source` e apenas a usa como `remote_url`. A existência do arquivo só é consultada no save, em `download_file` (`downloader.py:110`), e **falha de download retorna `False`, que é contado como sucesso**: o valor é anexado a `downloaded_paths` e incrementa `completed_files` (`save_draft_impl.py:172-183`). Resultado: projeto sem a mídia, progresso 100%, nenhum erro.
- **Tool (v1):** `capcut.media.probe` (campos `exists`, `readable`)
- **Erros:** `SOURCE_NOT_FOUND`, `SOURCE_UNREADABLE`, `ASSET_FETCH_FAILED`
- **Limitações:** sem checagem de permissão, tamanho, integridade ou de mídia corrompida além do que o ffprobe acusar.
- **AC:** (a) `add` com caminho inexistente → `SOURCE_NOT_FOUND` **no add**, não no save; (b) qualquer asset que falhe no save → `ASSET_FETCH_FAILED` com a lista; (c) nenhum save reporta sucesso com asset faltando.

#### MED-03 — Validar formato
- **Status:** `NOT_SUPPORTED`
- **Implementação atual:** nenhuma. O nome do material é fixado por tipo (`.mp4`/`.mp3`/`.png`) independentemente do arquivo real, e arquivos locais são copiados com `shutil.copy2` **sem transcodificação**. Verificado: `tone.wav` → `audio_11c17dd7377d1ec3.mp3` contendo WAV. As funções que transcodificam (`download_audio`, `download_image`, via ffmpeg) existem mas **não são chamadas** por `save_draft_background`. As listas `SUPPORTED_*_FORMATS` do MCP TypeScript não são usadas para validar nada.
- **Tool (v1):** `capcut.media.probe` (campos `container`, `codec`, `kind`, `extension_matches_content`)
- **Erros:** `UNSUPPORTED_FORMAT`, `FORMAT_EXTENSION_MISMATCH` (warning por default)
- **Limitações:** **não se sabe se o CapCut aceita extensão trocada** (Unknown #7 da auditoria). Até haver teste, o L1 deve preservar a extensão real.
- **AC:** (a) `probe` reporta container/codec reais; (b) o asset gravado preserva a extensão real do arquivo de origem; (c) formato fora da allowlist → `UNSUPPORTED_FORMAT` no add.

---

## MCP Tool Contract

### Convenções

| Regra | Definição |
|---|---|
| Namespace | `capcut.<domínio>.<ação>` — `draft`, `video`, `audio`, `image`, `text`, `subtitle`, `effect`, `keyframe`, `media`, `catalog`, `project` |
| Schemas | JSON Schema estrito com `additionalProperties: false`. **Obrigatório**: o upstream repassa `**arguments` sem validação, então qualquer chave extra vira `TypeError`. |
| Tempo | Entradas em **segundos** (float); saídas sempre incluem o valor em **µs** (unidade interna do CapCut). |
| Cores | Hex `#RGB` ou `#RRGGBB`. |
| Enums | Nome canônico do catálogo. O L1 aceita case-insensitive e normaliza; o retorno informa o identificador canônico aplicado. |
| Idempotência | `draft.create` não é idempotente. Operações de mídia não são idempotentes (adicionar duas vezes cria dois segmentos). `draft.save` é idempotente para o mesmo estado, mas sobrescreve o destino apenas com `overwrite: true`. |
| Envelope | Toda tool retorna o mesmo envelope (abaixo). Nenhuma tool retorna URL externa. |

### Envelope de resposta

```json
{
  "ok": true,
  "data": { },
  "warnings": [
    { "code": "VIP_RESOURCE", "message": "…", "context": { } }
  ],
  "meta": { "draft_id": "dfd_cat_…", "tool": "capcut.video.add", "elapsed_ms": 12 }
}
```

```json
{
  "ok": false,
  "error": {
    "code": "SEGMENT_OVERLAP",
    "message": "O clipe 4.0s–9.0s colide com um segmento existente em 'video_main' (0.0s–6.0s).",
    "retryable": false,
    "suggestion": "Use timeline_start >= 6.0 ou adicione em outra track.",
    "context": { "track": "video_main", "conflicting_segment_id": "…" }
  },
  "warnings": [],
  "meta": { }
}
```

**Racional do `ok` no corpo:** o transporte MCP do upstream devolve erros como conteúdo de texto em resultados de sucesso, sem `isError`. O L1 deve **também** sinalizar erro no nível do protocolo (`isError: true`), mantendo o envelope para que o agente tenha causa e sugestão estruturadas.

### Inventário de tools da v1

| Tool | Status geral | Requisitos cobertos |
|---|---|---|
| `capcut.draft.create` | `SUPPORTED` | PRJ-01, PRJ-02, PRJ-03 |
| `capcut.draft.list` | `REQUIRES_EXTENSION` | PRJ-04 |
| `capcut.draft.inspect` | `REQUIRES_EXTENSION` | PRJ-07 |
| `capcut.draft.validate` | `REQUIRES_EXTENSION` | PRJ-07 |
| `capcut.draft.save` | `PARTIALLY_SUPPORTED` | PRJ-06 |
| `capcut.draft.rebuild` | `REQUIRES_EXTENSION` | VID-05, UF-2 |
| `capcut.video.add` | `SUPPORTED` | VID-01..04, 06..09 |
| `capcut.audio.add` | `SUPPORTED` | AUD-01..05 |
| `capcut.image.add` | `SUPPORTED` | IMG-01..04 |
| `capcut.text.add` | `SUPPORTED` | TXT-01..09 |
| `capcut.subtitle.add` | `PARTIALLY_SUPPORTED` | SUB-01..04 |
| `capcut.effect.add` | `PARTIALLY_SUPPORTED` | FX-01..03 |
| `capcut.keyframe.add` | `SUPPORTED` | KF-01..05 |
| `capcut.media.probe` | `SUPPORTED` (duração) / `NOT_SUPPORTED` (validação) | MED-01..03 |
| `capcut.catalog.list` | `REQUIRES_EXTENSION` | G3 (transições, efeitos, animações, fontes, máscaras, props de keyframe) |
| `capcut.catalog.effect_params` | `REQUIRES_EXTENSION` | FX-03 |
| `capcut.project.list` / `capcut.project.inspect` | `REQUIRES_EXTENSION` | PRJ-05 |

**Deliberadamente ausentes** (para não induzir o agente ao erro): qualquer tool de remover/mover/reordenar segmento, editar segmento existente, aplicar animação de loop de texto, renderizar vídeo, recarregar o CapCut, ou gerar `draft_url`.

### Descoberta de capacidades

`capcut.catalog.list(kind)` com `kind ∈ {transition, effect_scene, effect_character, animation_intro, animation_outro, animation_combo, text_animation, mask, font, audio_effect, keyframe_property, filter}`.

Retorno por item: `{ name, kind, is_vip, default_duration_us?, params?, notes? }`. Paginação obrigatória (`limit`/`offset`) — os catálogos maiores têm 345 e 468 itens, e uma lista inteira estoura o orçamento de contexto do agente. Deve suportar `query` (busca por substring) para que o agente peça "transições de fade" em vez de baixar 116 nomes.

### Configuração no Codex

```toml
# ~/.codex/config.toml  — formato a confirmar na doc do Codex antes de implementar
[mcp_servers.capcut]
command = "/caminho/para/venv/bin/python"
args    = ["/caminho/para/capcut-mcp-mac/server.py"]

[mcp_servers.capcut.env]
CAPCUT_PROJECTS_DIR = "/Users/<user>/Movies/CapCut/User Data/Projects/com.lveditor.draft"
CAPCUT_DRAFT_PROFILE = "capcut_legacy"
CAPCUT_REGISTRY_DIR = "/Users/<user>/Library/Application Support/capcut-mcp"
CAPCUT_LOG_LEVEL = "info"
```

Requisitos de compatibilidade de protocolo (a validar — Unknown #9 da auditoria): o servidor deve **ecoar a `protocolVersion` do cliente** quando suportada (o upstream fixa `"2024-11-05"`) e responder graciosamente a `prompts/list` / `resources/list` com lista vazia, em vez de `-32601`.

---

## Error Model

### Taxonomia

| Família | Códigos | Semântica | `retryable` |
|---|---|---|---|
| Entrada | `MISSING_REQUIRED_PARAM`, `INVALID_DIMENSIONS`, `INVALID_TIMERANGE`, `INVALID_COLOR`, `INVALID_VOLUME`, `INVALID_TRANSFORM`, `INVALID_FADE`, `INVALID_STYLE_RANGE`, `BATCH_LENGTH_MISMATCH`, `RATIO_MISMATCH` | O agente enviou algo inválido | não |
| Catálogo | `UNKNOWN_TRANSITION`, `UNKNOWN_EFFECT`, `UNKNOWN_ANIMATION`, `UNKNOWN_MASK`, `UNKNOWN_FONT`, `UNKNOWN_AUDIO_EFFECT`, `UNKNOWN_KEYFRAME_PROPERTY`, `UNKNOWN_FILTER`, `INVALID_EFFECT_PARAMS` | Identificador fora do catálogo | não (após corrigir o nome) |
| Estado | `DRAFT_NOT_FOUND`, `DRAFT_EMPTY`, `TRACK_NOT_FOUND`, `TRACK_EMPTY`, `SEGMENT_OVERLAP`, `KEYFRAME_OUTSIDE_SEGMENT`, `SOURCE_RANGE_EXCEEDS_MEDIA` | O pedido não é aplicável ao estado atual | não |
| Mídia | `SOURCE_NOT_FOUND`, `SOURCE_UNREADABLE`, `UNSUPPORTED_FORMAT`, `PROBE_FAILED`, `PROBE_TIMEOUT`, `ASSET_FETCH_FAILED`, `SRT_PARSE_ERROR`, `SRT_NOT_FOUND`, `SRT_FETCH_FAILED`, `IMAGE_UNREADABLE` | Problema com o arquivo/URL | às vezes (rede) |
| Ambiente | `FFPROBE_UNAVAILABLE`, `TARGET_DIR_NOT_FOUND`, `TARGET_EXISTS`, `PROJECT_LOCKED`, `TEMPLATE_MISSING`, `DISK_FULL`, `PERMISSION_DENIED` | Falta pré-requisito na máquina | sim, após ação do usuário |
| Contrato | `OPERATION_NOT_SUPPORTED`, `UNSUPPORTED_STYLE`, `VALIDATION_FAILED` | Pedido fora da capacidade declarada | não |
| Interno | `UPSTREAM_ERROR`, `INTERNAL_ERROR` | Exceção não mapeada do L0 | não |

### Regras

| # | Regra |
|---|---|
| E1 | **Proibido sucesso vazio.** Se a operação não produziu o efeito pedido, é erro. Alvo direto da falha `save_draft` → `success: true` + `draft_url: null` + zero bytes. |
| E2 | **Toda exceção do L0 é traduzida.** `TypeError: missing 1 required positional argument: 'effect_category'` → `MISSING_REQUIRED_PARAM`. `NameError: font_type` → `MISSING_FONT`. Nenhuma mensagem crua do Python chega ao agente. |
| E3 | **Zero mensagens em chinês.** Mapear as do L0 (`不存在名为 'X' 的轨道` → `TRACK_NOT_FOUND`). |
| E4 | **Todo erro carrega `suggestion` acionável.** Para erros de catálogo, incluir até 3 candidatos por distância de edição. |
| E5 | **Atomicidade por chamada.** Se a operação falhar, o draft volta ao estado anterior. Necessário porque o L0 cria tracks *antes* de falhar (comprovado em `add_subtitle`). |
| E6 | **Erro no protocolo e no envelope.** `isError: true` no resultado MCP **e** `ok: false` no corpo. |
| E7 | **Nenhum erro é silenciado por `except:` nu.** O L0 tem dezenas; o L1 não adiciona nenhum. |

---

## File Handling

### Resolução do diretório de projetos do CapCut (macOS)

Ordem de precedência:

1. `CAPCUT_PROJECTS_DIR` (env) — sempre vence.
2. `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` — **caminho real do CapCut International no macOS**, evidenciado pelo `draft_fold_path` do template capturado de uma instalação real (`template/draft_meta_info.json`).
3. `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft` — fallback (aparece no `__main__` de `save_draft_impl.py:742`).
4. `~/Library/Containers/com.lemon.lvpro/Data/Documents/JianyingPro/User Data/Projects/com.lveditor.draft` — **o único que o upstream consulta** (`save_draft_impl.py:259`); é do Jianying Pro chinês, sandboxed. Mantido por último, para compatibilidade.

Se nenhum existir: `TARGET_DIR_NOT_FOUND` com instrução para instalar o CapCut ou definir a env. **Nunca** cair para o diretório do repositório.

### Layout de saída

```
<CAPCUT_PROJECTS_DIR>/<project_name>/
├── draft_info.json          ← perfil capcut_legacy
├── draft_info.json.bak      ← deve ser sincronizado com o conteúdo (hoje é estático)
├── draft_meta_info.json     ← REESCRITO pelo L1 (ver abaixo)
├── assets/{video,image,audio}/<tipo>_<sha256[:16]>.<ext real>
└── (demais arquivos do template)
```

### Regras

| # | Regra | Motivo |
|---|---|---|
| F1 | `draft_folder` sempre explícito, resolvido pelo L1. | O default do L0 escreve no repositório clonado, não ignorado pelo git. |
| F2 | Salvar **diretamente** no diretório de projetos do CapCut. | Os `path` dos materiais são absolutos e apontam para o diretório de salvamento; copiar a pasta depois deixa a mídia apontando para o lugar antigo. |
| F3 | Nunca `rmtree` sem `overwrite: true` explícito. | O L0 apaga o destino sem perguntar (`save_draft_impl.py:81-83`). |
| F4 | `project_name` sanitizado: sem `/`, `..`, sem caminho absoluto; unicode NFC. | `read_project` do L0 aceita caminho absoluto (`capcut_server.py:875`). |
| F5 | **Reescrever `draft_meta_info.json`**: `draft_name`, `draft_fold_path`, `draft_root_path`, `draft_id` (UUID v4 novo), `tm_draft_create/modified` (µs atuais), `tm_duration`. | Hoje é byte-idêntico ao template: nome `0707`, paths de outro usuário, **mesmo UUID em todo projeto**. |
| F6 | Gerar `draft_cover.jpg` (primeiro frame via ffmpeg) ou remover a referência. | O template CapCut referencia um arquivo que não existe. |
| F7 | Preservar a extensão real do asset. | Hoje tudo vira `.mp4`/`.mp3`/`.png`; verificado WAV nomeado `.mp3`. |
| F8 | Nome do asset = `<tipo>_<sha256(source)[:16]>.<ext>`, mantendo a dedup por hash. | Comportamento do L0 que vale preservar: mesmo source → um material. |
| F9 | Verificar `.locked` antes de escrever; `PROJECT_LOCKED` se presente. | Indica projeto aberto no app; o autosave sobrescreveria a gravação. |
| F10 | Checar espaço em disco antes de copiar assets. | O save copia todos os arquivos; falha no meio deixa projeto parcial. |
| F11 | `source` local é validado no **add**, não no save. | O L0 só descobre no save, e trata falha como sucesso. |
| F12 | Assets remotos passam por allowlist de esquema (`https`, `http` opcional) e host. | Ver Security. |

---

## Draft Lifecycle

```
      capcut.draft.create
              │
              ▼
       ┌─────────────┐   add_* (video/audio/image/text/subtitle/effect/keyframe)
       │   DRAFTING  │◀──────────────────────────────────┐
       │ (em memória │                                   │
       │  + registry)│───────────────────────────────────┘
       └──────┬──────┘
              │ capcut.draft.validate
              ▼
       ┌─────────────┐   issues de severidade "error"
       │  VALIDATED  │◀──────── não ──── VALIDATION_FAILED (volta a DRAFTING)
       └──────┬──────┘
              │ capcut.draft.save
              ▼
       ┌─────────────┐
       │   SAVING    │  resolve metadados (ffprobe) → copia assets →
       │ (bloqueante)│  aplica keyframes pendentes → grava JSON + meta
       └──────┬──────┘
              │
              ▼
       ┌─────────────┐   próximo passo é HUMANO:
       │   SAVED     │   abrir/voltar à Home do CapCut
       └──────┬──────┘
              │ novo add_* no mesmo draft_id  → volta a DRAFTING (DIRTY)
              │ ⚠️ regravar por cima de projeto aberto no app é sobrescrito
              ▼
       ┌─────────────┐
       │  ABANDONED  │  TTL da sessão / draft.discard
       └─────────────┘
```

### Regras de ciclo de vida

| # | Regra |
|---|---|
| D1 | O `draft_id` é emitido por `create` e é o único handle. Nenhuma outra tool o cria. |
| D2 | Toda tool com `draft_id` desconhecido → `DRAFT_NOT_FOUND`. **Nunca** criar draft implicitamente (comportamento atual do L0 em *todos* os `add_*`). |
| D3 | O registry persiste `{draft_id, name, canvas, plano[], estado, timestamps}` em disco, fora do repositório, sobrevivendo a reinício do servidor MCP. |
| D4 | Após reinício, um draft do registry é **reconstruído a partir do plano** (replay) antes de qualquer mutação; se o replay falhar, `DRAFT_NOT_FOUND` com o motivo. |
| D5 | `save` não encerra o draft: ele volta a `DRAFTING` na próxima mutação, e o próximo `save` exige `overwrite: true`. |
| D6 | Keyframes são **pendentes** até o save (comportamento do L0). `inspect` deve distinguir `keyframes_pending` de `keyframes_applied`. |
| D7 | A resolução de duração e o passe de sobreposição do L0 rodam no save e **podem alterar o timeline**. O L1 executa a validação equivalente **antes**, e o `save` compara o resultado: qualquer segmento perdido no save é `INTERNAL_ERROR`, não silêncio. |
| D8 | `draft.discard(draft_id)` remove do registry e da memória; não toca em arquivos já salvos. |

---

## Validation

Dois níveis: **schema** (rejeição imediata) e **modelo** (`capcut.draft.validate`).

### Regras do validador de modelo

| Código | Severidade | Regra | Origem |
|---|---|---|---|
| `V_OVERLAP` | error | Dois segmentos na mesma track se sobrepõem (após resolução de duração real) | O L0 resolve isso **apagando** o segmento posterior; verificado: 3 clipes → 1 |
| `V_ZERO_DURATION` | error | Segmento com duração 0 ou negativa | Duração diferida deixa segmentos degenerados |
| `V_RANGE_EXCEEDS_MEDIA` | error | `source_end` > duração real da mídia | O L0 encurta em silêncio no save |
| `V_MISSING_ASSET` | error | `source` inexistente/ilegível | O L0 conta falha de download como sucesso |
| `V_KEYFRAME_ORPHAN` | error | Keyframe cujo instante não cai em nenhum segmento da track | O L0 descarta com `print` engolido |
| `V_EMPTY_DRAFT` | error | Nenhum segmento em nenhuma track | `save` produziria projeto vazio |
| `V_EMPTY_TRACK` | warning | Track criada sem segmentos | O L0 cria a track `video` vazia sempre, e a `subtitle` quando `add_subtitle` falha |
| `V_BASE_TRACK_NOT_AT_ZERO` | warning | Primeiro segmento da track de vídeo base não começa em 0 | O CapCut força o alinhamento (`script_file.py:250-252`) |
| `V_GAP` | info | Buraco entre segmentos consecutivos | Provavelmente não intencional |
| `V_VIP_RESOURCE` | warning | Recurso com `is_vip: true` | Metadado existe; nenhum `add_*` o consulta |
| `V_TEXT_UNSAFE_ZONE` | warning | Texto com `\|transform_y\| > 0.85` | Recomendação do skill `capcut-director` |
| `V_TEXT_SIZE_SUSPECT` | warning | `font_size > 20` ou `< 3` | Escala interna ~5–15; docs do upstream sugerem 48 |
| `V_TEXT_LOW_CONTRAST` | info | Texto sobre vídeo sem borda nem background | Defaults do upstream são 0.0 para ambos |
| `V_RATIO_INEXACT` | warning | `width/height` não corresponde a 9:16, 16:9 ou 1:1 | O rótulo gravado será incorreto (1080×1350 → "9:16") |
| `V_TRANSITION_TOO_LONG` | warning | Duração da transição ≥ duração de um dos clipes adjacentes | Nada valida no L0 |
| `V_SCALE_CONFLICT` | error | `uniform_scale` junto com `scale_x`/`scale_y` no mesmo segmento | Mutualmente exclusivos por doc (`keyframe.py:48-53`) |
| `V_EXT_MISMATCH` | warning | Extensão do asset gravado ≠ conteúdo real | Comportamento atual do L0 |

### Política

- `save` recusa por default com qualquer `error` (`VALIDATION_FAILED`, com a lista completa).
- `save(force: true)` ignora `error` **exceto** `V_MISSING_ASSET` e `V_EMPTY_DRAFT`.
- `warning`/`info` nunca bloqueiam, mas viajam no campo `warnings[]` da resposta.
- **O validador precisa das durações reais**, portanto `validate` executa/usa o cache de `media.probe`.

---

## Observability

| # | Requisito | Motivo |
|---|---|---|
| O1 | **Capturar o stdout do L0 e convertê-lo em `warnings[]` estruturados.** O `mcp_server.py` atual envolve as chamadas em `capture_stdout()` e **descarta** o conteúdo (`mcp_server.py:258-267`), apagando avisos de keyframe descartado, download falho, fallback de dimensão e segmento deletado. | Maior lacuna de observabilidade do sistema |
| O2 | Log estruturado (JSONL) em `~/Library/Logs/capcut-mcp/`, com `session_id`, `draft_id`, `tool`, `elapsed_ms`, `ok`, `error.code`. | Diagnóstico sem repetir a sessão |
| O3 | **Nada do log vai para stdout.** Só stderr e arquivo. | stdout é o canal do JSON-RPC; qualquer `print` corrompe o protocolo |
| O4 | `capcut.draft.inspect` retorna o estado real: tracks, segmentos com ids e timeranges, materiais, keyframes pendentes vs. aplicados, duração total. | Auto-verificação do agente (G7) |
| O5 | `save` retorna manifest: arquivos escritos, assets copiados com tamanho, duração final, avisos. | Permite ao agente confirmar o efeito |
| O6 | Progresso de operações longas (downloads) via log; o save é sincrono e pode levar minutos. | Timeout de tool call no cliente |
| O7 | `capcut.system.doctor`: versões (Python, ffprobe, commit do L0), diretórios resolvidos, permissões, presença do CapCut. | Primeiro passo de qualquer troubleshooting |
| O8 | Correlacionar `warnings` a `segment_id`/`track`. | Aviso sem alvo é inútil para o agente |

---

## Security Considerations

| # | Consideração | Decisão |
|---|---|---|
| S1 | **Travessia de caminho arbitrária.** `GET /preview/media?path=` serve qualquer arquivo do disco sem restrição (`web_preview.py:178-188`). | `web_preview.py` **não é usado** (N4). O L1 não expõe nenhuma superfície HTTP. |
| S2 | **SSRF.** Os `add_*` aceitam qualquer URL e o processo a busca, com `User-Agent`/`Referer` falsificados hardcoded (`downloader.py:150-155`). | Allowlist de esquema (`https` por default) e bloqueio de IPs privados/loopback/link-local e de `file://`. `http` só com opt-in explícito. |
| S3 | **`ffprobe`/`ffmpeg` recebem strings controladas pelo chamador.** | Sempre via `subprocess` com lista de argumentos (o L0 já faz), nunca `shell=True`. Validar o `source` antes. Timeout obrigatório. |
| S4 | **Escrita fora do destino pretendido.** `project_name` não sanitizado permite subir diretórios. | F4 + recusa de caminho absoluto e de `..`. |
| S5 | **Destruição de dados.** `save` faz `rmtree` do destino; `Draft_folder.remove()` também existe. | `overwrite` explícito; nunca expor uma tool de remoção de projeto na v1. |
| S6 | **Identificadores fabricados.** O bloco `platform` do draft carrega `device_id`, `mac_address` e `hard_disk_id` **de outra máquina** (`settings/__init__.py`, `draft_profiles.py:22-31`). | Documentar. Não randomizar sem saber como o CapCut reage (Unknown). Não enviar nada a serviços externos. |
| S7 | **Segredos.** `config.json` guarda chaves de OSS em texto claro. | O L1 não usa OSS; `is_upload_draft` deve ser forçado a `false`. |
| S8 | **Execução de conteúdo de terceiros.** SRT/JSON vindos de URL são dados, não código. | Nunca `eval`; limite de tamanho de download; timeout. |
| S9 | **Prompt injection via mídia/SRT.** Conteúdo de arquivo pode conter texto que o agente interprete como instrução. | O L1 devolve conteúdo de arquivo como dado rotulado; a orientação de não seguir instruções embutidas é do lado do agente. |
| S10 | **Superfície de rede zero.** | stdio apenas. Nenhuma porta aberta, nenhum bind, nem em localhost. |
| S11 | **Permissões do macOS.** `~/Movies` pode exigir consentimento (TCC) dependendo do contexto de execução. | `doctor` detecta e explica; `PERMISSION_DENIED` acionável. |

---

## Compatibility Strategy

### Upstream (VectCutAPI)

| # | Estratégia |
|---|---|
| C1 | **Fork com commit fixo.** `b83be74` para o caminho MCP. Nunca seguir `main` automaticamente: a regressão de macOS tem 2 dias e entrou por um PR Windows-only de 5.548 linhas. |
| C2 | **Não modificar o L0.** Todas as correções no L1, para manter o merge trivial. |
| C3 | **Módulos proibidos**, verificados por teste de import: `capcut_server`, `web_preview`, `desktop_companion`, `jianying_controller`, `jianying_ui_inspector`, `mcp-server/`. |
| C4 | **Teste de contrato do L0**: um teste que chama cada função `add_*` com os parâmetros que o L1 usa e compara o JSON gerado com um snapshot. Roda a cada atualização do fork. |
| C5 | **Congelar `settings/local.py`** via `config.json` próprio: `draft_profile`, `is_upload_draft: false`. Lembrar que falha de parse do `config.json` é engolida por `except: pass` — o `doctor` deve reler e confirmar os valores efetivos. |
| C6 | Se o upstream corrigir um bug que o L1 contorna, o contorno vira no-op idempotente, não é removido às cegas. |

### CapCut Desktop

| # | Estratégia |
|---|---|
| C7 | **Probe de versão antes de qualquer escrita.** Ler um projeto real existente e detectar: nome do arquivo de conteúdo (`draft_info.json` vs `draft_content.json`), presença de `Timelines/<uuid>/`, `new_version`, `app_version`. Registrar como "perfil detectado". |
| C8 | **Matriz de compatibilidade** mantida no repositório: versão do CapCut × perfil que funciona × resultado observado. A auditoria só estabelece que o template foi capturado de um CapCut mac com `app_version 6.5.0` / `new_version 138.0.0`. |
| C9 | **Contradição não resolvida, tratada como risco explícito.** O perfil `capcut_legacy` grava `draft_info.json` sem `Timelines/`; o skill `capcut-director` afirma que CapCut 9.x+ lê `Timelines/<uuid>/draft_content.json` e que só a raiz abre timeline vazio; `list_projects`/`read_project`/`web_preview` procuram `draft_content.json`. Antes de escrever código, **testar `capcut_legacy` e `jianying_pro_10`** e adotar o que abrir corretamente. |
| C10 | **Não regredir a versão do schema.** Hoje o conteúdo sai com `new_version: "110.0.0"` (de `pyJianYingDraft/draft_content_template.json`) enquanto o template real diz `138.0.0`. O L1 deve escrever a versão observada na instalação do usuário, ou a do template, e registrar a decisão. |
| C11 | **Escrever espelhos coerentes.** `draft_info.json.bak` e os `.tmp` hoje ficam com o conteúdo do projeto do autor original. Sincronizar ou remover, conforme o teste C9 indicar. |
| C12 | **Nunca escrever em projeto com `.locked`**, e nunca durante autosave: o app não tem file watcher e sobrescreve o disco com o estado em memória. |
| C13 | Se o probe C7 não reconhecer a instalação: `save` em modo `target="path"` + aviso, em vez de escrever no diretório do CapCut às cegas. |

### Codex / MCP

| # | Estratégia |
|---|---|
| C14 | Ecoar a `protocolVersion` do cliente quando suportada; responder `prompts/list`/`resources/list` com lista vazia. |
| C15 | Schemas com `additionalProperties: false` e descrições que contenham as unidades (µs vs s, escala de fonte, unidade de transform). O agente acerta na proporção da qualidade das descrições. |
| C16 | Catálogos sempre paginados/filtráveis — 345 efeitos e 468 filtros não cabem no contexto. |
| C17 | Operações longas (`save`) documentadas como tal, com `elapsed_ms` no retorno; considerar um `save` assíncrono com `job_id` se o cliente tiver timeout curto. |

---

## Acceptance Criteria

### Portão 0 — Pré-requisito de viabilidade (bloqueia tudo)

| # | Critério |
|---|---|
| AC0.1 | Um draft gerado pelo pipeline **aparece na lista de projetos do CapCut macOS instalado**, com o nome pedido. |
| AC0.2 | O projeto **abre** e o timeline contém os segmentos esperados nas posições esperadas. |
| AC0.3 | Toda a mídia é **encontrada** pelo app (nenhum material faltando). |
| AC0.4 | O perfil vencedor entre `capcut_legacy` e `jianying_pro_10` está determinado e registrado na matriz C8. |
| AC0.5 | Dois projetos gerados coexistem na biblioteca sem conflito (questão do `draft_id` UUID duplicado). |

**Se AC0.1–AC0.3 falharem para ambos os perfis, esta spec é suspensa** e o problema volta para investigação de formato (ver Unknowns da auditoria).

### Portão 1 — Contrato MCP

| # | Critério |
|---|---|
| AC1.1 | `tools/list` expõe apenas as tools do inventário, com schemas estritos e descrições que declaram unidades. |
| AC1.2 | Nenhuma tool proibida é exposta (reordenar, remover, renderizar, recarregar, `draft_url`). |
| AC1.3 | Toda tool responde no envelope padrão; erro vem com `isError: true` **e** `ok: false`. |
| AC1.4 | Nenhuma resposta contém mensagem crua do Python, texto em chinês, ou URL externa. |
| AC1.5 | Handshake bem-sucedido com o cliente MCP do Codex, incluindo eco de `protocolVersion`. |

### Portão 2 — Correção dos defeitos herdados

| # | Critério | Defeito coberto |
|---|---|---|
| AC2.1 | `capcut.subtitle.add` sem `font` retorna `MISSING_FONT`; com `font` válida importa todos os blocos. | `NameError: font_type` |
| AC2.2 | `capcut.effect.add` funciona sem `params` e com `category` obrigatório validado. | `params[::-1]` + `effect_category` ausente do schema |
| AC2.3 | `capcut.effect.add` com efeito de 2+ parâmetros aplica os valores na ordem canônica. | Inversão de `params` |
| AC2.4 | `capcut.draft.save` com `draft_id` inválido retorna `DRAFT_NOT_FOUND` e escreve zero bytes. | `success: true` + `draft_url: null` |
| AC2.5 | Três clipes adicionados sem duração explícita → erro/probe automático; **nunca** perda silenciosa de segmentos. | 3 clipes → 1 sobrevivente |
| AC2.6 | Keyframe fora de segmento → `KEYFRAME_OUTSIDE_SEGMENT`. | Descarte com `print` engolido |
| AC2.7 | Asset que falha no save → `ASSET_FETCH_FAILED` com a lista. | `download_file → False` contado como sucesso |
| AC2.8 | `draft_meta_info.json` gravado tem nome, paths e UUID próprios. | Metadados do autor original |
| AC2.9 | Nenhum arquivo é escrito dentro do clone do VectCutAPI em nenhum fluxo. | Default de `output_base_dir` |
| AC2.10 | JSON final não contém track vazia espúria. | Track `video` sempre criada; `subtitle` órfã |
| AC2.11 | Asset preserva a extensão real do arquivo de origem. | WAV nomeado `.mp3` |
| AC2.12 | Nome de track é único em todas as tools (sem `main` vs `video_main`). | Defaults divergentes entre fachadas |

### Portão 3 — Cobertura funcional

| # | Critério |
|---|---|
| AC3.1 | Todo requisito `SUPPORTED` tem teste automatizado que verifica o JSON gerado. |
| AC3.2 | Todo requisito `PARTIALLY_SUPPORTED` tem teste do caminho felizardo **e** teste que prova que o modo quebrado agora retorna erro estruturado. |
| AC3.3 | Todo requisito `REQUIRES_EXTENSION`/`NOT_SUPPORTED` é rejeitado com `OPERATION_NOT_SUPPORTED` + sugestão, nunca silenciosamente ignorado. |
| AC3.4 | Um projeto de referência com os 9 domínios é gerado, validado e conferido visualmente no CapCut. |
| AC3.5 | `capcut.draft.validate` detecta todas as 17 regras da seção Validation em casos sintéticos. |
| AC3.6 | Os catálogos retornam as contagens verificadas: 345/95 efeitos, 116 transições, 43/23/108 animações, 76/68/53 de texto, 9 máscaras, 335 fontes, 29 efeitos de áudio, 11 propriedades de keyframe, 468 filtros. |
| AC3.7 | `pytest` do fork passa 14/14 (hoje 11/14 no macOS) ou os 3 testes Windows são explicitamente marcados como skip por plataforma. |

### Portão 4 — Operação

| # | Critério |
|---|---|
| AC4.1 | `capcut.system.doctor` diagnostica ffprobe ausente, diretório do CapCut ausente e permissão negada, com instrução de correção. |
| AC4.2 | O `draft_id` sobrevive a reinício do servidor MCP (registry + replay do plano). |
| AC4.3 | Nenhuma porta de rede é aberta (verificável por `lsof`). |
| AC4.4 | Logs em JSONL, com stdout limpo (o protocolo nunca corrompido). |
| AC4.5 | Save de projeto com 30+ segmentos completa em tempo documentado, com manifest completo. |

---

## Future Extensions

| Prioridade | Extensão | Pré-requisito |
|---|---|---|
| P1 | `capcut.draft.rebuild` completo (editar/reordenar/remover via replay do plano) | Plano declarativo (A5) |
| P1 | `capcut.filter.add` — 468 filtros já catalogados, `add_filter` já implementado na lib | Teste de aceitação no CapCut |
| P1 | Tabela calibrada de `font_size` e presets tipográficos (título/subtítulo/legenda) | Teste empírico de escala |
| P2 | Animação de loop de texto (53 opções catalogadas, sem parâmetro) | Extensão do `add_text_impl` no L1 |
| P2 | Fade de áudio e ducking automático (`Audio_fade` já existe na lib) | Acesso ao `Audio_segment` no L1 |
| P2 | `capcut.project.open` — mutação de projeto existente via `load_template`/`replace_*` | Resolver o modelo de imported tracks |
| P2 | Catálogo de stickers e de bolhas/花字 (hoje exigem IDs opacos) | Fonte confiável de `resource_id` |
| P3 | Presets de alto nível (`capcut.preset.apply` — reel, talking-head, slideshow) | Portão 3 completo |
| P3 | Preview server-side (render de frames por ffmpeg a partir do draft) | Parser próprio do timeline |
| P3 | Exportação headless (FFmpeg a partir do draft, sem CapCut) | Reimplementação da semântica de render |
| P3 | Automação de UI do CapCut no macOS (Accessibility API) para abrir/exportar | Projeto separado; fora do espírito desta spec |
| P4 | Suporte a Jianying e a Windows | Matriz de compatibilidade multiplataforma |
| P4 | Sincronização bidirecional com edições humanas | Requer entender o autosave do CapCut |
| P4 | Alinhamento a frame e snap de legendas a cortes | Modelo temporal em frames |

---

## Anexo A — Rastreabilidade

| Requisito | Evidência no código | Verificação empírica |
|---|---|---|
| PRJ-01/02 | `create_draft.py:6-24`, `script_file.py:189-210` | `create_draft` via MCP stdio ✔ |
| PRJ-03 | `draft_profiles.py:110-118` | 1080×1350 → rótulo `9:16` ✔ |
| PRJ-04 | `create_draft.py:16,37-44`, `draft_cache.py` | draft_id novo por processo; id desconhecido cria outro draft ✔ |
| PRJ-05 | `script_file.py:214,641,696,734,780`, `draft_folder.py` | `load_template` sem consumidor fora de `draft_folder.py` ✔ |
| PRJ-06 | `save_draft_impl.py:42-278` | save em `draft_folder` ✔; `success:true`+`null` com id inválido ✔ |
| PRJ-07 | `save_draft_impl.py:520-544,561-584` | 3 clipes → 1 segmento ✔ |
| VID-01..09 | `add_video_track.py:10-215` | add local ✔; `fade_in` falha / `Mix` ok ✔; `circle` falha / `Circle` ok ✔; track `video` vazia ✔ |
| AUD-01..05 | `add_audio_track.py:11-151`, `audio_segment.py:22,189` | WAV → `.mp3` ✔; 0 ocorrências de "fade" ✔ |
| IMG-01..04 | `add_image_impl.py:11-238`, `save_draft_impl.py:419-429` | PNG 400×400 no JSON ✔ |
| TXT-01..09 | `add_text_impl.py:10-289`, `text_segment.py:47-72` | add_text ✔; 0 ocorrências de "loop" ✔ |
| SUB-01..04 | `add_subtitle_impl.py:9-169`, `script_file.py:469-604` | `NameError` sem font ✔; ok com `font="Amigate"`, 2 blocos ✔ |
| FX-01..04 | `add_effect_impl.py:10-90`, `script_file.py:414-441`, `video_segment.py:110-120` | `effect_category` ausente ✔; `params=None` explode ✔; `params=[]` ok ✔; `Blur`/`Zoom_Lens` params ✔; 468 filtros ✔ |
| KF-01..06 | `add_video_keyframe_impl.py`, `track.py:95-162`, `keyframe.py:36-64` | keyframe ligado ao segmento correto ✔; erro em chinês ✔ |
| MED-01..03 | `get_duration_impl.py`, `downloader.py:110-190`, `save_draft_impl.py:172-183` | ffprobe 8.00s ✔; cópia sem transcode ✔ |
| macOS | `desktop_companion.py:15`, `capcut_server.py:40`, `web_preview.py:13,17` | `import capcut_server` falha em `b83be74`, ok em `71aafc1` ✔ |

## Anexo B — Itens que precisam de decisão antes de implementar

| # | Questão | Quem decide | Impacto |
|---|---|---|---|
| Q1 | Perfil de draft para CapCut macOS: `capcut_legacy` ou `jianying_pro_10`? | teste AC0.4 | estrutura de arquivos inteira |
| Q2 | Escrever `new_version` observado na instalação, ou manter `110.0.0`? | teste AC0.2 | compatibilidade do schema |
| Q3 | Randomizar `device_id`/`mac_address` no bloco `platform`, ou manter os do autor? | teste + política | aceitação pelo app; privacidade |
| Q4 | Faixa válida de `volume` (0–1, 0–2?) e de `font_size` | calibração empírica | validação de entrada |
| Q5 | `save` sincrono ou assíncrono com `job_id`? | timeout do cliente Codex | contrato da tool |
| Q6 | `http` permitido para sources remotos, ou só `https`? | política de segurança | S2 |
| Q7 | Onde fica o registry de drafts (`~/Library/Application Support/...`)? | convenção do projeto | D3 |
| Q8 | O adaptador vive em repositório próprio ou como diretório no fork? | organização | C2 |
