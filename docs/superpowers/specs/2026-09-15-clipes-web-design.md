# Design — Clipes web: da gravação longa ao clipe pronto para o CapCut Web

**Data:** 2026-09-15 · **Estado:** aprovado nas seções, aguardando revisão da spec
**Substitui:** o alvo CapCut Desktop como caminho principal

---

## 1. O problema

Hoje o projeto gera um **rascunho do CapCut Desktop** escrevendo arquivos em
`~/Movies/CapCut/User Data/Projects/`. Isso funciona e está verificado na tela,
mas exige que cada pessoa tenha o app instalado e rode algo na própria máquina.
Para uso de time isso não serve: ninguém quer pedir ao usuário que suba um
processo no computador dele.

O objetivo é um aplicativo web onde a pessoa sobe uma gravação longa, a IA acha
os momentos que valem, ela revisa, e **termina de editar no CapCut Web** — sem
instalar nada.

## 2. Goals

1. Pessoa abre um link, sobe um vídeo, e não instala nada.
2. A IA transcreve e propõe clipes com justificativa.
3. A pessoa **revisa e corrige** o que a IA propôs: pontas dos cortes, texto das
   legendas, títulos.
4. A entrega, por clipe: um **MP4 já cortado** e um **SRT alinhado**, que a
   pessoa sobe e importa no CapCut Web para estilizar e exportar.
5. Reaproveitar o que já está construído e verificado: transcrição,
   remapeamento de tempo, quebra de legenda em fronteira de palavra.

## 3. Non-Goals

- **Não renderizamos vídeo.** Sem legenda queimada, sem texto desenhado, sem
  reencode. Quem gera pixel novo é o CapCut.
- **Não é editor de timeline.** Sem múltiplas faixas, sem arrastar clipe, sem
  transição. É uma tela de revisão do que a IA decidiu.
- **Não substitui o CapCut.** Estilo de legenda, reenquadramento e export são
  dele — e ele faz melhor.
- **Sem publicação em rede social**, sem score de viralidade (ver §9).

## 4. Arquitetura

```
 navegador                       Vercel                        serviços
 ─────────                       ──────                        ────────
 sobe o vídeo ─────────────────────────────────────────────►   Blob
 preview (arquivo local)                                        │
 revisão e ajustes  ◄────────►  API (funções Node)  ◄────────►  Neon
 baixa mp4 + srt                      │    │                    projetos
                                      │    └───────────────►   API de ASR
                                      │                         LLM (seleção)
                                      ▼
                            container com FFmpeg
                            corte por cópia de fluxo
```

### 4.1 Decisões e por quê

**O preview não renderiza.** O navegador toca o arquivo **local** da pessoa via
`URL.createObjectURL` e desenha legenda e título por cima, pulando as fronteiras
dos trechos. Ajustar uma legenda é instantâneo e custa zero CPU. É o que permite
"revisar e corrigir" sem infraestrutura.

**O corte é cópia de fluxo, não render.** `ffmpeg -c copy` copia os bytes com
fronteiras novas: nenhum pixel é gerado, segundos de CPU para qualquer duração.
Cabe folgado no teto de 300 s do plano Hobby, onde um reencode não caberia.

**O clipe chega cortado, e isso não é preferência — é correção.** A documentação
do CapCut diz que o comportamento de trim *"depends on whether you use ripple
delete or the magnet feature, and it may vary between CapCut's mobile and desktop
versions"*, e "ripple delete em todas as faixas" ainda é **pedido de feature** no
fórum deles — ou seja, cortar o vídeo na timeline **não** arrasta as faixas de
texto. Qualquer desenho que peça à pessoa para cortar dentro do CapCut
dessincroniza as legendas por configuração que varia de máquina para máquina.
Entregando o clipe já cortado, ele **é** o vídeo inteiro começando em zero, e
"posição absoluta na timeline" e "tempo do clipe" passam a ser a mesma coisa.

**O vídeo sobe.** Consequência direta do corte no servidor. Uma versão anterior
deste desenho subia só o áudio (para o ASR) e mantinha o vídeo local; isso caiu
quando o corte virou responsabilidade do servidor. Vale registrar que o vídeo vai
para a ByteDance de qualquer forma no passo seguinte, quando ela abre o CapCut
Web — então o ganho abandonado era de banda e tempo, não de privacidade.

**Sem Workflow, sem fila.** Cada passo cabe numa função: o ASR é espera de I/O, a
seleção é espera de I/O, e o corte é cópia de bytes. Nenhum passo chega perto de
300 s. Introduzir Workflow aqui seria complexidade sem causa.

## 5. Modelo de dados

Um documento por projeto, no Neon:

```
projeto
├── id, nome, criado_em
├── fonte        { nome, bytes, duracao_s, largura, altura, fingerprint, blob_url }
├── transcript   { blocos[], palavras[], idioma, modelo }
└── clipes[]
    ├── id, titulo_curto, justificativa      ← por que a IA escolheu
    ├── trechos   [[4.9, 38.7]]              ← tempos da MÍDIA ORIGINAL
    ├── textos[]  { texto, inicio, duracao, posicao }
    ├── estilo    { max_chars_por_bloco, straddle }
    └── saida     { mp4_url, inicio_real_s }  ← preenchido após o corte
```

### 5.1 A regra que sustenta tudo: o SRT é derivado

**O SRT nunca é armazenado.** Ele é gerado no download, a partir de `trechos` +
`transcript`, passando pelo `timemap`. Três consequências:

1. É **impossível** o SRT divergir da decisão — ele é uma projeção dela. Arrastar
   a ponta de um corte e baixar de novo já sai certo.
2. O preview lê a mesma fonte (`trechos`), então preview e SRT não podem
   discordar.
3. Gerar variantes é grátis, o que resolve incertezas sem custo (§9.1).

### 5.2 O ajuste de keyframe, que não é opcional

Corte por cópia de fluxo cai em keyframe, então o início real do arquivo pode
sair até ~2 s antes do pedido. Gerar o SRT contra o tempo **pedido**
dessincronizaria por esse tanto — a mesma classe de erro que a auditoria de L1/L2
encontrou nesta base.

Portanto: depois do corte, `media.probe` lê a duração real e o offset efetivo, o
valor vai para `saida.inicio_real_s`, e **o SRT é gerado contra ele**. Medir, não
supor.

## 6. O fluxo da pessoa

1. Abre o link, entra (código interno).
2. Sobe a gravação. O preview já toca, do arquivo local.
3. A IA transcreve e propõe clipes, cada um com uma linha de justificativa.
4. Ela revisa: arrasta as pontas, corrige texto de legenda, edita títulos,
   descarta clipe que não serve.
5. Clica em **Preparar clipe**. O corte roda em segundos.
6. Baixa `clipe-1.mp4` e `clipe-1.srt`, e vê o passo a passo:
   > 1. Suba `clipe-1.mp4` no CapCut Web
   > 2. Aba **Captions** → *Upload caption file* → `clipe-1.srt`
   > 3. Estilize, aplique auto-reframe se quiser, exporte

O passo 2 é o caminho documentado: web aceita **só `.srt`**, e exige **UTF-8** —
que é o que o nosso gerador produz.

## 7. Reaproveitamento

| Módulo | Situação |
|---|---|
| `media.py` | transfere inteiro (ffprobe, duração, colisão) |
| `timemap.py` | as funções puras transferem; `build()` ganha adaptador para `trechos` |
| `subtitles.py` | a quebra em fronteira de palavra e o limite medido na tela transferem |
| `asr.py` | vira **fallback local**; na nuvem entra API de ASR (espera de I/O não é cobrada, CPU é) |
| `validator.py` | as regras de tempo transferem; as de CapCut Desktop saem |
| `deployer.py`, `profile.py`, `upstream.py`, L0 | **saem do caminho principal**; seguem servindo o modo MCP/Desktop |

O modo MCP e a saída para o CapCut Desktop **continuam existindo** para quem
quiser dirigir por agente — 246 testes cobrem isso e não se joga fora.

## 8. Erros e o que a tela diz

Herda o princípio desta base: erro tem **código, mensagem e sugestão**, e nunca
falha em silêncio.

| Situação | Comportamento |
|---|---|
| Vídeo sem faixa de áudio | recusa na hora do upload, com o motivo |
| ASR não reconhece fala | `NO_SPEECH_DETECTED`; anotação de som (`[MÚSICA]`) é descartada |
| Corte pedido cai no meio de palavra | `snap` move para a fronteira e **reporta** o quanto moveu |
| Corte sem reencode saiu fora do pedido | `inicio_real_s` registrado e o SRT corrigido por ele |
| Clipe acima de ~3 min | avisa que o CapCut Web pode demorar no upload |
| Upload maior que o limite do Blob | recusa antes de começar, dizendo o teto |

## 9. Riscos e o que **não** está verificado

| # | Risco | Situação |
|---|---|---|
| R1 | O import de SRT do CapCut Web não aceitar o nosso arquivo | **não verificado na tela.** Documentação diz que aceita `.srt` UTF-8 na aba Captions. Validação da Fase 1. |
| R2 | Offset de keyframe maior que o esperado | mitigado por medição (§5.2), mas o tamanho real do desvio é desconhecido até medir |
| R3 | Custo do ASR por minuto de áudio | **fornecedor não escolhido** — decisão da Fase 3, com critérios em §9.2. É o único custo variável do desenho. |
| R4 | Limite de upload do Blob para gravação longa | a verificar; upload do cliente é o caminho documentado |
| R5 | Legenda cinética e reenquadramento por rosto | **não entregáveis por nós** sem render. Vêm das ferramentas nativas do CapCut. Foram pedidos e não serão atendidos por este desenho — decisão consciente. |
| R6 | Score de viralidade | fora de escopo: não temos os dados de engajamento para isso, e um número inventado seria teatro. A IA entrega **justificativa em texto**. |

### 9.1 Como R1 deixa de bloquear

Porque o SRT é derivado (§5.1), gerar variantes custa o mesmo. A tela de entrega
oferece `clipe-1.srt` (zero-based, o caminho normal) e, atrás de um link
*"não alinhou?"*, `clipe-1-tempos-originais.srt`. Se o CapCut se comportar de um
jeito que não previmos, existe recuperação sem novo deploy.

### 9.2 Critérios para escolher o ASR (decisão da Fase 3)

Deixar o fornecedor em aberto na spec seria uma dependência sem nome no caminho
crítico, então ficam os critérios, em ordem de peso:

1. **Timestamp por palavra**, não só por bloco — sem isso o `snap` para fronteira
   de fala não funciona, e ele é o que evita corte no meio de sílaba.
2. **Pontuação de frase em português.** Foi medido nesta base que modelo sem
   pontuação quebra a legenda em lugar errado e destrói a seleção por fronteira
   de sentença. É critério eliminatório, não preferência.
3. **Custo por minuto**, comparado contra rodar `whisper.cpp` em container: a
   cobrança da Vercel é por CPU ativa, e espera de I/O não é cobrada — então a
   API tende a ganhar, mas isso precisa ser conferido com número real.
4. Aceitar arquivo por URL (o vídeo já está no Blob) evita um segundo upload.

O `asr.py` local, já testado, serve de referência de qualidade: o que for
escolhido precisa transcrever a fixture `fala_pt.wav` pelo menos tão bem quanto o
`small` do whisper (38 palavras, 1 erro conhecido).

## 10. Critérios de aceite

| # | Critério |
|---|---|
| AC1 | Pessoa sobe um vídeo e vê o preview sem nenhuma instalação |
| AC2 | Transcrição volta com timestamps e a IA propõe pelo menos um clipe com justificativa |
| AC3 | Arrastar a ponta de um corte muda o preview na hora, sem chamada de servidor |
| AC4 | `clipe-1.mp4` sai por cópia de fluxo, **sem reencode**, em menos de 30 s |
| AC5 | **`clipe-1.srt` importado no CapCut Web fica alinhado com a fala — verificado na tela** |
| AC6 | Acentuação portuguesa correta no CapCut Web (`transcrição`, `preço`) |
| AC7 | O SRT reflete um ajuste de corte feito depois, sem passo manual |
| AC8 | Nenhum passo do servidor passa de 300 s |
| AC9 | O modo MCP/Desktop continua passando os 246 testes existentes |

**AC5 é o único que prova o produto.** Os outros protegem as partes; só a tela do
CapCut confirma que a entrega serve. É a mesma lição do AC7 da spec anterior.

## 11. Fases

| Fase | Entrega | Termina com |
|---|---|---|
| **1** | **Validar R1 antes de construir**: gerar um SRT da fixture e importar no CapCut Web | evidência na tela, ou o desenho muda |
| 2 | Upload + preview local + projeto no Neon | AC1 |
| 3 | ASR por API + seleção pela LLM | AC2 |
| 4 | Tela de revisão: pontas, legendas, títulos | AC3, AC7 |
| 5 | Corte por cópia de fluxo + SRT derivado | AC4, AC6, AC8 |
| 6 | Entrega e passo a passo | **AC5** |

A Fase 1 é deliberadamente antes de tudo: se o import não aceitar o nosso SRT
como esperamos, as fases 2 a 6 mudam de forma. Custa uma sessão de teste e
protege o resto.
