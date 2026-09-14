"""Legendas (spec: SUB-01..04).

## Decisão de desenho: não usamos o `import_srt` do upstream

`Script_file.import_srt()` tem um bug estrutural: `font_type` só é atribuído dentro de
`if font:` (`script_file.py:503-505`) mas é lido na closure em `:547` e `:552`. Com
`font=None` — o default do schema MCP do upstream — levanta
`NameError: cannot access free variable 'font_type'`. Verificado na auditoria.

Pior: a track de legenda é criada **antes** da exceção, deixando uma track órfã no draft.

Em vez de contornar o bug, o L1 **parseia o SRT por conta própria** e cria um segmento
de texto por bloco usando `add_text_impl`, que é o caminho já verificado visualmente na
Phase 3 (acentuação PT-BR e multi-estilo confirmados no CapCut). Ganhos:

  * a classe de erro `NameError` deixa de existir;
  * `blocks_imported` é exato, e o upstream não devolve contagem nenhuma;
  * erro de parsing aponta o número da linha;
  * nada é mutado antes de todo o SRT estar validado — sem track órfã;
  * o preset de contraste é aplicado de forma uniforme.

O que se perde: `import_srt` define `fixed_width` conforme a orientação. Isso é
reproduzido aqui explicitamente.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import errors as E

# 00:00:01,500 --> 00:00:03,250   (aceita '.' no lugar de ',')
_TS = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*$"
)

# Largura fixa da legenda, como proporção da largura do canvas. O `import_srt` do
# upstream usa 0.6 em retrato e 0.7 em paisagem; reproduzido aqui.
FIXED_WIDTH_PORTRAIT = 0.6
FIXED_WIDTH_LANDSCAPE = 0.7


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_srt(content: str) -> List[Dict[str, Any]]:
    """Parseia SRT e devolve [{index, start, end, text, line}].

    Tolerante ao que varia na prática (índice ausente, `.` no lugar de `,`, CRLF,
    linhas em branco extras) e estrito no que importa: todo bloco precisa de um
    timestamp válido e de pelo menos uma linha de texto.
    """
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):           # BOM
        text = text[1:]
    lines = text.split("\n")

    blocks: List[Dict[str, Any]] = []
    i = 0
    n = len(lines)
    while i < n:
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break
        block_line = i + 1                   # 1-indexado, para a mensagem de erro

        # índice numérico opcional. Se a linha seguinte PARECE um timestamp (tem
        # '-->') mas não casa, avançamos para apontar o erro nela, que é onde está.
        if lines[i].strip().isdigit() and i + 1 < n and (
                _TS.match(lines[i + 1]) or "-->" in lines[i + 1]):
            i += 1
        match = _TS.match(lines[i]) if i < n else None
        if not match:
            raise E.CapcutError(
                E.SRT_PARSE_ERROR,
                f"Linha {i + 1}: esperava um timestamp SRT e encontrei "
                f"{lines[i].strip()[:60]!r}.",
                "O formato é 'HH:MM:SS,mmm --> HH:MM:SS,mmm'. "
                "Se o conteúdo não é SRT, use o parâmetro 'segments' em vez de 'srt'.",
                line=i + 1,
            )
        start = _to_seconds(*match.group(1, 2, 3, 4))
        end = _to_seconds(*match.group(5, 6, 7, 8))
        i += 1

        text_lines: List[str] = []
        while i < n and lines[i].strip():
            text_lines.append(lines[i].rstrip())
            i += 1
        if not text_lines:
            raise E.CapcutError(
                E.SRT_PARSE_ERROR,
                f"Linha {block_line}: o bloco tem timestamp mas nenhum texto.",
                "Todo bloco precisa de ao menos uma linha de texto.",
                line=block_line,
            )
        blocks.append({
            "index": len(blocks) + 1,
            "start": start,
            "end": end,
            "text": "\n".join(text_lines),
            "line": block_line,
        })
    if not blocks:
        raise E.CapcutError(
            E.SRT_PARSE_ERROR, "Nenhum bloco de legenda foi encontrado no conteúdo.",
            "Verifique se o SRT não está vazio.",
        )
    return blocks


def load_source(srt: str) -> Tuple[str, str]:
    """Aceita caminho de arquivo, URL http(s) ou conteúdo SRT inline.

    Devolve (conteúdo, origem) onde origem ∈ {file, url, inline}.
    """
    if srt.startswith(("http://", "https://")):
        import requests
        try:
            resp = requests.get(srt, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            raise E.CapcutError(
                E.SRT_FETCH_FAILED, f"Não foi possível baixar o SRT: {srt}",
                "Confirme a URL e a conectividade.", upstream=str(exc)[:200],
            ) from exc
        resp.encoding = resp.encoding or "utf-8"
        return resp.text, "url"

    expanded = os.path.abspath(os.path.expanduser(srt))
    looks_like_path = "\n" not in srt and len(srt) < 4096
    if looks_like_path and os.path.isfile(expanded):
        try:
            with open(expanded, encoding="utf-8-sig") as f:
                return f.read(), "file"
        except UnicodeDecodeError as exc:
            raise E.CapcutError(
                E.SRT_PARSE_ERROR, f"O arquivo não está em UTF-8: {expanded}",
                "Converta o arquivo para UTF-8 e tente de novo.", upstream=str(exc)[:200],
            ) from exc
    if looks_like_path and ("-->" not in srt):
        raise E.CapcutError(
            E.SRT_NOT_FOUND, f"Arquivo de legenda não encontrado: {expanded}",
            "Informe um caminho absoluto existente, uma URL http(s), ou o conteúdo "
            "SRT inline (que precisa conter '-->').",
        )
    return srt, "inline"


def validate_blocks(blocks: List[Dict[str, Any]], offset: float) -> List[Dict[str, Any]]:
    """Aplica o deslocamento e recusa o que geraria timeline inválida."""
    out = []
    for b in blocks:
        start = b["start"] + offset
        end = b["end"] + offset
        if start < 0:
            raise E.CapcutError(
                E.INVALID_TIMERANGE,
                f"Bloco {b['index']} (linha {b['line']}) ficaria em {start:.3f}s com "
                f"time_offset={offset}.",
                "Use um time_offset menor, ou 0 para manter os tempos do arquivo.",
                block=b["index"], line=b["line"],
            )
        if end <= start:
            raise E.CapcutError(
                E.INVALID_TIMERANGE,
                f"Bloco {b['index']} (linha {b['line']}) tem fim <= início "
                f"({start:.3f}s → {end:.3f}s).",
                "Corrija os timestamps no arquivo.",
                block=b["index"], line=b["line"],
            )
        out.append(dict(b, start=start, end=end))

    for prev, cur in zip(out, out[1:]):
        if cur["start"] < prev["end"] - 1e-6:
            raise E.CapcutError(
                E.SEGMENT_OVERLAP,
                f"Os blocos {prev['index']} e {cur['index']} se sobrepõem "
                f"({prev['end']:.3f}s vs {cur['start']:.3f}s).",
                "Legendas na mesma track não podem se sobrepor. Ajuste os timestamps.",
                blocks=[prev["index"], cur["index"]],
            )
    return out


def from_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Converte a forma estruturada [{start, end, text}] para blocos."""
    out = []
    for i, s in enumerate(segments, start=1):
        if "start" not in s or "end" not in s or not str(s.get("text", "")).strip():
            raise E.CapcutError(
                E.MISSING_REQUIRED_PARAM,
                f"Segmento {i} precisa de 'start', 'end' e 'text' não vazio.",
                "Formato: {\"start\": 0.0, \"end\": 2.0, \"text\": \"...\"}",
                segment=i,
            )
        out.append({"index": i, "start": float(s["start"]), "end": float(s["end"]),
                    "text": str(s["text"]), "line": i})
    return sorted(out, key=lambda b: b["start"])


def to_srt(blocks: List[Dict[str, Any]]) -> str:
    """Serializa blocos de volta para SRT — útil para log e depuração."""
    def stamp(t: float) -> str:
        ms = int(round((t - int(t)) * 1000))
        s = int(t) % 60
        m = (int(t) // 60) % 60
        h = int(t) // 3600
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    parts = []
    for b in blocks:
        parts.append(f"{b['index']}\n{stamp(b['start'])} --> {stamp(b['end'])}\n"
                     f"{b['text']}\n")
    return "\n".join(parts)
