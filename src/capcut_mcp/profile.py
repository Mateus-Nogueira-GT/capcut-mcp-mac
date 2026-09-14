"""Descoberta da instalação do CapCut e derivação do perfil de draft.

Baseado nos achados empíricos das Phases 0 e 1:

  * O diretório de drafts no macOS é `~/Movies/CapCut/User Data/Projects/com.lveditor.draft`.
    O caminho que o upstream procura (`~/Library/Containers/com.lemon.lvpro/...JianyingPro...`)
    é de OUTRO aplicativo (Jianying Pro chinês) e não existe.

  * O CapCut 9.4.1 exige a estrutura `Timelines/<UUID>/draft_info.json`. O perfil
    `capcut_legacy` do upstream (só o draft_info.json da raiz) gera um projeto que o app
    LISTA mas SE RECUSA A ABRIR — verificado. O perfil `jianying_pro_10` tem a estrutura
    certa mas grava `draft_content.json`. O correto é o híbrido: estrutura do
    jianying_pro_10 + `content_file="draft_info.json"`.

  * `platform` e `new_version` são específicos da instalação e são lidos de um projeto
    real. Os valores hardcoded do upstream são de outra máquina (app_version 6.5.0).

  * O `root_meta_info.json` NÃO deve ser escrito: o CapCut mantém esse índice sozinho,
    varrendo o diretório — verificado com um projeto deliberadamente não registrado.
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import errors as E
from .upstream import DraftProfile

APP_BUNDLE = "/Applications/CapCut.app"
CACHE_DIR = os.path.expanduser("~/Library/Application Support/capcut-mcp")
TEMPLATE_CACHE = os.path.join(CACHE_DIR, "template", "capcut_detected")

# Ordem de precedência (spec: File Handling). O container do app é symlink para ~/Movies.
CANDIDATES = [
    "~/Movies/CapCut/User Data/Projects/com.lveditor.draft",
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
    "~/Library/Containers/com.lemon.lvpro/Data/Documents/JianyingPro/User Data/"
    "Projects/com.lveditor.draft",
]


@dataclass
class Installation:
    projects_dir: str
    app_version: Optional[str]
    platform: Dict[str, object]
    new_version: str
    reference_project: str
    template_dir: str

    def profile(self) -> DraftProfile:
        return DraftProfile(
            name="capcut_detected",
            template_dir=self.template_dir,
            content_file="draft_info.json",          # <<< a diferença vs jianying_pro_10
            content_mirrors=("draft_info.json.bak", "template-2.tmp"),
            timeline_content_file="template.tmp",
            is_capcut_env=True,
            platform=self.platform,
        )


def find_projects_dir() -> str:
    env = os.environ.get("CAPCUT_PROJECTS_DIR")
    if env:
        p = os.path.expanduser(env)
        if os.path.isdir(p):
            return p
        raise E.CapcutError(
            E.TARGET_DIR_NOT_FOUND,
            f"CAPCUT_PROJECTS_DIR aponta para um diretório inexistente: {p}",
            "Corrija a variável de ambiente ou remova-a para usar a detecção automática.",
        )
    for c in CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isdir(p):
            return p
    raise E.CapcutError(
        E.TARGET_DIR_NOT_FOUND,
        "Diretório de projetos do CapCut não encontrado.",
        "Instale o CapCut e abra-o uma vez, ou defina CAPCUT_PROJECTS_DIR.",
        candidates=[os.path.expanduser(c) for c in CANDIDATES],
    )


def installed_app_version() -> Optional[str]:
    plist = os.path.join(APP_BUNDLE, "Contents", "Info.plist")
    try:
        with open(plist, "rb") as f:
            return plistlib.load(f).get("CFBundleShortVersionString")
    except Exception:
        return None


def _content_file_of(project_dir: str) -> Optional[str]:
    for name in ("draft_info.json", "draft_content.json"):
        p = os.path.join(project_dir, name)
        if os.path.isfile(p):
            return p
    return None


def list_projects(projects_dir: str) -> List[Dict[str, object]]:
    out = []
    for item in sorted(os.listdir(projects_dir)):
        d = os.path.join(projects_dir, item)
        if not os.path.isdir(d) or item.startswith("."):
            continue
        content = _content_file_of(d)
        tl = os.path.join(d, "Timelines")
        out.append({
            "name": item,
            "path": d,
            "content_file": os.path.basename(content) if content else None,
            "has_timelines": os.path.isdir(tl),
            "is_locked": os.path.exists(os.path.join(d, ".locked")),
        })
    return out


def find_reference_project(projects_dir: str) -> str:
    """Um projeto real da instalação, com a estrutura multi-timeline completa.

    Serve de esqueleto: é a única fonte confiável de `platform`, `new_version` e dos
    arquivos auxiliares que a versão instalada espera.
    """
    best = None
    for p in list_projects(projects_dir):
        if not p["has_timelines"] or p["is_locked"]:
            continue
        tl = os.path.join(str(p["path"]), "Timelines")
        subs = [s for s in os.listdir(tl) if os.path.isdir(os.path.join(tl, s))]
        if len(subs) != 1:
            continue
        if not os.path.isfile(os.path.join(tl, subs[0], "draft_info.json")):
            continue
        # prefere o mais antigo: menor chance de ser um projeto gerado por nós
        mtime = os.path.getmtime(str(p["path"]))
        if best is None or mtime < best[0]:
            best = (mtime, str(p["path"]))
    if best is None:
        raise E.CapcutError(
            E.NO_REFERENCE_PROJECT,
            "Nenhum projeto de referência com estrutura Timelines/ foi encontrado.",
            "Abra o CapCut, crie um projeto qualquer à mão, volte à página inicial "
            "e tente novamente. O esqueleto real da sua versão é necessário.",
            projects_dir=projects_dir,
        )
    return best[1]


def build_template(reference_project: str, force: bool = False) -> str:
    """Deriva o template a partir do projeto de referência (cópia, sem alterar o original)."""
    if os.path.isdir(TEMPLATE_CACHE) and not force:
        return TEMPLATE_CACHE
    os.makedirs(os.path.dirname(TEMPLATE_CACHE), exist_ok=True)
    if os.path.isdir(TEMPLATE_CACHE):
        shutil.rmtree(TEMPLATE_CACHE)
    shutil.copytree(reference_project, TEMPLATE_CACHE)
    # assets do projeto de referência não pertencem ao template
    assets = os.path.join(TEMPLATE_CACHE, "assets")
    if os.path.isdir(assets):
        shutil.rmtree(assets)
    for junk in ("draft_cover.jpg", ".locked"):
        p = os.path.join(TEMPLATE_CACHE, junk)
        if os.path.exists(p):
            os.remove(p)
    return TEMPLATE_CACHE


def detect(force_template: bool = False) -> Installation:
    projects_dir = find_projects_dir()
    reference = find_reference_project(projects_dir)
    with open(os.path.join(reference, "draft_info.json"), encoding="utf-8") as f:
        content = json.load(f)
    platform = content.get("platform") or {}
    new_version = content.get("new_version") or ""
    if not platform or not new_version:
        raise E.CapcutError(
            E.TEMPLATE_MISSING,
            f"O projeto de referência não tem platform/new_version: {reference}",
            "Crie outro projeto à mão no CapCut e tente novamente.",
        )
    return Installation(
        projects_dir=projects_dir,
        app_version=installed_app_version(),
        platform=platform,
        new_version=new_version,
        reference_project=reference,
        template_dir=build_template(reference, force=force_template),
    )
