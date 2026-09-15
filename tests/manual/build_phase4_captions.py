#!/usr/bin/env python3
"""Projeto-lote da Phase 4: legendas para verificação visual no CapCut."""
from __future__ import annotations
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.abspath(os.path.join(REPO, "fixtures"))
from capcut_mcp import obs, tools  # noqa: E402

VIDEO = os.path.join(FX, "video_teste.mp4")
VIDEO_B = os.path.join(FX, "clip_b.mp4")
WARN = []

def call(tool, **args):
    bus = obs.WarningBus()
    out = tools.TOOLS[tool]["handler"](args, bus)
    WARN.extend(w["code"] for w in bus.warnings)
    return out

# cinco legendas consecutivas em PT-BR, com acento, quebra de linha real e emoji
SRT = """1
00:00:00,000 --> 00:00:02,000
Ação e coração

2
00:00:02,000 --> 00:00:04,000
Duas linhas de verdade
segunda linha aqui

3
00:00:04,000 --> 00:00:06,000
Pão, ótimo, çãõ — travessão

4
00:00:06,000 --> 00:00:08,000
Emoji 🎬 e "aspas" … reticências

5
00:00:08,000 --> 00:00:10,000
Quinta e última legenda
"""

d = call("capcut.draft.create", name="P4 Captions", width=1080, height=1920)["draft_id"]
call("capcut.video.add", draft_id=d, source=VIDEO, source_end=6, volume=0.0)
call("capcut.video.add", draft_id=d, source=VIDEO_B, source_end=6, volume=0.0)
call("capcut.video.add", draft_id=d, source=VIDEO, source_end=4, volume=0.0)

# 0–10 s: cinco legendas com o preset default (outline)
r1 = call("capcut.subtitle.add", draft_id=d, srt=SRT)

# 10–16 s: três legendas com preset boxed, em track própria, para comparar estilo
r2 = call("capcut.subtitle.add", draft_id=d, track="subtitle_boxed", style="boxed",
          segments=[{"start": 10.0, "end": 12.0, "text": "preset boxed"},
                    {"start": 12.0, "end": 14.0, "text": "com fundo\ne duas linhas"},
                    {"start": 14.0, "end": 16.0, "text": "Ação com caixa"}])

# rótulos de seção, no topo
call("capcut.text.add", draft_id=d, text="0-10s: preset outline (5 legendas)",
     timeline_start=0, duration=10, track="labels", font_size=6.0, transform_y=0.85,
     background_color="#000000", background_alpha=0.6)
call("capcut.text.add", draft_id=d, text="10-16s: preset boxed (3 legendas)",
     timeline_start=10, duration=6, track="labels", font_size=6.0, transform_y=0.85,
     background_color="#000000", background_alpha=0.6)

res = call("capcut.draft.save", draft_id=d, project_name="P4 Captions", overwrite=True)
m = res["manifest"]
print(f"P4 Captions  dur={res['duration_us']/1_000_000:.1f}s tracks={m['tracks']} "
      f"segs={m['segments']} timeline_ok={m['timeline_content_matches_root']}")
print(f"  outline: {r1['blocks_imported']} blocos {r1['first_start_s']}-{r1['last_end_s']}s"
      f" fixed_width={r1['fixed_width_ratio']}")
print(f"  boxed:   {r2['blocks_imported']} blocos {r2['first_start_s']}-{r2['last_end_s']}s")
if WARN:
    from collections import Counter
    print("  avisos:", dict(Counter(WARN)))
