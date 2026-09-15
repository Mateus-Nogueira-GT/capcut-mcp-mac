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
    from . import asr as _asr
    out["whisper_cli"] = shutil.which(_asr.BIN)
    out["asr_models_installed"] = _asr.installed_models()
    out["asr_models_dir"] = _asr.MODELS_DIR
    out["asr_default_model"] = _asr.DEFAULT_MODEL
    if not out["whisper_cli"]:
        bus.add("ASR_UNAVAILABLE",
                "whisper.cpp não está instalado; a transcrição vai falhar.",
                fix="brew install whisper-cpp")
    elif _asr.DEFAULT_MODEL not in out["asr_models_installed"]:
        spec = _asr.MODELS[_asr.DEFAULT_MODEL]
        bus.add("ASR_MODEL_MISSING",
                f"O modelo default '{_asr.DEFAULT_MODEL}' ({spec['mb']} MB) não está "
                "baixado.",
                fix=f"curl -L -o '{_asr.MODELS_DIR}/{spec['file']}' "
                    + _asr.MODEL_URL.format(file=spec["file"]))
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

    # --- validação pré-save (spec: Validation). Erro bloqueia, salvo com force=true.
    from . import validator as V
    report = V.validate(script, entry)
    erros = [i for i in report["issues"] if i["severity"] == V.ERROR]
    if args.get("allow_empty"):
        # quem pediu allow_empty já sabe que o draft está vazio
        erros = [i for i in erros if i["code"] != "V_EMPTY_DRAFT"]
    if erros and not args.get("force", False):
        raise E.CapcutError(
            E.VALIDATION_FAILED,
            f"{len(erros)} problema(s) impedem o save: "
            + "; ".join(i["message"] for i in erros[:3]),
            "Corrija os itens listados, ou passe force=true para salvar mesmo assim. "
            "Use capcut.draft.validate para ver o relatório completo.",
            issues=erros,
        )
    for issue in report["issues"]:
        if issue["severity"] != V.ERROR:
            bus.add(issue["code"], issue["message"], **issue.get("context", {}))

    result = deployer.save(script, draft_id, project_name, inst,
                           overwrite=bool(args.get("overwrite", False)), bus=bus)
    result["validation"] = {"counts": report["counts"], "forced": bool(erros)}
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

    from . import handlers_media as HM
    plan = entry.get("plan", [])
    steps = [s for s in plan if s.get("op") != "create"]
    if steps:
        # o replay usa os mesmos appliers, então o resultado é idêntico ao original;
        # o plano já está registrado, por isso não re-registramos nada aqui.
        HM.replay(script, draft_id, plan, bus)
    bus.add("DRAFT_REPLAYED",
            f"O servidor havia reiniciado; o draft foi reconstruído pelo plano "
            f"registrado ({len(steps)} passo(s) de mídia).")
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
            "Valida o draft e grava como projeto no diretório real do CapCut no macOS, "
            "no formato multi-timeline que a versão instalada exige, com os metadados "
            "reescritos. Recusa se a validação encontrar erro — passe force=true para "
            "salvar mesmo assim. "
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
                "force": {"type": "boolean", "default": False,
                          "description": "Salva mesmo com erros de validação. Use só "
                                         "depois de ver o relatório e decidir."},
            },
            "required": ["draft_id"],
            "additionalProperties": False,
        },
    },
}


# ==========================================================================
# Superfície MCP exposta.
#
# O escopo pedido é: cortar, legendar e colocar textos em momentos
# pré-determinados. Só essas tools são oferecidas ao agente. As demais continuam
# implementadas e testadas — apenas não entram no `tools/list`, porque superfície
# a mais só dá ao agente mais formas de errar fora do escopo.
#
# Para reativar todas: CAPCUT_ENABLE_ALL_TOOLS=1 no ambiente.
# ==========================================================================
ENABLED_TOOLS = (
    "capcut.system.doctor",
    "capcut.media.probe",
    "capcut.media.transcribe",
    "capcut.draft.create",
    "capcut.video.cut",
    "capcut.subtitle.add",
    "capcut.subtitle.from_transcript",
    "capcut.text.add",
    "capcut.text.add_many",
    "capcut.draft.validate",
    "capcut.draft.save",
)


def enabled() -> Dict[str, Any]:
    if os.environ.get("CAPCUT_ENABLE_ALL_TOOLS") == "1":
        return TOOLS
    return {name: TOOLS[name] for name in ENABLED_TOOLS if name in TOOLS}


def tool_list() -> list:
    return [
        {"name": name, "title": spec["title"], "description": spec["description"],
         "inputSchema": spec["schema"]}
        for name, spec in enabled().items()
    ]


# ==========================================================================
# Phase 3 — edição da timeline. As tools de mídia compartilham o mesmo ciclo:
# resolver o script (com replay se o processo reiniciou) -> aplicar -> registrar
# o passo no plano declarativo.
# ==========================================================================
from . import catalog as _catalog              # noqa: E402
from . import handlers_draft as _HD            # noqa: E402
from . import handlers_media as _HM            # noqa: E402


def _media_handler(op: str) -> Handler:
    def handler(args: Dict[str, Any], bus: obs.WarningBus) -> Dict[str, Any]:
        draft_id = args["draft_id"]
        entry = registry.get(draft_id)
        script = _resolve_script(draft_id, entry, bus)
        info = _HM.APPLIERS[op](script, draft_id, args, bus)
        _HM.record(draft_id, op, args, info)
        return {"draft_id": draft_id, **info}
    return handler


_TIME_NOTE = ("Entrada em segundos; a saída traz também µs, a unidade interna do "
              "CapCut. Omitir timeline_start ANEXA ao fim da track — a forma segura de "
              "encadear clipes.")
_TRANSFORM_NOTE = ("transform_x/transform_y são normalizados em 'meia tela': 0 é o "
                   "centro, 1.0 desloca meia largura/altura. Y POSITIVO move para CIMA.")

_COMMON_VISUAL = {
    "scale_x": {"type": "number", "default": 1.0, "description": "Escala horizontal."},
    "scale_y": {"type": "number", "default": 1.0, "description": "Escala vertical."},
    "transform_x": {"type": "number", "default": 0.0, "description": _TRANSFORM_NOTE},
    "transform_y": {"type": "number", "default": 0.0, "description": _TRANSFORM_NOTE},
    "layer": {"type": "integer", "default": 0,
              "description": "Camada relativa entre tracks do mesmo tipo; maior fica "
                             "na frente. Use para picture-in-picture."},
    "mask": {"type": "string",
             "description": "Nome exato da máscara. As 9 opções: Split, Filmstrip, "
                            "Circle, Rectangle, Heart, Star, Mirror, Linear, Love."},
    "transition": {"type": "string",
                   "description": "Nome exato do catálogo 'transition' (ex.: Mix). "
                                  "ATENCAO: verificado no CapCut 9.4.1 que a transicao "
                                  "e gravada no projeto mas NAO e aplicada pelo app — "
                                  "nao ha icone na juncao nem mistura entre os clipes. "
                                  "Use apenas se voce for conferir manualmente."},
    "transition_duration": {"type": "number", "default": 0.5,
                            "description": "Duração da transição em segundos."},
}

TOOLS.update({
    "capcut.media.probe": {
        "handler": _HD.media_probe,
        "title": "Inspecionar mídia",
        "description": (
            "Lê duração, dimensões, codec e container reais de arquivos ou URLs, via "
            "ffprobe, em lote e com cache de sessão. CHAME ISTO ANTES de montar a "
            "timeline: sem duração conhecida não é possível calcular posições, e "
            "segmentos podem colidir. Também informa se a extensão do arquivo "
            "corresponde ao conteúdo real."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "sources": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                            "description": "Caminhos absolutos ou URLs http(s)."},
                "refresh": {"type": "boolean", "default": False,
                            "description": "Ignora o cache da sessão."},
            },
            "required": ["sources"], "additionalProperties": False,
        },
    },
    "capcut.catalog.list": {
        "handler": _HD.catalog_list,
        "title": "Listar catálogos do CapCut",
        "description": (
            "Lista os nomes válidos de transições, máscaras, fontes, animações, efeitos, "
            "filtros e propriedades de keyframe, direto dos metadados do CapCut. "
            "Os nomes exigem correspondência EXATA e case-sensitive: 'fade_in' não "
            "existe, 'Fade_In' sim. Use 'search' para filtrar — alguns catálogos têm "
            "centenas de itens. O campo 'applicable' indica se esta versão consegue "
            "aplicar o recurso."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": _catalog.KINDS,
                         "description": "Qual catálogo listar."},
                "search": {"type": "string",
                           "description": "Filtro por substring, case-insensitive."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "required": ["kind"], "additionalProperties": False,
        },
    },
    "capcut.video.add": {
        "handler": _media_handler("video"),
        "title": "Adicionar vídeo",
        "description": (
            "Acrescenta um clipe de vídeo à timeline, com corte na inserção, "
            "velocidade, volume, escala, posição, máscara, blur de fundo e transição. "
            f"{_TIME_NOTE} O corte é feito NA INSERÇÃO (source_start/source_end); não "
            "existe edição de um segmento já adicionado — para mudar, use "
            "capcut.draft.rebuild. Colisão na mesma track é erro; para sobrepor "
            "visualmente use outra track com 'layer'."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "source": {"type": "string",
                           "description": "Caminho absoluto ou URL http(s) do vídeo."},
                "track": {"type": "string", "default": _HM.TRACK_VIDEO,
                          "description": "Track de destino. Clipes na mesma track ficam "
                                         "em sequência; tracks distintas se sobrepõem."},
                "timeline_start": {"type": "number", "minimum": 0,
                                   "description": "Posição na timeline, em segundos. "
                                                  "Omitir anexa ao fim da track."},
                "source_start": {"type": "number", "minimum": 0, "default": 0,
                                 "description": "Início do corte DENTRO da mídia."},
                "source_end": {"type": "number",
                               "description": "Fim do corte dentro da mídia. Omitir usa "
                                              "até o fim do arquivo."},
                "duration": {"type": "number",
                             "description": "Alternativa a source_end: quantos segundos "
                                            "a partir de source_start."},
                "speed": {"type": "number", "default": 1.0,
                          "description": "1.0 = original. Afeta a duração na timeline."},
                "volume": {"type": "number", "minimum": 0, "maximum": 2, "default": 1.0,
                           "description": "1.0 = original, 0.0 = mudo."},
                "background_blur": {"type": "integer", "enum": [1, 2, 3, 4],
                                    "description": "Blur do fundo: 1 leve a 4 máximo."},
                **_COMMON_VISUAL,
            },
            "required": ["draft_id", "source"], "additionalProperties": False,
        },
    },
    "capcut.image.add": {
        "handler": _media_handler("image"),
        "title": "Adicionar imagem",
        "description": (
            "Acrescenta uma imagem à timeline como segmento de vídeo, com duração "
            "própria, escala, posição, máscara, transição e animações de entrada, "
            f"saída e combo. {_TIME_NOTE} Para picture-in-picture, use uma track "
            "diferente da do vídeo principal e ajuste scale/transform."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "source": {"type": "string",
                           "description": "Caminho absoluto ou URL http(s) da imagem."},
                "track": {"type": "string", "default": _HM.TRACK_VIDEO},
                "timeline_start": {"type": "number", "minimum": 0,
                                   "description": "Omitir anexa ao fim da track."},
                "duration": {"type": "number", "default": 3.0,
                             "description": "Quanto tempo a imagem fica na tela."},
                "intro_animation": {"type": "string",
                                    "description": "Nome do catálogo 'animation_intro'."},
                "outro_animation": {"type": "string",
                                    "description": "Nome do catálogo 'animation_outro'."},
                "combo_animation": {"type": "string",
                                    "description": "Nome do catálogo 'animation_combo'."},
                **_COMMON_VISUAL,
            },
            "required": ["draft_id", "source"], "additionalProperties": False,
        },
    },
    "capcut.audio.add": {
        "handler": _media_handler("audio"),
        "title": "Adicionar áudio",
        "description": (
            "Acrescenta áudio à timeline. Use role='music' para trilha de fundo (volume "
            "default 0.25, track 'audio_main') ou role='voice' para narração (volume "
            f"1.0, track própria). {_TIME_NOTE} NÃO existe fade in/out nesta versão: o "
            "upstream não expõe o parâmetro, e pedi-lo devolve um aviso."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "source": {"type": "string",
                           "description": "Caminho absoluto ou URL http(s) do áudio."},
                "role": {"type": "string", "enum": ["music", "voice", "sfx"],
                         "default": "music",
                         "description": "Define track e volume default."},
                "track": {"type": "string",
                          "description": "Sobrescreve a track derivada de 'role'."},
                "timeline_start": {"type": "number", "minimum": 0,
                                   "description": "Omitir anexa ao fim da track."},
                "source_start": {"type": "number", "minimum": 0, "default": 0},
                "source_end": {"type": "number"},
                "duration": {"type": "number"},
                "speed": {"type": "number", "default": 1.0},
                "volume": {"type": "number", "minimum": 0, "maximum": 2,
                           "description": "Default 0.25 para music, 1.0 para voice/sfx."},
            },
            "required": ["draft_id", "source"], "additionalProperties": False,
        },
    },
    "capcut.text.add": {
        "handler": _media_handler("text"),
        "title": "Adicionar texto",
        "description": (
            "Acrescenta um texto à timeline, com fonte, cor, borda, fundo, sombra, "
            "alinhamento, espaçamento, animações de entrada/saída e estilos por faixa "
            "de caracteres. ATENÇÃO ao tamanho: font_size está na escala interna do "
            f"CapCut, aproximadamente 3–20, e {_HM.FONT_SIZE_DEFAULT} é o tamanho "
            "padrão do app — não são pontos nem pixels. "
            f"{_TIME_NOTE} {_TRANSFORM_NOTE} Para vários textos de uma vez, use "
            "capcut.text.add_many. Não existe edição de um texto já adicionado: para "
            "corrigir, crie o draft de novo."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "text": {"type": "string", "minLength": 1,
                         "description": "Conteúdo. Aceita acentuação e quebras de linha."},
                "track": {"type": "string", "default": _HM.TRACK_TEXT},
                "timeline_start": {"type": "number", "minimum": 0,
                                   "description": "Omitir anexa ao fim da track."},
                "duration": {"type": "number", "default": 3.0},
                "font": {"type": "string",
                         "description": "Nome exato de uma das 335 fontes do CapCut. "
                                        "Omitir usa a fonte padrão do app, que "
                                        "renderiza acentuação portuguesa corretamente "
                                        "— é a escolha recomendada. Nome inválido "
                                        "devolve erro com sugestões parecidas."},
                "font_size": {"type": "number", "minimum": 1, "maximum": 100,
                              "default": _HM.FONT_SIZE_DEFAULT,
                              "description": "Escala interna do CapCut (~3–20), não pt."},
                "font_color": {"type": "string", "default": "#FFFFFF",
                               "description": "Hex #RGB ou #RRGGBB."},
                "transform_x": {"type": "number", "default": 0.0,
                                "description": _TRANSFORM_NOTE},
                "transform_y": {"type": "number", "default": -0.8,
                                "description": "Default -0.8 = rodapé. " + _TRANSFORM_NOTE},
                "bold": {"type": "boolean", "default": False},
                "italic": {"type": "boolean", "default": False},
                "underline": {"type": "boolean", "default": False},
                "align": {"type": "integer", "enum": [0, 1, 2], "default": 1,
                          "description": "0 esquerda, 1 centro, 2 direita."},
                "line_spacing": {"type": "number", "default": 0.25},
                "letter_spacing": {"type": "number", "default": 0.0},
                "border_color": {"type": "string"},
                "border_width": {"type": "number",
                                 "description": "> 0 liga a borda. Melhora legibilidade "
                                                "sobre vídeo."},
                "background_color": {"type": "string"},
                "background_alpha": {"type": "number", "minimum": 0, "maximum": 1,
                                     "description": "> 0 liga o fundo."},
                "background_round_radius": {"type": "number"},
                "shadow_enabled": {"type": "boolean"},
                "intro_animation": {"type": "string",
                                    "description": "Animação de entrada do texto "
                                                   "(ex.: Typewriter, Fade_In). Nome "
                                                   "inválido devolve sugestões."},
                "outro_animation": {"type": "string",
                                    "description": "Animação de saída do texto "
                                                   "(ex.: Fade_Out). Nome inválido "
                                                   "devolve sugestões."},
                "text_styles": {
                    "type": "array",
                    "description": "Estilos por faixa de caracteres, sem sobreposição.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "integer", "minimum": 0},
                            "end": {"type": "integer", "minimum": 1},
                            "font_size": {"type": "number"},
                            "font_color": {"type": "string"},
                            "bold": {"type": "boolean"},
                            "italic": {"type": "boolean"},
                            "underline": {"type": "boolean"},
                            "font": {"type": "string",
                                     "description": "Fonte só desta faixa."},
                        },
                        "required": ["start", "end"], "additionalProperties": False,
                    },
                },
            },
            "required": ["draft_id", "text"], "additionalProperties": False,
        },
    },
    "capcut.subtitle.add": {
        "handler": _media_handler("subtitle"),
        "title": "Adicionar legendas",
        "description": (
            "Importa legendas para uma track própria, criando um segmento de texto por "
            "bloco. Aceita 'srt' (caminho de arquivo, URL http(s) ou conteúdo SRT "
            "inline) OU 'segments' com [{start, end, text}] — exatamente um dos dois. "
            "Os timestamps vêm da entrada; 'time_offset' desloca TODOS os blocos de uma "
            "vez, que é o único controle temporal disponível. O estilo é uniforme para "
            "todas as legendas: não há estilo por bloco. O preset default ('outline') "
            "liga a borda, porque texto sem contraste sobre vídeo fica ilegível. "
            "Acentuação portuguesa e quebra de linha dentro do bloco são preservadas. "
            "Todo o conteúdo é validado ANTES de qualquer alteração, então um SRT "
            "malformado não deixa nada pela metade."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "srt": {"type": "string",
                        "description": "Caminho absoluto, URL http(s), ou conteúdo SRT "
                                       "inline (precisa conter '-->')."},
                "segments": {
                    "type": "array", "minItems": 1,
                    "description": "Alternativa ao SRT: blocos estruturados.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "number", "minimum": 0,
                                      "description": "Início em segundos."},
                            "end": {"type": "number", "minimum": 0,
                                    "description": "Fim em segundos."},
                            "text": {"type": "string", "minLength": 1,
                                     "description": "Aceita \\n para quebrar linha."},
                        },
                        "required": ["start", "end", "text"],
                        "additionalProperties": False,
                    },
                },
                "track": {"type": "string", "default": _HM.TRACK_SUBTITLE},
                "time_offset": {"type": "number", "default": 0.0,
                                "description": "Desloca todos os blocos, em segundos. "
                                               "Positivo atrasa."},
                "style": {"type": "string",
                          "enum": sorted(_HM.SUBTITLE_PRESETS),
                          "default": _HM.DEFAULT_SUBTITLE_PRESET,
                          "description": "outline = borda preta; boxed = caixa "
                                         "semitransparente; outline_boxed = os dois; "
                                         "plain = sem contraste (não recomendado)."},
                "font": {"type": "string",
                         "description": "Nome exato de uma das 335 fontes do CapCut. "
                                        "Omitir usa a fonte padrão do app, que "
                                        "renderiza acentuação portuguesa corretamente "
                                        "— é a escolha recomendada. Nome inválido "
                                        "devolve erro com sugestões parecidas."},
                "font_size": {"type": "number", "minimum": 1, "maximum": 100,
                              "default": _HM.SUBTITLE_FONT_SIZE,
                              "description": "Escala interna do CapCut. 8.0 equivale a "
                                             "~31 px num canvas 1080x1920."},
                "font_color": {"type": "string", "default": "#FFFFFF"},
                "transform_x": {"type": "number", "default": 0.0},
                "transform_y": {"type": "number", "default": -0.8,
                                "description": "-0.8 = rodapé. Y positivo é para cima."},
                "align": {"type": "integer", "enum": [0, 1, 2], "default": 1},
                "bold": {"type": "boolean", "default": False},
                "line_spacing": {"type": "number", "default": 0.25},
                "max_chars_per_line": {"type": "integer", "minimum": 12, "maximum": 120,
                                       "description": "Limite por linha antes de quebrar "
                                                      "em limite de palavra. Omitir "
                                                      "calcula pelo font_size."},
            },
            "required": ["draft_id"], "additionalProperties": False,
        },
    },
    "capcut.video.cut": {
        "handler": _media_handler("cut"),
        "title": "Cortar vídeo mantendo trechos",
        "description": (
            "Corta um vídeo declarando os trechos que FICAM, e os encadeia na timeline "
            "em sequência, sem buraco. É a forma direta de 'cortar nos momentos X': "
            "keep=[[0,5],[12,18]] mantém 0–5s e 12–18s da mídia e produz um vídeo de "
            "11s. Evita calcular timeline_start à mão, que é onde é fácil errar e "
            "perder conteúdo. Devolve também quais trechos da origem foram removidos. "
            "Os trechos são sempre montados na ordem da mídia; para montar fora dessa "
            "ordem, crie um draft novo com os trechos na ordem desejada."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "source": {"type": "string",
                           "description": "Caminho absoluto ou URL http(s) do vídeo."},
                "keep": {
                    "type": "array", "minItems": 1,
                    "description": "Trechos a manter, em segundos DENTRO da mídia: "
                                   "[[inicio, fim], ...]. Não podem se sobrepor.",
                    "items": {"type": "array", "minItems": 2, "maxItems": 2,
                              "items": {"type": "number", "minimum": 0}},
                },
                "track": {"type": "string", "default": _HM.TRACK_VIDEO},
                "timeline_start": {"type": "number", "minimum": 0,
                                   "description": "Onde o primeiro trecho entra. "
                                                  "Omitir anexa ao fim da track."},
                "gap": {"type": "number", "minimum": 0, "default": 0.0,
                        "description": "Segundos entre os trechos. 0 = encadeado."},
                "snap": {"type": "string", "enum": ["none", "speech"], "default": "none",
                         "description": "Com 'speech', encosta as pontas na fronteira "
                                        "de palavra para não cortar no meio da fala. "
                                        "Exige transcrição feita antes "
                                        "(capcut.media.transcribe)."},
                "snap_tolerance": {"type": "number", "minimum": 0, "default": 0.5,
                                   "description": "Quanto cada ponta pode se mover, em "
                                                  "segundos."},
                "snap_padding": {"type": "number", "minimum": 0, "default": 0.15,
                                 "description": "Folga antes e depois da fala, para não "
                                                "cortar a respiração."},
                "speed": {"type": "number", "default": 1.0},
                "volume": {"type": "number", "minimum": 0, "maximum": 2, "default": 1.0},
                "scale_x": {"type": "number", "default": 1.0},
                "scale_y": {"type": "number", "default": 1.0},
                "transform_x": {"type": "number", "default": 0.0},
                "transform_y": {"type": "number", "default": 0.0},
                "layer": {"type": "integer", "default": 0},
                "mask": {"type": "string"},
                "background_blur": {"type": "integer", "enum": [1, 2, 3, 4]},
            },
            "required": ["draft_id", "source", "keep"], "additionalProperties": False,
        },
    },
    "capcut.text.add_many": {
        "handler": _media_handler("text_batch"),
        "title": "Adicionar vários textos",
        "description": (
            "Coloca vários textos em momentos pré-determinados numa única chamada, com "
            "estilo compartilhado. Cada item traz só conteúdo e tempo; fonte, tamanho, "
            "cor, borda, fundo e posição vêm do nível de cima e valem para todos. "
            "Sobreposição entre os textos é recusada antes de qualquer alteração. "
            "Para um texto só, ou para estilos diferentes por texto, use capcut.text.add."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "items": {
                    "type": "array", "minItems": 1,
                    "description": "Os textos e seus momentos.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "minLength": 1},
                            "timeline_start": {"type": "number", "minimum": 0,
                                               "description": "Momento em que aparece."},
                            "duration": {"type": "number",
                                         "description": "Quanto tempo fica. Omitir usa "
                                                        "o 'duration' do nível de cima."},
                        },
                        "required": ["text", "timeline_start"],
                        "additionalProperties": False,
                    },
                },
                "track": {"type": "string", "default": _HM.TRACK_TEXT},
                "duration": {"type": "number", "default": 3.0,
                             "description": "Duração default de cada texto."},
                "font": {"type": "string"},
                "font_size": {"type": "number", "minimum": 1, "maximum": 100,
                              "default": _HM.FONT_SIZE_DEFAULT,
                              "description": "Escala interna do CapCut (~3-20)."},
                "font_color": {"type": "string", "default": "#FFFFFF"},
                "transform_x": {"type": "number", "default": 0.0},
                "transform_y": {"type": "number", "default": 0.0},
                "bold": {"type": "boolean", "default": False},
                "italic": {"type": "boolean", "default": False},
                "align": {"type": "integer", "enum": [0, 1, 2], "default": 1},
                "border_color": {"type": "string"},
                "border_width": {"type": "number"},
                "background_color": {"type": "string"},
                "background_alpha": {"type": "number", "minimum": 0, "maximum": 1},
                "background_round_radius": {"type": "number"},
                "shadow_enabled": {"type": "boolean"},
                "intro_animation": {"type": "string"},
                "outro_animation": {"type": "string"},
            },
            "required": ["draft_id", "items"], "additionalProperties": False,
        },
    },
    "capcut.media.transcribe": {
        "handler": _HD.media_transcribe,
        "title": "Transcrever a fala do vídeo",
        "description": (
            "Transcreve a fala com timestamps, usando whisper.cpp local — nada é "
            "enviado para fora da máquina. Devolve 'segments' no formato que "
            "capcut.subtitle.add consome, 'compact' para você LER e escolher os cortes, "
            "e opcionalmente 'words' com timestamp por palavra. O resultado fica em "
            "cache: chamar de novo é instantâneo. "
            "IMPORTANTE: se você for cortar o vídeo, não passe estes 'segments' para o "
            "subtitle.add — use capcut.subtitle.from_transcript, que remapeia os tempos "
            "para a timeline cortada. Sem isso a legenda fica dessincronizada."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string",
                           "description": "Caminho absoluto do vídeo ou áudio. Vídeo tem "
                                          "o áudio extraído automaticamente."},
                "language": {"type": "string", "default": "auto",
                             "description": "'auto' detecta; ou 'pt', 'en', 'es'..."},
                "model": {"type": "string",
                          "enum": ["tiny", "base", "small", "medium"],
                          "default": "small",
                          "description": "'small' é o default: medido nesta máquina, "
                                         "pontua corretamente e roda a ~8x o tempo real. "
                                         "'tiny' e 'base' saem sem pontuação de frase."},
                "format": {"type": "string", "enum": ["blocks", "words", "both"],
                           "default": "blocks",
                           "description": "'words' só quando precisar de timestamp por "
                                          "palavra: infla muito a resposta."},
                "max_chars_per_block": {"type": "integer", "minimum": 12, "maximum": 120,
                                        "default": 26,
                                        "description": "Teto de caracteres por bloco de "
                                                       "legenda. 26 foi medido na tela do "
                                                       "CapCut. O limite é respeitado: o "
                                                       "-ml do whisper.cpp é aproximado, "
                                                       "então blocos acima do teto são "
                                                       "repartidos em fronteira de palavra. "
                                                       "Uma palavra sozinha maior que o "
                                                       "teto fica intacta — partir no meio "
                                                       "dela seria pior."},
                "max_block_seconds": {"type": "number", "default": 4.0},
                "offset": {"type": "integer", "minimum": 0, "default": 0,
                           "description": "Paginação, para transcript longo."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000,
                          "default": 200},
                "refresh": {"type": "boolean", "default": False,
                            "description": "Ignora o cache e transcreve de novo."},
            },
            "required": ["source"], "additionalProperties": False,
        },
    },
    "capcut.subtitle.from_transcript": {
        "handler": _media_handler("subtitle_from_transcript"),
        "title": "Legendas do transcript, sincronizadas com o corte",
        "description": (
            "Cria as legendas a partir da transcrição em cache, REMAPEANDO os tempos da "
            "mídia original para a timeline cortada. Use sempre que houver corte: o "
            "transcript está em tempo da mídia, e depois de cortar os tempos da timeline "
            "são outros — passar os blocos direto produz legenda dessincronizada sem que "
            "nada acuse o erro. "
            "Descarta os blocos que caíram em trecho removido e encurta os que "
            "atravessam a fronteira do corte, informando quantos em cada caso. "
            "Exige capcut.media.transcribe antes, e o vídeo já na timeline."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "source": {"type": "string",
                           "description": "A mesma mídia que foi transcrita e cortada."},
                "transcript_id": {"type": "string",
                                  "description": "Fixa QUAL transcrição usar, quando a "
                                                 "mesma mídia tem várias em cache. "
                                                 "Omitir usa a mais recente do modelo "
                                                 "mais forte, e avisa se houver outras."},
                "max_chars_per_block": {"type": "integer", "minimum": 12, "maximum": 120,
                                        "description": "Prefere a transcrição moldada "
                                                       "com este limite, se existir."},
                "track": {"type": "string", "default": _HM.TRACK_SUBTITLE},
                "straddle": {"type": "string",
                             "enum": ["truncate", "drop", "keep_partial"],
                             "default": "truncate",
                             "description": "O que fazer com a legenda que atravessa a "
                                            "fronteira do corte."},
                "style": {"type": "string", "enum": sorted(_HM.SUBTITLE_PRESETS),
                          "default": _HM.DEFAULT_SUBTITLE_PRESET},
                "font": {"type": "string",
                         "description": "Omitir usa a fonte padrão do CapCut, que "
                                        "renderiza acentuação portuguesa corretamente."},
                "font_size": {"type": "number", "minimum": 1, "maximum": 100,
                              "default": _HM.SUBTITLE_FONT_SIZE},
                "font_color": {"type": "string", "default": "#FFFFFF"},
                "transform_x": {"type": "number", "default": 0.0},
                "transform_y": {"type": "number", "default": -0.8},
                "align": {"type": "integer", "enum": [0, 1, 2], "default": 1},
                "bold": {"type": "boolean", "default": False},
                "line_spacing": {"type": "number", "default": 0.25},
                "max_chars_per_line": {"type": "integer", "minimum": 12, "maximum": 120},
            },
            "required": ["draft_id", "source"], "additionalProperties": False,
        },
    },
    "capcut.draft.validate": {
        "handler": _HD.draft_validate,
        "title": "Validar o draft antes de salvar",
        "description": (
            "Confere o draft e devolve os problemas encontrados, por severidade. "
            "Pega o que este fluxo erra na prática: texto que começa depois de o vídeo "
            "terminar (aparece sobre tela preta), buraco na track de vídeo, legenda "
            "fora da safe zone, texto sem contraste, segmento de duração zero, mídia "
            "que saiu do disco, sobreposição. O save chama isto automaticamente e "
            "recusa quando há erro — use antes para saber o que corrigir."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "min_severity": {"type": "string", "enum": ["error", "warning", "info"],
                                 "default": "info",
                                 "description": "Filtra o que é reportado."},
            },
            "required": ["draft_id"], "additionalProperties": False,
        },
    },
    "capcut.draft.inspect": {
        "handler": _HD.draft_inspect,
        "title": "Inspecionar o draft",
        "description": (
            "Mostra o estado real do draft: tracks, segmentos com índice e tempos, "
            "duração total, tracks vazias, lacunas e keyframes pendentes. Use para "
            "verificar o que foi construído ANTES de salvar, e para descobrir os "
            "índices que capcut.draft.rebuild usa."
        ),
        "schema": {
            "type": "object",
            "properties": {"draft_id": {"type": "string"}},
            "required": ["draft_id"], "additionalProperties": False,
        },
    },
    "capcut.draft.rebuild": {
        "handler": _HD.draft_rebuild,
        "title": "Reconstruir o draft em outra ordem",
        "description": (
            "Recria o draft aplicando uma nova ordem aos passos já registrados. É assim "
            "que se REORDENA conteúdo: não existe API de mover ou remover segmento em "
            "nenhuma camada, então reordenar significa reconstruir. Passe 'order' como "
            "permutação dos índices dos passos (veja capcut.draft.inspect). Por default "
            "os tempos são recalculados em cadeia."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "order": {"type": "array", "items": {"type": "integer", "minimum": 0},
                          "description": "Permutação dos índices dos passos de mídia."},
                "recompute_timeline": {"type": "boolean", "default": True,
                                       "description": "Recalcula timeline_start em "
                                                      "sequência, ignorando os originais."},
            },
            "required": ["draft_id"], "additionalProperties": False,
        },
    },
})
