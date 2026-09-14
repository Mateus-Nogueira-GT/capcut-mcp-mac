"""Único ponto de import do L0 (spec: A2, C2, C3).

O L0 (VectCutAPI) é um submodule FIXADO em b83be74 e NUNCA é modificado.
Este módulo:
  1. adiciona o L0 ao sys.path;
  2. importa apenas as funções de lógica que o L1 usa;
  3. GUARDA contra os módulos proibidos (não importam no macOS ou são inúteis);
  4. injeta o perfil de draft, porque `save_draft_background` chama
     `get_draft_profile()` sem argumento.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
L0_DIR = os.path.join(REPO_ROOT, "vendor", "VectCutAPI")

# Módulos do L0 que NÃO podem ser importados:
#  - desktop_companion: executa ctypes.windll no import -> AttributeError no macOS
#  - capcut_server / web_preview: importam desktop_companion
#  - jianying_controller / jianying_ui_inspector: código morto, dependências ausentes
FORBIDDEN = (
    "capcut_server",
    "web_preview",
    "desktop_companion",
    "pyJianYingDraft.jianying_controller",
    "pyJianYingDraft.jianying_ui_inspector",
)

if not os.path.isdir(L0_DIR):
    raise RuntimeError(
        f"Submodule do upstream ausente em {L0_DIR}. "
        "Rode: git submodule update --init --recursive"
    )

if L0_DIR not in sys.path:
    sys.path.insert(0, L0_DIR)

# NÃO fazemos chdir: o L0 resolve template_dir relativo ao próprio diretório e
# aceita caminho absoluto, então chdir seria efeito colateral desnecessário.

import draft_profiles  # noqa: E402
import save_draft_impl  # noqa: E402
import pyJianYingDraft.script_file as _script_file  # noqa: E402
from draft_cache import DRAFT_CACHE, update_cache  # noqa: E402,F401
from draft_profiles import DraftProfile  # noqa: E402,F401
from create_draft import get_or_create_draft  # noqa: E402,F401
from save_draft_impl import save_draft_impl as _save_draft_impl  # noqa: E402,F401
from settings.local import IS_CAPCUT_ENV  # noqa: E402,F401


def assert_no_forbidden_imports() -> None:
    """Falha se algum módulo proibido entrou em sys.modules (C3)."""
    leaked = [m for m in FORBIDDEN if m in sys.modules]
    if leaked:
        raise RuntimeError(f"Módulo proibido do upstream foi importado: {leaked}")


assert_no_forbidden_imports()


def inject_profile(profile: DraftProfile) -> None:
    """Injeta o perfil em todos os pontos onde o L0 o resolve sem argumento."""
    getter = lambda name=None: profile  # noqa: E731
    draft_profiles.get_draft_profile = getter
    save_draft_impl.get_draft_profile = getter
    _script_file.get_draft_profile = getter


def upstream_commit() -> str:
    """Commit fixado do L0, para o doctor e o log."""
    head = os.path.join(L0_DIR, ".git")
    try:
        if os.path.isfile(head):  # submodule -> arquivo .git com gitdir:
            with open(head) as f:
                gitdir = f.read().strip().split("gitdir:")[1].strip()
            gitdir = os.path.normpath(os.path.join(L0_DIR, gitdir))
        else:
            gitdir = head
        with open(os.path.join(gitdir, "HEAD")) as f:
            ref = f.read().strip()
        if ref.startswith("ref:"):
            with open(os.path.join(gitdir, ref.split()[1])) as f:
                return f.read().strip()[:12]
        return ref[:12]
    except Exception:
        return "unknown"
