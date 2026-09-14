#!/usr/bin/env python3
"""Servidor MCP (JSON-RPC 2.0 sobre stdio) do adaptador CapCut para macOS.

Diferenças deliberadas em relação ao `mcp_server.py` do upstream:

  * `initialize` ECOA a protocolVersion do cliente quando suportada (o upstream fixa
    "2024-11-05" e ignora o que o cliente pediu) — spec C14.
  * `prompts/list` e `resources/list` devolvem lista VAZIA em vez de -32601.
  * Erro é sinalizado nos DOIS níveis: `isError: true` no resultado MCP e `ok: false`
    no envelope — spec E6.
  * O stdout do L0 é capturado e convertido em `warnings[]`, nunca descartado — spec O1.
  * Nenhum log vai para stdout: ele é exclusivamente do JSON-RPC — spec O3.
  * Schemas estritos e validação de argumentos antes de chamar o L0.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from typing import Any, Dict, Optional

from . import errors as E
from . import obs, tools

SERVER_NAME = "capcut-mcp-mac"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = "2024-11-05"

INSTRUCTIONS = (
    "Gera projetos do CapCut Desktop no macOS. Fluxo: capcut.draft.create -> "
    "capcut.draft.save. Depois do save, volte à página inicial do CapCut para ele reler "
    "o disco. Tempos de entrada em segundos; a saída também traz microssegundos (µs), "
    "que é a unidade interna do CapCut. Se algo falhar, chame capcut.system.doctor."
)


def _reply(msg_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _validate(args: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Validação mínima do schema: chaves extras, obrigatórios e tipos primitivos."""
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(args) - set(props))
        if extra:
            raise E.CapcutError(
                E.MISSING_REQUIRED_PARAM,
                f"Parâmetro(s) não reconhecido(s): {', '.join(extra)}.",
                f"Parâmetros aceitos: {', '.join(sorted(props))}.",
            )
    for req in schema.get("required", []):
        if req not in args or args[req] in (None, ""):
            raise E.CapcutError(
                E.MISSING_REQUIRED_PARAM, f"O parâmetro '{req}' é obrigatório.",
                f"Inclua '{req}' na chamada.",
            )
    kinds = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
    for key, value in args.items():
        expected = kinds.get(props.get(key, {}).get("type"))
        if expected and not isinstance(value, expected):
            raise E.CapcutError(
                E.MISSING_REQUIRED_PARAM,
                f"'{key}' deveria ser {props[key]['type']}, veio "
                f"{type(value).__name__}.",
                f"Envie '{key}' como {props[key]['type']}.",
            )
        if isinstance(value, bool) and expected is int:
            raise E.CapcutError(
                E.MISSING_REQUIRED_PARAM, f"'{key}' deveria ser integer, veio boolean.",
                f"Envie '{key}' como número.",
            )


def handle(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = request.get("method")
    msg_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        asked = params.get("protocolVersion")
        agreed = asked if asked in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        obs.log("initialize", client=params.get("clientInfo"), asked=asked, agreed=agreed)
        return _reply(msg_id, {
            "protocolVersion": agreed,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return _reply(msg_id, {})

    if method == "tools/list":
        return _reply(msg_id, {"tools": tools.tool_list()})

    if method in ("prompts/list", "resources/list", "resources/templates/list"):
        key = "prompts" if method.startswith("prompts") else \
            ("resourceTemplates" if "templates" in method else "resources")
        return _reply(msg_id, {key: []})

    if method == "tools/call":
        return _call_tool(msg_id, params)

    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Método não suportado: {method}"}}


def _call_tool(msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name", "")
    args = params.get("arguments") or {}
    spec = tools.TOOLS.get(name)
    started = time.time()
    bus = obs.WarningBus()

    if spec is None:
        env = E.err_envelope(
            E.CapcutError(E.OPERATION_NOT_SUPPORTED, f"Tool desconhecida: {name}",
                          f"Tools disponíveis: {', '.join(tools.TOOLS)}."),
            meta={"tool": name})
        return _reply(msg_id, _content(env, is_error=True))

    try:
        _validate(args, spec["schema"])
        data = spec["handler"](args, bus)
        meta = {"tool": name, "elapsed_ms": int((time.time() - started) * 1000),
                "session": obs.SESSION_ID}
        env = E.ok_envelope(data, warnings=bus.warnings, meta=meta)
        obs.log("tool_ok", tool=name, elapsed_ms=meta["elapsed_ms"],
                warnings=len(bus.warnings))
        return _reply(msg_id, _content(env, is_error=False))
    except BaseException as exc:  # noqa: BLE001 — nada escapa sem tradução
        meta = {"tool": name, "elapsed_ms": int((time.time() - started) * 1000),
                "session": obs.SESSION_ID}
        env = E.err_envelope(exc, warnings=bus.warnings, meta=meta)
        obs.log("tool_error", tool=name, code=env["error"]["code"],
                message=env["error"]["message"], traceback=traceback.format_exc()[-1500:])
        return _reply(msg_id, _content(env, is_error=True))


def _content(envelope: Dict[str, Any], is_error: bool) -> Dict[str, Any]:
    return {
        "content": [{"type": "text",
                     "text": json.dumps(envelope, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def main() -> None:
    obs.log("server_start", version=SERVER_VERSION, argv=sys.argv[1:])
    print(f"{SERVER_NAME} {SERVER_VERSION} pronto", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"JSON inválido: {exc}"}}) + "\n")
            sys.stdout.flush()
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    obs.log("server_stop")


if __name__ == "__main__":
    main()
