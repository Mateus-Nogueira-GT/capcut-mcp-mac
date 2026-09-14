"""Handlers de inspeção, catálogo, probe e rebuild."""
from __future__ import annotations

from typing import Any, Dict, List

from . import catalog, errors as E, handlers_media as HM, media, obs, profile, registry
from .upstream import DRAFT_CACHE, get_or_create_draft, update_cache

US = media.US


# ------------------------------------------------------------ media.probe
def media_probe(a: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    sources = a.get("sources")
    if isinstance(sources, str):
        sources = [sources]
    if not sources:
        raise E.CapcutError(E.MISSING_REQUIRED_PARAM, "Informe 'sources'.",
                            "Passe uma lista de caminhos ou URLs.")
    results, failures = [], []
    for src in sources:
        try:
            results.append(media.probe(src, use_cache=not a.get("refresh", False)))
        except E.CapcutError as exc:
            failures.append({"source": src, "error": exc.to_dict()})
    for r in results:
        if not r["extension_matches_content"]:
            bus.add("FORMAT_EXTENSION_MISMATCH",
                    f"{r['source']}: extensão sugere '{r['extension_kind']}' mas o "
                    f"conteúdo é '{r['kind']}'.")
    return {"probed": results, "failed": failures,
            "note": "Use duration_s para calcular timeline_start e duration antes de "
                    "adicionar mídia. Sem duração resolvida, segmentos podem colidir."}


# ----------------------------------------------------------- catalog.list
def catalog_list(a: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    kind = a.get("kind")
    if kind not in catalog.KINDS:
        raise E.CapcutError(
            E.UNKNOWN_CATALOG, f"Catálogo desconhecido: {kind}",
            f"Válidos: {', '.join(catalog.KINDS)}.",
        )
    out = catalog.query(kind, search=a.get("search"),
                        limit=int(a.get("limit", 50)), offset=int(a.get("offset", 0)))
    if not out.get("applicable", True):
        bus.add("CATALOG_NOT_APPLICABLE", out["applicability_note"], kind=kind)
    return out


# ---------------------------------------------------------- draft.inspect
def draft_inspect(a: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    draft_id = a.get("draft_id")
    entry = registry.get(draft_id)
    script = DRAFT_CACHE.get(draft_id)
    if script is None:
        return {
            "draft_id": draft_id, "name": entry.get("name"),
            "state": entry.get("state"), "in_memory": False,
            "canvas": entry.get("canvas"),
            "plan_steps": len(entry.get("plan", [])),
            "saved_to": entry.get("saved_to"),
            "note": "O draft não está na memória deste processo. O próximo save o "
                    "reconstrói pelo plano registrado.",
        }
    tracks: List[Dict[str, Any]] = []
    for name, track in script.tracks.items():
        segs = []
        for i, seg in enumerate(track.segments):
            item = {
                "index": i,
                "start_s": round(seg.target_timerange.start / US, 3),
                "end_s": round(seg.target_timerange.end / US, 3),
                "duration_s": round(seg.target_timerange.duration / US, 3),
            }
            src = getattr(seg, "source_timerange", None)
            if src is not None:
                item["source_start_s"] = round(src.start / US, 3)
                item["source_duration_s"] = round(src.duration / US, 3)
            segs.append(item)
        tracks.append({
            "name": name,
            "type": track.track_type.name,
            "segments": segs,
            "segment_count": len(segs),
            "end_s": round(media.track_end(script, name), 3),
            "pending_keyframes": len(getattr(track, "pending_keyframes", []) or []),
        })
    total = sum(t["segment_count"] for t in tracks)
    gaps = _find_gaps(tracks)
    if gaps:
        bus.add("TIMELINE_GAPS", f"{len(gaps)} intervalo(s) sem conteúdo detectado(s).",
                gaps=gaps[:5])
    empty = [t["name"] for t in tracks if t["segment_count"] == 0]
    return {
        "draft_id": draft_id, "name": entry.get("name"), "state": entry.get("state"),
        "in_memory": True, "canvas": entry.get("canvas"),
        "duration_s": round(max((t["end_s"] for t in tracks), default=0.0), 3),
        "tracks": tracks, "total_segments": total,
        "empty_tracks": empty, "plan_steps": len(entry.get("plan", [])),
        "saved_to": entry.get("saved_to"),
    }


def _find_gaps(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    gaps = []
    for t in tracks:
        prev_end = None
        for seg in t["segments"]:
            if prev_end is not None and seg["start_s"] - prev_end > 0.04:
                gaps.append({"track": t["name"], "from_s": prev_end,
                             "to_s": seg["start_s"]})
            prev_end = seg["end_s"]
    return gaps


# ---------------------------------------------------------- draft.rebuild
def draft_rebuild(a: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    """Reconstrói o draft aplicando uma nova ordem ao plano declarativo.

    Substitui a reordenação de clipes, que o upstream NÃO suporta: não existe API de
    remover ou mover segmento em nenhuma camada. Aqui o draft é recriado do zero com os
    mesmos passos em outra ordem e os `timeline_start` recalculados em cadeia.
    """
    draft_id = a.get("draft_id")
    entry = registry.get(draft_id)
    plan = entry.get("plan", [])
    steps = [s for s in plan if s.get("op") != "create"]
    if not steps:
        raise E.CapcutError(
            E.DRAFT_EMPTY, "O plano não tem passos de mídia para reordenar.",
            "Adicione mídia antes de reconstruir.")

    order = a.get("order")
    if order is None:
        order = list(range(len(steps)))
    if sorted(order) != list(range(len(steps))):
        raise E.CapcutError(
            E.MISSING_REQUIRED_PARAM,
            f"'order' deve ser uma permutação de 0..{len(steps) - 1}; veio {order}.",
            f"O plano tem {len(steps)} passos. Use capcut.draft.inspect para vê-los.",
        )

    canvas = entry.get("canvas", {})
    with bus.capture():
        _tmp_id, script = get_or_create_draft(width=int(canvas.get("width", 1080)),
                                              height=int(canvas.get("height", 1920)))
    update_cache(draft_id, script)

    # zera o plano e reaplica na nova ordem, deixando o append recalcular o tempo
    data = registry._load()
    data["drafts"][draft_id]["plan"] = [s for s in plan if s.get("op") == "create"]
    registry._save_atomic(data)

    applied = []
    for pos in order:
        step = steps[pos]
        args = dict(step.get("args", {}))
        if a.get("recompute_timeline", True):
            args.pop("timeline_start", None)      # deixa anexar em sequência
        info = HM.APPLIERS[step["op"]](script, draft_id, args, bus)
        HM.record(draft_id, step["op"], args, info)
        applied.append({"op": step["op"], "from_index": pos,
                        "timeline_start_s": info.get("timeline_start_s"),
                        "timeline_end_s": info.get("timeline_end_s")})
    return {
        "draft_id": draft_id, "steps_reapplied": len(applied), "order": order,
        "applied": applied,
        "duration_s": round(max((s["timeline_end_s"] or 0) for s in applied), 3),
        "note": "O draft foi reconstruído em memória. Chame capcut.draft.save para "
                "gravar; use overwrite=true se o projeto já existir em disco.",
    }


# --------------------------------------------------------- draft.validate
def draft_validate(a: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    from . import validator as V

    draft_id = a.get("draft_id")
    entry = registry.get(draft_id)
    script = DRAFT_CACHE.get(draft_id)
    if script is None:
        raise E.CapcutError(
            E.DRAFT_NOT_FOUND,
            f"O draft '{draft_id}' não está na memória deste processo.",
            "Recrie o draft nesta sessão, ou chame capcut.draft.save, que o "
            "reconstrói pelo plano registrado antes de validar.",
            draft_id=draft_id)

    report = V.validate(script, entry)
    order = {V.ERROR: 0, V.WARNING: 1, V.INFO: 2}
    floor = order[a.get("min_severity", V.INFO)]
    report["issues"] = [i for i in report["issues"] if order[i["severity"]] <= floor]
    report["draft_id"] = draft_id
    if not report["ok"]:
        bus.add("VALIDATION_FAILED",
                f"{report['counts'][V.ERROR]} erro(s) impedem o save.",
                codes=[i["code"] for i in report["issues"]
                       if i["severity"] == V.ERROR])
    return report
