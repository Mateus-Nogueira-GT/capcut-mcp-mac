# VectCutAPI — Auditoria Técnica para Automação do CapCut via MCP (macOS)

**Repositório auditado:** `sun-guannan/VectCutAPI`
**Commit:** `b83be74` (`Merge pull request #81 from sun-guannan/dev`, 2026-09-12)
**Clone local:** `/Users/mateusnascimentonogueiradasilva/MCP Capcut/VectCutAPI` (nenhum arquivo do repositório foi alterado)
**Data da auditoria:** 2026-09-14
**Ambiente de teste:** macOS 15 (Darwin 24.6.0), Apple Silicon, Python 3.14, ffmpeg/ffprobe 
**Licença:** Apache 2.0 (arquivo `LICENSE`) — note que `pyproject.toml` declara MIT (metadado inconsistente)

> Metodologia: leitura integral do código-fonte relevante + execução empírica. Foi criado um venv isolado fora do repositório, as dependências reais foram instaladas, o servidor MCP foi exercitado pelo protocolo JSON-RPC real via stdio, os endpoints HTTP foram exercitados via `Flask test_client`, e drafts reais foram gerados e inspecionados. O README **não** foi tratado como fonte de verdade — e, de fato, divergiu da implementação em vários pontos.

---

## Executive Summary

VectCutAPI é um **gerador de arquivos de projeto ("draft") do CapCut/CapCut-Jianying**, não um controlador do CapCut. Ele monta em memória a estrutura JSON interna de um projeto do CapCut (tracks, materiais, segmentos, keyframes, efeitos) e grava uma pasta de projeto no disco. O CapCut Desktop nunca é pilotado, consultado ou renderizado por ele: a última milha é copiar a pasta para o diretório de projetos do CapCut e abrir o app manualmente.

O núcleo (`pyJianYingDraft` + módulos `add_*_impl.py`) é surpreendentemente completo e de boa qualidade: 345 efeitos de cena, 95 efeitos de personagem, 116 transições, 174 animações de entrada/saída/combo, 197 animações de texto, 335 fontes, 9 máscaras, keyframes em 11 propriedades, multi-track, multi-estilo de texto. Isso é real e funciona.

Porém, **o estado atual do `main` tem três problemas que impedem o uso direto como base de automação no macOS**, todos confirmados empiricamente:

1. **`capcut_server.py` (a API HTTP) não inicia no macOS.** O commit `e4f45a0` (mergeado 2 dias antes desta auditoria) introduziu `desktop_companion.py`, que executa `ctypes.windll.user32` no import — API exclusiva do Windows. `capcut_server.py:40` e `web_preview.py:13` importam esse módulo no topo. Resultado: `AttributeError: module 'ctypes' has no attribute 'windll'`. Todo o caminho HTTP (e o MCP em TypeScript, que é um cliente HTTP) está morto no macOS. O commit anterior (`71aafc1`) importa e responde normalmente — verificado.
2. **O caminho de "auto-deploy para o CapCut" no macOS aponta para o app errado.** O código procura `~/Library/Containers/com.lemon.lvpro/.../JianyingPro/User Data/Projects/com.lveditor.draft` (Jianying Pro chinês, sandboxed), enquanto o próprio template do repositório foi capturado de um CapCut International em `~/Movies/CapCut/User Data/Projects/com.lveditor.draft`. Quando o diretório não existe, o deploy é **silenciosamente ignorado**.
3. **Duas das 11 tools MCP estão quebradas com os parâmetros documentados**: `add_effect` (falta `effect_category`, que não existe no schema) e `add_subtitle` (`NameError: font_type` quando `font` é omitido — e o schema marca `font` como opcional).

Além disso, há um modo de falha silenciosa grave para agentes: `save_draft` retorna `success: true` com `draft_url: null` **sem escrever nada** quando o `draft_id` não está no cache em memória do processo (servidor reiniciado, outra sessão, ou uso cruzado HTTP↔MCP).

**Veredito: `GO WITH RESTRICTIONS`** — usar **apenas** o servidor MCP em Python (`mcp_server.py`), que funciona no macOS, com um wrapper/fork próprio que corrija os bugs conhecidos, force `draft_folder` explícito e injete um catálogo de nomes de enums. Detalhes em *Recommendations*.

---

## Architecture

### Visão geral (1)

```
                       ┌──────────────────────────────────────────────┐
                       │            pyJianYingDraft/ (5.2k LOC)       │
   Camada de modelo    │  Script_file, Track, *_segment, *_material,  │
                       │  Keyframe, metadata/ (catálogos de enums)    │
                       └──────────────▲───────────────────────────────┘
                                      │ (in-process)
                       ┌──────────────┴───────────────────────────────┐
   Camada de lógica    │  add_video_track / add_audio_track /         │
   (verbos da API)     │  add_image_impl / add_text_impl /            │
                       │  add_subtitle_impl / add_effect_impl /       │
                       │  add_sticker_impl / add_video_keyframe_impl /│
                       │  get_duration_impl / save_draft_impl         │
                       └───▲──────────────────────────────────▲───────┘
                           │                                  │
          ┌────────────────┴───────┐        ┌─────────────────┴──────────────┐
 Fachadas │ mcp_server.py (Python) │        │ capcut_server.py (Flask, 29    │
          │ JSON-RPC stdio, 11     │        │ rotas) + web_preview.py (SSE)  │
          │ tools, IN-PROCESS      │        │  ⚠️ NÃO INICIA NO macOS         │
          └────────────────────────┘        └─────────────────▲──────────────┘
                                                              │ HTTP :9001
                                            ┌─────────────────┴──────────────┐
                                            │ mcp-server/ (TypeScript, 14    │
                                            │ tools) — cliente HTTP do Flask │
                                            │  ⚠️ inútil enquanto (2) cair    │
                                            └────────────────────────────────┘

   Estado: DRAFT_CACHE (OrderedDict em memória, máx. 10.000, draft_cache.py)
           ⚠️ sem persistência; por processo
   Saída:  <output_base>/<draft_id>/  (cópia de template/ + assets/ + draft_info.json)
   Última milha: cópia manual (ou auto-deploy Windows) → CapCut Desktop → abrir app
```

Pontos estruturais importantes:

- **Há três fachadas concorrentes** (MCP Python in-process, HTTP Flask, MCP TypeScript sobre HTTP) com **defaults e nomes de parâmetros divergentes**. Isso não é cosmético: o default de `track_name` em `/add_video` (HTTP) é `video_main`, enquanto via MCP Python é `main` — e keyframes referenciam tracks por nome, então misturar fachadas gera `TrackNotFound`.
- **`pyJianYingDraft` é um fork vendorizado** do projeto homônimo (comentários e exceções em chinês), adaptado para CapCut International via a flag `IS_CAPCUT_ENV`.
- **`mcp-server/` é código de terceiros vendorizado** (`Atx-Guy/capcut-mcp-server`, conforme `docs/PRIMARY_OBJECTIVE.md`), não publicado no npm, sem `dist/` comitado.
- **Código morto**: `pyJianYingDraft/jianying_controller.py` (automação de exportação via UI) importa `process_controller` — **módulo que não existe no repositório** — e `uiautomation` (Windows-only, ausente dos requirements). Não é importado por nada. Idem `jianying_ui_inspector.py`. Ou seja: **não existe exportação/render automatizada no código aberto**.
- **`docs/PRIMARY_OBJECTIVE.md`** não é documentação: é um prompt de setup para um agente de IA em máquina Windows, deixado no repositório pelo PR #80. Sinaliza o processo pelo qual o código Windows-only entrou no `main`.

### Como os drafts são criados e modificados (2)

1. `create_draft.create_draft(width, height)` → instancia `draft.Script_file(w, h, fps=30)`, que carrega `pyJianYingDraft/draft_content_template.json` como base do conteúdo, e registra o objeto em `DRAFT_CACHE[draft_id]`.
2. Cada `add_*` chama `get_or_create_draft(draft_id)`. **Se o `draft_id` não estiver no cache, um draft NOVO é criado silenciosamente** com novo id (`create_draft.py:37-44`) — não há erro.
3. As mutações acontecem no objeto `Script_file` em memória: cria track se não existir, monta `*_material` + `*_segment`, anexa transições/máscaras/animações/efeitos.
4. `save_draft_impl` materializa: copia a pasta de template do perfil, resolve metadados de mídia via ffprobe/imageio, baixa/copia os assets em paralelo (16 threads), aplica keyframes pendentes, resolve conflitos de sobreposição, e grava `script.dumps(profile)`.

Nada é persistido entre etapas. O "draft" só existe como objeto Python até o `save_draft`.

---

## MCP Server

### `mcp_server.py` — como funciona (4) e como se comunica com o resto (5)

- **Não usa o SDK MCP.** É uma implementação JSON-RPC 2.0 manual sobre stdio: loop `sys.stdin.readline()` → `handle_request()` → `print(json.dumps(...))`. O `requirements-mcp.txt` (`mcp>=1.0.0`, `aiohttp`, `pydantic`) **não é usado por este arquivo** — nenhum dos três é importado.
- **Não fala HTTP.** Importa os módulos `add_*_impl` diretamente e executa **in-process** (`mcp_server.py:20-33`). Consequência crítica: **`capcut_server.py` não precisa estar rodando**, e o `DRAFT_CACHE` do MCP é totalmente separado do `DRAFT_CACHE` do Flask. Drafts criados via HTTP são invisíveis ao MCP e vice-versa.
- **Métodos suportados:** `initialize`, `notifications/initialized`, `tools/list`, `tools/call`. Qualquer outro retorna `-32601`. Verificado: `prompts/list` e `resources/list` → `Method not found`. Como as capabilities anunciadas são só `tools`, clientes bem-comportados (incluindo Codex) não deveriam chamá-los; risco baixo, mas real com clientes legados.
- **`protocolVersion` fixo em `"2024-11-05"`**, ignorando o que o cliente pede. Aceito na prática (testado enviando `2025-06-18`), mas é uma bomba-relógio de compatibilidade.
- **Despacho por `**arguments` sem validação.** `execute_tool` repassa o dict de argumentos direto para a função Python. Duas consequências:
  - Parâmetro inexistente → `TypeError` transformado em `{"success": false, "error": ...}`.
  - **Parâmetros fora do schema são aceitos** (não há `additionalProperties: false`). Isso é o que permite os workarounds: passar `draft_folder` em `save_draft`, ou `effect_category`/`params` em `add_effect`, mesmo sem estarem declarados.
- **`capture_stdout()` descarta todo o stdout dos módulos internos.** Todos os avisos importantes — keyframe descartado por não achar segmento, download que falhou, fallback de resolução para 1920x1080, segmento deletado por sobreposição — são impressos em stdout e **jogados fora**. O agente só vê exceções. Este é o maior problema de observabilidade para uso por IA.
- **Erros são retornados como resultado de sucesso** (`{"success": false, "error": ...}` dentro de `content[0].text`), sem `isError`. O agente precisa ler o JSON do texto para saber que falhou.
- **`draft_url` hardcoded para `https://www.install-ai-guider.top/...`** (`mcp_server.py:310` e `:352`), ignorando `DRAFT_DOMAIN` do `config.json`. Com `is_upload_draft: false` (o default), essa URL **não existe** — nenhum upload acontece. Um agente vai reportar ao usuário um link inválido de um domínio de terceiros.

**Teste de handshake real (executado):** `initialize` → OK; `tools/list` → 11 tools; `tools/call create_draft` → OK. O servidor MCP Python **funciona no macOS**.

### `mcp-server/` (TypeScript) — segunda implementação

- Usa `@modelcontextprotocol/sdk` corretamente, com transportes stdio e Streamable HTTP. 14 tools prefixadas `capcut_*`, incluindo três que o MCP Python não tem: `capcut_list_projects`, `capcut_read_project`, `capcut_reload_desktop`.
- **É um cliente HTTP** de `capcut_server.py` em `http://127.0.0.1:9001` → **inoperante no macOS** enquanto o bug (1) existir.
- Bug próprio: `api-client.ts` chama `POST /add_keyframe`, mas a rota Flask é `/add_video_keyframe` → **404**. A tool `capcut_add_keyframe` está quebrada por definição.
- `constants.ts` contém catálogos **inventados** (`TRANSITIONS = ['fade_in','fade_out','dissolve',...]`, `AVAILABLE_EFFECTS = ['blur','sharpen',...]`). Nenhum desses nomes existe nos enums reais (os reais são `Mix`, `Black_Fade`, `Blur`, `Fade_In`...). Um agente que confie nesses valores falha 100% das vezes.
- Requer `npm install && npm run build`; não há `dist/` no repositório nem pacote npm publicado.

### `test_mcp_client.py`

Cliente de teste caseiro (338 linhas). O README afirma que a saída esperada inclui "✅ Got 11 available tools" — a contagem de 11 confere.

---

## HTTP API

`capcut_server.py` — Flask, sem autenticação, sem rate limit, bind em `127.0.0.1:PORT` (`capcut_server.py:1588`).

> ⚠️ **Não inicia no macOS em `b83be74`.** Toda esta seção descreve o contrato; a execução foi validada no commit `71aafc1` (pré-regressão).

**Armadilha de porta:** `settings/local.py:28` define `PORT = 9000`; README, `config.json.example` e o cliente TypeScript assumem `9001`. Sem criar `config.json`, o servidor sobe em 9000 e nada o encontra.

### Endpoints reais (7) — 29 rotas

| Categoria | Endpoint | Método | Observações |
|---|---|---|---|
| Draft | `/create_draft` | POST | `width`, `height` → `{draft_id, draft_url}` |
| Draft | `/save_draft` | POST | `draft_id`, `draft_folder`, `project_name`, `auto_deploy`, `auto_reload` |
| Draft | `/query_script` | POST | Dump JSON completo do draft (bom para inspeção/diff) |
| Draft | `/query_draft_status` | POST | `task_id` == `draft_id`; save é sincrono, então tem pouco uso |
| Draft | `/generate_draft_url` | POST | **Bug**: gera `...?=<id>` (sem `draft_id=`) |
| Mídia | `/add_video` | POST | ~25 params (máscara, transição, blur de fundo, volume, speed) |
| Mídia | `/add_audio` | POST | `sound_effects` como lista de tuplas |
| Mídia | `/add_image` | POST | intro/outro/combo animation, transição, máscara |
| Texto | `/add_text` | POST | ~45 params (sombra, fundo, borda, multi-estilo, animações) |
| Texto | `/add_subtitle` | POST | **parâmetro é `srt`**, não `srt_path`; `font` default `"思源粗宋"` |
| Efeitos | `/add_effect` | POST | **falha se `params` não for enviado** (ver abaixo) |
| Efeitos | `/add_sticker` | POST | `resource_id` numérico do CapCut |
| Anim. | `/add_video_keyframe` | POST | default `track_name = "video_main"` |
| Mídia | `/get_duration` | POST | aceita `url` ou `video_url`; **só existe a partir de `e4f45a0`** |
| Desktop | `/list_projects` | GET/POST | procura `draft_content.json`; **não** `draft_info.json` |
| Desktop | `/read_project` | POST | idem — incompatível com o perfil `capcut_legacy` |
| Desktop | `/reload_desktop` | GET/POST | Windows-only (simula cliques) |
| Catálogos | `/get_intro_animation_types` | GET | 43 itens |
| Catálogos | `/get_outro_animation_types` | GET | 23 |
| Catálogos | `/get_combo_animation_types` | GET | 108 |
| Catálogos | `/get_transition_types` | GET | 116 |
| Catálogos | `/get_mask_types` | GET | 9 |
| Catálogos | `/get_audio_effect_types` | GET | 29 (filters + characters + speech2song) |
| Catálogos | `/get_font_types` | GET | 335 |
| Catálogos | `/get_text_intro_types` | GET | 76 |
| Catálogos | `/get_text_outro_types` | GET | 68 |
| Catálogos | `/get_text_loop_anim_types` | GET | 53 |
| Catálogos | `/get_video_scene_effect_types` | GET | 345 |
| Catálogos | `/get_video_character_effect_types` | GET | 95 |

Blueprint de preview (`web_preview.py`): `/preview`, `/preview/media`, `/api/active_draft`, `/api/preview_update`, `/api/preview_events` (SSE), `/api/trigger_desktop_reload`.

### Endpoints **documentados que não existem** (27)

O `vectcut-skill/skill/references/api_reference.md` — exatamente o arquivo que um agente de IA leria como referência — documenta 8 endpoints inexistentes:

`POST /upload_video`, `POST /upload_image`, `GET /list_uploads`, `DELETE /delete_upload/<file>`, `POST /export_to_capcut`, `POST /export_draft_to_video`, `GET /export_status`, `POST /execute_workflow`.

Verificado por grep: **zero ocorrências** em `capcut_server.py`. `export_draft_to_video` (render em nuvem) é explicitamente parte do produto fechado — o README admite: *"the code for the MCP Editing Agent, web-based editing client, and cloud rendering modules has not been open-sourced yet"*.

O mesmo arquivo documenta **parâmetros errados** para `/add_subtitle` (`srt_url`, `stroke_enabled`, `stroke_color`, `stroke_width`, `pos_y` — nenhum existe; os reais são `srt`, `border_*`, `transform_y`) e **valores de enum errados** para transições (`fade_in`, `wipe_left`) e máscaras (`circle`, `rect`, `linear` minúsculos). Confirmado empiricamente que `transition="fade_in"` → `ValueError` e `mask_type="circle"` → `ValueError`, enquanto `"Mix"` e `"Circle"` funcionam.

---

## Available Tools

### As 11 tools MCP (Python) — estado verificado (6)

| Tool | Status real (testado) | Notas |
|---|---|---|
| `create_draft` | ✅ funciona | `width`/`height`; retorna `draft_id` + URL fictícia |
| `add_video` | ✅ funciona | local e remoto; transição, máscara, blur, volume, speed |
| `add_audio` | ✅ funciona | `sound_effects` exige formato `[[nome, [params]]]` |
| `add_image` | ✅ funciona | intro/outro/combo, transição, máscara |
| `add_text` | ✅ funciona | sombra, fundo, borda, multi-estilo, animações |
| `add_subtitle` | ❌ **quebrada** com defaults | `NameError: font_type` — exige `font` explícito e válido |
| `add_effect` | ❌ **quebrada** com o schema | exige `effect_category` (ausente do schema) **e** `params` (lista, mesmo vazia) |
| `add_sticker` | ⚠️ funciona, utilidade limitada | precisa de `resource_id` interno do CapCut; sem descoberta |
| `add_video_keyframe` | ✅ funciona | default `track_name="main"`; o exemplo da doc usa `"video_main"` → falha |
| `get_video_duration` | ✅ funciona | ffprobe local, 3 tentativas, timeout 10s |
| `save_draft` | ⚠️ funciona mas com falha silenciosa | `success: true` + `draft_url: null` se o draft não está no cache |

Evidência (saída real do MCP via stdio):

```
id2: {"success": false, "error": "add_effect_impl() missing 1 required positional argument: 'effect_category'"}
id3: {"success": false, "error": "cannot access free variable 'font_type' where it is not associated with a value in enclosing scope"}
```

Com os workarounds (`effect_category="scene"`, `params=[]`, `font="Amigate"`), ambas passam a funcionar — os bugs estão no schema/nas defaults, não na lógica.

### Ausências relevantes no MCP

Nenhuma das 12 rotas de catálogo (`/get_*_types`) é exposta como tool. Como todos os enums exigem **match exato e case-sensitive** do identificador Python (`getattr(Enum, nome)`), **um agente não tem como descobrir os nomes válidos via MCP**. Também ausentes: `query_script` (inspeção/verificação do resultado), `list_projects`, `read_project`.

### Catálogos reais (enumerados no ambiente de teste)

| Catálogo | Qtd | Exemplos reais |
|---|---|---|
| Efeitos de cena (CapCut) | 345 | `Blur`, `Fade_In`, `Explosion`, `Zoom_Lens` |
| Efeitos de personagem | 95 | `Face_Mosaic`, `Lightning_Eyes` |
| Transições | 116 | `Mix`, `Mix_1`, `Black_Fade`, `Montage_Snippets` |
| Animações de entrada | 43 | `Fade_In`, `Zoom_1`, `Slide_Down` |
| Animações de saída | 23 | `Fade_Out`, `RGB_Scanlines` |
| Animações combo | 108 | `Bounce_1`, `Sway_Out` |
| Máscaras | 9 | `Split`, `Filmstrip`, `Circle`, `Rectangle` |
| Texto: intro / outro / loop | 76 / 68 / 53 | `Typewriter`, `Wobble_2` |
| Filtros de voz / personagens / speech2song | 15 / 13 / 1 | `Big_House`, `Queen`, `Folk` |
| Fontes | 335 (214 não-ASCII) | `Amigate`, `Caveat_Regular`, `思源粗宋` |

Os metadados carregam flag `is_vip` (`pyJianYingDraft/metadata/effect_meta.py`), mas **nenhum `add_*` verifica VIP** — recursos pagos entram no draft sem aviso.

---

## Draft Structure

### Estrutura do `draft_id` (8)

`create_draft.py:16`: `draft_id = f"dfd_cat_{unix_time}_{uuid4().hex[:8]}"`
Exemplo real: `dfd_cat_1789395132_85fa3e06`.

- É **apenas uma chave do dicionário em memória** e o nome da pasta de saída. Não tem relação com o `draft_id` interno do CapCut (que é um UUID em `draft_meta_info.json`).
- Colisão praticamente impossível (timestamp + 32 bits).
- Não é persistido em lugar algum: perder o processo = perder o draft.

### Estrutura dos arquivos gerados (9)

Perfil `capcut_legacy` (default para CapCut) — saída real verificada:

```
dfd_cat_1789395132_85fa3e06/
├── assets/
│   ├── video/video_<sha256[:16]>.mp4
│   ├── image/image_<sha256[:16]>.png
│   └── audio/audio_<sha256[:16]>.mp3
├── draft_info.json          ← gerado (conteúdo do timeline)
├── draft_info.json.bak      ← cópia estática do template (NÃO atualizada)
├── draft_meta_info.json     ← ⚠️ copiado do template SEM reescrita
├── draft_settings           ← INI estático com timestamps do autor original
├── template.tmp             ← snapshot estático do draft do autor original
├── template-2.tmp           ← idem
├── attachment_editing.json, attachment_pc_common.json
├── common_attachment/{aigc_aigc_generate.json, attachment_script_video.json}
├── draft_agency_config.json, draft_biz_config.json
└── performance_opt_info.json
```

Três perfis disponíveis (`draft_profiles.py`):

| Perfil | Template | Arquivo de conteúdo | `platform` |
|---|---|---|---|
| `capcut_legacy` | `template/` | `draft_info.json` | mac, `app_source: cc`, `app_version 6.5.0` |
| `jianying_legacy` | `template_jianying/` | `draft_info.json` | windows, `lv 10.2.0` |
| `jianying_pro_10` | `template_jianying_10_2/` | `draft_content.json` + espelhos + `Timelines/<uuid>/` | windows, `lv 10.2.0` |

⚠️ **Inconsistência de normalização de perfil:** `settings/local.py` mapeia `"capcut"` → `capcut_legacy`; `draft_profiles.PROFILE_ALIASES` mapeia `"capcut"` → **`jianying_pro_10`**, e `normalize_profile_name(None)` também default para `jianying_pro_10`. Na prática o caminho usado (`get_draft_profile()` → `settings.DRAFT_PROFILE`) resolve para `capcut_legacy`, mas qualquer chamada direta com `"capcut"` escolhe o template do Jianying Windows.

### Problemas confirmados no conteúdo gerado

1. **`draft_meta_info.json` não é reescrito.** Diff byte-a-byte com `template/draft_meta_info.json`: **idêntico**. Ou seja, todo projeto gerado carrega:
   - `draft_name: "0707"` (nome do projeto do autor original)
   - `draft_fold_path` / `draft_root_path`: `/Users/sunguannan/Movies/CapCut/User Data/Projects/com.lveditor.draft/0707`
   - `draft_id: "989869B1-B560-489C-9C6F-4B444F24BF36"` — **o mesmo UUID em todos os projetos gerados** (colisão garantida ao importar dois)
   - `tm_draft_create` / `tm_draft_modified` de julho de 2025, `tm_duration: 0`
   - `draft_cover: "draft_cover.jpg"` — **arquivo que não existe** em `template/` (existe só em `template_jianying/`)

   Como o CapCut monta a lista de projetos a partir do `draft_meta_info.json`, este é o ponto de maior risco na importação.

2. **`new_version` regride.** O template capturado do CapCut real diz `new_version: "138.0.0"`; o conteúdo gerado sai como **`110.0.0`**, porque `Script_file` parte de `pyJianYingDraft/draft_content_template.json` e não do `template/draft_info.json`. Escrever uma versão de schema mais antiga do que a do app é um vetor clássico de "projeto não abre / abre vazio".

3. **`.bak` e `.tmp` ficam dessincronizados** do `draft_info.json` no perfil `capcut_legacy` (`content_mirrors` é vazio). Se o CapCut preferir o `.tmp`/`.bak` em alguma situação de recuperação, ele lerá o projeto do autor original.

4. **Caminhos de mídia são absolutos e apontam para o diretório de salvamento.** Verificado: `path = <output_base>/<draft_id>/assets/video/....mp4`. Se você salvar em pasta temporária e depois copiar o projeto para o CapCut, **os caminhos continuam apontando para a pasta temporária**. Corolário prático: salve direto no diretório de projetos do CapCut (`draft_folder=...`) para que o projeto seja autocontido.

5. **Extensões são mentirosas.** O nome do material é sempre `video_<hash>.mp4`, `audio_<hash>.mp3`, `image_<hash>.png`, independentemente do formato real. Arquivos locais são copiados com `shutil.copy2` **sem transcodificação** (`downloader.py:110-131`). Teste executado: um `tone.wav` virou `audio_11c17dd7377d1ec3.mp3` contendo WAV. As funções que realmente transcodificam (`download_audio`, `download_image`) existem mas **não são usadas** por `save_draft_background`, que usa só `download_file`.

6. **Track vazia extra.** `add_video_track` cria uma track sem nome antes de criar a nomeada (`add_video_track.py:83-88`), resultando sempre numa track `video` vazia no JSON. Verificado na saída real.

7. `write_profile_content` injeta `canvas_config.ratio` derivado (9:16 / 16:9 / 1:1) e remove `.locked` obsoleto — comportamento correto e útil.

---

## CapCut Integration

### Como vídeo / imagem / áudio / texto / legenda / efeito / transição / sticker / keyframe são adicionados (10-18)

| Recurso | Mecanismo | Notas críticas |
|---|---|---|
| **Vídeo (10)** | `Video_material(material_type='video', remote_url=...)` + `Video_segment` com `source_timerange`/`target_timerange`; `speed`, `volume`, `Clip_settings` (scale/transform), máscara, `add_background_filling("blur")` | `duration` **não** é detectada no add (fica 0.0) a menos que você passe `end` ou `duration`; resolvida no save |
| **Imagem (11)** | Mesmo `Video_material` com `material_type='photo'`; duração padrão 3s; `duration` do material = 10800s (convenção CapCut) | dimensões via `imageio.imread` (baixa a imagem inteira); fallback 1920x1080 |
| **Áudio (12)** | `Audio_material` + `Audio_segment`; `volume`, `speed`, `sound_effects` | duração idem vídeo |
| **Texto (13)** | `Text_segment` + `Text_style` (~45 params); `text_styles` como `TextStyleRange[]` para multi-cor/multi-tamanho | **`font_size` está na escala interna do CapCut (~5–15), não em pt.** O skill `capcut-director` mapeia: 9.0–12.0 ≈ título 80–135pt; 6.5–7.5 ≈ legenda. O README e o `MCP_Documentation_English.md` usam `font_size: 48/56` — isso produz texto gigantesco |
| **Legendas (14)** | `Script_file.import_srt()` parseia SRT (arquivo, URL ou conteúdo inline) e cria um `Text_segment` por bloco | **Bug**: `font_type` só é atribuído dentro de `if font:` (`script_file.py:503-505`) mas é lido na closure em `:547/:552` → `NameError` quando `font` é `None`. HTTP escapa porque a rota injeta `font="思源粗宋"`; MCP não |
| **Efeitos (15)** | Track `effect` dedicada + `script.add_effect(enum, trange, params=params[::-1])` | `params[::-1]` explode com `None`; exige lista. Ordem dos params é **invertida** — semântica não documentada |
| **Transições (16)** | `segment.add_transition(enum, duration)` anexada ao segmento **anterior**; aplicável em vídeo e imagem | nomes case-sensitive; sem validação de duração vs. tamanho dos clipes |
| **Stickers (17)** | `Sticker_segment(resource_id, trange, clip_settings)` | depende de `resource_id` do catálogo interno do CapCut; sem API de busca. `inspect_material()` só lista stickers de um template importado |
| **Keyframes (18)** | Enfileirados em `track.pending_keyframes` e materializados no save por `process_pending_keyframes()`; 11 propriedades (`position_x/y`, `rotation`, `scale_x/y`, `uniform_scale`, `alpha`, `saturation`, `contrast`, `brightness`, `volume`) | O keyframe é ligado ao segmento que **cobre aquele instante**. Se nenhum cobrir, é **descartado com aviso em stdout** — que o MCP engole. Modo batch (`property_types`/`times`/`values`) exige as 3 listas do mesmo tamanho |

### Como a duração da mídia é detectada (19)

Estratégia de **resolução tardia**, e ela é a origem do pior comportamento emergente do sistema:

1. No `add_*`, se `duration`/`end` não forem informados, a duração é **0.0** e o segmento nasce com timerange degenerado.
2. No `save_draft`, `update_media_metadata()` roda `ffprobe` sobre o `remote_url` (URL ou caminho local) de cada material, obtém duração e dimensões, e **estende** os segmentos cujo `source_timerange.end <= 0`.
3. Em seguida, um passe O(n²) detecta sobreposições por track e **deleta o segmento de índice maior** (`save_draft_impl.py:520-544`).

**Teste executado:** três clipes adicionados na mesma track sem `end`/`target_start`. Antes do save: 3 segmentos. Depois da resolução: **1 segmento**. Dois foram apagados silenciosamente. Um agente que faça "adicione estes 3 clipes em sequência" sem calcular offsets recebe `success: true` em todas as chamadas e um vídeo com um clipe.

O fluxo correto é: `get_video_duration` para cada mídia → calcular `start`/`end`/`target_start` explicitamente → `add_video`.

### Como o projeto final é salvo (20) e como chega ao CapCut Desktop (21)

`save_draft_impl.save_draft_impl()` é **sincrono** (o caminho em thread está comentado no código; `query_draft_status` é vestigial). Sequência:

1. `output_base_dir = draft_folder or <diretório do repositório>` (`save_draft_impl.py:78`). **Sem `draft_folder`, o draft e todas as mídias são escritos dentro do próprio repositório** — e `.gitignore` **não** ignora `dfd_*`.
2. Apaga a pasta destino se existir (`shutil.rmtree`) — cuidado com `project_name` reutilizado.
3. Copia o template do perfil, resolve metadados, baixa assets (16 threads).
4. `write_profile_content` grava o conteúdo (e espelhos/Timelines, conforme perfil).
5. Se `IS_UPLOAD_DRAFT` (default `false`): zipa e faz upload para OSS Aliyun, retornando URL assinada de 24h. **Desligado por default.**
6. Se `auto_deploy` (default `true`): tenta copiar para o diretório de projetos do CapCut. No macOS procura o caminho do **JianyingPro**; se não existir, **não faz nada e não avisa**.
7. Retorna `deployed_path or draft_dir`.

Portanto, no macOS, a entrega real é: **`save_draft` grava uma pasta e você copia manualmente para o diretório de projetos do CapCut** — exatamente o que o README-zh descreve na linha 243. Não há hot-reload no macOS (`desktop_companion` é 100% Win32: `EnumWindows`, `mouse_event`, `keybd_event`, cliques em coordenadas fixas).

**Nota de arquitetura do CapCut**, conforme `.agents/skills/capcut-director/SKILL.md` (não verificável aqui, sem CapCut instalado):
- CapCut 9.x+ leria `Timelines/<UUID>/draft_content.json`, e escrever só o `draft_content.json` da raiz abriria um timeline vazio.
- CapCut não tem file watcher: o app precisa estar fechado (ou voltar à Home) para reler do disco; o autosave em memória sobrescreve mudanças externas; `.locked` indica projeto aberto.

Isso **contradiz** o perfil `capcut_legacy`, que gera `draft_info.json` e nenhum diretório `Timelines/`. As duas coisas não podem estar certas simultaneamente para a mesma versão do app — e o template `capcut_legacy` foi capturado de um CapCut mac real (`app_version 6.5.0`, `new_version 138.0.0`). É a **incógnita nº 1** desta auditoria.

---

## macOS Integration

### Caminhos usados no macOS (22)

| Origem | Caminho | Avaliação |
|---|---|---|
| `save_draft_impl.py:259`, `capcut_server.py:784` | `~/Library/Containers/com.lemon.lvpro/Data/Documents/JianyingPro/User Data/Projects/com.lveditor.draft` | **Jianying Pro (chinês), sandboxed.** Não é o CapCut International |
| `template/draft_meta_info.json` (capturado de instalação real) | `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` | **Este é o caminho do CapCut no macOS** — e o código nunca o consulta |
| `web_preview.py:17` | `%LOCALAPPDATA%\CapCut\...` | Literal do Windows; `expandvars` no macOS devolve a string crua → nunca existe |
| `desktop_companion.py:35-36` | `%LOCALAPPDATA%\CapCut\Apps\CapCut.exe` | Windows-only |
| `scripts/*.ps1`, `scripts/*.cmd` | — | Só PowerShell/cmd; nenhum script de inicialização para macOS |
| `save_draft_impl.py:742` (`__main__`) | `/Users/sunguannan/Movies/JianyingPro/...` | Caminho pessoal do autor, hardcoded |

**Verificado nesta máquina:** nenhum dos quatro diretórios candidatos existe; `CapCut.app` não está instalado. A validação da importação no CapCut **não pôde ser feita** e permanece como teste obrigatório.

### Estado do macOS por componente

| Componente | macOS |
|---|---|
| `mcp_server.py` (MCP Python) | ✅ funciona (testado) |
| `pyJianYingDraft` + `add_*_impl` | ✅ funciona (testado) |
| `save_draft_impl` (gravação em disco) | ✅ funciona (testado) |
| `capcut_server.py` (HTTP) | ❌ **não importa** (`ctypes.windll`) |
| `web_preview.py` (preview + SSE) | ❌ não importa; e a detecção de projeto é Win-only |
| `desktop_companion.py` (hot-reload) | ❌ conceitualmente Windows-only |
| `mcp-server/` (MCP TypeScript) | ❌ depende do HTTP |
| auto-deploy para CapCut | ❌ caminho errado, falha silenciosa |
| `jianying_controller.py` (exportar vídeo) | ❌ código morto, Windows-only |

Evidência:

```
$ python -c "import capcut_server"
  File ".../web_preview.py", line 13, in <module>
    from desktop_companion import reload_capcut_desktop, get_capcut_windows
  File ".../desktop_companion.py", line 15, in <module>
    user32 = ctypes.windll.user32
AttributeError: module 'ctypes' has no attribute 'windll'

$ (no commit 71aafc1, pré-e4f45a0)
$ python -c "import capcut_server; print(len(list(capcut_server.app.url_map.iter_rules())))"
IMPORT OK — routes: 26
```

---

## Dependencies

### Python (23)

`requirements.txt` (5 pacotes, instalação limpa verificada no Python 3.14):
`imageio`, `psutil`, `flask`, `requests`, `oss2`, `json5`

`requirements-mcp.txt`: `mcp>=1.0.0`, `aiohttp>=3.8.0`, `pydantic>=2.0.0` — **nenhum é importado** por `mcp_server.py`. Na prática, **o servidor MCP roda apenas com `requirements.txt`** (e nem precisa de `flask`).

`pyproject.toml` declara um conjunto **totalmente diferente e em grande parte não usado**: `Pillow`, `numpy`, `opencv-python`, `ffmpeg-python`, `fastapi`, `uvicorn`. Não há FastAPI nem OpenCV em nenhum lugar do código. Metadado abandonado (inclusive as URLs apontam para `ashreo/CapCutAPI`).

Dependências reais por caminho de uso:
- MCP mínimo: `imageio`, `requests`, `json5` (+ `oss2` só se `is_upload_draft: true`)
- `psutil`: só `desktop_companion` (Windows)
- `flask`: só a API HTTP
- `uiautomation`, `process_controller`: código morto, **não instaláveis/inexistentes**

`requires-python = ">=3.10"`. Funcionou em 3.14; `add_text_impl.py` usa sintaxe `str | None` (3.10+).

### Externas (24)

- **FFmpeg/ffprobe — obrigatório.** `ffprobe` é o único mecanismo de detecção de duração/dimensão de vídeo e áudio (`get_duration_impl.py`, `save_draft_impl.update_media_metadata`). Sem ele no PATH, durações ficam 0 e o comportamento de deleção por sobreposição destrói o timeline. Presente nesta máquina (`/opt/homebrew/bin/ffprobe`).
- **Node.js ≥ 18 + npm** — só para o MCP TypeScript (requer build).
- **CapCut Desktop** — necessário apenas para abrir o resultado; irrelevante para o import dos módulos (ao contrário do que o troubleshooting do `MCP_Documentation_English.md` afirma).
- **OSS Aliyun** — opcional, desligado por default.
- **Chamada de rede embutida**: `save_draft_impl.download_script()` faz POST para `https://cut-jianying-vdvswivepm.cn-hongkong.fcapp.run/query_script` (função não exposta em nenhuma rota, mas presente).

### Configurações necessárias (25)

`config.json` (cópia de `config.json.example`, formato JSON5 com comentários, ignorado pelo git):

```jsonc
{
  "draft_profile": "capcut_legacy",   // para CapCut International
  "is_capcut_env": true,              // controla qual família de enums é usada
  "port": 9001,                       // SEM isto, o default real é 9000
  "is_upload_draft": false,
  "draft_domain": "https://www.capcutapi.top",
  "preview_router": "/draft/downloader"
}
```

Notas:
- `IS_CAPCUT_ENV` é lido em **import time** e decide entre `CapCut_*_type` e os enums do Jianying. Mudar exige reiniciar o processo.
- Falha de parsing do `config.json` é engolida por um `except: pass` (`settings/local.py:78-80`) → volta silenciosamente para os defaults. Um typo no JSON faz você rodar com perfil e porta errados sem nenhum aviso.
- `mcp_config.json` do repositório contém `cwd: "/Users/chuham/Downloads/CapCutAPI-dev"` — caminho de outra pessoa; precisa ser reescrito.
- Sem `config.json`, o `DRAFT_DOMAIN` default é `https://www.install-ai-guider.top` (domínio de terceiros).

---

## Capabilities

### O que o VectCutAPI **realmente** consegue fazer (verificado empiricamente)

1. Criar projetos com resolução arbitrária (1080x1920, 1920x1080, 1080x1080) e `ratio` correto.
2. Montar timelines multi-track: vídeo, áudio, imagem, texto, legenda, efeito, sticker — com tracks nomeadas e ordem de render por `relative_index`.
3. Cortar (`start`/`end`), posicionar (`target_start`), acelerar (`speed`), transformar (`scale_x/y`, `transform_x/y`), ajustar volume.
4. Aplicar, a partir de catálogos reais e grandes: 440 efeitos, 116 transições, 174 animações de mídia, 197 animações de texto, 9 máscaras, 29 efeitos de voz, 335 fontes.
5. Texto com tipografia rica: sombra, borda, fundo com raio, alinhamento, entrelinha, espaçamento, largura fixa e **multi-estilo por faixa de caracteres**.
6. Importar SRT (arquivo local, URL ou conteúdo inline) gerando um segmento de texto por bloco — **desde que `font` seja informado**.
7. Keyframes em 11 propriedades, modo unitário ou batch, ligados automaticamente ao segmento correto — verificado no JSON gerado.
8. Usar **arquivos locais** como mídia: são copiados para `assets/` e referenciados por caminho absoluto (teste com mp4/wav/png passou).
9. Detectar duração/dimensões via ffprobe e **auto-ajustar** os timeranges no save.
10. Blur de fundo (4 níveis), máscaras com feather/rotação/inversão, background filling.
11. Gravar uma pasta de projeto do CapCut estruturalmente plausível, com `canvas_config` coerente.
12. Servir tudo isso por MCP stdio funcional no macOS (11 tools) — integrável ao Codex/Claude Code sem servidor HTTP.
13. Exportar o JSON completo do draft para inspeção (`/query_script`, só HTTP).

### O que **aparentemente** consegue fazer (documentado, mas não confiável)

| Alegação | Realidade |
|---|---|
| "Real-Time Cloud Preview" / `/preview` | Existe um player HTML5 + SSE, mas: não importa no macOS, procura `draft_content.json` (o perfil CapCut gera `draft_info.json`) e localiza projetos por caminho do Windows. É um renderizador aproximado em canvas, não um preview fiel |
| "Desktop Auto-Reload" | Win32 puro (cliques em coordenadas fixas da janela). Inexistente no macOS |
| Auto-deploy para o CapCut | No macOS aponta para o JianyingPro; falha em silêncio |
| `add_effect` / `add_subtitle` via MCP | Quebradas com os parâmetros documentados |
| `draft_url` retornado | Link para domínio de terceiros que só é válido se você ativar upload para o OSS do fornecedor |
| Endpoints de upload/export/workflow do skill | Não existem no código |
| Catálogos de transições/efeitos do MCP TypeScript | Valores inventados, 100% inválidos |
| "Automated Cloud Generation" (render final) | **Módulo fechado**, não open-source. O `jianying_controller.py` que exportaria via UI é código morto |
| `query_draft_status` / progresso assíncrono | O save é sincrono; o task cache existe mas é vestigial |
| `generate_draft_url` | Gera URL malformada (`?=<id>`) |
| `capcut_add_keyframe` (TS) | Chama endpoint inexistente → 404 |

### O que **não** consegue fazer

- **Renderizar/exportar vídeo.** Nenhum caminho aberto produz um MP4.
- **Controlar o CapCut.** Não abre projeto, não clica, não exporta, não lê estado do app no macOS.
- **Ler/editar um projeto existente do CapCut** de forma prática. Existe `Script_file.load_template()` e o módulo `template_mode.py`, mas nenhuma tool MCP ou rota os expõe para edição incremental.
- **Persistir drafts.** Reiniciar o processo apaga tudo; e `save_draft` de um draft ausente "sucede" sem escrever.
- **Descobrir nomes de assets via MCP** (efeitos, fontes, transições, `resource_id` de sticker).
- **Validar semanticamente** o timeline: não avisa sobre sobreposição (apenas apaga), gap, clipe estourando duração, texto fora da safe zone, ou recurso VIP.
- **Transcodificar/normalizar mídia.** Copia bytes com extensão trocada.
- **Rodar concorrentemente com segurança.** `DRAFT_CACHE` é um `OrderedDict` global sem lock, e o Flask é single-instance sem auth.
- **Gerar drafts para Windows a partir do macOS**: `build_draft_asset_path` produz `D:\\Pasta\...` (barra dupla) fora do Windows — dois testes do próprio repositório falham exatamente por isso.

### O que precisaria ser desenvolvido adicionalmente

1. **Camada de compatibilidade macOS**: import guard no `desktop_companion`, detecção real do diretório do CapCut (`~/Movies/CapCut/...`), e um `reload`/`open` via AppleScript/`open -a`.
2. **Reescrita do `draft_meta_info.json`** por projeto: `draft_name`, `draft_fold_path`, `draft_root_path`, `draft_id` (UUID novo), timestamps, `tm_duration`, e geração de `draft_cover.jpg`.
3. **Persistência de drafts** (serializar o `Script_file` em disco) e erro explícito quando `draft_id` não existe, em vez de criar outro ou "suceder" vazio.
4. **Tools MCP de descoberta**: `list_transitions`, `list_effects`, `list_fonts`, `list_animations`, `list_masks` (os dados já existem em `metadata/`).
5. **Tool de verificação**: `query_script`/`inspect_draft` via MCP, para o agente auditar o que construiu antes de salvar.
6. **Validação e propagação de avisos**: parar de engolir stdout; devolver `warnings[]` estruturados no resultado da tool (keyframe descartado, segmento deletado, download falho, fallback de dimensão).
7. **Planejador de timeline**: resolver duração antes de montar, calcular `target_start` em cadeia e recusar sobreposição em vez de apagar.
8. **Pipeline de exportação** próprio (FFmpeg headless a partir do draft, ou automação de UI do CapCut no macOS via Accessibility API).
9. **Correções pontuais**: `effect_category` default + `params or []`; `font_type = None` em `import_srt`; `/generate_draft_url`; `/add_keyframe` no cliente TS; extensões reais nos nomes de material.

---

## Limitations

**Conhecidas / estruturais (26)**

| # | Limitação | Impacto |
|---|---|---|
| L1 | Estado só em memória, por processo, sem persistência | Reinício do MCP = perda total; sessões não compartilham drafts |
| L2 | `save_draft` de draft ausente → `success: true`, nada escrito | Falha silenciosa, a pior classe para agentes |
| L3 | `draft_id` desconhecido em `add_*` → cria draft novo em silêncio | Agente acha que editou o projeto A e editou o B |
| L4 | Sem `draft_folder`, escreve no diretório do repositório (não ignorado pelo git) | Poluição, risco de commit de mídia |
| L5 | Sem renderização/exportação | Sempre exige um humano no CapCut |
| L6 | Sem hot-reload/auto-deploy no macOS | Cópia manual + reabrir o app |
| L7 | Enums case-sensitive sem descoberta via MCP e sem fuzzy match | Alta taxa de erro do agente; mensagens de erro chegam a listar nomes errados |
| L8 | `font_size` em escala interna (~5–15), contradito pela própria documentação | Texto ilegível ou gigante |
| L9 | Sobreposição resolvida por deleção silenciosa | Perda de conteúdo sem erro |
| L10 | Stdout descartado pelo MCP | Nenhum aviso chega ao agente |
| L11 | Todo aviso/erro interno em chinês ou misto | Ex.: `不存在名为 'video_main' 的轨道` |
| L12 | Defaults divergentes entre fachadas (`main` vs `video_main`; `srt` vs `srt_path`) | Quebra ao misturar HTTP e MCP |
| L13 | Sem autenticação nem rate limit no Flask | Ver *Risks* |
| L14 | Save sincrono e bloqueante (downloads em 16 threads, timeout 180s por arquivo) | Uma tool call pode travar minutos |
| L15 | `is_vip` ignorado | Projeto pode depender de recursos pagos sem aviso |
| L16 | Assets com extensão errada e sem transcodificação | Risco de mídia não reconhecida |
| L17 | 3 de 14 testes do repositório falham no macOS em HEAD | Sem rede de segurança; CI aparentemente não roda |
| L18 | `template.tmp`/`.bak` estáticos do projeto do autor | Estado inconsistente dentro do projeto gerado |
| L19 | Governança: "no direct PRs to main", merges semanais de `dev`; um PR Windows-only de 5.5k linhas entrou com regressão de plataforma | Risco de instabilidade contínua |

**Funcionalidades documentadas que parecem incompletas (27)**

- Preview web / SSE / inspector: implementado para Windows + perfil `jianying_pro_10`; inerte no cenário macOS + CapCut.
- `query_draft_status` e `save_task_cache`: infraestrutura para save assíncrono que foi comentada.
- `download_script`: baixa draft de um endpoint de nuvem do fornecedor; não exposto, não documentado.
- `template_mode.py` / `load_template` / `inspect_material`: base para editar projetos existentes, sem fachada.
- `oss.py` `upload_mp4_to_oss`: presume um pipeline de render que não existe no código aberto.
- `examples/`: quatro scripts com caminhos absolutos da máquina de um contribuidor (`C:\Users\Hemanshi Makwana\...`), fazendo cirurgia manual de JSON em vez de usar a API. Não reutilizáveis; um deles depende de Playwright + Gemini.
- `.flake8` presente, mas o código não passaria em revisão (dezenas de `except:` nus).

---

## Risks

**Frágeis por dependerem do formato interno do CapCut (28)**

| Risco | Detalhe |
|---|---|
| R1 | **`draft_meta_info.json` não reescrito** — nome, caminhos do autor original e **`draft_id` UUID duplicado** em todos os projetos. É o arquivo que o CapCut usa para listar projetos |
| R2 | **`new_version` 110.0.0 vs 138.0.0 do template real** — schema declarado mais antigo que o do app |
| R3 | **`draft_info.json` vs `draft_content.json` vs `Timelines/<uuid>/`** — o repositório contém três teorias mutuamente incompatíveis sobre onde o CapCut lê o timeline (perfil `capcut_legacy`, `web_preview`/`list_projects`/`read_project`, e o skill `capcut-director`) |
| R4 | `draft_cover.jpg` referenciado mas ausente no template do CapCut |
| R5 | `platform` hardcoded com `device_id`/`mac_address`/`hard_disk_id` **de outra máquina** e `os_version: 15.5` — identificadores fabricados enviados ao app |
| R6 | `resource_id`/`effect_id` de efeitos, fontes e stickers são IDs opacos do backend do CapCut; podem ser rotacionados ou virar VIP em qualquer update |
| R7 | Caminhos absolutos de mídia embutidos no JSON — mover a pasta quebra o projeto |
| R8 | Metadados congelados em `metadata/*.py` (milhares de entradas geradas em algum momento) sem processo de atualização visível |

**Incompatibilidades possíveis entre versões do CapCut (29)**

- O template `capcut_legacy` foi capturado de **um** CapCut macOS (`app_version 6.5.0`, `new_version 138.0.0`, `os_version 15.5`). Não há matriz de versões testadas, nem verificação de versão em runtime, nem migração.
- Se a sua instalação do CapCut for mais nova, os cenários possíveis são: abre normalmente; abre com timeline vazia; abre e "conserta" o projeto descartando o que não entende; ou não lista o projeto. O código não distingue nem reporta nenhum desses casos.
- O rebranding CapCut ↔ Jianying (`com.lveditor.draft`, `com.lemon.lvpro`, `app_source: cc|lv`) tornou a base de código ambígua sobre qual app está alvejado em cada caminho.
- `IS_CAPCUT_ENV` errado → busca de enums na família errada → `ValueError` em massa ou, pior, IDs de recurso que o app não resolve.

**Segurança / operacionais**

| Risco | Detalhe |
|---|---|
| S1 | **`GET /preview/media?path=<qualquer coisa>` serve qualquer arquivo do disco** sem restrição (`web_preview.py:178-188`). Bind é 127.0.0.1, mas qualquer processo local — ou uma página web maliciosa fazendo fetch para localhost — pode ler arquivos arbitrários do usuário |
| S2 | Nenhuma rota tem autenticação. `/save_draft` faz `shutil.rmtree` do diretório destino; `project_name` não é sanitizado em `read_project` (aceita caminho absoluto) |
| S3 | `add_*` aceitam URLs arbitrárias e o servidor as busca (SSRF) com `User-Agent`/`Referer` falsificados de forma hardcoded (`downloader.py`: `Referer: https://www.163.com/`) |
| S4 | `ffprobe`/`ffmpeg` recebem URLs controladas pelo chamador como argumento |
| S5 | Chaves do OSS ficam em texto claro no `config.json` |
| S6 | Falhas de download são contadas como sucesso (`download_file` retorna `False`, que é anexado à lista de "downloaded_paths" e incrementa o contador) → projeto com material faltando e progresso 100% |
| S7 | Repositório em evolução rápida com merges semanais direto para `main`; a regressão macOS tem 2 dias |

---

## Unknowns

1. **O draft gerado abre corretamente no CapCut macOS atual?** Não testável aqui (CapCut não instalado). É a incógnita que decide o projeto todo.
2. **`draft_info.json` ou `draft_content.json` + `Timelines/`** na sua versão do CapCut? As três fontes internas do repositório discordam.
3. O `draft_meta_info.json` não reescrito impede a listagem do projeto, ou o CapCut reconstrói metadados ao escanear o diretório?
4. Dois projetos com o mesmo `draft_id` UUID coexistem ou se sobrescrevem na biblioteca?
5. `new_version: 110.0.0` é aceito, migrado ou rejeitado pelo app atual?
6. Quantos dos 440 efeitos / 116 transições / 335 fontes ainda resolvem nos servidores atuais do CapCut, e quantos são VIP?
7. O CapCut aceita um WAV nomeado `.mp3` e um JPEG nomeado `.png` dentro de `assets/`?
8. Fontes não-ASCII (`思源粗宋`, default de `/add_subtitle`) resolvem no CapCut International?
9. O cliente MCP do Codex tolera `protocolVersion: "2024-11-05"` fixo e `-32601` em `prompts/list`/`resources/list`?
10. O perfil `jianying_pro_10` (que gera `draft_content.json` + `Timelines/`) funciona melhor com o CapCut International moderno do que o `capcut_legacy`? Hipótese plausível e barata de testar.
11. Há um caminho oficial de deep link/URL scheme do CapCut para abrir um projeto sem reiniciar o app?
12. O upstream vai reverter/corrigir a regressão macOS, e em que prazo? (não consultei issues/PRs abertos)

---

## Tests Required

Pontos que precisam de verificação empírica (30), em ordem de valor decrescente:

**Bloco A — decide GO/NO-GO (fazer antes de escrever qualquer automação)**
1. Instalar o CapCut macOS; registrar a versão exata e a estrutura real de um projeto criado à mão em `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` (nome do arquivo de conteúdo, presença de `Timelines/`, `new_version`).
2. Gerar um draft mínimo (1 vídeo + 1 texto) com `draft_folder` = diretório real do CapCut e verificar: o projeto aparece na lista? Abre? O timeline tem o conteúdo? A mídia é encontrada?
3. Repetir com `draft_profile: "jianying_pro_10"` e comparar.
4. Testar a reescrita manual do `draft_meta_info.json` (nome, paths, UUID novo, timestamps) e medir se muda o resultado de (2).
5. Gerar dois projetos e confirmar se o `draft_id` UUID duplicado causa conflito.

**Bloco B — fidelidade de conteúdo**
6. Um projeto completo com todos os tipos (vídeo, imagem, áudio, texto multi-estilo, legenda SRT, efeito, transição, sticker, keyframes) e conferência visual de cada elemento no CapCut.
7. Amostra de 20–30 efeitos/transições/animações/fontes: quais resolvem, quais aparecem como VIP, quais quebram.
8. `resource_id` de sticker: encontrar uma fonte confiável de IDs e validar um.
9. Escala de `font_size`: calibrar 5.0 / 8.0 / 12.0 num canvas 1080x1920 e criar uma tabela própria.
10. Mídia com extensão trocada (WAV→.mp3, JPEG→.png, MOV→.mp4) — o CapCut aceita?
11. Precisão de tempo: comparar o timerange pedido com o resultado no timeline (drift de arredondamento em µs, alinhamento a frames em 30fps).
12. Keyframes: confirmar as curvas/valores no app e o comportamento de keyframe fora do range do segmento.

**Bloco C — robustez para uso por agente**
13. Reproduzir o cenário de sobreposição (3 clipes sem `end`) e desenhar a proteção no wrapper.
14. `save_draft` com `draft_id` inválido → confirmar `success: true` + `draft_url: null` e decidir a política de erro do wrapper.
15. Reinício do processo MCP no meio de uma sessão → confirmar a perda de estado.
16. Draft grande (30+ segmentos, 10+ tracks): tempo de save, tempo de abertura no CapCut, tamanho do JSON.
17. Downloads remotos: URL 404 / lenta / gigante → verificar o mascaramento de falha (S6).
18. Rodar `pytest tests/` num fork com os fixes e garantir 14/14 (hoje: 11 passam, 3 falham).
19. `add_*` concorrentes no mesmo `draft_id` → corrida no `DRAFT_CACHE`.
20. Abrir o projeto no CapCut, editar no app, e rodar `save_draft` de novo por cima → confirmar a regra "CapCut sobrescreve com o estado em memória".

**Bloco D — integração**
21. Handshake do MCP com o cliente real do Codex (nomes de tools, schemas, tolerância de protocolo, timeouts em tool calls longas).
22. Se o HTTP for necessário: patch do import do `desktop_companion` e validação das 29 rotas no macOS.
23. Verificar se `/preview` tem qualquer utilidade após corrigir o nome do arquivo de conteúdo e o diretório de projetos.

---

## Recommendations

### Decisão de arquitetura

**Use somente `mcp_server.py` (MCP Python, in-process).** Ignore `capcut_server.py`, `web_preview.py`, `desktop_companion.py` e `mcp-server/` (TypeScript). Justificativa: o MCP Python é o único caminho que funciona no macOS, não precisa de servidor HTTP, tem menos peças móveis e acessa a mesma camada de lógica. Os outros três só adicionam superfície de falha, de rede e de segurança.

### Plano de adoção

1. **Fork, não fetch.** Faça fork de `sun-guannan/VectCutAPI` e fixe o commit (`b83be74` ou o `71aafc1` se você precisar do HTTP). Puxar `main` semanalmente sem revisão é inaceitável dado o histórico.
2. **Não modifique o upstream: adicione um wrapper MCP próprio.** Um `mcp_server_mac.py` que importe os mesmos `add_*_impl` e exponha tools saneadas. Isso mantém o merge do upstream trivial e concentra as correções.
3. **Correções obrigatórias no wrapper** (todas de baixo custo):
   - `add_effect`: default `effect_category="scene"` e `params = params or []`.
   - `add_subtitle`: `font` default explícito e válido (escolhido por você, não `思源粗宋`).
   - `save_draft`: **erro de verdade** se `draft_id not in DRAFT_CACHE`; `draft_folder` obrigatório (default = diretório real do CapCut); nunca retornar `draft_url` fictício.
   - Todo `add_*`: recusar `draft_id` desconhecido em vez de criar um novo.
   - Reescrever `draft_meta_info.json` a cada save (nome, `draft_fold_path`, `draft_root_path`, `draft_id` novo, timestamps, `tm_duration`), e gerar um `draft_cover.jpg`.
   - Detectar o diretório do CapCut macOS de verdade: `~/Movies/CapCut/User Data/Projects/com.lveditor.draft`.
   - **Não engolir stdout**: capturar e devolver como `warnings[]` no resultado da tool.
4. **Adicione tools de descoberta e verificação** — é o que mais aumenta a taxa de acerto do agente: `list_transitions`, `list_effects(category)`, `list_fonts`, `list_animations(kind)`, `list_masks`, e `inspect_draft(draft_id)` (reuso de `query_script_impl`).
5. **Torne o planejamento de tempo explícito.** No wrapper, exija `duration`/`end` (resolvendo via `get_video_duration` quando ausente) e calcule `target_start` em cadeia; recuse sobreposição com erro em vez de deixar o save apagar segmentos.
6. **Padronize nomes de track** (`main`, `audio_main`, `text_main`, `subtitle`, `effect_01`, `sticker_main`) numa constante compartilhada, e faça as tools de keyframe validarem a existência da track antes de enfileirar.
7. **Trate a última milha como manual e explícita.** `save_draft` grava direto no diretório do CapCut; a tool retorna o caminho e a instrução ("feche/volte à Home do CapCut para recarregar"). Não prometa hot-reload no macOS.
8. **Escreva um smoke test próprio** que gere um projeto de referência com todos os tipos de elemento e faça diff do JSON — sua única proteção contra regressões do upstream.
9. **Se precisar de render automático**, planeje um caminho separado (FFmpeg headless a partir do draft, ou automação de UI via Accessibility API do macOS). Não conte com o repositório para isso.
10. **Antes de investir no wrapper**, execute o **Bloco A** dos testes. Se o CapCut atual não abrir corretamente um draft gerado, nada mais importa.

### Padrão de uso recomendado (para o agente)

```
get_video_duration(cada mídia)
  → create_draft(1080, 1920)
  → add_video/add_image/add_audio com start/end/target_start/duration EXPLÍCITOS
  → add_text (font_size na escala 5–12) / add_subtitle (com font)
  → add_effect (com effect_category e params=[])
  → add_video_keyframe (track_name = o mesmo usado no add_video)
  → inspect_draft (verificar)
  → save_draft (draft_folder = diretório de projetos do CapCut)
```

Tudo numa **única sessão do processo MCP**. Nunca assuma que um `draft_id` sobrevive a um reinício.

---

## Verdict

# `GO WITH RESTRICTIONS`

**Por quê `GO`:** o núcleo que importa — modelagem do timeline do CapCut, catálogos de efeitos/transições/animações/fontes, texto rico, keyframes, resolução de mídia, gravação da pasta de projeto — é real, funciona no macOS e é grande o suficiente para que reimplementá-lo do zero custaria muito mais do que corrigi-lo. O servidor MCP Python é diretamente utilizável a partir do Codex, sem HTTP, e foi validado de ponta a ponta nesta auditoria: draft criado, dois clipes sequenciais, texto, keyframe, projeto gravado em disco com JSON coerente. A licença Apache 2.0 permite fork e uso comercial.

**Por quê `WITH RESTRICTIONS`:**

- Use **apenas** `mcp_server.py`. `capcut_server.py`, `web_preview.py`, `desktop_companion.py` e `mcp-server/` (TS) estão quebrados ou são inúteis no macOS.
- Trabalhe sobre um **fork com commit fixo** e um **wrapper** que corrija `add_effect`, `add_subtitle`, a falha silenciosa de `save_draft`, o `draft_meta_info.json` e o caminho de projetos do macOS.
- Trate a documentação — README, `MCP_Documentation_English.md` e especialmente `vectcut-skill/.../api_reference.md` — como **não confiável**. O código é a especificação.
- Aceite que a entrega final é **um projeto para abrir no CapCut**, não um vídeo, e que a importação é manual.
- **Valide o Bloco A dos testes antes de construir qualquer coisa.** Se o draft gerado não abrir na sua versão do CapCut macOS, o veredito vira `NO-GO` até que o problema de perfil/versão seja resolvido — e nesse caso o próximo experimento mais barato é testar o perfil `jianying_pro_10`.

**Não é `NO-GO`** porque todos os defeitos encontrados são de integração e de camada de fachada — corrigíveis em dezenas de linhas — e não no motor de geração de drafts. **Não é `GO` puro** porque, no commit atual, metade dos caminhos anunciados não funciona no macOS e dois dos onze verbos MCP falham com os parâmetros que a própria documentação recomenda.
