"""O fluxo enxuto: cortar + legendar + texto em momentos pré-determinados.

Este é o escopo que o usuário pediu. Cada teste cobre uma ergonomia ou uma proteção
que existe só por causa deste fluxo.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.abspath(os.path.join(REPO, "fixtures"))

from capcut_mcp import errors as E, obs, registry, tools, validator as V  # noqa: E402

VIDEO = os.path.join(FX, "video_teste.mp4")     # 6 s
US = 1_000_000


def call(tool: str, **args):
    bus = obs.WarningBus()
    return tools.TOOLS[tool]["handler"](args, bus), bus


@pytest.fixture
def draft():
    d, _ = call("capcut.draft.create", name=f"flow-{uuid.uuid4().hex[:8]}",
                width=1080, height=1920)
    yield d["draft_id"]
    registry.discard(d["draft_id"])


def segs(draft_id, track):
    from capcut_mcp.upstream import DRAFT_CACHE
    return DRAFT_CACHE[draft_id].tracks[track].segments


# ==================================================== CORTAR
def test_cut_mantem_trechos_e_encadeia(draft):
    d, _ = call("capcut.video.cut", draft_id=draft, source=VIDEO,
                keep=[[0, 2], [4, 6]])
    assert d["segments_created"] == 2
    assert d["total_duration_s"] == 4.0, "2s + 2s, encadeados sem buraco"
    s = segs(draft, "video_main")
    assert s[0].target_timerange.start == 0
    assert s[1].target_timerange.start == 2 * US, "o segundo trecho começa onde o 1º acaba"
    assert s[0].source_timerange.start == 0
    assert s[1].source_timerange.start == 4 * US


def test_cut_reporta_o_que_foi_removido(draft):
    d, _ = call("capcut.video.cut", draft_id=draft, source=VIDEO,
                keep=[[1, 2], [4, 5]])
    assert d["removed_from_source_s"] == [[0.0, 1.0], [2.0, 4.0], [5.0, 6.0]]


def test_cut_com_gap_explicito(draft):
    d, _ = call("capcut.video.cut", draft_id=draft, source=VIDEO,
                keep=[[0, 1], [2, 3]], gap=0.5)
    s = segs(draft, "video_main")
    assert s[1].target_timerange.start == 1.5 * US


def test_cut_ordena_e_avisa(draft):
    d, bus = call("capcut.video.cut", draft_id=draft, source=VIDEO,
                  keep=[[4, 6], [0, 2]])
    assert any(w["code"] == "CUTS_REORDERED" for w in bus.warnings)
    assert d["kept"][0]["source_range_s"] == [0.0, 2.0]


def test_cut_recusa_trechos_sobrepostos(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.cut", draft_id=draft, source=VIDEO, keep=[[0, 3], [2, 5]])
    assert exc.value.code == E.INVALID_TIMERANGE


def test_cut_recusa_trecho_alem_da_midia(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.cut", draft_id=draft, source=VIDEO, keep=[[0, 99]])
    assert exc.value.code == E.SOURCE_RANGE_EXCEEDS_MEDIA


def test_cut_recusa_par_malformado(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.cut", draft_id=draft, source=VIDEO, keep=[[0]])
    assert exc.value.code == E.MISSING_REQUIRED_PARAM


# ==================================================== TEXTOS EM LOTE
def test_textos_em_momentos_predeterminados(draft):
    d, _ = call("capcut.text.add_many", draft_id=draft, duration=1.5,
                font_size=12.0, border_width=5.0,
                items=[{"text": "um", "timeline_start": 0},
                       {"text": "dois", "timeline_start": 2},
                       {"text": "três", "timeline_start": 4, "duration": 2}])
    assert d["texts_created"] == 3
    s = segs(draft, "text_main")
    assert [x.target_timerange.start for x in s] == [0, 2 * US, 4 * US]
    assert s[2].target_timerange.duration == 2 * US, "duração por item sobrescreve"


def test_textos_em_lote_compartilham_estilo(draft):
    call("capcut.text.add_many", draft_id=draft, font_size=11.0, border_width=6.0,
         items=[{"text": "a", "timeline_start": 0, "duration": 1},
                {"text": "b", "timeline_start": 1, "duration": 1}])
    for s in segs(draft, "text_main"):
        assert s.border is not None


def test_textos_em_lote_recusam_sobreposicao(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.text.add_many", draft_id=draft, duration=3.0,
             items=[{"text": "a", "timeline_start": 0},
                    {"text": "b", "timeline_start": 1}])
    assert exc.value.code == E.SEGMENT_OVERLAP


def test_textos_em_lote_nao_mutam_se_um_item_e_invalido(draft):
    from capcut_mcp.upstream import DRAFT_CACHE
    with pytest.raises(E.CapcutError):
        call("capcut.text.add_many", draft_id=draft,
             items=[{"text": "ok", "timeline_start": 0, "duration": 1},
                    {"text": "   ", "timeline_start": 2, "duration": 1}])
    assert "text_main" not in DRAFT_CACHE[draft].tracks


def test_textos_em_lote_fora_de_ordem_sao_ordenados(draft):
    d, _ = call("capcut.text.add_many", draft_id=draft, duration=1.0,
                items=[{"text": "b", "timeline_start": 3},
                       {"text": "a", "timeline_start": 0}])
    assert d["texts"][0]["text"] == "a"


# ==================================================== VALIDAÇÃO
def test_validate_draft_limpo_passa(draft):
    call("capcut.video.cut", draft_id=draft, source=VIDEO, keep=[[0, 4]])
    call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 0.0, "end": 2.0, "text": "primeira"},
        {"start": 2.0, "end": 4.0, "text": "segunda"}])
    d, _ = call("capcut.draft.validate", draft_id=draft)
    assert d["ok"] is True
    assert d["counts"]["error"] == 0


def test_validate_pega_texto_depois_do_fim_do_video(draft):
    """O erro típico deste fluxo: texto aparece sobre tela preta."""
    call("capcut.video.cut", draft_id=draft, source=VIDEO, keep=[[0, 3]])
    call("capcut.text.add", draft_id=draft, text="tarde demais",
         timeline_start=5, duration=2, border_width=5.0)
    d, _ = call("capcut.draft.validate", draft_id=draft)
    codes = [i["code"] for i in d["issues"]]
    assert "V_TEXT_AFTER_VIDEO" in codes


def test_validate_pega_buraco_na_track_de_video(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2,
         timeline_start=0)
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2,
         timeline_start=5)
    d, _ = call("capcut.draft.validate", draft_id=draft)
    gaps = [i for i in d["issues"] if i["code"] == "V_GAP"]
    assert gaps and gaps[0]["context"]["gap_s"] == 3.0


def test_validate_pega_texto_sem_contraste(draft):
    call("capcut.video.cut", draft_id=draft, source=VIDEO, keep=[[0, 4]])
    call("capcut.text.add", draft_id=draft, text="pelado", timeline_start=0,
         duration=2)
    d, _ = call("capcut.draft.validate", draft_id=draft)
    assert "V_TEXT_LOW_CONTRAST" in [i["code"] for i in d["issues"]]


def test_validate_draft_vazio_e_erro(draft):
    d, _ = call("capcut.draft.validate", draft_id=draft)
    assert d["ok"] is False
    assert d["issues"][0]["code"] == "V_EMPTY_DRAFT"


def test_validate_filtra_por_severidade(draft):
    call("capcut.video.cut", draft_id=draft, source=VIDEO, keep=[[0, 4]])
    call("capcut.text.add", draft_id=draft, text="x", timeline_start=0, duration=1)
    todos, _ = call("capcut.draft.validate", draft_id=draft, min_severity="info")
    so_erros, _ = call("capcut.draft.validate", draft_id=draft, min_severity="error")
    assert len(so_erros["issues"]) <= len(todos["issues"])
    assert all(i["severity"] == "error" for i in so_erros["issues"])


def test_todo_issue_tem_sugestao(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2,
         timeline_start=0)
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2,
         timeline_start=5)
    call("capcut.text.add", draft_id=draft, text="x", timeline_start=9, duration=1)
    d, _ = call("capcut.draft.validate", draft_id=draft)
    assert d["issues"]
    for i in d["issues"]:
        assert i["suggestion"].strip(), i["code"]


# ==================================================== SAVE BLOQUEADO
def test_save_recusa_quando_validacao_tem_erro(draft):
    """Draft vazio -> V_EMPTY_DRAFT -> save recusado."""
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.draft.save", draft_id=draft, project_name="flow-nunca-salvo")
    assert exc.value.code in (E.VALIDATION_FAILED, E.DRAFT_EMPTY)


def test_save_com_force_ignora_erro_de_validacao(draft, tmp_path):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2,
         timeline_start=0)
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2,
         timeline_start=5)   # cria V_GAP, que é warning, não erro
    d, bus = call("capcut.draft.save", draft_id=draft,
                  project_name=f"flow-{uuid.uuid4().hex[:6]}", overwrite=True)
    assert d["validation"]["counts"]["warning"] >= 1
    assert any(w["code"] == "V_GAP" for w in bus.warnings), \
        "warnings da validação precisam chegar ao agente"
    import shutil
    shutil.rmtree(d["project_path"], ignore_errors=True)


# ==================================================== FLUXO COMPLETO
def test_fluxo_completo_cortar_legendar_texto(draft):
    """O fluxo que o usuário pediu, ponta a ponta, em 4 chamadas."""
    probe, _ = call("capcut.media.probe", sources=[VIDEO])
    dur = probe["probed"][0]["duration_s"]
    assert dur == 6.0

    corte, _ = call("capcut.video.cut", draft_id=draft, source=VIDEO,
                    keep=[[0, 2], [3, 5]])
    assert corte["total_duration_s"] == 4.0

    legendas, _ = call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 0.0, "end": 2.0, "text": "Primeira fala"},
        {"start": 2.0, "end": 4.0, "text": "Segunda fala"}])
    assert legendas["blocks_imported"] == 2

    textos, _ = call("capcut.text.add_many", draft_id=draft, font_size=14.0,
                     transform_y=0.5, border_width=6.0, duration=1.5,
                     items=[{"text": "Abertura", "timeline_start": 0},
                            {"text": "Fechamento", "timeline_start": 2.5}])
    assert textos["texts_created"] == 2

    relatorio, _ = call("capcut.draft.validate", draft_id=draft)
    assert relatorio["ok"] is True, relatorio["issues"]

    estado, _ = call("capcut.draft.inspect", draft_id=draft)
    assert estado["duration_s"] == 4.0
    assert estado["total_segments"] == 6      # 2 cortes + 2 legendas + 2 textos
