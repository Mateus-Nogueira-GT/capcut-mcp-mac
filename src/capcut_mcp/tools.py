"""As tools da Phase 2 — três, deliberadamente (spec: walking skeleton).

Schemas ESTRITOS (`additionalProperties: false`): o L0 repassa `**arguments` direto
para funções Python, então qualquer chave extra viraria TypeError.

Descrições carregam o que o agente não pode adivinhar (spec C15): unidade de tempo,
o que NÃO existe, e o passo humano que fecha o fluxo.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Any, Callable, Dict, Tuple

from . import deployer, errors as E, obs, profile, registry
from .upstream import (DRAFT_CACHE, get_or_create_draft, upstream_commit,
                       assert_no_forbidden_imports)

MAX_DIM = 4096


# ------------------------------------------------------------------ doctor
def doctor(_: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    out: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "upstream_commit": upstream_commit(),
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "capcut_app_version": profile.installed_app_version(),
        "registry_path": registry.REGISTRY_PATH,
        "log_dir": obs.LOG_DIR,
        "drafts_in_session": len(registry.listing()),
    }
    if not ffprobe:
        bus.add("FFPROBE_MISSING", "ffprobe não está no PATH; o save vai falhar.",
                fix="brew install ffmpeg")
    try:
        inst = profile.detect()
        free = deployer._free_bytes(inst.projects_dir)
        out.update({
            "projects_dir": inst.projects_dir,
            "projects_dir_writable": os.access(inst.projects_dir, os.W_OK),
            "reference_project": inst.reference_project,
            "template_dir": inst.template_dir,
            "draft_new_version": inst.new_version,
            "platform_app_version": inst.platform.get("app_version"),
            "free_disk_gib": round(free / 1024**3, 1),
            "projects": profile.list_projects(inst.projects_dir),
            "profile": {
                "name": "capcut_detected",
                "content_file": "draft_info.json",
                "multi_timeline": True,
            },
        })
        if free < deployer.MIN_FREE_BYTES:
            bus.add("LOW_DISK", f"Só {free / 1024**3:.1f} GiB livres; o save exige "
                                f"{deployer.MIN_FREE_BYTES / 1024**3:.0f} GiB.")
        app_v = out.get("capcut_app_version")
        tpl_v = inst.platform.get("app_version")
        if app_v and tpl_v and str(app_v) != str(tpl_v):
            bus.add("VERSION_DRIFT",
                    f"O CapCut instalado é {app_v} mas o projeto de referência foi feito "
                    f"na {tpl_v}. Recapture a referência.",
                    installed=app_v, reference=tpl_v)
        out["ready"] = bool(ffprobe and out["projects_dir_writable"]
                            and free >= deployer.MIN_FREE_BYTES)
    except E.CapcutError as exc:
        out["ready"] = False
        out["blocker"] = exc.to_dict()
    assert_no_forbidden_imports()
    return out


# ------------------------------------------------------------ draft.create
def draft_create(args: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    width = int(args.get("width", 1080))
    height = int(args.get("height", 1920))
    fps = int(args.get("fps", 30))
    name = deployer.sanitize_project_name(args.get("name") or "")

    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        raise E.CapcutError(
            E.INVALID_DIMENSIONS,
            f"Resolução inválida: {width}x{height}.",
            f"Use valores inteiros entre 1 e {MAX_DIM}. Vertical típico: 1080x1920.",
        )
    ratio, exact = _ratio_label(width, height)
    wanted = args.get("aspect_ratio")
    if wanted and wanted != ratio:
        raise E.CapcutError(
            E.RATIO_MISMATCH,
            f"aspect_ratio={wanted} não corresponde a {width}x{height} (seria {ratio}).",
            "Ajuste width/height ou remova aspect_ratio.",
        )

    profile.detect()  # falha cedo se a instalação não estiver pronta
    with bus.capture():
        draft_id, _script = get_or_create_draft(width=width, height=height)
    registry.create(draft_id, name, width, height, fps)
    if not exact:
        bus.add("RATIO_INEXACT",
                f"{width}x{height} será rotulado '{ratio}', que não é a proporção real. "
                "O CapCut só oferece 16:9, 4:3, 2.35:1, 2:1, 1.85:1, 9:16, 3:4 e 1:1.")
    obs.log("draft_created", draft_id=draft_id, name=name, w=width, h=height)
    return {
        "draft_id": draft_id,
        "name": name,
        "width": width,
        "height": height,
        "fps": fps,
        "ratio_label": ratio,
        "ratio_is_exact": exact,
        "state": "DRAFTING",
    }


def _ratio_label(w: int, h: int) -> Tuple[str, bool]:
    known = {(9, 16): "9:16", (16, 9): "16:9", (1, 1): "1:1", (3, 4): "3:4", (4, 3): "4:3"}
    from math import gcd
    g = gcd(w, h)
    key = (w // g, h // g)
    if key in known:
        return known[key], True
    return ("9:16" if h > w else "16:9" if w > h else "1:1"), False


# -------------------------------------------------------------- draft.save
def draft_save(args: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    draft_id = args.get("draft_id")
    if not draft_id:
        raise E.CapcutError(E.MISSING_REQUIRED_PARAM, "draft_id é obrigatório.",
                            "Use o draft_id devolvido por capcut.draft.create.")
    entry = registry.get(draft_id)                     # levanta DRAFT_NOT_FOUND
    inst = profile.detect()
    project_name = deployer.sanitize_project_name(
        args.get("project_name") or entry.get("name") or draft_id)

    script = _resolve_script(draft_id, entry, bus)
    segments = sum(len(t.segments) for t in script.tracks.values())
    if segments == 0 and not args.get("allow_empty", False):
        raise E.CapcutError(
            E.DRAFT_EMPTY,
            "O draft não tem nenhum segmento; salvá-lo produziria um projeto vazio.",
            "Adicione mídia antes de salvar, ou passe allow_empty=true se o objetivo "
            "for justamente testar o caminho de gravação.",
            draft_id=draft_id,
        )

    result = deployer.save(script, draft_id, project_name, inst,
                           overwrite=bool(args.get("overwrite", False)), bus=bus)
    registry.mark_saved(draft_id, result["project_path"])
    result["draft_id"] = draft_id
    result["segments"] = segments
    return result


def _resolve_script(draft_id: str, entry: Dict[str, Any], bus: obs.WarningBus):
    """Spec D4: se o processo reiniciou, reconstrói o draft pelo plano declarativo."""
    if draft_id in DRAFT_CACHE:
        return DRAFT_CACHE[draft_id]
    canvas = entry.get("canvas", {})
    with bus.capture():
        _new_id, script = get_or_create_draft(
            width=int(canvas.get("width", 1080)), height=int(canvas.get("height", 1920)))
    from .upstream import update_cache
    update_cache(draft_id, script)                     # re-liga ao id original
    steps = [s for s in entry.get("plan", []) if s.get("op") != "create"]
    if steps:
        raise E.CapcutError(
            E.OPERATION_NOT_SUPPORTED,
            f"O draft '{draft_id}' tem {len(steps)} passo(s) de mídia e o processo do "
            "servidor foi reiniciado; o replay desses passos entra na Phase 3.",
            "Recrie o draft e refaça as adições nesta sessão.",
            draft_id=draft_id, pending_steps=len(steps),
        )
    bus.add("DRAFT_REPLAYED",
            "O servidor havia reiniciado; o draft foi reconstruído pelo plano registrado.")
    return script


# --------------------------------------------------------------- registro
Handler = Callable[[Dict[str, Any], obs.WarningBus], Dict[str, Any]]

TOOLS: Dict[str, Dict[str, Any]] = {
    "capcut.system.doctor": {
        "handler": doctor,
        "title": "Diagnóstico do ambiente CapCut",
        "description": (
            "Verifica se o ambiente está pronto para gerar projetos do CapCut: versão do "
            "app instalado, diretório real de drafts no macOS, projeto de referência usado "
            "como esqueleto, presença do ffprobe, espaço em disco e projetos existentes. "
            "Chame isto primeiro quando algo falhar — o campo 'blocker' diz o que corrigir."
        ),
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "capcut.draft.create": {
        "handler": draft_create,
        "title": "Criar projeto do CapCut",
        "description": (
            "Cria um projeto (draft) novo e devolve o draft_id usado por todas as outras "
            "tools. A resolução é fixada aqui e não pode ser mudada depois. "
            "Nada é escrito em disco até capcut.draft.save. "
            "NÃO existe: reordenar clipes, editar um segmento já adicionado, renderizar "
            "vídeo, ou recarregar o CapCut automaticamente."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 120,
                         "description": "Nome do projeto. Vira o nome da PASTA e o nome "
                                        "exibido na lista do CapCut."},
                "width": {"type": "integer", "minimum": 1, "maximum": MAX_DIM,
                          "default": 1080, "description": "Largura em pixels."},
                "height": {"type": "integer", "minimum": 1, "maximum": MAX_DIM,
                           "default": 1920, "description": "Altura em pixels."},
                "fps": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30,
                        "description": "Quadros por segundo. Só 30 foi verificado."},
                "aspect_ratio": {"type": "string",
                                 "enum": ["9:16", "16:9", "1:1", "3:4", "4:3"],
                                 "description": "Opcional, só para validação cruzada "
                                                "contra width/height."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "capcut.draft.save": {
        "handler": draft_save,
        "title": "Salvar projeto no CapCut",
        "description": (
            "Grava o draft como projeto no diretório real do CapCut no macOS, no formato "
            "multi-timeline que a versão instalada exige, com os metadados reescritos. "
            "Devolve o caminho e um manifest do que foi escrito. "
            "Depois de salvar, o CapCut precisa reler o disco: volte à página inicial do "
            "app (ou reinicie-o) para o projeto aparecer. Um projeto aberto no editor "
            "sobrescreve o disco com o estado que tem em memória, então salve com o "
            "projeto fechado."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string",
                             "description": "O draft_id devolvido por capcut.draft.create."},
                "project_name": {"type": "string", "minLength": 1, "maxLength": 120,
                                 "description": "Sobrescreve o nome definido na criação."},
                "overwrite": {"type": "boolean", "default": False,
                              "description": "Necessário para substituir um projeto "
                                             "existente com o mesmo nome."},
                "allow_empty": {"type": "boolean", "default": False,
                                "description": "Permite salvar um draft sem nenhum "
                                               "segmento (só para testar o caminho)."},
            },
            "required": ["draft_id"],
            "additionalProperties": False,
        },
    },
}


def tool_list() -> list:
    return [
        {"name": name, "title": spec["title"], "description": spec["description"],
         "inputSchema": spec["schema"]}
        for name, spec in TOOLS.items()
    ]
