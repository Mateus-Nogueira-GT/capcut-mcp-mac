# SPEC — Transcrição (ASR) e Seleção de cortes

**Versão:** 0.1 · **Data:** 2026-09-14 · **Status:** especificação para revisão — nada implementado
**Base:** `capcut-mcp-mac` @ `c1e0108` (9 tools expostas, 140 testes)
**Origem:** as duas primeiras lacunas de [`OPUS_CLIP_GAP.md`](OPUS_CLIP_GAP.md)

---

## Goals

| # | Objetivo | Critério |
|---|---|---|
| G1 | Deixar de exigir que alguém entregue o SRT | `capcut.media.transcribe(source)` devolve `segments` que o `capcut.subtitle.add` consome sem transformação |
| G2 | Permitir que o agente escolha os cortes a partir do que foi dito | O agente lê um transcript com timestamps e chama `capcut.video.cut` com os trechos escolhidos |
| G3 | Cortes que não partem palavras | Ponto de corte encostado na fronteira de fala mais próxima, com o deslocamento reportado |
| G4 | Legendas sincronizadas **depois** do corte | Tempos remapeados da mídia original para a timeline cortada, automaticamente |
| G5 | Não estourar o contexto do agente | Transcript entregue em forma compacta e paginável; palavra por palavra só quando pedido |
| G6 | Não inflar as dependências do L1 | Hoje são 6 pacotes Python. A meta é continuar 6. |

## Non-Goals

| # | Fora de escopo | Por quê |
|---|---|---|
| N1 | Legenda cinética (palavra destacada) | Depende de `words[]`, que esta spec entrega, mas é trabalho separado |
| N2 | Pontuação de viralidade | Não replicável de forma honesta sem dados de engajamento — ver `OPUS_CLIP_GAP.md` §L10 |
| N3 | Diarização (quem falou) | O whisper.cpp não entrega de forma confiável; exigiria outro modelo |
| N4 | Tradução | O Whisper traduz, mas isso é outro produto |
| N5 | Renderizar MP4 | Continua fora: a saída é projeto do CapCut |
| N6 | Reenquadramento com rastreamento | Lacuna L3, separada |

---

# Parte 1 — Transcrição (ASR)

## 1.1 Escolha da engine — medida, não suposta

| Engine | Pacotes Python novos | Puxa `torch` | Padrão de integração | RAM |
|---|---|---|---|---|
| **`whisper.cpp` (brew 1.9.4)** | **0** | não | subprocess, **igual ao que já fazemos com ffprobe** | baixa |
| `faster-whisper` | 18 | não | biblioteca Python | média |
| `mlx-whisper` | 25 | **sim** | biblioteca Python | alta |

Medido com `uv pip install --dry-run` nesta máquina. O `whisper.cpp` está no Homebrew
como bottle, com dependências `ggml`, `llama.cpp` e `sdl2-compat` — nenhuma delas Python.

### Decisão: `whisper.cpp`

Três razões, em ordem:

1. **Zero deriva de dependência.** O L1 tem 6 pacotes Python hoje. O `mlx-whisper`
   triplicaria isso e traria o `torch`. O `whisper.cpp` mantém o número em 6.
2. **É o padrão que o projeto já usa.** O `media.probe` chama `ffprobe` por
   `subprocess` com timeout e parsing de JSON. O ASR entra pelo mesmo caminho, com o
   mesmo tratamento de erro. Nada de arquitetura nova.
3. **8 GB de RAM.** Esta máquina tem 8 GB. Carregar Whisper em Python com `torch` ao
   lado do Chromium do CapCut é pedir swap.

**Consequência operacional:** o `whisper.cpp` passa a ser dependência externa ao lado do
FFmpeg, e o `capcut.system.doctor` precisa verificá-lo e dizer como instalar
(`brew install whisper-cpp`), do mesmo jeito que já faz com o `ffprobe`.

### Teto de modelo nesta máquina

| Modelo | Arquivo | RAM aprox. | Cabe em 8 GB? |
|---|---|---|---|
| `tiny` | ~75 MB | ~1 GB | sim |
| `base` | ~150 MB | ~1 GB | sim |
| `small` | ~500 MB | ~2 GB | sim |
| `medium` | ~1,5 GB | ~5 GB | apertado, com o CapCut fechado |
| `large-v3` | ~3 GB | ~10 GB | **não** |

**Default proposto: `small`.** É o equilíbrio para português. `medium` como opt-in
explícito, com aviso de que exige o CapCut fechado. `large-v3` bloqueado nesta máquina
com erro acionável em vez de swap.

> ⚠️ **A tabela acima é conhecimento geral sobre o Whisper, não medição minha.** A
> precisão real em PT-BR e o tempo de processamento por minuto de áudio **precisam ser
> medidos** antes de fixar o default — está no plano de testes (T1.1).

## 1.2 Contrato: `capcut.media.transcribe`

**Status:** `REQUIRES_EXTENSION`

```
entrada:
  source              string   caminho absoluto ou URL http(s)        [obrigatório]
  language            string   "auto" (default) | "pt" | "en" | ...
  model               enum     tiny | base | small (default) | medium
  word_timestamps     bool     default true
  vad                 bool     default true — descarta silêncio longo
  max_chars_per_block int      default 26 — molda os blocos de legenda
  max_block_seconds   number   default 4.0
  format              enum     blocks (default) | words | both
  offset              int      default 0   — paginação do transcript
  limit               int      default 200 — blocos por resposta
  refresh             bool     default false — ignora o cache

saída:
  transcript_id        string   estável: hash(arquivo + modelo + idioma)
  language             string   detectado
  language_probability number
  duration_s           number
  block_count          int
  segments             [{start, end, text}]      ← pronto para capcut.subtitle.add
  words                [{start, end, word}]      ← só se format inclui words
  compact              string   "[12.4] texto..." — para o agente ler
  truncated            bool     há mais blocos além de offset+limit
  model                string
  elapsed_s            number
  cached               bool
```

**O ponto que faz isso valer a pena:** `segments` sai no formato que o
`capcut.subtitle.add` **já aceita hoje** (`segments=[{start,end,text}]`, verificado na
tela na Phase 4). Nenhum contrato existente muda.

### Moldagem dos blocos — é aqui que mora a qualidade

Os segmentos nativos do Whisper **não são bons blocos de legenda**: ele quebra por
pausa de fala, gerando blocos de 10 s ou de 3 palavras. A moldagem é trabalho real:

| Regra | Valor | Origem |
|---|---|---|
| máximo de caracteres por linha | 26 | **medido na tela** na Phase 4: 27 caracteres couberam, 31 quebraram no meio da palavra |
| máximo de segundos por bloco | 4,0 | prática de legendagem |
| mínimo de segundos por bloco | 0,8 | abaixo disso o leitor não acompanha |
| quebra preferencial | em `.`, `?`, `!`, `,`, depois em fronteira de palavra | |
| junção | blocos com menos de 0,8 s são fundidos com o vizinho | |

O `subtitles.wrap_text()` e o `chars_per_line()` do L1 **já existem e estão testados** —
a moldagem os reaproveita em vez de duplicar a lógica.

### Cache — obrigatório, não otimização

Transcrever é caro (minutos). Reexecutar tem de ser grátis.

- Chave: `sha256(arquivo) + modelo + idioma`. Para URL, o hash é da URL mais o
  `Content-Length`.
- Local: `~/Library/Application Support/capcut-mcp/transcripts/<transcript_id>.json`
- Escrita atômica por `os.replace`, como o registry já faz.
- Guarda o resultado **completo** (blocos e palavras); a paginação acontece na leitura.
- `refresh=true` recalcula.

### Orçamento de contexto — restrição de primeira ordem

Um vídeo de 30 minutos gera ~5.000 palavras. Devolver `words[]` inteiro seria ~7 mil
tokens só de timestamps, e destruiria o contexto do agente.

Por isso: `format="blocks"` por default, `words` só quando pedido, `limit` de 200 blocos,
e o campo `compact` — uma linha por bloco, `[12.4] texto`, que é a forma que o agente
realmente lê para escolher cortes.

### Erros

| Código | Quando |
|---|---|
| `ASR_UNAVAILABLE` | binário do whisper.cpp ausente → sugestão `brew install whisper-cpp` |
| `ASR_MODEL_MISSING` | modelo não baixado → sugestão com o comando e o tamanho |
| `ASR_MODEL_TOO_LARGE` | `large-v3` nesta máquina → sugere `medium` e explica a RAM |
| `ASR_FAILED` | binário retornou erro → stderr no log, não na mensagem |
| `ASR_TIMEOUT` | excedeu o limite (proposta: 10× a duração do áudio, mínimo 120 s) |
| `SOURCE_NOT_FOUND` / `PROBE_FAILED` | reaproveitados do `media.probe` |
| `DISK_FULL` | espaço insuficiente para baixar o modelo |
| `NO_SPEECH_DETECTED` | o VAD não achou fala → sugere `vad=false` |

---

# Parte 2 — Seleção de cortes

## 2.1 Correção do que eu afirmei antes

Eu disse: *"não precisa de código, precisa de prompt"*. **Isso foi impreciso.** O
critério de escolha é prompt, sim. Mas entre um agente que adivinha e um agente
confiável há duas peças de código, e a segunda é obrigatória.

## 2.2 Peça A — encostar o corte na fronteira de fala

**Status:** `REQUIRES_EXTENSION`

Se o agente pede "mantenha 12,0 a 30,0" e a palavra *preço* começa em 11,82, o corte
entra no meio da sílaba. Com `words[]` isso se resolve:

```
início  → começo da primeira palavra que começa em ou depois do pedido,
          ou o fim da palavra anterior se estiver dentro da tolerância
fim     → fim da última palavra que termina em ou antes do pedido
padding → lead-in/lead-out opcional (proposta: 0,15 s), para não cortar a respiração
```

Entra como parâmetro do `capcut.video.cut`:

```
snap              enum    none (default) | speech
snap_tolerance    number  default 0.5  — quanto pode mover cada ponta
snap_padding      number  default 0.15
```

Com `snap="speech"`, o `cut` lê o transcript em cache daquele `source`. Sem transcript,
erro acionável em vez de silêncio. O retorno ganha `snapped: [{requested, applied, delta_s}]`
— o agente **precisa saber** que os tempos mudaram.

## 2.3 Peça B — remapear os tempos depois do corte · **a mais importante da spec**

Este é o erro mais provável de todo o fluxo, e ele é silencioso.

Suponha corte mantendo `[[0,3],[5,8]]`. A timeline final tem 6 s. Mas o transcript está
em **tempo da mídia original**. Uma fala em 6,0 s da origem cai em **4,0 s** da timeline.
Passar os segmentos do transcript direto para o `subtitle.add` produz legenda
dessincronizada — e nada no sistema atual detecta isso, porque o JSON fica válido.

### Solução: `capcut.subtitle.from_transcript`

**Status:** `REQUIRES_EXTENSION`

```
entrada:
  draft_id      string
  source        string   qual mídia (usa o transcript em cache)
  track         string   default "subtitle"
  style         enum     outline (default) | boxed | outline_boxed | plain
  ... demais parâmetros de estilo do subtitle.add
  straddle      enum     truncate (default) | drop | keep_partial

saída:
  blocks_imported     int
  blocks_dropped      int
  blocks_truncated    int
  mapping             [{source_range, timeline_range}]
  first_start_s / last_end_s
```

A tool lê o **plano declarativo do draft** (que o registry já guarda) para saber quais
trechos foram mantidos, e:

1. descarta os blocos que caem inteiramente em trecho removido;
2. remapeia os que caem em trecho mantido: `t_timeline = t_origem - deslocamento_acumulado`;
3. trata os que atravessam a fronteira do corte conforme `straddle`:
   - `truncate` (default): encurta para a parte mantida; descarta se sobrar menos de 0,8 s;
   - `drop`: descarta o bloco inteiro;
   - `keep_partial`: mantém e avisa.
4. reporta tudo no retorno e emite aviso quando descarta.

**Por que isso não pode ser responsabilidade do agente:** é aritmética de acumulação de
deslocamento com casos de borda. Pedir que o agente faça isso a cada projeto é garantir
erro. E o erro é invisível no JSON.

## 2.4 O que continua sendo prompt

O critério de escolha. Isto vai nas `instructions` do servidor e num guia curto:

```
1. capcut.media.transcribe(source)            → leia o campo `compact`
2. escolha os trechos segundo o pedido do usuário
3. capcut.draft.create(...)
4. capcut.video.cut(source, keep=[...], snap="speech")
5. capcut.subtitle.from_transcript(draft_id, source)   ← remapeia sozinho
6. capcut.text.add_many(items=[...])          → títulos nos momentos escolhidos
7. capcut.draft.validate(draft_id)
8. capcut.draft.save(draft_id)
```

Orientações a incluir no prompt, derivadas do que já sabemos:

- o gancho está nos 3 primeiros segundos do clipe — comece na frase, não no meio dela;
- prefira trechos que começam e terminam em fronteira de sentença;
- clipe curto para vertical: 20 a 60 s;
- `font_size` 14–15 para título, 8 para legenda (**medido na tela** na Phase 3);
- não coloque texto depois do fim do vídeo — o `validate` avisa, mas evite de saída.

## 2.5 Validação nova

Duas regras a acrescentar ao `validator.py`:

| Código | Severidade | Quando |
|---|---|---|
| `V_CAPTION_DESYNC_RISK` | `warning` | há corte no draft e legendas que **não** vieram do `from_transcript` — provável dessincronização |
| `V_CUT_MID_WORD` | `info` | corte feito com `snap="none"` havendo transcript disponível |

A primeira é a rede contra justamente o erro da §2.3.

---

## Plano de testes

### T1 — ASR (precisa de medição real antes de fixar defaults)

| # | Teste | Critério |
|---|---|---|
| T1.1 | **Medir** precisão PT-BR e tempo por minuto de áudio nos modelos `base`, `small`, `medium` | produz a tabela que fixa o default; sem isso o default é chute |
| T1.2 | Áudio de 30 s com fala conhecida | palavras corretas, timestamps dentro de ±0,3 s |
| T1.3 | `segments` alimenta `subtitle.add` sem transformação | contrato preservado |
| T1.4 | Blocos respeitam 26 caracteres e 0,8–4,0 s | nenhum bloco fora da faixa |
| T1.5 | Cache: segunda chamada devolve `cached: true` em menos de 100 ms | |
| T1.6 | `format="blocks"` de um transcript longo não passa de um teto de tokens | orçamento de contexto |
| T1.7 | Binário ausente → `ASR_UNAVAILABLE` com o comando do brew | |
| T1.8 | `large-v3` → `ASR_MODEL_TOO_LARGE` sem tentar carregar | |
| T1.9 | Áudio só com silêncio → `NO_SPEECH_DETECTED` | |
| T1.10 | Áudio com sotaque e ruído | registra a degradação, não finge que não existe |

### T2 — Snap

| # | Teste | Critério |
|---|---|---|
| T2.1 | Pedido no meio de uma palavra → move para a fronteira | `delta_s` reportado |
| T2.2 | Pedido já em fronteira → `delta_s` zero | |
| T2.3 | Fronteira além da tolerância → não move, e avisa | |
| T2.4 | `snap="speech"` sem transcript em cache → erro acionável | |

### T3 — Remapeamento · **os testes que mais importam**

| # | Teste | Critério |
|---|---|---|
| T3.1 | Corte `[[0,3],[5,8]]`, bloco em 6,0–7,0 da origem | vira 4,0–5,0 na timeline |
| T3.2 | Bloco inteiramente em trecho removido | descartado, contado em `blocks_dropped` |
| T3.3 | Bloco atravessando a fronteira, `straddle="truncate"` | encurtado para a parte mantida |
| T3.4 | Resto da truncagem abaixo de 0,8 s | descartado com aviso |
| T3.5 | Três trechos mantidos, deslocamento acumulado | todos os blocos no lugar certo |
| T3.6 | Sem corte no draft | remapeamento é identidade |
| T3.7 | **Verificação visual no CapCut** | as legendas batem com a fala depois do corte |

T3.7 é o único teste que realmente prova o conjunto. Os outros seis protegem a
aritmética; só o olho confirma a sincronia.

---

## Acceptance criteria

| # | Critério |
|---|---|
| AC1 | `capcut.media.transcribe` de um vídeo sem SRT produz legendas corretas no CapCut, verificado na tela |
| AC2 | O L1 continua com **6 dependências Python** |
| AC3 | `capcut.system.doctor` detecta ausência do whisper.cpp e do modelo, com o comando de correção |
| AC4 | Segunda transcrição do mesmo arquivo é servida do cache |
| AC5 | Transcript de 30 min entregue em forma compacta sem estourar o contexto |
| AC6 | Corte com `snap="speech"` não parte palavra, verificado ouvindo o resultado |
| AC7 | **Legenda sincronizada depois de um corte com três trechos, verificada na tela** |
| AC8 | `validate` avisa quando há corte e legenda não remapeada |
| AC9 | O fluxo inteiro roda pelo protocolo MCP, do vídeo cru ao projeto salvo |
| AC10 | Nenhuma descrição de tool cita tool não exposta (teste que já existe) |

---

## Riscos

| # | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| R1 | **Dessincronização de legenda após corte** | alta se o remapeamento não existir | alto | §2.3 é obrigatória, não opcional; `V_CAPTION_DESYNC_RISK`; T3.7 |
| R2 | 8 GB de RAM com o CapCut aberto | média | médio | default `small`; `medium` avisa para fechar o app; `large-v3` bloqueado |
| R3 | Precisão em PT-BR abaixo do aceitável no `small` | média | médio | T1.1 mede antes de fixar; se falhar, `medium` vira default e a exigência de RAM vai para a documentação |
| R4 | Transcript longo estoura o contexto do agente | alta sem paginação | alto | `format`/`offset`/`limit` e o campo `compact` desde o início |
| R5 | Flags do CLI do whisper.cpp diferentes do previsto | média | baixo | **verificar as flags reais antes de escrever o wrapper** — esta spec não as afirma |
| R6 | Download do modelo em disco apertado | média | médio | guarda de espaço antes de baixar; o disco oscilou de 12 GiB a 0,3 GiB nesta sessão |
| R7 | Tempo de transcrição maior que o timeout de tool-call do Codex | média | médio | medir em T1.1; se necessário, modo assíncrono com `job_id`, como se cogitou para o `save` |

---

## Fases de implementação

| Fase | Entrega | Gate |
|---|---|---|
| **A** | Verificar as flags do whisper.cpp; medir T1.1 nos três modelos | tabela de precisão e tempo; default escolhido com dado |
| **B** | `capcut.media.transcribe` com cache, moldagem de blocos e paginação | T1.2–T1.10 verdes |
| **C** | Legenda automática ponta a ponta **sem corte** | verificação visual: vídeo cru → legendas corretas |
| **D** | `snap="speech"` no `capcut.video.cut` | T2.1–T2.4 |
| **E** | `capcut.subtitle.from_transcript` com remapeamento | T3.1–T3.6 |
| **F** | Verificação visual do conjunto: corte + legenda sincronizada | **T3.7 e AC7** |
| **G** | Prompt de seleção nas `instructions`; regras novas no validator | AC8, AC9 |

A fase C entrega valor sozinha: legenda automática de vídeo sem corte já elimina o "me
dê o SRT". As fases D–F é que fecham o fluxo com corte.

---

## Superfície resultante

De 9 para 11 tools expostas:

| Tool | Situação |
|---|---|
| `capcut.media.transcribe` | **nova** |
| `capcut.subtitle.from_transcript` | **nova** |
| `capcut.video.cut` | ganha `snap`, `snap_tolerance`, `snap_padding` |
| `capcut.system.doctor` | passa a verificar whisper.cpp e modelos |
| `capcut.draft.validate` | ganha duas regras |
| as outras 6 | sem mudança |
