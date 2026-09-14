"""Handlers de mídia: vídeo, imagem, áudio e texto (spec: VID/IMG/AUD/TXT).

Convenções unificadas (spec AC2.12 — o upstream tem defaults divergentes por fachada):
  vídeo e imagem -> track "video_main"   (imagem vive em track de vídeo)
  áudio          -> track "audio_main"
  texto          -> track "text_main"

`timeline_start` omitido = anexa ao fim daquela track. Assim o agente encadeia clipes
sem calcular offsets — que é justamente onde a auditoria viu segmentos serem apagados.

Unidades: entrada em segundos; a saída também traz µs, a unidade interna do CapCut.
`transform_*` é normalizado em "meia tela" e o eixo Y é POSITIVO PARA CIMA.
`font_size` está na escala interna do CapCut (~5–15); 15.0 é o default real medido
na 9.4.1, não os 8.0 do upstream nem os 24/48 da documentação dele.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import catalog, errors as E, media, obs, registry
from .upstream import DRAFT_CACHE

US = media.US

TRACK_VIDEO = "video_main"
TRACK_AUDIO = "audio_main"
TRACK_TEXT = "text_main"

FONT_SIZE_DEFAULT = 15.0     # medido num texto padrão criado à mão no CapCut 9.4.1
FONT_SIZE_SANE = (3.0, 20.0)
VOLUME_RANGE = (0.0, 2.0)
TRANSFORM_RANGE = (-10.0, 10.0)


# ------------------------------------------------------------- validações
def _check_volume(v: float) -> float:
    if not VOLUME_RANGE[0] <= v <= VOLUME_RANGE[1]:
        raise E.CapcutError(
            E.INVALID_VOLUME, f"volume={v} fora da faixa aceita.",
            f"Use entre {VOLUME_RANGE[0]} e {VOLUME_RANGE[1]} "
            "(1.0 = original, 0.0 = mudo).",
        )
    return float(v)


def _check_transform(name: str, v: float) -> float:
    if not TRANSFORM_RANGE[0] <= v <= TRANSFORM_RANGE[1]:
        raise E.CapcutError(
            E.INVALID_TRANSFORM, f"{name}={v} fora da faixa aceita.",
            f"Use entre {TRANSFORM_RANGE[0]} e {TRANSFORM_RANGE[1]}. A unidade é "
            "'meia tela': 0 é o centro, 1.0 desloca meia largura/altura. "
            "Y positivo move para CIMA.",
        )
    return float(v)


def _seg_info(script: Any, track_name: str) -> Dict[str, Any]:
    track = script.tracks.get(track_name)
    seg = track.segments[-1]
    return {
        "track": track_name,
        "segment_index": len(track.segments) - 1,
        "timeline_start_us": seg.target_timerange.start,
        "timeline_end_us": seg.target_timerange.end,
        "timeline_start_s": round(seg.target_timerange.start / US, 3),
        "timeline_end_s": round(seg.target_timerange.end / US, 3),
        "segments_in_track": len(track.segments),
    }


# ------------------------------------------------------------------ vídeo
def apply_video(script: Any, draft_id: str, a: Dict[str, Any],
                bus: obs.WarningBus) -> Dict[str, Any]:
    from add_video_track import add_video_track

    track = a.get("track") or TRACK_VIDEO
    probe = media.probe(a["source"])
    if probe["kind"] not in ("video", "image"):
        raise E.CapcutError(
            E.UNSUPPORTED_FORMAT,
            f"{a['source']} é '{probe['kind']}', não vídeo.",
            "Use capcut.audio.add para áudio ou capcut.image.add para imagem.",
        )
    if not probe["extension_matches_content"]:
        bus.add("FORMAT_EXTENSION_MISMATCH",
                f"A extensão do arquivo sugere '{probe['extension_kind']}' mas o "
                f"conteúdo é '{probe['kind']}'.", source=a["source"])

    speed = float(a.get("speed", 1.0))
    src_start, src_end, tl_dur = media.resolve_range(
        probe, a.get("source_start"), a.get("source_end"), a.get("duration"), speed)
    tl_start = a.get("timeline_start")
    tl_start = media.track_end(script, track) if tl_start is None else float(tl_start)
    if tl_start < 0:
        raise E.CapcutError(E.INVALID_TIMERANGE, f"timeline_start negativo: {tl_start}",
                            "Use um valor >= 0.")
    media.check_collision(script, track, tl_start, tl_dur)

    kwargs: Dict[str, Any] = dict(
        video_url=probe["source"], draft_id=draft_id, track_name=track,
        start=src_start, end=src_end, duration=probe["duration_s"],
        target_start=tl_start, speed=speed,
        volume=_check_volume(float(a.get("volume", 1.0))),
        scale_x=float(a.get("scale_x", 1.0)), scale_y=float(a.get("scale_y", 1.0)),
        transform_x=_check_transform("transform_x", float(a.get("transform_x", 0.0))),
        transform_y=_check_transform("transform_y", float(a.get("transform_y", 0.0))),
        relative_index=int(a.get("layer", 0)),
    )
    if a.get("transition"):
        name = catalog.resolve("transition", a["transition"], E.UNKNOWN_TRANSITION)
        kwargs["transition"] = name
        kwargs["transition_duration"] = float(a.get("transition_duration", 0.5))
        vip = catalog.vip_warning("transition", name)
        if vip:
            bus.warnings.append(vip)
        bus.add("TRANSITION_NOT_RENDERED",
                f"A transição '{name}' foi gravada no projeto, mas no CapCut 9.4.1 ela "
                "não é aplicada (verificado: sem ícone na junção e sem mistura entre os "
                "clipes). Provável causa: o upstream a anexa ao clipe seguinte ao corte, "
                "quando o CapCut a espera no clipe anterior.",
                transition=name)
        if kwargs["transition_duration"] >= tl_dur:
            bus.add("TRANSITION_TOO_LONG",
                    f"A transição ({kwargs['transition_duration']}s) é maior ou igual à "
                    f"duração do clipe ({tl_dur:.2f}s).")
    if a.get("mask"):
        kwargs["mask_type"] = catalog.resolve("mask", a["mask"], E.UNKNOWN_MASK)
    if a.get("background_blur") is not None:
        blur = int(a["background_blur"])
        if blur not in (1, 2, 3, 4):
            raise E.CapcutError(
                E.MISSING_REQUIRED_PARAM, f"background_blur={blur} inválido.",
                "Use 1 (leve), 2 (médio), 3 (forte) ou 4 (máximo).")
        kwargs["background_blur"] = blur

    with bus.capture():
        add_video_track(**kwargs)

    info = _seg_info(script, track)
    info.update({"source": probe["source"], "kind": "video",
                 "source_range_s": [src_start, src_end], "speed": speed,
                 "media_duration_s": probe["duration_s"],
                 "media_size": [probe["width"], probe["height"]]})
    return info


# ----------------------------------------------------------------- imagem
def apply_image(script: Any, draft_id: str, a: Dict[str, Any],
                bus: obs.WarningBus) -> Dict[str, Any]:
    from add_image_impl import add_image_impl

    track = a.get("track") or TRACK_VIDEO
    probe = media.probe(a["source"])
    if probe["kind"] not in ("image", "video"):
        raise E.CapcutError(
            E.UNSUPPORTED_FORMAT, f"{a['source']} é '{probe['kind']}', não imagem.",
            "Use capcut.video.add para vídeo.",
        )
    duration = float(a.get("duration", 3.0))
    if duration <= 0:
        raise E.CapcutError(E.INVALID_TIMERANGE, f"duration={duration} inválida.",
                            "A duração da imagem deve ser > 0.")
    tl_start = a.get("timeline_start")
    tl_start = media.track_end(script, track) if tl_start is None else float(tl_start)
    media.check_collision(script, track, tl_start, duration)

    kwargs: Dict[str, Any] = dict(
        image_url=probe["source"], draft_id=draft_id, track_name=track,
        start=tl_start, end=tl_start + duration,   # para imagem, start/end são timeline
        scale_x=float(a.get("scale_x", 1.0)), scale_y=float(a.get("scale_y", 1.0)),
        transform_x=_check_transform("transform_x", float(a.get("transform_x", 0.0))),
        transform_y=_check_transform("transform_y", float(a.get("transform_y", 0.0))),
        relative_index=int(a.get("layer", 0)),
    )
    for key, kind, param in (("intro_animation", "animation_intro", "intro_animation"),
                             ("outro_animation", "animation_outro", "outro_animation"),
                             ("combo_animation", "animation_combo", "combo_animation")):
        if a.get(key):
            name = catalog.resolve(kind, a[key], E.UNKNOWN_ANIMATION)
            kwargs[param] = name
            vip = catalog.vip_warning(kind, name)
            if vip:
                bus.warnings.append(vip)
    if a.get("transition"):
        kwargs["transition"] = catalog.resolve("transition", a["transition"],
                                               E.UNKNOWN_TRANSITION)
        kwargs["transition_duration"] = float(a.get("transition_duration", 0.5))
    if a.get("mask"):
        kwargs["mask_type"] = catalog.resolve("mask", a["mask"], E.UNKNOWN_MASK)

    with bus.capture():
        add_image_impl(**kwargs)

    info = _seg_info(script, track)
    info.update({"source": probe["source"], "kind": "image",
                 "media_size": [probe["width"], probe["height"]]})
    return info


# ------------------------------------------------------------------ áudio
def apply_audio(script: Any, draft_id: str, a: Dict[str, Any],
                bus: obs.WarningBus) -> Dict[str, Any]:
    from add_audio_track import add_audio_track

    role = a.get("role", "music")
    track = a.get("track") or (TRACK_AUDIO if role == "music" else f"audio_{role}")
    probe = media.probe(a["source"])
    if probe["kind"] == "image":
        raise E.CapcutError(
            E.UNSUPPORTED_FORMAT, f"{a['source']} é imagem, não áudio.",
            "Use capcut.image.add.",
        )
    if probe["kind"] == "video" and not probe["has_audio"]:
        raise E.CapcutError(
            E.UNSUPPORTED_FORMAT, f"{a['source']} não tem faixa de áudio.",
            "Escolha um arquivo com áudio.",
        )
    speed = float(a.get("speed", 1.0))
    src_start, src_end, tl_dur = media.resolve_range(
        probe, a.get("source_start"), a.get("source_end"), a.get("duration"), speed)
    tl_start = a.get("timeline_start")
    tl_start = media.track_end(script, track) if tl_start is None else float(tl_start)
    media.check_collision(script, track, tl_start, tl_dur)

    default_volume = 0.25 if role == "music" else 1.0
    kwargs = dict(
        audio_url=probe["source"], draft_id=draft_id, track_name=track,
        start=src_start, end=src_end, duration=probe["duration_s"],
        target_start=tl_start, speed=speed,
        volume=_check_volume(float(a.get("volume", default_volume))),
    )
    with bus.capture():
        add_audio_track(**kwargs)

    if a.get("fade_in") or a.get("fade_out"):
        bus.add("OPERATION_NOT_SUPPORTED",
                "fade_in/fade_out não são expostos pelo upstream nesta versão "
                "(Audio_fade existe na biblioteca mas add_audio_track não o aceita).")

    info = _seg_info(script, track)
    info.update({"source": probe["source"], "kind": "audio", "role": role,
                 "source_range_s": [src_start, src_end],
                 "volume": kwargs["volume"], "media_duration_s": probe["duration_s"]})
    return info


# ------------------------------------------------------------------ texto
def apply_text(script: Any, draft_id: str, a: Dict[str, Any],
               bus: obs.WarningBus) -> Dict[str, Any]:
    from add_text_impl import add_text_impl
    from pyJianYingDraft.text_segment import TextStyleRange

    track = a.get("track") or TRACK_TEXT
    text = a.get("text") or ""
    if not text.strip():
        raise E.CapcutError(E.MISSING_REQUIRED_PARAM, "O texto não pode ser vazio.",
                            "Informe 'text' com o conteúdo a exibir.")
    tl_start = a.get("timeline_start")
    tl_start = media.track_end(script, track) if tl_start is None else float(tl_start)
    duration = float(a.get("duration", 3.0))
    if duration <= 0:
        raise E.CapcutError(E.INVALID_TIMERANGE, f"duration={duration} inválida.",
                            "A duração do texto deve ser > 0.")
    media.check_collision(script, track, tl_start, duration)

    font_size = float(a.get("font_size", FONT_SIZE_DEFAULT))
    if not FONT_SIZE_SANE[0] <= font_size <= FONT_SIZE_SANE[1]:
        bus.add("TEXT_SIZE_SUSPECT",
                f"font_size={font_size} está fora da faixa usual ({FONT_SIZE_SANE[0]}–"
                f"{FONT_SIZE_SANE[1]}). A escala é interna do CapCut, não pontos: "
                f"{FONT_SIZE_DEFAULT} é o tamanho padrão do app.")

    kwargs: Dict[str, Any] = dict(
        text=text, draft_id=draft_id, track_name=track,
        start=tl_start, end=tl_start + duration,
        font_size=font_size,
        font_color=a.get("font_color", "#FFFFFF"),
        transform_x=_check_transform("transform_x", float(a.get("transform_x", 0.0))),
        transform_y=_check_transform("transform_y", float(a.get("transform_y", -0.8))),
        bold=bool(a.get("bold", False)), italic=bool(a.get("italic", False)),
        underline=bool(a.get("underline", False)),
        align=int(a.get("align", 1)),
        line_spacing=float(a.get("line_spacing", 0.25)),
        letter_spacing=float(a.get("letter_spacing", 0.0)),
    )
    if a.get("font"):
        kwargs["font"] = catalog.resolve("font", a["font"], E.UNKNOWN_FONT)
    for key, param in (("border_color", "border_color"),
                       ("border_width", "border_width"),
                       ("background_color", "background_color"),
                       ("background_alpha", "background_alpha"),
                       ("background_round_radius", "background_round_radius"),
                       ("shadow_enabled", "shadow_enabled")):
        if a.get(key) is not None:
            kwargs[param] = a[key]
    for key, kind, param in (("intro_animation", "text_intro", "intro_animation"),
                             ("outro_animation", "text_outro", "outro_animation")):
        if a.get(key):
            kwargs[param] = catalog.resolve(kind, a[key], E.UNKNOWN_ANIMATION)
    if a.get("loop_animation"):
        raise E.CapcutError(
            E.OPERATION_NOT_SUPPORTED,
            "Animação de loop de texto não é aplicável nesta versão.",
            "O catálogo tem 53 opções (capcut.catalog.list kind='text_loop') mas o "
            "upstream não expõe parâmetro para aplicá-las. Use intro/outro_animation.",
        )

    styles = a.get("text_styles")
    if styles:
        # O construtor real é TextStyleRange(start, end, style: Text_style, border,
        # font_str). O mcp_server.py do upstream passa font_size/font_color/bold/...
        # como kwargs, que NÃO existem — por isso o multi-estilo dele sempre falha
        # com TypeError. Aqui montamos o Text_style corretamente.
        from pyJianYingDraft.text_segment import Text_style
        from util import hex_to_rgb

        ordered = sorted(styles, key=lambda s: int(s.get("start", 0)))
        for i in range(1, len(ordered)):
            if int(ordered[i]["start"]) < int(ordered[i - 1]["end"]):
                raise E.CapcutError(
                    E.INVALID_STYLE_RANGE,
                    f"As faixas de estilo se sobrepõem em torno do caractere "
                    f"{ordered[i]['start']}.",
                    "Ordene as faixas e evite sobreposição.")
        ranges = []
        for s in ordered:
            start_i, end_i = int(s.get("start", 0)), int(s.get("end", 0))
            if not (0 <= start_i < end_i <= len(text)):
                raise E.CapcutError(
                    E.INVALID_STYLE_RANGE,
                    f"Faixa de estilo inválida: {start_i}–{end_i} para um texto de "
                    f"{len(text)} caracteres.",
                    "Use 0 <= start < end <= len(text).",
                )
            ranges.append(TextStyleRange(
                start=start_i, end=end_i,
                style=Text_style(
                    size=float(s.get("font_size", font_size)),
                    bold=bool(s.get("bold", False)),
                    italic=bool(s.get("italic", False)),
                    underline=bool(s.get("underline", False)),
                    color=hex_to_rgb(s.get("font_color")
                                     or a.get("font_color", "#FFFFFF")),
                    align=int(a.get("align", 1)),
                ),
                font_str=(catalog.resolve("font", s["font"], E.UNKNOWN_FONT)
                          if s.get("font") else None),
            ))
        kwargs["text_styles"] = ranges

    if abs(kwargs["transform_y"]) > 0.85:
        bus.add("TEXT_UNSAFE_ZONE",
                f"transform_y={kwargs['transform_y']} fica na borda, onde a interface do "
                "sistema pode cobrir o texto. Prefeira |y| <= 0.85.")
    if not a.get("border_width") and not a.get("background_alpha"):
        bus.add("TEXT_LOW_CONTRAST",
                "Texto sem borda nem fundo pode ficar ilegível sobre vídeo. "
                "Considere border_width ou background_alpha.")

    with bus.capture():
        add_text_impl(**kwargs)

    info = _seg_info(script, track)
    info.update({"kind": "text", "text": text, "font_size": font_size,
                 "resolved_font": kwargs.get("font"),
                 "style_ranges": len(styles) if styles else 0})
    return info


# ------------------------------------------------------------------ replay
APPLIERS = {"video": apply_video, "image": apply_image,
            "audio": apply_audio, "text": apply_text}


def record(draft_id: str, op: str, args: Dict[str, Any], resolved: Dict[str, Any]) -> None:
    """Grava o passo no plano declarativo (spec A5) — base do rebuild e do replay."""
    registry.append_plan(draft_id, {
        "op": op,
        "args": {k: v for k, v in args.items() if k != "draft_id"},
        "timeline_start_s": resolved.get("timeline_start_s"),
        "timeline_end_s": resolved.get("timeline_end_s"),
        "track": resolved.get("track"),
    })


def replay(script: Any, draft_id: str, plan: list, bus: obs.WarningBus) -> int:
    """Reexecuta os passos de mídia registrados (spec D4)."""
    applied = 0
    for step in plan:
        op = step.get("op")
        if op == "create":
            continue
        applier = APPLIERS.get(op)
        if applier is None:
            raise E.CapcutError(
                E.OPERATION_NOT_SUPPORTED, f"Passo desconhecido no plano: {op}",
                "O registry pode ser de uma versão anterior; recrie o draft.")
        applier(script, draft_id, step.get("args", {}), bus)
        applied += 1
    return applied


# --------------------------------------------------------------- legendas
# Presets com contraste embutido. Os defaults do upstream são border_width=0.0 e
# background_alpha=0.0 — ou seja, texto pelado sobre vídeo, ilegível na prática.
SUBTITLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "outline": {"border_width": 6.0, "border_color": "#000000",
                "background_alpha": 0.0},
    "boxed": {"border_width": 0.0, "background_color": "#000000",
              "background_alpha": 0.65, "background_round_radius": 12.0},
    "outline_boxed": {"border_width": 5.0, "border_color": "#000000",
                      "background_color": "#000000", "background_alpha": 0.45,
                      "background_round_radius": 12.0},
    "plain": {},                       # sem contraste: só com escolha explícita
}
DEFAULT_SUBTITLE_PRESET = "outline"
SUBTITLE_FONT_SIZE = 8.0               # ~31 px num canvas 1080x1920 (calibrado na Phase 3)
TRACK_SUBTITLE = "subtitle"


def apply_subtitle(script: Any, draft_id: str, a: Dict[str, Any],
                   bus: obs.WarningBus) -> Dict[str, Any]:
    """Cria um segmento de texto por bloco de legenda.

    Não usa `Script_file.import_srt` — ver o docstring de `subtitles.py` para o porquê.
    Tudo é validado ANTES da primeira mutação, então uma falha não deixa track órfã.
    """
    from . import subtitles as SUB

    track = a.get("track") or TRACK_SUBTITLE
    srt = a.get("srt")
    segments = a.get("segments")
    if bool(srt) == bool(segments):
        raise E.CapcutError(
            E.MISSING_REQUIRED_PARAM,
            "Informe exatamente um entre 'srt' e 'segments'.",
            "'srt' aceita caminho de arquivo, URL ou conteúdo SRT inline; "
            "'segments' aceita [{start, end, text}].",
        )

    # ---- 1. carregar e validar tudo antes de tocar no draft
    if srt:
        content, origin = SUB.load_source(srt)
        blocks = SUB.parse_srt(content)
    else:
        origin = "segments"
        blocks = SUB.from_segments(segments)
    offset = float(a.get("time_offset", 0.0))
    blocks = SUB.validate_blocks(blocks, offset)

    if script.tracks.get(track) and script.tracks[track].segments:
        raise E.CapcutError(
            E.SEGMENT_OVERLAP,
            f"A track '{track}' já tem legendas.",
            "Use outra track, ou reconstrua o draft com capcut.draft.rebuild.",
            track=track,
        )

    style = dict(SUBTITLE_PRESETS[a.get("style", DEFAULT_SUBTITLE_PRESET)])
    font_size = float(a.get("font_size", SUBTITLE_FONT_SIZE))
    font = a.get("font")
    resolved_font = catalog.resolve("font", font, E.UNKNOWN_FONT) if font else None
    # fixed_width como o import_srt faz: proporção da largura, conforme a orientação
    portrait = script.height >= script.width
    fixed_width = (SUB.FIXED_WIDTH_PORTRAIT if portrait
                   else SUB.FIXED_WIDTH_LANDSCAPE)

    # ---- 2. quebrar em limite de palavra (o app quebra por caractere)
    limit = int(a.get("max_chars_per_line")
                or SUB.chars_per_line(font_size, fixed_width))
    wrapped_any = []
    for b in blocks:
        novo, houve = SUB.wrap_text(b["text"], limit)
        b["text"] = novo
        if houve:
            wrapped_any.append(b["index"])
    if wrapped_any:
        bus.add("SUBTITLE_WRAPPED",
                f"{len(wrapped_any)} legenda(s) passaram de {limit} caracteres e foram "
                "quebradas em limite de palavra. Sem isso o CapCut quebraria no meio da "
                "palavra (verificado). Encurte o texto ou ajuste max_chars_per_line.",
                blocks=wrapped_any, limit=limit)

    # ---- 3. mutar
    from add_text_impl import add_text_impl
    created = []
    with bus.capture():
        for b in blocks:
            kwargs: Dict[str, Any] = dict(
                text=b["text"], draft_id=draft_id, track_name=track,
                start=b["start"], end=b["end"],
                font_size=font_size,
                font_color=a.get("font_color", "#FFFFFF"),
                transform_x=_check_transform("transform_x",
                                             float(a.get("transform_x", 0.0))),
                transform_y=_check_transform("transform_y",
                                             float(a.get("transform_y", -0.8))),
                align=int(a.get("align", 1)),
                bold=bool(a.get("bold", False)),
                line_spacing=float(a.get("line_spacing", 0.25)),
                fixed_width=fixed_width,
                **style,
            )
            if resolved_font:
                kwargs["font"] = resolved_font
            add_text_impl(**kwargs)
            created.append({"index": b["index"], "start_s": round(b["start"], 3),
                            "end_s": round(b["end"], 3),
                            "lines": b["text"].count("\n") + 1})

    imported = len(script.tracks[track].segments)
    if imported != len(blocks):
        raise E.CapcutError(
            E.INTERNAL_ERROR,
            f"Esperava {len(blocks)} legendas na track mas encontrei {imported}.",
            "Consulte o log estruturado; nenhum bloco deveria ser perdido.",
            expected=len(blocks), found=imported,
        )
    if abs(float(a.get("transform_y", -0.8))) > 0.85:
        bus.add("TEXT_UNSAFE_ZONE",
                "As legendas ficam na borda, onde a interface do sistema pode cobri-las. "
                "Prefira |transform_y| <= 0.85.")
    if a.get("style") == "plain":
        bus.add("TEXT_LOW_CONTRAST",
                "O preset 'plain' não tem borda nem fundo; sobre vídeo a legenda pode "
                "ficar ilegível.")

    gaps = sum(1 for p, c in zip(blocks, blocks[1:]) if c["start"] - p["end"] > 0.5)
    return {
        "track": track,
        "blocks_imported": imported,
        "timeline_start_s": round(blocks[0]["start"], 3),
        "timeline_end_s": round(blocks[-1]["end"], 3),
        "source_kind": origin,
        "first_start_s": round(blocks[0]["start"], 3),
        "last_end_s": round(blocks[-1]["end"], 3),
        "time_offset_s": offset,
        "style": a.get("style", DEFAULT_SUBTITLE_PRESET),
        "font_size": font_size,
        "resolved_font": resolved_font,
        "fixed_width_ratio": fixed_width,
        "gaps_over_500ms": gaps,
        "max_chars_per_line": limit,
        "wrapped_blocks": wrapped_any,
        "blocks": created,
    }


APPLIERS["subtitle"] = apply_subtitle
