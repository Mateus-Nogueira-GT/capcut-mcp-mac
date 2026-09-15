"""O front: tradução de nomes, execução de tool e o resumo que vai para a tela.

O loop do agente em si não é testado aqui — ele depende da API da Anthropic. O
que é testado é tudo o que fica entre a decisão da LLM e o disco, que é a parte
que este repositório controla.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "web"))
FX = os.path.join(REPO, "fixtures")

from capcut_mcp import registry, tools  # noqa: E402

import app as front  # noqa: E402

VIDEO = os.path.join(FX, "video_teste.mp4")


# ------------------------------------------------- tradução de nome de tool
def test_todo_nome_exposto_vai_e_volta():
    """Os nomes do MCP têm ponto; a Messages API não aceita. A volta tem de ser exata."""
    for nome in tools.enabled():
        api = front.para_api(nome)
        assert "." not in api, f"{api} ainda tem ponto"
        assert front.de_api(api) == nome, f"{nome} -> {api} -> {front.de_api(api)}"


def test_nome_com_underscore_no_ultimo_segmento():
    """`from_transcript` e `add_many` têm underscore legítimo — não pode virar ponto."""
    assert front.de_api("capcut_subtitle_from_transcript") == \
        "capcut.subtitle.from_transcript"
    assert front.de_api("capcut_text_add_many") == "capcut.text.add_many"


def test_nome_estranho_passa_intacto():
    assert front.de_api("outra_coisa") == "outra_coisa"


# -------------------------------------------------- superfície para a LLM
def test_tools_para_api_tem_cache_e_strict():
    api = front.tools_para_api()
    assert len(api) == len(tools.enabled())
    assert all(t["strict"] for t in api), "os schemas já são fechados; strict é grátis"
    assert all(t["input_schema"]["additionalProperties"] is False for t in api)
    # o prefixo de ~5,4k tokens repete em todo turno: sem cache, dobra a conta
    assert api[-1]["cache_control"] == {"type": "ephemeral"}
    assert sum("cache_control" in t for t in api) == 1, "um breakpoint basta"


def test_sistema_cita_apenas_tools_expostas():
    import re
    expostas = set(tools.enabled())
    citadas = set(re.findall(r"capcut\.[a-z_]+\.[a-z_]+", front.SISTEMA))
    assert citadas <= expostas, f"o prompt manda chamar o que não existe: {citadas - expostas}"


# ------------------------------------------------------- execução de tool
def test_tool_desconhecida_nao_derruba():
    r = front.executa_tool("capcut_nao_existe", {})
    assert r["ok"] is False and r["error"]["code"] == "UNKNOWN_TOOL"


def test_tool_implementada_mas_fora_da_superficie_e_recusada():
    """`image.add` existe e é testada, mas está fora do escopo exposto."""
    assert "capcut.image.add" in tools.TOOLS
    assert "capcut.image.add" not in tools.enabled()
    r = front.executa_tool("capcut_image_add", {"source": VIDEO})
    assert r["error"]["code"] == "UNKNOWN_TOOL"


def test_erro_de_dominio_chega_com_suggestion():
    """O loop precisa da suggestion para se corrigir sozinho no turno seguinte."""
    r = front.executa_tool("capcut_draft_create", {"name": "x", "width": -1,
                                                   "height": 1920})
    assert r["ok"] is False
    assert r["error"]["message"] and r["error"]["suggestion"]


def test_argumento_faltando_nao_vira_crash():
    r = front.executa_tool("capcut_video_cut", {})
    assert r["ok"] is False
    assert r["error"]["code"] != "INTERNAL_ERROR", \
        "parâmetro ausente é erro de domínio, não falha interna"


def test_excecao_inesperada_e_capturada(monkeypatch):
    """Uma tool que estoura não pode matar o loop — o turno seguinte precisa do erro."""
    def explode(args, bus):
        raise RuntimeError("boom")
    monkeypatch.setitem(tools.TOOLS["capcut.system.doctor"], "handler", explode)
    r = front.executa_tool("capcut_system_doctor", {})
    assert r["ok"] is False
    assert r["error"]["code"] == "INTERNAL_ERROR"
    assert "boom" in r["error"]["message"]


# ------------------------------------------ o resumo que o usuário lê
def test_resumo_do_probe_le_a_chave_certa():
    """Regressão: lia `media` em vez de `probed` e mostrava '0.0s, NonexNone'."""
    r = front.executa_tool("capcut_media_probe", {"sources": [VIDEO]})
    resumo = front.resumo_da_tool("capcut.media.probe", r)
    assert "None" not in resumo, resumo
    assert "6.0s" in resumo and "1080x1920" in resumo, resumo


def test_resumo_do_probe_avisa_video_sem_audio(tmp_path):
    import subprocess
    mudo = str(tmp_path / "mudo.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", VIDEO, "-an", "-c:v",
                    "copy", mudo], check=True)
    r = front.executa_tool("capcut_media_probe", {"sources": [mudo]})
    assert "SEM áudio" in front.resumo_da_tool("capcut.media.probe", r)


def test_resumo_de_erro_mostra_codigo_e_mensagem():
    r = front.executa_tool("capcut_video_cut", {})
    resumo = front.resumo_da_tool("capcut.video.cut", r)
    assert resumo.startswith(r["error"]["code"])


def test_resumo_nunca_devolve_json_cru():
    """Se cair no default, ainda tem de ser legível — não um dict despejado."""
    for nome in tools.enabled():
        resumo = front.resumo_da_tool(nome, {"ok": True, "data": {}})
        assert resumo and "{" not in resumo, f"{nome}: {resumo!r}"


def test_fluxo_completo_pelo_caminho_do_front():
    """A sequência que a LLM produz, executada pelo mesmo código que ela usa."""
    nome_proj = f"Front Test {uuid.uuid4().hex[:6]}"
    r = front.executa_tool("capcut_draft_create",
                           {"name": nome_proj, "width": 1080, "height": 1920})
    assert r["ok"], r
    did = r["data"]["draft_id"]
    try:
        passos = [
            ("capcut_video_cut", {"draft_id": did, "source": VIDEO,
                                  "keep": [[0.0, 2.0], [3.0, 5.0]]}),
            ("capcut_subtitle_add", {"draft_id": did, "segments": [
                {"start": 0.2, "end": 1.8, "text": "primeira"},
                {"start": 2.2, "end": 3.6, "text": "segunda"}]}),
            ("capcut_text_add_many", {"draft_id": did, "items": [
                {"text": "TÍTULO", "timeline_start": 0.1, "duration": 1.5}]}),
            ("capcut_draft_validate", {"draft_id": did}),
        ]
        for nome_api, args in passos:
            saida = front.executa_tool(nome_api, args)
            assert saida["ok"], f"{nome_api}: {saida.get('error')}"
            resumo = front.resumo_da_tool(front.de_api(nome_api), saida)
            assert resumo and "None" not in resumo, f"{nome_api}: {resumo!r}"
    finally:
        registry.discard(did)


# ---------------------------------------------------------------- HTTP
@pytest.fixture
def cliente():
    front.app.config["TESTING"] = True
    return front.app.test_client()


def test_pagina_carrega(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    corpo = r.data.decode()
    assert "Anexe um vídeo" in corpo
    assert "/api/chat" in corpo and "/api/upload" in corpo


def test_ambiente_responde_o_que_a_tela_usa(cliente):
    d = cliente.get("/api/ambiente").get_json()
    # regressão: a tela lia `app_version` e mostrava "CapCut não encontrado"
    for chave in ("ok", "capcut", "whisper", "api_key", "modelo_llm",
                  "projetos_dir", "disco_gib", "projeto_referencia"):
        assert chave in d, f"a tela usa '{chave}' e o endpoint não devolve"


def test_upload_sem_arquivo(cliente):
    assert cliente.post("/api/upload").status_code == 400


def test_upload_sanitiza_o_nome(cliente):
    import io
    r = cliente.post("/api/upload", data={
        "arquivo": (io.BytesIO(b"x" * 64), "../../../etc/pas swd;rm -rf.mp4")})
    j = r.get_json()
    assert r.status_code == 200
    assert ".." not in j["caminho"] and "/etc/" not in j["caminho"]
    assert j["caminho"].startswith(front.UPLOADS)
    os.remove(j["caminho"])


def test_revelar_recusa_caminho_fora_dos_projetos(cliente):
    r = cliente.post("/api/revelar", json={"caminho": "/etc/passwd"})
    assert r.status_code == 400


def test_parametro_nao_reconhecido_e_recusado():
    """Segunda camada: o front valida contra o schema, como o servidor MCP faz."""
    r = front.executa_tool("capcut_draft_create",
                           {"name": "x", "width": 1080, "height": 1920,
                            "inventado": True})
    assert r["ok"] is False
    assert "inventado" in r["error"]["message"]
    assert r["error"]["code"] != "INTERNAL_ERROR"


def test_tipo_errado_e_recusado():
    r = front.executa_tool("capcut_draft_create",
                           {"name": "x", "width": "mil", "height": 1920})
    assert r["ok"] is False and r["error"]["code"] != "INTERNAL_ERROR"
