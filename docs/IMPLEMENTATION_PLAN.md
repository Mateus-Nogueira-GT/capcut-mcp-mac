# IMPLEMENTATION_PLAN — Codex → MCP → VectCutAPI → CapCut Desktop

**Versão:** 0.1 · **Data:** 2026-09-14 · **Status:** plano para revisão — **nenhum código escrito**

**Documentos-fonte:**
- [`vectcut-research.md`](vectcut-research.md) — auditoria empírica do upstream (commit `b83be74`)
- [`CAPCUT_MCP_SPEC.md`](CAPCUT_MCP_SPEC.md) — contrato funcional, 49 funcionalidades classificadas
- `CAPCUT_ARCHITECTURE.md` — **não existe.** Nunca foi criado. A arquitetura vigente é a seção *System Architecture* do `CAPCUT_MCP_SPEC.md` (camadas L0/L1, decisões A1–A7), e é ela que este plano segue. Se um documento de arquitetura separado for desejado, ele deve ser extraído da spec **antes** da Phase 2 — não durante.

---

## Como ler este plano

| Elemento | Significado |
|---|---|
| `WI-<fase>.<n>` | Work Item — unidade de trabalho rastreável |
| **Teste verificável** | O que precisa passar para a fase fechar. Comando executável ou checklist de evidência. |
| **Bloqueia** | O que não pode começar antes desta fase fechar |
| 🔴 | Tarefa bloqueante sem workaround |
| 📋 | Produz artefato que outras fases consomem |
| ⚗️ | Experimento cujo resultado decide uma questão aberta (Q1–Q8 do Anexo B da spec) |
| Esforço | S ≈ ≤ 0,5 dia · M ≈ 1–2 dias · L ≈ 3–5 dias (estimativa, não compromisso) |

### Premissas

| # | Premissa | Origem |
|---|---|---|
| P1 | Somente o caminho **MCP Python in-process**. `capcut_server.py`, `web_preview.py`, `desktop_companion.py` e `mcp-server/` (TypeScript) ficam fora. | Spec N4, C3 — o HTTP não importa no macOS (`ctypes.windll`) |
| P2 | Duas camadas: **L0** = fork do VectCutAPI com commit fixo e **intocado**; **L1** = adaptador novo. | Spec A2, C2 |
| P3 | Nenhuma funcionalidade é declarada pronta por estar documentada. Cada uma passa por assert automatizado no JSON **e** verificação visual no CapCut. | Instrução explícita do escopo |
| P4 | O menor fluxo funcional (`create` → `save` → abre no CapCut) é entregue antes de qualquer feature. | Instrução explícita do escopo |
| P5 | O produto final é um **draft para abrir no CapCut**, nunca um vídeo renderizado. | Spec N1 |

---

## Estado do ambiente — já verificado nesta máquina

Levantado em 2026-09-14 por inspeção direta. A Phase 0 **não precisa repetir** o que está ✅; precisa fechar o que está ❌ e registrar tudo em arquivo versionado.

| Item | Estado | Valor verificado |
|---|---|---|
| Sistema operacional | ✅ | macOS 15.7.3 (build 24G419) |
| Arquitetura | ✅ | `arm64` — Apple M2 |
| Python disponível | ✅ | 3.14.0 (framework, default), 3.11.15, 3.12.13, 3.14.3 (`~/.local/bin`) |
| Gerenciador de ambiente | ✅ | **`uv` 0.11.1** · Homebrew 6.0.22 · sem pyenv/conda/poetry/pipx |
| Dependências Python do L0 | ✅ | `requirements.txt` (imageio, psutil, flask, requests, oss2, json5) instala limpo |
| FFmpeg | ✅ | ffmpeg 9.0.1 |
| Caminho do FFmpeg | ✅ | `/opt/homebrew/bin/ffmpeg` · `/opt/homebrew/bin/ffprobe` |
| **CapCut Desktop** | ✅ | **INSTALADO** em 2026-09-14 via `brew install --cask capcut` (CDN oficial `capcutstatic.com`, SHA256 fixado). Universal binary x86_64+arm64, 2,8 GB, assinado por TeamIdentifier `22MMUN2RN5` |
| Versão do CapCut | ✅ | **9.4.1** (`CFBundleShortVersionString` e `CFBundleVersion`) · bundle ID **`com.lemon.lvoverseas`** · `LSMinimumSystemVersion` 10.14 |
| Diretório real de drafts | ⏳ | criado no primeiro uso do app — WI-0.8 fecha após o projeto de referência |
| `~/Movies` | ✅ | existe, `drwx------`, sujeito a TCC |
| Permissões de escrita no destino | ⚠️ | a validar após instalar o CapCut |
| **Espaço em disco** | ⚠️ | **38 GiB livres** (eram 12 GiB e chegaram a **zero** durante esta sessão — ver R6) |
| Funcionamento básico do L0 | ✅ | create/add_video/add_audio/add_image/add_text/keyframe/sticker/save OK; `add_effect` e `add_subtitle` falham com os defaults |
| Servidor HTTP | ✅ (como *não usar*) | `import capcut_server` falha em `b83be74`; funciona em `71aafc1`. Fora de escopo por P1 |
| MCP server do L0 | ✅ | handshake + `tools/list` (11 tools) + `tools/call` OK via stdio no macOS |
| **Codex instalado** | ✅ | `~/.codex/config.toml` presente; app build `26.903.71938`; CLI em `/Applications/ChatGPT.app/Contents/Resources/codex` (fora do PATH) |
| **Formato de config MCP do Codex** | ✅ | **TOML confirmado neste host**: `[mcp_servers.<nome>]` com `command`, `args`, `cwd`, `enabled`, `startup_timeout_sec`, mais `[mcp_servers.<nome>.env]`. Há dois exemplos reais no config (`node_repl`, `computer-use`). |
| Upstream fixado | ✅ | `b83be7404bf2343581744b2ef72c07d9fbe39b7e` (2026-09-12), working tree limpo |

**Consequência imediata:** o único item que impede a Phase 0 de fechar é a **ausência do CapCut Desktop**. Sem ele, o Portão 0 da spec (AC0.1–AC0.5) não pode ser avaliado e **nenhuma fase posterior pode ser declarada concluída** — porque o critério de todas elas é "abre corretamente no CapCut".

---

## Mapa de fases e dependências

```
  Phase 0 ── Environment validation ──────────────────── 🔴 instalar CapCut
      │                                                  ⚗️ capturar projeto de referência
      ▼
  Phase 1 ── VectCutAPI baseline (sem MCP) ───────────── PORTÃO 0 da spec (AC0.1–0.5)
      │      "VectCut Baseline Test": 1 vídeo + 1 texto + 1 imagem + 1 áudio
      │      ⛔ SE FALHAR EM TODAS AS VARIANTES → PLANO SUSPENSO
      ▼
  Phase 2 ── MCP baseline (menor fluxo funcional) ────── PORTÃO 1 da spec (AC1.x)
      │      L1 mínimo: 3 tools (doctor, draft.create, draft.save) + Codex conectado
      ▼
  Phase 3 ── Core timeline editing ──────────────────┐
      │      vídeo · imagem · áudio · texto          │ Phases 4 e 5 podem correr
      ▼                                             │ em paralelo depois da 3
  Phase 4 ── Captions ──────────────────────────────┤
      │                                             │
  Phase 5 ── Advanced (effects/transitions/         │
      │      stickers/keyframes) ────────────────────┘
      ▼
  Phase 6 ── Reliability layer ──────────────────────── PORTÃO 2 da spec (AC2.x)
      ▼
  Phase 7 ── Codex usability ────────────────────────── PORTÃO 3 da spec (AC3.x)
      ▼
  Phase 8 ── End-to-end test ────────────────────────── PORTÃO 4 da spec (AC4.x)
             "VectCut MCP E2E Test" — 1080x1920, ~15 s, só via Codex
```

Paralelismo permitido: Phases 4 e 5 depois que a 3 fechar. Todo o resto é estritamente sequencial — cada fase consome o harness de verificação e as correções da anterior.

---

## Convenções de teste (valem para todas as fases)

### Estrutura de repositório proposta

```
capcut-mcp-mac/                        ← L1 (decisão Q8: repositório próprio)
├── src/capcut_mcp/
│   ├── server.py                      ← loop MCP stdio
│   ├── tools/                         ← uma tool por arquivo
│   ├── planner.py · validator.py · catalog.py
│   ├── deployer.py · registry.py · warnings.py
│   └── upstream.py                    ← ÚNICO ponto de import do L0
├── tests/
│   ├── fixtures/make_fixtures.sh      ← gera mídia determinística via ffmpeg
│   ├── unit/ · contract/ · snapshot/
│   └── manual/                        ← checklists de verificação no CapCut
├── evidence/<fase>/<WI>/              ← screenshots, JSONs, logs
└── vendor/VectCutAPI/                 ← submodule fixado em b83be74 (L0, read-only)
```

### Três níveis de verificação — nenhum substitui o outro

| Nível | O que faz | Automatizável |
|---|---|---|
| **N1 — Contrato** | A tool retorna o envelope esperado; erros com o código certo. | Sim (pytest) |
| **N2 — Estrutural** | O JSON gravado tem tracks/segmentos/timeranges corretos em µs; cada `path` de material existe em disco com tamanho > 0. | Sim (pytest + snapshot) |
| **N3 — Visual** | O projeto abre no CapCut, o timeline está correto, a mídia carrega, os tempos batem. | **Não.** Manual, com evidência registrada. |

**Regra dura:** nenhuma funcionalidade passa de `PARTIALLY_SUPPORTED` para `SUPPORTED` sem N1 + N2 + N3. N2 verde com N3 vermelho significa que a funcionalidade **não** funciona — foi exatamente o que a auditoria mostrou: JSON plausível não implica projeto abrível.

### Fixtures determinísticas

Geradas por `ffmpeg -f lavfi`, nunca mídia externa — o teste precisa ser reproduzível em qualquer máquina:

| Fixture | Fonte | Uso |
|---|---|---|
| `clip_a.mp4` | `testsrc=duration=6:size=640x360:rate=30` | vídeo principal |
| `clip_b.mp4` | `smptebars=duration=8:size=1080x1920:rate=30` | segundo clipe, vertical nativo |
| `tone.wav` / `tone.mp3` | `sine=frequency=440:duration=20` | música de fundo |
| `voice.wav` | `sine=frequency=220:duration=10` | voice-over |
| `pic.png` / `pic.jpg` | `testsrc`, 1 frame | imagem e teste de extensão trocada |
| `subs_pt.srt` | acentuação, `ç`, emoji, quebra de linha | legendas |
| `broken.mp4` | arquivo truncado deliberadamente | mídia inacessível |

### Formato de evidência (N3)

Uma tabela por WI em `evidence/<fase>/<WI>/RESULT.md`:

| Campo | Conteúdo |
|---|---|
| Projeto / caminho | nome e caminho absoluto |
| Versão do CapCut | exata |
| Perfil usado | `capcut_legacy` \| `jianying_pro_10` |
| Abriu? | sim/não + screenshot da lista de projetos |
| Timeline | screenshot |
| Mídia | todos os materiais carregados? lista dos faltantes |
| Tempos | valor pedido vs. valor lido na UI, por segmento |
| Limitações observadas | texto livre — **alimenta o registro de status** |
| Veredito | PASS / FAIL / PASS-COM-RESSALVA |

### Registro de status vivo

📋 `docs/STATUS_MATRIX.md` — as 49 funcionalidades × status atual × fase que verificou × link da evidência. **Atualizado no fim de cada fase.** É a fonte de verdade quando divergir da tabela estática da spec.

---

## Questões abertas × fase de resolução

| Q | Questão | Resolvida em | Como |
|---|---|---|---|
| Q1 | Perfil: `capcut_legacy` ou `jianying_pro_10`? | **Phase 1** | ⚗️ WI-1.6 — gerar o baseline nos dois perfis e ver qual abre |
| Q2 | `new_version`: manter `110.0.0` ou escrever o observado? | **Phase 1** | ⚗️ WI-1.7 — três variantes |
| Q3 | Randomizar `device_id`/`mac_address` do bloco `platform`? | **Phase 1** | ⚗️ WI-1.8 — aceitação + política de privacidade |
| Q4 | Faixa de `volume` e escala de `font_size` | **Phase 3** | ⚗️ WI-3.14 / WI-3.28 — calibração visual |
| Q5 | `save` sincrono ou assíncrono com `job_id`? | **Phase 2** | WI-2.12 — medir contra o timeout do Codex |
| Q6 | `http` permitido para sources remotos? | **Phase 6** | WI-6.18 — política + allowlist |
| Q7 | Local do registry de drafts | **Phase 2** | WI-2.9 — proposta: `~/Library/Application Support/capcut-mcp/` |
| Q8 | Adaptador em repo próprio ou dentro do fork? | **Phase 2** | WI-2.1 — proposta: repo próprio com o L0 como submodule |

---

## Desvios do escopo pedido — com justificativa

O escopo desta solicitação lista itens que a spec classifica como não suportados. Nenhum é silenciado; cada um tem tratamento explícito.

| Item pedido | Classificação na spec | Tratamento no plano | Justificativa |
|---|---|---|---|
| **Phase 3 — "reorganizar clips"** | `NOT_SUPPORTED` (VID-05) | Entregue **indiretamente** por `capcut.draft.rebuild` (WI-3.8): o L1 guarda o plano declarativo e reconstrói o draft com nova ordem. Nenhuma tool `reorder` é exposta. | Não existe API de remover/mover/reordenar segmento em nenhuma camada do upstream — inventário completo de `Script_file`/`Track` confirmado. Expor uma tool de reordenação seria prometer o que não há. |
| **Phase 3 — "overlapping quando suportado"** | ambíguo | Desambiguado: **(a)** overlap na *mesma* track = **erro por design** (`SEGMENT_OVERLAP`); **(b)** sobreposição visual entre tracks (PiP) = **suportado** via múltiplas tracks + `layer_index`. WI-3.10 cobre (b). | `Track.add_segment` levanta `SegmentOverlap` (`track.py:189-192`) — verificado. Empilhamento se faz por tracks, não por colisão. |
| **Phase 0 — "funcionamento do servidor HTTP, caso utilizado"** | fora de escopo (N4) | Verificado **uma vez** em WI-0.12 apenas para documentar que não é usado e por quê. Nenhum trabalho de correção do HTTP entra no plano. | P1/C3. Consertar o HTTP significaria manter duas fachadas divergentes — origem dos bugs de default (`main` vs `video_main`). |
| **Phase 6 — "backups automáticos" e "atomic writes"** | **não estão na spec** | Adicionados como WI-6.10/6.11; a spec ganha F13/F14 via changelog em WI-6.20. | Requisito explícito desta solicitação ("nunca sobrescrever sem backup") e mitigação direta do `shutil.rmtree` sem confirmação do upstream (`save_draft_impl.py:81-83`). É endurecimento, não mudança de arquitetura. |
| **Phase 6 — "validação de MIME"** | spec previa só extensão/container | Adicionado em WI-6.3 por sniffing de conteúdo. | O upstream renomeia tudo para `.mp4`/`.mp3`/`.png` sem transcodificar (WAV→`.mp3` verificado). Validar por extensão é insuficiente. |
| **Phase 5 — "stickers"** | `PARTIALLY_SUPPORTED`, sem catálogo | Testado (WI-5.12) mas entra como **experimental**: exige `resource_id` interno do CapCut sem fonte confiável. | Sem descoberta de IDs, a tool é inutilizável por um agente na prática. |

**Nenhuma alteração na arquitetura L0/L1, no inventário de 17 tools, ou nos portões da spec.** Os acréscimos acima são internos ao L1.

---

# Phase 0 — Environment validation

**Objetivo:** ambiente documentado, reproduzível, e com o CapCut real disponível para servir de oráculo.
**Esforço:** M (a maior parte é instalação e captura, não código)
**Entradas:** o estado já verificado na tabela acima.

## Tarefas

| WI | Tarefa | Notas |
|---|---|---|
| WI-0.1 | Registrar SO, build, arquitetura e chip em `evidence/phase0/ENVIRONMENT.md` | ✅ dados levantados: macOS 15.7.3 / 24G419 / arm64 / M2 |
| WI-0.2 | **Escolher e fixar a versão do Python.** Recomendação: **3.12.13** | Justificativa: os classifiers do upstream param em 3.12; o 3.14 funcionou na auditoria, mas é maior superfície de risco (a mensagem do bug do `font_type`, por exemplo, varia entre versões). Registrar a decisão. |
| WI-0.3 | Criar o venv com **`uv`** (já instalado) e gerar lockfile | `uv` é o único gerenciador presente |
| WI-0.4 | Instalar deps do L0 e validar import de cada módulo usado pelo L1 | Teste explícito de que `desktop_companion` **não** é importado transitivamente |
| WI-0.5 | Registrar ffmpeg/ffprobe: versão, caminho absoluto, e probe em cada fixture | ✅ ffmpeg 9.0.1 em `/opt/homebrew/bin` |
| WI-0.6 | 🔴 **Instalar o CapCut Desktop** (International, macOS arm64) | Bloqueante absoluto. Registrar origem do instalador e versão exata. |
| WI-0.7 | Registrar a versão do CapCut: `CFBundleShortVersionString` + `CFBundleVersion` | Entra na matriz de compatibilidade (spec C8) |
| WI-0.8 | Descobrir o diretório **real** de drafts criando um projeto manualmente no app e localizando a pasta | Ordem de busca da spec: env var → `~/Movies/CapCut/...` → `~/Movies/JianyingPro/...` → container `com.lemon.lvpro`. **Não assumir**: registrar o que o app usa. |
| WI-0.9 | 📋⚗️ **Capturar um projeto de referência** feito à mão no CapCut (1 vídeo + 1 texto) e arquivar a pasta inteira | **O artefato mais importante da fase.** Responde: qual é o arquivo de conteúdo? existe `Timelines/<uuid>/`? qual o `new_version`? o que há no `draft_meta_info.json`? Desenha Q1/Q2. |
| WI-0.10 | Validar permissões: leitura/escrita/criação/remoção no diretório de drafts, com o app fechado | `~/Movies` é `drwx------` e pode disparar TCC dependendo do processo |
| WI-0.11 | Definir o mínimo operacional de espaço em disco e a guarda no `save` | ⚠️ o disco chegou a **zero** nesta sessão. Proposta: abortar `save` abaixo de 2 GiB livres |
| WI-0.12 | Registrar, com um teste, que `import capcut_server` falha no macOS e por quê | Documenta a exclusão do HTTP (P1). Não consertar. |
| WI-0.13 | Validar o MCP do L0 por stdio: `initialize` → `tools/list` → `tools/call create_draft` | ✅ já verificado; transformar em teste automatizado |
| WI-0.14 | 📋 Documentar a configuração MCP do Codex no formato **confirmado neste host** | `[mcp_servers.capcut]` + `[mcp_servers.capcut.env]` em `~/.codex/config.toml`; usar `node_repl`/`computer-use` como referência de forma. Registrar `startup_timeout_sec`. |
| WI-0.15 | 📋 `tests/fixtures/make_fixtures.sh` — gerar todas as fixtures via ffmpeg, com hash conferido | Reprodutibilidade |
| WI-0.16 | 📋 Escrever `ENVIRONMENT.md` + `SETUP.md` (passo a passo do zero) | Critério de conclusão da fase |

## Teste verificável

```
tests/contract/test_phase0_environment.py   — deve passar 100%
```

1. `sys.version_info[:2]` == versão fixada em WI-0.2.
2. Todas as dependências do lockfile importam.
3. `shutil.which("ffprobe")` não é `None` **e** um probe em `clip_a.mp4` devolve 6,0 s ± 0,05.
4. `/Applications/CapCut.app/Contents/Info.plist` existe e a versão é legível.
5. O diretório de drafts resolvido existe, é gravável, e um `mkdir`/`rmdir` de teste funciona.
6. `evidence/phase0/reference_project/` contém a pasta capturada em WI-0.9, com ≥ 1 arquivo de conteúdo JSON válido.
7. Import de `desktop_companion` levanta `AttributeError` (documentação do bug) **e** nenhum módulo do L1 o importa (teste de grafo de imports).
8. Handshake MCP do L0 responde `tools/list` com 11 tools.
9. Espaço livre ≥ limite definido em WI-0.11.
10. `SETUP.md` executado em ambiente limpo reproduz tudo acima (validação manual, uma vez).

## Critério de conclusão

`ENVIRONMENT.md` + `SETUP.md` + lockfile + fixtures + projeto de referência arquivado, com o teste acima verde.

## Bloqueia

Tudo. **Sem WI-0.6 e WI-0.9, a Phase 1 não pode ser avaliada.**

## Riscos

| Risco | Mitigação |
|---|---|
| CapCut não instalável / exige conta | Não há substituto: sem CapCut não existe oráculo. Escalar como decisão de negócio. |
| Espaço em disco insuficiente | WI-0.11; assets são copiados, não linkados |
| TCC bloqueia acesso a `~/Movies` pelo processo do MCP | Detectar em WI-0.10; conceder permissão ao app hospedeiro |
| Versão do CapCut divergente do template | É o que WI-0.9 vai revelar — melhor descobrir aqui do que na Phase 1 |

---

# Phase 1 — VectCutAPI baseline (sem MCP)

**Objetivo:** provar que o L0 produz um projeto que o CapCut abre. **É a fase que decide a viabilidade do projeto inteiro** (Portão 0 da spec).
**Esforço:** M · **Entradas:** WI-0.9 (projeto de referência), fixtures, venv.

> Nenhuma linha do L1 é escrita aqui. Só scripts de teste chamando o L0 diretamente.

## Tarefas

| WI | Tarefa |
|---|---|
| WI-1.1 | Harness `baseline_build.py` (teste, não produto) chamando o L0 direto: `get_or_create_draft` → `add_video_track` → `add_image_impl` → `add_audio_track` → `add_text_impl` → `save_draft_impl` |
| WI-1.2 | Validar isoladamente, com assert no JSON: criação de draft · resolução · rótulo de aspect ratio · formato do `draft_id` |
| WI-1.3 | Validar isoladamente cada adição (vídeo, imagem, áudio, texto) com `draft_folder` explícito |
| WI-1.4 | Construir **`VectCut Baseline Test`**: 1080×1920 · 1 vídeo (`clip_a.mp4`, 0–5 s) · 1 imagem (`pic.png`, 5–8 s) · 1 áudio (`tone.wav`, 0–8 s, volume 0.3) · 1 texto ("Baseline", 0–3 s, `font_size` 9.0) |
| WI-1.5 | **Passar `source_end`/`duration` explicitamente em todas as adições** — evita a resolução tardia que apagou 2 de 3 clipes na auditoria |
| WI-1.6 | ⚗️ **Q1** — gerar o baseline em `capcut_legacy` **e** em `jianying_pro_10`, salvar como dois projetos, e testar ambos no CapCut |
| WI-1.7 | ⚗️ **Q2** — para o perfil vencedor, três variantes de `new_version`: `110.0.0` (atual), o valor observado em WI-0.9, e omitido |
| WI-1.8 | ⚗️ **Q3** — duas variantes do bloco `platform`: o hardcoded do upstream vs. valores desta máquina |
| WI-1.9 | ⚗️ **Metadados** — duas variantes do `draft_meta_info.json`: copiado do template (comportamento atual) vs. reescrito com nome/paths/UUID próprios. **Hipótese da auditoria: a variante reescrita é necessária.** |
| WI-1.10 | Salvar direto no diretório de drafts do CapCut (spec F2), com o app **fechado** |
| WI-1.11 | Executar as 5 verificações no CapCut e registrar evidência por variante |
| WI-1.12 | 📋 Preencher a matriz de compatibilidade (spec C8) e **decidir Q1, Q2, Q3 e a política de metadados** |
| WI-1.13 | 📋 Criar o snapshot de referência do JSON do baseline — usado pelas fases seguintes para detectar regressão |

## Teste verificável

**N2 — automatizado** (`tests/snapshot/test_baseline_structure.py`):

1. O arquivo de conteúdo do perfil vencedor é JSON válido.
2. `canvas_config` == `{width:1080, height:1920, ratio:"9:16"}`.
3. Existem exatamente as tracks esperadas, **sem track vazia espúria** (a auditoria viu uma track `video` vazia sempre criada — se persistir, registrar como limitação conhecida, não como falha).
4. Vídeo: `target_timerange == {start:0, duration:5_000_000}`.
5. Imagem: `target_timerange == {start:5_000_000, duration:3_000_000}`.
6. Áudio: `target_timerange == {start:0, duration:8_000_000}`, volume 0.3.
7. Texto: `target_timerange == {start:0, duration:3_000_000}`, conteúdo contém "Baseline".
8. `duration` total == 8_000_000.
9. Cada `materials.*[].path` existe em disco com `getsize() > 0`.
10. Nenhum `path` aponta para dentro do clone do VectCutAPI.

**N3 — manual, checklist obrigatório** (as 5 verificações do escopo):

| # | Verificação | PASS/FAIL |
|---|---|---|
| 1 | O draft **aparece** na lista de projetos do CapCut, com o nome `VectCut Baseline Test` | |
| 2 | O CapCut **abre** o projeto sem erro e sem diálogo de reparo | |
| 3 | O timeline **não está corrompido**: 4 elementos nas tracks corretas, nenhum segmento fantasma | |
| 4 | Os 4 **arquivos de mídia** carregam (sem placeholder de mídia faltando) | |
| 5 | Os **tempos** conferem: vídeo 0–5 s, imagem 5–8 s, áudio 0–8 s, texto 0–3 s (tolerância 1 frame) | |

## Critério de conclusão

As 5 verificações em PASS para **pelo menos uma** combinação de perfil/variantes, com a combinação vencedora registrada.

## Bloqueia

Phase 2 em diante.

## ⛔ Condição de suspensão do plano

**Se nenhuma combinação de perfil × `new_version` × `platform` × metadados fizer o CapCut abrir o projeto**, este plano é suspenso e o trabalho volta para investigação de formato (Unknowns #1–#5 da auditoria). Nenhuma fase seguinte tem valor nesse cenário, e o veredito `GO WITH RESTRICTIONS` da auditoria vira `NO-GO` até a questão ser resolvida.

## Riscos

| Risco | Mitigação |
|---|---|
| Nenhum perfil funciona | Ver condição de suspensão. Antes disso, testar o caminho inverso: partir do projeto de referência (WI-0.9) e injetar nele apenas materiais e segmentos, preservando todo o resto do arquivo do app |
| Projeto abre com timeline vazio | Sintoma clássico do arquivo de conteúdo errado (raiz vs. `Timelines/<uuid>/`). WI-1.6 cobre |
| Mídia não encontrada | Caminhos absolutos do L0 apontam para o diretório de salvamento — por isso F2 (salvar direto no destino) |
| `draft_id` UUID duplicado quebra a biblioteca com 2 projetos | WI-1.9 é a mitigação |

---

# Phase 2 — MCP baseline (menor fluxo funcional possível)

**Objetivo:** Codex → MCP → `create` → `save` → projeto válido no CapCut. **Três tools, nada mais.**
**Esforço:** M · **Entradas:** Q1/Q2/Q3 e a política de metadados, fechadas na Phase 1.

> Este é o *walking skeleton*. A tentação de já incluir `video.add` deve ser recusada: o que se prova aqui é o **caminho**, com o menor número de variáveis.

## Tarefas

| WI | Tarefa |
|---|---|
| WI-2.1 | Decidir **Q8** e criar o repositório do L1 com o L0 como submodule fixado em `b83be74` |
| WI-2.2 | `upstream.py` — único ponto de import do L0, com guarda que falha se um módulo proibido for importado |
| WI-2.3 | Loop MCP stdio: `initialize` (ecoando a `protocolVersion` do cliente), `tools/list`, `tools/call`; `prompts/list`/`resources/list` → lista vazia (spec C14) |
| WI-2.4 | Envelope de resposta padrão (`ok`/`data`/`warnings`/`meta`) + `isError` no nível do protocolo (spec E6) |
| WI-2.5 | **Warning bus**: capturar o stdout do L0 e convertê-lo em `warnings[]` estruturados. **Nunca descartar** (spec O1) |
| WI-2.6 | Logging JSONL em `~/Library/Logs/capcut-mcp/`, com stdout mantido limpo (spec O3) |
| WI-2.7 | `capcut.system.doctor` — primeira tool: versões, diretórios resolvidos, permissões, espaço, presença do CapCut |
| WI-2.8 | `capcut.draft.create` — com `name`; `width`/`height` **não** aparecem em tools de mídia (spec PRJ-02) |
| WI-2.9 | Decidir **Q7** e implementar o registry de drafts em disco (spec D3) |
| WI-2.10 | `capcut.draft.save` — com `target`/`path`/`overwrite`, deploy no diretório real do macOS, e reescrita do `draft_meta_info.json` conforme decidido na Phase 1 |
| WI-2.11 | `DRAFT_NOT_FOUND` explícito: `draft_id` desconhecido **nunca** cria draft novo (spec D2) e `save` de draft ausente **nunca** retorna sucesso (spec AC2.4) |
| WI-2.12 | Medir a duração do `save` do baseline e **decidir Q5** contra o `startup_timeout_sec` e o timeout de tool-call do Codex |
| WI-2.13 | Escrever a entrada `[mcp_servers.capcut]` no `~/.codex/config.toml` (formato confirmado em WI-0.14) |
| WI-2.14 | Validar no Codex: servidor inicializa · conecta · descobre tools · schemas carregados · chamada simples · erro estruturado · log localiza a falha |
| WI-2.15 | Teste de injeção de falha: provocar um erro em cada tool e confirmar que o log aponta arquivo/linha/causa |

## Teste verificável

**N1 — automatizado** (`tests/contract/test_mcp_baseline.py`), contra o servidor por stdio:

1. `initialize` responde e ecoa a `protocolVersion` enviada.
2. `tools/list` devolve exatamente 3 tools (`doctor`, `draft.create`, `draft.save`), todas com `additionalProperties: false`.
3. `prompts/list` e `resources/list` devolvem lista vazia, não `-32601`.
4. `draft.create` devolve `draft_id` e **nenhuma URL externa** no payload.
5. `draft.save` com `draft_id` inexistente → `ok:false`, `error.code == "DRAFT_NOT_FOUND"`, `isError:true`, e **zero bytes escritos** no destino.
6. `draft.save` de draft vazio → `DRAFT_EMPTY`.
7. `draft.save` com destino existente e sem `overwrite` → `TARGET_EXISTS`.
8. Toda resposta de erro tem `suggestion` não vazia.
9. Nenhuma mensagem contém caractere CJK (spec E3) nem traceback do Python (spec E2).
10. O `stdout` do processo contém **apenas** JSON-RPC válido (nenhum log vazado).
11. Após reiniciar o servidor, um `draft_id` do registry é resolvido por replay (spec D4).

**N3 — manual**, o teste do escopo, executado **no Codex**:

```
Codex → MCP → capcut.draft.create(1080x1920, name="VectCut MCP Baseline")
            → capcut.draft.save(target="capcut")
            → abrir no CapCut
```

## Critério de conclusão

O Codex cria e salva um projeto que abre no CapCut, sem nenhuma intervenção manual além de abrir o app. Projeto vazio é aceitável nesta fase.

## Bloqueia

Phases 3–8.

## Riscos

| Risco | Mitigação |
|---|---|
| Codex não carrega o servidor | `startup_timeout_sec` generoso; `doctor` como primeira chamada de diagnóstico; log em arquivo desde o primeiro byte |
| `save` estoura o timeout de tool-call | Q5 → `save` assíncrono com `job_id` + `capcut.draft.save_status` |
| Qualquer `print` do L0 corrompe o protocolo | WI-2.5 é pré-requisito de tudo; o teste 10 é a rede de proteção |
| Projeto vazio não aparece na lista do CapCut | Aceitar e adiar: reavaliar com 1 segmento no início da Phase 3 |

---

# Phase 3 — Core timeline editing

**Objetivo:** o fluxo principal de edição, uma operação por vez, cada uma verificada no CapCut antes da próxima.
**Esforço:** L · **Entradas:** Phase 2 fechada.

> **Disciplina obrigatória** para cada operação: (1) executar; (2) salvar; (3) abrir no CapCut; (4) verificar visualmente; (5) registrar limitações. Não agrupar operações num teste único nesta fase.

## Tarefas — Vídeo

| WI | Operação | Risco conhecido |
|---|---|---|
| WI-3.1 | `capcut.video.add` — 1 vídeo | Nome de track default único em todas as tools (spec AC2.12) |
| WI-3.2 | Múltiplos vídeos em sequência na mesma track | ⚠️ **exigir duração explícita**; sem ela a auditoria perdeu 2 de 3 clipes |
| WI-3.3 | `timeline_start` | ⚠️ avisar se > 0 na track base (o CapCut força alinhamento em 0) |
| WI-3.4 | Duração | derivada de `source_start`/`source_end`/`speed` |
| WI-3.5 | Trim: `source_start` | |
| WI-3.6 | Trim: `source_end` | ⚠️ além da duração real → erro no add, não encurtamento mudo |
| WI-3.7 | Trim combinado + corte em dois segmentos do mesmo source | |
| WI-3.8 | **`capcut.draft.rebuild`** — reordenação via replay do plano | Substitui "reorganizar clips" (ver Desvios) |
| WI-3.9 | Múltiplas tracks de vídeo | |
| WI-3.10 | Sobreposição visual entre tracks (PiP) + `layer_index` | E confirmar que overlap na mesma track dá `SEGMENT_OVERLAP` |
| WI-3.11 | `volume` | |
| WI-3.12 | `transform_x`/`transform_y` | ⚠️ unidade "meia tela", Y positivo = cima. Declarar na descrição da tool |
| WI-3.13 | `scale_x`/`scale_y` | |
| WI-3.14 | ⚗️ **Q4** — calibrar a faixa aceitável de `volume` (0–1? 0–2?) | |

## Tarefas — Imagem

| WI | Operação |
|---|---|
| WI-3.15 | `capcut.image.add` |
| WI-3.16 | Duração |
| WI-3.17 | Posição temporal (`timeline_start`) |
| WI-3.18 | Escala |
| WI-3.19 | Posição visual — **unificar os defaults de máscara com os do vídeo** (a auditoria achou `mask_center` 0.0/0.5 divergentes) |

## Tarefas — Áudio

| WI | Operação | Notas |
|---|---|---|
| WI-3.20 | Música de fundo (`role="background"`) | |
| WI-3.21 | Voice-over em track separada | |
| WI-3.22 | `volume` nas duas tracks | ⚗️ **Q4** |
| WI-3.23 | Início / fim / trim | ⚠️ o L0 reatribui a variável `duration` internamente — sempre passar `source_end` |
| WI-3.24 | Múltiplas tracks de áudio simultâneas | |

## Tarefas — Texto

| WI | Operação | Notas |
|---|---|---|
| WI-3.25 | Conteúdo, incluindo acentuação PT-BR | |
| WI-3.26 | Início / fim | obrigatórios; ausência → `MISSING_REQUIRED_PARAM`, não `TypeError` |
| WI-3.27 | Posição | mesma unidade do vídeo |
| WI-3.28 | ⚗️ **Q4** — calibrar `font_size` | testar 5.0 / 8.0 / 9.0 / 12.0 / 48.0 em 1080×1920 e **produzir a tabela real**, substituindo a tabela não verificada do skill `capcut-director` |
| WI-3.29 | Estilo: bold/italic/underline/align/line_spacing/letter_spacing | |
| WI-3.30 | Cor + borda + background + sombra | fixar um conjunto único de defaults (os do L0 divergem entre camadas) |
| WI-3.31 | Multi-estilo por faixa (`text_styles`) + validação de faixas | `INVALID_STYLE_RANGE` — o L0 não valida |
| WI-3.32 | `capcut.catalog.list(kind="font")` — 335 fontes, paginado e filtrável | ⚠️ o catálogo é do backend do CapCut, não do sistema: verificar quais realmente renderizam |

## Tarefas — Transversais

| WI | Tarefa |
|---|---|
| WI-3.33 | `capcut.media.probe` em lote, com cache de sessão |
| WI-3.34 | **Planner**: resolver duração → calcular timeline em cadeia → detectar colisão **antes** de mutar |
| WI-3.35 | `capcut.draft.inspect` — estado real: tracks, segmentos com id e timerange, materiais, keyframes pendentes vs. aplicados |
| WI-3.36 | Atomicidade por chamada (spec E5): operação que falha não deixa track órfã |
| WI-3.37 | 📋 Atualizar `STATUS_MATRIX.md` com o resultado real de cada uma das ~30 operações |

## Teste verificável

**N2 — automatizado:** um teste por WI, cada um construindo um draft mínimo com **só aquela operação** e afirmando sobre o JSON. Mais:

1. `test_multi_clip_no_silent_loss`: 3 clipes sequenciais → **3 segmentos** sobrevivem ao save (regressão direta do achado da auditoria).
2. `test_overlap_is_error`: mesma track + tempos colidentes → `SEGMENT_OVERLAP`, e o draft fica inalterado.
3. `test_no_implicit_draft`: qualquer `add` com `draft_id` inválido → `DRAFT_NOT_FOUND` e nenhum draft novo no registry.
4. `test_rebuild_reorders`: rebuild com ordem invertida produz os mesmos materiais e timeranges recalculados.
5. `test_track_naming_consistency`: o nome de track default é idêntico em todas as tools.

**N3 — manual:** um projeto por grupo (vídeo / imagem / áudio / texto), aberto no CapCut, com a tabela de evidência preenchida. Para WI-3.14 e WI-3.28, anexar screenshot comparativo das variantes.

## Critério de conclusão

Todas as operações com N1+N2+N3 em PASS, ou com limitação registrada no `STATUS_MATRIX.md`; Q4 fechada com tabela de calibração.

## Riscos

| Risco | Mitigação |
|---|---|
| Escala de `font_size` inutilizável | WI-3.28 é experimento, não implementação — o resultado define os defaults |
| Unidade de transform confunde o agente | Descrições declaram unidade e sentido; considerar variantes `*_px` |
| Track vazia espúria do L0 aparece no app | Se incomodar visualmente, o L1 filtra tracks vazias na serialização (mudança interna ao L1, permitida) |
| Volume de trabalho da fase | É a maior fase; entregar em 4 lotes (vídeo → imagem → áudio → texto), cada um com seu gate |

---

# Phase 4 — Captions

**Objetivo:** legendas confiáveis em português, com estilo reutilizável.
**Esforço:** M · **Entradas:** Phase 3 (texto) fechada.

> Ponto de partida: a tool upstream `add_subtitle` **falha sempre** com os parâmetros documentados (`NameError: font_type` quando `font` é omitido, e o schema declara `font` como opcional). Verificado. A fase começa corrigindo isso.

## Tarefas

| WI | Tarefa | Notas |
|---|---|---|
| WI-4.1 | `capcut.subtitle.add` com **`font` obrigatório** e `MISSING_FONT` acionável | Correção do bug (spec AC2.1) |
| WI-4.2 | Preset de estilo default **com contraste** (borda ou background ligados) | Os defaults do L0 são 0.0 para ambos — ilegível sobre vídeo |
| WI-4.3 | Criação manual: aceitar `segments: [{start, end, text}]` e serializar para SRT internamente | |
| WI-4.4 | Múltiplos segmentos: **teste com ≥ 5 legendas consecutivas** | Requisito do escopo |
| WI-4.5 | Timestamps: conferir cada bloco no JSON contra a entrada | |
| WI-4.6 | `time_offset` global + erro se algum bloco ficar negativo | Único controle temporal existente |
| WI-4.7 | Caracteres especiais e **português**: `ã õ ç é ê à`, `—`, `…`, emoji | Parser lê `utf-8-sig`; validar BOM |
| WI-4.8 | Quebra de linha dentro de um bloco | Comportamento do parser caseiro não avaliado na auditoria |
| WI-4.9 | Posição (`transform_y`), fonte, tamanho, cor | |
| WI-4.10 | Outline (`border_*`) e background (`background_*`) | |
| WI-4.11 | Estilo reutilizável: preset nomeado no L1 (`subtitle_style`) | `style_reference` do L0 não é exposto e exige um segmento existente — preset no L1 é o caminho |
| WI-4.12 | Garantir que falha de import **não deixa track vazia** | A auditoria observou a track `subtitle` órfã após a exceção |
| WI-4.13 | SRT malformado → `SRT_PARSE_ERROR` com número de linha | |
| WI-4.14 | Retornar `blocks_imported` e conferir contra a entrada | O L0 não retorna contagem |
| WI-4.15 | 📋 Atualizar `STATUS_MATRIX.md` (SUB-01..04) | |

## Teste verificável

**N2 — automatizado:**

1. 5 legendas consecutivas → **5 segmentos** na track, ordem preservada.
2. Timestamps: cada `target_timerange` == valor de entrada convertido para µs.
3. Sem sobreposição entre blocos consecutivos; gap conferido.
4. Texto com acentuação e emoji sobrevive ao round-trip JSON sem mojibake.
5. Quebra de linha preservada no material de texto.
6. `font` omitido → `MISSING_FONT` (nunca `NameError`).
7. SRT malformado → `SRT_PARSE_ERROR` com linha, e draft inalterado.
8. `blocks_imported == 5`.

**N3 — manual:** projeto `VectCut Captions Test` com as 5 legendas em PT-BR sobre `clip_b.mp4`, aberto no CapCut. Conferir **sincronização** (cada legenda no tempo certo), **sobreposição** (nenhuma), **ordem** (sequencial) e **renderização** (acentuação correta, quebra de linha correta, contraste legível, dentro da safe zone).

## Critério de conclusão

As 5 legendas renderizam corretamente no CapCut, com acentuação PT-BR íntegra, e o preset de estilo é reutilizável entre projetos.

## Riscos

| Risco | Mitigação |
|---|---|
| Fonte escolhida não renderiza acentuação | WI-4.7 testa; manter lista curta de fontes validadas para PT-BR |
| Quebra de linha ignorada pelo parser | Se confirmado, o L1 divide em blocos ou usa `\n` literal — decidir com a evidência |
| Estilo por bloco é impossível | Já declarado fora de escopo na spec; reconfirmar na descrição da tool |

---

# Phase 5 — Advanced editing

**Objetivo:** efeitos, transições, stickers e keyframes — **cada recurso com teste mínimo independente**, sem misturar.
**Esforço:** L · **Entradas:** Phase 3 fechada.

## Tarefas — Effects

| WI | Tarefa | Notas |
|---|---|---|
| WI-5.1 | `capcut.effect.add` funcionando **sem** `params` | Corrige `params[::-1]` com `None` (spec AC2.2) |
| WI-5.2 | `category` obrigatório e validado | Corrige o parâmetro ausente do schema |
| WI-5.3 | `capcut.catalog.list(kind="effect_scene"/"effect_character")` — 345/95, paginado e filtrável | |
| WI-5.4 | `capcut.catalog.effect_params(effect)` — nome/default/min/max na ordem canônica | Metadados já existem |
| WI-5.5 | **Params por nome** (`{"effects_adjust_blur": 60}`) e compensação da inversão do L0 | ⚠️ testar obrigatoriamente com efeito de **2+ params** (`Zoom_Lens`) |
| WI-5.6 | Intervalo na timeline + alocação automática de `effect_NN` | Efeitos simultâneos exigem tracks distintas |
| WI-5.7 | Compatibilidade: amostra de 20–30 efeitos — quais resolvem, quais são VIP, quais quebram | |

## Tarefas — Transitions

| WI | Tarefa |
|---|---|
| WI-5.8 | Catálogo de 116 transições com `default_duration` e `is_vip` |
| WI-5.9 | Aplicar em vídeo→vídeo e imagem→vídeo; identificar quais pares são compatíveis |
| WI-5.10 | Duração: default do metadado, valor custom, e aviso quando ≥ duração de um clipe adjacente |
| WI-5.11 | Registrar limitações: consumo de tempo do clipe adjacente, comportamento no primeiro/último segmento |

## Tarefas — Stickers (experimental)

| WI | Tarefa | Notas |
|---|---|---|
| WI-5.12 | `capcut.sticker.add` com `resource_id`, posição, duração, escala | ⚠️ **sem catálogo**: exige ID interno do CapCut |
| WI-5.13 | Investigar fonte confiável de `resource_id` (inclusive extrair de um projeto de referência via `inspect_material`) | Sem fonte, a tool fica `experimental` e **não** é oferecida como primária ao agente |

## Tarefas — Keyframes

| WI | Tarefa | Notas |
|---|---|---|
| WI-5.14 | `scale` (`scale_x`/`scale_y`/`uniform_scale`) + erro de exclusividade | O L0 não valida a exclusividade |
| WI-5.15 | `position_x` | ⚠️ unidade "meia tela" |
| WI-5.16 | `position_y` | ⚠️ positivo = cima |
| WI-5.17 | `rotation` (graus, aceita `"45deg"`) | |
| WI-5.18 | `opacity` (`alpha`, aceita `"50%"`) | |
| WI-5.19 | `KEYFRAME_OUTSIDE_SEGMENT` quando nenhum segmento cobre o instante | ⚠️ hoje é descarte silencioso com `print` engolido (spec AC2.6) |
| WI-5.20 | ⚗️ **KF-06** — decidir por teste se keyframes funcionam em tracks de áudio/texto | Até haver evidência, só vídeo é aceito |
| WI-5.21 | Catálogo das 11 propriedades com unidade, faixa e tipos de segmento compatíveis | |
| WI-5.22 | 📋 Atualizar `STATUS_MATRIX.md` (FX, KF, stickers, transições) | |

## Teste verificável

**N2 — automatizado, um teste isolado por recurso:**

1. `effect.add` sem `params` → sucesso; `params` inválido → `INVALID_EFFECT_PARAMS`.
2. Efeito de 2 params por nome → valores na posição **canônica** no JSON (prova a compensação da inversão).
3. Efeitos simultâneos em tracks distintas coexistem; na mesma track → `SEGMENT_OVERLAP`.
4. Transição aplicada aparece em `materials.transitions` e é referenciada pelo segmento.
5. Transição mais longa que o clipe → `warning` emitido.
6. Cada uma das 5 propriedades de keyframe produz `common_keyframes` no segmento correto.
7. Keyframe em `t` fora de qualquer segmento → `KEYFRAME_OUTSIDE_SEGMENT`.
8. `scale_x` + `uniform_scale` juntos → erro.
9. Recurso VIP → `warning` com o nome do recurso.
10. Contagens dos catálogos conferem: 345 / 95 / 116 / 9 / 335 / 29 / 11.

**N3 — manual:** **um projeto por recurso** (`FX Test`, `Transition Test`, `Sticker Test`, `Keyframe Test`), cada um com um único recurso aplicado, aberto no CapCut. Só depois de os quatro passarem individualmente, um projeto combinado.

## Critério de conclusão

Cada recurso verificado isoladamente no CapCut, com limitações registradas. Stickers podem fechar como `experimental` sem bloquear a fase.

## Riscos

| Risco | Mitigação |
|---|---|
| Muitos efeitos são VIP e aparecem travados | WI-5.7 mapeia; o catálogo expõe `is_vip` e o validador avisa |
| Efeitos de personagem com escopo global (o L0 usa `apply_target_type=2`) | Testar em WI-5.7 e registrar como limitação se o comportamento for errado |
| Stickers sem fonte de ID | Aceitar como `experimental`; não é bloqueante |
| Keyframes sem controle de easing | Limitação estrutural do L0 — registrar, não tentar contornar |

---

# Phase 6 — Reliability layer

**Objetivo:** transformar o protótipo em algo que não destrói trabalho do usuário.
**Esforço:** M–L · **Entradas:** Phases 3–5 fechadas.

> **Regra dura desta fase:** nunca sobrescrever um draft existente sem backup. Vale para o `save` do L1 e para qualquer escrita no diretório do CapCut.

## Tarefas

| WI | Tarefa | Origem |
|---|---|---|
| WI-6.1 | Validação de arquivo: existência, legibilidade, tamanho > 0 — **no `add`**, não no `save` | Auditoria: hoje falha de download conta como sucesso |
| WI-6.2 | Validação de extensão contra allowlist por tipo | Spec MED-03 |
| WI-6.3 | **Validação de MIME por sniffing de conteúdo** + `FORMAT_EXTENSION_MISMATCH` | Acréscimo justificado: o L0 renomeia tudo (WAV→`.mp3` verificado) |
| WI-6.4 | Validação de duração: `source_end` ≤ duração real; duração > 0 | |
| WI-6.5 | Path normalization: expandir `~`, resolver relativos, NFC no unicode, recusar `..` e caminho absoluto em `project_name` | Spec F4 |
| WI-6.6 | Arquivo inexistente → `SOURCE_NOT_FOUND` no add | |
| WI-6.7 | Mídia inacessível (permissão, rede, `broken.mp4`) → `SOURCE_UNREADABLE`/`ASSET_FETCH_FAILED` com a lista de falhas | Spec AC2.7 |
| WI-6.8 | IDs únicos: `draft_id` do registry + **UUID novo no `draft_meta_info.json` por projeto** | Auditoria: hoje é o mesmo UUID em todos |
| WI-6.9 | **Draft locking**: respeitar `.locked` do CapCut (`PROJECT_LOCKED`) + lock próprio do L1 contra dois saves concorrentes | Spec F9 |
| WI-6.10 | **Backups automáticos**: antes de qualquer sobrescrita, copiar a pasta para `<destino>.bak-<timestamp>/`, com retenção configurável | Requisito do escopo; mitiga o `rmtree` do L0 |
| WI-6.11 | **Atomic writes**: escrever em diretório temporário no mesmo volume e `os.replace` no final; nunca deixar projeto meio-escrito | Requisito do escopo |
| WI-6.12 | Validação do JSON pós-escrita: reler, parsear, conferir invariantes (canvas, contagem de tracks/segmentos, paths existentes) | |
| WI-6.13 | Detecção de draft corrompido: JSON inválido, `path` apontando para arquivo ausente, timerange negativo/degenerado, `duration` incoerente | |
| WI-6.14 | Recuperação: `capcut.draft.restore(project, backup_id)` | |
| WI-6.15 | Logs estruturados completos (spec O2) + correlação `warning → segment_id/track` (spec O8) | |
| WI-6.16 | Revisão de **todas** as mensagens de erro: código + causa + `suggestion`; zero CJK; zero traceback | Spec E2/E3/E4 |
| WI-6.17 | **Retries só para operações seguras**: download HTTP idempotente e probe. **Nunca** re-executar mutação de draft nem escrita de arquivo | |
| WI-6.18 | Decidir **Q6** e implementar allowlist de esquema/host + bloqueio de IP privado/loopback/link-local e `file://` | Spec S2 |
| WI-6.19 | Guarda de espaço em disco antes do save (limite de WI-0.11) | Ver R6 |
| WI-6.20 | 📋 Changelog na spec: acrescentar F13 (backup antes de sobrescrever) e F14 (atomic write) ao File Handling | Rastreabilidade do desvio |

## Teste verificável

**N1/N2 — automatizado** (`tests/contract/test_reliability.py`):

1. `add` com arquivo inexistente → `SOURCE_NOT_FOUND`; nada muda no draft.
2. `add` com `broken.mp4` → `SOURCE_UNREADABLE`.
3. JPEG renomeado para `.png` → `FORMAT_EXTENSION_MISMATCH` (warning), e o asset gravado mantém a extensão real.
4. `save` sobre projeto existente com `overwrite:true` → **backup criado e verificado** antes de qualquer escrita.
5. `save` interrompido no meio (falha injetada) → destino **inalterado** (prova do atomic write) e backup intacto.
6. `save` em projeto com `.locked` → `PROJECT_LOCKED`, zero escrita.
7. Dois `save` concorrentes no mesmo projeto → o segundo recebe erro de lock, sem corrupção.
8. `draft.restore` recupera o estado anterior byte-a-byte.
9. Draft corrompido artificialmente é detectado com o código específico.
10. Espaço em disco abaixo do limite → `DISK_FULL` antes de começar a copiar.
11. Retry acontece **só** em download/probe; nenhuma mutação é repetida (verificado por contador de chamadas).
12. Varredura de todas as mensagens de erro do código: nenhuma CJK, nenhuma sem `suggestion`.
13. URL para IP privado → bloqueada.

**N3 — manual:** simular o desastre — salvar por cima de um projeto real editado à mão no CapCut, confirmar que o backup preserva a versão anterior, e que ela pode ser restaurada e reaberta no app.

## Critério de conclusão

Todos os testes verdes **e** a prova manual de que nenhum trabalho do usuário é perdido em sobrescrita.

## Riscos

| Risco | Mitigação |
|---|---|
| Backups consomem o disco | Retenção configurável (default: 3 últimos) + guarda de espaço (R6) |
| `os.replace` não é atômico entre volumes | Temp sempre no mesmo volume do destino |
| Lock deixa resíduo após crash | Lock com PID + timestamp e expiração |

---

# Phase 7 — Codex usability

**Objetivo:** o agente usa as tools corretamente **sem ler o código-fonte**.
**Esforço:** M · **Entradas:** Phases 3–6 fechadas.

> Métrica desta fase: taxa de acerto do agente na primeira tentativa. É a única fase cujo sucesso se mede com o agente, não com pytest.

## Tarefas

| WI | Tarefa |
|---|---|
| WI-7.1 | Revisar nomes: `capcut.<domínio>.<ação>`, verbos previsíveis, nenhuma tool genérica tipo `capcut.do` |
| WI-7.2 | Reescrever descrições para conter **o que o agente não pode adivinhar**: unidade de tempo (s na entrada, µs na saída), escala de `font_size`, unidade e sentido de `transform_*`, exigência de nome exato de enum, ordem dos params de efeito |
| WI-7.3 | Schemas: `additionalProperties:false`, tipos estritos, `enum` onde há domínio fechado, ranges declarados |
| WI-7.4 | Minimizar obrigatórios; defaults sensatos e **idênticos** entre tools (nome de track, fonte, contraste de legenda) |
| WI-7.5 | Toda mensagem de erro com `suggestion` acionável e até 3 candidatos por similaridade nos erros de catálogo |
| WI-7.6 | Catálogos sempre paginados **e** filtráveis por substring — 345 efeitos e 468 filtros não cabem no contexto |
| WI-7.7 | Documentar explicitamente na descrição o que **não** existe: sem reordenar, sem editar segmento, sem renderizar, sem recarregar o CapCut |
| WI-7.8 | `capcut.draft.inspect` com saída compacta e legível por agente (não o JSON cru de milhares de linhas) |
| WI-7.9 | 📋 Guia de uso em uma página, entregue como descrição do servidor ou README curto |
| WI-7.10 | **Avaliação com agente**: 10 prompts em linguagem natural, executados pelo Codex sem acesso ao código-fonte |

## Teste verificável

**Avaliação comportamental** — os 10 prompts de WI-7.10, cada um julgado por: completou sem erro? quantas chamadas falhadas antes de acertar? precisou de intervenção humana?

Prompts mínimos: (1) reel 9:16 com 2 clipes; (2) trocar a ordem dos clipes; (3) legenda em PT-BR com 5 blocos; (4) título grande no começo; (5) música de fundo baixa; (6) efeito de blur nos 2 primeiros segundos; (7) transição entre os clipes; (8) zoom por keyframe; (9) PiP com imagem no canto; (10) salvar e dizer onde ficou.

**Critérios:**

1. ≥ 8 dos 10 prompts completam sem intervenção humana.
2. Zero casos em que o agente conclui sucesso enquanto o projeto está errado (**falha silenciosa = reprovação da fase**).
3. Toda chamada falhada é seguida de correção na chamada seguinte (prova de que a mensagem de erro ensina).
4. Nenhum prompt exige que o agente leia o código-fonte.
5. O agente nunca tenta uma operação inexistente duas vezes (a primeira recusa foi clara).

## Critério de conclusão

Os 5 critérios atendidos, com a transcrição das 10 execuções arquivada em `evidence/phase7/`.

---

# Phase 8 — End-to-end test

**Objetivo:** o projeto `VectCut MCP E2E Test` construído **exclusivamente** pelo Codex via MCP.
**Esforço:** S (execução) + M (correções que aparecerem)
**Entradas:** todas as fases anteriores fechadas.

## Especificação do projeto

| Parâmetro | Valor |
|---|---|
| Nome | `VectCut MCP E2E Test` |
| Formato | 1080×1920 |
| Duração | ≈ 15 s |
| Origem | somente Codex + MCP — **nenhuma chamada Python manual, nenhuma edição de JSON** |

## Fluxo (os 15 passos do escopo)

| # | Passo | Tool | Observação |
|---|---|---|---|
| 1 | criar draft | `capcut.draft.create` | |
| 2 | vídeo principal | `capcut.video.add` | `clip_b.mp4`, 0–8 s |
| 3 | cortar vídeo | `capcut.video.add` com `source_start/end` | trim na inserção |
| 4 | segundo clip | `capcut.video.add` | 8–15 s |
| 5 | música | `capcut.audio.add` | `role="background"`, 0–15 s |
| 6 | ajustar volume | parâmetro do passo 5 | 0.2 |
| 7 | headline | `capcut.text.add` | 0–3 s, tamanho calibrado na Phase 3 |
| 8 | captions | `capcut.subtitle.add` | ≥ 5 blocos em PT-BR |
| 9 | imagem | `capcut.image.add` | track separada, PiP com escala e posição |
| 10 | efeito suportado | `capcut.effect.add` | nome vindo do catálogo, não inventado |
| 11 | transição se suportada | `capcut.video.add` | entre os clipes dos passos 2 e 4 |
| 12 | keyframe se suportado | `capcut.keyframe.add` | zoom por `uniform_scale` |
| 13 | salvar | `capcut.draft.save` | `target="capcut"` |
| 14 | verificar integridade | `capcut.draft.validate` + `inspect` | antes e depois do save |
| 15 | abrir no CapCut | manual | |

## Teste verificável

**N1/N2 — automatizado:**

1. O log da sessão prova que **todas** as mutações vieram de chamadas MCP (nenhum acesso direto ao L0).
2. `validate` antes do save retorna zero issues de severidade `error`.
3. `duration` total entre 14 e 16 s.
4. Todas as tracks esperadas presentes, com a contagem de segmentos esperada.
5. Todos os `path` de material existem em disco, com tamanho > 0.
6. Nenhum segmento perdido entre o estado de `inspect` e o JSON salvo (spec D7).
7. `inspect` pós-save bate com o JSON gravado.
8. O manifest do `save` lista todos os arquivos e assets escritos.

**N3 — manual, critério final:**

| # | Verificação | PASS/FAIL |
|---|---|---|
| 1 | **O projeto abre no CapCut** sem erro e sem diálogo de reparo | |
| 2 | Aparece com o nome `VectCut MCP E2E Test` | |
| 3 | Timeline com os 2 clipes, imagem, música, headline e 5 legendas | |
| 4 | Toda a mídia carrega | |
| 5 | Efeito visível no intervalo pedido | |
| 6 | Transição presente entre os clipes (se suportada) | |
| 7 | Keyframe produz o movimento pedido (se suportado) | |
| 8 | Duração ≈ 15 s | |
| 9 | Legendas sincronizadas e com acentuação correta | |
| 10 | O projeto é editável à mão a partir daí, sem travar | |

## Critério de conclusão

**O projeto abre no CapCut**, com os 10 itens em PASS. Os itens 6 e 7 podem ser N/A se a Phase 5 os tiver marcado como não suportados — com o registro correspondente no `STATUS_MATRIX.md`.

---

## Riscos gerais e contingências

| # | Risco | Probabilidade | Impacto | Contingência |
|---|---|---|---|---|
| R1 | Nenhum perfil de draft faz o CapCut abrir o projeto | **alta** (revisada em 2026-09-14) | **fatal** | Suspender o plano. Plano B: partir do projeto de referência (WI-0.9) e injetar apenas materiais e segmentos, preservando todo o resto do arquivo do app. **Motivo da revisão:** a versão instalada é **9.4.1**, enquanto o template do upstream foi capturado de um CapCut **6.5.0** (`new_version 138.0.0`). O skill `capcut-director` afirma que CapCut 9.x+ lê `Timelines/<UUID>/draft_content.json` e que escrever só o arquivo da raiz abre timeline vazio — exatamente o que o perfil `capcut_legacy` faz. Q1 provavelmente não resolve para `capcut_legacy`. |
| R2 | CapCut atualiza e muda o formato durante o desenvolvimento | média | alto | Matriz de compatibilidade (spec C8) + probe de versão no `doctor`; travar a versão do CapCut durante o desenvolvimento. **O cask não declara `auto_updates`, mas o app pode se atualizar sozinho** — desativar atualização automática nas preferências antes da Phase 1 |
| R3 | Upstream quebra mais coisas no `main` | alta | baixo | Submodule fixo em `b83be74`; teste de contrato do L0 (spec C4) a cada atualização deliberada |
| R4 | Catálogo de efeitos/fontes majoritariamente VIP | média | médio | Expor `is_vip`; curar lista de recursos gratuitos validados |
| R5 | Timeout de tool-call do Codex em `save` grande | média | médio | Q5 → `save` assíncrono com `job_id` |
| R6 | **Espaço em disco** | **alta — já ocorreu** | médio | O disco chegou a **zero** durante esta sessão de auditoria, com o CapCut ainda nem instalado. Retenção de backup + guarda no `save` (WI-0.11, WI-6.19) + limpeza de assets órfãos. Cada `save` **copia** todos os assets. |
| R7 | Esforço da Phase 3 estoura | alta | médio | Entregar em 4 lotes com gate próprio; adiar `rebuild` (WI-3.8) para depois da Phase 4 se necessário |
| R8 | Escala de `font_size` inviabiliza tipografia previsível | baixa | médio | Tabela calibrada (WI-3.28) + presets nomeados em vez de números crus |
| R9 | Keyframes não funcionam fora de vídeo | média | baixo | Já tratado como `PARTIALLY_SUPPORTED`; restringir a vídeo |
| R10 | Sobrescrita destrói trabalho do usuário | baixa | **alto** | Phase 6 inteira; backup obrigatório antes de qualquer escrita |

---

## Rastreabilidade — fase × requisitos da spec

| Fase | Portão da spec | Requisitos cobertos | Questões fechadas |
|---|---|---|---|
| 0 | — | pré-requisitos de C7, C8 | — |
| 1 | **Portão 0** (AC0.1–0.5) | PRJ-01, 02, 03, 04 (parcial), 06 (parcial) | Q1, Q2, Q3 |
| 2 | **Portão 1** (AC1.1–1.5) | PRJ-01, 04, 06 · AC2.4, AC2.9 · O1, O2, O3 · D2, D3, D4 | Q5, Q7, Q8 |
| 3 | — | VID-01..09 · IMG-01..04 · AUD-01..05 · TXT-01..09 · MED-01 · AC2.5, AC2.10, AC2.12 | Q4 |
| 4 | — | SUB-01..04 · AC2.1 | — |
| 5 | — | FX-01..03 · KF-01..06 · stickers · AC2.2, AC2.3, AC2.6 | KF-06 |
| 6 | **Portão 2** (AC2.x) | MED-02, MED-03 · F1–F14 · E1–E7 · S2–S11 · AC2.7, AC2.8, AC2.11 | Q6 |
| 7 | **Portão 3** (AC3.x) | G3, G7 · C15, C16 · AC3.3 | — |
| 8 | **Portão 4** (AC4.x) | fluxo completo · AC3.4, AC4.x | — |

Requisitos da spec **fora deste plano**, por já estarem declarados como extensões futuras: `capcut.project.open` (mutação de projeto existente), `capcut.filter.add`, animação de loop de texto, fade de áudio, presets de alto nível.

---

## Checklist de progresso

```
[ ] Phase 0 — Environment validation      → ENVIRONMENT.md + SETUP.md + projeto de referência
      [ ] 🔴 WI-0.6  CapCut Desktop instalado
      [ ] 📋 WI-0.9  projeto de referência capturado
      [ ] 📋 WI-0.14 config MCP do Codex documentada
[ ] Phase 1 — VectCutAPI baseline         → PORTÃO 0 · Q1/Q2/Q3
      [ ] ⛔ as 5 verificações no CapCut em PASS
[ ] Phase 2 — MCP baseline                → PORTÃO 1 · Q5/Q7/Q8
      [ ] Codex cria e salva projeto que abre no CapCut
[ ] Phase 3 — Core timeline editing       → Q4
      [ ] lote vídeo   [ ] lote imagem   [ ] lote áudio   [ ] lote texto
[ ] Phase 4 — Captions                    → 5 legendas PT-BR sincronizadas
[ ] Phase 5 — Advanced editing            → 4 projetos isolados em PASS
[ ] Phase 6 — Reliability layer           → PORTÃO 2 · Q6 · backup provado
[ ] Phase 7 — Codex usability             → PORTÃO 3 · ≥8/10 prompts
[ ] Phase 8 — End-to-end test             → PORTÃO 4 · o projeto abre
```

---

## Próxima ação

**WI-0.6 — instalar o CapCut Desktop (International, macOS arm64).** É o único item bloqueante do plano inteiro: sem ele não existe oráculo, e toda verificação N3 — de todas as fases — fica impossível. Em seguida, **WI-0.9** (capturar o projeto de referência), que é o que responde as perguntas de formato que decidem a Phase 1.
