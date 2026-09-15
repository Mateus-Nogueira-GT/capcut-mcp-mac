# Phase 3 — Core timeline editing · RESULTADO: **verificado em N1+N2+N3**, com 1 falha e 4 itens inconclusivos

## Verificação visual (N3) — 2026-09-14, 20:13–20:16

Os quatro lotes foram abertos no CapCut 9.4.1. Todos **abrem**, com as durações exatas
(17 s, 12 s, 10 s, 18 s) e todos os rótulos batendo com o que aparece na tela. Depois de
abertos, o CapCut regravou os quatro e gerou miniaturas próprias — adoção completa.

### Confirmado visualmente

| Operação | Evidência |
|---|---|
| 5 clipes em sequência | os cinco na track, cada um sob seu rótulo |
| **`speed` 2.0** | o CapCut exibe o badge **"Velocidade 2.0X"** no terceiro clipe — leu e aplicou |
| trim de origem | clipe 2 mostra conteúdo a partir do segundo 2 da mídia |
| **PiP entre tracks** | miniatura reduzida sobre o vídeo principal, no canto superior direito |
| **eixo Y positivo = para CIMA** | `transform_y=0.55` colocou o PiP em cima; `transform_y=-0.6` colocou a imagem embaixo. Confirma a unidade documentada |
| eixo X: negativo = esquerda | `transform_x=-0.5` → canto esquerdo; `+0.6` → canto direito |
| `mask="Circle"` em vídeo | recorte elíptico visível, cantos preenchidos de preto |
| `mask="Circle"` em imagem | PiP recortado em elipse sobre o vídeo |
| `scale` em imagem | 0.4 e 0.3 visivelmente reduzidos |
| 3 tracks de áudio | rótulos e duas tracks com forma de onda (música 0–10 s, voz a partir de 2 s) |
| **multi-estilo por faixa** | "VERDE" verde, "azul" azul, "VERMELHO" vermelho e negrito — exatamente as três faixas |
| fundo + borda + sombra | cápsula arredondada com o raio pedido, borda e sombra visíveis |
| **acentuação PT-BR** | "Ação, coração — ótimo! ção" com todos os diacríticos e o travessão intactos |
| **calibração de `font_size`** | seis tamanhos simultâneos, ver tabela abaixo |

### ❌ Falha: `transition` não é aplicada

`transition="Mix"` entra em `materials.transitions` e o segmento a referencia, mas o
CapCut **não a aplica**: não há ícone de transição em nenhuma junção da track, e em
14,0 s e 14,2 s o quadro mostra o clipe seguinte puro, sem mistura.

**Hipótese** (não testada): no modelo do CapCut a transição pertence ao clipe que
**precede** o corte, e/ou exige que os clipes se sobreponham pela duração da transição.
O upstream a anexa ao segmento que está sendo adicionado — isto é, ao que vem **depois**
do corte (`add_video_track.py:158-175` chama `video_segment.add_transition`).

**Consequência:** `transition` passa a `PARTIALLY_SUPPORTED` — aceita, validada contra o
catálogo, gravada no JSON, mas **sem efeito visível**. A tool não deve prometer o que não
entrega; a descrição precisa dizer isso até a hipótese ser testada.

### ⚠️ Inconclusivos

| Item | Por quê |
|---|---|
| `background_blur` | o clipe usado preenche o quadro inteiro, então não há fundo para desfocar. Precisa de um clipe menor que o canvas |
| fade in/out de imagem | um quadro estático não mostra transição de opacidade; exige comparar dois instantes |
| animação `Typewriter` em texto | idem — em 13,5 s o texto já estava completo |
| **quebra de linha em texto** | **bug no meu dado de teste**: escrevi `"\\n"` no script do lote, então o CapCut exibiu `\n` literal. O L1 passa o texto verbatim, então uma quebra real deve funcionar — mas **não foi verificado** |
| fonte `Amigate` | o texto renderiza, mas os glifos parecem a fonte padrão. Não é possível confirmar se a face foi aplicada ou se houve fallback sem uma fonte de aparência inconfundível |

### Tabela de `font_size` — Q4 FECHADA com medição real

Seis tamanhos renderizados simultaneamente num canvas 1080×1920, medidos por pixel na
captura (altura de caixa alta, convertida para a escala do canvas):

| `font_size` | altura aprox. no canvas | leitura prática |
|---|---|---|
| 5.0 | ~18 px | micro-label; ilegível em tela de celular |
| 8.0 | ~31 px | legenda |
| 10.0 | ~40 px | subtítulo |
| 12.0 | ~48 px | subtítulo grande |
| **15.0** | ~59 px | **título — é o default do app** |
| 20.0 | ~79 px | título hero |

Relação aproximada: **~3,9 px de altura por unidade de `font_size`**. Medição por
leitura de pixel numa captura escalada, portanto aproximada — serve para escolher
tamanho, não para cálculo tipográfico exato.

Isso corrige a tabela não verificada do skill `capcut-director`, que sugeria 9,0–12,0
para título: na prática 12,0 é subtítulo e o título confortável é 15,0.

---

## Resultado original (N1+N2)

**Data:** 2026-09-14 · **L1:** `capcut-mcp-mac` @ `d34304d` · **L0:** `b83be74`, intocado
**Testes:** 77 passando (59 de operação + 18 de contrato)

---

## Cobertura das operações pedidas

### Vídeo — 13 de 13

| Operação | Status | Teste | Nota |
|---|---|---|---|
| adicionar vídeo | ✅ | `test_vid01` | |
| adicionar múltiplos vídeos | ✅ | `test_vid02` | 3 clipes em sequência, offsets corretos |
| **3 clipes sem duração explícita** | ✅ | `test_vid02b` | **regressão da auditoria**: antes viravam 1; agora os 3 sobrevivem |
| definir início na timeline | ✅ | `test_vid03` | omitir `timeline_start` anexa ao fim da track |
| definir duração | ✅ | `test_vid04` | |
| trim (source_start/source_end) | ✅ | `test_vid05` | |
| cortar em dois segmentos | ✅ | `test_vid06` | contíguos, sem gap |
| reorganizar clips | ✅ via `draft.rebuild` | `test_rebuild_reordena` | ver Desvio 1 |
| múltiplas tracks | ✅ | `test_vid09` | |
| overlapping (PiP entre tracks) | ✅ | `test_vid09` | mesma track = `SEGMENT_OVERLAP` (`test_vid08`) |
| volume | ✅ | `test_vid10` | faixa 0–2 validada |
| posição | ✅ | `test_vid11` | |
| escala | ✅ | `test_vid11` | |

Extras cobertos: `speed` (altera duração na timeline), máscara, blur de fundo, transição com resolução case-insensitive e erro com sugestões.

### Imagem — 5 de 5
`test_img01..07`: adicionar, duração (default 3 s), posição temporal, escala, posição visual, animações intro/outro/combo, máscara, PiP.

### Áudio — 7 de 7
`test_aud01..08`: música (volume default 0.25), voice-over (track própria, 1.0), sfx, volume explícito, trim, posição, múltiplas tracks simultâneas. Imagem como áudio é recusada.

### Texto — 9 de 9
`test_txt01..11`: conteúdo, início/fim, posição, tamanho, estilo (negrito/itálico/sublinhado/alinhamento/espaçamento), cor, borda, fundo, sombra, multi-estilo por faixa, animações, fontes do catálogo, acentuação PT-BR.

### Transversais
`media.probe` em lote com falha parcial · catálogos paginados e filtráveis · `draft.inspect` com lacunas · `draft.rebuild` · nenhuma tool cria draft implicitamente · nomes de track consistentes · plano declarativo registra cada passo.

---

## Bug novo encontrado no upstream

**O texto multi-estilo do `mcp_server.py` do upstream sempre falha.**

`convert_text_styles` (`mcp_server.py:278-286`) chama:

```python
TextStyleRange(start=..., end=..., font_size=..., font_color=...,
               bold=..., italic=..., underline=...)
```

A assinatura real é `TextStyleRange(start, end, style: Text_style, border=None, font_str=None)` (`text_segment.py:262`). Nenhum daqueles kwargs existe → `TypeError`. É o **terceiro** tool MCP quebrado do upstream, junto de `add_effect` (falta `effect_category`, `params=None` explode) e `add_subtitle` (`NameError: font_type`) — e justamente o recurso que o README dele destaca como exemplo avançado.

O L1 monta o `Text_style` corretamente e o teste `test_txt08` cobre.

## Risco de formato encerrado

A única chave "desconhecida" que a Phase 0 havia sinalizado — `masks` (gerado) vs
`common_mask` (real) — era **falso alarme**. A análise estática anterior olhou o
template-base `draft_content_template.json`; o `Script_material.export_json()` emite
`common_mask`, igual ao real. Conferido no JSON gerado:

```
chaves de materials que o gerado tem e o real não tem: []
```

Resta apenas `remote_url` nos materiais de vídeo (campo próprio do upstream, ausente no
real) — e os projetos abrem, então o CapCut o tolera.

## Q4 — calibração de `font_size` preparada

O projeto `P3 Text` exibe **seis tamanhos simultâneos** (5, 8, 10, 12, 15, 20) em
alturas distintas, entre 0 e 5 s. Confirmado que cada valor chega intacto ao JSON.
A leitura da tabela definitiva depende da inspeção visual (abaixo).

Default adotado: **15.0**, medido num texto criado à mão no CapCut 9.4.1 — contra 8.0 do
impl do upstream e 24/48 da documentação dele. Fora da faixa 3–20 o L1 emite
`TEXT_SIZE_SUSPECT`.

---

## Desvios, com justificativa

**1 — "reorganizar clips" é entregue por `capcut.draft.rebuild`, não por uma tool de reordenação.**
Não existe API de remover ou mover segmento em nenhuma camada do upstream (inventário
completo de `Script_file`/`Track` conferido na auditoria). O L1 guarda o plano
declarativo de cada draft e o `rebuild` recria tudo na ordem pedida, recalculando os
tempos em cadeia. Nenhuma tool `reorder` é exposta, para não prometer o que não há.

**2 — a verificação visual foi agrupada em quatro projetos-lote, não uma por operação.**
O plano pedia abrir o CapCut por operação (~30 aberturas). Cada operação recebeu um
**rótulo de texto na própria timeline**, então um problema visual continua atribuível à
operação que o causou — que era o objetivo da regra. Quatro aberturas em vez de trinta.

**3 — `fade_in`/`fade_out` de áudio não entraram.**
`Audio_fade` existe na biblioteca e `Audio_segment.add_fade()` também, mas
`add_audio_track` não expõe parâmetro. Pedi-los devolve aviso
`OPERATION_NOT_SUPPORTED` em vez de silêncio. Fica para v1.1 (o L1 opera in-process e
pode chamar `add_fade` direto no segmento).

---

## Projetos-lote prontos para inspeção visual

Construídos e verificados estruturalmente; **aguardando abertura no CapCut**.

| Projeto | Duração | Tracks | Segmentos | O que verificar |
|---|---|---|---|---|
| `P3 Video` | 17,0 s | 5 | 12 | 5 clipes rotulados em sequência + PiP 0–6 s no canto; speed 2x reduziu 6 s de origem para 3 s; máscara circular em 11–14 s; transição e blur em 14–17 s |
| `P3 Image` | 12,0 s | 5 | 10 | imagem cheia, escala 0.4 no canto, fade in/out, PiP circular |
| `P3 Audio` | 10,0 s | 6 | 8 | três tracks de áudio: música 0–10 s (0.25), voz 2–7 s (1.0), sfx 8–9 s (1.5) |
| `P3 Text` | 18,0 s | 10 | 16 | **calibração**: seis tamanhos simultâneos 0–5 s; multi-estilo tricolor 6–9 s; fundo/borda/sombra 9–12 s; acentos + Typewriter 12–15 s; fonte Amigate 15–18 s |

### Checklist de verificação (N3) — pendente

Para cada projeto: abre sem erro · timeline com a contagem esperada de segmentos ·
mídia carrega · rótulos batem com o que se vê · tempos conferem.

Específicos:

- [ ] `P3 Video`: o PiP aparece no canto superior direito, em cima do vídeo principal?
- [ ] `P3 Video`: a máscara circular recorta de fato o clipe de 11–14 s?
- [ ] `P3 Video`: a transição em 14 s é visível?
- [ ] `P3 Image`: o fade in/out da imagem de 6–9 s acontece?
- [ ] `P3 Audio`: as três tracks de áudio aparecem separadas, com as durações certas?
- [ ] `P3 Text`: **anotar qual tamanho corresponde a título, subtítulo e legenda** — fecha Q4
- [ ] `P3 Text`: as três cores do multi-estilo aparecem nas palavras certas?
- [ ] `P3 Text`: a acentuação renderiza sem caractere quebrado?

Até isso acontecer, as operações ficam como **verificadas em N1+N2**, não em N3. Pela
regra P3 do plano, elas não sobem para `SUPPORTED` no `STATUS_MATRIX.md` sem a inspeção
visual — o JSON estar correto não prova que o app renderiza como se espera.
