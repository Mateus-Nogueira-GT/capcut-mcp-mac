"""Front local para o adaptador: chat + anexo de vídeo, sobre as tools do L1.

## Por que LOCAL e não hospedado

O adaptador entrega um projeto do CapCut escrevendo arquivos em
`~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` — no disco da máquina
onde o CapCut Desktop roda. Um servidor web não tem como escrever nessa pasta na
máquina de outra pessoa. Então o front roda na máquina de cada um, e o "CapCut
daquele usuário" é simplesmente o CapCut instalado ali, já logado por ele.

Não existe OAuth do CapCut para colocar aqui: a plataforma aberta deles é para
plugins que rodam DENTRO do editor, e a API pública é de texto-para-vídeo e
templates — nenhuma das duas cria projeto na timeline. Ver web/LEIA.md.

## Loop de agente manual, de propósito

O `tool_runner` do SDK espera funções decoradas; aqui as tools vêm de um
registro dinâmico (`tools.TOOLS`) e cada chamada precisa virar um evento na
tela. O loop explícito é o que encaixa.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List

from flask import Flask, Response, jsonify, request, send_from_directory

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from capcut_mcp import errors as E, obs, profile, server as mcp_server, tools  # noqa: E402

app = Flask(__name__, static_folder="static", static_url_path="")

MODEL = os.environ.get("CAPCUT_MODEL", "claude-opus-5")
BASE_APOIO = os.path.expanduser("~/Library/Application Support/capcut-mcp")
UPLOADS = os.path.join(BASE_APOIO, "uploads")
TOKEN_PATH = os.path.join(BASE_APOIO, "pair_token")
MAX_TURNOS = 24          # teto do loop: sem isto um erro repetido gira para sempre
MAX_UPLOAD_MB = 2048

# Origens que podem dirigir este motor de fora. A UI hospedada (Vercel) roda no
# navegador DA MESMA máquina, então ela alcança 127.0.0.1 — mas isso significa
# que qualquer página aberta no navegador tentaria o mesmo. Duas travas:
#   1. allowlist de origem exata (sem curinga, sem preview aleatório);
#   2. token de pareamento obrigatório em toda requisição de outra origem.
# Só a primeira não bastaria: requisição simples de formulário dispara sem
# preflight, e aí a origem nem é checada pelo navegador.
ORIGENS_LOCAIS = {f"http://127.0.0.1:{p}" for p in (5151, 3000, 5173)} | \
                 {f"http://localhost:{p}" for p in (5151, 3000, 5173)}


def origens_externas() -> set:
    bruto = os.environ.get("CAPCUT_ALLOW_ORIGIN", "")
    return {o.strip().rstrip("/") for o in bruto.split(",") if o.strip()}


def token_pareamento() -> str:
    """Segredo estável desta máquina, criado na primeira execução."""
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                return t
    except OSError:
        pass
    t = uuid.uuid4().hex
    os.makedirs(BASE_APOIO, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(t)
    os.chmod(TOKEN_PATH, 0o600)
    return t

# Os nomes das tools do MCP têm ponto (`capcut.video.cut`), que a API de tool use
# não aceita. A tradução é só de nome; o schema vai inteiro.
_PONTO = re.compile(r"\.")


def para_api(nome: str) -> str:
    return _PONTO.sub("_", nome)


def de_api(nome: str) -> str:
    return nome.replace("_", ".", 2) if nome.startswith("capcut_") else nome


def tools_para_api() -> List[Dict[str, Any]]:
    """As tools do L1 no formato da Messages API, com cache no fim do bloco.

    O `cache_control` no ÚLTIMO item cobre o prefixo inteiro (tools + system),
    que é ~5,4k tokens repetidos em todo turno do loop. Medido neste projeto:
    com cache, o custo do fluxo cai pela metade num vídeo de 30 min.
    """
    fora = []
    for nome in tools.enabled():
        t = tools.TOOLS[nome]
        fora.append({
            "name": para_api(nome),
            "description": t["description"],
            "input_schema": t["schema"],
            "strict": True,          # os schemas já são additionalProperties: false
        })
    fora[-1]["cache_control"] = {"type": "ephemeral"}
    return fora


SISTEMA = (
    mcp_server.INSTRUCTIONS
    + "\n\nVocê está atendendo por um chat interno. Regras deste contexto:\n"
    "- O caminho do arquivo anexado chega na mensagem do usuário. Use-o como "
    "'source'.\n"
    "- Antes de escolher cortes, chame capcut.media.transcribe e LEIA o campo "
    "'compact'. Escolha os trechos você mesmo, e diga em uma linha por que "
    "escolheu cada um.\n"
    "- Sempre termine com capcut.draft.validate e capcut.draft.save.\n"
    "- Ao final, diga em português, em 2 ou 3 frases, o que foi montado e que o "
    "usuário deve voltar à página inicial do CapCut para o projeto aparecer.\n"
    "- Se uma tool falhar, leia 'suggestion' no erro e corrija a chamada. Não "
    "invente parâmetro que não está no schema."
)

_SESSOES: Dict[str, List[Dict[str, Any]]] = {}


# ----------------------------------------------------------------- execução
def executa_tool(nome_api: str, args: Dict[str, Any]) -> Dict[str, Any]:
    nome = de_api(nome_api)
    entrada = tools.TOOLS.get(nome)
    if entrada is None or nome not in tools.enabled():
        return {"ok": False, "error": {"code": "UNKNOWN_TOOL",
                                       "message": f"Tool desconhecida: {nome}"}}
    bus = obs.WarningBus()
    try:
        # A MESMA validação que o servidor MCP faz antes de chamar o handler.
        # Sem ela, parâmetro ausente virava `INTERNAL_ERROR: KeyError: 'draft_id'`
        # — e no loop a LLM precisa da `suggestion` para se corrigir no turno
        # seguinte. `strict: true` já faz a API respeitar o schema, mas isto é a
        # segunda camada, e é de graça.
        mcp_server._validate(args, entrada["schema"])
        dados = entrada["handler"](args, bus)
        return {"ok": True, "data": dados,
                "warnings": [w["code"] for w in bus.warnings]}
    except E.CapcutError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": exc.message,
                                       "suggestion": exc.suggestion}}
    except Exception as exc:                      # nunca derruba o loop
        obs.log("web_tool_crash", tool=nome, erro=repr(exc))
        return {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                       "message": f"{type(exc).__name__}: {exc}"}}


def conversa(sessao: str, texto: str, anexos: List[str]) -> Iterator[Dict[str, Any]]:
    """Roda o loop de tool use e emite um evento por passo, para a tela."""
    import anthropic

    cliente = anthropic.Anthropic()
    historico = _SESSOES.setdefault(sessao, [])

    partes = [texto or ""]
    for caminho in anexos:
        partes.append(f"\n[arquivo anexado: {caminho}]")
    historico.append({"role": "user", "content": "".join(partes).strip()})

    api_tools = tools_para_api()
    gasto = {"entrada": 0, "saida": 0, "cache_lido": 0, "cache_escrito": 0}

    for turno in range(MAX_TURNOS):
        try:
            with cliente.messages.stream(
                model=MODEL,
                max_tokens=16000,
                system=[{"type": "text", "text": SISTEMA,
                         "cache_control": {"type": "ephemeral"}}],
                thinking={"type": "adaptive", "display": "summarized"},
                tools=api_tools,
                messages=historico,
            ) as fluxo:
                resposta = fluxo.get_final_message()
        except anthropic.APIStatusError as exc:
            yield {"tipo": "erro", "texto": f"A API respondeu {exc.status_code}: "
                                            f"{getattr(exc, 'message', exc)}"}
            return
        except anthropic.APIConnectionError:
            yield {"tipo": "erro", "texto": "Sem conexão com a API da Anthropic."}
            return

        u = resposta.usage
        gasto["entrada"] += u.input_tokens
        gasto["saida"] += u.output_tokens
        gasto["cache_lido"] += getattr(u, "cache_read_input_tokens", 0) or 0
        gasto["cache_escrito"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        for bloco in resposta.content:
            if bloco.type == "thinking" and getattr(bloco, "thinking", ""):
                yield {"tipo": "pensando", "texto": bloco.thinking}
            elif bloco.type == "text" and bloco.text.strip():
                yield {"tipo": "texto", "texto": bloco.text}

        historico.append({"role": "assistant", "content": resposta.content})

        if resposta.stop_reason != "tool_use":
            yield {"tipo": "fim", "gasto": gasto}
            return

        chamadas = [b for b in resposta.content if b.type == "tool_use"]
        resultados = []
        for c in chamadas:
            yield {"tipo": "tool_inicio", "nome": de_api(c.name), "args": c.input}
            t0 = time.time()
            saida = executa_tool(c.name, dict(c.input))
            yield {"tipo": "tool_fim", "nome": de_api(c.name), "ok": saida["ok"],
                   "ms": int((time.time() - t0) * 1000),
                   "resumo": resumo_da_tool(de_api(c.name), saida),
                   "avisos": saida.get("warnings", [])}
            resultados.append({
                "type": "tool_result", "tool_use_id": c.id,
                "content": json.dumps(saida, ensure_ascii=False)[:60000],
                "is_error": not saida["ok"],
            })
        historico.append({"role": "user", "content": resultados})

    yield {"tipo": "erro",
           "texto": f"Parei em {MAX_TURNOS} passos sem concluir. Veja os passos "
                    "acima: normalmente é uma tool falhando de novo e de novo."}


def resumo_da_tool(nome: str, saida: Dict[str, Any]) -> str:
    """Uma linha legível por chamada — o usuário não deveria ler JSON."""
    if not saida["ok"]:
        err = saida["error"]
        return f"{err['code']}: {err['message']}"
    d = saida.get("data") or {}
    if nome == "capcut.media.transcribe":
        return (f"{d.get('block_count')} blocos, {d.get('duration_s', 0):.0f}s, "
                f"idioma {d.get('language')}"
                + (" (do cache)" if d.get("cached") else ""))
    if nome == "capcut.video.cut":
        return (f"{d.get('segments_created')} trecho(s), "
                f"{d.get('total_duration_s')}s finais")
    if nome in ("capcut.subtitle.add", "capcut.subtitle.from_transcript"):
        extra = ""
        if d.get("blocks_dropped"):
            extra = f", {d['blocks_dropped']} descartada(s) pelo corte"
        return f"{d.get('blocks_imported')} legenda(s){extra}"
    if nome in ("capcut.text.add", "capcut.text.add_many"):
        return f"{d.get('texts_created', 1)} texto(s)"
    if nome == "capcut.draft.validate":
        return d.get("summary", "verificado")
    if nome == "capcut.draft.save":
        return d.get("project_path", "salvo")
    if nome == "capcut.media.probe":
        vistos = d.get("probed") or []
        if not vistos:
            return f"{len(d.get('failed') or [])} arquivo(s) não puderam ser lidos"
        m = vistos[0]
        extra = f" (+{len(vistos) - 1})" if len(vistos) > 1 else ""
        sem_audio = "" if m.get("has_audio") else ", SEM áudio"
        return (f"{m.get('duration_s', 0):.1f}s, {m.get('width')}x{m.get('height')}"
                f"{sem_audio}{extra}")
    if nome == "capcut.draft.create":
        return f"draft {str(d.get('draft_id', ''))[:12]}"
    return "ok"


# ------------------------------------------------------- portaria e CORS
import hmac  # noqa: E402  (fica junto do uso, que é só aqui)


def _origem_ok(origem: str) -> bool:
    return bool(origem) and (origem in ORIGENS_LOCAIS or origem in origens_externas())


@app.before_request
def portaria():
    origem = (request.headers.get("Origin") or "").rstrip("/")

    # Private Network Access do Chrome: uma página pública que chama 127.0.0.1
    # manda um preflight pedindo permissão explícita. Sem responder, a chamada
    # falha com um erro que não diz o motivo.
    if request.method == "OPTIONS":
        return ("", 204)

    if not origem or origem in ORIGENS_LOCAIS:
        return None                       # página servida por este próprio motor

    if not _origem_ok(origem):
        return jsonify({"erro": "Origem não autorizada. Suba o motor com "
                                "CAPCUT_ALLOW_ORIGIN=https://seu-app.vercel.app"}), 403

    enviado = request.headers.get("X-Pair-Token", "")
    if not hmac.compare_digest(enviado, token_pareamento()):
        return jsonify({"erro": "Token de pareamento inválido ou ausente.",
                        "precisa_pareamento": True}), 401
    return None


@app.after_request
def cabecalhos_cors(resp):
    origem = (request.headers.get("Origin") or "").rstrip("/")
    if _origem_ok(origem):
        resp.headers["Access-Control-Allow-Origin"] = origem
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Pair-Token"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        resp.headers["Access-Control-Max-Age"] = "600"
    return resp


# -------------------------------------------------------------------- rotas
@app.get("/")
def raiz():
    return send_from_directory("static", "index.html")


@app.get("/api/ping")
def ping():
    """A UI hospedada chama isto para saber se achou o motor e se está pareada."""
    return jsonify({"motor": "capcut-mcp-mac", "porta": request.host,
                    "pareado": True})


@app.get("/api/ambiente")
def ambiente():
    """O que a tela mostra no cabeçalho: dá para trabalhar nesta máquina?"""
    bus = obs.WarningBus()
    try:
        d = tools.TOOLS["capcut.system.doctor"]["handler"]({}, bus)
    except E.CapcutError as exc:
        return jsonify({"ok": False, "erro": exc.message, "correcao": exc.suggestion})
    return jsonify({
        "ok": bool(d.get("ready")),
        "capcut": d.get("capcut_app_version"),
        "projetos_dir": d.get("projects_dir"),
        "projeto_referencia": d.get("reference_project"),
        "ffprobe": bool(d.get("ffprobe")),
        "whisper": bool(d.get("whisper_cli")),
        "modelos_asr": d.get("asr_models_installed") or [],
        "disco_gib": d.get("free_disk_gib"),
        "modelo_llm": MODEL,
        "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "avisos": [{"codigo": w["code"], "texto": w["message"],
                    "correcao": (w.get("context") or {}).get("fix")}
                   for w in bus.warnings],
    })


@app.post("/api/upload")
def upload():
    arq = request.files.get("arquivo")
    if not arq or not arq.filename:
        return jsonify({"erro": "Nenhum arquivo recebido."}), 400
    os.makedirs(UPLOADS, exist_ok=True)
    # nome próprio: o do usuário pode ter barra, acento ou colidir
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(arq.filename))[-80:]
    destino = os.path.join(UPLOADS, f"{uuid.uuid4().hex[:8]}_{base}")
    arq.save(destino)
    tam = os.path.getsize(destino)
    if tam > MAX_UPLOAD_MB * 1024 * 1024:
        os.remove(destino)
        return jsonify({"erro": f"Arquivo acima de {MAX_UPLOAD_MB} MB."}), 413
    return jsonify({"caminho": destino, "nome": base, "bytes": tam})


@app.post("/api/chat")
def chat():
    corpo = request.get_json(force=True)
    sessao = corpo.get("sessao") or uuid.uuid4().hex
    texto = corpo.get("texto") or ""
    anexos = corpo.get("anexos") or []

    fila: "queue.Queue[Any]" = queue.Queue()

    def trabalha():
        try:
            for evento in conversa(sessao, texto, anexos):
                fila.put(evento)
        except Exception as exc:                  # o front precisa saber
            obs.log("web_loop_crash", erro=repr(exc))
            fila.put({"tipo": "erro", "texto": f"{type(exc).__name__}: {exc}"})
        finally:
            fila.put(None)

    threading.Thread(target=trabalha, daemon=True).start()

    def sse():
        yield f"data: {json.dumps({'tipo': 'sessao', 'id': sessao})}\n\n"
        while True:
            ev = fila.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return Response(sse(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/revelar")
def revelar():
    """Abre a pasta do projeto no Finder — o último passo é humano mesmo."""
    caminho = (request.get_json(force=True) or {}).get("caminho", "")
    inst = profile.detect()
    raiz_ok = os.path.abspath(caminho).startswith(
        os.path.abspath(inst.projects_dir)) if inst else False
    if not raiz_ok or not os.path.exists(caminho):
        return jsonify({"erro": "Caminho fora da pasta de projetos do CapCut."}), 400
    import subprocess
    subprocess.run(["open", "-R", caminho], check=False)
    return jsonify({"ok": True})


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", "5151"))
    print(f"\n  Motor local em  http://127.0.0.1:{porta}")
    externas = origens_externas()
    if externas:
        print(f"  UI hospedada autorizada: {', '.join(sorted(externas))}")
        print(f"  Token de pareamento: {token_pareamento()}")
        print("  (cole este token uma vez na UI hospedada; ele fica salvo no "
              "navegador)")
    else:
        print("  Para usar com a UI hospedada, suba assim:")
        print("    CAPCUT_ALLOW_ORIGIN=https://seu-app.vercel.app \\")
        print("      PYTHONPATH=src ./.venv/bin/python web/app.py")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n  ANTHROPIC_API_KEY não está definida — o chat vai falhar na "
              "primeira mensagem.")
    print()
    # host fixo em loopback: isto escreve na pasta de projetos do CapCut local e
    # executa o que a LLM pedir. Não deve ficar acessível na rede.
    app.run(host="127.0.0.1", port=porta, threaded=True)
