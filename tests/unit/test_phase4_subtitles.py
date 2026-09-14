"""Phase 4 — legendas. Um teste por item do escopo."""
from __future__ import annotations

import os
import sys
import uuid

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.abspath(os.path.join(REPO, "..", "fixtures"))

from capcut_mcp import errors as E, obs, registry, subtitles as SUB, tools  # noqa: E402
from capcut_mcp import handlers_media as HM  # noqa: E402

US = 1_000_000

SRT_5 = """1
00:00:00,000 --> 00:00:02,000
Primeira legenda

2
00:00:02,000 --> 00:00:04,000
Segunda legenda

3
00:00:04,000 --> 00:00:06,000
Terceira legenda

4
00:00:06,000 --> 00:00:08,000
Quarta legenda

5
00:00:08,000 --> 00:00:10,000
Quinta legenda
"""

SRT_PT = """1
00:00:00,000 --> 00:00:03,000
Ação, coração e pão — ótimo!

2
00:00:03,000 --> 00:00:06,000
Duas linhas aqui
segunda linha com çãõ

3
00:00:06,000 --> 00:00:09,000
Emoji 🎬 e "aspas" … reticências
"""


def call(tool: str, **args):
    bus = obs.WarningBus()
    return tools.TOOLS[tool]["handler"](args, bus), bus


@pytest.fixture
def draft():
    d, _ = call("capcut.draft.create", name=f"t4-{uuid.uuid4().hex[:8]}",
                width=1080, height=1920)
    yield d["draft_id"]
    registry.discard(d["draft_id"])


def segs(draft_id, track="subtitle"):
    from capcut_mcp.upstream import DRAFT_CACHE
    return DRAFT_CACHE[draft_id].tracks[track].segments


# ============================================== criação e múltiplos segmentos
def test_sub01_cinco_legendas_consecutivas(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    assert d["blocks_imported"] == 5
    assert len(segs(draft)) == 5
    assert d["first_start_s"] == 0.0 and d["last_end_s"] == 10.0


def test_sub02_ordem_e_sincronizacao_preservadas(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    tr = [(s.target_timerange.start, s.target_timerange.end) for s in segs(draft)]
    assert tr == [(0, 2 * US), (2 * US, 4 * US), (4 * US, 6 * US),
                  (6 * US, 8 * US), (8 * US, 10 * US)]


def test_sub03_sem_sobreposicao_entre_blocos(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    for prev, cur in zip(segs(draft), segs(draft)[1:]):
        assert cur.target_timerange.start >= prev.target_timerange.end


def test_sub04_criacao_manual_por_segments(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 0.0, "end": 1.5, "text": "um"},
        {"start": 1.5, "end": 3.0, "text": "dois"},
        {"start": 3.0, "end": 4.5, "text": "três"},
    ])
    assert d["blocks_imported"] == 3
    assert d["source_kind"] == "segments"


def test_sub05_segments_fora_de_ordem_sao_ordenados(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 2.0, "end": 4.0, "text": "b"},
        {"start": 0.0, "end": 2.0, "text": "a"},
    ])
    assert d["blocks"][0]["start_s"] == 0.0


def test_sub06_srt_e_segments_juntos_erram(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.add", draft_id=draft, srt=SRT_5,
             segments=[{"start": 0, "end": 1, "text": "x"}])
    assert exc.value.code == E.MISSING_REQUIRED_PARAM


def test_sub07_nenhum_dos_dois_erra(draft):
    with pytest.raises(E.CapcutError):
        call("capcut.subtitle.add", draft_id=draft)


# ============================================================== timestamps
def test_sub08_time_offset_desloca_todos(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5, time_offset=2.5)
    assert d["first_start_s"] == 2.5 and d["last_end_s"] == 12.5
    assert segs(draft)[0].target_timerange.start == 2.5 * US


def test_sub09_offset_negativo_que_gera_tempo_negativo_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.add", draft_id=draft, srt=SRT_5, time_offset=-5)
    assert exc.value.code == E.INVALID_TIMERANGE
    assert exc.value.context.get("line")


def test_sub10_blocos_sobrepostos_no_srt_erram(draft):
    bad = ("1\n00:00:00,000 --> 00:00:05,000\na\n\n"
           "2\n00:00:03,000 --> 00:00:07,000\nb\n")
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.add", draft_id=draft, srt=bad)
    assert exc.value.code == E.SEGMENT_OVERLAP


# ==================================================== parsing e robustez
def test_sub11_indice_opcional_e_ponto_no_lugar_de_virgula():
    blocks = SUB.parse_srt("00:00:00.000 --> 00:00:01.500\nsem indice\n")
    assert len(blocks) == 1 and blocks[0]["end"] == 1.5


def test_sub12_bom_e_crlf_aceitos():
    blocks = SUB.parse_srt("﻿1\r\n00:00:00,000 --> 00:00:01,000\r\ncom BOM\r\n")
    assert blocks[0]["text"] == "com BOM"


def test_sub13_srt_malformado_erra_com_numero_de_linha(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.add", draft_id=draft,
             srt="1\nisto nao e timestamp -->\ntexto\n")
    assert exc.value.code == E.SRT_PARSE_ERROR
    assert exc.value.context["line"] == 2


def test_sub14_bloco_sem_texto_erra():
    with pytest.raises(E.CapcutError) as exc:
        SUB.parse_srt("1\n00:00:00,000 --> 00:00:01,000\n\n")
    assert exc.value.code == E.SRT_PARSE_ERROR


def test_sub15_arquivo_inexistente_erra(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.add", draft_id=draft, srt="/nao/existe/legenda.srt")
    assert exc.value.code == E.SRT_NOT_FOUND


def test_sub16_arquivo_real_e_lido(draft, tmp_path):
    p = tmp_path / "legendas.srt"
    p.write_text(SRT_PT, encoding="utf-8")
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=str(p))
    assert d["blocks_imported"] == 3
    assert d["source_kind"] == "file"


# ============================================ caracteres especiais e PT-BR
def test_sub17_acentuacao_portuguesa_preservada(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_PT)
    from capcut_mcp.upstream import DRAFT_CACHE
    conteudos = [m["content"] for m in DRAFT_CACHE[draft].materials.texts]
    todo = " ".join(conteudos)
    for trecho in ("Ação", "coração", "pão", "ótimo", "çãõ"):
        assert trecho in todo, trecho


def test_sub18_caracteres_especiais_e_emoji(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_PT)
    from capcut_mcp.upstream import DRAFT_CACHE
    todo = " ".join(m["content"] for m in DRAFT_CACHE[draft].materials.texts)
    assert "🎬" in todo
    assert "…" in todo


def test_sub19_quebra_de_linha_real_preservada(draft):
    """O lote da Phase 3 usou '\\n' literal por engano; aqui a quebra é real."""
    d, _ = call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 0.0, "end": 2.0, "text": "linha um\nlinha dois"},
    ])
    assert d["blocks"][0]["lines"] == 2
    import json as _json
    from capcut_mcp.upstream import DRAFT_CACHE
    # o material guarda o texto dentro de um JSON; a quebra chega escapada ali
    conteudo = _json.loads(DRAFT_CACHE[draft].materials.texts[0]["content"])
    assert "\n" in conteudo["text"], "a quebra de linha precisa ser real, não literal"


def test_sub20_multilinha_no_srt_conta_linhas(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=SRT_PT)
    assert d["blocks"][1]["lines"] == 2


# ==================================================== estilo visual
def test_sub21_preset_default_liga_contraste(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    assert d["style"] == "outline"
    assert segs(draft)[0].border is not None, "o default precisa ter borda"


def test_sub22_preset_boxed_liga_fundo(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_5, style="boxed")
    assert segs(draft)[0].background is not None


def test_sub23_preset_plain_avisa_sobre_contraste(draft):
    _, bus = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5, style="plain")
    assert any(w["code"] == "TEXT_LOW_CONTRAST" for w in bus.warnings)


def test_sub24_posicao_fonte_tamanho_e_cor(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5,
                font="Amigate", font_size=10.0, font_color="#FFD700",
                transform_y=-0.6, align=0, bold=True)
    assert d["resolved_font"] == "Amigate"
    assert d["font_size"] == 10.0


def test_sub25_fonte_invalida_erra_sem_tocar_no_draft(draft):
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.add", draft_id=draft, srt=SRT_5, font="NaoExisteEssaFonte")
    assert exc.value.code == E.UNKNOWN_FONT
    from capcut_mcp.upstream import DRAFT_CACHE
    assert "subtitle" not in DRAFT_CACHE[draft].tracks, "não deve deixar track órfã"


def test_sub26_safe_zone_gera_warning(draft):
    _, bus = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5, transform_y=-0.95)
    assert any(w["code"] == "TEXT_UNSAFE_ZONE" for w in bus.warnings)


def test_sub27_fixed_width_segue_a_orientacao(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    assert d["fixed_width_ratio"] == SUB.FIXED_WIDTH_PORTRAIT


def test_sub28_estilo_reutilizavel_entre_projetos():
    """O preset é nomeado, então o mesmo estilo se repete sem repetir parâmetros."""
    ids = []
    for _ in range(2):
        d, _ = call("capcut.draft.create", name=f"t4-reuse-{uuid.uuid4().hex[:6]}")
        did = d["draft_id"]
        ids.append(did)
        r, _ = call("capcut.subtitle.add", draft_id=did, srt=SRT_5,
                    style="outline_boxed")
        assert r["style"] == "outline_boxed"
        assert segs(did)[0].border is not None
        assert segs(did)[0].background is not None
    for did in ids:
        registry.discard(did)


# ==================================================== integridade
def test_sub29_falha_no_meio_nao_deixa_track_pela_metade(draft):
    """Um SRT malformado é detectado antes de qualquer mutação."""
    bad = ("1\n00:00:00,000 --> 00:00:02,000\nok\n\n"
           "2\nlixo aqui\ntexto\n")
    with pytest.raises(E.CapcutError):
        call("capcut.subtitle.add", draft_id=draft, srt=bad)
    from capcut_mcp.upstream import DRAFT_CACHE
    assert "subtitle" not in DRAFT_CACHE[draft].tracks


def test_sub30_duas_importacoes_na_mesma_track_erram(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    with pytest.raises(E.CapcutError) as exc:
        call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    assert exc.value.code == E.SEGMENT_OVERLAP


def test_sub31_track_alternativa_permite_segunda_faixa(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    d, _ = call("capcut.subtitle.add", draft_id=draft, srt=SRT_5, track="subtitle_en")
    assert d["blocks_imported"] == 5
    assert len(segs(draft, "subtitle_en")) == 5


def test_sub32_registrado_no_plano_declarativo(draft):
    call("capcut.subtitle.add", draft_id=draft, srt=SRT_5)
    assert [s["op"] for s in registry.get(draft)["plan"]] == ["create", "subtitle"]


def test_sub33_gaps_reportados(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 3.0, "end": 4.0, "text": "b"},
    ])
    assert d["gaps_over_500ms"] == 1


def test_sub34_roundtrip_srt():
    blocks = SUB.parse_srt(SRT_5)
    again = SUB.parse_srt(SUB.to_srt(blocks))
    assert [(b["start"], b["end"], b["text"]) for b in blocks] == \
           [(b["start"], b["end"], b["text"]) for b in again]


# ============================== quebra em limite de palavra (achado visual)
def test_sub35_legenda_longa_quebra_em_limite_de_palavra(draft):
    """Verificado na tela: o CapCut quebra por CARACTERE, partindo a palavra."""
    longa = 'Emoji e "aspas" e reticencias bem compridas aqui'
    d, bus = call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 0.0, "end": 3.0, "text": longa}])
    assert any(w["code"] == "SUBTITLE_WRAPPED" for w in bus.warnings)
    assert d["wrapped_blocks"] == [1]
    import json as _json
    from capcut_mcp.upstream import DRAFT_CACHE
    texto = _json.loads(DRAFT_CACHE[draft].materials.texts[0]["content"])["text"]
    assert "\n" in texto
    for linha in texto.split("\n"):
        assert len(linha) <= d["max_chars_per_line"]
    # nenhuma palavra foi partida
    assert set(longa.split()) == set(texto.replace("\n", " ").split())


def test_sub36_legenda_curta_nao_e_tocada(draft):
    d, bus = call("capcut.subtitle.add", draft_id=draft, segments=[
        {"start": 0.0, "end": 2.0, "text": "curta"}])
    assert d["wrapped_blocks"] == []
    assert not any(w["code"] == "SUBTITLE_WRAPPED" for w in bus.warnings)


def test_sub37_limite_escala_com_o_tamanho_da_fonte(draft):
    d8, _ = call("capcut.subtitle.add", draft_id=draft, font_size=8.0,
                 segments=[{"start": 0.0, "end": 1.0, "text": "x"}])
    d16, _ = call("capcut.subtitle.add", draft_id=draft, font_size=16.0,
                  track="s2", segments=[{"start": 0.0, "end": 1.0, "text": "x"}])
    assert d16["max_chars_per_line"] < d8["max_chars_per_line"]


def test_sub38_limite_explicito_respeitado(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, max_chars_per_line=15,
                segments=[{"start": 0.0, "end": 3.0,
                           "text": "uma frase razoavelmente longa aqui"}])
    assert d["max_chars_per_line"] == 15
    import json as _json
    from capcut_mcp.upstream import DRAFT_CACHE
    texto = _json.loads(DRAFT_CACHE[draft].materials.texts[0]["content"])["text"]
    assert all(len(l) <= 15 for l in texto.split("\n"))


def test_sub39_palavra_maior_que_o_limite_nao_e_partida(draft):
    d, _ = call("capcut.subtitle.add", draft_id=draft, max_chars_per_line=12,
                segments=[{"start": 0.0, "end": 2.0,
                           "text": "anticonstitucionalissimamente"}])
    import json as _json
    from capcut_mcp.upstream import DRAFT_CACHE
    texto = _json.loads(DRAFT_CACHE[draft].materials.texts[0]["content"])["text"]
    assert texto == "anticonstitucionalissimamente", "palavra não deve ser cortada"
