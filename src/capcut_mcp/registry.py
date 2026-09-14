"""Registry de drafts em disco (spec: D3, D4 · decisão Q7).

Motivo: o `DRAFT_CACHE` do L0 é um OrderedDict em memória, por processo, sem
persistência. Reiniciar o servidor MCP apagava o draft, e `save_draft` de um draft
ausente retornava `success: true` com `draft_url: null` sem escrever nada.

Aqui o registry guarda o **plano declarativo** (a intenção), não o objeto Python.
Isso permite: (a) erro explícito DRAFT_NOT_FOUND, (b) replay do plano após reinício,
(c) no futuro, `draft.rebuild` para reordenar — que o upstream não suporta.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from . import errors as E

REGISTRY_DIR = os.environ.get(
    "CAPCUT_REGISTRY_DIR", os.path.expanduser("~/Library/Application Support/capcut-mcp")
)
REGISTRY_PATH = os.path.join(REGISTRY_DIR, "registry.json")


def _load() -> Dict[str, Any]:
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"drafts": {}, "version": 1}


def _save_atomic(data: Dict[str, Any]) -> None:
    os.makedirs(REGISTRY_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, REGISTRY_PATH)   # atômico no mesmo volume
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def create(draft_id: str, name: str, width: int, height: int, fps: int) -> Dict[str, Any]:
    data = _load()
    entry = {
        "draft_id": draft_id,
        "name": name,
        "canvas": {"width": width, "height": height, "fps": fps},
        "plan": [{"op": "create", "width": width, "height": height, "fps": fps}],
        "state": "DRAFTING",
        "created_at": time.time(),
        "updated_at": time.time(),
        "saved_to": None,
    }
    data["drafts"][draft_id] = entry
    _save_atomic(data)
    return entry


def get(draft_id: str) -> Dict[str, Any]:
    entry = _load()["drafts"].get(draft_id)
    if entry is None:
        raise E.CapcutError(
            E.DRAFT_NOT_FOUND,
            f"O draft '{draft_id}' não existe.",
            "Crie um draft com capcut.draft.create e use o draft_id retornado. "
            "Nenhum draft é criado implicitamente.",
            draft_id=draft_id,
        )
    return entry


def append_plan(draft_id: str, step: Dict[str, Any]) -> None:
    data = _load()
    entry = data["drafts"].get(draft_id)
    if entry is None:
        raise E.CapcutError(
            E.DRAFT_NOT_FOUND, f"O draft '{draft_id}' não existe.",
            "Crie um draft com capcut.draft.create.", draft_id=draft_id,
        )
    entry["plan"].append(step)
    entry["state"] = "DRAFTING"
    entry["updated_at"] = time.time()
    _save_atomic(data)


def mark_saved(draft_id: str, path: str) -> None:
    data = _load()
    entry = data["drafts"].get(draft_id)
    if entry:
        entry["state"] = "SAVED"
        entry["saved_to"] = path
        entry["updated_at"] = time.time()
        _save_atomic(data)


def listing() -> List[Dict[str, Any]]:
    out = [
        {k: v for k, v in e.items() if k != "plan"} | {"steps": len(e.get("plan", []))}
        for e in _load()["drafts"].values()
    ]
    return sorted(out, key=lambda e: e.get("updated_at", 0), reverse=True)


def discard(draft_id: str) -> None:
    data = _load()
    data["drafts"].pop(draft_id, None)
    _save_atomic(data)
