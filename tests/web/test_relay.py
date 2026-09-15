"""Modo relay: inventário, estado e o lote de eventos.

O transporte com o banco não é testado aqui (exige Postgres); o que é testado é
tudo o que roda na máquina do usuário. O job de tipo 'diagnostico' existe
justamente para provar o transporte ponta a ponta sem gastar token de LLM.
"""
from __future__ import annotations

import os
import shutil
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "web"))
FX = os.path.join(REPO, "fixtures")


@pytest.fixture
def relay(monkeypatch, tmp_path):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    monkeypatch.setenv("CAPCUT_ENTRADA", str(entrada))
    monkeypatch.setenv("CAPCUT_RELAY", "https://exemplo.vercel.app")
    monkeypatch.setenv("CAPCUT_MAQUINA", "mac-de-teste")
    monkeypatch.setenv("CAPCUT_RELAY_TOKEN", "x" * 32)
    for m in list(sys.modules):
        if m == "relay":
            del sys.modules[m]
    import relay as r
    r.ENTRADA = str(entrada)
    return r


def test_inventario_vazio_nao_quebra(relay):
    assert relay.inventario() == []


def test_inventario_le_duracao_e_audio(relay, tmp_path):
    shutil.copy(os.path.join(FX, "video_fala.mp4"), relay.ENTRADA)
    shutil.copy(os.path.join(FX, "tone.mp3"), relay.ENTRADA)
    inv = {a["nome"]: a for a in relay.inventario()}
    assert set(inv) == {"video_fala.mp4", "tone.mp3"}
    assert inv["video_fala.mp4"]["duracao_s"] == pytest.approx(18.767, abs=0.01)
    assert inv["video_fala.mp4"]["tem_audio"] is True
    assert inv["tone.mp3"]["tipo"] == "audio"
    assert inv["video_fala.mp4"]["bytes"] > 0


def test_inventario_ignora_o_que_nao_serve(relay):
    for nome in ("notas.txt", "planilha.xlsx", ".oculto.mp4", "pasta"):
        alvo = os.path.join(relay.ENTRADA, nome)
        if nome == "pasta":
            os.makedirs(alvo)
        else:
            open(alvo, "w").write("x")
    assert relay.inventario() == [], "só mídia deveria entrar na lista"


def test_inventario_marca_arquivo_ilegivel(relay):
    """Um .mp4 que não é vídeo não pode derrubar a batida."""
    open(os.path.join(relay.ENTRADA, "mentira.mp4"), "w").write("nao sou video")
    inv = relay.inventario()
    assert len(inv) == 1 and inv[0]["tipo"] == "ilegível"


def test_inventario_tem_teto(relay):
    """Uma pasta com mil arquivos não pode inflar toda batida."""
    origem = os.path.join(FX, "clip_b.mp4")
    for i in range(90):
        shutil.copy(origem, os.path.join(relay.ENTRADA, f"c{i:03}.mp4"))
    assert len(relay.inventario()) == 80


def test_estado_reporta_o_que_a_ui_mostra(relay):
    e = relay.estado()
    for chave in ("pronto", "capcut", "whisper", "disco_gib", "api_key",
                  "modelo", "entrada"):
        assert chave in e, f"a UI mostra '{chave}'"


def test_envio_agrupa_e_nao_perde_o_resto(relay, monkeypatch):
    enviados = []
    monkeypatch.setattr(relay, "http",
                        lambda rota, carga, **kw: enviados.append(carga) or {})
    envio = relay.Envio(7)
    for i in range(relay.LOTE_EVENTOS + 3):
        envio.add({"tipo": "texto", "texto": str(i)})
    assert len(enviados) == 1, "deveria ter subido um lote cheio"
    assert len(enviados[0]["eventos"]) == relay.LOTE_EVENTOS
    envio.descarrega(estado_final="ok")
    assert len(enviados) == 2
    assert len(enviados[1]["eventos"]) == 3, "o resto não pode ficar para trás"
    assert enviados[1]["estado_final"] == "ok"


def test_envio_marca_o_fim_mesmo_sem_eventos(relay, monkeypatch):
    enviados = []
    monkeypatch.setattr(relay, "http",
                        lambda rota, carga, **kw: enviados.append(carga) or {})
    relay.Envio(9).descarrega(estado_final="erro")
    assert enviados and enviados[0]["estado_final"] == "erro"


def test_falha_ao_subir_evento_nao_derruba_o_job(relay, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("rede caiu")
    monkeypatch.setattr(relay, "http", explode)
    envio = relay.Envio(1)
    envio.add({"tipo": "texto", "texto": "oi"})
    envio.descarrega(estado_final="ok")          # não deve levantar


def test_diagnostico_roda_sem_llm(relay, monkeypatch):
    """É o job que prova o relay sem gastar token — precisa funcionar sozinho."""
    eventos = []
    monkeypatch.setattr(relay, "http", lambda rota, carga, **kw: None)
    envio = relay.Envio(1)
    envio.add = lambda ev: eventos.append(ev)
    fonte = os.path.join(FX, "video_fala.mp4")
    final = relay.roda_diagnostico({"id": 1, "fonte": fonte}, envio)
    assert final == "ok"
    tools_rodadas = [e["nome"] for e in eventos if e["tipo"] == "tool_fim"]
    assert tools_rodadas == ["capcut.system.doctor", "capcut.media.probe"]
    assert all(e["ok"] for e in eventos if e["tipo"] == "tool_fim")
    assert eventos[-1]["tipo"] == "texto"


def test_diagnostico_para_e_reporta_no_primeiro_erro(relay, monkeypatch):
    eventos = []
    monkeypatch.setattr(relay, "http", lambda rota, carga, **kw: None)
    envio = relay.Envio(1)
    envio.add = lambda ev: eventos.append(ev)
    final = relay.roda_diagnostico({"id": 1, "fonte": "/nao/existe.mp4"}, envio)
    assert final == "erro"
    assert eventos[-1]["tipo"] == "erro"


def test_http_nao_repete_erro_4xx(relay, monkeypatch):
    """4xx é erro nosso: insistir só atrasa e polui o log do relay."""
    import urllib.error
    tentativas = []

    def abre(req, timeout=None):
        tentativas.append(1)
        raise urllib.error.HTTPError(req.full_url, 403, "proibido", {}, None)
    monkeypatch.setattr(relay.urllib.request, "urlopen", abre)
    with pytest.raises(RuntimeError, match="403"):
        relay.http("/api/agente/batida", {})
    assert len(tentativas) == 1, "não deveria repetir um 403"


def test_http_repete_erro_5xx(relay, monkeypatch):
    import urllib.error
    tentativas = []

    def abre(req, timeout=None):
        tentativas.append(1)
        raise urllib.error.HTTPError(req.full_url, 502, "gateway", {}, None)
    monkeypatch.setattr(relay.urllib.request, "urlopen", abre)
    monkeypatch.setattr(relay.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        relay.http("/api/agente/batida", {}, tentativas=3)
    assert len(tentativas) == 3, "5xx é transitório e merece nova tentativa"


def test_resultado_util_pega_probe_que_falhou_por_dentro(relay):
    """ACHADO: media.probe devolve ok=True com o arquivo ilegível em `failed`."""
    saida = {"ok": True, "data": {"probed": [],
                                  "failed": [{"source": "/nao/existe.mp4",
                                              "error": "arquivo não encontrado"}]}}
    util, porque = relay.resultado_util("capcut.media.probe", saida)
    assert util is False
    assert "não encontrado" in porque or "existe" in porque


def test_resultado_util_pega_doctor_nao_pronto(relay):
    saida = {"ok": True, "data": {"ready": False, "capcut_app_version": None,
                                  "reference_project": None, "ffprobe": "/x"}}
    util, porque = relay.resultado_util("capcut.system.doctor", saida)
    assert util is False
    assert "CapCut não encontrado" in porque
    assert "projeto de referência" in porque


def test_resultado_util_aprova_o_que_esta_bom(relay):
    assert relay.resultado_util("capcut.media.probe", {
        "ok": True, "data": {"probed": [{"duration_s": 1.0}], "failed": []}})[0]
    assert relay.resultado_util("capcut.system.doctor", {
        "ok": True, "data": {"ready": True}})[0]
    assert relay.resultado_util("capcut.draft.save", {"ok": True, "data": {}})[0]
