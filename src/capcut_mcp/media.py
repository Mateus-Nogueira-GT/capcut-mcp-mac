"""Probe de mídia e planejamento de timeline (spec: MED-01..03, WI-3.33, WI-3.34).

Por que o planner existe: o L0 deixa a duração em 0.0 quando `end`/`duration` não são
informados e só a resolve no `save`, via ffprobe. Nesse momento um passe O(n²) detecta
sobreposição e **apaga o segmento de índice maior**. Verificado na auditoria: três
clipes adicionados sem duração viraram um. Aqui a duração é resolvida ANTES de mutar e
a colisão é erro, nunca deleção.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from . import errors as E

_CACHE: Dict[str, Dict[str, Any]] = {}

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".flv", ".mpg", ".mpeg"}
AUDIO_EXT = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".aiff", ".caf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tiff"}

US = 1_000_000  # microssegundos por segundo


def _is_remote(src: str) -> bool:
    return src.startswith(("http://", "https://"))


def kind_of(src: str) -> str:
    ext = os.path.splitext(src.split("?")[0])[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    return "unknown"


def probe(source: str, use_cache: bool = True) -> Dict[str, Any]:
    """Duração, dimensão e formato reais. ffprobe é obrigatório (MED-01)."""
    if use_cache and source in _CACHE:
        return _CACHE[source]
    if not shutil.which("ffprobe"):
        raise E.CapcutError(
            E.FFPROBE_UNAVAILABLE, "ffprobe não encontrado no PATH.",
            "Instale o FFmpeg: brew install ffmpeg",
        )
    local = not _is_remote(source)
    if local:
        source = os.path.abspath(os.path.expanduser(source))
        if not os.path.isfile(source):
            raise E.CapcutError(
                E.SOURCE_NOT_FOUND, f"Arquivo não encontrado: {source}",
                "Informe o caminho absoluto de um arquivo existente.", source=source,
            )
        if os.path.getsize(source) == 0:
            raise E.CapcutError(
                E.SOURCE_NOT_FOUND, f"Arquivo vazio: {source}",
                "O arquivo existe mas tem 0 bytes.", source=source,
            )

    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "stream=codec_type,codec_name,width,height,duration:format=duration,format_name",
           "-of", "json", source]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                             check=True).stdout
        info = json.loads(raw)
    except subprocess.TimeoutExpired as exc:
        raise E.CapcutError(
            E.PROBE_FAILED,
            f"ffprobe excedeu 30 s em {source}",
            "Se for URL remota, baixe o arquivo antes de usá-lo.", source=source,
        ) from exc
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise E.CapcutError(
            E.SOURCE_NOT_FOUND,
            f"Não foi possível ler a mídia: {os.path.basename(source)}",
            "Confirme que o arquivo é um vídeo, áudio ou imagem válido.",
            source=source, ffprobe=str(exc)[:200],
        ) from exc

    streams = info.get("streams", []) or []
    video_s = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_s = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = None
    for candidate in ([video_s, audio_s] if video_s or audio_s else []):
        if candidate and candidate.get("duration"):
            duration = float(candidate["duration"])
            break
    if duration is None and info.get("format", {}).get("duration"):
        duration = float(info["format"]["duration"])

    ext_kind = kind_of(source)
    # imagem: tem stream de vídeo mas sem duração real
    if video_s and not audio_s and (duration is None or duration <= 0.1) \
            and ext_kind == "image":
        real_kind = "image"
    elif video_s:
        real_kind = "video"
    elif audio_s:
        real_kind = "audio"
    else:
        real_kind = "unknown"

    result = {
        "source": source,
        "kind": real_kind,
        "extension_kind": ext_kind,
        "extension_matches_content": real_kind == ext_kind,
        "duration_s": round(duration, 3) if duration else None,
        "width": int(video_s["width"]) if video_s and video_s.get("width") else None,
        "height": int(video_s["height"]) if video_s and video_s.get("height") else None,
        "codec": (video_s or audio_s or {}).get("codec_name"),
        "container": info.get("format", {}).get("format_name"),
        "has_audio": audio_s is not None,
        "is_remote": _is_remote(source),
        "bytes": os.path.getsize(source) if not _is_remote(source) else None,
    }
    _CACHE[source] = result
    return result


# ------------------------------------------------------------------ planner
def resolve_range(source_probe: Dict[str, Any], source_start: Optional[float],
                  source_end: Optional[float], duration: Optional[float],
                  speed: float) -> Tuple[float, float, float]:
    """Devolve (source_start, source_end, duração_na_timeline) em segundos.

    Recusa o que o L0 resolveria tarde e em silêncio.
    """
    media_dur = source_probe.get("duration_s")
    start = float(source_start or 0.0)
    if start < 0:
        raise E.CapcutError(E.INVALID_TIMERANGE, f"source_start negativo: {start}",
                            "Use um valor >= 0.")
    if source_end is not None:
        end = float(source_end)
    elif duration is not None:
        end = start + float(duration)
    elif media_dur:
        end = media_dur                      # usa a mídia inteira
    else:
        raise E.CapcutError(
            E.INVALID_TIMERANGE,
            "Não foi possível determinar a duração da mídia.",
            "Informe source_end ou duration explicitamente.",
        )
    if end <= start:
        raise E.CapcutError(
            E.INVALID_TIMERANGE, f"Intervalo inválido: {start}s → {end}s.",
            "source_end deve ser maior que source_start.",
        )
    if media_dur and end > media_dur + 0.05:
        raise E.CapcutError(
            E.SOURCE_RANGE_EXCEEDS_MEDIA,
            f"source_end={end}s passa do fim da mídia ({media_dur}s).",
            f"Use source_end <= {media_dur}s. A mídia não é encurtada em silêncio.",
            media_duration_s=media_dur,
        )
    if speed <= 0:
        raise E.CapcutError(E.INVALID_TIMERANGE, f"speed inválido: {speed}",
                            "Use um valor > 0 (1.0 = velocidade original).")
    return start, end, (end - start) / speed


def check_collision(script: Any, track_name: str, timeline_start: float,
                    timeline_duration: float) -> None:
    """Colisão na mesma track é ERRO (spec VID-02), nunca deleção silenciosa."""
    track = script.tracks.get(track_name)
    if track is None:
        return
    new_start = int(round(timeline_start * US))
    new_end = new_start + int(round(timeline_duration * US))
    for seg in track.segments:
        tr = seg.target_timerange
        if new_start < tr.end and tr.start < new_end:
            raise E.CapcutError(
                E.SEGMENT_OVERLAP,
                f"O intervalo {timeline_start:.2f}s–{(timeline_start + timeline_duration):.2f}s "
                f"colide com um segmento existente em '{track_name}' "
                f"({tr.start / US:.2f}s–{tr.end / US:.2f}s).",
                f"Use timeline_start >= {tr.end / US:.2f}, ou uma track diferente para "
                "sobrepor visualmente (picture-in-picture).",
                track=track_name, conflict_start_s=tr.start / US, conflict_end_s=tr.end / US,
            )


def track_end(script: Any, track_name: str) -> float:
    """Fim da track em segundos — permite encadear clipes sem calcular à mão."""
    track = script.tracks.get(track_name)
    if track is None or not track.segments:
        return 0.0
    return max(s.target_timerange.end for s in track.segments) / US
