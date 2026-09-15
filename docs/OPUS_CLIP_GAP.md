# Análise de lacuna: o que falta para chegar perto do Opus Clip

**Data:** 2026-09-14 · **Base do nosso lado:** `capcut-mcp-mac` @ `c1e0108`, 140 testes
**Fontes sobre o Opus Clip:** ver o fim do documento. Pesquisado, não de memória.

---

## 1. O pipeline do Opus Clip

| Etapa | O que o Opus Clip faz |
|---|---|
| **Ingestão** | Upload ou link: YouTube, Google Drive, Vimeo, Zoom, Rumble, Twitch, Facebook, LinkedIn, Twitter, Loom, Riverside, StreamYard |
| **Transcrição** | ASR automática, precisão declarada acima de 97%, em 25+ idiomas (inclui português) |
| **Compreensão** | Analisa pistas visuais, de áudio e de sentimento ao longo do vídeo inteiro |
| **Seleção de cortes** | `ClipAnything`: acha os momentos em qualquer gênero (podcast, entrevista, vlog, esporte, gaming, explainer). Aceita prompt em linguagem natural para pedir momentos específicos |
| **Pontuação** | `Virality Score` 0–100, treinado em padrões de engajamento de milhões de vídeos; avalia força do gancho nos 3 primeiros segundos, coerência narrativa, ressonância emocional, ritmo e relevância de tendência |
| **Reenquadramento** | `ReframeAnything`: rastreia objeto/rosto para manter o sujeito centralizado ao converter 16:9 → 9:16; layouts de split-screen; rastreamento manual opcional |
| **Legendas** | Automáticas, animadas (cinéticas), com estilo |
| **B-roll** | Insere B-roll gerado por IA ou de banco, contextualmente, para cobrir lacunas visuais |
| **Marca** | Brand templates: fontes, cores, logo, intro e outro |
| **Edição manual** | Editor web para ajustar o resultado |
| **Renderização** | Entrega o vídeo **pronto** |
| **Publicação** | Um clique para todas as redes; agendamento |
| **Operação** | Workspace de time, API para automação |

O resumo em uma frase: **o Opus Clip é um pipeline de renderização.** Entra um vídeo
longo, saem vários vídeos curtos verticais prontos para postar.

## 2. O que a gente tem

| | |
|---|---|
| **O que é** | Um gerador de **arquivo de projeto** do CapCut, dirigido por agente via MCP |
| **Entrada** | Caminho de arquivo local (ou URL http direta de mídia) |
| **Operações** | Cortar por trechos explícitos · legendar de SRT ou de blocos estruturados · textos em momentos pré-determinados |
| **Proteções** | Validação com 11 regras antes de gravar; save recusa com erro; avisos estruturados |
| **Saída** | Uma pasta de projeto que **um humano abre no CapCut** |
| **Verificado** | 140 testes; formato confirmado na tela do CapCut 9.4.1 |

O resumo em uma frase: **é um montador de timeline.** Entra uma decisão editorial já
tomada, sai um projeto editável.

---

## 3. A diferença que não é uma funcionalidade

As duas coisas não estão na mesma categoria. O Opus Clip **decide e renderiza**; a gente
**executa e entrega para edição**.

```
OPUS CLIP     vídeo longo → transcreve → DECIDE os cortes → pontua →
              reenquadra → legenda → renderiza → MP4 pronto → publica

A GENTE       decisão já tomada → monta a timeline → projeto do CapCut →
              humano abre e refina → humano exporta
```

Isso tem duas consequências práticas que valem mais que qualquer item de lista:

**(a) Falta a camada que decide.** Tudo que o Opus Clip vende — achar o momento bom,
pontuar, reenquadrar seguindo o rosto — acontece *antes* do que a gente faz. A gente
construiu a última etapa primeiro.

**(b) Se o objetivo é MP4 pronto, o CapCut é o alvo errado.** Para cortar, queimar
legenda e colocar texto em vídeo vertical, o FFmpeg faz direto — sem CapCut, sem
formato de draft para engenharia reversa, sem humano abrindo aplicativo. O CapCut só
se justifica quando o humano **quer** refinar depois. Vale decidir isso antes de
investir: são dois produtos diferentes.

---

## 4. Lacunas, em ordem de alavancagem

### L1 — Transcrição (ASR) · **a mais importante**

Hoje a gente exige que alguém entregue o SRT. Sem ASR não existe legenda automática
nem seleção de cortes — é a base de tudo o mais.

- **Como fechar:** Whisper local (`faster-whisper` roda bem em Apple Silicon) ou API.
  Precisa de timestamps por palavra, não só por bloco — é isso que habilita legenda
  cinética depois.
- **Encaixe:** o `capcut.subtitle.add` já aceita `segments=[{start,end,text}]`, então o
  ASR pluga sem mudar o contrato. Uma tool nova, `capcut.media.transcribe`.
- **Esforço:** baixo. Uma semana, talvez menos.
- **Ganho:** destrava L2, L3 e legenda automática de uma vez.

### L2 — Seleção de cortes

O Opus Clip usa um modelo próprio. **Aqui a nossa arquitetura tem vantagem**: dado um
transcript com timestamps, escolher os melhores momentos é exatamente o que um agente
faz bem — e ele aceita instrução arbitrária ("ache onde ele fala de preço", "quero os 3
momentos mais engraçados"), que no Opus Clip é um recurso à parte (`ClipAnything` por
prompt).

- **Como fechar:** o agente lê o transcript e chama `capcut.video.cut` com os `keep`.
  Não precisa de código novo — precisa de um **prompt de sistema** e talvez uma tool que
  devolva o transcript em formato compacto.
- **Esforço:** muito baixo. É configuração, não engenharia.

### L3 — Reenquadramento com rastreamento de rosto · **a maior lacuna técnica**

Converter 16:9 → 9:16 sem rastrear o sujeito faz o falante sair do quadro. Hoje a gente
só tem `scale`/`transform` estáticos.

- **Como fechar:** detecção de rosto por frame (MediaPipe ou OpenCV) → suavizar a
  trajetória → gerar keyframes de `position_x`/`scale`. O L0 **já suporta keyframes**
  nessas propriedades (`add_video_keyframe_impl`, 11 propriedades), e eu deliberadamente
  não expus a tool. O caminho existe.
- **Ressalva honesta:** a Phase 3 nunca verificou keyframes na tela do CapCut — só no
  JSON. Antes de construir isso, precisa de teste visual.
- **Esforço:** médio-alto. É o item mais caro da lista.

### L4 — Legenda cinética (palavra por palavra)

O Opus Clip destaca a palavra falada. A gente tem legenda estática com borda ou caixa.

- **Como fechar:** timestamps por palavra do ASR + um segmento de texto por palavra, ou
  `text_styles` por faixa de caracteres — que **já funciona e está verificado na tela**
  (o teste tricolor da Phase 3).
- **Ressalva:** um segmento por palavra infla o JSON e a timeline. Precisa medir se o
  CapCut aguenta centenas de segmentos de texto.
- **Esforço:** médio.

### L5 — Ingestão por link

Hoje: caminho local. O Opus Clip aceita 11 fontes.

- **Como fechar:** `yt-dlp` cobre YouTube, Twitch, Facebook, Twitter e mais numa
  dependência. Zoom/Drive/Loom exigem OAuth de cada um.
- **Esforço:** baixo para o `yt-dlp`; médio por cada serviço autenticado.
- **Ressalva legal:** baixar de plataformas de terceiros tem termos de uso próprios.

### L6 — Brand templates

Fonte, cor, logo, intro e outro padronizados.

- **Como fechar:** arquivo de preset que o L1 aplica. Os presets de legenda
  (`outline`, `boxed`) já são a semente disso. Logo/intro/outro = imagem e vídeo em
  track própria — as tools `image.add` e `video.add` **já existem e estão testadas**,
  só estão fora da superfície exposta.
- **Esforço:** baixo.

### L7 — Renderização para MP4 · **decisão de arquitetura, não tarefa**

O VectCutAPI **não tem** renderização: esse módulo é fechado, e o
`jianying_controller.py` que exportaria via UI é código morto que importa um módulo
inexistente. Três caminhos:

| Caminho | Prós | Contras |
|---|---|---|
| Pipeline FFmpeg próprio | Determinístico, sem humano, sem CapCut | Reimplementa o compositor: legenda queimada, texto, transição |
| Automação de UI do CapCut para exportar | Reaproveita o render do app | Frágil; no macOS precisa de Accessibility API; é o que a auditoria reprovou no upstream |
| Manter o humano exportando | Zero trabalho | Não é "parecido com Opus Clip" |

**Minha leitura:** se MP4 pronto é requisito, o FFmpeg direto é mais honesto que o
CapCut. Se o valor está no humano refinar, a gente já está no lugar certo.

### L8 — Publicação e agendamento

- **Como fechar:** API de cada plataforma (TikTok Content Posting, YouTube Data,
  Instagram Graph). Cada uma exige app review e OAuth.
- **Esforço:** alto, e mais burocrático que técnico.

### L9 — B-roll automático

- **Como fechar:** banco de stock (Pexels/Storyblocks têm API) ou geração. O agente
  escolhe pelo transcript; `image.add`/`video.add` colocam na timeline.
- **Esforço:** médio.

### L10 — Virality Score · **não replicável de forma honesta**

O Opus Clip treina isso em padrões de engajamento de milhões de vídeos. A gente não tem
esses dados.

Um agente consegue avaliar heuristicamente força de gancho, coerência e ritmo — e isso
tem valor real. O que **não** dá é prever engajamento. Se isso virar um número de 0 a
100 na interface, é teatro. Melhor entregar uma justificativa em texto ("o gancho está
no segundo 4, não no 1; considere começar aqui") do que um score inventado.

---

## 5. O que a gente tem e o Opus Clip não

Não é uma lista de consolo: são diferenças que podem ser o produto.

| Nosso | Por que importa |
|---|---|
| **Saída editável no NLE do usuário** | O Opus Clip entrega vídeo renderizado; o refino é no editor web dele. A gente entrega um projeto do CapCut que o usuário abre e mexe. Uma resenha independente de 2026 estima que ~40% dos clipes do Opus Clip são descartados — quem descarta quer editar, não regenerar |
| **Instrução arbitrária** | O nosso fluxo é dirigido por agente do começo ao fim, não por um pipeline fixo |
| **Local, sem upload** | O material do usuário não sai da máquina dele. Sem cota de minutos |
| **Sem assinatura por minuto** | O Opus Clip cobra por minuto processado |

---

## 6. Caminho sugerido

Se o objetivo é "parecido com Opus Clip" **mantendo o CapCut** como saída:

1. **ASR com timestamps por palavra** (L1) — destrava metade da lista.
2. **Prompt de seleção de cortes** (L2) — quase de graça, e é onde o agente brilha.
3. **Reexpor `image.add` e `video.add`** + brand template (L6) — já estão prontos.
4. **Teste visual de keyframes**, e só então reenquadramento com rastreamento (L3).
5. **Legenda cinética** (L4) depois do ASR por palavra.
6. `yt-dlp` para ingestão (L5) quando fizer falta.

Com 1 a 3 feitos, o fluxo passa de "me dê o SRT e os tempos" para "me dê o vídeo e eu
devolvo um projeto cortado, legendado e titulado" — que já é a proposta do Opus Clip
menos a renderização e a pontuação.

Se o objetivo é **MP4 pronto sem humano**, a conversa é outra: aí o alvo é um pipeline
FFmpeg, e o trabalho no formato de draft do CapCut deixa de ser o caminho.

---

## Fontes

- [OpusClip — site oficial](https://www.opus.pro/)
- [Creator Economy 2026: AI Video Repurposing — blog do OpusClip](https://www.opus.pro/blog/creator-economy-2026-ai-video-repurposing-attention-war)
- [Opus Clip Tested 2026: Where the AI Wins (and the 40% You'll Discard) — BIGVU](https://bigvu.tv/blog/opus-clip-tested-2026-where-ai-wins-40-percent-discard/)
- [Is Opus Clips Worth It? An Honest 2026 Review — BIGVU](https://bigvu.tv/blog/opus-clips-worth-the-hype/)
- [OpusClip Review 2026: Pricing, Pros, Cons and Alternatives — Argil](https://www.argil.ai/blog/opusclip-ai-powered-video-repurposing-1cfae)
- [Opus Clip 2026 Complete Guide — AI Tools DevPro](https://aitoolsdevpro.com/ai-tools/opus-clip-guide/)
