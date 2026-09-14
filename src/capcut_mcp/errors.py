"""Modelo de erro e envelope de resposta (spec: Error Model, MCP Tool Contract).

Regra E1: proibido sucesso vazio. Se a operação não produziu o efeito pedido, é erro.
Regra E2: toda exceção do L0 é traduzida — nenhuma mensagem crua do Python vaza.
Regra E3: zero mensagens em chinês.
Regra E4: todo erro carrega `suggestion` acionável.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------- códigos
# Entrada
MISSING_REQUIRED_PARAM = "MISSING_REQUIRED_PARAM"
INVALID_DIMENSIONS = "INVALID_DIMENSIONS"
INVALID_TIMERANGE = "INVALID_TIMERANGE"
RATIO_MISMATCH = "RATIO_MISMATCH"
INVALID_VOLUME = "INVALID_VOLUME"
INVALID_TRANSFORM = "INVALID_TRANSFORM"
INVALID_STYLE_RANGE = "INVALID_STYLE_RANGE"
# Catálogo
UNKNOWN_TRANSITION = "UNKNOWN_TRANSITION"
UNKNOWN_MASK = "UNKNOWN_MASK"
UNKNOWN_FONT = "UNKNOWN_FONT"
UNKNOWN_ANIMATION = "UNKNOWN_ANIMATION"
UNKNOWN_CATALOG = "UNKNOWN_CATALOG"
# Estado
DRAFT_NOT_FOUND = "DRAFT_NOT_FOUND"
DRAFT_EMPTY = "DRAFT_EMPTY"
TRACK_NOT_FOUND = "TRACK_NOT_FOUND"
SEGMENT_OVERLAP = "SEGMENT_OVERLAP"
SOURCE_RANGE_EXCEEDS_MEDIA = "SOURCE_RANGE_EXCEEDS_MEDIA"
# Mídia
SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
PROBE_FAILED = "PROBE_FAILED"
ASSET_FETCH_FAILED = "ASSET_FETCH_FAILED"
# Ambiente
FFPROBE_UNAVAILABLE = "FFPROBE_UNAVAILABLE"
TARGET_DIR_NOT_FOUND = "TARGET_DIR_NOT_FOUND"
TARGET_EXISTS = "TARGET_EXISTS"
PROJECT_LOCKED = "PROJECT_LOCKED"
TEMPLATE_MISSING = "TEMPLATE_MISSING"
DISK_FULL = "DISK_FULL"
PERMISSION_DENIED = "PERMISSION_DENIED"
NO_REFERENCE_PROJECT = "NO_REFERENCE_PROJECT"
# Contrato
OPERATION_NOT_SUPPORTED = "OPERATION_NOT_SUPPORTED"
VALIDATION_FAILED = "VALIDATION_FAILED"
# Interno
UPSTREAM_ERROR = "UPSTREAM_ERROR"
INTERNAL_ERROR = "INTERNAL_ERROR"

RETRYABLE = {ASSET_FETCH_FAILED, FFPROBE_UNAVAILABLE, DISK_FULL, PERMISSION_DENIED,
             PROBE_FAILED}

_CJK = re.compile(r"[　-鿿＀-￯]")


class CapcutError(Exception):
    """Erro de domínio, sempre com código e sugestão acionável."""

    def __init__(self, code: str, message: str, suggestion: str = "", **context: Any):
        if _CJK.search(message):  # regra E3
            message = "O upstream reportou um erro em chinês; consulte o log estruturado."
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion
        self.context = context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.code in RETRYABLE,
            "suggestion": self.suggestion,
            "context": self.context,
        }


# ----------------------------------------------------- tradução do upstream
def translate(exc: BaseException) -> CapcutError:
    """Regra E2: traduz exceções cruas do L0 para o modelo de erro."""
    if isinstance(exc, CapcutError):
        return exc
    text = str(exc)

    if isinstance(exc, TypeError) and "required positional argument" in text:
        arg = text.split("'")[-2] if "'" in text else "?"
        return CapcutError(
            MISSING_REQUIRED_PARAM,
            f"O parâmetro obrigatório '{arg}' não foi informado.",
            f"Inclua '{arg}' na chamada.",
            upstream=text,
        )
    if isinstance(exc, NameError) and "font_type" in text:
        return CapcutError(
            MISSING_REQUIRED_PARAM,
            "A fonte é obrigatória para legendas nesta versão do upstream.",
            "Informe 'font' com um nome válido do catálogo.",
            upstream=text,
        )
    if isinstance(exc, FileNotFoundError):
        return CapcutError(
            SOURCE_NOT_FOUND, f"Arquivo não encontrado: {text}",
            "Verifique o caminho absoluto do arquivo.", upstream=text,
        )
    if _CJK.search(text):
        return CapcutError(
            UPSTREAM_ERROR,
            "O upstream recusou a operação (mensagem original em chinês no log).",
            "Consulte o log estruturado para a causa.", upstream=text,
        )
    return CapcutError(
        UPSTREAM_ERROR, f"Falha inesperada no upstream: {text}",
        "Consulte o log estruturado; se persistir, reporte com o trecho do log.",
        upstream=text, exc_type=type(exc).__name__,
    )


# ----------------------------------------------------------- envelope
def ok_envelope(data: Dict[str, Any], warnings: Optional[List[Dict]] = None,
                meta: Optional[Dict] = None) -> Dict[str, Any]:
    return {"ok": True, "data": data, "warnings": warnings or [], "meta": meta or {}}


def err_envelope(exc: BaseException, warnings: Optional[List[Dict]] = None,
                 meta: Optional[Dict] = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": translate(exc).to_dict(),
        "warnings": warnings or [],
        "meta": meta or {},
    }
