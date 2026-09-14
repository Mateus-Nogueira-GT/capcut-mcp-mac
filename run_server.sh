#!/bin/sh
# Entrypoint do servidor MCP. O Codex chama isto.
HERE=$(cd "$(dirname "$0")" && pwd)
exec "$HERE/.venv/bin/python" -m capcut_mcp.server "$@"
