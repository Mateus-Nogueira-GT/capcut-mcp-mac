#!/bin/sh
# Sobe o motor local autorizando a UI hospedada.
# A allowlist é de origem EXATA — preview da Vercel tem outro domínio e não passa.
cd "$(dirname "$0")/.." || exit 1
export CAPCUT_ALLOW_ORIGIN="${CAPCUT_ALLOW_ORIGIN:-https://capcut-front.vercel.app}"
export PYTHONPATH=src
exec ./.venv/bin/python web/app.py
