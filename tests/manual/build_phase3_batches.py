#!/usr/bin/env python3
"""Constrói os quatro projetos-lote da Phase 3 para verificação visual no CapCut.

Cada operação recebe um rótulo de texto na timeline, para que um problema visual possa
ser atribuído à operação que o causou — é o que permite agrupar a verificação em quatro
aberturas do app em vez de trinta.

Uso:  PYTHONPATH=src .venv/bin/python tests/manual/build_phase3_batches.py
"""
from __future__ import annotations

import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.abspath(os.path.join(REPO, "fixtures"))

from capcut_mcp import obs, tools  # noqa: E402

VIDEO = os.path.join(FX, "video_teste.mp4")
VIDEO_B = os.path.join(FX, "clip_b.mp4")
IMAGE = os.path.join(FX, "pic.png")
AUDIO = os.path.join(FX, "tone.mp3")

ALL_WARNINGS: list = []


def call(tool: str, **args):
    bus = obs.WarningBus()
    data = tools.TOOLS[tool]["handler"](args, bus)
    for w in bus.warnings:
        ALL_WARNINGS.append((tool, w["code"]))
    return data


def new_draft(name: str) -> str:
    return call("capcut.draft.create", name=name, width=1080, height=1920)["draft_id"]


def label(draft: str, text: str, start: float, dur: float, track="labels"):
    call("capcut.text.add", draft_id=draft, text=text, timeline_start=start,
         duration=dur, track=track, font_size=6.0, transform_y=0.85,
         background_color="#000000", background_alpha=0.6)


def save(draft: str, name: str) -> dict:
    return call("capcut.draft.save", draft_id=draft, project_name=name, overwrite=True)


# ============================================================ lote 1: VÍDEO
def batch_video() -> dict:
    d = new_draft("P3 Video")
    # 0–4  clipe normal
    call("capcut.video.add", draft_id=d, source=VIDEO, source_end=4)
    label(d, "1 normal 0-4s", 0, 4)
    # 4–8  trim de origem (segundos 2..6 da mídia)
    call("capcut.video.add", draft_id=d, source=VIDEO, source_start=2, source_end=6)
    label(d, "2 trim src 2-6", 4, 4)
    # 8–11 velocidade 2x (6 s de origem -> 3 s na timeline)
    call("capcut.video.add", draft_id=d, source=VIDEO, source_end=6, speed=2.0)
    label(d, "3 speed 2x", 8, 3)
    # 11–14 máscara circular
    call("capcut.video.add", draft_id=d, source=VIDEO, source_end=3, mask="Circle")
    label(d, "4 mask Circle", 11, 3)
    # 14–17 transição + blur de fundo + volume mudo
    call("capcut.video.add", draft_id=d, source=VIDEO_B, source_end=3,
         transition="Mix", transition_duration=0.5, background_blur=3, volume=0.0)
    label(d, "5 transicao+blur+mudo", 14, 3)
    # PiP: track separada, escala 0.35 no canto superior direito
    call("capcut.video.add", draft_id=d, source=VIDEO_B, source_end=6, timeline_start=0,
         track="video_pip", scale_x=0.35, scale_y=0.35,
         transform_x=0.55, transform_y=0.55, layer=1, volume=0.0)
    label(d, "6 PiP canto (0-6s)", 0, 2, track="labels2")
    return save(d, "P3 Video")


# =========================================================== lote 2: IMAGEM
def batch_image() -> dict:
    d = new_draft("P3 Image")
    call("capcut.video.add", draft_id=d, source=VIDEO, source_end=6, volume=0.0)
    call("capcut.video.add", draft_id=d, source=VIDEO_B, source_end=6, volume=0.0)
    # 0–3 imagem cheia
    call("capcut.image.add", draft_id=d, source=IMAGE, timeline_start=0, duration=3,
         track="img_1", layer=1)
    label(d, "1 imagem default 0-3s", 0, 3)
    # 3–6 escalada e deslocada
    call("capcut.image.add", draft_id=d, source=IMAGE, timeline_start=3, duration=3,
         track="img_1", scale_x=0.4, scale_y=0.4, transform_x=-0.5, transform_y=0.5)
    label(d, "2 escala 0.4 canto", 3, 3)
    # 6–9 com animações de entrada e saída
    call("capcut.image.add", draft_id=d, source=IMAGE, timeline_start=6, duration=3,
         track="img_1", intro_animation="Fade_In", outro_animation="Fade_Out",
         scale_x=0.7, scale_y=0.7)
    label(d, "3 fade in/out", 6, 3)
    # 9–12 PiP sobre vídeo, em track própria com layer maior
    call("capcut.image.add", draft_id=d, source=IMAGE, timeline_start=9, duration=3,
         track="img_pip", scale_x=0.3, scale_y=0.3, transform_x=0.6, transform_y=-0.6,
         layer=2, mask="Circle")
    label(d, "4 PiP mascara circular", 9, 3)
    return save(d, "P3 Image")


# ============================================================ lote 3: ÁUDIO
def batch_audio() -> dict:
    d = new_draft("P3 Audio")
    call("capcut.video.add", draft_id=d, source=VIDEO, source_end=6, volume=0.0)
    call("capcut.video.add", draft_id=d, source=VIDEO_B, source_end=4, volume=0.0)
    # trilha de fundo: volume default de 0.25, cobre tudo
    call("capcut.audio.add", draft_id=d, source=AUDIO, source_end=10, role="music")
    label(d, "1 musica 0-10s vol .25", 0, 3)
    # voice-over: track propria, 2–7 s, volume 1.0
    call("capcut.audio.add", draft_id=d, source=AUDIO, source_start=5, source_end=10,
         role="voice", timeline_start=2)
    label(d, "2 voice 2-7s vol 1.0", 3, 3)
    # sfx: terceira track, trim curto, volume alto
    call("capcut.audio.add", draft_id=d, source=AUDIO, source_start=1, source_end=2,
         role="sfx", timeline_start=8, volume=1.5)
    label(d, "3 sfx 8-9s vol 1.5", 6, 3)
    return save(d, "P3 Audio")


# ============================================================ lote 4: TEXTO
def batch_text() -> dict:
    """Inclui a calibração de font_size (WI-3.28): seis tamanhos simultâneos."""
    d = new_draft("P3 Text")
    call("capcut.video.add", draft_id=d, source=VIDEO, source_end=6, volume=0.0)
    call("capcut.video.add", draft_id=d, source=VIDEO_B, source_end=6, volume=0.0)

    # --- 0–5 s: calibração. Seis tamanhos ao mesmo tempo, em alturas distintas.
    for i, size in enumerate((5.0, 8.0, 10.0, 12.0, 15.0, 20.0)):
        y = 0.75 - i * 0.28
        call("capcut.text.add", draft_id=d, text=f"size {size:g}", timeline_start=0,
             duration=5, track=f"cal_{i}", font_size=size, transform_y=y,
             border_width=4.0, border_color="#000000")

    # --- 6–9 s: multi-estilo por faixa
    call("capcut.text.add", draft_id=d, text="VERDE azul VERMELHO", timeline_start=6,
         duration=3, track="t_style", font_size=11.0, transform_y=0.2,
         border_width=5.0,
         text_styles=[{"start": 0, "end": 5, "font_color": "#00FF00"},
                      {"start": 6, "end": 10, "font_color": "#3399FF"},
                      {"start": 11, "end": 19, "font_color": "#FF3333", "bold": True}])
    label(d, "multi-estilo 6-9s", 6, 3)

    # --- 9–12 s: fundo, borda, sombra, negrito, alinhamento
    call("capcut.text.add", draft_id=d, text="fundo + borda\\n+ sombra",
         timeline_start=9, duration=3, track="t_style", font_size=12.0,
         transform_y=0.0, bold=True, align=1, border_width=6.0,
         background_color="#1E1E1E", background_alpha=0.75,
         background_round_radius=20.0, shadow_enabled=True, line_spacing=0.3)
    label(d, "fundo/borda/sombra 9-12s", 9, 3)

    # --- 12–15 s: acentuação portuguesa e animação de entrada
    call("capcut.text.add", draft_id=d, text="Ação, coração — ótimo! çãõ",
         timeline_start=12, duration=3, track="t_style", font_size=9.0,
         transform_y=-0.3, border_width=5.0, intro_animation="Typewriter")
    label(d, "acentos + Typewriter 12-15s", 12, 3)

    # --- 15–18 s: fonte do catálogo
    call("capcut.text.add", draft_id=d, text="fonte Amigate", timeline_start=15,
         duration=3, track="t_style", font_size=12.0, transform_y=0.0,
         font="Amigate", border_width=5.0)
    label(d, "fonte do catalogo 15-18s", 15, 3)
    return save(d, "P3 Text")


if __name__ == "__main__":
    for fn in (batch_video, batch_image, batch_audio, batch_text):
        res = fn()
        m = res["manifest"]
        print(f"{res['project_name']:12s} dur={res['duration_us'] / 1_000_000:5.1f}s "
              f"tracks={m['tracks']:2d} segs={m['segments']:2d} "
              f"assets={sum(1 for a in m['assets'] if a['ok'])}/{len(m['assets'])} "
              f"timeline_ok={m['timeline_content_matches_root']}")
    if ALL_WARNINGS:
        from collections import Counter
        print("\navisos emitidos:", dict(Counter(c for _, c in ALL_WARNINGS)))
