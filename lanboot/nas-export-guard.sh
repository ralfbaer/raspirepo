#!/bin/bash
# Stellt sicher, dass die no_root_squash-Exporte auf dem NAS vorhanden sind.
#
# Hintergrund: Die Firmware des WD My Cloud EX2 Ultra schreibt /etc/exports
# neu, sobald in der Weboberflaeche eine Netzwerk- oder Share-Einstellung
# geaendert wird, und beim Firmware-Update. Unsere zusaetzlichen Zeilen
# verschwinden dabei. Ohne sie verliert der Netboot-Client sein
# Root-Dateisystem - und zwar mitten im Betrieb.
#
# Dieses Skript prueft die Zeilen und setzt sie bei Bedarf zurueck.

set -u

KEY=/home/baer/.ssh/id_ed25519
NAS=sshd@baernas
NETZ=192.168.188.0/24
OPTS="$NETZ(rw,sync,no_wdelay,no_root_squash,no_subtree_check,insecure,insecure_locks)"

ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new "$NAS" "
changed=0
for d in netboot home; do
  if ! grep -q \"/nfs/pi/\$d\\\"\" /etc/exports; then
    printf '%s\n' \"\\\"/nfs/pi/\$d\\\" $OPTS\" >> /etc/exports
    changed=1
  fi
done
if [ \"\$changed\" = 1 ]; then
  exportfs -ra && echo 'WIEDERHERGESTELLT: Exportzeilen fehlten und wurden neu gesetzt'
else
  echo 'OK: Exportzeilen vorhanden'
fi
"
