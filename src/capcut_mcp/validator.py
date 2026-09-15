"""Validação pré-save, focada no fluxo cortar + legendar + texto (spec: Validation).

O upstream não tem nenhuma linha de validação. A única coisa parecida é destrutiva: no
`save`, um passe O(n²) detecta sobreposição e **apaga** o segmento de índice maior.

Aqui a validação é de leitura: reporta e, por default, bloqueia o save quando há erro.
As regras foram escolhidas pelos erros que este fluxo realmente comete — texto que
aparece depois do vídeo acabar, legenda fora da safe zone, corte com buraco no meio.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from . import media

US = media.US

ERROR = "error"
WARNING = "warning"
INFO = "info"

TEXT_KINDS = {"text"}
VIDEO_KINDS = {"video"}


def _issue(code: str, severity: str, message: str, suggestion: str = "",
           **context: Any) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "message": message,
            "suggestion": suggestion, "context": context}


def validate(script: Any, entry: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    tracks = script.tracks
    issues += _check_caption_sync(entry)
    issues += _check_cut_mid_word(entry)

    # ---------------------------------------------------------- vazio
    total = sum(len(t.segments) for t in tracks.values())
    if total == 0:
        issues.append(_issue(
            "V_EMPTY_DRAFT", ERROR, "O draft não tem nenhum segmento.",
            "Adicione vídeo, texto ou legenda antes de salvar."))
        return _summary(issues)

    # ------------------------------------------- duração do conteúdo visual
    visual_end = 0.0
    for name, track in tracks.items():
        if track.track_type.name in VIDEO_KINDS:
            for seg in track.segments:
                visual_end = max(visual_end, seg.target_timerange.end / US)

    for name, track in tracks.items():
        kind = track.track_type.name
        segs = sorted(track.segments, key=lambda s: s.target_timerange.start)

        # -------------------------------------------------- track vazia
        if not segs:
            # 'video' é a track sem nome que o add_video_track do upstream cria sempre.
            # A Phase 3 confirmou que um projeto real do CapCut também tem uma track de
            # vídeo vazia, então avisar sobre ela em toda validação seria só ruído.
            if name != "video":
                issues.append(_issue(
                    "V_EMPTY_TRACK", WARNING, f"A track '{name}' não tem segmentos.",
                    "Tracks vazias são inofensivas, mas costumam indicar uma operação "
                    "que falhou pela metade.", track=name))
            continue

        for i, seg in enumerate(segs):
            tr = seg.target_timerange
            start_s, end_s = tr.start / US, tr.end / US

            # ------------------------------------------ duração degenerada
            if tr.duration <= 0:
                issues.append(_issue(
                    "V_ZERO_DURATION", ERROR,
                    f"Segmento {i} da track '{name}' tem duração {tr.duration} µs.",
                    "Informe duration ou source_end explicitamente.",
                    track=name, index=i))

            # -------------------- texto/legenda depois do fim do vídeo
            if kind in TEXT_KINDS and visual_end > 0 and start_s >= visual_end - 1e-6:
                issues.append(_issue(
                    "V_TEXT_AFTER_VIDEO", WARNING,
                    f"O texto em {start_s:.2f}s da track '{name}' começa depois de o "
                    f"vídeo terminar ({visual_end:.2f}s) — vai aparecer sobre tela "
                    "preta.",
                    f"Use timeline_start < {visual_end:.2f}, ou estenda o vídeo.",
                    track=name, index=i, start_s=start_s, video_end_s=visual_end))
            elif kind in TEXT_KINDS and visual_end > 0 and end_s > visual_end + 1e-6:
                issues.append(_issue(
                    "V_TEXT_EXCEEDS_VIDEO", INFO,
                    f"O texto da track '{name}' termina em {end_s:.2f}s, depois do fim "
                    f"do vídeo ({visual_end:.2f}s).",
                    "O trecho final aparecerá sobre tela preta.",
                    track=name, index=i))

            # ------------------------------------ safe zone e contraste
            if kind in TEXT_KINDS:
                clip = getattr(seg, "clip_settings", None)
                y = abs(getattr(clip, "transform_y", 0.0) or 0.0) if clip else 0.0
                if y > 0.85:
                    issues.append(_issue(
                        "V_TEXT_UNSAFE_ZONE", WARNING,
                        f"O texto da track '{name}' está em y={y:.2f}, na borda, onde a "
                        "interface do sistema pode cobri-lo.",
                        "Prefira |transform_y| <= 0.85.", track=name, index=i))
                if getattr(seg, "border", None) is None and \
                        getattr(seg, "background", None) is None:
                    issues.append(_issue(
                        "V_TEXT_LOW_CONTRAST", INFO,
                        f"O texto da track '{name}' não tem borda nem fundo; sobre "
                        "vídeo pode ficar ilegível.",
                        "Use border_width, background_alpha, ou o preset 'outline' "
                        "nas legendas.", track=name, index=i))

        # --------------------------------- sobreposição e buracos na track
        for prev, cur in zip(segs, segs[1:]):
            if cur.target_timerange.start < prev.target_timerange.end - 1:
                issues.append(_issue(
                    "V_OVERLAP", ERROR,
                    f"Dois segmentos da track '{name}' se sobrepõem em "
                    f"{cur.target_timerange.start / US:.2f}s.",
                    "Ajuste timeline_start, ou use tracks diferentes para sobrepor.",
                    track=name))
            gap = (cur.target_timerange.start - prev.target_timerange.end) / US
            if kind in VIDEO_KINDS and gap > 0.04:
                issues.append(_issue(
                    "V_GAP", WARNING,
                    f"Há {gap:.2f}s sem vídeo na track '{name}', a partir de "
                    f"{prev.target_timerange.end / US:.2f}s.",
                    "Um buraco na track de vídeo aparece como tela preta. Encadeie os "
                    "cortes omitindo timeline_start, que anexa ao fim da track.",
                    track=name, gap_s=round(gap, 3)))

    # ------------------------------------------------- mídia em disco
    for kind_key in ("videos", "audios"):
        for mat in getattr(script.materials, kind_key, []) or []:
            path = getattr(mat, "remote_url", None) or getattr(mat, "path", None)
            if path and not path.startswith(("http://", "https://")) \
                    and not os.path.isfile(path):
                issues.append(_issue(
                    "V_MISSING_ASSET", ERROR,
                    f"A mídia não está mais no disco: {path}",
                    "O save copia os arquivos; eles precisam existir neste momento.",
                    path=path))

    # ------------------------------------------------- proporção
    canvas = entry.get("canvas", {})
    w, h = int(canvas.get("width", 0)), int(canvas.get("height", 0))
    if w and h:
        from math import gcd
        g = gcd(w, h)
        if (w // g, h // g) not in {(9, 16), (16, 9), (1, 1), (3, 4), (4, 3)}:
            issues.append(_issue(
                "V_RATIO_INEXACT", WARNING,
                f"{w}x{h} não corresponde a nenhuma proporção que o CapCut oferece.",
                "O rótulo gravado será aproximado. Prefira 1080x1920, 1920x1080 "
                "ou 1080x1080.", width=w, height=h))

    return _summary(issues)


def _check_caption_sync(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rede contra o erro silencioso de legenda dessincronizada (spec §2.5).

    Se o draft tem corte e as legendas NÃO vieram do `from_transcript`, os tempos
    provavelmente estão em tempo da mídia original em vez da timeline.
    """
    plano = entry.get("plan", [])
    ops = [p.get("op") for p in plano]
    tem_corte = "cut" in ops or sum(1 for o in ops if o == "video") > 1
    legenda_crua = "subtitle" in ops
    legenda_remapeada = "subtitle_from_transcript" in ops
    if tem_corte and legenda_crua and not legenda_remapeada:
        return [_issue(
            "V_CAPTION_DESYNC_RISK", WARNING,
            "O draft tem corte e legendas que não passaram pelo remapeamento de tempo.",
            "Se as legendas vieram de um transcript da mídia original, elas estão "
            "dessincronizadas. Use capcut.subtitle.from_transcript, que remapeia. "
            "Se os tempos já são da timeline cortada, ignore este aviso.",
            ops=ops)]
    return []


def _check_cut_mid_word(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Corte que caiu no meio de uma palavra falada (spec §2.2).

    Só opina quando já existe transcrição em cache para aquela mídia — a validação
    nunca dispara ASR. Sem transcript, não há como saber, e o silêncio é honesto.
    """
    from . import asr

    achados: List[Dict[str, Any]] = []
    for passo in entry.get("plan", []):
        if passo.get("op") != "cut":
            continue
        args = passo.get("args", {}) or {}
        if args.get("snap") == "speech":
            continue                      # já encostado na fala por construção
        source = args.get("source")
        if not source:
            continue
        cache = asr.find_cached_by_source(source)
        if not cache:
            continue
        palavras = cache.get("words") or []
        if not palavras:
            continue
        for par in args.get("keep") or []:
            try:
                pontas = (("início", float(par[0])), ("fim", float(par[1])))
            except (TypeError, ValueError, IndexError):
                continue
            for rotulo, t in pontas:
                dentro = next((w for w in palavras
                               if w["start"] + 0.02 < t < w["end"] - 0.02), None)
                if dentro:
                    achados.append((rotulo, t, dentro))
    if not achados:
        return []
    amostra = [{"ponta": r, "t_s": round(t, 3), "palavra": w.get("word", "").strip(),
                "palavra_s": [round(w["start"], 3), round(w["end"], 3)]}
               for r, t, w in achados[:6]]
    return [_issue(
        "V_CUT_MID_WORD", INFO,
        f"{len(achados)} ponta(s) de corte caem no meio de uma palavra falada.",
        "O corte vai soar truncado. Repita o capcut.video.cut com snap='speech', "
        "que move as pontas para a fronteira de palavra mais próxima.",
        pontas=amostra)]


def _summary(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {sev: sum(1 for i in issues if i["severity"] == sev)
              for sev in (ERROR, WARNING, INFO)}
    return {
        "ok": counts[ERROR] == 0,
        "issues": issues,
        "counts": counts,
        "summary": (f"{counts[ERROR]} erro(s), {counts[WARNING]} aviso(s), "
                    f"{counts[INFO]} informativo(s)"),
    }
