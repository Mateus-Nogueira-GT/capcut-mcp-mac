# Phase 1 — VectCutAPI baseline · RESULTADO: **PORTÃO 0 PASSOU**

**Data:** 2026-09-14 · **CapCut:** 9.4.1 · **Python:** 3.12.13 · **Upstream:** `b83be74` (intocado)
**Harness:** `phase1/baseline_build.py` (teste, não produto) · **Evidência:** este arquivo

---

## Veredito

| Variante | Perfil | `Timelines/` | Registrado no índice | Aparece na lista | **Abre no CapCut** |
|---|---|---|---|---|---|
| **A** | `capcut_legacy` do upstream, sem mudanças | ausente | sim | sim, 00:08, 7.6M | ❌ **NÃO ABRE** |
| **B** | híbrido (template = projeto real + `content_file=draft_info.json`) | presente | sim | sim, 00:08 | ✅ **ABRE** |
| **C** | híbrido, **sem** registrar no índice | presente | **não** | sim, 00:08 | ✅ **ABRE** |

A recusa de A é **silenciosa**: duplo clique e Enter não fazem nada, sem diálogo de erro, mesmo com 10 s de espera. O menu de contexto da miniatura só oferece Carregar / Renomear / Duplicar / Excluir — não existe "abrir", então o duplo clique é o único caminho e ele falha.

### As 5 verificações do escopo (variantes B e C)

| # | Verificação | Resultado |
|---|---|---|
| 1 | O draft aparece no CapCut | ✅ com o nome correto, duração 00:08 |
| 2 | O CapCut abre o projeto | ✅ sem erro, sem diálogo de reparo |
| 3 | A timeline não está corrompida | ✅ 4 elementos, tracks corretas |
| 4 | Os arquivos de mídia aparecem | ✅ miniaturas de vídeo/imagem renderizam, áudio com forma de onda |
| 5 | Os tempos estão corretos | ✅ vídeo 0–5 s · imagem 5–8 s · áudio 0–8 s · texto 0–3 s · total `00:00:08:00` |

Depois de abrir e salvar, o CapCut **regravou o projeto por conta própria** (tamanho caiu de 7.6M para 489.7K) e gerou miniatura real — adoção completa, não tolerância parcial.

---

## Q1 — RESPONDIDA em definitivo

**A estrutura `Timelines/<UUID>/draft_info.json` é OBRIGATÓRIA no CapCut 9.4.1.** O perfil `capcut_legacy`, que grava apenas o `draft_info.json` da raiz, produz um projeto que o app **lista mas se recusa a abrir**.

O skill `capcut-director` do repositório estava **certo** sobre a arquitetura multi-timeline do 9.x e **errado** sobre o nome do arquivo (ele afirma `draft_content.json`).

### A correção é de uma linha

O perfil `jianying_pro_10` já implementa toda a mecânica necessária. O que muda:

```python
# draft_profiles.py — perfil novo, sem alterar os existentes
"capcut_94": DraftProfile(
    name="capcut_94",
    template_dir="<projeto de referência real da instalação>",
    content_file="draft_info.json",          # <<< jianying_pro_10 usa draft_content.json
    content_mirrors=("draft_info.json.bak", "template-2.tmp"),
    timeline_content_file="template.tmp",
    is_capcut_env=True,
    platform=<platform lido da instalação>,
),
```

Verificado que `write_profile_content()` faz o resto corretamente: renomeia `Timelines/<uuid>` para o `id` do conteúdo (conferido: `id` do JSON == nome do diretório), espelha o conteúdo byte-a-byte na raiz e no timeline, e regrava `project.json` / `timeline_layout.json`.

## Q-índice — RESPONDIDA: não precisa tocar no `root_meta_info.json`

**O CapCut mantém o índice sozinho, varrendo o diretório.** Prova: a variante C nunca foi registrada por mim e apareceu na lista igualmente; e o app **sobrescreveu** minhas entradas de B e C com `draft_id`s próprios (diferentes dos que gravei nos metadados) e seu próprio `draft_timeline_materials_size`.

**Impacto:** a responsabilidade mais arriscada que a Phase 0 havia identificado para o `Deployer` do L1 — escrever num arquivo compartilhado por todos os projetos do usuário — **desaparece**. Também cai a interpretação de `draft_ids` como contagem (é contador próprio do app).

## Q2 / Q3 — aplicadas e validadas

- `new_version` reescrito para **185.0.0** (real da instalação) em vez de 110.0.0. Projeto abriu.
- `platform` com `app_version 9.4.1` e os hashes de máquina **reais** desta instalação, lidos do projeto de referência.
- Não testei isoladamente se 110.0.0 também abriria — Q2 fica **respondida na prática** (185.0.0 funciona) e **não isolada** (não se sabe se era necessário).

## Q4 — validada visualmente

`font_size = 15.0` (valor medido na 9.4.1) renderizou o texto "Baseline" em proporção adequada num quadro 1080×1920. O default 8.0 do upstream produziria algo em torno da metade.

---

## Achado novo: renomear a pasta do projeto quebra a mídia

Primeira tentativa de B falhou com **3/3 assets ausentes**. Causa: o L0 nomeia a pasta de saída com o `draft_id` e grava nos materiais o **caminho absoluto** apontando para ela (`<draft_folder>/<draft_id>/assets/...`). Renomear a pasta depois — que é o que `project_name` sugere fazer — invalida todos os caminhos. O parâmetro `project_name` do upstream só afeta a cópia de auto-deploy, nunca os caminhos.

**Solução aplicada no harness** (e que o L1 deve adotar): re-chavear o `DRAFT_CACHE` para o nome final **antes** de salvar, de modo que a pasta nasça com o nome definitivo e os caminhos saiam corretos:

```python
update_cache(PROJECT_NAME, script)
save_draft_impl(PROJECT_NAME, draft_folder=CAPCUT_DIR, auto_deploy=False)
```

Isto é mais simples do que reescrever caminhos depois, e confirma que o `draft_id` do upstream é só uma chave de dicionário e nome de pasta — pode ser o nome do projeto.

## Confirmação de achado da Phase 0

Os assets **foram** copiados para `<projeto>/assets/` pelo L0 e funcionaram. Combinado com o achado de que o CapCut por padrão referencia mídia no local original, ficam **as duas formas válidas**: copiar para dentro do projeto (o que o L0 faz) ou apontar para o original. A cópia continua sendo escolha, não requisito.

---

## Conteúdo gerado (variantes B e C)

```
canvas_config : {"ratio":"9:16","width":1080,"height":1920}
new_version   : 185.0.0          duration: 8000000 µs          fps: 30
tracks        : video ''          (vazia — igual ao projeto real do app)
                video 'main'      seg 0–5 s   (video_teste.mp4, source 0–5 de 6 s)
                video 'main'      seg 5–8 s   (pic.png)
                audio 'audio_main' seg 0–8 s  (tone.mp3, volume 0.3)
                text  'text_main'  seg 0–3 s  ("Baseline", font_size 15.0)
Timelines/91E08AC5-…/draft_info.json  ==  draft_info.json da raiz  (byte-a-byte)
assets/{video,image,audio}/  — 3/3 presentes e válidos
draft_meta_info.json — reescrito: nome, paths, UUID novo, timestamps, tm_duration
```

## Pendências desta fase

| Item | Situação |
|---|---|
| WI-1.7 (isolar Q2: 110.0.0 vs 185.0.0 vs omitido) | não executado — 185.0.0 funciona; saber se era necessário é otimização |
| WI-1.8 (isolar Q3: hashes do upstream vs reais) | não executado — mesma razão |
| WI-1.9 (isolar: `draft_meta_info` copiado vs reescrito) | não executado — reescrito funciona |
| WI-1.13 (snapshot de referência do JSON) | a fazer, para detectar regressão nas fases seguintes |

Essas três variantes isoladas dizem **o que é estritamente necessário** versus o que é apenas suficiente. Valem uma rodada antes da Phase 3, para não carregar correções desnecessárias no L1. Não bloqueiam a Phase 2.

## Limpeza

Os projetos `VectCut Baseline A/B/C` continuam no diretório do CapCut, para inspeção. `phase1/backup/root_meta_info.json.orig` tem o índice original, embora o app já o tenha regravado por conta própria.
