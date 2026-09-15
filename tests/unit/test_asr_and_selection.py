"""Transcrição (ASR) e seleção de cortes — plano de testes da SPEC_ASR_E_SELECAO.

Numeração igual à da spec: T1.x = transcrição, T2.x = encostar o corte na fala,
T3.x = remapeamento de tempo. T3.7 não está aqui porque é verificação visual no
CapCut; o registro dela fica em evidence/asr/RESULT.md.

Os testes que dependem do whisper.cpp usam `language="pt"` para bater com o cache
gravado; é o mesmo caminho de código, só sem pagar a inferência de novo.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.abspath(os.path.join(REPO, "fixtures"))

from capcut_mcp import (asr, errors as E, handlers_media as HM, media,  # noqa: E402
                        obs, registry, timemap, tools, validator as V)

WAV = os.path.join(FX, "fala_pt.wav")           # 16,72 s, fala PT-BR conhecida
VIDEO_FALA = os.path.join(FX, "video_fala.mp4")  # 18,77 s, mesma fala
VIDEO_MUDO = os.path.join(FX, "video_teste.mp4")
GROUND_TRUTH = os.path.join(FX, "fala_pt.txt")
US = 1_000_000

tem_whisper = pytest.mark.skipif(
    shutil.which(asr.BIN) is None or asr.DEFAULT_MODEL not in asr.installed_models(),
    reason="whisper.cpp ou o modelo default não estão instalados")


def call(tool: str, **args):
    bus = obs.WarningBus()
    return tools.TOOLS[tool]["handler"](args, bus), bus


@pytest.fixture
def draft():
    d, _ = call("capcut.draft.create", name=f"asr-{uuid.uuid4().hex[:8]}",
                width=1080, height=1920)
    yield d["draft_id"]
    registry.discard(d["draft_id"])


@pytest.fixture(scope="module")
def transcript():
    if shutil.which(asr.BIN) is None:
        pytest.skip("whisper.cpp ausente")
    return asr.transcribe(WAV, language="pt")


# O whisper NORMALIZA número e moeda: "cento e vinte reais" sai "R$ 120", "três
# dias" sai "3 dias". Não é erro, é convenção de escrita — mas compararia falso
# contra o texto lido em voz alta. As duas pontas passam por isto.
NORMALIZACOES = [("cento e vinte", "120"), ("três", "3"), ("reais", "r$"),
                 ("r$ 120", "120 r$")]


def palavras_de(texto: str) -> set:
    t = texto.lower()
    for de, para in NORMALIZACOES:
        t = t.replace(de, para)
    limpo = "".join(c if c.isalnum() or c in " -$" else " " for c in t)
    return {p for p in limpo.split() if len(p) > 2 or p in ("r$", "120", "3")}


# ============================================================ T1 transcrição
@tem_whisper
def test_t1_2_palavras_e_timestamps(transcript):
    """T1.2 — fala conhecida: palavras corretas e timestamps dentro do áudio."""
    esperado = palavras_de(open(GROUND_TRUTH, encoding="utf-8").read())
    obtido = palavras_de(" ".join(b["text"] for b in transcript["blocks"]))
    faltando = esperado - obtido
    # 1 palavra de 38 é o erro medido do 'small' nesta fixture: "prazo" sai
    # "trase". Está registrado em evidence/asr/RESULT.md em vez de escondido aqui.
    assert len(faltando) <= 1, f"palavras perdidas: {sorted(faltando)}"
    if faltando:
        print(f"\n  erro de reconhecimento conhecido: {sorted(faltando)}")

    dur = transcript["duration_s"]
    for b in transcript["blocks"]:
        assert 0 <= b["start"] < b["end"] <= dur + 0.3, b
    for a, b in zip(transcript["blocks"], transcript["blocks"][1:]):
        assert b["start"] >= a["start"], "blocos fora de ordem"
    assert transcript["language"] == "pt"


@tem_whisper
def test_t1_3_segments_alimentam_subtitle_add(draft, transcript):
    """T1.3 — o `segments` do transcribe entra no subtitle.add sem transformação."""
    r, _ = call("capcut.media.transcribe", source=WAV, language="pt")
    d, _ = call("capcut.video.add", draft_id=draft, source=VIDEO_FALA)
    s, _ = call("capcut.subtitle.add", draft_id=draft, segments=r["segments"])
    assert s["blocks_imported"] == len(r["segments"])


@tem_whisper
def test_t1_4_blocos_dentro_da_faixa(transcript):
    """T1.4 — 26 caracteres por bloco; duração entre 0,8 e 4,0 s."""
    for b in transcript["blocks"]:
        assert len(b["text"]) <= asr.DEFAULT_MAX_CHARS + 4, \
            f"bloco longo demais para a tela: {b['text']!r}"
        assert b["end"] - b["start"] <= asr.DEFAULT_MAX_BLOCK_S + 0.5, b
    # o último bloco pode ficar curto: não há com o que fundir depois dele
    for b in transcript["blocks"][:-1]:
        assert b["end"] - b["start"] >= asr.MIN_BLOCK_S - 1e-6, \
            f"bloco curto demais para ser lido: {b}"


@tem_whisper
def test_t1_5_cache_na_segunda_chamada(transcript):
    """T1.5 — segunda chamada vem do cache, em menos de 100 ms."""
    t0 = time.time()
    r = asr.transcribe(WAV, language="pt")
    elapsed = time.time() - t0
    assert r["cached"] is True
    assert elapsed < 0.1, f"cache levou {elapsed * 1000:.0f} ms"
    assert r["blocks"] == transcript["blocks"]


@tem_whisper
def test_t1_6_forma_compacta_nao_estoura_contexto(transcript):
    """T1.6 — a forma que o agente lê tem teto, e a paginação é honesta."""
    longo = []
    for volta in range(60):
        for b in transcript["blocks"]:
            longo.append({**b, "start": b["start"] + volta * 20,
                          "end": b["end"] + volta * 20})
    texto, truncado = asr.compact(longo, offset=0, limit=200)
    assert truncado is True, "600 blocos e limit=200 tem de sinalizar truncagem"
    assert len(texto) / 4 < 4000, "a página não pode passar de ~4k tokens"
    assert len(texto.splitlines()) == 200

    resto, ainda = asr.compact(longo, offset=200, limit=200)
    assert resto.splitlines()[0] != texto.splitlines()[0], "offset tem de avançar"
    assert ainda is True
    _, fim = asr.compact(longo, offset=400, limit=200)
    assert fim is False, "a última página não sinaliza mais nada adiante"


def test_t1_7_binario_ausente(monkeypatch):
    """T1.7 — sem o binário, erro acionável com o comando do brew."""
    monkeypatch.setattr(asr.shutil, "which", lambda _: None)
    with pytest.raises(E.CapcutError) as exc:
        asr.transcribe(WAV)
    assert exc.value.code == E.ASR_UNAVAILABLE
    assert "brew install whisper-cpp" in exc.value.suggestion


def test_t1_8_modelo_grande_demais():
    """T1.8 — large-v3 é recusado antes de tentar carregar 3,1 GB."""
    with pytest.raises(E.CapcutError) as exc:
        asr.model_path("large-v3")
    assert exc.value.code == E.ASR_MODEL_TOO_LARGE
    assert "medium" in exc.value.suggestion


def test_t1_8b_modelo_nao_baixado(monkeypatch):
    monkeypatch.setattr(asr.os.path, "isfile", lambda _: False)
    with pytest.raises(E.CapcutError) as exc:
        asr.model_path("small")
    assert exc.value.code == E.ASR_MODEL_MISSING
    assert "curl" in exc.value.suggestion


@tem_whisper
def test_t1_9_sem_fala(tmp_path):
    """T1.9 — áudio só com silêncio não inventa legenda."""
    silencio = str(tmp_path / "silencio.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=16000:cl=mono", "-t", "3", silencio], check=True)
    with pytest.raises(E.CapcutError) as exc:
        asr.transcribe(silencio, language="pt", model="base", refresh=True)
    assert exc.value.code == E.NO_SPEECH_DETECTED
    # Medido: em silêncio puro o whisper.cpp alucina "[MÚSICA DE FUNDO]". Se isso
    # passasse como bloco, viraria legenda na tela.
    assert exc.value.context["non_speech_blocks"], \
        "a alucinação tem de ser reportada, não só engolida"


def test_t1_9b_video_sem_faixa_de_audio(tmp_path):
    """Sem faixa de áudio o erro sai do probe, antes de acordar o whisper."""
    mudo = str(tmp_path / "mudo.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", VIDEO_MUDO, "-an",
                    "-c:v", "copy", mudo], check=True)
    with pytest.raises(E.CapcutError) as exc:
        asr.transcribe(mudo, language="pt")
    assert exc.value.code == E.NO_SPEECH_DETECTED
    assert "áudio" in exc.value.message


@tem_whisper
def test_t1_10_degradacao_com_ruido_e_reportada(tmp_path, transcript):
    """T1.10 — com ruído a precisão cai; o teste registra a queda, não a esconde.

    A confiança média por palavra (`p` do whisper.cpp) é o indicador; se o ruído
    não a derrubasse, o campo não serviria para nada.
    """
    ruidoso = str(tmp_path / "ruido.wav")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", WAV, "-f", "lavfi", "-i",
         "anoisesrc=r=16000:a=0.06", "-filter_complex",
         "[0:a][1:a]amix=inputs=2:duration=first", "-ar", "16000", "-ac", "1",
         ruidoso], check=True)
    sujo = asr.transcribe(ruidoso, language="pt")

    def confianca(r):
        ps = [w["p"] for w in r["words"] if w.get("p") is not None]
        return sum(ps) / len(ps) if ps else 0.0

    limpo_p, sujo_p = confianca(transcript), confianca(sujo)
    esperado = palavras_de(open(GROUND_TRUTH, encoding="utf-8").read())
    acerto_limpo = len(esperado & palavras_de(
        " ".join(b["text"] for b in transcript["blocks"]))) / len(esperado)
    acerto_sujo = len(esperado & palavras_de(
        " ".join(b["text"] for b in sujo["blocks"]))) / len(esperado)
    print(f"\n  ruído a=0.06: confiança {limpo_p:.3f} -> {sujo_p:.3f} | "
          f"acerto {acerto_limpo:.0%} -> {acerto_sujo:.0%}")
    # O que se afirma é o que se mediu: com ruído moderado o 'small' ainda
    # transcreve, e a confiança por palavra cai. A taxa de acerto por palavra
    # nesta fixture curta oscila nas duas direções — afirmar que ela SEMPRE cai
    # seria inventar um resultado. A degradação fica registrada, não assumida.
    assert sujo["block_count"] > 0, "com ruído moderado ainda tem de transcrever algo"
    assert sujo_p < limpo_p, "a confiança por palavra tem de cair com ruído"
    assert acerto_sujo >= 0.5, "queda além disto tornaria a legenda inútil"


def test_t1_tokens_especiais_nao_vazam():
    """Regressão: '[_TT_163]' vazou colado numa palavra por regex frouxa."""
    tokens = [{"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
              {"text": " autom", "offsets": {"from": 1000, "to": 1200}, "p": 0.9},
              {"text": "ática.", "offsets": {"from": 1200, "to": 1400}, "p": 0.8},
              {"text": "[_TT_163]", "offsets": {"from": 1400, "to": 1400}},
              {"text": "[_EOT_]", "offsets": {"from": 1400, "to": 1400}}]
    words = asr._tokens_to_words(tokens)
    assert [w["word"] for w in words] == ["automática."]
    assert words[0]["p"] == 0.8, "a confiança da palavra é a do token mais fraco"


# ================================================ T2 encostar o corte na fala
PALAVRAS = [
    {"start": 1.00, "end": 1.40, "word": "Bem-vindo"},
    {"start": 1.50, "end": 1.70, "word": "ao"},
    {"start": 1.80, "end": 2.60, "word": "teste"},
    {"start": 5.00, "end": 5.90, "word": "preço,"},
    {"start": 6.10, "end": 6.80, "word": "prazo"},
    {"start": 7.00, "end": 7.90, "word": "qualidade."},
]


def test_t2_1_pedido_no_meio_de_palavra_move():
    """T2.1 — 2,0 s está no meio de 'teste'; a ponta volta para o começo dela."""
    r = timemap.snap_range(PALAVRAS, 2.0, 6.5, tolerance=0.5, padding=0.0)
    assert r["snapped"] is True
    assert r["start"] == 1.8, "encostou no início de 'teste'"
    assert r["end"] == 6.8, "encostou no fim de 'prazo'"
    assert r["delta_start_s"] == -0.2
    assert r["delta_end_s"] == 0.3


def test_t2_2_pedido_na_fronteira_nao_move():
    """T2.2 — já em fronteira: delta zero."""
    r = timemap.snap_range(PALAVRAS, 1.8, 6.8, tolerance=0.5, padding=0.0)
    assert r["delta_start_s"] == 0.0 and r["delta_end_s"] == 0.0
    assert r["snapped"] is False


def test_t2_3_fronteira_longe_nao_move():
    """T2.3 — a fronteira mais próxima está a 2,4 s: fora da tolerância, não mexe."""
    r = timemap.snap_range(PALAVRAS, 3.5, 4.0, tolerance=0.5, padding=0.0)
    assert r["snapped"] is False
    assert (r["start"], r["end"]) == (3.5, 4.0)


def test_t2_3b_padding_respira():
    """O padding é a diferença entre cortar colado e cortar a respiração."""
    sem = timemap.snap_range(PALAVRAS, 1.8, 2.6, tolerance=0.5, padding=0.0)
    com = timemap.snap_range(PALAVRAS, 1.8, 2.6, tolerance=0.5, padding=0.15)
    assert com["start"] == round(sem["start"] - 0.15, 3)
    assert com["end"] == round(sem["end"] + 0.15, 3)


def test_t2_3c_sem_palavras_e_identidade():
    r = timemap.snap_range([], 3.0, 9.0)
    assert (r["start"], r["end"], r["snapped"]) == (3.0, 9.0, False)


def test_t2_4_snap_sem_transcript_em_cache(draft, tmp_path):
    """T2.4 — snap='speech' sem transcrição: erro que diz o que fazer."""
    copia = str(tmp_path / "nunca_transcrito.mp4")
    shutil.copy(VIDEO_MUDO, copia)
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.cut", draft_id=draft, source=copia,
             keep=[[0, 2]], snap="speech")
    assert exc.value.code == E.TRANSCRIPT_NOT_FOUND
    assert "capcut.media.transcribe" in exc.value.suggestion


@tem_whisper
def test_t2_5_cut_com_snap_reporta_o_ajuste(draft):
    """O relatório do corte tem de dizer quanto cada ponta andou."""
    asr.transcribe(VIDEO_FALA, language="pt")
    d, bus = call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
                  keep=[[5.0, 10.0], [13.0, 17.0]], snap="speech")
    assert d["snap"] == "speech"
    assert len(d["snapped"]) == 2
    assert any(s["snapped"] for s in d["snapped"])
    for s in d["snapped"]:
        assert abs(s["delta_start_s"]) <= 0.5 + 0.15 + 1e-6
        assert abs(s["delta_end_s"]) <= 0.5 + 0.15 + 1e-6
    assert any(w["code"] == "CUT_SNAPPED_TO_SPEECH" for w in bus.warnings)


# ======================================================== T3 remapeamento
def mapa_de(*pares):
    """Mapa equivalente a um corte que manteve `pares`, encadeados sem buraco."""
    mapa, cursor = [], 0.0
    for a, b in pares:
        mapa.append({"source_start": a, "source_end": b,
                     "timeline_start": cursor, "timeline_end": cursor + (b - a)})
        cursor += b - a
    return mapa


def test_t3_1_bloco_deslocado_pelo_corte():
    """T3.1 — corte [[0,3],[5,8]]: 6,0–7,0 da origem vira 4,0–5,0 na timeline."""
    m = timemap.map_block(mapa_de((0, 3), (5, 8)), 6.0, 7.0)
    assert (m["timeline_start"], m["timeline_end"]) == (4.0, 5.0)
    assert m["truncated"] is False
    assert timemap.map_instant(mapa_de((0, 3), (5, 8)), 6.0) == 4.0


def test_t3_2_bloco_em_trecho_removido_e_descartado():
    """T3.2 — 3,2–4,0 caiu no buraco: não sobrevive."""
    assert timemap.map_block(mapa_de((0, 3), (5, 8)), 3.2, 4.0) is None
    assert timemap.map_instant(mapa_de((0, 3), (5, 8)), 4.0) is None


def test_t3_3_bloco_atravessando_a_fronteira():
    """T3.3 — 2,0–4,0 atravessa; com 'truncate' fica a parte mantida."""
    m = timemap.map_block(mapa_de((0, 3), (5, 8)), 2.0, 4.0, "truncate")
    assert (m["timeline_start"], m["timeline_end"]) == (2.0, 3.0)
    assert m["truncated"] is True
    assert timemap.map_block(mapa_de((0, 3), (5, 8)), 2.0, 4.0, "drop") is None


def test_t3_4_resto_curto_demais_e_descartado():
    """T3.4 — sobrou 0,5 s da legenda: curto demais para ser lido, descarta."""
    assert timemap.map_block(mapa_de((0, 3), (5, 8)), 2.5, 4.0) is None
    assert timemap.MIN_KEPT_S == 0.8


def test_t3_5_tres_trechos_deslocamento_acumulado():
    """T3.5 — o deslocamento acumula: cada trecho tem o seu próprio offset."""
    m = mapa_de((0, 2), (5, 7), (10, 12))
    assert timemap.map_instant(m, 1.0) == 1.0     # offset 0
    assert timemap.map_instant(m, 6.0) == 3.0     # offset -3
    assert timemap.map_instant(m, 11.0) == 5.0    # offset -6
    assert timemap.total_kept_s(m) == 6.0


def test_t3_6_sem_corte_o_remapeamento_e_identidade():
    """T3.6 — vídeo inteiro na timeline: entra igual, sai igual."""
    m = mapa_de((0, 18.77))
    for t in (0.0, 4.3, 12.9, 18.77):
        assert timemap.map_instant(m, t) == t
    b = timemap.map_block(m, 4.0, 6.0)
    assert (b["timeline_start"], b["timeline_end"]) == (4.0, 6.0)
    assert b["truncated"] is False


@tem_whisper
def test_t3_mapa_vem_dos_segmentos_reais(draft):
    """O mapa é derivado do script, não do plano — vale para cut e para add."""
    asr.transcribe(VIDEO_FALA, language="pt")
    call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
         keep=[[1.0, 4.0], [8.0, 11.0], [14.0, 17.0]])
    from capcut_mcp.upstream import DRAFT_CACHE
    m = timemap.build(DRAFT_CACHE[draft], VIDEO_FALA)
    assert len(m) == 3
    assert [round(i["timeline_start"], 2) for i in m] == [0.0, 3.0, 6.0]
    assert [round(i["source_start"], 2) for i in m] == [1.0, 8.0, 14.0]


@tem_whisper
def test_t3_from_transcript_conta_o_que_perdeu(draft):
    """A tool tem de dizer quantas legendas morreram no corte, não só as que vivem."""
    asr.transcribe(VIDEO_FALA, language="pt")
    call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
         keep=[[1.0, 4.0], [8.0, 11.0], [14.0, 17.0]])
    s, bus = call("capcut.subtitle.from_transcript", draft_id=draft,
                  source=VIDEO_FALA)
    assert s["remapped"] is True
    assert s["blocks_in_transcript"] == (s["blocks_imported"] + s["blocks_dropped"])
    assert s["kept_source_s"] == 9.0
    for par in s["mapping"]:
        assert par["timeline_range"][1] <= 9.0 + 1e-6, "legenda além do fim do corte"
    if s["blocks_dropped"]:
        assert any(w["code"] == "CAPTIONS_DROPPED_BY_CUT" for w in bus.warnings)


def test_t3_from_transcript_exige_video_na_timeline(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.from_transcript", draft_id=draft, source=VIDEO_FALA)
    assert exc.value.code in (E.SOURCE_NOT_FOUND, E.TRANSCRIPT_NOT_FOUND)


# =========================================== AC8 e AC3: validator e doctor
@tem_whisper
def test_ac8_validate_avisa_legenda_nao_remapeada(draft):
    """AC8 — corte + legenda crua é o erro silencioso; o validate precisa falar."""
    r = asr.transcribe(VIDEO_FALA, language="pt")
    call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
         keep=[[1.0, 4.0], [8.0, 11.0]])
    call("capcut.subtitle.add", draft_id=draft,
         segments=[{"start": b["start"], "end": b["end"], "text": b["text"]}
                   for b in r["blocks"][:2]])
    v, _ = call("capcut.draft.validate", draft_id=draft)
    codes = [i["code"] for i in v["issues"]]
    assert "V_CAPTION_DESYNC_RISK" in codes
    aviso = next(i for i in v["issues"] if i["code"] == "V_CAPTION_DESYNC_RISK")
    assert "from_transcript" in aviso["suggestion"]


@tem_whisper
def test_ac8b_from_transcript_nao_dispara_o_aviso(draft):
    asr.transcribe(VIDEO_FALA, language="pt")
    call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
         keep=[[1.0, 4.0], [8.0, 11.0]])
    call("capcut.subtitle.from_transcript", draft_id=draft, source=VIDEO_FALA)
    v, _ = call("capcut.draft.validate", draft_id=draft)
    assert "V_CAPTION_DESYNC_RISK" not in [i["code"] for i in v["issues"]]


@tem_whisper
def test_validate_avisa_corte_no_meio_da_palavra(draft):
    """V_CUT_MID_WORD: com transcript em cache, dá para saber e avisar."""
    r = asr.transcribe(VIDEO_FALA, language="pt")
    meio = next(w for w in r["words"] if w["end"] - w["start"] > 0.25)
    t = round((meio["start"] + meio["end"]) / 2, 3)
    call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
         keep=[[t, t + 3.0], [15.0, 17.0]])
    v, _ = call("capcut.draft.validate", draft_id=draft)
    achado = next((i for i in v["issues"] if i["code"] == "V_CUT_MID_WORD"), None)
    assert achado is not None, f"corte em {t}s parte {meio['word']!r} e passou batido"
    assert "snap='speech'" in achado["suggestion"]


@tem_whisper
def test_validate_nao_avisa_quando_houve_snap(draft):
    asr.transcribe(VIDEO_FALA, language="pt")
    call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
         keep=[[5.0, 10.0]], snap="speech")
    v, _ = call("capcut.draft.validate", draft_id=draft)
    assert "V_CUT_MID_WORD" not in [i["code"] for i in v["issues"]]


def test_ac3_doctor_reporta_whisper_e_modelos():
    """AC3 — o doctor tem de dizer se dá para transcrever nesta máquina."""
    d, bus = call("capcut.system.doctor")
    assert "whisper_cli" in d and "asr_models_installed" in d
    assert d["asr_default_model"] == asr.DEFAULT_MODEL
    codes = [w["code"] for w in bus.warnings]
    if not d["whisper_cli"]:
        assert "ASR_UNAVAILABLE" in codes
    elif asr.DEFAULT_MODEL not in d["asr_models_installed"]:
        assert "ASR_MODEL_MISSING" in codes
    else:
        assert "ASR_UNAVAILABLE" not in codes and "ASR_MODEL_MISSING" not in codes


def test_doctor_sem_whisper_traz_o_comando(monkeypatch):
    real = shutil.which
    monkeypatch.setattr("capcut_mcp.tools.shutil.which",
                        lambda n: None if n == asr.BIN else real(n))
    d, bus = call("capcut.system.doctor")
    assert d["whisper_cli"] is None
    aviso = next(w for w in bus.warnings if w["code"] == "ASR_UNAVAILABLE")
    assert "brew install whisper-cpp" in aviso["context"]["fix"]


# ================================================= superfície MCP das tools
def test_tools_novas_estao_expostas():
    assert "capcut.media.transcribe" in tools.enabled()
    assert "capcut.subtitle.from_transcript" in tools.enabled()


def test_schema_do_cut_aceita_snap():
    props = tools.TOOLS["capcut.video.cut"]["schema"]["properties"]
    assert props["snap"]["enum"] == ["none", "speech"]
    assert "snap_tolerance" in props and "snap_padding" in props


def test_schemas_novos_sao_fechados():
    for nome in ("capcut.media.transcribe", "capcut.subtitle.from_transcript"):
        s = tools.TOOLS[nome]["schema"]
        assert s["additionalProperties"] is False, nome
        assert json.dumps(s), nome


# ==================================== contraste da legenda (achado do AC7)
def _stroke_do_preset(draft_id, preset):
    """Largura de stroke que um preset realmente grava no JSON."""
    from capcut_mcp.upstream import DRAFT_CACHE
    call("capcut.video.add", draft_id=draft_id, source=VIDEO_MUDO)
    call("capcut.subtitle.add", draft_id=draft_id, style=preset, track="s",
         segments=[{"start": 0.2, "end": 2.0, "text": "preço"}], font_size=8.0)
    script = DRAFT_CACHE[draft_id]
    mat_id = script.tracks["s"].segments[0].material_id
    for m in script.materials.texts:          # o L0 guarda estes como dict
        if m.get("id") != mat_id:
            continue
        estilo = json.loads(m["content"])["styles"][0]
        strokes = estilo.get("strokes") or []
        return strokes[0]["width"] if strokes else None
    return None


def test_mapeamento_de_borda_do_upstream_e_o_que_pensamos(draft):
    """O L0 faz `width / 100 * 0.2`, e o comentário dele diz que pode estar errado.

    Este teste fixa o mapeamento: se o upstream mudar, a calibração de todos os
    presets muda com ele, e é melhor descobrir aqui do que na tela.
    """
    largura = HM.SUBTITLE_PRESETS["outline"]["border_width"]
    assert _stroke_do_preset(draft, "outline") == pytest.approx(
        largura / 100.0 * 0.2), "o L0 mudou o mapeamento de border_width"


def test_presets_com_contraste_gravam_stroke_ou_fundo(draft):
    """Um preset que promete contraste não pode sair sem nada no JSON."""
    for preset in ("outline", "outline_boxed"):
        d, _ = call("capcut.draft.create", name=f"p-{preset}",
                    width=1080, height=1920)
        try:
            assert _stroke_do_preset(d["draft_id"], preset), \
                f"o preset '{preset}' não gravou stroke nenhum"
        finally:
            registry.discard(d["draft_id"])


def test_borda_do_outline_e_espessa_o_bastante(draft):
    """A borda do default tem de dar contraste de verdade.

    O piso 0.08 saiu de medição na tela ("Borda Calibra", 6/20/40/70 sobre barras
    claras): abaixo disso o contorno desaparece e a legenda branca fica ilegível
    sobre fundo claro. Foi o defeito que o AC7 revelou.
    """
    assert _stroke_do_preset(draft, "outline") >= 0.08


def test_subtitle_nao_promete_borda_que_nao_aceita():
    """A legenda só dá contraste por preset. Então não pode anunciar outra coisa.

    O apply_subtitle monta os kwargs com `**style` e IGNORA border_width vindo do
    chamador — ao contrário do apply_text. Como o schema não expõe esses campos,
    pelo MCP ninguém consegue passá-los e o silêncio não machuca; se algum dia
    forem expostos, o applier tem de passar a lê-los.
    """
    for nome in ("capcut.subtitle.add", "capcut.subtitle.from_transcript"):
        props = tools.TOOLS[nome]["schema"]["properties"]
        expostos = [k for k in props if "border" in k or "background" in k]
        assert not expostos, (
            f"{nome} passou a expor {expostos}, mas apply_subtitle ainda ignora "
            "esses campos — ligue-os no applier antes de expor no schema")


# ============================== achados da auditoria de L1 e L2 (regressão)
@tem_whisper
def test_snap_nao_cruza_trechos_vizinhos(draft):
    """ACHADO A: o snap cruzava dois `keep` e duplicava mídia no resultado.

    Medido antes da correção: keep=[[1.0,3.2],[3.3,6.0]] virava
    [[1.15,3.43],[3.15,6.03]] — 0,280 s da origem apareciam DUAS vezes na
    timeline (gagueira audível), o mapa de tempo ficava ambíguo, e nada avisava:
    a checagem de sobreposição roda antes do snap, então ele passava por cima.
    """
    asr.transcribe(VIDEO_FALA, language="pt")
    d, bus = call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
                  keep=[[1.0, 3.2], [3.3, 6.0]], snap="speech")
    aplicados = [s["applied"] for s in d["snapped"]]
    for (_, fim), (ini, _) in zip(aplicados, aplicados[1:]):
        assert fim <= ini + 1e-6, f"trechos se cruzam: {aplicados}"

    from capcut_mcp.upstream import DRAFT_CACHE
    segs = sorted(DRAFT_CACHE[draft].tracks["video_main"].segments,
                  key=lambda s: s.target_timerange.start)
    for a, b in zip(segs, segs[1:]):
        ini = max(a.source_timerange.start, b.source_timerange.start)
        fim = min(a.source_timerange.end, b.source_timerange.end)
        assert fim <= ini, "o mesmo pedaço da origem entrou duas vezes na timeline"
    assert any(w["code"] == "SNAP_LIMITED_BY_NEIGHBOUR" for w in bus.warnings), \
        "conter o snap sem avisar esconde que as pontas não ficaram na fala"


@tem_whisper
def test_snap_contido_para_no_meio_do_intervalo(draft):
    """A ponta anda no máximo até a metade do vão que separa os dois trechos."""
    asr.transcribe(VIDEO_FALA, language="pt")
    d, _ = call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
                keep=[[1.0, 3.2], [3.3, 6.0]], snap="speech")
    fim0 = d["snapped"][0]["applied"][1]
    ini1 = d["snapped"][1]["applied"][0]
    assert fim0 == pytest.approx((3.2 + 3.3) / 2, abs=1e-6)
    assert ini1 == pytest.approx((3.2 + 3.3) / 2, abs=1e-6)


@tem_whisper
def test_delta_do_snap_descreve_o_que_foi_aplicado(draft):
    """ACHADO B: o delta era calculado antes do clamp no fim da mídia.

    Pedindo até a duração exata, o padding empurrava além do fim; o valor
    aplicado era clampado mas o delta reportado não, então quem somasse
    `pedido + delta` chegava a um instante que não existe na mídia.
    """
    asr.transcribe(VIDEO_FALA, language="pt")
    dur = media.probe(VIDEO_FALA)["duration_s"]
    d, _ = call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
                keep=[[13.0, dur]], snap="speech")
    s = d["snapped"][0]
    assert s["applied"][0] == pytest.approx(13.0 + s["delta_start_s"], abs=1e-3)
    assert s["applied"][1] == pytest.approx(dur + s["delta_end_s"], abs=1e-3)
    assert s["applied"][1] <= dur + 1e-6, "corte não pode passar do fim da mídia"


def test_fusao_de_blocos_respeita_max_chars():
    """ACHADO C: a fusão de blocos curtos estourava o limite pedido.

    O `-ml` do binário limita o que ELE emite, mas a fusão acontece depois.
    Medido antes: com max_chars=16 saía um bloco de 33 caracteres.
    """
    curtos = [{"start": i * 0.4, "end": i * 0.4 + 0.4, "text": "palavra"}
              for i in range(6)]
    blocos = asr._shape_blocks(curtos, max_block_s=10.0, max_chars=16)
    assert blocos, "não pode devolver vazio"
    for b in blocos:
        assert len(b["text"]) <= 16, f"fusão estourou o limite: {b['text']!r}"
    # sem limite de texto a fusão junta tudo — é o comportamento que quebrava
    solto = asr._shape_blocks(curtos, max_block_s=10.0, max_chars=1000)
    assert len(solto) < len(blocos), "o limite de texto tem de conter a fusão"


@tem_whisper
def test_max_chars_e_alvo_e_a_tela_nao_transborda():
    """O excesso que resta é do binário, que não parte palavra — e está declarado.

    O que importa é a tela: o subtitle.add quebra em limite de palavra depois,
    então um bloco acima do alvo vira duas linhas em vez de transbordar.
    """
    r = asr.transcribe(VIDEO_FALA, language="pt", max_chars=40)
    pior = max(len(b["text"]) for b in r["blocks"])
    assert pior <= 40 * 1.3, f"excesso além do medido (25%): {pior} caracteres"
    desc = tools.TOOLS["capcut.media.transcribe"]["schema"]["properties"][
        "max_chars_per_block"]["description"].lower()
    assert "alvo" in desc and "teto" in desc, \
        "se o limite é aproximado, a descrição tem de dizer isso"


@tem_whisper
def test_escolha_de_transcript_e_deterministica(tmp_path):
    """ACHADO D/E: com várias transcrições da mesma mídia, vencia o os.listdir.

    A chave do cache inclui modelo, idioma e max_chars, mas a busca por caminho
    ignorava os três. Resultado: o from_transcript podia devolver legendas
    moldadas com um max_chars que ninguém pediu, e a escolha mudava de máquina
    para máquina.
    """
    for mc in (16, 26, 60):
        asr.transcribe(VIDEO_FALA, language="pt", max_chars=mc)
    ids = {asr.find_cached_by_source(VIDEO_FALA)["transcript_id"] for _ in range(5)}
    assert len(ids) == 1, f"escolha instável entre chamadas: {ids}"
    assert asr.find_cached_by_source(VIDEO_FALA, max_chars=26)["max_chars"] == 26
    assert asr.find_cached_by_source(VIDEO_FALA, max_chars=60)["max_chars"] == 60
    cands = asr.cached_for_source(VIDEO_FALA)
    assert len(cands) >= 3
    assert cands == asr.cached_for_source(VIDEO_FALA), "a ordem tem de ser estável"


@tem_whisper
def test_from_transcript_declara_e_permite_fixar_qual_usou(draft):
    for mc in (26, 60):
        asr.transcribe(VIDEO_FALA, language="pt", max_chars=mc)
    call("capcut.video.cut", draft_id=draft, source=VIDEO_FALA,
         keep=[[1.0, 5.0], [8.0, 12.0]])
    s, bus = call("capcut.subtitle.from_transcript", draft_id=draft,
                  source=VIDEO_FALA, max_chars_per_block=26)
    assert s["transcript_max_chars"] == 26, "a preferência tem de ser honrada"
    assert s["transcript_model"] and s["transcript_id"]
    assert any(w["code"] == "TRANSCRIPT_AMBIGUOUS" for w in bus.warnings), \
        "havendo mais de uma transcrição, o agente precisa saber qual entrou"

    alvo = asr.find_cached_by_source(VIDEO_FALA, max_chars=60)
    d2, _ = call("capcut.draft.create", name="pin", width=1080, height=1920)
    try:
        call("capcut.video.cut", draft_id=d2["draft_id"], source=VIDEO_FALA,
             keep=[[1.0, 5.0], [8.0, 12.0]])
        s2, _ = call("capcut.subtitle.from_transcript", draft_id=d2["draft_id"],
                     source=VIDEO_FALA, transcript_id=alvo["transcript_id"])
        assert s2["transcript_id"] == alvo["transcript_id"]
        assert s2["transcript_max_chars"] == 60
    finally:
        registry.discard(d2["draft_id"])


def test_transcript_id_inexistente_da_erro_acionavel():
    with pytest.raises(E.CapcutError) as exc:
        asr.require_cached(VIDEO_FALA, transcript_id="naoexiste")
    assert exc.value.code == E.TRANSCRIPT_NOT_FOUND
    assert "transcript_id" in exc.value.suggestion


@tem_whisper
def test_cache_segue_o_conteudo_nao_o_caminho(tmp_path):
    """ACHADO F: o cache era endereçado por conteúdo e buscado por caminho.

    Apareceu ao mover as fixtures para dentro do repo. O `transcribe` respondia
    `cached: true` — acerto por fingerprint de conteúdo — e o `snap` seguinte
    falhava com TRANSCRIPT_NOT_FOUND, porque `find_cached_by_source` comparava o
    caminho absoluto. Basta mover o arquivo, ter uma cópia em outra pasta, ou
    alcançá-lo por outro ponto de montagem.
    """
    asr.transcribe(VIDEO_FALA, language="pt")

    copia = str(tmp_path / "outro_nome.mp4")
    shutil.copy(VIDEO_FALA, copia)

    r = asr.transcribe(copia, language="pt")
    assert r["cached"] is True, "mesmo conteúdo tem de acertar o cache"
    assert asr.find_cached_by_source(copia) is not None, \
        "quem acabou de transcrever com sucesso não pode ouvir 'não existe'"
    assert asr.require_cached(copia)["blocks"] == r["blocks"]
    # e o caminho original continua encontrando
    assert asr.find_cached_by_source(VIDEO_FALA) is not None


@tem_whisper
def test_snap_funciona_em_copia_da_midia(draft, tmp_path):
    """O teste de ponta que o achado F quebrava: transcrever e cortar uma cópia."""
    copia = str(tmp_path / "copia.mp4")
    shutil.copy(VIDEO_FALA, copia)
    asr.transcribe(copia, language="pt")
    d, _ = call("capcut.video.cut", draft_id=draft, source=copia,
                keep=[[5.0, 10.0]], snap="speech")
    assert d["snap"] == "speech"
    assert d["snapped"][0]["snapped"] is True


def test_fingerprint_e_do_conteudo(tmp_path):
    a = str(tmp_path / "a.mp4")
    b = str(tmp_path / "b.mp4")
    shutil.copy(VIDEO_FALA, a)
    shutil.copy(VIDEO_FALA, b)
    assert asr.fingerprint(a) == asr.fingerprint(b), \
        "arquivos idênticos em caminhos diferentes têm o mesmo fingerprint"
    assert asr.fingerprint(a) != asr.fingerprint(VIDEO_MUDO)
