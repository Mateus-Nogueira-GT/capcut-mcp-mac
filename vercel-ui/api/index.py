"""Relay hospedado: fila de trabalho entre a UI e o motor na máquina de cada um.

## Por que existe

O Chrome 142+ bloqueia uma página de origem pública que chama `127.0.0.1`
(Local Network Access), e a falha é silenciosa. Então o sentido da conexão é
invertido: **o motor local liga para cá**, de saída, e puxa trabalho. Nenhuma
requisição da página vai para a rede local, e o LNA não se aplica.

    navegador ──> relay (aqui) <── batida do motor local ──> CapCut no Mac

O vídeo **não passa por aqui**. O motor informa o que existe na pasta de entrada
dele; a UI mostra essa lista e manda só o caminho escolhido. O arquivo nunca sai
da máquina.

## Autenticação, e por que ela é obrigatória

Sem autenticação este endpoint deixaria qualquer pessoa na internet enfileirar
trabalho que **executa no Mac de outra pessoa**. Duas credenciais separadas:

  * `CAPCUT_UI_CODE`  — quem pode criar job pela UI;
  * token por máquina — só o motor que registrou aquele nome pega os jobs dele,
    guardado como hash.

Para uso interno vale também ligar o Deployment Protection da Vercel na frente
disto; são coisas complementares, não alternativas.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from typing import Any, Dict, List, Optional

import psycopg
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="../static", static_url_path="")

UI_CODE = os.environ.get("CAPCUT_UI_CODE", "")
DB = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
MAX_EVENTOS = 400
VISTO_RECENTE_S = 25       # acima disto a máquina aparece como offline


def _hash(valor: str) -> str:
    return hashlib.sha256(("capcut-relay:" + valor).encode()).hexdigest()


def conexao():
    if not DB:
        raise RuntimeError(
            "DATABASE_URL não está definida. Conecte o store Neon ao projeto "
            "no painel da Vercel (Storage -> Connect Project) e refaça o deploy."
        )
    return psycopg.connect(DB, autocommit=True)


ESQUEMA = """
create schema if not exists capcut;

create table if not exists capcut.maquinas (
  nome        text primary key,
  token_hash  text not null,
  visto_em    timestamptz not null default now(),
  estado      jsonb not null default '{}'::jsonb,
  inventario  jsonb not null default '[]'::jsonb
);

create table if not exists capcut.jobs (
  id           bigserial primary key,
  maquina      text not null references capcut.maquinas(nome) on delete cascade,
  tipo         text not null,
  prompt       text not null default '',
  fonte        text,
  estado       text not null default 'pendente',
  criado_em    timestamptz not null default now(),
  pego_em      timestamptz,
  terminado_em timestamptz
);

create index if not exists jobs_fila on capcut.jobs (maquina, estado, id);

create table if not exists capcut.eventos (
  id        bigserial primary key,
  job_id    bigint not null references capcut.jobs(id) on delete cascade,
  tipo      text not null,
  dados     jsonb not null default '{}'::jsonb,
  criado_em timestamptz not null default now()
);

create index if not exists eventos_do_job on capcut.eventos (job_id, id);
"""

_pronto = False


def garante_esquema(cur) -> None:
    """Idempotente, e roda na primeira requisição — não há passo de migração."""
    global _pronto
    if _pronto:
        return
    cur.execute(ESQUEMA)
    _pronto = True


def erro(msg: str, codigo: int = 400, **extra):
    return jsonify({"erro": msg, **extra}), codigo


@app.errorhandler(Exception)
def qualquer_erro(exc):
    """Sem isto, 'banco não conectado' chegava como 500 opaco na tela.

    A causa mais comum é justamente a configuração faltando, e um 500 sem
    mensagem manda a pessoa procurar no lugar errado.
    """
    if isinstance(exc, RuntimeError) and "DATABASE_URL" in str(exc):
        return erro(str(exc), 503, configuracao_faltando="DATABASE_URL")
    if isinstance(exc, psycopg.Error):
        return erro(f"O banco recusou a operação: {type(exc).__name__}: {exc}"[:400],
                    502)
    codigo = getattr(exc, "code", 500)
    if isinstance(codigo, int) and 400 <= codigo < 500:
        return erro(str(exc), codigo)
    return erro(f"{type(exc).__name__}: {exc}"[:400], 500)


def exige_ui():
    """A UI precisa provar que pode enfileirar trabalho na máquina de alguém."""
    if not UI_CODE:
        return erro("CAPCUT_UI_CODE não está configurada no projeto. Sem ela "
                    "qualquer pessoa poderia enfileirar trabalho.", 503)
    enviado = request.headers.get("X-UI-Code", "")
    if not hmac.compare_digest(enviado, UI_CODE):
        return erro("Código de acesso inválido.", 401, precisa_codigo=True)
    return None


# ------------------------------------------------------------ lado do motor
@app.post("/api/agente/batida")
def batida():
    """O motor liga para cá: diz como está, o que tem, e pega o próximo job.

    Registrar é a primeira batida: o nome vira dono do token. Uma segunda
    máquina com o mesmo nome e token diferente é recusada — senão qualquer um
    roubaria a fila de outra pessoa só sabendo o nome dela.
    """
    corpo = request.get_json(silent=True) or {}
    nome = (corpo.get("maquina") or "").strip()
    token = corpo.get("token") or ""
    if not nome or not token:
        return erro("Informe 'maquina' e 'token'.")
    if len(token) < 24:
        return erro("Token curto demais; use ao menos 24 caracteres.")

    with conexao() as con, con.cursor() as cur:
        garante_esquema(cur)
        cur.execute("select token_hash from capcut.maquinas where nome = %s",
                    (nome,))
        linha = cur.fetchone()
        if linha is None:
            cur.execute(
                "insert into capcut.maquinas (nome, token_hash, estado, inventario)"
                " values (%s, %s, %s, %s)",
                (nome, _hash(token), json.dumps(corpo.get("estado") or {}),
                 json.dumps(corpo.get("inventario") or [])))
        else:
            if not hmac.compare_digest(linha[0], _hash(token)):
                return erro("Este nome de máquina já está registrado com outro "
                            "token.", 403)
            cur.execute(
                "update capcut.maquinas set visto_em = now(), estado = %s,"
                " inventario = %s where nome = %s",
                (json.dumps(corpo.get("estado") or {}),
                 json.dumps(corpo.get("inventario") or []), nome))

        # pega um job, marcando como rodando na mesma ida ao banco
        cur.execute(
            "update capcut.jobs set estado = 'rodando', pego_em = now()"
            " where id = ("
            "   select id from capcut.jobs where maquina = %s and"
            "   estado = 'pendente' order by id limit 1"
            "   for update skip locked)"
            " returning id, tipo, prompt, fonte", (nome,))
        job = cur.fetchone()

    if job is None:
        return jsonify({"job": None})
    return jsonify({"job": {"id": job[0], "tipo": job[1], "prompt": job[2],
                            "fonte": job[3]}})


@app.post("/api/agente/evento")
def evento():
    """O motor devolve o que aconteceu, evento por evento."""
    corpo = request.get_json(silent=True) or {}
    nome, token = (corpo.get("maquina") or "").strip(), corpo.get("token") or ""
    job_id, eventos = corpo.get("job_id"), corpo.get("eventos") or []
    if not (nome and token and job_id):
        return erro("Informe 'maquina', 'token' e 'job_id'.")

    with conexao() as con, con.cursor() as cur:
        garante_esquema(cur)
        cur.execute("select token_hash from capcut.maquinas where nome = %s",
                    (nome,))
        linha = cur.fetchone()
        if linha is None or not hmac.compare_digest(linha[0], _hash(token)):
            return erro("Máquina ou token inválidos.", 403)
        # o job tem de ser DESTA máquina, senão uma máquina escreveria na outra
        cur.execute("select maquina from capcut.jobs where id = %s", (job_id,))
        dono = cur.fetchone()
        if dono is None or dono[0] != nome:
            return erro("Este job não é desta máquina.", 403)

        for ev in eventos[:MAX_EVENTOS]:
            cur.execute(
                "insert into capcut.eventos (job_id, tipo, dados)"
                " values (%s, %s, %s)",
                (job_id, str(ev.get("tipo", "texto"))[:40], json.dumps(ev)))
        final = corpo.get("estado_final")
        if final in ("ok", "erro"):
            cur.execute("update capcut.jobs set estado = %s, terminado_em = now()"
                        " where id = %s", (final, job_id))
    return jsonify({"ok": True, "gravados": len(eventos[:MAX_EVENTOS])})


# --------------------------------------------------------------- lado da UI
@app.get("/api/maquinas")
def maquinas():
    barrado = exige_ui()
    if barrado:
        return barrado
    with conexao() as con, con.cursor() as cur:
        garante_esquema(cur)
        cur.execute(
            "select nome, estado, inventario,"
            " extract(epoch from (now() - visto_em))::int"
            " from capcut.maquinas order by visto_em desc")
        fora = [{"nome": n, "estado": e, "inventario": i, "visto_ha_s": s,
                 "online": s is not None and s <= VISTO_RECENTE_S}
                for n, e, i, s in cur.fetchall()]
    return jsonify({"maquinas": fora})


@app.post("/api/job")
def cria_job():
    barrado = exige_ui()
    if barrado:
        return barrado
    corpo = request.get_json(silent=True) or {}
    nome = (corpo.get("maquina") or "").strip()
    tipo = corpo.get("tipo") or "agente"
    if tipo not in ("agente", "diagnostico"):
        return erro("tipo deve ser 'agente' ou 'diagnostico'.")
    if not nome:
        return erro("Escolha a máquina.")
    if tipo == "agente" and not (corpo.get("prompt") or "").strip():
        return erro("Escreva o que você quer que seja feito.")

    with conexao() as con, con.cursor() as cur:
        garante_esquema(cur)
        cur.execute("select 1 from capcut.maquinas where nome = %s", (nome,))
        if cur.fetchone() is None:
            return erro("Máquina desconhecida. Ela já fez alguma batida?", 404)
        cur.execute(
            "insert into capcut.jobs (maquina, tipo, prompt, fonte)"
            " values (%s, %s, %s, %s) returning id",
            (nome, tipo, (corpo.get("prompt") or "")[:8000], corpo.get("fonte")))
        job_id = cur.fetchone()[0]
    return jsonify({"job_id": job_id})


@app.get("/api/job/<int:job_id>")
def le_job(job_id: int):
    barrado = exige_ui()
    if barrado:
        return barrado
    depois = request.args.get("depois", type=int, default=0)
    with conexao() as con, con.cursor() as cur:
        garante_esquema(cur)
        cur.execute("select estado, maquina, tipo from capcut.jobs where id = %s",
                    (job_id,))
        j = cur.fetchone()
        if j is None:
            return erro("Job não encontrado.", 404)
        cur.execute(
            "select id, dados from capcut.eventos where job_id = %s and id > %s"
            " order by id limit %s", (job_id, depois, MAX_EVENTOS))
        eventos = [{"id": i, **(d or {})} for i, d in cur.fetchall()]
    return jsonify({"estado": j[0], "maquina": j[1], "tipo": j[2],
                    "eventos": eventos,
                    "ultimo": eventos[-1]["id"] if eventos else depois})


@app.get("/api/saude")
def saude():
    """Diz se o relay está de pé E se o banco está conectado — separadamente."""
    fora = {"relay": True, "banco": False, "ui_code": bool(UI_CODE)}
    try:
        with conexao() as con, con.cursor() as cur:
            garante_esquema(cur)
            cur.execute("select count(*) from capcut.maquinas")
            fora["banco"] = True
            fora["maquinas"] = cur.fetchone()[0]
    except Exception as exc:
        fora["erro_banco"] = f"{type(exc).__name__}: {exc}"[:300]
    return jsonify(fora)


@app.get("/")
def raiz():
    return send_from_directory(app.static_folder, "index.html")
