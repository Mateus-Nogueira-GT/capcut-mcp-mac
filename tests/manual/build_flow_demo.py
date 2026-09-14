#!/usr/bin/env python3
"""O fluxo enxuto ponta a ponta: cortar + legendar + texto. Projeto 'Fluxo Corte'."""
from __future__ import annotations
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
FX = os.path.abspath(os.path.join(REPO, "..", "fixtures"))
from capcut_mcp import obs, tools  # noqa: E402

VIDEO = os.path.join(FX, "clip_b.mp4")   # 1080x1920, 8 s

def call(tool, **args):
    bus = obs.WarningBus()
    out = tools.TOOLS[tool]["handler"](args, bus)
    for w in bus.warnings:
        print(f"    aviso {w['code']}: {w['message'][:70]}")
    return out

print("1. probe")
p = call("capcut.media.probe", sources=[VIDEO])["probed"][0]
print(f"   {p['kind']} {p['duration_s']}s {p['width']}x{p['height']}")

print("2. create")
d = call("capcut.draft.create", name="Fluxo Corte", width=1080, height=1920)["draft_id"]

print("3. cortar: mantém 0-3s e 5-8s, descarta 3-5s")
c = call("capcut.video.cut", draft_id=d, source=VIDEO, keep=[[0, 3], [5, 8]])
print(f"   {c['segments_created']} trechos, {c['total_duration_s']}s finais, "
      f"removido da origem: {c['removed_from_source_s']}")

print("4. legendar")
l = call("capcut.subtitle.add", draft_id=d, segments=[
    {"start": 0.0, "end": 2.0, "text": "Primeira fala do vídeo"},
    {"start": 2.0, "end": 4.0, "text": "Segunda fala, com acentuação"},
    {"start": 4.0, "end": 6.0, "text": "Terceira e última"}])
print(f"   {l['blocks_imported']} legendas, {l['first_start_s']}-{l['last_end_s']}s, "
      f"limite {l['max_chars_per_line']} caracteres")

print("5. textos nos momentos pré-determinados")
t = call("capcut.text.add_many", draft_id=d, font_size=14.0, transform_y=0.55,
         border_width=6.0, background_color="#000000", background_alpha=0.5,
         background_round_radius=16.0, bold=True, duration=1.5,
         items=[{"text": "ABERTURA", "timeline_start": 0.0},
                {"text": "MEIO", "timeline_start": 2.5},
                {"text": "FIM", "timeline_start": 4.5}])
print(f"   {t['texts_created']} textos em {[x['start_s'] for x in t['texts']]}")

print("6. validar")
v = call("capcut.draft.validate", draft_id=d)
print(f"   ok={v['ok']} · {v['summary']}")
for i in v["issues"]:
    print(f"   [{i['severity']}] {i['code']}: {i['message'][:70]}")

print("7. salvar")
r = call("capcut.draft.save", draft_id=d, project_name="Fluxo Corte", overwrite=True)
m = r["manifest"]
print(f"   {r['project_name']}: {r['duration_us']/1_000_000}s, {m['tracks']} tracks, "
      f"{m['segments']} segmentos, assets {sum(1 for a in m['assets'] if a['ok'])}/"
      f"{len(m['assets'])}, timeline_ok={m['timeline_content_matches_root']}")
print(f"   {r['next_step']}")
