"""Mapeamento tempo-da-mídia -> tempo-da-timeline (spec: SPEC_ASR_E_SELECAO §2.3).

## O problema que isto resolve

O transcript está em tempo da **mídia original**. Depois de um corte, os tempos da
timeline são outros. Se as legendas forem passadas direto do transcript, elas ficam
dessincronizadas — e o JSON continua válido, então nada detecta.

Exemplo: corte mantendo [0,3] e [5,8]. A timeline tem 6 s. Uma fala em 6,0 s da origem
cai em **4,0 s** da timeline.

## Como é construído

O mapa é derivado dos **segmentos reais do script**, não do plano declarativo. Cada
segmento de vídeo carrega `source_timerange` e `target_timerange` — isso *é* o
mapeamento, vindo da verdade. Funciona igual se o corte veio de `capcut.video.cut` ou de
chamadas individuais de `capcut.video.add`.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import media

US = media.US
MIN_KEPT_S = 0.8          # sobra menor que isto não vale uma legenda


def _material_matches(script: Any, material_id: str, source: str) -> bool:
    alvo = os.path.abspath(os.path.expanduser(source))
    for mat in getattr(script.materials, "videos", []) or []:
        if getattr(mat, "material_id", None) != material_id:
            continue
        for attr in ("remote_url", "path", "replace_path"):
            valor = getattr(mat, attr, None)
            if valor and os.path.abspath(str(valor)) == alvo:
                return True
        return False
    return False


def build(script: Any, source: str) -> List[Dict[str, float]]:
    """Intervalos mantidos daquele `source`, em ordem de tempo da mídia."""
    intervalos: List[Dict[str, float]] = []
    for track in script.tracks.values():
        if track.track_type.name != "video":
            continue
        for seg in track.segments:
            src = getattr(seg, "source_timerange", None)
            if src is None:
                continue
            if not _material_matches(script, seg.material_id, source):
                continue
            intervalos.append({
                "source_start": src.start / US,
                "source_end": src.end / US,
                "timeline_start": seg.target_timerange.start / US,
                "timeline_end": seg.target_timerange.end / US,
            })
    return sorted(intervalos, key=lambda i: i["source_start"])


def map_instant(mapa: List[Dict[str, float]], t: float) -> Optional[float]:
    """Instante da mídia -> instante da timeline. None se caiu em trecho removido."""
    for iv in mapa:
        if iv["source_start"] - 1e-6 <= t <= iv["source_end"] + 1e-6:
            return iv["timeline_start"] + (t - iv["source_start"])
    return None


def map_block(mapa: List[Dict[str, float]], start: float, end: float,
              straddle: str = "truncate") -> Optional[Dict[str, Any]]:
    """Bloco em tempo de mídia -> bloco em tempo de timeline.

    Devolve None quando o bloco não sobrevive. `straddle` decide o que fazer com o
    bloco que atravessa a fronteira de um corte:
      truncate  — encurta para a parte mantida (default)
      drop      — descarta o bloco inteiro
      keep_partial — igual a truncate, mas sinaliza para o chamador avisar
    """
    melhor: Optional[Dict[str, Any]] = None
    for iv in mapa:
        ini = max(start, iv["source_start"])
        fim = min(end, iv["source_end"])
        if fim - ini <= 0:
            continue
        cand = {
            "timeline_start": iv["timeline_start"] + (ini - iv["source_start"]),
            "timeline_end": iv["timeline_start"] + (fim - iv["source_start"]),
            "source_start": ini,
            "source_end": fim,
            "kept_ratio": (fim - ini) / (end - start) if end > start else 0.0,
        }
        if melhor is None or cand["kept_ratio"] > melhor["kept_ratio"]:
            melhor = cand
    if melhor is None:
        return None
    truncado = melhor["kept_ratio"] < 0.999
    if truncado and straddle == "drop":
        return None
    if melhor["timeline_end"] - melhor["timeline_start"] < MIN_KEPT_S:
        return None                    # sobra curta demais para ser lida
    melhor["truncated"] = truncado
    return melhor


def total_kept_s(mapa: List[Dict[str, float]]) -> float:
    return round(sum(i["source_end"] - i["source_start"] for i in mapa), 3)


# ------------------------------------------------- encostar na fala (§2.2)
def snap_range(words: List[Dict[str, Any]], start: float, end: float,
               tolerance: float = 0.5, padding: float = 0.15) -> Dict[str, Any]:
    """Move as pontas para a fronteira de palavra mais próxima.

    Sem isto, "mantenha de 12,0 a 30,0" pode entrar no meio de uma sílaba.
    """
    if not words:
        return {"start": start, "end": end, "delta_start_s": 0.0,
                "delta_end_s": 0.0, "snapped": False}

    # início: primeira palavra que começa em ou depois do pedido, se estiver perto;
    # senão o começo da palavra que está em curso no instante pedido.
    novo_ini = start
    candidatos = [w for w in words if w["start"] >= start - 1e-6]
    if candidatos and candidatos[0]["start"] - start <= tolerance:
        novo_ini = candidatos[0]["start"]
    else:
        em_curso = [w for w in words if w["start"] <= start <= w["end"]]
        if em_curso and start - em_curso[0]["start"] <= tolerance:
            novo_ini = em_curso[0]["start"]

    # fim: última palavra que termina em ou antes do pedido, se estiver perto
    novo_fim = end
    anteriores = [w for w in words if w["end"] <= end + 1e-6]
    if anteriores and end - anteriores[-1]["end"] <= tolerance:
        novo_fim = anteriores[-1]["end"]
    else:
        em_curso = [w for w in words if w["start"] <= end <= w["end"]]
        if em_curso and em_curso[0]["end"] - end <= tolerance:
            novo_fim = em_curso[0]["end"]

    novo_ini = max(0.0, novo_ini - padding)
    novo_fim = novo_fim + padding
    if novo_fim - novo_ini < 0.2:                 # degenerou: não mexe
        return {"start": start, "end": end, "delta_start_s": 0.0,
                "delta_end_s": 0.0, "snapped": False}
    return {
        "start": round(novo_ini, 3),
        "end": round(novo_fim, 3),
        "delta_start_s": round(novo_ini - start, 3),
        "delta_end_s": round(novo_fim - end, 3),
        "snapped": abs(novo_ini - start) > 1e-3 or abs(novo_fim - end) > 1e-3,
    }
