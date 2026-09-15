"""Transcrição via whisper.cpp (spec: SPEC_ASR_E_SELECAO, Parte 1).

## Engine: whisper.cpp por subprocess

Escolhida porque mantém o L1 em 6 dependências Python (o `mlx-whisper` traria 25
pacotes, incluindo `torch`) e porque entra pelo mesmo padrão que o `media.probe` já usa
com o `ffprobe`. Esta máquina tem 8 GB de RAM e o working set da GPU é 5,7 GB.

## Fatos verificados no binário 1.9.4 (não supostos)

  * aceita apenas flac, mp3, ogg e wav -> vídeo precisa de extração por ffmpeg;
  * `-ml N -sow` já molda blocos por caractere quebrando em palavra, o que dispensa
    reimplementar o wrap para o caminho de ASR;
  * `-ojf` traz timestamps por TOKEN sem precisar de `-dtw`; tokens são sub-palavra
    (`Bem`, `-`, `v`, `indo`), então a junção em palavras é feita aqui;
  * o JSON sai em arquivo (`-of`), não em stdout;
  * stderr é ruidoso (carregamento dos backends ggml/Metal) e não é aviso;
  * `-np` silencia tudo que não é resultado.

## Medido nesta máquina (16,72 s de fala pt-BR)

  | modelo | tempo  | velocidade | qualidade                                  |
  | base   | 0,84 s | ~20x       | sem pontuação de frase, perde hífen        |
  | small  | 2,04 s | ~8x        | pontuação e capitalização corretas         |

`small` é o default por causa da pontuação, não da velocidade: legenda sem pontuação
fica ruim, e 8x tempo real é folgado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from . import errors as E, media, obs

BIN = "whisper-cli"
MODELS_DIR = os.path.expanduser("~/Library/Application Support/capcut-mcp/models")
CACHE_DIR = os.path.expanduser("~/Library/Application Support/capcut-mcp/transcripts")

# Formatos que o binário aceita direto; o resto passa por ffmpeg.
NATIVE_AUDIO = {".wav", ".mp3", ".ogg", ".flac"}

# tamanho do arquivo, RAM aproximada e se cabe nesta máquina (working set 5,7 GB)
MODELS: Dict[str, Dict[str, Any]] = {
    "tiny": {"file": "ggml-tiny.bin", "mb": 75, "ram_gb": 1.0, "ok": True},
    "base": {"file": "ggml-base.bin", "mb": 141, "ram_gb": 1.0, "ok": True},
    "small": {"file": "ggml-small.bin", "mb": 465, "ram_gb": 2.0, "ok": True},
    "medium": {"file": "ggml-medium.bin", "mb": 1500, "ram_gb": 5.0, "ok": True},
    "large-v3": {"file": "ggml-large-v3.bin", "mb": 3100, "ram_gb": 10.0, "ok": False},
}
DEFAULT_MODEL = "small"

MODEL_URL = ("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{file}")

# Moldagem de bloco de legenda. 26 caracteres foi MEDIDO na tela na Phase 4:
# 27 caracteres couberam numa linha, 31 quebraram no meio da palavra.
DEFAULT_MAX_CHARS = 26
DEFAULT_MAX_BLOCK_S = 4.0
MIN_BLOCK_S = 0.8

# Tokens especiais do whisper.cpp: [_BEG_], [_TT_163], [_EOT_]...
# O sufixo varia (nem todos terminam em "_]"), por isso o padrão é aberto.
_SPECIAL_TOKEN = re.compile(r"^\[_.*\]$")

# Anotação de som não-falado. Em silêncio, o whisper.cpp ALUCINA: medido nesta
# máquina, 3 s de silêncio puro no modelo 'base' produziram o bloco
# "[MÚSICA DE FUNDO]". Como legenda isso apareceria na tela, então é descartado —
# e se nada sobrar, a transcrição é NO_SPEECH_DETECTED, que é a verdade.
_NON_SPEECH = re.compile(r"^[\[\(\*\u266a]+[^\]\)\*\u266a]*[\]\)\*\u266a]*$")


def is_non_speech(text: str) -> bool:
    t = text.strip()
    return bool(t) and bool(_NON_SPEECH.match(t))


# ------------------------------------------------------------- pré-condições
def binary_path() -> str:
    path = shutil.which(BIN)
    if not path:
        raise E.CapcutError(
            E.ASR_UNAVAILABLE, f"'{BIN}' não encontrado no PATH.",
            "Instale com: brew install whisper-cpp",
        )
    return path


def model_path(model: str) -> str:
    spec = MODELS.get(model)
    if spec is None:
        raise E.CapcutError(
            E.MISSING_REQUIRED_PARAM, f"Modelo desconhecido: {model}",
            f"Use um destes: {', '.join(MODELS)}.")
    if not spec["ok"]:
        raise E.CapcutError(
            E.ASR_MODEL_TOO_LARGE,
            f"O modelo '{model}' precisa de ~{spec['ram_gb']:.0f} GB de RAM e esta "
            "máquina tem 8 GB (working set da GPU: 5,7 GB).",
            "Use 'medium' com o CapCut fechado, ou 'small', que é o default.",
            model=model)
    path = os.path.join(MODELS_DIR, spec["file"])
    if not os.path.isfile(path):
        raise E.CapcutError(
            E.ASR_MODEL_MISSING,
            f"O modelo '{model}' não está baixado ({spec['mb']} MB).",
            f"Baixe com:\n  mkdir -p '{MODELS_DIR}' && curl -L -o '{path}' "
            + MODEL_URL.format(file=spec["file"]),
            model=model, expected_path=path, size_mb=spec["mb"])
    return path


def installed_models() -> List[str]:
    return [name for name, spec in MODELS.items()
            if os.path.isfile(os.path.join(MODELS_DIR, spec["file"]))]


# ------------------------------------------------------------------- cache
def _file_fingerprint(path: str) -> str:
    """Hash do conteúdo. Para arquivo grande, amostra início, meio e fim."""
    size = os.path.getsize(path)
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb") as f:
        if size <= 8 * 1024 * 1024:
            h.update(f.read())
        else:
            for pos in (0, size // 2, max(0, size - 2 * 1024 * 1024)):
                f.seek(pos)
                h.update(f.read(2 * 1024 * 1024))
    return h.hexdigest()[:20]


def fingerprint(source: str) -> str:
    """Identidade do CONTEÚDO da mídia, independente de onde ela está no disco."""
    if source.startswith(("http://", "https://")):
        return hashlib.sha256(source.encode()).hexdigest()[:20]
    return _file_fingerprint(source)


def transcript_id(source: str, model: str, language: str, max_chars: int) -> str:
    return hashlib.sha256(
        f"{fingerprint(source)}|{model}|{language}|{max_chars}".encode()
    ).hexdigest()[:24]


def _cache_path(tid: str) -> str:
    return os.path.join(CACHE_DIR, f"{tid}.json")


def load_cached(tid: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_cache_path(tid), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cached(tid: str, data: Dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _cache_path(tid))     # atômico, como o registry
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --------------------------------------------------------------- extração
def ensure_audio(source: str, workdir: str) -> Tuple[str, bool]:
    """Devolve (caminho de áudio aceito pelo binário, precisou converter)."""
    ext = os.path.splitext(source)[1].lower()
    if ext in NATIVE_AUDIO and not source.startswith(("http://", "https://")):
        return source, False
    out = os.path.join(workdir, "audio.wav")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", source,
           "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", out]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        raise E.CapcutError(
            E.ASR_FAILED, f"Não foi possível extrair o áudio de {os.path.basename(source)}.",
            "Confirme que o arquivo tem faixa de áudio.",
            ffmpeg=(exc.stderr or "")[-300:]) from exc
    except subprocess.TimeoutExpired as exc:
        raise E.CapcutError(
            E.ASR_TIMEOUT, "A extração de áudio excedeu 10 minutos.",
            "Use um arquivo local em vez de URL, ou um trecho menor.") from exc
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise E.CapcutError(
            E.NO_SPEECH_DETECTED, f"{os.path.basename(source)} não tem áudio.",
            "Escolha um arquivo com faixa de áudio.")
    return out, True


# -------------------------------------------------------------- execução
def _run(binary: str, model: str, audio: str, language: str, max_chars: int,
         threads: Optional[int], timeout_s: float, out_base: str) -> Dict[str, Any]:
    cmd = [
        binary, "-m", model, "-f", audio,
        "-l", language,
        "-np",                       # só resultado; stderr continua ruidoso
        "-ml", str(max_chars),       # molda o bloco por caractere
        "-sow",                      # quebra em palavra, não em token
        "-ojf",                      # JSON com timestamps por token
        "-of", out_base,
    ]
    if threads:
        cmd += ["-t", str(threads)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise E.CapcutError(
            E.ASR_TIMEOUT,
            f"A transcrição excedeu {timeout_s:.0f}s.",
            "Use um modelo menor, ou transcreva um trecho com ffmpeg antes.",
            timeout_s=timeout_s) from exc
    if proc.returncode != 0:
        obs.log("asr_failed", returncode=proc.returncode, stderr=proc.stderr[-2000:])
        raise E.CapcutError(
            E.ASR_FAILED, "O whisper.cpp terminou com erro.",
            "Consulte o log estruturado; o stderr completo está lá.",
            returncode=proc.returncode)
    path = out_base + ".json"
    if not os.path.isfile(path):
        raise E.CapcutError(
            E.ASR_FAILED, "O whisper.cpp não gerou o arquivo JSON esperado.",
            "Consulte o log estruturado.", expected=path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- parsing
def _tokens_to_words(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Junta tokens sub-palavra em palavras.

    O whisper.cpp emite ' Bem', '-', 'v', 'indo' — um token começa palavra nova quando
    tem espaço à frente. Tokens especiais (`[_BEG_]`) são descartados.
    """
    words: List[Dict[str, Any]] = []
    for tok in tokens or []:
        text = tok.get("text", "")
        if not text or _SPECIAL_TOKEN.match(text.strip()):
            continue
        off = tok.get("offsets") or {}
        start, end = off.get("from", 0) / 1000.0, off.get("to", 0) / 1000.0
        if text.startswith(" ") or not words:
            words.append({"start": round(start, 3), "end": round(end, 3),
                          "word": text.strip(), "p": tok.get("p")})
        else:
            w = words[-1]
            w["word"] += text
            w["end"] = round(max(w["end"], end), 3)
            if tok.get("p") is not None and w.get("p") is not None:
                w["p"] = round(min(w["p"], tok["p"]), 4)
    return [w for w in words if w["word"]]


def _shape_blocks(raw: List[Dict[str, Any]], max_block_s: float,
                  max_chars: int = DEFAULT_MAX_CHARS) -> List[Dict[str, Any]]:
    """Funde blocos curtos demais no anterior, respeitando tempo E comprimento.

    O `-ml` do binário limita o comprimento de cada bloco que ELE emite, mas a
    fusão aqui acontece depois — e sem conferir o comprimento ela estourava o
    limite que a tool anuncia. Medido: com `max_chars=16` saía um bloco de 33
    caracteres, o dobro do pedido, que na tela quebra em duas linhas sem aviso.
    """
    blocks: List[Dict[str, Any]] = []
    for b in raw:
        if blocks:
            prev = blocks[-1]
            fundido = f"{prev['text']} {b['text']}".strip()
            curta = b["end"] - b["start"] < MIN_BLOCK_S
            cabe_no_tempo = (b["end"] - prev["start"]) <= max_block_s
            cabe_no_texto = len(fundido) <= max_chars
            if curta and cabe_no_tempo and cabe_no_texto:
                prev["end"] = b["end"]
                prev["text"] = fundido
                continue
        blocks.append(dict(b))
    for i, b in enumerate(blocks, start=1):
        b["index"] = i
    return blocks


def parse_output(data: Dict[str, Any], max_block_s: float,
                 max_chars: int = DEFAULT_MAX_CHARS) -> Dict[str, Any]:
    raw_blocks, words, descartados = [], [], []
    for seg in data.get("transcription", []) or []:
        off = seg.get("offsets") or {}
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if is_non_speech(text):
            descartados.append(text)
            continue
        raw_blocks.append({"start": round(off.get("from", 0) / 1000.0, 3),
                           "end": round(off.get("to", 0) / 1000.0, 3),
                           "text": text})
        words.extend(_tokens_to_words(seg.get("tokens")))
    if not raw_blocks:
        detalhe = (f" O reconhecedor devolveu só anotação de som: "
                   f"{', '.join(descartados[:3])}." if descartados else "")
        raise E.CapcutError(
            E.NO_SPEECH_DETECTED,
            "Nenhuma fala foi reconhecida no áudio." + detalhe,
            "Confirme que há voz audível. Se houver, tente o modelo 'medium'.",
            non_speech_blocks=descartados[:10])
    return {
        "language": (data.get("result") or {}).get("language"),
        "model_type": (data.get("model") or {}).get("type"),
        "blocks": _shape_blocks(raw_blocks, max_block_s, max_chars),
        "words": words,
        "non_speech_dropped": descartados,
    }


# ---------------------------------------------------------------- pública
def transcribe(source: str, *, language: str = "auto", model: str = DEFAULT_MODEL,
               max_chars: int = DEFAULT_MAX_CHARS,
               max_block_s: float = DEFAULT_MAX_BLOCK_S,
               threads: Optional[int] = None, refresh: bool = False,
               bus: Optional[obs.WarningBus] = None) -> Dict[str, Any]:
    bus = bus or obs.WarningBus()
    binary = binary_path()
    mpath = model_path(model)

    probe = media.probe(source)
    if probe["kind"] == "image":
        raise E.CapcutError(
            E.UNSUPPORTED_FORMAT, f"{source} é imagem; não há áudio para transcrever.",
            "Informe um vídeo ou um arquivo de áudio.")
    if probe["kind"] == "video" and not probe["has_audio"]:
        raise E.CapcutError(
            E.NO_SPEECH_DETECTED, f"{os.path.basename(source)} não tem faixa de áudio.",
            "Escolha um arquivo com áudio.")

    tid = transcript_id(probe["source"], model, language, max_chars)
    if not refresh:
        cached = load_cached(tid)
        if cached:
            cached["cached"] = True
            # registros antigos não têm fingerprint, e o arquivo pode ter sido
            # movido desde a transcrição: reancora o registro no caminho atual
            # para que find_cached_by_source o encontre.
            if (cached.get("fingerprint") is None
                    or cached.get("source") != probe["source"]):
                cached["fingerprint"] = fingerprint(probe["source"])
                cached["source"] = probe["source"]
                save_cached(tid, {k: v for k, v in cached.items() if k != "cached"})
            return cached

    duration = probe.get("duration_s") or 0.0
    timeout_s = max(120.0, duration * 10.0)
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="capcut-asr-") as work:
        audio, converted = ensure_audio(probe["source"], work)
        if converted:
            obs.log("asr_audio_extracted", source=probe["source"])
        raw = _run(binary, mpath, audio, language, max_chars, threads, timeout_s,
                   os.path.join(work, "out"))
    parsed = parse_output(raw, max_block_s, max_chars)
    elapsed = time.time() - started

    result = {
        "transcript_id": tid,
        "fingerprint": fingerprint(probe["source"]),
        "source": probe["source"],
        "language": parsed["language"],
        "duration_s": duration,
        "model": model,
        "max_chars": max_chars,
        "block_count": len(parsed["blocks"]),
        "word_count": len(parsed["words"]),
        "non_speech_dropped": parsed["non_speech_dropped"],
        "blocks": parsed["blocks"],
        "words": parsed["words"],
        "elapsed_s": round(elapsed, 2),
        "realtime_factor": round(duration / elapsed, 1) if elapsed > 0 else None,
        "cached": False,
    }
    save_cached(tid, result)
    obs.log("asr_done", transcript_id=tid, model=model, blocks=len(parsed["blocks"]),
            words=len(parsed["words"]), elapsed_s=result["elapsed_s"])
    if parsed["non_speech_dropped"]:
        bus.add("NON_SPEECH_DROPPED",
                f"{len(parsed['non_speech_dropped'])} bloco(s) eram anotação de som, "
                "não fala, e foram descartados para não virar legenda na tela.",
                blocos=parsed["non_speech_dropped"][:10])
    if model in ("tiny", "base"):
        bus.add("ASR_MODEL_WEAK_PUNCTUATION",
                f"O modelo '{model}' costuma sair sem pontuação de frase, o que piora a "
                "legenda. Medido nesta máquina: 'small' pontua corretamente e ainda roda "
                "a ~8x o tempo real.", model=model)
    return result


def compact(blocks: List[Dict[str, Any]], offset: int = 0,
            limit: int = 200) -> Tuple[str, bool]:
    """Forma que o agente lê para escolher cortes, sem estourar o contexto."""
    page = blocks[offset:offset + limit]
    linhas = [f"[{b['start']:.1f}] {b['text']}" for b in page]
    return "\n".join(linhas), (offset + limit) < len(blocks)


def cached_for_source(source: str) -> List[Dict[str, Any]]:
    """Todos os transcripts em cache desta mídia, do mais desejável ao menos.

    A ordem é DETERMINÍSTICA: modelo mais forte primeiro, e entre iguais o mais
    recente. Antes o desempate era a ordem do `os.listdir`, que é do sistema de
    arquivos — com várias transcrições do mesmo arquivo em `max_chars` diferentes,
    o `from_transcript` escolhia uma arbitrária e o resultado mudava de máquina
    para máquina.
    """
    alvo = os.path.abspath(os.path.expanduser(source))
    # A identidade é o CONTEÚDO, não o caminho — é assim que o transcript_id é
    # formado. Comparar só o caminho fazia o `transcribe` responder
    # `cached: true` e o `snap` seguinte falhar com TRANSCRIPT_NOT_FOUND assim
    # que o arquivo era movido, copiado ou alcançado por outro caminho.
    try:
        fp = fingerprint(alvo)
    except OSError:
        fp = None
    ordem = list(MODELS)
    achados: List[Tuple[int, float, Dict[str, Any]]] = []
    try:
        nomes = sorted(os.listdir(CACHE_DIR))
    except OSError:
        return []
    for nome in nomes:
        if not nome.endswith(".json"):
            continue
        caminho = os.path.join(CACHE_DIR, nome)
        try:
            with open(caminho, encoding="utf-8") as f:
                data = json.load(f)
            mtime = os.path.getmtime(caminho)
        except Exception:
            continue
        mesmo_conteudo = fp is not None and data.get("fingerprint") == fp
        mesmo_caminho = os.path.abspath(str(data.get("source", ""))) == alvo
        if not (mesmo_conteudo or mesmo_caminho):
            continue
        rank = ordem.index(data["model"]) if data.get("model") in ordem else -1
        achados.append((rank, mtime, data))
    achados.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [d for _r, _m, d in achados]


def find_cached_by_source(source: str, *, max_chars: Optional[int] = None,
                          transcript_id: Optional[str] = None
                          ) -> Optional[Dict[str, Any]]:
    """Transcript em cache desta mídia.

    `transcript_id` fixa exatamente qual. `max_chars` prefere a moldagem pedida e
    só cai para outra se não houver — o que importa para as legendas, onde a
    moldagem é o que aparece na tela. Para o `snap` é indiferente: as palavras são
    as mesmas em qualquer moldagem.
    """
    candidatos = cached_for_source(source)
    if not candidatos:
        return None
    if transcript_id:
        return next((d for d in candidatos
                     if d.get("transcript_id") == transcript_id), None)
    if max_chars is not None:
        exato = [d for d in candidatos if d.get("max_chars") == max_chars]
        if exato:
            return exato[0]
    return candidatos[0]


def require_cached(source: str, *, max_chars: Optional[int] = None,
                   transcript_id: Optional[str] = None) -> Dict[str, Any]:
    data = find_cached_by_source(source, max_chars=max_chars,
                                 transcript_id=transcript_id)
    if data is None:
        if transcript_id:
            raise E.CapcutError(
                E.TRANSCRIPT_NOT_FOUND,
                f"Não há transcrição em cache com transcript_id={transcript_id}.",
                "Use o transcript_id que capcut.media.transcribe devolveu, ou "
                "omita o parâmetro para usar a transcrição mais recente.",
                source=source, transcript_id=transcript_id)
        raise E.CapcutError(
            E.TRANSCRIPT_NOT_FOUND,
            f"Não há transcrição em cache para {os.path.basename(source)}.",
            "Chame capcut.media.transcribe(source=...) antes — o resultado fica em "
            "cache e é reaproveitado aqui.",
            source=source)
    return data
