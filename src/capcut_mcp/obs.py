"""Observabilidade (spec: O1, O2, O3).

O1 — warning bus: o stdout do L0 é CAPTURADO e convertido em warnings estruturados.
     O `mcp_server.py` do upstream captura e DESCARTA esse stdout, apagando avisos de
     keyframe descartado, download falho e fallback de dimensão. Aqui nada é descartado.
O2 — log estruturado JSONL.
O3 — stdout do processo é do JSON-RPC; nada de log vai para lá.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import time
import uuid
from typing import Any, Dict, List

LOG_DIR = os.path.expanduser("~/Library/Logs/capcut-mcp")
SESSION_ID = uuid.uuid4().hex[:12]

# Padrões de stdout do L0 que viram warning estruturado.
_PATTERNS = [
    (re.compile(r"找不到对应的片段|找不到.*片段|跳过此关键帧"), "KEYFRAME_DISCARDED",
     "Um keyframe foi descartado porque nenhum segmento cobre aquele instante."),
    (re.compile(r"Download failed after|Request failed|Unexpected error during download"),
     "ASSET_DOWNLOAD_FAILED", "Falha ao obter um asset; o projeto pode ficar sem a mídia."),
    (re.compile(r"using default values 1920x1080|using default values"), "DIMENSION_FALLBACK",
     "Não foi possível ler as dimensões da mídia; foi usado 1920x1080."),
    (re.compile(r"not found|未找到"), "UPSTREAM_NOT_FOUND",
     "O upstream reportou um recurso não encontrado."),
    (re.compile(r"[Ww]arning"), "UPSTREAM_WARNING", "O upstream emitiu um aviso."),
]


def _log_path() -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, time.strftime("capcut-mcp-%Y-%m-%d.jsonl"))


def log(event: str, **fields: Any) -> None:
    """Escreve uma linha JSONL. Nunca toca em stdout (O3)."""
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": SESSION_ID, "event": event}
    rec.update(fields)
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # log nunca derruba a operação


class WarningBus:
    """Captura o stdout do L0 e o converte em warnings estruturados."""

    def __init__(self) -> None:
        self.warnings: List[Dict[str, Any]] = []
        self.raw: str = ""

    def add(self, code: str, message: str, **context: Any) -> None:
        self.warnings.append({"code": code, "message": message, "context": context})

    @contextlib.contextmanager
    def capture(self):
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            yield self
        finally:
            sys.stdout = old
            self.raw = buf.getvalue()
            self._parse(self.raw)

    def _parse(self, text: str) -> None:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("[PROGRESS]"):
                continue
            for pattern, code, human in _PATTERNS:
                if pattern.search(line):
                    self.add(code, human, upstream_line=line[:300])
                    break
        if text:
            log("upstream_stdout", lines=len(text.splitlines()),
                warnings=len(self.warnings))
