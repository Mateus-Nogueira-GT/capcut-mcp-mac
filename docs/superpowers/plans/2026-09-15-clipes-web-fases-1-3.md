# Clipes Web — Fases 1 a 3 · Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pessoa sobe uma gravação longa num app web, a IA aponta os highlights com minutagem e justificativa, e ela baixa os clipes curtos já cortados — sem instalar nada.

**Architecture:** App Flask único na Vercel (o mesmo padrão que já roda em `vercel-ui/api/index.py`), Neon para estado, Vercel Blob para a mídia. O preview toca o arquivo **local** no navegador, então ajustar nada custa servidor. O corte é `ffmpeg -c copy` — cópia de bytes, sem reencode — com o binário estático dentro do bundle. Nenhum passo passa de 300 s.

**Tech Stack:** Python 3.12 · Flask · psycopg 3 (Neon) · Vercel Blob (upload do cliente) · ffmpeg estático linux-x64 · API de ASR (escolhida por medição na Task 5) · Anthropic `claude-opus-5` para a seleção

**Spec:** [`docs/superpowers/specs/2026-09-15-clipes-web-design.md`](../specs/2026-09-15-clipes-web-design.md)

## Global Constraints

- **Plano Hobby da Vercel: teto de 300 s por função, sem extensão.** Nenhum passo pode se aproximar disso. Bundle Python: 500 MB.
- **Não renderizamos vídeo.** Sem reencode, sem legenda queimada, sem pixel novo. Apenas `-c copy`.
- **O SRT é derivado, nunca armazenado** (§5.1 da spec). Não criar coluna nem arquivo de SRT persistido.
- **Medir, não supor.** Todo valor que vem do mundo (duração, offset de keyframe, custo de ASR) é lido, não assumido. É a regra que pegou os 8 achados da auditoria desta base.
- **Erro tem código, mensagem e sugestão.** Nunca falhar em silêncio — o padrão de `src/capcut_mcp/errors.py`.
- **Texto de interface em português**, com acentuação correta. UTF-8 em tudo.
- **Os 246 testes existentes continuam passando.** Nada em `src/capcut_mcp/` que sirva ao modo MCP/Desktop é removido neste plano.
- **Reaproveitar, não reescrever:** `media.py` (198 linhas), `timemap.py` (155), `subtitles.py` (261) são importados, não copiados.

---

## File Structure

Novo diretório `clipes/`, projeto Vercel próprio. O `vercel-ui/` (relay) e o `src/capcut_mcp/` (MCP/Desktop) ficam intactos.

| Arquivo | Responsabilidade |
|---|---|
| `clipes/api/index.py` | app Flask: rotas HTTP, autenticação, nada de lógica de domínio |
| `clipes/api/banco.py` | esquema e acesso ao Neon. Único lugar com SQL. |
| `clipes/api/projeto.py` | o modelo de projeto e clipe: criar, ler, atualizar a decisão |
| `clipes/api/asr.py` | cliente da API de ASR e normalização para blocos/palavras |
| `clipes/api/selecao.py` | monta o prompt, chama a LLM, valida o que ela devolveu |
| `clipes/api/corte.py` | `ffmpeg -c copy` e medição do início real |
| `clipes/api/blob.js` | **único arquivo JS**: emite o token de upload do cliente |
| `clipes/bin/ffmpeg` | binário estático linux-x64 (baixado no build) |
| `clipes/static/index.html` | tela: upload, preview local, highlights, download |
| `clipes/requirements.txt` | flask, psycopg[binary], anthropic, requests |
| `clipes/vercel.json` | rotas e `maxDuration` por função |
| `tests/clipes/test_*.py` | testes, no mesmo `pytest` da suíte existente |

Por que `blob.js` existe: o upload direto do navegador para o Blob precisa de um token de curta duração, e a geração dele só é publicada no SDK JavaScript da Vercel. Passar o `BLOB_READ_WRITE_TOKEN` para o navegador seria expor a credencial. Um arquivo de ~20 linhas em TS resolve; todo o resto segue Python.

---

## Fase 1 — Upload, preview e projeto

### Task 1: Esquema no Neon

**Files:**
- Create: `clipes/api/banco.py`
- Test: `tests/clipes/test_banco.py`

**Interfaces:**
- Consumes: nada
- Produces: `conexao() -> psycopg.Connection`, `garante_esquema(cur) -> None`, `ESQUEMA: str`

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_banco.py
import os, sys
import pytest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))

import banco


def test_esquema_e_idempotente_e_cria_as_tabelas():
    """Roda duas vezes: a segunda não pode falhar nem duplicar."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL não definida")
    with banco.conexao() as con, con.cursor() as cur:
        banco.garante_esquema(cur)
        banco._pronto = False          # força o segundo passe
        banco.garante_esquema(cur)
        cur.execute("""
            select table_name from information_schema.tables
            where table_schema = 'clipes' order by table_name""")
        assert [r[0] for r in cur.fetchall()] == ["clipes", "projetos"]


def test_esquema_sem_database_url_da_erro_acionavel(monkeypatch):
    monkeypatch.setattr(banco, "DB", "")
    with pytest.raises(RuntimeError) as exc:
        banco.conexao()
    assert "DATABASE_URL" in str(exc.value)
    assert "Storage" in str(exc.value), "o erro tem de dizer como corrigir"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_banco.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'banco'`

- [ ] **Step 3: Write minimal implementation**

```python
# clipes/api/banco.py
"""Acesso ao Neon. Único lugar deste projeto com SQL.

O esquema é criado na primeira requisição, de forma idempotente — não há passo
de migração para esquecer. Vive no schema `clipes` para poder compartilhar o
mesmo Neon com outros projetos sem colidir.
"""
from __future__ import annotations

import os
import psycopg

DB = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""

ESQUEMA = """
create schema if not exists clipes;

create table if not exists clipes.projetos (
  id          text primary key,
  nome        text not null,
  criado_em   timestamptz not null default now(),
  fonte       jsonb not null default '{}'::jsonb,
  transcript  jsonb,
  estado      text not null default 'novo'
);

create table if not exists clipes.clipes (
  id            text primary key,
  projeto_id    text not null references clipes.projetos(id) on delete cascade,
  ordem         int not null,
  titulo_curto  text not null default '',
  justificativa text not null default '',
  trechos       jsonb not null default '[]'::jsonb,
  textos        jsonb not null default '[]'::jsonb,
  estilo        jsonb not null default '{}'::jsonb,
  saida         jsonb,
  descartado    boolean not null default false
);

create index if not exists clipes_do_projeto
  on clipes.clipes (projeto_id, ordem);
"""

_pronto = False


def conexao() -> psycopg.Connection:
    if not DB:
        raise RuntimeError(
            "DATABASE_URL não está definida. Conecte o store Neon ao projeto "
            "no painel da Vercel (Storage -> Connect Project) e refaça o deploy."
        )
    return psycopg.connect(DB, autocommit=True)


def garante_esquema(cur) -> None:
    global _pronto
    if _pronto:
        return
    cur.execute(ESQUEMA)
    _pronto = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_banco.py -v`
Expected: PASS (o primeiro teste pula sem `DATABASE_URL`; rode com `DATABASE_URL=$(...)` para exercitá-lo)

- [ ] **Step 5: Commit**

```bash
git add clipes/api/banco.py tests/clipes/test_banco.py
git commit -m "feat(clipes): esquema no Neon, idempotente, em schema próprio"
```

---

### Task 2: Projeto — criar e ler

**Files:**
- Create: `clipes/api/projeto.py`
- Test: `tests/clipes/test_projeto.py`

**Interfaces:**
- Consumes: `banco.conexao`, `banco.garante_esquema`
- Produces: `cria(nome: str, fonte: dict) -> str` (devolve id), `le(id: str) -> dict | None`, `atualiza_transcript(id: str, transcript: dict) -> None`, `novo_id() -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_projeto.py
import os, sys
import pytest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))

import projeto

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                                reason="DATABASE_URL não definida")

FONTE = {"nome": "reuniao.mp4", "bytes": 1024, "duracao_s": 1800.0,
         "largura": 1920, "altura": 1080, "blob_url": "https://x/y.mp4"}


def test_cria_e_le():
    pid = projeto.cria("Reunião de terça", FONTE)
    d = projeto.le(pid)
    assert d["nome"] == "Reunião de terça"
    assert d["fonte"]["duracao_s"] == 1800.0
    assert d["estado"] == "novo"
    assert d["transcript"] is None
    assert d["clipes"] == []


def test_le_inexistente_devolve_none():
    assert projeto.le("nao-existe") is None


def test_id_nao_e_sequencial():
    """Id sequencial deixaria qualquer pessoa adivinhar o projeto de outra."""
    ids = {projeto.novo_id() for _ in range(20)}
    assert len(ids) == 20
    assert all(len(i) >= 16 for i in ids)


def test_atualiza_transcript_preserva_o_resto():
    pid = projeto.cria("x", FONTE)
    projeto.atualiza_transcript(pid, {"blocos": [{"start": 0, "end": 1,
                                                  "text": "oi"}], "palavras": []})
    d = projeto.le(pid)
    assert d["transcript"]["blocos"][0]["text"] == "oi"
    assert d["fonte"]["nome"] == "reuniao.mp4", "a fonte não pode ser perdida"
    assert d["estado"] == "transcrito"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=$DATABASE_URL PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_projeto.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'projeto'`

- [ ] **Step 3: Write minimal implementation**

```python
# clipes/api/projeto.py
"""O modelo de projeto e clipe.

`le()` devolve o projeto com os clipes embutidos, porque toda tela precisa dos
dois juntos e duas idas ao banco por render seria desperdício numa função
serverless.
"""
from __future__ import annotations

import json
import secrets
from typing import Any, Dict, List, Optional

import banco


def novo_id() -> str:
    # aleatório, não sequencial: id adivinhável exporia projeto de terceiro
    return secrets.token_urlsafe(12)


def cria(nome: str, fonte: Dict[str, Any]) -> str:
    pid = novo_id()
    with banco.conexao() as con, con.cursor() as cur:
        banco.garante_esquema(cur)
        cur.execute(
            "insert into clipes.projetos (id, nome, fonte) values (%s, %s, %s)",
            (pid, nome[:200], json.dumps(fonte)))
    return pid


def le(pid: str) -> Optional[Dict[str, Any]]:
    with banco.conexao() as con, con.cursor() as cur:
        banco.garante_esquema(cur)
        cur.execute(
            "select id, nome, criado_em, fonte, transcript, estado"
            " from clipes.projetos where id = %s", (pid,))
        linha = cur.fetchone()
        if linha is None:
            return None
        cur.execute(
            "select id, ordem, titulo_curto, justificativa, trechos, textos,"
            " estilo, saida, descartado from clipes.clipes"
            " where projeto_id = %s order by ordem", (pid,))
        clipes = [{"id": c[0], "ordem": c[1], "titulo_curto": c[2],
                   "justificativa": c[3], "trechos": c[4], "textos": c[5],
                   "estilo": c[6], "saida": c[7], "descartado": c[8]}
                  for c in cur.fetchall()]
    return {"id": linha[0], "nome": linha[1], "criado_em": linha[2].isoformat(),
            "fonte": linha[3], "transcript": linha[4], "estado": linha[5],
            "clipes": clipes}


def atualiza_transcript(pid: str, transcript: Dict[str, Any]) -> None:
    with banco.conexao() as con, con.cursor() as cur:
        banco.garante_esquema(cur)
        cur.execute(
            "update clipes.projetos set transcript = %s, estado = 'transcrito'"
            " where id = %s", (json.dumps(transcript), pid))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=$DATABASE_URL PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_projeto.py -v`
Expected: PASS, 4 testes

- [ ] **Step 5: Commit**

```bash
git add clipes/api/projeto.py tests/clipes/test_projeto.py
git commit -m "feat(clipes): modelo de projeto, com id aleatório e clipes embutidos"
```

---

### Task 3: App Flask, autenticação e token do Blob

**Files:**
- Create: `clipes/api/index.py`, `clipes/api/blob.js`, `clipes/requirements.txt`, `clipes/vercel.json`, `clipes/package.json`
- Test: `tests/clipes/test_http.py`

**Interfaces:**
- Consumes: `projeto.cria`, `projeto.le`
- Produces: rotas `GET /api/saude`, `POST /api/projeto`, `GET /api/projeto/<id>`; helper `exige_codigo() -> tuple | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_http.py
import os, sys
import pytest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))

import index


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(index, "UI_CODE", "segredo-de-teste")
    index.app.config["TESTING"] = True
    return index.app.test_client()


def test_saude_nao_exige_codigo(cliente):
    d = cliente.get("/api/saude").get_json()
    assert d["app"] is True
    assert "banco" in d and "blob" in d


def test_criar_projeto_sem_codigo_e_401(cliente):
    r = cliente.post("/api/projeto", json={"nome": "x", "fonte": {}})
    assert r.status_code == 401
    assert r.get_json()["precisa_codigo"] is True


def test_criar_projeto_com_codigo_errado_e_401(cliente):
    r = cliente.post("/api/projeto", json={"nome": "x"},
                     headers={"X-UI-Code": "chute"})
    assert r.status_code == 401


def test_sem_ui_code_configurada_recusa_em_vez_de_liberar(cliente, monkeypatch):
    """Falha fechado: sem código configurado, ninguém entra."""
    monkeypatch.setattr(index, "UI_CODE", "")
    r = cliente.post("/api/projeto", json={"nome": "x"},
                     headers={"X-UI-Code": ""})
    assert r.status_code == 503
    assert "CAPCUT_UI_CODE" in r.get_json()["erro"]


def test_fonte_sem_duracao_e_recusada(cliente):
    r = cliente.post("/api/projeto",
                     json={"nome": "x", "fonte": {"nome": "a.mp4"}},
                     headers={"X-UI-Code": "segredo-de-teste"})
    assert r.status_code == 400
    assert "duracao_s" in r.get_json()["erro"]


def test_fonte_sem_audio_e_recusada(cliente):
    r = cliente.post("/api/projeto", json={"nome": "x", "fonte": {
        "nome": "a.mp4", "duracao_s": 10.0, "tem_audio": False}},
        headers={"X-UI-Code": "segredo-de-teste"})
    assert r.status_code == 400
    assert "áudio" in r.get_json()["erro"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_http.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'index'`

- [ ] **Step 3: Write minimal implementation**

```python
# clipes/api/index.py
"""Rotas HTTP. Sem lógica de domínio — isso vive nos outros módulos.

Autenticação: um código interno em `CAPCUT_UI_CODE`. Sem ele configurado o app
RECUSA em vez de liberar — falhar fechado, porque este endpoint cria trabalho
que consome API paga.
"""
from __future__ import annotations

import hmac
import os

from flask import Flask, jsonify, request, send_from_directory

import banco
import projeto

app = Flask(__name__, static_folder="../static", static_url_path="")

UI_CODE = os.environ.get("CAPCUT_UI_CODE", "")


def erro(msg: str, codigo: int = 400, **extra):
    return jsonify({"erro": msg, **extra}), codigo


def exige_codigo():
    if not UI_CODE:
        return erro("CAPCUT_UI_CODE não está configurada no projeto. Sem ela "
                    "qualquer pessoa consumiria a API paga.", 503)
    if not hmac.compare_digest(request.headers.get("X-UI-Code", ""), UI_CODE):
        return erro("Código de acesso inválido.", 401, precisa_codigo=True)
    return None


@app.errorhandler(Exception)
def qualquer_erro(exc):
    if isinstance(exc, RuntimeError) and "DATABASE_URL" in str(exc):
        return erro(str(exc), 503, configuracao_faltando="DATABASE_URL")
    codigo = getattr(exc, "code", 500)
    if isinstance(codigo, int) and 400 <= codigo < 500:
        return erro(str(exc), codigo)
    return erro(f"{type(exc).__name__}: {exc}"[:400], 500)


@app.get("/api/saude")
def saude():
    fora = {"app": True, "banco": False,
            "blob": bool(os.environ.get("BLOB_READ_WRITE_TOKEN")),
            "ui_code": bool(UI_CODE)}
    try:
        with banco.conexao() as con, con.cursor() as cur:
            banco.garante_esquema(cur)
            fora["banco"] = True
    except Exception as exc:
        fora["erro_banco"] = f"{type(exc).__name__}: {exc}"[:200]
    return jsonify(fora)


@app.post("/api/projeto")
def cria_projeto():
    barrado = exige_codigo()
    if barrado:
        return barrado
    corpo = request.get_json(silent=True) or {}
    fonte = corpo.get("fonte") or {}
    if not fonte.get("duracao_s"):
        return erro("A fonte precisa de 'duracao_s' — sem duração real não dá "
                    "para calcular corte nenhum.")
    if fonte.get("tem_audio") is False:
        return erro("Este arquivo não tem faixa de áudio, então não há fala "
                    "para transcrever nem highlight para achar.")
    pid = projeto.cria(corpo.get("nome") or fonte.get("nome") or "sem nome", fonte)
    return jsonify({"projeto_id": pid})


@app.get("/api/projeto/<pid>")
def le_projeto(pid: str):
    barrado = exige_codigo()
    if barrado:
        return barrado
    d = projeto.le(pid)
    if d is None:
        return erro("Projeto não encontrado.", 404)
    return jsonify(d)


@app.get("/")
def raiz():
    return send_from_directory(app.static_folder, "index.html")
```

```javascript
// clipes/api/blob.js
// ÚNICO arquivo JS do projeto. Existe porque o upload direto do navegador para
// o Vercel Blob precisa de um token de curta duração, e a geração dele só é
// publicada no SDK JavaScript. Passar o BLOB_READ_WRITE_TOKEN para o navegador
// exporia a credencial.
import { handleUpload } from '@vercel/blob/client'

export const config = { runtime: 'nodejs' }

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ erro: 'Use POST.' })
  if (req.headers['x-ui-code'] !== process.env.CAPCUT_UI_CODE) {
    return res.status(401).json({ erro: 'Código de acesso inválido.' })
  }
  try {
    const resposta = await handleUpload({
      request: req,
      body: req.body,
      onBeforeGenerateToken: async () => ({
        allowedContentTypes: ['video/mp4', 'video/quicktime', 'video/x-m4v',
                              'video/webm', 'audio/mpeg', 'audio/wav'],
        maximumSizeInBytes: 2 * 1024 * 1024 * 1024,
        addRandomSuffix: true,
      }),
      onUploadCompleted: async () => {},
    })
    return res.status(200).json(resposta)
  } catch (e) {
    return res.status(400).json({ erro: String(e?.message || e) })
  }
}
```

```json
// clipes/package.json
{
  "name": "clipes-blob",
  "private": true,
  "type": "module",
  "dependencies": { "@vercel/blob": "^0.27.0" }
}
```

```
# clipes/requirements.txt
flask>=3.0
psycopg[binary]>=3.2
anthropic>=0.40
requests>=2.32
```

```json
// clipes/vercel.json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": {
    "api/index.py": { "maxDuration": 290 }
  },
  "rewrites": [
    { "source": "/api/blob", "destination": "/api/blob" },
    { "source": "/api/(.*)", "destination": "/api/index" },
    { "source": "/", "destination": "/static/index.html" }
  ],
  "headers": [
    { "source": "/(.*)", "headers": [
      { "key": "X-Content-Type-Options", "value": "nosniff" },
      { "key": "Referrer-Policy", "value": "no-referrer" },
      { "key": "X-Frame-Options", "value": "DENY" }
    ]}
  ]
}
```

`maxDuration: 290` e não 300: deixa margem para o handler responder antes do corte duro do plano Hobby, em vez de morrer com `504` sem mensagem.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_http.py -v`
Expected: PASS, 6 testes

- [ ] **Step 5: Commit**

```bash
git add clipes/ tests/clipes/test_http.py
git commit -m "feat(clipes): app Flask com portaria que falha fechado, e token do Blob"
```

---

### Task 4: Tela de upload com preview local

**Files:**
- Create: `clipes/static/index.html`
- Test: `tests/clipes/test_tela.py`

**Interfaces:**
- Consumes: `POST /api/projeto`, `POST /api/blob`
- Produces: nada para outras tasks (é a ponta)

O preview usa `URL.createObjectURL(arquivo)` — o vídeo toca do disco da pessoa, sem esperar upload. A duração e as dimensões saem do próprio elemento `<video>`, então `duracao_s` é **medida**, não pedida ao usuário.

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_tela.py
import os

TELA = os.path.join(os.path.dirname(__file__), "..", "..",
                    "clipes", "static", "index.html")


def corpo():
    with open(TELA, encoding="utf-8") as f:
        return f.read()


def test_preview_usa_o_arquivo_local():
    """O vídeo não pode esperar o upload para tocar."""
    assert "createObjectURL" in corpo()


def test_duracao_e_medida_do_elemento_video():
    c = corpo()
    assert "loadedmetadata" in c
    assert "videoWidth" in c and "duration" in c


def test_upload_vai_direto_para_o_blob():
    """Se passar pela nossa API, estoura o limite de 4,5 MB de corpo."""
    c = corpo()
    assert "upload" in c and "/api/blob" in c
    assert "@vercel/blob" in c or "vercel-blob" in c or "blob" in c.lower()


def test_tela_avisa_quando_falta_configuracao():
    assert "/api/saude" in corpo()


def test_texto_em_portugues_com_acento():
    c = corpo()
    for palavra in ("gravação", "Código", "duração"):
        assert palavra in c, f"falta {palavra!r} — a interface é em português"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_tela.py -v`
Expected: FAIL com `FileNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Criar `clipes/static/index.html` com: campo de código (guardado em `localStorage`), seletor de arquivo com arrastar-e-soltar, `<video>` com `createObjectURL`, leitura de `duration`/`videoWidth`/`videoHeight` no evento `loadedmetadata`, upload pelo `upload()` do `@vercel/blob/client` via CDN apontando para `/api/blob`, e `POST /api/projeto` com a fonte medida. Paleta e tokens de cor iguais aos de `vercel-ui/static/index.html`, para as duas telas parecerem o mesmo produto.

O trecho que mede a fonte, que é a parte que os testes exigem:

```javascript
const video = document.querySelector("#preview");
video.src = URL.createObjectURL(arquivo);
video.addEventListener("loadedmetadata", () => {
  fonte = {
    nome: arquivo.name,
    bytes: arquivo.size,
    duracao_s: video.duration,          // MEDIDO, não informado
    largura: video.videoWidth,
    altura: video.videoHeight,
    tem_audio: null,                    // o navegador não expõe; o servidor confere
  };
  document.querySelector("#resumo").textContent =
    `${fonte.duracao_s.toFixed(0)} s · ${fonte.largura}×${fonte.altura}`;
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_tela.py -v`
Expected: PASS, 5 testes

- [ ] **Step 5: Verificar na tela**

```bash
cd clipes && vercel deploy --prod --yes
```

Abrir o URL, entrar com o código, escolher um arquivo. Confirmar: o vídeo toca **antes** do upload terminar, e o resumo mostra duração e dimensões reais. **Este é o AC1.**

- [ ] **Step 6: Commit**

```bash
git add clipes/static/index.html tests/clipes/test_tela.py
git commit -m "feat(clipes): upload com preview local e fonte medida no navegador"
```

---

## Fase 2 — Transcrição e seleção com insights

### Task 5: Escolher a API de ASR por medição

**Files:**
- Create: `docs/superpowers/plans/evidencia/asr-comparacao.md`
- Test: nenhum — é uma medição, e o produto dela é a decisão registrada

Esta task existe porque a spec (§9.2) deixou o fornecedor em aberto de propósito, com critérios. Escolher por reputação repetiria o erro que esta sessão cometeu várias vezes.

- [ ] **Step 1: Transcrever a fixture em dois fornecedores**

Usar `fixtures/fala_pt.wav` (16,72 s, PT-BR, texto conhecido em `fixtures/fala_pt.txt`). Candidatos que atendem o critério eliminatório de **timestamp por palavra**: Deepgram e AssemblyAI. Rodar os dois.

- [ ] **Step 2: Preencher a tabela de comparação**

```markdown
| Critério | Deepgram | AssemblyAI | whisper small (referência local) |
|---|---|---|---|
| Timestamp por palavra | | | sim |
| Pontuação de frase em PT | | | sim |
| Palavras corretas de 38 | | | 37 (erra "prazo") |
| Tempo de resposta | | | 2,04 s |
| Custo por minuto de áudio | | | zero, mas CPU |
| Aceita URL (o Blob já tem o arquivo) | | | n/a |
```

- [ ] **Step 3: Registrar a decisão com o motivo**

Escrever no documento qual foi escolhido e por quê, em uma frase. Critério eliminatório: sem timestamp por palavra, o `snap` para fronteira de fala não funciona.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/evidencia/asr-comparacao.md
git commit -m "docs(clipes): escolha da API de ASR, medida contra a fixture"
```

---

### Task 6: Cliente de ASR e normalização

**Files:**
- Create: `clipes/api/asr.py`
- Modify: `clipes/api/index.py` (rota `POST /api/projeto/<id>/transcrever`)
- Test: `tests/clipes/test_asr.py`

**Interfaces:**
- Consumes: `projeto.le`, `projeto.atualiza_transcript`
- Produces: `transcreve(blob_url: str, idioma: str = "pt") -> dict` devolvendo `{"blocos": [{"start", "end", "text"}], "palavras": [{"start", "end", "word"}], "idioma", "modelo"}`

O formato de saída é **o mesmo** de `src/capcut_mcp/asr.py`, para `timemap` e `subtitles` funcionarem sem adaptador.

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_asr.py
import json, os, sys
import pytest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))
sys.path.insert(0, os.path.join(REPO, "src"))

import asr as asr_web

RESPOSTA_CRUA = {  # forma reduzida do que o fornecedor devolve
    "results": {"channels": [{"alternatives": [{
        "transcript": "Bem-vindo ao teste de transcrição automática.",
        "words": [
            {"word": "Bem-vindo", "start": 0.02, "end": 0.55},
            {"word": "ao", "start": 0.60, "end": 0.72},
            {"word": "teste", "start": 0.78, "end": 1.10},
            {"word": "de", "start": 1.15, "end": 1.24},
            {"word": "transcrição", "start": 1.30, "end": 1.95},
            {"word": "automática.", "start": 2.00, "end": 2.60},
        ]}]}]}
}


def test_normaliza_para_o_formato_do_projeto():
    d = asr_web.normaliza(RESPOSTA_CRUA, max_chars=26)
    assert set(d) >= {"blocos", "palavras", "idioma", "modelo"}
    assert d["palavras"][0] == {"start": 0.02, "end": 0.55, "word": "Bem-vindo"}
    for b in d["blocos"]:
        assert b["end"] > b["start"]
        assert len(b["text"]) <= 26, f"bloco acima do teto: {b['text']!r}"


def test_blocos_saem_em_ordem_e_sem_sobreposicao():
    d = asr_web.normaliza(RESPOSTA_CRUA, max_chars=26)
    for a, b in zip(d["blocos"], d["blocos"][1:]):
        assert b["start"] >= a["end"] - 1e-6


def test_formato_bate_com_o_asr_local():
    """timemap e subtitles consomem os dois; divergir aqui quebra os dois."""
    d = asr_web.normaliza(RESPOSTA_CRUA, max_chars=26)
    assert set(d["blocos"][0]) == {"start", "end", "text", "index"}
    assert set(d["palavras"][0]) == {"start", "end", "word"}


def test_resposta_sem_palavras_da_erro_acionavel():
    with pytest.raises(asr_web.ErroASR) as exc:
        asr_web.normaliza({"results": {"channels": [{"alternatives": [{}]}]}},
                          max_chars=26)
    assert "timestamp por palavra" in str(exc.value)


def test_resposta_vazia_e_no_speech():
    with pytest.raises(asr_web.ErroASR) as exc:
        asr_web.normaliza({"results": {"channels": []}}, max_chars=26)
    assert "fala" in str(exc.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_asr.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'asr'` (do diretório `clipes/api`)

- [ ] **Step 3: Write minimal implementation**

```python
# clipes/api/asr.py
"""Cliente da API de ASR, normalizado para o formato desta base.

O formato de saída é IDÊNTICO ao de src/capcut_mcp/asr.py — blocos com
{start, end, text, index} e palavras com {start, end, word} — porque `timemap` e
`subtitles` consomem os dois. Divergir aqui quebraria os dois de uma vez.

A moldagem dos blocos reaproveita `capcut_mcp.asr._shape_blocks`, que já impõe o
teto de caracteres partindo em fronteira de palavra (medido: 26 caracteres cabem
numa linha na tela).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

from capcut_mcp import asr as local

FORNECEDOR = os.environ.get("ASR_FORNECEDOR", "deepgram")
CHAVE = os.environ.get("ASR_API_KEY", "")
TIMEOUT_S = 240          # abaixo dos 290 do handler


class ErroASR(Exception):
    """Erro com mensagem acionável, no padrão de errors.py."""


def _palavras(cru: Dict[str, Any]) -> List[Dict[str, Any]]:
    canais = ((cru.get("results") or {}).get("channels") or [])
    if not canais:
        raise ErroASR("Nenhuma fala foi reconhecida no áudio. Confirme que há "
                      "voz audível no arquivo.")
    alt = (canais[0].get("alternatives") or [{}])[0]
    cruas = alt.get("words")
    if not cruas:
        raise ErroASR("O fornecedor não devolveu timestamp por palavra, e sem "
                      "ele o corte não consegue encostar na fronteira de fala. "
                      "Confira se a opção está ligada na chamada.")
    return [{"start": round(float(w["start"]), 3),
             "end": round(float(w["end"]), 3),
             "word": w.get("punctuated_word") or w["word"]} for w in cruas]


def normaliza(cru: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    palavras = _palavras(cru)
    # agrupa palavras em blocos crus e deixa o _shape_blocks impor o teto
    brutos, atual = [], None
    for p in palavras:
        if atual and len(f"{atual['text']} {p['word']}") <= max_chars:
            atual["text"] += " " + p["word"]
            atual["end"] = p["end"]
        else:
            atual = {"start": p["start"], "end": p["end"], "text": p["word"]}
            brutos.append(atual)
    blocos = local._shape_blocks(brutos, local.DEFAULT_MAX_BLOCK_S, max_chars)
    return {"blocos": blocos, "palavras": palavras,
            "idioma": "pt", "modelo": FORNECEDOR}


def transcreve(blob_url: str, idioma: str = "pt",
               max_chars: int = local.DEFAULT_MAX_CHARS) -> Dict[str, Any]:
    if not CHAVE:
        raise ErroASR("ASR_API_KEY não está definida no projeto. Defina-a na "
                      "Vercel e refaça o deploy.")
    resp = requests.post(
        "https://api.deepgram.com/v1/listen",
        params={"model": "nova-3", "language": idioma, "punctuate": "true",
                "smart_format": "true"},
        headers={"Authorization": f"Token {CHAVE}",
                 "Content-Type": "application/json"},
        json={"url": blob_url}, timeout=TIMEOUT_S)
    if resp.status_code != 200:
        raise ErroASR(f"A API de ASR respondeu {resp.status_code}: "
                      f"{resp.text[:200]}")
    return normaliza(resp.json(), max_chars)
```

Se a Task 5 escolher outro fornecedor, apenas `transcreve()` muda; `normaliza()` e os testes ficam.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_asr.py -v`
Expected: PASS, 5 testes

- [ ] **Step 5: Ligar a rota**

Acrescentar em `clipes/api/index.py`:

```python
@app.post("/api/projeto/<pid>/transcrever")
def transcrever(pid: str):
    barrado = exige_codigo()
    if barrado:
        return barrado
    import asr
    d = projeto.le(pid)
    if d is None:
        return erro("Projeto não encontrado.", 404)
    if d.get("transcript"):
        return jsonify({"ja_transcrito": True,
                        "blocos": len(d["transcript"]["blocos"])})
    url = (d["fonte"] or {}).get("blob_url")
    if not url:
        return erro("Este projeto não tem arquivo no Blob; refaça o upload.")
    try:
        t = asr.transcreve(url)
    except asr.ErroASR as exc:
        return erro(str(exc), 422)
    projeto.atualiza_transcript(pid, t)
    return jsonify({"blocos": len(t["blocos"]),
                    "palavras": len(t["palavras"])})
```

- [ ] **Step 6: Commit**

```bash
git add clipes/api/asr.py clipes/api/index.py tests/clipes/test_asr.py
git commit -m "feat(clipes): ASR por API, normalizado para o formato desta base"
```

---

### Task 7: Seleção pela LLM, com insight e minutagem

**Files:**
- Create: `clipes/api/selecao.py`
- Modify: `clipes/api/index.py` (rota `POST /api/projeto/<id>/selecionar`), `clipes/api/projeto.py` (`grava_clipes`)
- Test: `tests/clipes/test_selecao.py`

**Interfaces:**
- Consumes: `projeto.le`
- Produces: `propoe(transcript: dict, duracao_s: float, pedido: str = "") -> list[dict]` com itens `{"titulo_curto", "justificativa", "trechos": [[a, b]]}`; `projeto.grava_clipes(pid, clipes) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_selecao.py
import os, sys
import pytest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))

import selecao

TRANSCRIPT = {"blocos": [
    {"start": 0.0, "end": 3.0, "text": "Bem-vindo ao teste", "index": 1},
    {"start": 3.0, "end": 9.0, "text": "vamos falar de preço", "index": 2},
    {"start": 9.0, "end": 20.0, "text": "o preço é cento e vinte", "index": 3},
], "palavras": []}


def test_valida_trecho_fora_da_duracao():
    with pytest.raises(selecao.ErroSelecao) as exc:
        selecao.valida([{"titulo_curto": "x", "justificativa": "y",
                         "trechos": [[10.0, 99.0]]}], duracao_s=20.0)
    assert "99" in str(exc.value)


def test_valida_trecho_invertido():
    with pytest.raises(selecao.ErroSelecao):
        selecao.valida([{"titulo_curto": "x", "justificativa": "y",
                         "trechos": [[9.0, 4.0]]}], duracao_s=20.0)


def test_valida_exige_justificativa():
    """Sem o porquê, o insight não existe — e insight é metade do produto."""
    with pytest.raises(selecao.ErroSelecao) as exc:
        selecao.valida([{"titulo_curto": "x", "justificativa": "",
                         "trechos": [[1.0, 5.0]]}], duracao_s=20.0)
    assert "justificativa" in str(exc.value)


def test_valida_descarta_clipe_curto_demais():
    with pytest.raises(selecao.ErroSelecao) as exc:
        selecao.valida([{"titulo_curto": "x", "justificativa": "y",
                         "trechos": [[1.0, 2.0]]}], duracao_s=20.0)
    assert "curto" in str(exc.value)


def test_valida_aceita_o_que_esta_bom():
    bons = [{"titulo_curto": "Preço", "justificativa": "fala o valor",
             "trechos": [[3.0, 19.0]]}]
    assert selecao.valida(bons, duracao_s=20.0) == bons


def test_prompt_traz_o_compact_e_a_duracao():
    p = selecao.monta_prompt(TRANSCRIPT, duracao_s=20.0, pedido="foco em preço")
    assert "[3.0]" in p or "3.0" in p, "o prompt precisa da minutagem"
    assert "20" in p
    assert "foco em preço" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_selecao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'selecao'`

- [ ] **Step 3: Write minimal implementation**

```python
# clipes/api/selecao.py
"""A LLM lê o transcript e propõe clipes com minutagem e justificativa.

`valida()` existe porque a saída de um modelo é entrada não confiável: trecho
fora da duração, invertido ou curto demais produziria corte inválido silencioso.
Validar antes de gravar é a mesma regra do validator.py desta base.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

MIN_CLIPE_S = 8.0
MAX_CLIPE_S = 90.0
MODELO = os.environ.get("CAPCUT_MODELO", "claude-opus-5")


class ErroSelecao(Exception):
    """Erro com mensagem acionável."""


def monta_prompt(transcript: Dict[str, Any], duracao_s: float,
                 pedido: str = "") -> str:
    linhas = [f"[{b['start']:.1f}] {b['text']}" for b in transcript["blocos"]]
    return (
        f"Esta é a transcrição de uma gravação de {duracao_s:.0f} segundos, com "
        "o instante em que cada fala começa.\n\n"
        + "\n".join(linhas)
        + "\n\nEscolha os melhores momentos para virar clipes curtos.\n"
        "Do que já foi medido neste projeto:\n"
        "- o gancho vive nos 3 primeiros segundos: comece NA frase, nunca no "
        "meio dela;\n"
        "- prefira trechos que começam e terminam em fronteira de sentença — a "
        "pontuação acima existe para isso;\n"
        f"- clipe vertical funciona entre {MIN_CLIPE_S:.0f} e {MAX_CLIPE_S:.0f} "
        "segundos.\n"
        + (f"\nPedido de quem vai usar: {pedido}\n" if pedido else "")
        + "\nPara cada clipe, escreva uma justificativa de uma linha dizendo "
        "por que ESTE momento vale — é o que a pessoa vai ler para decidir se "
        "aceita."
    )


ESQUEMA_SAIDA = {
    "type": "object",
    "properties": {"clipes": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "titulo_curto": {"type": "string"},
            "justificativa": {"type": "string"},
            "trechos": {"type": "array", "items": {
                "type": "array", "items": {"type": "number"},
                "minItems": 2, "maxItems": 2}},
        },
        "required": ["titulo_curto", "justificativa", "trechos"],
        "additionalProperties": False}}},
    "required": ["clipes"], "additionalProperties": False,
}


def valida(clipes: List[Dict[str, Any]], duracao_s: float) -> List[Dict[str, Any]]:
    for i, c in enumerate(clipes):
        if not (c.get("justificativa") or "").strip():
            raise ErroSelecao(f"O clipe {i} veio sem justificativa, e ela é o "
                              "insight que a pessoa lê para decidir.")
        trechos = c.get("trechos") or []
        if not trechos:
            raise ErroSelecao(f"O clipe {i} veio sem trecho nenhum.")
        total = 0.0
        for a, b in trechos:
            if b <= a:
                raise ErroSelecao(f"O clipe {i} tem trecho invertido: [{a}, {b}].")
            if b > duracao_s + 0.5:
                raise ErroSelecao(f"O clipe {i} termina em {b}, depois do fim da "
                                  f"gravação ({duracao_s:.1f}s).")
            total += b - a
        if total < MIN_CLIPE_S:
            raise ErroSelecao(f"O clipe {i} tem {total:.1f}s, curto demais para "
                              f"publicar (mínimo {MIN_CLIPE_S:.0f}s).")
    return clipes


def propoe(transcript: Dict[str, Any], duracao_s: float,
           pedido: str = "") -> List[Dict[str, Any]]:
    import anthropic
    cliente = anthropic.Anthropic()
    with cliente.messages.stream(
        model=MODELO, max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema",
                                  "schema": ESQUEMA_SAIDA}},
        messages=[{"role": "user",
                   "content": monta_prompt(transcript, duracao_s, pedido)}],
    ) as fluxo:
        resposta = fluxo.get_final_message()
    texto = next((b.text for b in resposta.content if b.type == "text"), "")
    try:
        clipes = json.loads(texto)["clipes"]
    except Exception as exc:
        raise ErroSelecao(f"Não consegui ler a resposta do modelo: {exc}") from exc
    return valida(clipes, duracao_s)
```

Acrescentar em `clipes/api/projeto.py`:

```python
def grava_clipes(pid: str, clipes: List[Dict[str, Any]]) -> None:
    """Substitui os clipes do projeto. A seleção é refeita por inteiro, nunca
    mesclada — mesclar deixaria clipe órfão de uma proposta anterior."""
    with banco.conexao() as con, con.cursor() as cur:
        banco.garante_esquema(cur)
        cur.execute("delete from clipes.clipes where projeto_id = %s", (pid,))
        for ordem, c in enumerate(clipes):
            cur.execute(
                "insert into clipes.clipes (id, projeto_id, ordem, titulo_curto,"
                " justificativa, trechos) values (%s, %s, %s, %s, %s, %s)",
                (novo_id(), pid, ordem, c["titulo_curto"][:200],
                 c["justificativa"][:500], json.dumps(c["trechos"])))
        cur.execute("update clipes.projetos set estado = 'selecionado'"
                    " where id = %s", (pid,))
```

E a rota em `index.py`:

```python
@app.post("/api/projeto/<pid>/selecionar")
def selecionar(pid: str):
    barrado = exige_codigo()
    if barrado:
        return barrado
    import selecao
    d = projeto.le(pid)
    if d is None:
        return erro("Projeto não encontrado.", 404)
    if not d.get("transcript"):
        return erro("Transcreva antes de selecionar — a escolha lê o transcript.",
                    409)
    pedido = (request.get_json(silent=True) or {}).get("pedido", "")
    try:
        clipes = selecao.propoe(d["transcript"], d["fonte"]["duracao_s"], pedido)
    except selecao.ErroSelecao as exc:
        return erro(str(exc), 422)
    projeto.grava_clipes(pid, clipes)
    return jsonify({"clipes": len(clipes)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_selecao.py -v`
Expected: PASS, 6 testes

- [ ] **Step 5: Commit**

```bash
git add clipes/api/selecao.py clipes/api/projeto.py clipes/api/index.py tests/clipes/test_selecao.py
git commit -m "feat(clipes): seleção pela LLM com insight, validada antes de gravar"
```

---

### Task 8: Tela dos highlights

**Files:**
- Modify: `clipes/static/index.html`
- Test: `tests/clipes/test_tela_highlights.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_tela_highlights.py
import os

TELA = os.path.join(os.path.dirname(__file__), "..", "..",
                    "clipes", "static", "index.html")


def corpo():
    with open(TELA, encoding="utf-8") as f:
        return f.read()


def test_chama_transcrever_e_selecionar():
    c = corpo()
    assert "/transcrever" in c and "/selecionar" in c


def test_mostra_justificativa_e_minutagem():
    """Sem esses dois na tela, o produto da Fase 2 não apareceu."""
    c = corpo()
    assert "justificativa" in c
    assert "minutagem" in c.lower() or "trechos" in c


def test_preview_pula_para_o_trecho_do_clipe():
    """Clicar num highlight tem de levar o preview até ele."""
    assert "currentTime" in corpo()


def test_mostra_o_progresso_das_etapas():
    c = corpo()
    assert "Transcrevendo" in c and "Analisando" in c
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_tela_highlights.py -v`
Expected: FAIL nos quatro

- [ ] **Step 3: Write minimal implementation**

```javascript
// as duas etapas, com o estado visível — uma barra que trava sem dizer em que
// passo está é o que faz a pessoa recarregar a página no meio
async function analisar(pid) {
  etapa("Transcrevendo a fala…");
  await api(`/api/projeto/${pid}/transcrever`, { method: "POST" });
  etapa("Analisando os melhores momentos…");
  await api(`/api/projeto/${pid}/selecionar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pedido: $("#pedido").value.trim() }),
  });
  etapa("");
  const d = await api(`/api/projeto/${pid}`);
  desenhaHighlights(d.clipes);
}

function desenhaHighlights(clipes) {
  const caixa = $("#highlights");
  caixa.innerHTML = "";
  clipes.filter(c => !c.descartado).forEach((c, i) => {
    const [ini, fim] = c.trechos[0];
    const card = el("div", "clipe");
    card.appendChild(el("div", "titulo", `${i + 1}. ${c.titulo_curto}`));
    // minutagem: o que foi pedido para aparecer junto com o insight
    card.appendChild(el("div", "minutagem",
      `${ini.toFixed(1)} s → ${fim.toFixed(1)} s · ${(fim - ini).toFixed(0)} s`));
    card.appendChild(el("div", "justificativa", c.justificativa));
    const prep = el("button", "principal", "Preparar clipe");
    prep.onclick = (e) => { e.stopPropagation(); prepara(c.id, card); };
    card.appendChild(prep);
    // clicar no card leva o preview LOCAL até o trecho — custo zero
    card.onclick = () => { $("#preview").currentTime = ini; };
    caixa.appendChild(card);
  });
}

function etapa(texto) {
  $("#etapa").textContent = texto;
  $("#etapa").hidden = !texto;
}
```

Reaproveitar os tokens de cor e as classes de `vercel-ui/static/index.html` para
as telas parecerem o mesmo produto; `el()` e `api()` são os mesmos helpers de lá.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_tela_highlights.py -v`
Expected: PASS, 4 testes

- [ ] **Step 5: Verificar na tela — AC2**

Subir uma gravação real, clicar em Analisar, e confirmar que cada highlight traz minutagem e uma justificativa que faz sentido. Clicar num card leva o preview ao trecho.

- [ ] **Step 6: Commit**

```bash
git add clipes/static/index.html tests/clipes/test_tela_highlights.py
git commit -m "feat(clipes): tela de highlights com minutagem e justificativa"
```

---

## Fase 3 — Corte em clipes curtos

### Task 9: ffmpeg estático no bundle

**Files:**
- Create: `clipes/build.sh`
- Modify: `clipes/vercel.json` (`buildCommand`)
- Test: `tests/clipes/test_ffmpeg.py`

**Interfaces:**
- Produces: `corte.caminho_ffmpeg() -> str`

O bundle Python da Vercel aceita 500 MB; um ffmpeg estático linux-x64 fica entre 70 e 90 MB. Cabe sem precisar do beta de *large functions*.

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_ffmpeg.py
import os, subprocess, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))

import corte


def test_acha_um_ffmpeg_executavel():
    """Localmente cai no ffmpeg do PATH; na Vercel, no binário do bundle."""
    caminho = corte.caminho_ffmpeg()
    assert caminho
    saida = subprocess.run([caminho, "-version"], capture_output=True, text=True)
    assert saida.returncode == 0
    assert "ffmpeg version" in saida.stdout


def test_erro_acionavel_quando_nao_acha():
    import pytest
    original = corte.BIN_BUNDLE
    corte.BIN_BUNDLE = "/nao/existe/ffmpeg"
    try:
        import shutil
        real = shutil.which
        corte.shutil.which = lambda n: None
        with pytest.raises(corte.ErroCorte) as exc:
            corte.caminho_ffmpeg()
        assert "build.sh" in str(exc.value)
    finally:
        corte.BIN_BUNDLE = original
        corte.shutil.which = real
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_ffmpeg.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'corte'`

- [ ] **Step 3: Write minimal implementation**

```bash
#!/bin/sh
# clipes/build.sh — baixa o ffmpeg estático para dentro do bundle.
# Sem isto a função não tem como cortar: a Vercel não traz ffmpeg.
set -e
mkdir -p bin
if [ ! -f bin/ffmpeg ]; then
  echo "baixando ffmpeg estático..."
  curl -sL -o /tmp/ff.tar.xz \
    https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
  tar -xJf /tmp/ff.tar.xz -C /tmp
  cp /tmp/ffmpeg-*-amd64-static/ffmpeg bin/ffmpeg
  cp /tmp/ffmpeg-*-amd64-static/ffprobe bin/ffprobe
  chmod +x bin/ffmpeg bin/ffprobe
fi
ls -la bin/
```

Em `clipes/vercel.json`, acrescentar `"buildCommand": "sh build.sh"`.

E o começo de `clipes/api/corte.py`:

```python
"""Corte por CÓPIA DE FLUXO. Não renderiza, não reencoda, não gera pixel.

`-c copy` copia os bytes com fronteiras novas: segundos de CPU para qualquer
duração, contra minutos para reencodar. É o que faz o corte caber no teto de
300 s do plano Hobby.
"""
from __future__ import annotations

import os
import shutil
import subprocess

BIN_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "bin", "ffmpeg")


class ErroCorte(Exception):
    """Erro com mensagem acionável."""


def caminho_ffmpeg() -> str:
    if os.path.isfile(BIN_BUNDLE) and os.access(BIN_BUNDLE, os.X_OK):
        return BIN_BUNDLE
    do_path = shutil.which("ffmpeg")
    if do_path:
        return do_path
    raise ErroCorte(
        "ffmpeg não encontrado. No deploy ele vem do bin/ do bundle — confira "
        "se o build.sh rodou; localmente, instale com 'brew install ffmpeg'.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_ffmpeg.py -v`
Expected: PASS, 2 testes

- [ ] **Step 5: Commit**

```bash
git add clipes/build.sh clipes/vercel.json clipes/api/corte.py tests/clipes/test_ffmpeg.py
git commit -m "feat(clipes): ffmpeg estático no bundle, com erro acionável se faltar"
```

---

### Task 10: Corte por cópia de fluxo, com o início medido

**Files:**
- Modify: `clipes/api/corte.py`
- Test: `tests/clipes/test_corte.py`

**Interfaces:**
- Consumes: `caminho_ffmpeg`, `capcut_mcp.media.probe`
- Produces: `corta(fonte: str, inicio_s: float, fim_s: float, destino: str) -> dict` devolvendo `{"caminho", "inicio_real_s", "duracao_real_s", "reencodou": False}`

**Este é o ponto onde a spec §5.2 se paga.** Corte sem reencode cai em keyframe, então o início real do arquivo pode não ser o pedido. Gerar o SRT contra o pedido dessincronizaria — a mesma classe de erro dos achados A e F da auditoria desta base. Por isso o retorno traz `inicio_real_s` **medido**.

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_corte.py
import os, subprocess, sys
import pytest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.join(REPO, "fixtures")

import corte
from capcut_mcp import media

FONTE = os.path.join(FX, "video_fala.mp4")     # 18,767 s


def test_corta_e_mede_o_inicio_real(tmp_path):
    destino = str(tmp_path / "c1.mp4")
    r = corte.corta(FONTE, 5.0, 12.0, destino)
    assert os.path.isfile(destino)
    assert r["reencodou"] is False
    # o início real pode diferir do pedido por causa do keyframe
    assert abs(r["inicio_real_s"] - 5.0) <= 3.0
    assert r["duracao_real_s"] > 0


def test_nao_reencoda():
    """Se reencodar, o custo explode e o teto de 300 s deixa de valer."""
    assert "-c" in corte.ARGS_COPIA and "copy" in corte.ARGS_COPIA


def test_o_arquivo_gerado_e_legivel_e_tem_audio(tmp_path):
    destino = str(tmp_path / "c2.mp4")
    corte.corta(FONTE, 2.0, 8.0, destino)
    p = media.probe(destino)
    assert p["kind"] == "video"
    assert p["has_audio"] is True
    assert p["duration_s"] > 4.0


def test_trecho_invertido_e_recusado(tmp_path):
    with pytest.raises(corte.ErroCorte):
        corte.corta(FONTE, 9.0, 3.0, str(tmp_path / "x.mp4"))


def test_fonte_inexistente_da_erro_acionavel(tmp_path):
    with pytest.raises(corte.ErroCorte) as exc:
        corte.corta("/nao/existe.mp4", 0.0, 5.0, str(tmp_path / "x.mp4"))
    assert "não" in str(exc.value).lower()


def test_corte_de_video_longo_e_rapido(tmp_path):
    """Cópia de fluxo não depende da duração — se dependesse, era reencode."""
    import time
    t0 = time.time()
    corte.corta(FONTE, 0.0, 18.0, str(tmp_path / "longo.mp4"))
    assert time.time() - t0 < 10.0, "cópia de fluxo levando mais de 10 s é suspeito"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_corte.py -v`
Expected: FAIL com `AttributeError: module 'corte' has no attribute 'corta'`

- [ ] **Step 3: Write minimal implementation**

```python
# acrescentar em clipes/api/corte.py
from typing import Any, Dict

ARGS_COPIA = ["-c", "copy", "-avoid_negative_ts", "make_zero"]
TIMEOUT_S = 240


def corta(fonte: str, inicio_s: float, fim_s: float,
          destino: str) -> Dict[str, Any]:
    from capcut_mcp import media

    if fim_s <= inicio_s:
        raise ErroCorte(f"Trecho invertido: [{inicio_s}, {fim_s}].")
    if not (fonte.startswith(("http://", "https://")) or os.path.isfile(fonte)):
        raise ErroCorte(f"A fonte não foi encontrada: {fonte}")

    cmd = [caminho_ffmpeg(), "-v", "error", "-y",
           "-ss", f"{inicio_s:.3f}", "-to", f"{fim_s:.3f}",
           "-i", fonte, *ARGS_COPIA, destino]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise ErroCorte(f"O corte passou de {TIMEOUT_S}s, o que não deveria "
                        "acontecer numa cópia de fluxo.") from exc
    if proc.returncode != 0 or not os.path.isfile(destino):
        raise ErroCorte(f"O ffmpeg falhou: {proc.stderr[-300:]}")

    # MEDIR, não supor: -ss antes do -i procura o keyframe anterior, então o
    # início real pode vir antes do pedido. O SRT é gerado contra este valor.
    p = media.probe(destino)
    return {"caminho": destino,
            "inicio_real_s": round(inicio_s - _deslocamento(p, inicio_s, fim_s), 3),
            "duracao_real_s": p.get("duration_s") or 0.0,
            "reencodou": False}


def _deslocamento(p: Dict[str, Any], inicio_s: float, fim_s: float) -> float:
    """Quanto o arquivo ficou MAIOR que o pedido — o quanto o keyframe recuou.

    ATENÇÃO: esta é uma DERIVAÇÃO, não uma medição — e o resto deste plano
    prega o contrário. O comportamento do `-ss` antes do `-i` com `-c copy`
    varia por versão de ffmpeg e por como o arquivo foi encodado, então a
    fórmula é uma primeira aproximação.

    O Step 3.1 existe para medir o valor real antes de confiar nela.
    """
    pedido = fim_s - inicio_s
    real = p.get("duration_s") or pedido
    return max(0.0, round(real - pedido, 3))
```

- [ ] **Step 3.1: Medir o deslocamento antes de confiar na fórmula**

A fórmula acima supõe que todo excedente de duração vem do keyframe anterior.
Isso precisa ser conferido, porque o SRT das Fases 4 a 6 será gerado contra este
número — e um erro aqui reapareceria como legenda dessincronizada, que é
exatamente a classe de bug que a auditoria desta base já pegou duas vezes.

Salvar como `clipes/medir_keyframe.py` e rodar:

```python
import os, sys, tempfile
sys.path.insert(0, "clipes/api"); sys.path.insert(0, "src")
import corte

F = "fixtures/video_fala.mp4"
print(f"{'pedido':>18} {'dur pedida':>11} {'dur real':>9} {'excesso':>8}")
with tempfile.TemporaryDirectory() as t:
    for ini, fim in ((0.0, 5.0), (2.5, 7.5), (5.0, 12.0), (7.3, 11.9), (13.0, 18.0)):
        d = os.path.join(t, "c.mp4")
        r = corte.corta(F, ini, fim, d)
        excesso = r["duracao_real_s"] - (fim - ini)
        print(f"  [{ini:5.1f}, {fim:5.1f}] {fim - ini:11.3f} "
              f"{r['duracao_real_s']:9.3f} {excesso:8.3f}")
```

Run: `PYTHONPATH=src ./.venv/bin/python clipes/medir_keyframe.py`

Registrar a tabela em `docs/superpowers/plans/evidencia/keyframe.md`.

- **Se o excesso for sempre ~0**: o `-ss` está fazendo seek preciso, o
  `inicio_real_s` é o próprio pedido, e a fórmula sai — o campo fica só por
  garantia, documentado como sempre zero nesta configuração.
- **Se variar**: a fórmula fica, e a evidência registra a faixa medida para as
  Fases 4 a 6 saberem com que erro estão lidando.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_corte.py -v`
Expected: PASS, 6 testes

- [ ] **Step 5: Commit**

```bash
git add clipes/api/corte.py tests/clipes/test_corte.py
git commit -m "feat(clipes): corte por cópia de fluxo com o início real medido"
```

---

### Task 11: Preparar clipe, baixar, e o AC10 de ponta a ponta

**Files:**
- Modify: `clipes/api/index.py` (rota `POST /api/clipe/<id>/preparar`), `clipes/api/projeto.py` (`grava_saida`), `clipes/static/index.html`
- Test: `tests/clipes/test_preparar.py`

**Interfaces:**
- Consumes: `corte.corta`, `projeto.le`
- Produces: `projeto.grava_saida(clipe_id, saida: dict) -> None`; rota devolvendo `{"mp4_url", "inicio_real_s", "duracao_real_s"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/clipes/test_preparar.py
import os, sys
import pytest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "clipes", "api"))

import index


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(index, "UI_CODE", "s")
    index.app.config["TESTING"] = True
    return index.app.test_client()


def test_preparar_sem_codigo_e_401(cliente):
    assert cliente.post("/api/clipe/x/preparar").status_code == 401


def test_preparar_clipe_inexistente_e_404(cliente):
    r = cliente.post("/api/clipe/nao-existe/preparar",
                     headers={"X-UI-Code": "s"})
    assert r.status_code in (404, 503)   # 503 se não houver banco no ambiente


def test_a_rota_tem_maxduration_abaixo_do_teto():
    """290 s deixa margem para responder antes do corte duro de 300 s."""
    import json
    cfg = json.load(open(os.path.join(REPO, "clipes", "vercel.json")))
    assert cfg["functions"]["api/index.py"]["maxDuration"] <= 290
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_preparar.py -v`
Expected: FAIL — a rota `/api/clipe/<id>/preparar` ainda não existe (404 onde se espera 401)

- [ ] **Step 3: Write minimal implementation**

Em `projeto.py`:

```python
def grava_saida(clipe_id: str, saida: Dict[str, Any]) -> None:
    with banco.conexao() as con, con.cursor() as cur:
        banco.garante_esquema(cur)
        cur.execute("update clipes.clipes set saida = %s where id = %s",
                    (json.dumps(saida), clipe_id))


def le_clipe(clipe_id: str) -> Optional[Dict[str, Any]]:
    with banco.conexao() as con, con.cursor() as cur:
        banco.garante_esquema(cur)
        cur.execute(
            "select c.id, c.projeto_id, c.ordem, c.trechos, c.saida, p.fonte"
            " from clipes.clipes c join clipes.projetos p"
            " on p.id = c.projeto_id where c.id = %s", (clipe_id,))
        l = cur.fetchone()
    if l is None:
        return None
    return {"id": l[0], "projeto_id": l[1], "ordem": l[2], "trechos": l[3],
            "saida": l[4], "fonte": l[5]}
```

Em `index.py`:

```python
@app.post("/api/clipe/<clipe_id>/preparar")
def preparar(clipe_id: str):
    barrado = exige_codigo()
    if barrado:
        return barrado
    import tempfile
    import corte
    c = projeto.le_clipe(clipe_id)
    if c is None:
        return erro("Clipe não encontrado.", 404)
    if c.get("saida"):
        return jsonify(c["saida"])            # idempotente: não corta de novo
    trechos = c["trechos"] or []
    if len(trechos) != 1:
        return erro("Esta versão prepara apenas clipe de trecho único; este tem "
                    f"{len(trechos)}. Divida em clipes separados.", 422)
    inicio, fim = float(trechos[0][0]), float(trechos[0][1])
    url = (c["fonte"] or {}).get("blob_url")
    if not url:
        return erro("O projeto não tem arquivo no Blob; refaça o upload.")
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, f"clipe-{c['ordem'] + 1}.mp4")
        try:
            r = corte.corta(url, inicio, fim, local)
        except corte.ErroCorte as exc:
            return erro(str(exc), 422)
        with open(local, "rb") as f:
            mp4_url = _sobe_para_blob(f.read(), os.path.basename(local))
    saida = {"mp4_url": mp4_url, "inicio_real_s": r["inicio_real_s"],
             "duracao_real_s": r["duracao_real_s"]}
    projeto.grava_saida(clipe_id, saida)
    return jsonify(saida)


def _sobe_para_blob(dados: bytes, nome: str) -> str:
    """Upload de servidor, pela API REST do Blob — o clipe cortado é pequeno."""
    import requests
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
    if not token:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN não definida no projeto.")
    resp = requests.put(
        f"https://blob.vercel-storage.com/{nome}",
        headers={"authorization": f"Bearer {token}",
                 "x-api-version": "7",
                 "x-content-type": "video/mp4",
                 "x-add-random-suffix": "1"},
        data=dados, timeout=120)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"O Blob recusou o upload: {resp.status_code} "
                           f"{resp.text[:200]}")
    return resp.json()["url"]
```

Na tela: botão **Preparar clipe** em cada card, que chama a rota e troca por um link de download com a duração real.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/clipes/test_preparar.py -v`
Expected: PASS, 3 testes

- [ ] **Step 5: Rodar a suíte inteira**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/ -q`
Expected: os 246 testes existentes + os novos, todos passando. **Se algum dos 246 quebrou, é regressão no modo MCP/Desktop e tem de ser consertada antes do commit.**

- [ ] **Step 6: AC10 — ponta a ponta com gravação real**

Deploy, e então com uma gravação **real** (não a fixture), verificar na tela:

1. Sobe o arquivo e o preview toca antes de o upload terminar
2. Analisar devolve highlights com minutagem e justificativa que fazem sentido
3. Preparar clipe responde em segundos, não minutos
4. O MP4 baixado **abre** e começa onde o card disse
5. Nenhuma chamada passou de 290 s

Registrar o resultado em `docs/superpowers/plans/evidencia/ac10.md`, com os tempos medidos.

- [ ] **Step 7: Commit**

```bash
git add clipes/ tests/clipes/ docs/superpowers/plans/evidencia/ac10.md
git commit -m "feat(clipes): preparar e baixar o clipe cortado — AC10 verificado"
```

---

## Cobertura da spec por esta parte do plano

| Requisito da spec | Task |
|---|---|
| §2.1 sobe sem instalar nada | 3, 4 |
| §2.2 IA transcreve e propõe com justificativa | 6, 7 |
| §2.4 MP4 já cortado | 10, 11 |
| §2.5 reaproveitar `media`, `timemap`, `subtitles` | 6 (`_shape_blocks`), 10 (`probe`) |
| §4.1 preview não renderiza | 4 |
| §4.1 corte é cópia de fluxo | 9, 10 |
| §4.1 sem Workflow | todo passo cabe em 290 s (Task 3, 11) |
| §5 modelo de dados | 1, 2, 7, 11 |
| §5.2 keyframe medido | 10 |
| §8 erro com código e sugestão | 1, 3, 6, 7, 9, 10 |
| AC1 | 4 |
| AC2 | 8 |
| AC4, AC8 | 10, 11 |
| AC9 (246 testes) | 11, Step 5 |
| AC10 | 11, Step 6 |

**Fora desta parte, por desenho:** §5.1 (SRT derivado), §6 (passo a passo do CapCut Web), AC3, AC5, AC6, AC7 — são as Fases 4 a 6, e entram num segundo plano depois que o AC10 fechar.
