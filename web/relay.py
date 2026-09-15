"""Modo relay: o motor local LIGA PARA FORA e puxa trabalho do app hospedado.

## Por que o sentido é invertido

O Chrome 142+ bloqueia uma página de origem pública que chama `127.0.0.1`
(Local Network Access), e a falha é **silenciosa** — medido: a requisição nem
chega ao motor, e não há erro no console. Em vez de pedir permissão em cada
navegador, aqui a conexão é de saída: o motor pergunta ao relay se há trabalho.
Nenhuma requisição da página vai para a rede local.

## O vídeo não sobe

O motor informa o **inventário** da pasta de entrada (nomes, tamanho, duração).
A UI mostra essa lista e devolve só o caminho escolhido. O arquivo fica no disco
de quem o gravou.

Uso:

    CAPCUT_RELAY=https://capcut-front.vercel.app \\
    CAPCUT_MAQUINA=mac-do-mateus \\
    CAPCUT_RELAY_TOKEN=<>=24 caracteres> \\
    ANTHROPIC_API_KEY=sk-ant-... \\
      PYTHONPATH=src ./.venv/bin/python web/relay.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import app as motor                                        # noqa: E402
from capcut_mcp import errors as E, media, obs, tools       # noqa: E402

RELAY = (os.environ.get("CAPCUT_RELAY") or "").rstrip("/")
MAQUINA = os.environ.get("CAPCUT_MAQUINA") or ""
TOKEN = os.environ.get("CAPCUT_RELAY_TOKEN") or ""
ENTRADA = os.path.expanduser(os.environ.get("CAPCUT_ENTRADA", "~/CapCut Entrada"))

INTERVALO_OCIOSO = 3.0
INTERVALO_ERRO = 10.0
EXTENSOES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".mp3", ".wav", ".m4a"}
LOTE_EVENTOS = 12          # agrupa antes de subir, para não fazer um POST por linha


def fala(*partes: Any) -> None:
    print(time.strftime("[%H:%M:%S]"), *partes, flush=True)


def http(rota: str, carga: Dict[str, Any], tentativas: int = 3) -> Dict[str, Any]:
    corpo = json.dumps(carga).encode()
    req = urllib.request.Request(
        RELAY + rota, data=corpo, method="POST",
        headers={"Content-Type": "application/json"})
    ultimo: Optional[Exception] = None
    for n in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detalhe = (exc.read() or b"").decode()[:300]
            # 4xx é erro nosso: repetir não conserta
            if 400 <= exc.code < 500:
                raise RuntimeError(f"{rota} -> {exc.code}: {detalhe}") from exc
            ultimo = RuntimeError(f"{rota} -> {exc.code}: {detalhe}")
        except Exception as exc:
            ultimo = exc
        time.sleep(1.5 * (n + 1))
    raise ultimo or RuntimeError("falha desconhecida")


# ------------------------------------------------------------- inventário
def inventario() -> List[Dict[str, Any]]:
    """O que existe na pasta de entrada. Sem isto a UI não tem o que oferecer."""
    if not os.path.isdir(ENTRADA):
        return []
    fora = []
    for nome in sorted(os.listdir(ENTRADA)):
        if nome.startswith("."):
            continue
        caminho = os.path.join(ENTRADA, nome)
        if not os.path.isfile(caminho):
            continue
        if os.path.splitext(nome)[1].lower() not in EXTENSOES:
            continue
        item = {"nome": nome, "caminho": caminho,
                "bytes": os.path.getsize(caminho)}
        try:                            # duração é o que o operador quer ver
            p = media.probe(caminho)
            item.update(duracao_s=p.get("duration_s"), tipo=p.get("kind"),
                        tem_audio=p.get("has_audio"))
        except E.CapcutError:
            item["tipo"] = "ilegível"
        fora.append(item)
    return fora[:80]


def estado() -> Dict[str, Any]:
    bus = obs.WarningBus()
    try:
        d = tools.TOOLS["capcut.system.doctor"]["handler"]({}, bus)
    except E.CapcutError as exc:
        return {"pronto": False, "erro": exc.message}
    return {"pronto": bool(d.get("ready")),
            "capcut": d.get("capcut_app_version"),
            "whisper": bool(d.get("whisper_cli")),
            "disco_gib": d.get("free_disk_gib"),
            "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "modelo": motor.MODEL,
            "entrada": ENTRADA}


# ------------------------------------------------------------ execução
class Envio:
    """Junta eventos e sobe em lote, sem perder o último se der erro."""

    def __init__(self, job_id: int) -> None:
        self.job_id, self.fila = job_id, []

    def add(self, ev: Dict[str, Any]) -> None:
        self.fila.append(ev)
        if len(self.fila) >= LOTE_EVENTOS:
            self.descarrega()

    def descarrega(self, estado_final: Optional[str] = None) -> None:
        if not self.fila and estado_final is None:
            return
        carga = {"maquina": MAQUINA, "token": TOKEN, "job_id": self.job_id,
                 "eventos": self.fila}
        if estado_final:
            carga["estado_final"] = estado_final
        try:
            http("/api/agente/evento", carga)
            self.fila = []
        except Exception as exc:
            fala("  ! não consegui subir eventos:", exc)


def resultado_util(nome: str, saida: Dict[str, Any]) -> tuple:
    """A tool respondeu, mas a resposta diz que está tudo bem?

    Devolve (útil, motivo). Existe porque `ok` significa "a chamada não
    levantou", e duas tools devolvem ok=True carregando a má notícia dentro:
    o `media.probe` põe o arquivo ilegível em `failed`, e o `system.doctor`
    traz `ready: False`.
    """
    d = saida.get("data") or {}
    if nome == "capcut.media.probe":
        falhos = d.get("failed") or []
        if falhos or not (d.get("probed") or []):
            alvo = falhos[0] if falhos else {}
            return False, (f"Não consegui ler a mídia: "
                           f"{alvo.get('error') or alvo.get('source') or 'arquivo ausente'}")
    if nome == "capcut.system.doctor" and not d.get("ready"):
        faltas = []
        if not d.get("capcut_app_version"):
            faltas.append("CapCut não encontrado")
        if not d.get("reference_project"):
            faltas.append("sem projeto de referência criado à mão")
        if not d.get("ffprobe"):
            faltas.append("ffprobe ausente")
        return False, "Máquina não está pronta: " + (", ".join(faltas) or "veja o doctor")
    return True, ""


def roda_diagnostico(job: Dict[str, Any], envio: Envio) -> str:
    """Job que NÃO usa a LLM: prova o relay de ponta a ponta sem gastar token.

    Existe porque a transporte é a parte nova e arriscada; o loop do agente já
    tem testes próprios. Também é o que responde "o relay chegou na máquina?".
    """
    fonte = job.get("fonte")
    passos = [("capcut_system_doctor", {})]
    if fonte:
        passos.append(("capcut_media_probe", {"sources": [fonte]}))
    for nome_api, args in passos:
        nome = motor.de_api(nome_api)
        envio.add({"tipo": "tool_inicio", "nome": nome})
        t0 = time.time()
        saida = motor.executa_tool(nome_api, args)
        # `ok` da tool não basta: o media.probe devolve ok=True com o arquivo
        # ilegível dentro de `failed`, e o doctor devolve ok=True com
        # ready=False. Um diagnóstico que passa nesses casos não diagnostica
        # nada — o check verde tem de significar algo.
        util, porque = resultado_util(nome, saida)
        envio.add({"tipo": "tool_fim", "nome": nome, "ok": saida["ok"] and util,
                   "ms": int((time.time() - t0) * 1000),
                   "resumo": porque or motor.resumo_da_tool(nome, saida),
                   "avisos": saida.get("warnings", [])})
        if not saida["ok"]:
            envio.add({"tipo": "erro", "texto": saida["error"]["message"]})
            return "erro"
        if not util:
            envio.add({"tipo": "erro", "texto": porque})
            return "erro"
    envio.add({"tipo": "texto", "texto": "Diagnóstico concluído: o relay chegou "
                                         "nesta máquina e as tools respondem."})
    return "ok"


def roda_agente(job: Dict[str, Any], envio: Envio) -> str:
    pedido = job.get("prompt") or ""
    anexos = [job["fonte"]] if job.get("fonte") else []
    sessao = f"relay-{job['id']}"
    estado_final = "ok"
    for ev in motor.conversa(sessao, pedido, anexos):
        envio.add(ev)
        if ev.get("tipo") == "erro":
            estado_final = "erro"
    return estado_final


def atende(job: Dict[str, Any]) -> None:
    fala(f"job {job['id']} ({job['tipo']}):", (job.get("prompt") or "")[:70]
         or job.get("fonte") or "")
    envio = Envio(job["id"])
    try:
        if job["tipo"] == "diagnostico":
            final = roda_diagnostico(job, envio)
        else:
            final = roda_agente(job, envio)
    except Exception as exc:
        obs.log("relay_job_crash", job=job["id"], erro=repr(exc))
        envio.add({"tipo": "erro", "texto": f"{type(exc).__name__}: {exc}"})
        final = "erro"
    envio.descarrega(estado_final=final)
    fala(f"job {job['id']} terminou:", final)


def principal() -> int:
    if not (RELAY and MAQUINA and TOKEN):
        print(__doc__)
        print("Falta configurar: " + ", ".join(
            n for n, v in (("CAPCUT_RELAY", RELAY), ("CAPCUT_MAQUINA", MAQUINA),
                           ("CAPCUT_RELAY_TOKEN", TOKEN)) if not v))
        return 2
    if len(TOKEN) < 24:
        print("CAPCUT_RELAY_TOKEN precisa de ao menos 24 caracteres.")
        return 2

    os.makedirs(ENTRADA, exist_ok=True)
    fala(f"máquina '{MAQUINA}' falando com {RELAY}")
    fala(f"pasta de entrada: {ENTRADA}")
    est = estado()
    if not est.get("pronto"):
        fala("ATENÇÃO: esta máquina não está pronta —", est.get("erro", "veja o doctor"))
    if not est.get("api_key"):
        fala("ATENÇÃO: sem ANTHROPIC_API_KEY, só jobs de diagnóstico funcionam.")

    espera = INTERVALO_OCIOSO
    while True:
        try:
            r = http("/api/agente/batida", {
                "maquina": MAQUINA, "token": TOKEN,
                "estado": estado(), "inventario": inventario()})
            espera = INTERVALO_OCIOSO
            job = r.get("job")
            if job:
                atende(job)
                continue                  # pode haver outro na fila
        except KeyboardInterrupt:
            fala("encerrando")
            return 0
        except Exception as exc:
            fala("batida falhou:", str(exc)[:200])
            espera = INTERVALO_ERRO
        time.sleep(espera)


if __name__ == "__main__":
    try:
        sys.exit(principal())
    except KeyboardInterrupt:
        sys.exit(0)
