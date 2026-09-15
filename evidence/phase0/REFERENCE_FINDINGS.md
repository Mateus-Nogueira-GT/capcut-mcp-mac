# WI-0.9 — Projeto de referência do CapCut 9.4.1 (parcial)

**Data:** 2026-09-14 · **CapCut:** 9.4.1 (`com.lemon.lvoverseas`) · **macOS:** 15.7.3 arm64
**Projeto capturado:** `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/0914`
**Arquivado em:** `evidence/phase0/reference_project/`

> **Status: COMPLETO.** Duas capturas:
> - `0914` — projeto vazio (0 tracks, 0 materiais). Deu a estrutura e as versões.
> - `0914 (1)` — projeto com **1 vídeo + 2 textos na timeline e proporção 9:16**, montado via controle de tela pelo Claude. Deu o conteúdo. Ver §8.

---

## 1. Diretório de drafts — CONFIRMADO (WI-0.8)

```
~/Movies/CapCut/User Data/Projects/com.lveditor.draft/
├── root_meta_info.json          ← ÍNDICE de projetos (ver §3)
├── .recycle_bin/
└── 0914/                        ← um projeto (nome = data MMDD)
```

O container do app (`~/Library/Containers/com.lemon.lvoverseas/Data/Movies`) é **symlink** para `~/Movies`. Não há dois locais: é o mesmo lugar por dois caminhos.

O caminho que o upstream procura — `~/Library/Containers/com.lemon.lvpro/Data/Documents/JianyingPro/User Data/Projects/com.lveditor.draft` (`save_draft_impl.py:259`) — **não existe**, nem dentro do container. `com.lemon.lvpro` é o Jianying Pro chinês; este app é `com.lemon.lvoverseas`.

## 2. Estrutura de um projeto 9.4.1

```
0914/
├── draft_info.json              ← conteúdo do timeline
├── draft_info.json.bak
├── draft_meta_info.json
├── draft_settings · draft_agency_config.json · draft_biz_config.json
├── performance_opt_info.json · attachment_pc_common.json · template-2.tmp
├── timeline_layout.json
├── common_attachment/{attachment_id_mapping,attachment_pc_timeline}.json
├── Timelines/
│   ├── project.json  ·  project.json.bak
│   └── B77121E7-E744-444C-8471-1D9F4EC0F9A4/
│       ├── draft_info.json      ← IDÊNTICO ao da raiz (cmp: byte-a-byte)
│       ├── draft_info.json.bak
│       ├── template.tmp · template-2.tmp
│       ├── attachment_editing.json · attachment_pc_common.json
│       ├── attachment/patch/
│       └── common_attachment/{attachment_action_scene,attachment_gen_ai_info,
│                              attachment_id_mapping,attachment_pc_timeline,
│                              attachment_script_video}.json
├── Resources/{audioAlg,videoAlg,digitalHuman/{audio,bsinfo,video}}/
└── adjust_mask · matting · qr_upload · smart_crop · subdraft   (vazios)
```

### → Q1 RESPONDIDA: **nenhum dos dois perfis do upstream está correto**

| Perfil | Arquivo de conteúdo | `Timelines/` | Veredito |
|---|---|---|---|
| `capcut_legacy` | `draft_info.json` ✅ | ausente ❌ | nome certo, estrutura errada |
| `jianying_pro_10` | `draft_content.json` ❌ | presente ✅ | estrutura certa, nome errado |
| **CapCut 9.4.1 real** | **`draft_info.json`** | **presente** | híbrido dos dois |

**Consequência prática — e é uma boa notícia:** o `jianying_pro_10` já implementa toda a lógica necessária (espelhar o conteúdo em `Timelines/<id>/`, renomear o diretório do timeline para o `id` do conteúdo, escrever `project.json` + `project.json.bak`, atualizar `timeline_layout.json`). O que falta é trocar `content_file` de `draft_content.json` para `draft_info.json` — **uma linha** em `draft_profiles.py`. Isso reduz o risco R1 em relação à hipótese anterior de que 9.x exigiria um formato inteiramente novo.

Divergências remanescentes do `jianying_pro_10` a corrigir:

| Item | Upstream escreve | 9.4.1 real |
|---|---|---|
| `project.json` → `id` | igual a `main_timeline_id` | **diferente** (`86B9AF52-…` vs `B77121E7-…`) |
| `project.json` → `timelines[].name` | `"时间线01"` (chinês) | `"Timeline 01"` |
| `project.json` → `config` | sem `hdr_vivid`, sem `mixed_track_mode_on` | tem ambos |
| `platform` | `app_version 6.5.0`, hashes de outra máquina | `9.4.1`, hashes desta máquina |

## 3. DESCOBERTA NOVA — `root_meta_info.json`

Não consta em nenhum dos três documentos anteriores, e **o VectCutAPI não escreve nem atualiza este arquivo.**

É um índice de projetos, na raiz de `com.lveditor.draft`:

```json
{
  "all_draft_store": [ {
      "draft_name": "0914",
      "draft_id": "1BE697F1-B897-49DD-9D9E-BDC08C82333F",
      "draft_fold_path": "/Users/…/com.lveditor.draft/0914",
      "draft_root_path": "/Users/…/com.lveditor.draft",
      "draft_json_file": "/Users/…/0914/draft_info.json",
      "draft_cover":     "/Users/…/0914/draft_cover.jpg",
      "draft_timeline_materials_size": 4199,
      "tm_draft_create": 1789413440958583,
      "tm_draft_modified": 1789413452835475,
      "tm_duration": 0,
      "streaming_edit_draft_ready": true
  } ],
  "draft_ids": 1,
  "root_path": "/Users/…/com.lveditor.draft"
}
```

**Hipótese de primeira ordem:** é daqui que o CapCut monta a lista de projetos. Se for, **copiar uma pasta para `com.lveditor.draft/` não faz o projeto aparecer** — o índice precisa ser atualizado também. Isso explicaria o modo de falha "o draft não aparece no app" sem que nada no JSON do timeline esteja errado.

**A testar na Phase 1** (vira um experimento próprio, WI-1.14): gerar um projeto e (a) só copiar a pasta; (b) copiar a pasta **e** inserir a entrada no `root_meta_info.json`. Comparar.

**Impacto no plano:** o `Deployer` do L1 ganha uma responsabilidade não prevista — ler, alterar e regravar `root_meta_info.json` de forma atômica, preservando as entradas existentes. Escrita nesse arquivo afeta **todos** os projetos do usuário, o que o coloca no mesmo nível de cuidado do backup obrigatório da Phase 6.

## 4. Versões — Q2

| Fonte | `new_version` | `version` |
|---|---|---|
| **CapCut 9.4.1 (real)** | **185.0.0** | 360000 |
| `template/draft_info.json` do upstream | 138.0.0 | 360000 |
| `pyJianYingDraft/draft_content_template.json` (o que o código grava) | **110.0.0** | 360000 |

`version` bate. `new_version` está 75 versões menores atrás do real.

## 5. Schema do `draft_info.json`

| | real 9.4.1 | base que o código usa |
|---|---|---|
| chaves de topo | 36 | 27 (+ `platform` e `last_modified_platform` injetadas no `dumps()`) |
| chaves de `materials` | 55 | 45 |

**Chaves de topo que o real tem e o código não escreve:** `draft_type`, `function_assistant_info`, `is_drop_frame_timecode`, `lyrics_effects`, `mixed_track_mode_on`, `path`, `smart_ads_info`, `uneven_animation_template_info`.

**Chaves de `materials` só no real:** `ai_text_effects`, `audio_pannings`, `audio_pitch_shifts`, `common_mask`, `digital_human_model_dressing`, `hsl_curves`, `manual_beautys`, `placeholder_infos`, `video_radius`, `video_shadows`, `video_strokes`. O código escreve `masks`, que o real não tem (o real usa `common_mask`).

**Ponto favorável:** o código escreve um **subconjunto** — não há nenhuma chave inventada que o real não conheça. Um subconjunto tende a ser tolerado (o app preenche defaults); chaves desconhecidas é que costumam quebrar. A exceção a investigar é `masks` vs `common_mask`.

## 6. `draft_meta_info.json`

Mesma forma do template do upstream, com **9 chaves novas** na 9.4.1 (todas de features novas: `pippit_*`, `draft_is_infinite_canvas_draft`, `draft_is_web_article_video`, `draft_has_unfinished_aigc_video_effect`). Nenhuma chave do upstream ficou obsoleta.

O problema segue sendo o da auditoria: o upstream **copia o arquivo sem reescrever**, então todo projeto gerado carrega `draft_name: "0707"`, os paths de `/Users/sunguannan/` e o **mesmo `draft_id` UUID**. Os campos a reescrever estão agora confirmados contra um arquivo real:

`draft_name` · `draft_fold_path` · `draft_root_path` · `draft_id` (UUID v4 novo) · `tm_draft_create` · `tm_draft_modified` · `tm_duration` · `draft_timeline_materials_size_`

## 7. Outros fatos úteis

- **Nome da pasta = nome do projeto no app.** O CapCut nomeou por data (`0914`), e `draft_name` == nome da pasta. O nome que o usuário digita na criação não virou o nome da pasta. Logo, o parâmetro `name`/`project_name` do L1 **é** o nome da pasta. Dois projetos no mesmo dia colidiriam em `0914` — verificar como o app desambigua.
- **`draft_cover.jpg` é referenciado e não existe** na pasta. Cover ausente é tolerado pelo app.
- **`tm_duration: 0`** num projeto vazio.
- Diretórios `Resources/`, `adjust_mask/`, `matting/`, `qr_upload/`, `smart_crop/`, `subdraft/` são criados vazios.

---

---

# Parte 2 — captura com conteúdo (`0914 (1)`)

Projeto com 1 vídeo (12,3 s) + 2 textos na timeline, proporção 9:16. Duração total 12,8 s.

## 8. Canvas 9:16 — PRJ-03 RESPONDIDA

```json
"canvas_config": { "ratio": "9:16", "width": 1080, "height": 1920, "background": null }
```

**O rótulo que o upstream deriva está correto.** `draft_profiles.write_profile_content()` calcula `"9:16"` para qualquer resolução vertical, e para 1080×1920 isso coincide com o que o app escreve. A ressalva do PRJ-03 permanece só para proporções que o upstream rotularia errado (4:5, 2:3): o diálogo do app oferece **Original, 16:9, 4:3, 2.35:1, 2:1, 1.85:1, 9:16, 3:4, 5.8 polegadas, 1:1** — não há 4:5 nem 2:3, então o upstream nunca deveria emitir um rótulo fora dessa lista.

Projeto sem proporção definida fica `ratio: "original"` com 1920×1080 — é o default.

## 9. Gravação em disco — "Voltar à página inicial" é suficiente

O menu **CapCut → Voltar à página inicial** gravou o projeto completo em disco (vídeo, textos, canvas 9:16), exibindo "Salvo no projeto". **Não é necessário encerrar o app.**

Isso muda a instrução operacional do fluxo: em vez de "feche o CapCut por completo", basta **voltar à tela inicial**. Note que o inverso continua valendo — enquanto o projeto está aberto no editor, o disco fica atrás do estado em memória (observado duas vezes nesta sessão).

## 10. Mídia NÃO é copiada para dentro do projeto

O material de vídeo aponta para o **local original**:

```json
"path": "/Users/…/Downloads/lupo-minerais-anuncio.mp4"
```

O diálogo *Configurações do projeto* tem a opção **Mídia importada**, com dois rádios: `Copiar mídia para o projeto` e `Manter no local original` — e o **default é manter no local original**.

**Consequência para a spec:** a regra F2 ("salvar direto no diretório do CapCut para que os caminhos fiquem autocontidos") pode ser relaxada. O CapCut aceita mídia em qualquer lugar do disco, desde que o `path` absoluto esteja correto. A cópia de assets que o VectCutAPI faz é **opcional**, não requisito — e evitá-la economiza disco (ver R6) e tempo de `save`. O que continua obrigatório é o `path` absoluto estar válido no momento da abertura.

## 11. Material de vídeo real vs. o que o upstream escreve

| | campos |
|---|---|
| material real da 9.4.1 | **68** |
| escritos pelo `Video_material` do upstream | **18** |
| em comum | 17 |

**Único campo que o upstream escreve e o real não tem: `remote_url`** — invenção do projeto para rastrear a origem. Junto com `masks` (o real usa `common_mask`), são os dois únicos candidatos a "chave desconhecida" em todo o arquivo.

51 campos do real que o upstream não escreve, entre eles os que parecem estruturalmente relevantes: `has_audio`, `has_sound_separated`, `crop`, `crop_ratio`, `crop_scale`, `source`, `source_platform`, `matting`, `stable`, `video_algorithm`, `extra_type_option`, `object_locked`, `local_id`, `unique_id`, `origin_material_id`. Os demais são de features novas (beauty, aigc, live photo, multi-camera, workflow).

Valores de referência do real:

```
type="video"  crop_ratio="free"  crop_scale=1.0  has_audio=true  category_name="local"
aigc_type="none"  media_path=""  reverse_path=""  intensifies_path=""
id (UUID maiúsculo)   local_material_id (UUID minúsculo)
crop = {upper_left_x:0, upper_left_y:0, upper_right_x:1, upper_right_y:0,
        lower_left_x:0, lower_left_y:1, lower_right_x:1, lower_right_y:1}
```

**A Phase 1 decide** se 17 campos bastam. Se o projeto abrir sem material faltando, bastam; se não, esta lista é o próximo lugar a olhar.

## 12. Segmento e track reais

```
segmento de vídeo: target_timerange={start:500000, duration:12300000}
                   source_timerange={start:0, duration:12300000}
                   speed=1.0  volume=1.0  render_index=1  visible=true
                   clip={scale:{x,y}, rotation, transform:{x,y}, flip:{v,h}, alpha}
```

| Achado | Implicação |
|---|---|
| `render_index`: **1** para vídeo, **14000/14001** para texto | O upstream usa `Track_type.value.render_index + relative_index`; conferir se a base de vídeo é compatível |
| `target_timerange.start = 500000` | **O vídeo não começa em 0.** Contradiz o docstring do upstream (`script_file.py:250-252`) de que a track de vídeo base é forçada a 0. Ou a regra não vale na 9.4.1, ou esta não é a track base |
| Tracks com `name: ""` | O CapCut real não nomeia tracks; o upstream nomeia (`main`, `text_main`). Não impediu nada aqui, mas é divergência |
| **4 tracks, sendo 1 de vídeo VAZIA** | O projeto real do próprio CapCut também tem track de vídeo sem segmentos. Logo, a "track vazia espúria" que o `add_video_track` do upstream cria **não é anomalia** — deixa de ser item de correção (era AC2.10 no plano) |
| Um texto por track | O CapCut criou duas tracks de texto para dois textos, em vez de dois segmentos numa track |

## 13. Diálogo *Configurações do projeto* — o que é configurável

Nome · Salvar em · **Mídia importada** (copiar vs. manter) · Espaço de cores (Rec. 709 SDR) · Organizar camadas · Aplicar a (timeline) · **Proporção de aspecto** · **Resolução** (Adaptado) · **Taxa de quadros** (30.00 fps).

`fps` no JSON saiu `30.0` — confere com o default do upstream.
