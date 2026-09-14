"""Gravação do projeto no diretório do CapCut, com as correções da Phase 1.

Correções aplicadas sobre o comportamento do L0:

 1. NOME DA PASTA. O L0 nomeia a pasta de saída com o `draft_id` e grava nos materiais
    caminhos ABSOLUTOS apontando para ela. Renomear depois quebra toda a mídia
    (verificado: 3/3 assets ausentes). Solução: re-chavear o DRAFT_CACHE para o nome
    final ANTES de salvar, para a pasta nascer com o nome definitivo.

 2. SUCESSO VAZIO. `save_draft_impl` de um draft ausente do cache retorna
    `success: true` + `draft_url: null` e não escreve nada. Aqui isso é DRAFT_NOT_FOUND.

 3. new_version. O L0 grava 110.0.0 (de draft_content_template.json). A instalação real
    usa o valor lido do projeto de referência (185.0.0 na 9.4.1).

 4. draft_meta_info.json. O L0 copia do template sem reescrever, deixando o nome, os
    caminhos do autor original e o MESMO UUID em todo projeto. Aqui é reescrito.

 5. project.json. O L0 escreve `id == main_timeline_id` e nome "时间线01"; o real tem
    ids distintos e "Timeline 01".

 6. root_meta_info.json NÃO é tocado — o CapCut mantém esse índice sozinho (verificado).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from typing import Any, Dict, List

from . import errors as E
from . import obs
from .profile import Installation
from .upstream import _save_draft_impl, inject_profile, update_cache

MIN_FREE_BYTES = 2 * 1024**3  # 2 GiB (WI-0.11)
_SAFE_NAME = re.compile(r"^[^/\\:]{1,120}$")


def sanitize_project_name(name: str) -> str:
    name = (name or "").strip()
    if not name or not _SAFE_NAME.match(name) or name in (".", "..") or ".." in name:
        raise E.CapcutError(
            E.MISSING_REQUIRED_PARAM,
            f"Nome de projeto inválido: {name!r}",
            "Use um nome simples, sem barras, dois-pontos ou '..'.",
        )
    return name


def _free_bytes(path: str) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def _rewrite_content(paths: List[str], new_version: str) -> None:
    for p in paths:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                content = json.load(f)
        except Exception:
            continue
        content["new_version"] = new_version
        with open(p, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False)


def _content_copies(project_dir: str) -> List[str]:
    out = [os.path.join(project_dir, n)
           for n in ("draft_info.json", "draft_info.json.bak", "template-2.tmp")]
    tl = os.path.join(project_dir, "Timelines")
    if os.path.isdir(tl):
        for sub in os.listdir(tl):
            d = os.path.join(tl, sub)
            if os.path.isdir(d):
                out += [os.path.join(d, n) for n in
                        ("draft_info.json", "draft_info.json.bak",
                         "template.tmp", "template-2.tmp")]
    return out


def save(script: Any, draft_id: str, project_name: str, inst: Installation,
         overwrite: bool = False, bus: obs.WarningBus | None = None) -> Dict[str, Any]:
    project_name = sanitize_project_name(project_name)
    target = os.path.join(inst.projects_dir, project_name)
    bus = bus or obs.WarningBus()

    # --- pré-condições -----------------------------------------------------
    if os.path.exists(os.path.join(target, ".locked")):
        raise E.CapcutError(
            E.PROJECT_LOCKED,
            f"O projeto '{project_name}' está aberto no CapCut.",
            "Feche o projeto no CapCut (volte à página inicial) e tente de novo.",
            path=target,
        )
    if os.path.exists(target) and not overwrite:
        raise E.CapcutError(
            E.TARGET_EXISTS,
            f"Já existe um projeto chamado '{project_name}'.",
            "Use outro project_name, ou passe overwrite=true para sobrescrever.",
            path=target,
        )
    free = _free_bytes(inst.projects_dir)
    if free < MIN_FREE_BYTES:
        raise E.CapcutError(
            E.DISK_FULL,
            f"Espaço em disco insuficiente: {free / 1024**3:.1f} GiB livres.",
            f"Libere espaço até ao menos {MIN_FREE_BYTES / 1024**3:.0f} GiB. "
            "O save copia todos os assets para dentro do projeto.",
            free_bytes=free,
        )
    if not shutil.which("ffprobe"):
        raise E.CapcutError(
            E.FFPROBE_UNAVAILABLE,
            "ffprobe não encontrado no PATH.",
            "Instale o FFmpeg (brew install ffmpeg). É obrigatório para resolver "
            "duração e dimensão das mídias.",
        )

    started = time.time()

    # --- perfil híbrido: SEM isto o L0 resolve get_draft_profile() pelo default
    # (capcut_legacy) e gera um projeto sem Timelines/, que o CapCut 9.x recusa abrir.
    inject_profile(inst.profile())

    # --- correção 1: a pasta nasce com o nome final ------------------------
    update_cache(project_name, script)

    with bus.capture():
        result = _save_draft_impl(project_name, draft_folder=inst.projects_dir,
                                  auto_deploy=False)

    # --- correção 2: sucesso vazio é erro ---------------------------------
    written = isinstance(result, dict) and result.get("draft_url")
    if not written or not os.path.isdir(target):
        raise E.CapcutError(
            E.INTERNAL_ERROR,
            "O upstream reportou sucesso mas nada foi escrito em disco.",
            "Verifique o log estruturado; o draft pode ter saído do cache do processo.",
            upstream_result=result, target=target,
        )

    content_path = os.path.join(target, "draft_info.json")
    with open(content_path, encoding="utf-8") as f:
        content = json.load(f)

    # --- correção 3: new_version da instalação ----------------------------
    _rewrite_content(_content_copies(target), inst.new_version)

    # --- correção 4: draft_meta_info.json reescrito -----------------------
    meta_path = os.path.join(target, "draft_meta_info.json")
    now_us = int(time.time() * 1_000_000)
    project_uuid = str(uuid.uuid4()).upper()
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}
    meta.update({
        "draft_name": project_name,
        "draft_fold_path": target,
        "draft_root_path": inst.projects_dir,
        "draft_id": project_uuid,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_duration": content.get("duration", 0),
    })
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    # --- correção 5: project.json como o real ------------------------------
    tl_dir = os.path.join(target, "Timelines")
    proj_path = os.path.join(tl_dir, "project.json")
    if os.path.isfile(proj_path):
        with open(proj_path, encoding="utf-8") as f:
            pj = json.load(f)
        timeline_id = pj.get("main_timeline_id") or pj.get("id")
        pj["id"] = str(uuid.uuid4()).upper()
        pj["main_timeline_id"] = timeline_id
        for t in pj.get("timelines", []):
            t["name"] = "Timeline 01"
        pj.setdefault("config", {}).update(
            {"hdr_vivid": False, "mixed_track_mode_on": False})
        for name in ("project.json", "project.json.bak"):
            with open(os.path.join(tl_dir, name), "w", encoding="utf-8") as f:
                json.dump(pj, f, ensure_ascii=False, separators=(",", ":"))

    # --- verificação pós-escrita (spec: WI-6.12 antecipado) ----------------
    manifest = _verify(target, content, bus)
    elapsed = time.time() - started
    obs.log("draft_saved", draft_id=draft_id, project=project_name, path=target,
            elapsed_s=round(elapsed, 2), duration_us=content.get("duration"),
            warnings=len(bus.warnings))

    return {
        "project_path": target,
        "project_name": project_name,
        "content_file": "draft_info.json",
        "duration_us": content.get("duration", 0),
        "canvas": content.get("canvas_config"),
        "new_version": inst.new_version,
        "project_uuid": project_uuid,
        "elapsed_s": round(elapsed, 2),
        "manifest": manifest,
        "next_step": "No CapCut, volte à página inicial (ou reinicie o app) para que ele "
                     "releia o disco; o projeto aparecerá na lista de Projetos.",
    }


def _verify(target: str, content: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
    """Confere invariantes e devolve o manifest (spec: O5)."""
    tl = os.path.join(target, "Timelines")
    subs = [s for s in os.listdir(tl) if os.path.isdir(os.path.join(tl, s))] \
        if os.path.isdir(tl) else []
    timeline_ok = False
    if subs:
        a = os.path.join(target, "draft_info.json")
        b = os.path.join(tl, subs[0], "draft_info.json")
        if os.path.isfile(b):
            with open(a, encoding="utf-8") as f1, open(b, encoding="utf-8") as f2:
                timeline_ok = f1.read() == f2.read()
    if not subs:
        bus.add("NO_TIMELINES_DIR",
                "O projeto foi gravado sem o diretório Timelines/. O CapCut 9.x lista "
                "mas não abre projetos nesse formato.")
    elif not timeline_ok:
        bus.add("TIMELINE_CONTENT_MISMATCH",
                "O conteúdo da raiz e o do Timelines/<id>/ divergem.")

    assets: List[Dict[str, Any]] = []
    missing: List[str] = []
    mats = content.get("materials", {})
    for kind in ("videos", "audios"):
        for m in mats.get(kind, []) or []:
            p = m.get("path") or ""
            exists = bool(p) and os.path.isfile(p) and os.path.getsize(p) > 0
            assets.append({"kind": kind, "path": p, "ok": exists,
                           "bytes": os.path.getsize(p) if exists else 0})
            if not exists:
                missing.append(p or "<sem path>")
    if missing:
        raise E.CapcutError(
            E.ASSET_FETCH_FAILED,
            f"{len(missing)} asset(s) não estão disponíveis em disco após o save.",
            "Confirme que os arquivos de origem existem e são legíveis.",
            missing=missing,
        )

    segments = sum(len(t.get("segments", [])) for t in content.get("tracks", []))
    return {
        "timeline_dir": subs[0] if subs else None,
        "timeline_content_matches_root": timeline_ok,
        "segments": segments,
        "tracks": len(content.get("tracks", [])),
        "assets": assets,
        "files": sorted(
            os.path.relpath(os.path.join(dp, f), target)
            for dp, _, fs in os.walk(target) for f in fs
        )[:60],
    }
