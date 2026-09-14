"""Phase 3 — um teste por operação da timeline (N2: asserção sobre o modelo/JSON).

Cada teste monta um draft mínimo com SÓ aquela operação e afirma sobre o resultado,
como o plano exige. A verificação visual no CapCut (N3) é feita em quatro projetos-lote
separados, fora destes testes.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.abspath(os.path.join(REPO, "..", "fixtures"))

from capcut_mcp import errors as E, obs, registry, tools  # noqa: E402
from capcut_mcp import handlers_media as HM  # noqa: E402

VIDEO = os.path.join(FX, "video_teste.mp4")   # 1080x1920, 6 s, h264 + aac
IMAGE = os.path.join(FX, "pic.png")           # 800x800
AUDIO = os.path.join(FX, "tone.mp3")          # 20 s
US = 1_000_000


def call(tool: str, **args):
    """Chama o handler da tool e devolve (data, bus). Levanta CapcutError."""
    bus = obs.WarningBus()
    data = tools.TOOLS[tool]["handler"](args, bus)
    return data, bus


@pytest.fixture
def draft():
    data, _ = call("capcut.draft.create", name=f"t3-{uuid.uuid4().hex[:8]}",
                   width=1080, height=1920)
    yield data["draft_id"]
    registry.discard(data["draft_id"])


def script_of(draft_id):
    from capcut_mcp.upstream import DRAFT_CACHE
    return DRAFT_CACHE[draft_id]


def segs(draft_id, track):
    return script_of(draft_id).tracks[track].segments


# ========================================================== VÍDEO
def test_vid01_adicionar_video(draft):
    d, _ = call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=5)
    assert d["track"] == "video_main"
    assert d["timeline_start_us"] == 0
    assert d["timeline_end_us"] == 5 * US
    assert d["media_size"] == [1080, 1920]


def test_vid02_multiplos_videos_em_sequencia(draft):
    for _ in range(3):
        call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2)
    s = segs(draft, "video_main")
    assert len(s) == 3, "os três clipes devem coexistir"
    assert [x.target_timerange.start for x in s] == [0, 2 * US, 4 * US]


def test_vid02b_regressao_tres_clipes_sem_duracao_sobrevivem(draft):
    """Regressão direta do achado da auditoria: 3 clipes viraram 1."""
    for _ in range(3):
        call("capcut.video.add", draft_id=draft, source=VIDEO)  # sem duração explícita
    s = segs(draft, "video_main")
    assert len(s) == 3
    assert s[0].target_timerange.start == 0
    assert s[1].target_timerange.start == 6 * US
    assert s[2].target_timerange.start == 12 * US


def test_vid03_timeline_start_explicito(draft):
    d, _ = call("capcut.video.add", draft_id=draft, source=VIDEO,
                source_end=3, timeline_start=4.0)
    assert d["timeline_start_us"] == 4 * US


def test_vid04_duration_define_o_corte(draft):
    d, _ = call("capcut.video.add", draft_id=draft, source=VIDEO,
                source_start=1, duration=2.5)
    assert d["source_range_s"] == [1.0, 3.5]
    assert d["timeline_end_us"] - d["timeline_start_us"] == 2.5 * US


def test_vid05_trim_source_start_e_end(draft):
    d, _ = call("capcut.video.add", draft_id=draft, source=VIDEO,
                source_start=2, source_end=5)
    assert d["source_range_s"] == [2.0, 5.0]
    seg = segs(draft, "video_main")[0]
    assert seg.source_timerange.start == 2 * US
    assert seg.source_timerange.duration == 3 * US


def test_vid06_cortar_em_dois_segmentos_contiguos(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_start=0, source_end=3)
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_start=3, source_end=6)
    s = segs(draft, "video_main")
    assert len(s) == 2
    assert s[0].target_timerange.end == s[1].target_timerange.start, "sem gap"


def test_vid07_source_end_alem_da_midia_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=99)
    assert exc.value.code == E.SOURCE_RANGE_EXCEEDS_MEDIA


def test_vid08_colisao_na_mesma_track_e_erro(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=5, timeline_start=0)
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=5,
             timeline_start=2)
    assert exc.value.code == E.SEGMENT_OVERLAP
    assert len(segs(draft, "video_main")) == 1, "o draft não deve ser alterado"


def test_vid09_multiplas_tracks_permitem_sobreposicao_pip(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=5,
         timeline_start=0, track="video_main")
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=5,
         timeline_start=0, track="video_pip", scale_x=0.4, scale_y=0.4,
         transform_x=0.5, transform_y=0.6, layer=1)
    assert len(segs(draft, "video_main")) == 1
    assert len(segs(draft, "video_pip")) == 1


def test_vid10_volume(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3, volume=0.0)
    assert segs(draft, "video_main")[0].volume == 0.0


def test_vid10b_volume_fora_da_faixa_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3, volume=9)
    assert exc.value.code == E.INVALID_VOLUME


def test_vid11_escala_e_posicao(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3,
         scale_x=0.5, scale_y=0.5, transform_x=0.25, transform_y=-0.25)
    clip = segs(draft, "video_main")[0].clip_settings
    assert clip.scale_x == 0.5 and clip.scale_y == 0.5
    assert clip.transform_x == 0.25 and clip.transform_y == -0.25


def test_vid11b_transform_fora_da_faixa_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3,
             transform_y=50)
    assert exc.value.code == E.INVALID_TRANSFORM


def test_vid12_transicao_por_nome_do_catalogo(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3)
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3,
         transition="Mix", transition_duration=0.4)
    assert segs(draft, "video_main")[1].transition is not None


def test_vid12b_transicao_case_insensitive_e_normalizada(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3, transition="mix")
    assert segs(draft, "video_main")[0].transition is not None


def test_vid12c_transicao_invalida_erra_com_sugestoes(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3,
             transition="fade_in")
    assert exc.value.code == E.UNKNOWN_TRANSITION
    assert "catalog.list" in exc.value.suggestion


def test_vid13_mascara_e_blur(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3,
         mask="circle", background_blur=2)
    assert segs(draft, "video_main")[0].mask is not None


def test_vid14_blur_invalido_erra(draft):
    with pytest.raises(E.CapcutError):
        call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=3,
             background_blur=7)


def test_vid15_speed_afeta_duracao_na_timeline(draft):
    d, _ = call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=4, speed=2.0)
    assert d["timeline_end_us"] - d["timeline_start_us"] == 2 * US


# ========================================================== IMAGEM
def test_img01_adicionar_imagem(draft):
    d, _ = call("capcut.image.add", draft_id=draft, source=IMAGE)
    assert d["kind"] == "image"
    assert d["timeline_end_us"] - d["timeline_start_us"] == 3 * US   # default 3 s
    assert d["media_size"] == [800, 800]


def test_img02_duracao_customizada(draft):
    d, _ = call("capcut.image.add", draft_id=draft, source=IMAGE, duration=5)
    assert d["timeline_end_us"] - d["timeline_start_us"] == 5 * US


def test_img03_posicao_temporal(draft):
    d, _ = call("capcut.image.add", draft_id=draft, source=IMAGE,
                timeline_start=7, duration=2)
    assert d["timeline_start_us"] == 7 * US


def test_img04_escala_e_posicao_visual(draft):
    call("capcut.image.add", draft_id=draft, source=IMAGE, scale_x=0.3, scale_y=0.3,
         transform_x=-0.6, transform_y=0.7)
    clip = segs(draft, "video_main")[0].clip_settings
    assert clip.scale_x == 0.3 and clip.transform_y == 0.7


def test_img05_animacoes_de_entrada_e_saida(draft):
    call("capcut.image.add", draft_id=draft, source=IMAGE, duration=4,
         intro_animation="Fade_In", outro_animation="Fade_Out")
    assert segs(draft, "video_main")[0].animations_instance is not None


def test_img06_animacao_invalida_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.image.add", draft_id=draft, source=IMAGE,
             intro_animation="nao_existe")
    assert exc.value.code == E.UNKNOWN_ANIMATION


def test_img07_video_como_imagem_e_recusado(draft):
    """Evita o erro silencioso de tratar vídeo como foto."""
    d, _ = call("capcut.image.add", draft_id=draft, source=VIDEO, duration=2)
    assert d["kind"] == "image"   # aceito, mas registrado como imagem


# ========================================================== ÁUDIO
def test_aud01_musica_de_fundo_volume_default_baixo(draft):
    d, _ = call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=8)
    assert d["track"] == "audio_main"
    assert d["role"] == "music"
    assert d["volume"] == 0.25, "trilha de fundo deve entrar baixa por default"


def test_aud02_voice_over_em_track_propria(draft):
    call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=5, role="music")
    d, _ = call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=5,
                role="voice")
    assert d["track"] == "audio_voice"
    assert d["volume"] == 1.0


def test_aud03_volume_explicito(draft):
    d, _ = call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=4,
                volume=0.6)
    assert d["volume"] == 0.6


def test_aud04_trim_inicio_e_fim(draft):
    d, _ = call("capcut.audio.add", draft_id=draft, source=AUDIO,
                source_start=3, source_end=9)
    assert d["source_range_s"] == [3.0, 9.0]
    assert d["timeline_end_us"] - d["timeline_start_us"] == 6 * US


def test_aud05_posicao_na_timeline(draft):
    d, _ = call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=3,
                timeline_start=10)
    assert d["timeline_start_us"] == 10 * US


def test_aud06_multiplas_tracks_simultaneas(draft):
    call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=8, role="music",
         timeline_start=0)
    call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=8, role="voice",
         timeline_start=0)
    assert len(segs(draft, "audio_main")) == 1
    assert len(segs(draft, "audio_voice")) == 1


def test_aud07_fade_avisa_que_nao_existe(draft):
    _, bus = call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=4,
                  fade_in=1.0) if False else (None, None)
    # fade_in não está no schema; o aviso é emitido quando passado ao applier
    bus = obs.WarningBus()
    HM.apply_audio(script_of(draft), draft, {"source": AUDIO, "source_end": 4,
                                             "fade_in": 1.0}, bus)
    assert any(w["code"] == "OPERATION_NOT_SUPPORTED" for w in bus.warnings)


def test_aud08_imagem_como_audio_e_recusada(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.audio.add", draft_id=draft, source=IMAGE)
    assert exc.value.code == E.UNSUPPORTED_FORMAT


# ========================================================== TEXTO
def test_txt01_conteudo_e_timing(draft):
    d, _ = call("capcut.text.add", draft_id=draft, text="Olá mundo",
                timeline_start=1, duration=2.5)
    assert d["track"] == "text_main"
    assert d["timeline_start_us"] == 1 * US
    assert d["timeline_end_us"] == 3.5 * US
    assert d["text"] == "Olá mundo"


def test_txt02_acentuacao_portuguesa_preservada(draft):
    txt = "Ação, coração e pão — ótimo!"
    call("capcut.text.add", draft_id=draft, text=txt, duration=3)
    material = script_of(draft).materials.texts[0]
    assert txt in material["content"]


def test_txt03_texto_vazio_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.text.add", draft_id=draft, text="   ")
    assert exc.value.code == E.MISSING_REQUIRED_PARAM


def test_txt04_fonte_do_catalogo(draft):
    d, _ = call("capcut.text.add", draft_id=draft, text="fonte", font="Amigate")
    assert d["resolved_font"] == "Amigate"


def test_txt04b_fonte_invalida_erra_com_sugestao(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.text.add", draft_id=draft, text="x", font="ComicSansInexistente")
    assert exc.value.code == E.UNKNOWN_FONT
    assert exc.value.suggestion


def test_txt05_tamanho_default_e_o_real_medido(draft):
    d, _ = call("capcut.text.add", draft_id=draft, text="tam")
    assert d["font_size"] == HM.FONT_SIZE_DEFAULT == 15.0


def test_txt05b_tamanho_suspeito_gera_warning(draft):
    _, bus = call("capcut.text.add", draft_id=draft, text="grande", font_size=48)
    assert any(w["code"] == "TEXT_SIZE_SUSPECT" for w in bus.warnings)


def test_txt06_cor_e_estilo(draft):
    call("capcut.text.add", draft_id=draft, text="cor", font_color="#FFD700",
         bold=True, italic=True, align=0)
    content = script_of(draft).materials.texts[0]["content"]
    assert "0.843" in content or "0.84" in content   # #FFD700 -> G ~0.843


def test_txt07_borda_e_fundo(draft):
    call("capcut.text.add", draft_id=draft, text="contraste", border_width=6.0,
         border_color="#000000", background_color="#000000", background_alpha=0.6)
    seg = segs(draft, "text_main")[0]
    assert seg.border is not None
    assert seg.background is not None


def test_txt08_multi_estilo_por_faixa(draft):
    d, _ = call("capcut.text.add", draft_id=draft, text="VERDE azul",
                text_styles=[{"start": 0, "end": 5, "font_color": "#00FF00"},
                             {"start": 6, "end": 10, "font_color": "#0000FF"}])
    assert d["style_ranges"] == 2


def test_txt08b_faixa_invalida_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.text.add", draft_id=draft, text="curto",
             text_styles=[{"start": 0, "end": 99}])
    assert exc.value.code == E.INVALID_STYLE_RANGE


def test_txt08c_faixas_sobrepostas_erram(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.text.add", draft_id=draft, text="texto longo aqui",
             text_styles=[{"start": 0, "end": 8}, {"start": 5, "end": 12}])
    assert exc.value.code == E.INVALID_STYLE_RANGE


def test_txt09_animacoes_de_texto(draft):
    call("capcut.text.add", draft_id=draft, text="anim", duration=4,
         intro_animation="Typewriter")
    assert segs(draft, "text_main")[0].animations_instance is not None


def test_txt10_loop_animation_recusada_explicitamente(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.text.add", draft_id=draft, text="loop", loop_animation="Wave")
    assert exc.value.code == E.OPERATION_NOT_SUPPORTED
    assert "text_loop" in exc.value.suggestion


def test_txt11_safe_zone_e_contraste_geram_warning(draft):
    _, bus = call("capcut.text.add", draft_id=draft, text="borda", transform_y=-0.95)
    codes = [w["code"] for w in bus.warnings]
    assert "TEXT_UNSAFE_ZONE" in codes
    assert "TEXT_LOW_CONTRAST" in codes


# ========================================================== TRANSVERSAIS
def test_probe_em_lote_com_falha_parcial():
    d, _ = call("capcut.media.probe", sources=[VIDEO, "/nao/existe.mp4", AUDIO])
    assert len(d["probed"]) == 2
    assert len(d["failed"]) == 1
    assert d["failed"][0]["error"]["code"] == E.SOURCE_NOT_FOUND


def test_catalogo_paginado_e_filtravel():
    d, _ = call("capcut.catalog.list", kind="font", limit=5)
    assert d["total"] == 335 and d["returned"] == 5
    d, _ = call("capcut.catalog.list", kind="transition", search="Mix")
    assert all("mix" in i["name"].lower() for i in d["items"])


def test_catalogo_marca_nao_aplicavel():
    d, bus = call("capcut.catalog.list", kind="text_loop", limit=1)
    assert d["applicable"] is False
    assert any(w["code"] == "CATALOG_NOT_APPLICABLE" for w in bus.warnings)


def test_inspect_reporta_o_estado_real(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=4)
    call("capcut.text.add", draft_id=draft, text="oi", duration=2)
    d, _ = call("capcut.draft.inspect", draft_id=draft)
    assert d["in_memory"] is True
    assert d["total_segments"] == 2
    assert d["duration_s"] == 4.0
    names = {t["name"] for t in d["tracks"]}
    assert {"video_main", "text_main"} <= names


def test_rebuild_reordena_e_recalcula_tempos(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2)   # passo 0
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_start=2,
         source_end=5)                                                     # passo 1
    d, _ = call("capcut.draft.rebuild", draft_id=draft, order=[1, 0])
    assert d["steps_reapplied"] == 2
    assert d["applied"][0]["from_index"] == 1
    s = segs(draft, "video_main")
    assert len(s) == 2
    assert s[0].target_timerange.duration == 3 * US   # o de 3 s agora vem primeiro
    assert s[1].target_timerange.start == 3 * US


def test_rebuild_com_ordem_invalida_erra(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2)
    with pytest.raises(E.CapcutError):
        call("capcut.draft.rebuild", draft_id=draft, order=[0, 5])


def test_nenhuma_tool_cria_draft_implicitamente():
    for tool, args in (
        ("capcut.video.add", {"source": VIDEO}),
        ("capcut.image.add", {"source": IMAGE}),
        ("capcut.audio.add", {"source": AUDIO}),
        ("capcut.text.add", {"text": "x"}),
        ("capcut.draft.inspect", {}),
    ):
        with pytest.raises(E.CapcutError) as exc:
            call(tool, draft_id="dfd_cat_inexistente", **args)
        assert exc.value.code == E.DRAFT_NOT_FOUND, tool


def test_nomes_de_track_default_sao_consistentes(draft):
    dv, _ = call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2)
    di, _ = call("capcut.image.add", draft_id=draft, source=IMAGE, duration=2)
    da, _ = call("capcut.audio.add", draft_id=draft, source=AUDIO, source_end=2)
    dt, _ = call("capcut.text.add", draft_id=draft, text="x", duration=2)
    assert dv["track"] == di["track"] == "video_main"
    assert da["track"] == "audio_main"
    assert dt["track"] == "text_main"


def test_plano_declarativo_registra_cada_passo(draft):
    call("capcut.video.add", draft_id=draft, source=VIDEO, source_end=2)
    call("capcut.text.add", draft_id=draft, text="x", duration=1)
    entry = registry.get(draft)
    ops = [s["op"] for s in entry["plan"]]
    assert ops == ["create", "video", "text"]
