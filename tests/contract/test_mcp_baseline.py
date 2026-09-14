"""Phase 2 — teste de contrato do servidor MCP, pelo protocolo real (stdio).

Cada teste corresponde a um item do "Teste verificável" da Phase 2 no
IMPLEMENTATION_PLAN. Nada aqui importa o L1 diretamente: fala JSON-RPC com o
processo, como o Codex faria.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PY = os.path.join(REPO, ".venv", "bin", "python")
CJK = re.compile(r"[　-鿿]")


class Client:
    """Cliente MCP mínimo sobre stdio."""

    def __init__(self) -> None:
        env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "src"))
        self.proc = subprocess.Popen(
            [PY, "-m", "capcut_mcp.server"], cwd=REPO, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._id = 0
        self.stdout_lines: list[str] = []

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method,
               "params": params or {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        self.stdout_lines.append(line)
        return json.loads(line)

    def notify(self, method: str) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def call(self, tool: str, args: dict | None = None) -> tuple[dict, bool]:
        res = self.rpc("tools/call", {"name": tool, "arguments": args or {}})
        result = res["result"]
        envelope = json.loads(result["content"][0]["text"])
        return envelope, bool(result.get("isError"))

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


@pytest.fixture
def client():
    c = Client()
    c.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "contract-test", "version": "1"}})
    c.notify("notifications/initialized")
    yield c
    c.close()


@pytest.fixture(scope="module")
def projects_dir():
    sys.path.insert(0, os.path.join(REPO, "src"))
    from capcut_mcp import profile
    return profile.find_projects_dir()


# 1 -------------------------------------------------------------------------
def test_initialize_ecoa_protocol_version():
    c = Client()
    try:
        res = c.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        assert res["result"]["protocolVersion"] == "2025-06-18"
        assert res["result"]["serverInfo"]["name"] == "capcut-mcp-mac"
        assert res["result"]["instructions"]
    finally:
        c.close()


def test_initialize_cai_para_default_se_protocolo_desconhecido():
    c = Client()
    try:
        res = c.rpc("initialize", {"protocolVersion": "1999-01-01"})
        assert res["result"]["protocolVersion"] == "2024-11-05"
    finally:
        c.close()


# 2 -------------------------------------------------------------------------
def test_tools_list_com_schema_estrito(client):
    tools = client.rpc("tools/list")["result"]["tools"]
    nomes = [t["name"] for t in tools]
    assert nomes == [
        "capcut.system.doctor", "capcut.draft.create", "capcut.draft.save",
        "capcut.media.probe", "capcut.catalog.list",
        "capcut.video.add", "capcut.image.add", "capcut.audio.add", "capcut.text.add",
        "capcut.subtitle.add", "capcut.draft.inspect", "capcut.draft.rebuild"]
    for t in tools:
        assert t["inputSchema"]["additionalProperties"] is False, t["name"]
        assert t["description"] and len(t["description"]) > 80, t["name"]


def test_nenhuma_tool_proibida_e_exposta(client):
    names = [t["name"] for t in client.rpc("tools/list")["result"]["tools"]]
    proibidas = ("reorder", "remove", "render", "export", "reload", "draft_url")
    assert not [n for n in names if any(p in n for p in proibidas)]


# 3 -------------------------------------------------------------------------
@pytest.mark.parametrize("method,key", [
    ("prompts/list", "prompts"),
    ("resources/list", "resources"),
    ("resources/templates/list", "resourceTemplates"),
])
def test_prompts_e_resources_devolvem_lista_vazia(client, method, key):
    res = client.rpc(method)
    assert "error" not in res, f"{method} devolveu erro em vez de lista vazia"
    assert res["result"][key] == []


# 4 -------------------------------------------------------------------------
def test_draft_create_devolve_id_e_nenhuma_url_externa(client):
    env, is_err = client.call("capcut.draft.create", {
        "name": f"ct-{uuid.uuid4().hex[:6]}", "width": 1080, "height": 1920})
    assert not is_err and env["ok"], env
    assert env["data"]["draft_id"].startswith("dfd_cat_")
    assert env["data"]["ratio_label"] == "9:16"
    assert env["data"]["ratio_is_exact"] is True
    blob = json.dumps(env)
    assert "http://" not in blob and "https://" not in blob, "URL externa no payload"


def test_draft_create_recusa_dimensao_invalida(client):
    env, is_err = client.call("capcut.draft.create",
                              {"name": "x", "width": 0, "height": 1920})
    assert is_err and env["error"]["code"] == "INVALID_DIMENSIONS"


def test_draft_create_recusa_parametro_desconhecido(client):
    env, is_err = client.call("capcut.draft.create", {"name": "x", "altura": 1920})
    assert is_err and env["error"]["code"] == "MISSING_REQUIRED_PARAM"
    assert "altura" in env["error"]["message"]


def test_ratio_inexato_gera_warning(client):
    env, is_err = client.call("capcut.draft.create", {
        "name": f"ct-{uuid.uuid4().hex[:6]}", "width": 1080, "height": 1350})
    assert not is_err
    assert env["data"]["ratio_is_exact"] is False
    assert any(w["code"] == "RATIO_INEXACT" for w in env["warnings"])


# 5 -------------------------------------------------------------------------
def test_save_de_draft_inexistente_erra_e_nao_escreve_nada(client, projects_dir):
    antes = set(os.listdir(projects_dir))
    env, is_err = client.call("capcut.draft.save", {"draft_id": "dfd_cat_nao_existe"})
    assert is_err, "deveria ser erro"
    assert env["error"]["code"] == "DRAFT_NOT_FOUND"
    assert env["ok"] is False
    assert set(os.listdir(projects_dir)) == antes, "escreveu algo em disco"


# 6 -------------------------------------------------------------------------
def test_save_de_draft_vazio_erra_com_draft_empty(client):
    env, _ = client.call("capcut.draft.create",
                         {"name": f"ct-{uuid.uuid4().hex[:6]}"})
    draft_id = env["data"]["draft_id"]
    env, is_err = client.call("capcut.draft.save", {"draft_id": draft_id})
    assert is_err and env["error"]["code"] == "DRAFT_EMPTY"
    assert "allow_empty" in env["error"]["suggestion"]


# 7 -------------------------------------------------------------------------
def test_save_em_projeto_existente_sem_overwrite_erra(client, projects_dir):
    existentes = [d for d in os.listdir(projects_dir)
                  if os.path.isdir(os.path.join(projects_dir, d))
                  and not d.startswith(".")]
    if not existentes:
        pytest.skip("nenhum projeto existente para colidir")
    env, _ = client.call("capcut.draft.create",
                         {"name": f"ct-{uuid.uuid4().hex[:6]}"})
    draft_id = env["data"]["draft_id"]
    env, is_err = client.call("capcut.draft.save", {
        "draft_id": draft_id, "project_name": existentes[0], "allow_empty": True})
    assert is_err and env["error"]["code"] in ("TARGET_EXISTS", "PROJECT_LOCKED")


# 8, 9 ---------------------------------------------------------------------
def test_todo_erro_tem_suggestion_sem_cjk_e_sem_traceback(client):
    casos = [
        ("capcut.draft.save", {"draft_id": "nope"}),
        ("capcut.draft.create", {"name": "x", "width": -5}),
        ("capcut.draft.create", {"foo": "bar"}),
        ("capcut.inexistente", {}),
    ]
    for tool, args in casos:
        env, is_err = client.call(tool, args)
        assert is_err, (tool, args)
        err = env["error"]
        assert err["suggestion"].strip(), f"{tool}: suggestion vazia"
        assert not CJK.search(err["message"]), f"{tool}: mensagem com CJK"
        assert "Traceback" not in err["message"]
        assert ", line " not in err["message"]


# 10 ------------------------------------------------------------------------
def test_stdout_contem_apenas_jsonrpc_valido(client):
    client.rpc("tools/list")
    client.call("capcut.system.doctor")
    for line in client.stdout_lines:
        msg = json.loads(line)
        assert msg["jsonrpc"] == "2.0"


def test_doctor_reporta_ambiente(client):
    env, is_err = client.call("capcut.system.doctor")
    assert not is_err and env["ok"]
    d = env["data"]
    assert d["upstream_commit"].startswith("b83be74"), "upstream deve estar fixado"
    assert d["ffprobe"], "ffprobe obrigatório"
    if d.get("ready"):
        assert d["profile"]["content_file"] == "draft_info.json"
        assert d["profile"]["multi_timeline"] is True
        assert d["projects_dir"].endswith("com.lveditor.draft")


# 11 ------------------------------------------------------------------------
def test_draft_id_sobrevive_a_reinicio_do_servidor(projects_dir):
    c1 = Client()
    c1.rpc("initialize", {"protocolVersion": "2024-11-05"})
    env, _ = c1.call("capcut.draft.create",
                     {"name": f"ct-replay-{uuid.uuid4().hex[:6]}"})
    draft_id = env["data"]["draft_id"]
    c1.close()

    c2 = Client()   # processo novo: o DRAFT_CACHE em memória está vazio
    try:
        c2.rpc("initialize", {"protocolVersion": "2024-11-05"})
        env, is_err = c2.call("capcut.draft.save",
                              {"draft_id": draft_id, "allow_empty": True,
                               "project_name": f"ct-replay-{uuid.uuid4().hex[:6]}"})
        assert not is_err, env
        assert any(w["code"] == "DRAFT_REPLAYED" for w in env["warnings"]), \
            "deveria avisar que reconstruiu pelo plano"
        shutil_target = env["data"]["project_path"]
        assert os.path.isdir(shutil_target)
        import shutil
        shutil.rmtree(shutil_target)     # limpeza
    finally:
        c2.close()
