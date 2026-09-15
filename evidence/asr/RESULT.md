# Evidência — Transcrição (ASR) e seleção de cortes

Execução de `docs/SPEC_ASR_E_SELECAO.md`. Tudo abaixo é medido nesta máquina
(macOS 24.6.0, 8 GB, working set de GPU 5.726 MB), não estimado.

## T1.1 — a medição que fixou o default

Fixture `fixtures/fala_pt.wav`: 16,72 s, PT-BR, gerada com `say -v Luciana` a
partir de `fixtures/fala_pt.txt`. whisper.cpp 1.9.4 via `brew`, binário
`whisper-cli`.

| Modelo | Arquivo | Tempo | Fator tempo real | Blocos | Pontuação de frase |
|---|---|---|---|---|---|
| `base` | 141 MB | 0,80 s | ~21x | 11 | **não** |
| `small` | 465 MB | 1,62 s | ~10x | 10 | **sim** |
| `medium` | 1,5 GB | não medido | — | — | — |
| `large-v3` | 3,1 GB | bloqueado | — | — | — |

**`small` é o default, e o motivo é pontuação, não velocidade.** O `base` é 2x
mais rápido e ainda assim sobra folga; o que ele não entrega é ponto e vírgula,
e sem pontuação a legenda quebra em lugar errado e a seleção de trechos perde a
fronteira de sentença — que é justamente o critério da §2.4. `tiny` e `base`
emitem `ASR_MODEL_WEAK_PUNCTUATION` quando escolhidos de propósito.

`large-v3` é recusado por `model_path()` antes de qualquer carga: pede ~10 GB e
a máquina tem 8. `medium` **não foi medido** — precisa de 1,5 GB de download e o
disco está em 312 MiB livres. O risco R3 da spec (precisão do `small` abaixo do
aceitável) fica portanto parcialmente aberto: o dado que tenho é a tabela acima
mais o erro de reconhecimento abaixo.

### Precisão medida no `small`

38 palavras, **1 erro**: `prazo` sai `trase`. Nas 4 rodadas, sempre a mesma
palavra — a fixture é TTS, com prosódia achatada, o que é mais difícil que fala
real em alguns aspectos e mais fácil em outros. Não extrapolo daqui para fala
humana.

O reconhecedor **normaliza número e moeda**: "cento e vinte reais" sai `R$ 120`,
"três dias" sai `3 dias`. Não é erro, é convenção de escrita, mas compara falso
contra o texto lido em voz alta — o teste T1.2 normaliza as duas pontas antes de
comparar, em vez de afrouxar a asserção.

### Ruído (T1.10)

Mixando `anoisesrc=a=0.06` sobre a fixture:

| | Confiança média por palavra | Acerto por palavra |
|---|---|---|
| limpo | 0,921 | 96% |
| com ruído | 0,857 | 92% |

A confiança cai de forma consistente; a taxa de acerto por palavra nesta fixture
curta oscila nas duas direções entre rodadas, então o teste afirma só a queda de
confiança. Afirmar que o acerto sempre cai seria inventar um resultado.

## Correções de spec descobertas na Fase A

A spec foi escrita antes de o binário ser exercitado. Quatro pontos estavam
errados:

1. `whisper-cli` aceita **só** `.wav`, `.mp3`, `.ogg`, `.flac`. Vídeo precisa de
   extração por ffmpeg — `ensure_audio()` faz isso em diretório temporário.
2. `-ojf` já entrega timestamp por token; `-dtw` não é necessário para isto.
3. VAD exige **outro** arquivo de modelo, separado. Não é uma flag.
4. `-ml N -sow` molda o bloco de legenda nativamente, no binário. Não precisei
   reimplementar a quebra por caractere — só a fusão por tempo (`_shape_blocks`),
   que o binário não controla.

## Alucinação em silêncio — defeito encontrado pelo teste T1.9

3 s de silêncio puro (`anullsrc`), modelo `base`: o whisper.cpp devolveu **um
bloco** com o texto `[MÚSICA DE FUNDO]`. Sem tratamento isso viraria uma legenda
na tela, em cima de um trecho onde não há fala.

Correção: `is_non_speech()` descarta bloco que é só anotação entre `[]`, `()`,
`*` ou `♪`. Se não sobrar bloco nenhum, a transcrição levanta
`NO_SPEECH_DETECTED` com os blocos descartados no contexto — a verdade, em vez de
uma legenda inventada. Linha com anotação **misturada** com fala
(`[inaudível] mas depois`) é preservada.

## T2 — encostar o corte na fala

`snap="speech"` em `fixtures/video_fala.mp4` (18,77 s), pedido
`[[5.0,10.0],[13.0,17.0]]`, tolerância 0,5 s, padding 0,15 s:

```
pedido [5.0, 10.0] -> aplicado [5.26, 10.47]   (Δini +0.26  Δfim +0.47)
pedido [13.0, 17.0] -> aplicado [12.75, 16.83] (Δini -0.25  Δfim -0.17)
duração final: 9,29 s
```

Cada ponta andou menos que tolerância + padding, e o relatório do corte diz
quanto — o agente não precisa adivinhar o que a ferramenta fez com o pedido dele.

## T3 — remapeamento de tempo (a peça que importa)

O mapa é derivado dos `source_timerange`/`target_timerange` dos **segmentos
reais do script**, não do plano declarativo. Consequência prática: funciona igual
se o corte veio de `capcut.video.cut` ou de chamadas soltas de `capcut.video.add`.

Verificado ponta a ponta com o corte acima:

```
origem  5.26-10.47 -> timeline  0.00- 5.21
origem 12.75-16.83 -> timeline  5.21- 9.29

10 blocos no transcript -> 6 importados | 4 descartados | 2 truncados
avisos: CUT_SNAPPED_TO_SPEECH, CAPTIONS_DROPPED_BY_CUT, CAPTIONS_TRUNCATED_BY_CUT
```

O bloco de 12,25–13,68 da origem atravessava a fronteira: foi truncado em 12,75 e
mapeado para 5,21–6,14 na timeline. Aritmética conferida à mão.

## T3.7 / AC7 — verificação visual, feita

Projeto `AC7 Sync`, salvo pelo protocolo MCP e aberto no CapCut 9.4.1. Corte de
**três trechos** com `snap="speech"` sobre `video_fala.mp4`:

```
timeline  0.000- 3.430  <- origem  0.000- 3.430
timeline  3.430- 7.110  <- origem  6.830-10.510
timeline  7.110-10.390  <- origem 13.550-16.830
```

### O que o olho conferiu

Três posições do playhead, lidas na tela com o timecode do próprio app:

| Timecode no app | Legenda exibida | Previsto pelo mapa |
|---|---|---|
| `00:00:02:00` | "transcrição automática." | 1,46–3,28 ✅ |
| `00:00:04:16` | "O preço do produto é de R$" | 3,56–5,63 ✅ |
| `00:00:08:01` | "Obrigado por assistir até" | 7,24–8,95 ✅ |

Duração total no app: `00:00:10:12` = 10,4 s, contra os 10,39 s gravados.

O caso do meio é o que prova a peça: essa fala está em **6,96 s da mídia
original** e a legenda aparece em **3,56 s da timeline**. Sem remapeamento ela
ficaria em 6,96 — em cima de "Obrigado por assistir". Na timeline também se vê
que os buracos da faixa de legenda caem exatamente nas fronteiras dos três
segmentos de vídeo.

O título (`text.add_many`, font_size 15, `transform_y` 0,55) e a legenda
(font_size 8, `transform_y` -0,8) renderizam nas posições pedidas, com a
acentuação portuguesa correta.

### Por que o olho não bastava, e o que resolveu

O vídeo da fixture é um padrão de barras **estático**: o frame é idêntico em
todos os instantes, então a tela confirma *qual legenda aparece em qual
timecode*, mas não consegue dizer *qual fala está tocando ali*. Faltava a outra
metade.

Primeira tentativa, e ela estava errada: reconstruí o corte com ffmpeg,
transcrevi o resultado e comparei os timestamps das palavras contra a previsão.
Deu uma deriva aparente de até **0,61 s**. Só que esse instrumento mistura o
erro do remapeamento com o erro de timestamp de **dois** passes de ASR
independentes — não mede o que eu queria medir.

O instrumento certo é o sinal. Montei o corte amostra por amostra a 16 kHz e
comparei cada janela de legenda na timeline contra a janela correspondente na
origem:

```
 0.00- 1.46 <-  0.00- 1.46  'Bem-vindo ao teste de'       amostras diferentes: 0/23360
 1.46- 3.28 <-  1.46- 3.28  'transcrição automática.'     amostras diferentes: 0/29120
 3.56- 5.63 <-  6.96- 9.03  'O preço do produto é de R$'  amostras diferentes: 0/33120
 5.63- 6.92 <-  9.03-10.32  '120.'                        amostras diferentes: 0/20640
 7.24- 8.95 <- 13.68-15.39  'Obrigado por assistir até'   amostras diferentes: 0/27360
 8.95-10.24 <- 15.39-16.68  'o final deste vídeo.'        amostras diferentes: 0/20640
```

**Zero amostras divergentes em todas as seis.** O áudio embaixo de cada legenda
na timeline é bit-a-bit o mesmo que estava embaixo dela na mídia original. O
remapeamento não está "dentro da tolerância": ele é exato. Aquela deriva de
0,61 s era variância do segundo pass de ASR.

A precisão da legenda passa a ser, então, exatamente a precisão dos timestamps
do primeiro pass — nada é acrescentado pelo corte. Isso é o que T1.2 cobre.

### Detalhe honesto

O áudio da fixture tem 16,721 s e o vídeo 18,767 s. O terceiro trecho pede até
16,83 s, então seus últimos 0,109 s são silêncio por falta de faixa de áudio, não
por defeito. Nenhuma legenda cai nessa sobra (a última termina em 10,24 de
10,39).

## Defeito encontrado na verificação visual: a borda da legenda é fina demais

Olhando a tela do `AC7 Sync`, "O preço" sobre a barra **branca** sai lavado,
quase ilegível, enquanto "do produto é de R$" sobre as barras escuras sai
nítido. A borda está no JSON — `strokes[0].width = 0.012` — mas não aparece.

Rastreando: o L0 mapeia `width / 100.0 * 0.2`, e o comentário do próprio
upstream nessa linha diz *"此映射可能不完全正确"* ("este mapeamento pode não
estar totalmente correto"). O preset `outline` do L1 usa `border_width: 6.0`,
que sai como **0,012** — contra o default do próprio upstream, `40.0` → **0,08**,
**6,7× mais grosso**.

Foi erro meu de calibração, e passou porque a Phase 4 verificou as legendas mas
não a **borda contra fundo claro**. O `V_TEXT_LOW_CONTRAST` do validator avisa
sobre ausência de borda, não sobre borda insuficiente — então não pegou.

### Calibração, medida na tela

Projeto `Borda Calibra`: a mesma frase em cinco larguras, todas visíveis ao mesmo
tempo sobre barras claras, em `00:00:04:02`.

| `border_width` | stroke | O que se vê na tela |
|---|---|---|
| (sem borda) | ausente | branco direto sobre a cor, sem separação |
| 6,0 (preset antigo) | 0,012 | **contorno nenhum** — indistinguível de "sem borda" |
| 20,0 | 0,040 | contorno fino, presente; magro para legenda pequena |
| **40,0** | **0,080** | **contorno limpo, letras nítidas, vazados abertos** |
| 70,0 | 0,140 | entope o vazado do "ç" e do "e", funde letras vizinhas |

**40,0 é o valor**, e é também o default do próprio upstream — o que faz sentido:
alguém já o calibrou contra o app real. `outline_boxed` foi de 5,0 para 30,0, mais
fino porque ali o fundo também ajuda.

### Fechamento no caso que havia falhado

Reconstruí o `AC7 Sync` com o valor novo e reabri no ponto exato do defeito,
`00:00:04:19`, onde "O preço" cai sobre a barra **branca**: agora sai com
contorno preto nítido e legível. Antes, no mesmo frame, saía lavado.

O teste `test_borda_do_outline_e_espessa_o_bastante` deixou de ser xfail e passa
com piso 0,08, então uma regressão para valor fino volta a quebrar a suíte.

## Testes

**181 coletados, 181 passando.**

Novos neste ciclo: `tests/unit/test_asr_and_selection.py`, 37 testes cobrindo
T1.2–T1.10, T2.1–T2.4, T3.1–T3.6, AC3 e AC8.

## Acceptance criteria

| AC | Situação |
|---|---|
| AC1 | ✅ legenda de vídeo sem SRT, verificada na tela (`AC7 Sync`) |
| AC2 | ✅ 6 dependências Python; whisper.cpp é binário externo, não pacote |
| AC3 | ✅ `doctor` traz `whisper_cli`, `asr_models_installed` e o comando de correção |
| AC4 | ✅ segunda transcrição vem do cache em < 100 ms |
| AC5 | ✅ `compact` pagina; 600 blocos em `limit=200` ficam sob ~4k tokens |
| AC6 | ✅ corte com `snap` conferido no sinal: identidade amostra-a-amostra |
| AC7 | ✅ **legenda sincronizada após corte de 3 trechos, verificada na tela** |
| AC8 | ✅ `V_CAPTION_DESYNC_RISK` avisa; `from_transcript` não dispara o aviso |
| AC9 | ✅ fluxo inteiro pelo protocolo MCP, do vídeo cru ao projeto salvo |
| AC10 | ✅ nenhuma descrição cita tool não exposta |

## O que está aberto

- `medium` não medido: 1,5 GB de download. O que se sabe do `small` é 1 erro em
  38 palavras nesta fixture, sempre a mesma (`prazo` -> `trase`). R3 da spec
  segue parcialmente aberto.
- Keyframes continuam verificados só em JSON, nunca na tela — pré-requisito de
  qualquer trabalho de face tracking.
