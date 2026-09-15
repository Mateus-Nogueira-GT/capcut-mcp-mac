# Phase 4 — Captions · RESULTADO: **verificado em N1+N2+N3**

**Data:** 2026-09-14 · **L1:** `capcut-mcp-mac` @ `6c78894` · **Testes:** 116 (39 de legenda)

## Verificação visual (N3) — 2026-09-14, 20:31–20:34

`P4 Captions` abriu no CapCut 9.4.1 com 16,0 s. Checklist do escopo:

| Verificação | Resultado |
|---|---|
| 5 legendas aparecem sincronizadas | ✅ conferidas nos instantes 1 s, 3 s, 5 s e 7 s |
| sem sobreposição visual | ✅ |
| ordem sequencial | ✅ |
| **acentuação renderiza** | ✅ "Ação e coração" com cedilha e os dois tis; "Pão, ótimo, çãõ — travessão" com o travessão intacto |
| **quebra de linha aparece como duas linhas** | ✅ "Duas linhas de verdade / segunda linha aqui" — **fecha a pendência da Phase 3** |
| emoji renderiza | ✅ 🎬 aparece, com as reticências … e as aspas |
| preset `outline` dá contraste | ✅ borda escura visível em volta dos glifos brancos |
| preset `boxed` mostra a caixa | ✅ cápsula arredondada semitransparente |
| legendas no rodapé, dentro da safe zone | ✅ |

### ❌ Falha encontrada e corrigida: quebra no meio da palavra

A legenda `Emoji 🎬 e "aspas" … reticências` (31 caracteres) renderizou como
`Emoji 🎬 e "aspas" … reticê` / `ncias` — **o CapCut quebra por caractere, não por
palavra**, com `fixed_width=0.6` (valor que o `import_srt` do upstream usa e que eu
havia reproduzido).

**Correção aplicada** (`6c78894`): o L1 quebra o texto em limite de palavra antes de
entregá-lo, usando quebras reais — que esta mesma inspeção provou que renderizam como
duas linhas. `chars_per_line()` escala com `font_size` e `fixed_width`;
`max_chars_per_line` permite ajuste; `SUBTITLE_WRAPPED` avisa quando acontece; palavra
isolada maior que o limite nunca é partida.

Reconstruído e conferido: `reticências` agora fica íntegra na segunda linha.

**Honestidade sobre o limite:** medi dois pontos — 27 caracteres couberam em uma linha,
31 quebraram. O limite real está entre 28 e 30, e contagem de caracteres é aproximação
(o emoji ocupa o dobro da largura, `…` ocupa menos). Ficamos em **26**, conservador de
propósito: uma quebra extra é cosmética, palavra partida é defeito visível. O efeito
colateral é que `Pão, ótimo, çãõ — travessão` (27 caracteres), que cabia numa linha,
agora quebra em duas.

---

## Resultado original (N1+N2)

---

## Decisão de desenho: o `import_srt` do upstream não é usado

`Script_file.import_srt()` tem um bug estrutural: `font_type` só é atribuído dentro de
`if font:` (`script_file.py:503-505`) mas é lido na closure em `:547` e `:552`. Com
`font=None` — que é o default do schema MCP do upstream — levanta
`NameError: cannot access free variable 'font_type'`. E a track de legenda é criada
**antes** da exceção, deixando uma track órfã no draft.

Em vez de contornar o bug, o L1 **parseia o SRT e cria um segmento de texto por bloco**
via `add_text_impl` — o caminho já verificado visualmente na Phase 3, onde a acentuação
PT-BR e o multi-estilo foram confirmados no CapCut.

**Consequência para o plano:** o critério AC "sem `font` → `MISSING_FONT`" deixa de ser
necessário. A intenção dele era garantir que o `NameError` nunca ocorra; aqui isso é
garantido **estruturalmente**, porque o código que contém o bug não é chamado. `font`
volta a ser opcional e, omitido, usa a fonte padrão do CapCut — que a Phase 3 confirmou
renderizar acentuação portuguesa corretamente. Um parâmetro obrigatório a menos e uma
ida ao catálogo a menos por legenda.

`MISSING_FONT` continua existindo como rede de segurança na tradução de erros.

O que se perde do `import_srt`: ele define `fixed_width` conforme a orientação
(0.6 retrato / 0.7 paisagem). Reproduzido explicitamente.

---

## Cobertura do escopo

| Item pedido | Status | Teste |
|---|---|---|
| criação manual | ✅ | `sub04` — parâmetro `segments` com `[{start, end, text}]` |
| múltiplos segmentos | ✅ | `sub01` — **5 legendas consecutivas**, o mínimo exigido |
| timestamps | ✅ | `sub02` — os cinco timeranges exatos em µs |
| início/fim | ✅ | `sub01`, `sub08` |
| caracteres especiais | ✅ | `sub18` — emoji 🎬, reticências …, aspas |
| português | ✅ | `sub17` — Ação, coração, pão, ótimo, çãõ, travessão |
| quebra de linha | ✅ | `sub19`, `sub20` — quebra **real** no campo de texto |
| posição | ✅ | `sub24` — `transform_x/y`, default −0.8 (rodapé) |
| fonte | ✅ | `sub24` — resolvida pelo catálogo; omitir usa a padrão do app |
| tamanho | ✅ | `sub24` — default 8.0 ≈ 31 px num canvas 1080×1920 |
| cor | ✅ | `sub24` |
| outline | ✅ | `sub21` — preset default liga borda |
| background | ✅ | `sub22` — preset `boxed` |
| estilo reutilizável | ✅ | `sub28` — presets nomeados, mesmo estilo entre projetos |

### Verificações extras que o escopo pedia no fim

| Verificação | Status |
|---|---|
| sincronização | ✅ `sub02` — timeranges conferidos em µs |
| sobreposição | ✅ `sub03` (nenhuma) e `sub10` (SRT sobreposto é recusado) |
| ordem | ✅ `sub02`, `sub05` (segments fora de ordem são ordenados) |
| renderização no CapCut | ⏳ **pendente** — ver abaixo |

---

## Robustez do parser

| Caso | Comportamento |
|---|---|
| índice numérico ausente | aceito |
| `.` no lugar de `,` nos milissegundos | aceito |
| CRLF e BOM | aceitos |
| linhas em branco extras | aceitas |
| timestamp malformado | `SRT_PARSE_ERROR` **com número de linha**, apontando a linha do timestamp e não a do índice |
| bloco com timestamp e sem texto | `SRT_PARSE_ERROR` |
| arquivo inexistente | `SRT_NOT_FOUND` |
| arquivo não-UTF-8 | `SRT_PARSE_ERROR` com instrução de conversão |
| URL inacessível | `SRT_FETCH_FAILED` (marcado como `retryable`) |
| `offset` que gera tempo negativo | `INVALID_TIMERANGE` com o bloco e a linha |
| `srt` e `segments` juntos, ou nenhum | `MISSING_REQUIRED_PARAM` |

**Atomicidade (`sub25`, `sub29`):** todo o conteúdo é validado antes da primeira
mutação. Um SRT malformado, ou uma fonte inválida, **não deixa track órfã** — o que era
exatamente o efeito colateral do `import_srt` do upstream.

---

## Projeto pronto para inspeção: `P4 Captions`

16,0 s · 5 tracks · 13 segmentos · estrutura de timeline conferida.

| Trecho | Conteúdo |
|---|---|
| 0–10 s | **5 legendas consecutivas**, preset `outline`, sobre vídeo: "Ação e coração" · "Duas linhas de verdade / segunda linha aqui" · "Pão, ótimo, çãõ — travessão" · "Emoji 🎬 e \"aspas\" … reticências" · "Quinta e última legenda" |
| 10–16 s | 3 legendas, preset `boxed`, em track própria, para comparar estilo |
| topo | rótulos de seção |

### Confirmado no JSON gravado

```
3 tracks de texto: 5 legendas + 3 legendas + 2 rótulos
todas as 8 legendas com size 8.0 e borda
2 blocos com quebra de linha REAL (\n no campo de texto)
caracteres íntegros: Ação · coração · Pão · ótimo · çãõ · — · 🎬 · …
```

### Checklist N3 — pendente

A aprovação de controle de tela expirou sem resposta (terceira vez nesta sessão).

- [ ] As 5 legendas aparecem uma a uma, sincronizadas com 0–2, 2–4, 4–6, 6–8, 8–10 s
- [ ] Nenhuma sobreposição visual entre legendas consecutivas
- [ ] A ordem é sequencial
- [ ] **Acentuação renderiza sem caractere quebrado** (Ação, çãõ, travessão)
- [ ] **A quebra de linha aparece como duas linhas na tela** — fecha a pendência da Phase 3
- [ ] O emoji 🎬 renderiza (ou degrada de forma aceitável)
- [ ] O preset `outline` dá contraste legível sobre o vídeo
- [ ] O preset `boxed` mostra a caixa semitransparente
- [ ] As legendas ficam no rodapé, dentro da safe zone

Até isso, as legendas ficam **verificadas em N1+N2**. Pela regra P3 do plano, não sobem
para `SUPPORTED` no `STATUS_MATRIX.md` sem a inspeção visual.

---

## Limitações registradas

| Limitação | Natureza |
|---|---|
| Estilo é uniforme para todas as legendas de uma track | `import_srt` também era assim; estilo por bloco exigiria uma tool de texto por legenda |
| Sem karaokê / realce palavra a palavra | fora de escopo declarado na spec |
| `time_offset` é o único controle temporal | não há re-timing por bloco; ajustar um bloco exige reimportar (ou usar `segments`) |
| Duas importações na mesma track são recusadas | `SEGMENT_OVERLAP`; use `track` diferente para uma segunda faixa (ex.: outro idioma) |
| Só SRT | sem VTT, ASS ou JSON de transcrição. O parâmetro `segments` cobre qualquer formato que o agente saiba converter |
| Sem ASR | não há geração automática de legenda a partir do áudio |
