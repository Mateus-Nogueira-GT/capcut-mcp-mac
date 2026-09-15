# Front local: chat + anexo de vídeo

```sh
uv pip install --python .venv/bin/python -r web/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
PYTHONPATH=src ./.venv/bin/python web/app.py     # http://127.0.0.1:5151
```

Anexe um vídeo, diga o que quer, e o projeto aparece no seu CapCut. A tela mostra
cada passo — qual tool rodou, o que ela devolveu, quanto tempo levou, e os avisos.

---

## Sobre o OAuth do CapCut: não é difícil, é impossível — e não resolveria

Isto foi pedido e merece resposta direta, porque muda o desenho do produto.

**Não existe OAuth do CapCut para colocar aqui.** A plataforma aberta deles é
para plugins que rodam **dentro** do editor; a API pública deles é de
texto-para-vídeo e de templates. Nenhuma das duas cria projeto na timeline nem dá
acesso de terceiro à conta de alguém.

**E se existisse, não ajudaria.** Este adaptador entrega um projeto **escrevendo
arquivos**:

```
~/Movies/CapCut/User Data/Projects/com.lveditor.draft/<projeto>/
```

Isso é o disco da máquina onde o CapCut Desktop roda. Um servidor web hospedado
não tem como escrever nessa pasta no Mac de outra pessoa — nenhum token muda essa
barreira. O que o OAuth resolveria é *identidade*, e o problema aqui é *acesso ao
disco*.

### O que substitui o OAuth

**O front roda na máquina de cada pessoa.** O "CapCut daquele usuário" é o CapCut
instalado ali, já logado por ele. A identidade vem da máquina, não de um token — e
o efeito prático é o mesmo que se pediu: cada um trabalha no seu CapCut, com os
seus projetos.

Ganhos de graça nesse desenho: o vídeo nunca sai da máquina, a transcrição roda
local, e não há cota nem upload.

O servidor escuta **só em `127.0.0.1`**, de propósito: ele escreve na pasta de
projetos do CapCut e executa o que a LLM pedir. Não exponha na rede.

### Se um dia precisar ser hospedado

O caminho seria um **companheiro local** — um processo pequeno no Mac de cada
pessoa, que o app hospedado aciona. É como integrações de desktop funcionam. Aí
sim entra login de verdade, mas do **seu** app (Google Workspace, por exemplo),
não do CapCut. É bem mais trabalho que este front, e para uso interno não se
paga.

---

## UI hospedada na Vercel: subiu, mas o Chrome barra

`https://capcut-front.vercel.app` está no ar e serve a mesma tela, com uma etapa
de pareamento. **Ela não conecta no motor local no Chrome padrão**, e isso foi
verificado, não suposto.

O que foi medido:

| | |
|---|---|
| Motor responde por `curl` com `Origin` da Vercel + token | `200`, com `Access-Control-Allow-Private-Network: true` |
| Página HTTPS chamando `http://127.0.0.1:5151` | **pendura até o timeout** |
| Página HTTPS chamando `http://localhost:5151` | **pendura até o timeout** |
| A requisição chega ao motor? | **não aparece no log dele** |
| Erro no console do navegador? | **nenhum** |

A causa é o **Local Network Access** do Chrome, ligado por padrão desde a versão
142 (out/2025): uma página de origem pública que chama um endereço de rede local
precisa de permissão explícita do usuário, e sem ela a requisição **falha em
silêncio** — sem erro de CORS, sem nada no console. O `Allow-Private-Network` que
o motor envia era o mecanismo *anterior* a esse modelo; ele não basta mais.

Testado no painel de preview (`ERR_BLOCKED_BY_CLIENT`) e no Chrome real do
usuário (pendura sem erro). O lado servidor está correto nos dois.

### O que fazer

1. **Use a interface local** (`http://127.0.0.1:5151`): mesma tela, mesmo código,
   sem pareamento e sem a restrição, porque é mesma origem. **É a recomendação.**
2. **Liberar por máquina**: `chrome://settings/content/localNetworkAccess`,
   autorizar `capcut-front.vercel.app`, e clicar em Conectar de novo. Num parque
   gerenciado, a política `LocalNetworkAccessAllowedForUrls` faz isso de uma vez.
3. **Inverter o sentido da conexão**, se o URL único for requisito de verdade: o
   motor local abre um WebSocket de saída para um relay hospedado, e o trabalho
   desce por ele. Não há chamada para `127.0.0.1` a partir da página, então o LNA
   não se aplica. É como túnel de desenvolvimento funciona — e é um serviço novo
   a construir e manter, não uma configuração.

A tela hospedada explica isso sozinha quando a conexão pendura, com o caminho da
configuração e o link para a versão local. O que ela não faz é fingir que
funcionou.

---

## Sobre os tokens: sim, gasta — e onde

**A transcrição é local e grátis.** whisper.cpp, nada sai da máquina, sem cobrança
por minuto. É justamente o que o Opus Clip cobra.

**A LLM é paga, e serve para uma coisa:** ler o transcript e **escolher** os
trechos, entendendo pedidos em linguagem natural ("ache onde ele fala de preço").
Medido neste projeto: ~4,9k tokens de schemas das 11 tools + ~0,6k do prompt de
sistema, repetidos em cada turno do loop, mais o transcript (~3,7 tokens por
segundo de vídeo).

Custo do fluxo inteiro por vídeo, com cache de prompt ligado (o front já liga):

| Duração | Opus 5 | Sonnet 5 | Haiku 4.5 |
|---|---|---|---|
| 5 min | $0,33 | $0,13 | $0,07 |
| 15 min | $0,35 | $0,14 | $0,07 |
| 30 min | $0,37 | $0,15 | $0,08 |
| 60 min | $0,43 | $0,17 | $0,09 |

O cache corta 40–56% da conta: o prefixo estável é o que mais repete. Para
calibrar: **100 vídeos de 30 min por mês ≈ $37 no Opus 5, $15 no Sonnet 5.**

Trocar o modelo é uma variável de ambiente:

```sh
CAPCUT_MODEL=claude-sonnet-5 PYTHONPATH=src ./.venv/bin/python web/app.py
```

A tela mostra o gasto real de cada conversa no pé da resposta, então não é preciso
confiar na tabela.

**Dá para gastar zero:** se você já sabe os tempos ("corte de 0 a 15 s e legende"),
a escolha não precisa de LLM. Aí o MCP server direto (`python -m
capcut_mcp.server`) faz o trabalho sem nenhuma chamada paga. A LLM ganha o
dinheiro quando o pedido é vago.

---

## Como está montado

```
navegador  ──SSE──>  web/app.py  ──>  src/capcut_mcp/tools.py  ──>  disco
   chat               loop de              as mesmas 11 tools       projeto
   anexo              tool use             do servidor MCP          do CapCut
```

- **Loop de agente manual**, não o `tool_runner` do SDK: as tools vêm de um
  registro dinâmico e cada chamada precisa virar um evento na tela. O loop
  explícito é o que encaixa; tem teto de 24 passos para um erro repetido não
  girar para sempre.
- **Nomes traduzidos**: as tools do MCP têm ponto (`capcut.video.cut`), que a
  Messages API não aceita, então viram `capcut_video_cut` e voltam.
- **Cache de prompt** num breakpoint só, no fim do bloco de tools — cobre tools +
  system, que é o que repete.
- **`strict: true`** em todas: os schemas já são `additionalProperties: false`.
- **Validação em duas camadas**: o front roda a mesma validação de schema do
  servidor MCP antes de chamar o handler. Sem ela, parâmetro ausente virava
  `KeyError` e a LLM não recebia a `suggestion` para se corrigir.
- **Dependências separadas**: `web/requirements.txt` acrescenta o `anthropic`. O
  adaptador (`src/capcut_mcp`) continua nas 6 dependências do L0 e não importa
  nada daqui.

## O que este front não faz

- Não renderiza vídeo. Entrega projeto editável; exportar é no CapCut.
- Não tem login nem multiusuário — é local, por máquina.
- Não recarrega o CapCut. Depois de salvar, volte à página inicial do app para
  ele reler o disco.
