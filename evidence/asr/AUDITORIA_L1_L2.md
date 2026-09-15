# Auditoria de L1 (ASR) e L2 (seleção de cortes)

Feita depois do merge, procurando inconsistência de propósito. Método: formular
hipóteses falsificáveis e testar cada uma, em vez de reler o código à procura do
que confirma. Seis achados, todos reproduzidos com evidência e corrigidos. Cinco vieram das
hipóteses; o sexto — e um dos dois mais graves — apareceu por acidente, ao mover
as fixtures de pasta.

---

## A — o `snap` cruzava dois trechos de `keep` · **o único com defeito visível**

**Hipótese:** a checagem de sobreposição roda *antes* do snap, então o snap pode
passar por cima dela.

**Reproduzido.** `keep=[[1.0, 3.2], [3.3, 6.0]]` com `snap="speech"`:

```
aplicado: [[1.15, 3.43], [3.15, 6.03]]
           o primeiro termina em 3.43, o segundo começa em 3.15
```

O fim do primeiro trecho avançou para a fronteira de palavra seguinte enquanto o
início do segundo recuou para a anterior. Os dois se cruzaram.

**Dano medido, não suposto:**

| Consequência | Medição |
|---|---|
| Mídia duplicada | `origem 3.150-3.430` (**0,280 s**) aparece **duas vezes** na timeline — gagueira audível |
| Mapa de tempo ambíguo | o instante `3.290 s` da origem tem **dois** destinos na timeline (`2.14` e `2.42`); `map_instant` devolve só o primeiro, então a segunda cópia toca a fala **sem legenda** |
| Ninguém avisa | avisos do cut: só `CUT_SNAPPED_TO_SPEECH`. `validate`: **0 erros, 0 avisos, 0 informativos** |

**Correção:** cada ponta só pode andar até a **metade do vão** que a separa do
trecho vizinho (e, na última, até o fim da mídia). Como os trechos pedidos nunca
se sobrepõem, o ponto médio é uma barreira que garante não-sobreposição sem
depender de caso. Aviso novo `SNAP_LIMITED_BY_NEIGHBOUR` quando a contenção
atua, porque conter em silêncio esconderia que as pontas não ficaram na fala. E
uma asserção de invariante levanta `INTERNAL_ERROR` se algum dia cruzar de novo.

Depois: `[[1.15, 3.25], [3.25, 6.03]]` — os trechos se encontram exatamente em
3,25, o meio do vão original. **0,000 s duplicados.**

---

## B — `delta_end_s` não descrevia o que foi aplicado

**Reproduzido.** Pedindo `keep=[[13.0, 18.767]]` (a duração exata da mídia), o
padding de 0,15 s empurra além do fim. O valor aplicado era clampado, o delta
reportado não:

```
applied[1]     = 18.767
pedido + delta = 18.917   <- instante que não existe na mídia
```

**Correção:** os deltas passam a ser derivados dos valores finais, depois de todo
clamp. Severidade baixa — o corte estava certo, só o relatório mentia — mas quem
confia no delta para calcular erra.

---

## C — a fusão de blocos estourava o `max_chars` prometido

**Hipótese:** o `-ml N` do binário limita o que *ele* emite, mas o
`_shape_blocks` funde blocos curtos **depois** e não reconferia o comprimento.

**Reproduzido.** Com `max_chars=16`, um bloco de **33 caracteres** — o dobro do
pedido.

**Correção:** a fusão agora exige que o texto resultante caiba no limite.

**Mas a auditoria achou uma segunda causa, e essa não tem correção:** o
`-ml` do whisper.cpp é limite **aproximado**, não duro — ele não parte palavra,
então um bloco estoura quando a próxima palavra não cabe. Depois da correção:

| `max_chars` | maior bloco | excesso |
|---|---|---|
| 16 | 20 | 25% |
| 20 | 20 | 0% |
| **26** (default) | 26 | **0%** |
| 32 | 33 | 3% |
| 40 | 45 | 12% |
| 60 | 48 | 0% |

O resíduo é do binário. Duas decisões:

1. **A descrição do parâmetro passou a dizer que é alvo, não teto**, com o
   excesso medido. Prometer um teto que a ferramenta não entrega seria pior que o
   excesso.
2. **A tela está protegida de qualquer forma:** o `subtitle.add` quebra em limite
   de palavra depois (26 caracteres por linha no font_size 8), então um bloco
   acima do alvo vira duas linhas em vez de transbordar. Verificado: 5 blocos
   quebrados, com `SUBTITLE_WRAPPED` avisando.

---

## D / E — a escolha de transcrição em cache era arbitrária

**Hipótese:** a chave do cache inclui modelo, idioma e `max_chars`, mas a busca
por caminho de arquivo (`find_cached_by_source`, usada pelo `snap` e pelo
`from_transcript`) ignorava os três.

**Reproduzido.** Sete transcrições da mesma mídia em cache:

```
modelo=small max_chars=16 blocos=13
modelo=small max_chars=20 blocos=13
modelo=small max_chars=26 blocos=10   <- o que o fluxo do AC7 usou
modelo=small max_chars=32 blocos=9
modelo=small max_chars=40 blocos=6
modelo=small max_chars=60 blocos=5

find_cached_by_source escolheu: max_chars=40, blocos=6
```

Todas têm o mesmo modelo, então o desempate por "modelo mais forte" não decidia
nada: vencia a ordem do `os.listdir`, que é do sistema de arquivos.

**Por que importa:** para o `snap` é inofensivo — as palavras são as mesmas em
qualquer moldagem. Para as legendas **muda o que aparece na tela**, e muda de
máquina para máquina. O AC7 passou com a moldagem certa por sorte do que havia
no cache naquele momento.

**Correção em três partes:**

- `cached_for_source()` devolve tudo em ordem **determinística** (modelo mais
  forte, e entre iguais o mais recente);
- `find_cached_by_source(source, max_chars=..., transcript_id=...)` prefere a
  moldagem pedida e aceita fixar exatamente uma;
- o `from_transcript` **declara** no resultado qual usou (`transcript_model`,
  `transcript_max_chars`, `transcript_id`), aceita `transcript_id` e
  `max_chars_per_block`, e avisa `TRANSCRIPT_AMBIGUOUS` quando há mais de uma.

O `D` original — `language="auto"` e `"pt"` gerando entradas separadas — deixa de
ter consequência: a busca é determinística e a preferência é explícita. O custo
que resta é uma transcrição repetida quando se alterna entre `auto` e explícito,
o que é desperdício de tempo, não erro de resultado.

---

## F — o cache era endereçado por conteúdo e buscado por caminho

**Não era hipótese: apareceu sozinho** ao mover as fixtures para dentro do repo,
que é exatamente o caso real.

O `transcript_id` é formado a partir do **fingerprint do conteúdo**. Já o
`find_cached_by_source` comparava o **caminho absoluto**. Consequência, medida:

```
transcribe(caminho novo)     -> cached = true    (acertou por conteúdo)
find_cached_by_source(idem)  -> None             (errou por caminho)
require_cached(idem)         -> TRANSCRIPT_NOT_FOUND
```

Quem acabou de transcrever com sucesso ouvia do passo seguinte que não há
transcrição. Dispara ao mover ou renomear o arquivo, ter uma cópia em outra
pasta, usar symlink, ou alcançar a mídia por outro ponto de montagem.

**Correção:** a busca passou a casar por **fingerprint**, com o caminho como
alternativa. O registro guarda o `fingerprint`, e um acerto de cache reancora o
`source` no caminho usado agora — registros antigos, sem o campo, são migrados
na primeira leitura. Os dois caminhos passam a encontrar a mesma transcrição.

Este foi o achado mais barato de todos: não custou análise, custou mover um
arquivo. Vale como lição sobre onde procurar — o fluxo real, não o código.

---

## Resultado

| Achado | Severidade | Situação |
|---|---|---|
| A — snap cruza trechos, duplica mídia, ninguém avisa | **alta** | corrigido + invariante + aviso |
| B — delta não descreve o aplicado | baixa | corrigido |
| C — fusão estoura `max_chars` | média | corrigido; resíduo do binário declarado |
| D — cache duplicado por idioma | baixa | sem consequência após E |
| E — escolha de transcrição arbitrária | média | corrigido + declarado + fixável |
| F — cache por conteúdo, busca por caminho | **alta** | corrigido + migração de registros antigos |

**11 testes de regressão novos**, cada um citando a medição que o motivou.
Suíte: **192 testes, 192 passando.**

### O que a auditoria não cobriu

- Nenhuma nova verificação **na tela**: as correções são de aritmética e de
  contrato, e o AC7 visual continua valendo (o `AC7 Sync` foi regravado depois da
  correção da borda, não depois destas). Se alguma dessas correções mudasse o que
  aparece, seria a de `max_chars` — e ela só torna os blocos mais curtos.
- `medium` continua não medido.
