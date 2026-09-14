"""Catálogos do CapCut expostos a partir dos metadados do L0 (spec: G3, C16).

Por que existe: todos os enums do upstream exigem match EXATO e case-sensitive do
identificador Python (`getattr(Enum, nome)`). Sem descoberta, o agente adivinha e erra —
foi o que a auditoria mostrou: os nomes documentados (`fade_in`, `circle`) falham,
enquanto os reais (`Mix`, `Circle`) funcionam. Pior, o `constants.ts` do MCP TypeScript
do upstream traz catálogos inventados.

Os catálogos vêm SEMPRE dos metadados do L0, nunca de listas escritas à mão (A7).
Paginados e filtráveis porque há 345 efeitos e 468 filtros — a lista inteira estouraria
o contexto do agente (C16).
"""
from __future__ import annotations

import difflib
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from . import errors as E
from . import upstream as _upstream  # noqa: F401 — põe o L0 no sys.path

# kind -> (módulo, atributo do enum CapCut)
_SOURCES: Dict[str, Tuple[str, str]] = {
    "transition": ("pyJianYingDraft.metadata.capcut_transition_meta",
                   "CapCut_Transition_type"),
    "mask": ("pyJianYingDraft.metadata.capcut_mask_meta", "CapCut_Mask_type"),
    "font": ("pyJianYingDraft.metadata.font_meta", "Font_type"),
    "animation_intro": ("pyJianYingDraft.metadata.capcut_animation_meta",
                        "CapCut_Intro_type"),
    "animation_outro": ("pyJianYingDraft.metadata.capcut_animation_meta",
                        "CapCut_Outro_type"),
    "animation_combo": ("pyJianYingDraft.metadata.capcut_animation_meta",
                        "CapCut_Group_animation_type"),
    "text_intro": ("pyJianYingDraft.metadata.capcut_text_animation_meta",
                   "CapCut_Text_intro"),
    "text_outro": ("pyJianYingDraft.metadata.capcut_text_animation_meta",
                   "CapCut_Text_outro"),
    "text_loop": ("pyJianYingDraft.metadata.capcut_text_animation_meta",
                  "CapCut_Text_loop_anim"),
    "effect_scene": ("pyJianYingDraft.metadata.capcut_effect_meta",
                     "CapCut_Video_scene_effect_type"),
    "effect_character": ("pyJianYingDraft.metadata.capcut_effect_meta",
                         "CapCut_Video_character_effect_type"),
    "audio_effect_filter": ("pyJianYingDraft.metadata.capcut_audio_effect_meta",
                            "CapCut_Voice_filters_effect_type"),
    "audio_effect_character": ("pyJianYingDraft.metadata.capcut_audio_effect_meta",
                               "CapCut_Voice_characters_effect_type"),
    "filter": ("pyJianYingDraft.metadata.filter_meta", "Filter_type"),
}

KINDS = sorted(_SOURCES) + ["keyframe_property"]

# Não aplicáveis na v1, mas listáveis para o agente saber que existem.
NOT_APPLICABLE = {
    "text_loop": "Catalogado, mas o upstream não expõe parâmetro para aplicar animação "
                 "de loop em texto. Fora de escopo nesta versão.",
    "filter": "Catalogado (468), mas nenhuma tool do upstream aplica filtros. "
              "Fora de escopo nesta versão.",
    "effect_scene": "Aplicável a partir da Phase 5.",
    "effect_character": "Aplicável a partir da Phase 5.",
}

KEYFRAME_PROPERTIES = [
    {"name": "position_x", "unit": "meia largura do canvas (valor do app ÷ largura)",
     "range": "-10..10", "segments": ["video", "image"]},
    {"name": "position_y", "unit": "meia altura do canvas; POSITIVO = para cima",
     "range": "-10..10", "segments": ["video", "image"]},
    {"name": "rotation", "unit": "graus, sentido horário; aceita '45deg'",
     "range": "livre", "segments": ["video", "image"]},
    {"name": "scale_x", "unit": "fator (1.0 = sem escala); exclusivo com uniform_scale",
     "range": "> 0", "segments": ["video", "image"]},
    {"name": "scale_y", "unit": "fator (1.0 = sem escala); exclusivo com uniform_scale",
     "range": "> 0", "segments": ["video", "image"]},
    {"name": "uniform_scale", "unit": "fator nos dois eixos; exclusivo com scale_x/scale_y",
     "range": "> 0", "segments": ["video", "image"]},
    {"name": "alpha", "unit": "opacidade; aceita '50%'", "range": "0..1",
     "segments": ["video", "image"]},
    {"name": "saturation", "unit": "aceita '+0.5'/'-0.5'", "range": "-1..1",
     "segments": ["video", "image"]},
    {"name": "contrast", "unit": "aceita '+0.5'/'-0.5'", "range": "-1..1",
     "segments": ["video", "image"]},
    {"name": "brightness", "unit": "aceita '+0.5'/'-0.5'", "range": "-1..1",
     "segments": ["video", "image"]},
    {"name": "volume", "unit": "1.0 = original; aceita '80%'", "range": ">= 0",
     "segments": ["video", "audio"]},
]


@lru_cache(maxsize=None)
def _entries(kind: str) -> Tuple[Dict[str, Any], ...]:
    if kind == "keyframe_property":
        return tuple(dict(p, kind=kind) for p in KEYFRAME_PROPERTIES)
    if kind not in _SOURCES:
        raise E.CapcutError(
            E.UNKNOWN_CATALOG, f"Catálogo desconhecido: {kind}",
            f"Catálogos válidos: {', '.join(KINDS)}.",
        )
    import importlib
    module_name, attr = _SOURCES[kind]
    enum_cls = getattr(importlib.import_module(module_name), attr)
    out: List[Dict[str, Any]] = []
    for member in enum_cls:
        meta = member.value
        item: Dict[str, Any] = {"name": member.name, "kind": kind,
                                "is_vip": bool(getattr(meta, "is_vip", False))}
        dur = getattr(meta, "default_duration", None)
        if dur:
            item["default_duration_us"] = dur
            item["default_duration_s"] = round(dur / 1_000_000, 3)
        params = getattr(meta, "params", None)
        if params:
            item["params"] = [
                {"name": p.name, "default": p.default_value,
                 "min": p.min_value, "max": p.max_value} for p in params
            ]
        out.append(item)
    return tuple(out)


def names(kind: str) -> List[str]:
    return [e["name"] for e in _entries(kind)]


def count(kind: str) -> int:
    return len(_entries(kind))


def query(kind: str, search: Optional[str] = None, limit: int = 50,
          offset: int = 0) -> Dict[str, Any]:
    items = list(_entries(kind))
    if search:
        needle = search.lower()
        items = [i for i in items if needle in i["name"].lower()]
    total = len(items)
    page = items[offset:offset + limit]
    out = {
        "kind": kind,
        "total": total,
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "items": page,
        "case_sensitive": True,
        "note": "Os nomes exigem correspondência exata, incluindo maiúsculas e "
                "sublinhados. 'fade_in' não existe; 'Fade_In' sim.",
    }
    if kind in NOT_APPLICABLE:
        out["applicable"] = False
        out["applicability_note"] = NOT_APPLICABLE[kind]
    else:
        out["applicable"] = True
    return out


def resolve(kind: str, value: str, code: str) -> str:
    """Normaliza o nome (case-insensitive) para o identificador canônico.

    Erro de catálogo traz até 3 candidatos por similaridade (spec E4).
    """
    all_names = names(kind)
    if value in all_names:
        return value
    lowered = {n.lower(): n for n in all_names}
    if value.lower() in lowered:
        return lowered[value.lower()]
    suggestions = difflib.get_close_matches(value, all_names, n=3, cutoff=0.4)
    hint = f"Talvez: {', '.join(suggestions)}." if suggestions else ""
    raise E.CapcutError(
        code, f"'{value}' não existe no catálogo '{kind}'.",
        f"{hint} Use capcut.catalog.list(kind='{kind}', search='...') para procurar. "
        f"O catálogo tem {len(all_names)} itens e os nomes são case-sensitive.".strip(),
        kind=kind, value=value, suggestions=suggestions,
    )


def vip_warning(kind: str, name: str) -> Optional[Dict[str, Any]]:
    for entry in _entries(kind):
        if entry["name"] == name and entry.get("is_vip"):
            return {"code": "VIP_RESOURCE",
                    "message": f"'{name}' ({kind}) é um recurso VIP do CapCut; pode "
                               f"aparecer bloqueado ou com marca d'água.",
                    "context": {"kind": kind, "name": name}}
    return None
