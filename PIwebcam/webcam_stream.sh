#!/usr/bin/env bash
# Startskript für den Webcam-Dienst.
#
# Startet webcam_stream.py über das gemeinsame venv. Alle übergebenen
# Argumente werden durchgereicht, zum Beispiel:
#   ./webcam_stream.sh --host 0.0.0.0
#
# Der Aufruf mit dem absoluten Pfad zum Programm sorgt dafür, dass das
# Projektverzeichnis in sys.path liegt und der Import von submodule.
# funktioniert, egal aus welchem Verzeichnis gestartet wird.
set -euo pipefail

hier="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="/home/baer/gitrepos/raspirepo/.venv/bin/python"

exec "$venv" "$hier/webcam_stream.py" "$@"
