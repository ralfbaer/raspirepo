#!/usr/bin/env bash
# Startskript für den Display-Anzeiger.
#
# Zeigt den Kamerastream auf dem angeschlossenen Display und startet bei
# Bedarf den Kameradienst (webcam_stream.py) mit. Einen schon laufenden
# Dienst benutzt es unverändert mit; nur einen selbst gestarteten Dienst
# beendet es beim Verlassen wieder.
#
# Der mitgestartete Dienst läuft mit seinen Standardwerten
# (127.0.0.1:8080, ohne Passwort) — genau das, was der Anzeiger erwartet.
# Für einen abweichenden Port oder eine Netzfreigabe die beiden Programme
# getrennt starten.
#
# Argumente werden an webcam_display.py durchgereicht, z. B.
#   ./webcam_display.sh --skalierung fuellen
set -euo pipefail

hier="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="/home/baer/gitrepos/raspirepo/.venv/bin/python"

dienst_pid=""
beenden() {
  if [ -n "$dienst_pid" ]; then
    kill "$dienst_pid" 2>/dev/null || true
    wait "$dienst_pid" 2>/dev/null || true
  fi
}

if pgrep -f webcam_stream.py >/dev/null; then
  echo "webcam_stream.py läuft bereits, wird mitbenutzt."
else
  echo "Starte webcam_stream.py ..."
  "$venv" "$hier/webcam_stream.py" &
  dienst_pid=$!
  trap beenden EXIT INT TERM
  # Kurz auf den Webserver warten (Standardadresse 127.0.0.1:8080). Die
  # Prüfung läuft in einer Gruppe mit umgeleitetem stderr, weil bash die
  # Meldung eines fehlgeschlagenen /dev/tcp sonst ausgibt, bevor das
  # 2>/dev/null der exec-Zeile greift.
  for _ in $(seq 1 50); do
    if { exec 3<>/dev/tcp/127.0.0.1/8080; } 2>/dev/null; then
      exec 3>&- 3<&-
      break
    fi
    sleep 0.2
  done
fi

"$venv" "$hier/webcam_display.py" "$@"
