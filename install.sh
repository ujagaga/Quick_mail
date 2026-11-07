#!/bin/sh
set -e
cd "$(dirname "$0")"
# System site packages give the venv access to the system GTK bindings (gi).
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
