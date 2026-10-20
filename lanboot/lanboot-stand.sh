#!/bin/bash
# lanboot-stand.sh -- Staende verwalten: vollstaendig unabhaengige Rootfs-Varianten
# fuer die Netboot-Clients.
#
# Ein STAND ist ein kompletter, eigenstaendiger Rootfs-Baum mit eigenem Home.
# Keine Hardlinks, kein overlayfs, nichts geteilt. Jede Kopie ist vollstaendig.
#
#   netboot/<serial>                 Ursprungsstand (ohne Datum im Namen)
#   netboot/<serial>-<datum>         ein Stand
#   netboot/tftpboot/<serial> -> ../<stand>/boot/firmware
#   home/<hostname>/<stand>/baer     das Home dieses Stands
#
# Ein Stand ist EINGEFROREN, sobald kein TFTP-Symlink mehr auf ihn zeigt --
# dann schreibt niemand hinein.
#
# Umschalten ist KEIN Kopieren: zwischen bestehenden Staenden wechselt man,
# indem der Symlink umgebogen wird. Kopiert wird nur fuer einen NEUEN Stand.
#
# Erklaerung: DOKU/ARCHITEKTUR.md, Handgriffe: DOKU/HOWTO.md,
# Regeln und Fallstricke: .kiro/steering/lanboot-*.md
#
# Eigenschaften:
#   - Alles Schwere laeuft AUF DEM NAS per ssh. Es werden keine GB durchs Netz
#     des 5B geschleift.
#   - Braucht auf dem 5B KEIN sudo. Das NAS-Konto sshd hat uid 0.
#   - Loescht nichts. Zum Aufraeumen gibt es den Befehl nur als Text aus.
#   - Kopiert nie von einem laufenden Client. Bietet an, ihn herunterzufahren;
#     das Passwort fragt dann sudo auf dem Client selbst ab.
#
# Aufruf:  ./lanboot-stand.sh

set -u
umask 022

# ---------------------------------------------------------------- Konstanten

NAS_HOST=baernas
NAS_SSH="sshd@$NAS_HOST"
SSH_KEY="$HOME/.ssh/id_ed25519"
PUBKEY="$HOME/.ssh/id_ed25519.pub"

# Zwei Schreibweisen fuer dasselbe Verzeichnis: der kurze Name gilt in
# Kommandos auf dem NAS, der lange in nfsroot= und in der fstab.
NAS_KURZ=/nfs/pi
NAS_LANG=/mnt/HD/HD_a2/pi
NAS_IP=192.168.188.26               # Pflicht in nfsroot=, dort gibt es keinen Resolver

NETBOOT="$NAS_KURZ/netboot"
HOMES="$NAS_KURZ/home"
TFTP="$NETBOOT/tftpboot"
LOKAL_NETBOOT=/srv/nfs/netboot      # NAS-Mount auf dem 5B, hier nur lesend genutzt

MIN_FREI_MB=20480                   # 20 GB Reserve auf dem NAS, darunter Abbruch
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEUTE="$(date +%Y-%m-%d)"

# ---------------------------------------------------------------- Typtabelle
# Hier erweitern, wenn eine neue Pi-Generation dazukommt.

TYPEN="3b 4b 5b"

typ_bootloader() { case "$1" in 3b) echo start.elf ;; 4b|5b) echo start4.elf ;; esac; }
typ_rwsize()     { case "$1" in 3b) echo 32768     ;; 4b|5b) echo 131072    ;; esac; }
typ_dtb()        { case "$1" in 3b) echo bcm2710-rpi-3-b.dtb ;; 4b) echo bcm2711-rpi-4-b.dtb ;; 5b) echo bcm2712-rpi-5-b.dtb ;; esac; }

typ_hinweis() {
  case "$1" in
    3b) cat <<'EOT'
  - Netboot freischalten: OTP-Bit 17 muss 3020000a sein. UNUMKEHRBAR.
      vcgencmd otp_dump | grep ^17:
  - SD-Karte mit AUSSCHLIESSLICH bootcode.bin wird gebraucht, siehe HOWTO F.
    Ohne lesbare Karte startet ein 3B nicht. Kein start.elf, keine config.txt
    darauf, sonst ist der Netboot ausgehebelt.
  - Nur 100 Mbit, daher rsize/wsize 32768.
EOT
    ;;
    4b|5b) cat <<'EOT'
  - Netboot freischalten: BOOT_ORDER=0xf21 im SPI-EEPROM, umkehrbar.
      sudo raspi-config   # Advanced Options -> Boot Order -> Network Boot
  - Keine SD-Karte noetig, der Bootloader steckt im EEPROM.
  - OTP-Register 17 ist hier bedeutungslos, nicht verwechseln.
EOT
    ;;
  esac
}

# Bekannte Seriennummern, fuer Baeume ohne Markerdatei.
serial_typ_bekannt() {
  case "$1" in
    451ba057) echo 4b ;;
    bf7cac06) echo 3b ;;
    948857e5) echo 5b ;;
    *)        echo ""   ;;
  esac
}

# ---------------------------------------------------------------- Hilfsmittel

rot()  { printf '\033[31m%s\033[0m\n' "$*"; }
gruen(){ printf '\033[32m%s\033[0m\n' "$*"; }
gelb() { printf '\033[33m%s\033[0m\n' "$*"; }
fett() { printf '\033[1m%s\033[0m\n' "$*"; }
titel(){ echo; fett "$*"; printf '%s\n' "----------------------------------------------------------------"; }

abbruch() { echo; rot "Abbruch: $*"; }

# Ein ssh-Aufruf zum NAS. Absichtlich wenige, grosse Aufrufe.
#
# -n ist Pflicht und nicht Geschmack: ohne es liest ssh das stdin des Scripts
# leer, und die naechste read-Abfrage bekommt EOF. Das Menue bricht dann
# lautlos ab. Der Aufruf gibt nichts auf stdin weiter, das Kommando steht als
# Argument.
nas() {
  ssh -n -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 \
      -o StrictHostKeyChecking=accept-new "$NAS_SSH" "$1"
}

# Schreibende NAS-Kommandos laufen hierueber. Mit NAS_TROCKEN=1 werden sie nur
# gezeigt und nicht ausgefuehrt -- zum Nachsehen, was tatsaechlich gesendet
# wird, bevor Gigabytes kopiert werden. Lesende Aufrufe nutzen weiter nas().
NAS_TROCKEN=${NAS_TROCKEN:-0}

nas_schreib() {
  if [ "$NAS_TROCKEN" = 1 ]; then
    echo
    gelb "--- TROCKENLAUF, dieses Kommando liefe auf dem NAS:"
    printf '%s\n' "$1" | sed 's/^/    | /'
    return 0
  fi
  nas "$1"
}

ja_nein() {   # ja_nein "Frage" [j|n]   -> 0 = ja
  local frage="$1" vorgabe="${2:-n}" a hinweis
  [ "$vorgabe" = j ] && hinweis="[J/n]" || hinweis="[j/N]"
  read -r -p "$frage $hinweis " a
  [ -z "$a" ] && a="$vorgabe"
  case "$a" in [jJyY]*) return 0 ;; *) return 1 ;; esac
}

# Der Text einer Beschreibung laeuft durch drei Engpaesse, darum bleiben nur
# harmlose Zeichen uebrig:
#   - die Zustandstabelle ist mit | getrennt,
#   - der Marker wird auf dem NAS in einem NICHT gequoteten Heredoc
#     geschrieben, dort expandiert die dortige Shell $ und Backtick,
#   - beim Nachtragen steht der Text in einem einfach gequoteten Argument,
#     ein ' darin beendet die Quotierung mitten im Kommando.
# Zeilenumbrueche wuerden das Format key=value des Markers zerlegen.
notiz_saeubern() {
  local t="$1"
  t=${t//[$'\n\r\t']/ }
  t=${t//|/ }
  t=${t//\$/ }
  t=${t//\`/ }
  t=${t//\\/ }
  t=${t//\'/ }
  t=${t//\"/ }
  while [ "$t" != "${t//  / }" ]; do t=${t//  / }; done
  t=${t# }; t=${t% }
  printf '%s' "$t"
}

# ---------------------------------------------------------- Zustand einlesen
# Fuellt die globalen Felder. Ein einziger ssh-Aufruf.
#   STAENDE  : eine Zeile je Stand, mit | getrennt
#              name|typ|serial|hostname|angelegt|herkunft|notiz
#   LINKS    : eine Zeile je TFTP-Symlink, mit | getrennt
#              serial|zielverzeichnis
#   FREI_MB  : freier Platz auf dem NAS in MB
#
# Trenner ist |, nicht Tab. Tab gilt in bash als IFS-Whitespace, dort
# kollabieren aufeinanderfolgende Trenner zu einem und leere Felder gehen
# verloren -- bei den Urspruengen ohne Marker verrutschen dann die Spalten.

STAENDE=""; LINKS=""; FREI_MB=0

zustand_lesen() {
  local roh
  roh=$(nas '
set -u
cd '"$NETBOOT"' || exit 1
for d in */ ; do
  n=${d%/}
  [ "$n" = tftpboot ] && continue
  [ -d "$n" ] || continue
  typ=""; serial=""; host=""; ang=""; herk=""; notiz=""
  if [ -f "$n/etc/lanboot-stand" ]; then
    while IFS="=" read -r k v; do
      case "$k" in
        typ) typ=$v ;; serial) serial=$v ;; hostname) host=$v ;;
        angelegt) ang=$v ;; herkunft) herk=$v ;; notiz) notiz=$v ;;
      esac
    done < "$n/etc/lanboot-stand"
  fi
  [ -n "$host" ] || host=$(cat "$n/etc/hostname" 2>/dev/null)
  [ -n "$ang" ]  || ang=$(stat -c %y "$n" 2>/dev/null | cut -c1-16)
  printf "S|%s|%s|%s|%s|%s|%s|%s\n" "$n" "$typ" "$serial" "$host" "$ang" "$herk" "$notiz"
done
cd '"$TFTP"' || exit 1
for l in * ; do
  [ -L "$l" ] || continue
  t=$(readlink "$l")
  t=${t#../}; t=${t%/boot/firmware}
  printf "L|%s|%s\n" "$l" "$t"
done
printf "F|%s\n" "$(df -P -m '"$NAS_KURZ"' | tail -1 | awk "{print \$4}")"
') || { rot "NAS nicht erreichbar."; return 1; }

  STAENDE=$(printf '%s\n' "$roh" | awk -F'[|]' '$1=="S"{sub(/^S[|]/,""); print}')
  LINKS=$(  printf '%s\n' "$roh" | awk -F'[|]' '$1=="L"{print $2"|"$3}')
  FREI_MB=$(printf '%s\n' "$roh" | awk -F'[|]' '$1=="F"{print $2}')
  return 0
}

feld()  { printf '%s\n' "$2" | awk -F'[|]' -v n="$1" '{print $n}'; }

stand_zeile() { printf '%s\n' "$STAENDE" | awk -F'[|]' -v s="$1" '$1==s{print; exit}'; }
stand_typ()   { local z; z=$(stand_zeile "$1"); local t; t=$(feld 2 "$z")
                [ -n "$t" ] || t=$(serial_typ_bekannt "$(stand_serial "$1")")
                printf '%s\n' "$t"; }
stand_host()  { feld 4 "$(stand_zeile "$1")"; }
stand_datum() { feld 5 "$(stand_zeile "$1")"; }
stand_notiz() { feld 7 "$(stand_zeile "$1")"; }

# Serial eines Stands: aus dem Marker, sonst aus dem Verzeichnisnamen.
stand_serial() {
  local z s
  z=$(stand_zeile "$1"); s=$(feld 3 "$z")
  [ -n "$s" ] || s=$(printf '%s\n' "$1" | sed 's/-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].*$//')
  printf '%s\n' "$s"
}

# Welcher Stand ist fuer diese Serial aktiv, also verlinkt?
aktiver_stand() { printf '%s\n' "$LINKS" | awk -F'[|]' -v s="$1" '$1==s{print $2; exit}'; }

alle_serials()  { printf '%s\n' "$LINKS" | awk -F'[|]' '{print $1}' | sort; }

# Alle Staende in aufbereiteter Form, sortiert nach Typ, dann Serial, dann
# Datum. Ausgabe je Zeile:  typ|serial|stand|hostname|datum|herkunft|notiz
#
# Das Auffuellen der Felder muss VOR dem Sortieren passieren: bei den
# Urspruengen sind typ und serial in der Rohtabelle leer, weil sie keine
# Markerdatei haben. Sortiert man die Rohzeilen, landen sie alle vorn und die
# Gruppierung nach Typ geht verloren.
#
# Das Datum kommt aus zwei Quellen in zwei Formaten -- der Marker schreibt
# 2026-10-19T07:52:24, stat schreibt 2026-10-06 02:26. Einheitlich auf
# 16 Zeichen mit Leerzeichen, sonst stimmt weder Sortierung noch Spaltenbreite.
datum_norm() { printf '%s' "$1" | tr 'T' ' ' | cut -c1-16; }

staende_normiert() {
  local s typ serial host datum herk notiz
  printf '%s\n' "$STAENDE" | while IFS='|' read -r s typ serial host datum herk notiz; do
    [ -n "$s" ] || continue
    [ -n "$serial" ] || serial=$(stand_serial "$s")
    [ -n "$typ" ]    || typ=$(serial_typ_bekannt "$serial")
    printf '%s|%s|%s|%s|%s|%s|%s\n' \
      "${typ:-?}" "$serial" "$s" "$host" "$(datum_norm "$datum")" "$herk" "$notiz"
  done | sort -t'|' -k1,1 -k2,2 -k5,5
}

# Standnamen einer Serial, nach Datum sortiert (aelteste zuerst). Die
# Sortierung kommt aus staende_normiert und ist damit dieselbe wie in der
# Gesamtuebersicht 'Alle Staende' -- Typ, Serial, Datum. Frueher lief die
# Auswahl ueber die Rohreihenfolge von $STAENDE und war unsortiert.
staende_von_serial() {
  staende_normiert | awk -F'[|]' -v ser="$1" '$2==ser {print $3}'
}

# Home-Pfad eines Stands, kurze Schreibweise. Quelle der Wahrheit ist die fstab
# des Baums selbst, nicht der Marker -- so stimmt es auch bei den Urspruengen.
stand_home() {
  local roh
  roh=$(nas "awk '\$2==\"/home/baer\" && \$3==\"nfs\" {print \$1; exit}' $NETBOOT/$1/etc/fstab 2>/dev/null")
  roh=${roh#*:}
  printf '%s\n' "${roh/$NAS_LANG/$NAS_KURZ}"
}

# ---------------------------------------------------------------- motd
#
# Die motd nennt den Stand und seine Beschreibung, jedes in einer eigenen
# Zeile. Die Herkunft bleibt draussen: ein zweiter Standname in derselben
# Zeile wurde mit dem eigenen verwechselt. Sie steht in /etc/lanboot-stand.
#
# Rahmen in der Laenge der laengsten Textzeile, rechts offen -- mit zwei
# Zeilen unterschiedlicher Laenge wuerde ein rechter Abschluss ausfransen.
#
# Eine Funktion, weil drei Stellen sie schreiben: beim Anlegen eines Stands,
# beim Aendern einer Beschreibung und beim Nachziehen aller Staende. Drei
# Textbausteine wuerden auseinanderlaufen.
#
# motd_setzen <stand> <typ> <serial> [beschreibung]
#
# Die Beschreibung wird uebergeben und nicht selbst nachgeschlagen: beim
# Anlegen eines Stands steht der neue Baum noch nicht im Katalog, stand_notiz
# lieferte dort leer.
motd_setzen() {
  local stand="$1" typ="$2" serial="$3"
  local notiz
  notiz=$(notiz_saeubern "${4:-}")
  local z1 z2 breite r
  z1="=== STAND $stand  (Typ $typ, Serial $serial)"
  z2=""
  [ -n "$notiz" ] && z2="=== $notiz"
  breite=${#z1}
  [ "${#z2}" -gt "$breite" ] && breite=${#z2}
  r=$(printf '%*s' "$breite" '' | tr ' ' '=')
  if [ -n "$z2" ]; then
    nas_schreib "printf '\n%s\n%s\n%s\n%s\n\n' '$r' '$z1' '$z2' '$r' > $NETBOOT/$stand/etc/motd"
  else
    nas_schreib "printf '\n%s\n%s\n%s\n\n' '$r' '$z1' '$r' > $NETBOOT/$stand/etc/motd"
  fi
}

# ------------------------------------------------------------- Beschreibung
#
# Im Marker heisst das Feld weiter 'notiz=', und die Funktionsnamen folgen dem
# Feld. Nach aussen -- in jedem Text, den ein Mensch liest -- heisst es
# Beschreibung. Das Feld umzubenennen wuerde alle bestehenden Marker brechen.
#
# stand_notiz_setzen <stand> <text>
#
# Setzt die notiz-Zeile im Marker eines bestehenden Stands. Gebraucht wird das
# beim Einfrieren: der Text beschreibt, was in dem Baum steckt, und das weiss
# man erst in dem Moment, in dem man ihn verlaesst.
#
# Hat der Baum noch keinen Marker -- so sind die Ursprungsstaende aus der Zeit
# vor dem Stand-Verfahren -- wird ein vollstaendiger angelegt. Die Felder
# kommen aus dem Baum selbst und aus der Typtabelle, nicht aus Annahmen.
stand_notiz_setzen() {
  local stand="$1"
  local text
  text=$(notiz_saeubern "$2")
  local m="$NETBOOT/$stand/etc/lanboot-stand"
  local typ serial host home_kurz home_lang

  if nas "[ -f $m ]"; then
    # Marker vorhanden: NUR die notiz-Zeile anfassen, alles andere bleibt
    # stehen. awk -v statt einer sed-Substitution, sonst waere der Text Teil
    # des Ausdrucks und jedes & oder | darin wuerde etwas anderes bedeuten.
    # Fehlt die Zeile, haengt der END-Block sie an.
    nas_schreib "set -e
      M=$m
      T=\$(mktemp)
      awk -v n='$text' '
        /^notiz=/ { print \"notiz=\" n; gesehen=1; next }
        { print }
        END { if (!gesehen) print \"notiz=\" n }
      ' \$M > \$T
      cat \$T > \$M && rm -f \$T
      chmod 644 \$M" || { rot "  Beschreibung an $stand nicht geschrieben."; return 1; }
    return 0
  fi

  serial=$(stand_serial "$stand")
  typ=$(stand_typ "$stand")
  [ -n "$typ" ] || typ=$(serial_typ_bekannt "$serial")
  [ -n "$typ" ] || { rot "  Typ von $stand unbekannt, kein Marker angelegt."; return 1; }
  host=$(stand_host "$stand")
  [ -n "$host" ] || host=$(nas "cat $NETBOOT/$stand/etc/hostname 2>/dev/null")
  home_kurz=$(stand_home "$stand")
  [ -n "$home_kurz" ] || { rot "  Home von $stand nicht aus der fstab lesbar."; return 1; }
  home_lang=${home_kurz/$NAS_KURZ/$NAS_LANG}

  echo "  $stand hat keinen Marker, es wird einer angelegt."
  # angelegt kommt aus der Verzeichniszeit, nicht aus heute -- der Baum ist
  # aelter als dieser Eintrag. Format wie beim Anlegen eines Stands.
  # herkunft bleibt leer: ein Ursprungsstand ist aus keinem anderen kopiert.
  nas_schreib "set -e
    A=\$(stat -c %y $NETBOOT/$stand | cut -c1-19 | tr ' ' 'T')
    cat > $m <<MARK
typ=$typ
serial=$serial
stand=$stand
hostname=$host
home=$home_lang
angelegt=\$A
herkunft=
notiz=$text
MARK
    chmod 644 $m" || { rot "  Marker an $stand nicht geschrieben."; return 1; }
  return 0
}

# ------------------------------------------------------------- Client-Zustand

client_laeuft() { ping -c1 -W2 "$1" >/dev/null 2>&1; }

# Sorgt dafuer, dass der Client aus ist. Fragt, fahrt auf Wunsch herunter.
# Das sudo-Passwort fragt der Client selbst ab, es wird hier nie angefasst.
client_stilllegen() {
  local host="$1" i
  if ! client_laeuft "$host"; then
    echo "  $host antwortet nicht, ist also aus. Gut."
    return 0
  fi
  echo
  gelb "  $host LAEUFT."
  cat <<EOT
  Eine Kopie eines laufenden Systems ist inkonsistent: dpkg-Datenbank, Journal
  und offene Dateien sind mitten im Schreiben. Der Client muss aus sein.
EOT
  # Im Trockenlauf wird auch der Client nicht angefasst. Ohne das hier wuerde
  # ein Lauf, der nur zum Ansehen gedacht ist, eine laufende Maschine
  # ausschalten -- das ist schon passiert.
  if [ "$NAS_TROCKEN" = 1 ]; then
    echo
    gelb "--- TROCKENLAUF, hier wuerde der Client heruntergefahren:"
    echo "    | ssh -t baer@$host 'sudo systemctl poweroff'"
    echo "    | danach warten, bis er nicht mehr antwortet"
    echo "  Der Ablauf laeuft weiter, als waere er aus."
    return 0
  fi

  if ja_nein "  Jetzt herunterfahren? sudo auf $host fragt dann nach dem Passwort." j; then
    echo
    ssh -t -o ConnectTimeout=10 "baer@$host" 'sudo systemctl poweroff' || true
    echo
    printf '  warte, bis %s aus ist ' "$host"
    for i in $(seq 1 24); do
      sleep 5
      printf '.'
      if ! client_laeuft "$host"; then
        echo
        gruen "  $host ist aus."
        sleep 3
        return 0
      fi
    done
    echo
    abbruch "$host antwortet nach 120 Sekunden noch. Nicht kopiert."
    return 1
  fi
  abbruch "Quell-Client laeuft, es wird nicht kopiert."
  return 1
}

# ---------------------------------------------------------------- Platzpruefung

# platz_pruefen <stand> <homepfad>  -> 0 = genug Platz
platz_pruefen() {
  local stand="$1" home="$2" braucht rest
  printf '  ermittle Groesse von %s ... ' "$stand"
  braucht=$(nas "du -sm $NETBOOT/$stand $home 2>/dev/null | awk '{s+=\$1} END{print s+0}'")
  echo "${braucht} MB"
  rest=$(( FREI_MB - braucht ))
  printf '  frei auf dem NAS: %s MB, danach: %s MB\n' "$FREI_MB" "$rest"
  if [ "$rest" -lt "$MIN_FREI_MB" ]; then
    abbruch "danach blieben unter $MIN_FREI_MB MB frei."
    return 1
  fi
  return 0
}

# ------------------------------------------------------------- Namensfindung

# Freier Standname fuer eine Serial: <serial>-<datum>, bei Kollision -2, -3, ...
freier_standname() {
  local serial="$1" kand="$1-$HEUTE" n=2
  while printf '%s\n' "$STAENDE" | awk -F'[|]' '{print $1}' | grep -qx "$kand"; do
    kand="$serial-$HEUTE-$n"
    n=$(( n + 1 ))
  done
  printf '%s\n' "$kand"
}

# ------------------------------------------------------------ Stand anlegen
#
# stand_anlegen <quellstand> <zielserial> <zielhost> <neues_geraet 0|1> <notiz>
#
# Legt eine vollstaendige, unabhaengige Kopie an: Rootfs UND Home.
# Biegt nfsroot, rsize/wsize und den Home-Pfad der fstab um, schreibt den
# Marker, prueft nach. Setzt ZIEL_STAND fuer den Aufrufer.

ZIEL_STAND=""

stand_anlegen() {
  local quelle="$1" zserial="$2" zhost="$3" neu="$4" notiz="$5"
  local typ bl rw qhome zhome zhome_lang ziel qhost ergebnis home_modus=kopie

  notiz=$(notiz_saeubern "$notiz")

  typ=$(stand_typ "$quelle")
  [ -n "$typ" ] || { rot "Typ von $quelle unbekannt."; return 1; }
  bl=$(typ_bootloader "$typ")
  rw=$(typ_rwsize "$typ")
  qhost=$(stand_host "$quelle")
  ziel=$(freier_standname "$zserial")
  qhome=$(stand_home "$quelle")
  [ -n "$qhome" ] || { rot "Home-Pfad von $quelle nicht aus der fstab lesbar."; return 1; }
  zhome="$HOMES/$zhost/$ziel/baer"
  zhome_lang="$NAS_LANG/home/$zhost/$ziel/baer"

  if [ "$neu" = 1 ]; then
    echo
    echo "  Das Home der Vorlage ($qhome) kann mitkopiert werden -- dann ist"
    echo "  die authorized_keys gleich dabei -- oder es wird ein leeres Home"
    echo "  aus /etc/skel angelegt."
    ja_nein "  Home der Vorlage mitkopieren?" j || home_modus=leer
  fi

  titel "Vorhaben"
  cat <<EOT
  Quelle Rootfs   $NETBOOT/$quelle
  Quelle Home     $qhome
  Ziel Rootfs     $NETBOOT/$ziel
  Ziel Home       $zhome   ($home_modus)
  Typ             $typ   Bootloader $bl   rsize/wsize $rw
  Serial          $zserial
  Hostname        $zhost
  TFTP-Symlink    $TFTP/$zserial -> ../$ziel/boot/firmware
EOT
  [ "$neu" = 1 ] && echo "  Identitaet        machine-id und SSH-Hostkeys werden zurueckgesetzt"
  echo

  # --- Quell-Client stilllegen, falls die Quelle gerade gebootet wird
  local aktiv_jetzt
  aktiv_jetzt=$(aktiver_stand "$(stand_serial "$quelle")")
  if [ "$aktiv_jetzt" = "$quelle" ] && [ -n "$qhost" ]; then
    titel "Quell-Client"
    echo "  $quelle ist der aktive Stand von $qhost."
    client_stilllegen "$qhost" || return 1
  else
    echo "  Quelle $quelle ist nicht verlinkt, wird also von niemandem gebootet."
  fi

  # --- Platz
  titel "Platz"
  platz_pruefen "$quelle" "$qhome" || return 1

  ja_nein "Kopieren? Das dauert auf dem NAS mehrere Minuten." n \
    || { abbruch "auf Wunsch."; return 1; }

  # --- Rootfs kopieren, auf dem NAS
  titel "Rootfs kopieren"
  echo "  cp -a auf dem NAS, kein Byte laeuft ueber den 5B. Bitte warten."
  local t0 t1
  t0=$(date +%s)
  nas_schreib "set -e
       [ -e $NETBOOT/$ziel ] && { echo 'ZIEL EXISTIERT'; exit 1; }
       cp -a $NETBOOT/$quelle $NETBOOT/$ziel
       echo fertig" || { abbruch "cp des Rootfs fehlgeschlagen."; return 1; }
  t1=$(date +%s)
  gruen "  Rootfs kopiert in $(( t1 - t0 )) s."

  # --- Home anlegen
  titel "Home anlegen"
  local pub
  pub=$(cat "$PUBKEY" 2>/dev/null)
  [ -n "$pub" ] || { rot "$PUBKEY nicht lesbar."; return 1; }

  if [ "$home_modus" = kopie ]; then
    nas_schreib "set -e
         mkdir -p $HOMES/$zhost/$ziel
         cp -a $qhome $zhome
         echo fertig" || { abbruch "cp des Home fehlgeschlagen."; return 1; }
  else
    nas_schreib "set -e
         mkdir -p $zhome
         cp -a $NETBOOT/$ziel/etc/skel/. $zhome/ 2>/dev/null || true
         echo fertig" || { abbruch "Anlegen des Home fehlgeschlagen."; return 1; }
  fi

  gruen "  Home kopiert nach $zhome."

  # --- Anpassungen im Baum
  titel "Anpassungen im neuen Baum"

  local ident=""
  if [ "$neu" = 1 ]; then
    ident="
    printf '%s\n' '$zhost' > \$R/etc/hostname
    sed -i 's/$qhost/$zhost/g' \$R/etc/hosts
    : > \$R/etc/machine-id
    rm -f \$R/etc/ssh/ssh_host_*
    if [ -f \$R/var/lib/dbus/machine-id ] && [ ! -L \$R/var/lib/dbus/machine-id ]; then
      : > \$R/var/lib/dbus/machine-id
    fi
    echo '  Identitaet getrennt: hostname, hosts, machine-id, ssh_host_*'"
  fi

  nas_schreib "set -eu
    R=$NETBOOT/$ziel
    C=\$R/boot/firmware/cmdline.txt

    # nfsroot auf das eigene Verzeichnis. Das Komma begrenzt den Pfad, damit
    # trifft das Muster nur die Pfadangabe und nichts sonst.
    sed -i 's|nfsroot=$NAS_IP:$NAS_LANG/netboot/[^,]*,|nfsroot=$NAS_IP:$NAS_LANG/netboot/$ziel,|' \$C
    sed -i 's|rsize=[0-9]*|rsize=$rw|; s|wsize=[0-9]*|wsize=$rw|' \$C

    # Home-Pfad in der fstab. Hier darf der Name stehen, diesen Mount macht
    # der Userspace. awk statt sed, damit nur die richtige Zeile angefasst wird.
    F=\$R/etc/fstab
    T=\$(mktemp)
    awk -v neu='$NAS_HOST:$zhome_lang' '
      \$2==\"/home/baer\" && \$3==\"nfs\" { printf \"%s  %s  %s  %s  %s  %s\n\", neu,\$2,\$3,\$4,\$5,\$6; next }
      { print }
    ' \$F > \$T
    cat \$T > \$F && rm -f \$T

    $ident

    # Marker: beantwortet im laufenden System die Frage 'wo bin ich'.
    cat > \$R/etc/lanboot-stand <<MARK
typ=$typ
serial=$zserial
stand=$ziel
hostname=$zhost
home=$zhome_lang
angelegt=$(date +%Y-%m-%dT%H:%M:%S)
herkunft=$quelle
notiz=$notiz
MARK
    echo '  cmdline.txt, fstab und Marker gesetzt'
  " || { abbruch "Anpassungen fehlgeschlagen."; return 1; }

  motd_setzen "$ziel" "$typ" "$zserial" "$notiz" || { abbruch "motd fehlgeschlagen."; return 1; }
  echo '  motd gesetzt'

  # --- Rechte am Home. Bewusst NACH Marker und motd: scheitert hier etwas --
  # etwa chown an toten venv-Symlinks --, ist die Beschreibung des Stands
  # bereits geschrieben und geht nicht verloren. Frueher stand dieser Block vor
  # dem Marker; ein chown-Fehler hat damals die Beschreibung verschluckt.
  titel "Rechte am Home"
  # authorized_keys sicherstellen -- ihr Fehlen war in diesem Projekt schon
  # die Ursache fuer 'Permission denied' bei einem einwandfrei gebooteten Client.
  nas_schreib "set -e
       mkdir -p $zhome/.ssh
       if [ ! -s $zhome/.ssh/authorized_keys ]; then
         printf '%s\n' '$pub' > $zhome/.ssh/authorized_keys
       fi
       chmod 755 $HOMES/$zhost/$ziel
       chmod 700 $zhome/.ssh
       chmod 600 $zhome/.ssh/authorized_keys
       # -h: den Symlink selbst chownen, nicht sein Ziel. Ein venv enthaelt
       # Symlinks auf System-Python; ohne -h scheitert chown an toten Links
       # und bricht das Anlegen ab.
       chown -Rh 1000:1000 $HOMES/$zhost/$ziel
       echo fertig" || { abbruch "Rechte am Home fehlgeschlagen."; return 1; }
  gruen "  Rechte am Home gesetzt."

  # --- Pruefen
  titel "Pruefung des neuen Stands"
  ergebnis=$(nas "
    exec 2>/dev/null          # fehlende Dateien melden die Pruefungen selbst
    R=$NETBOOT/$ziel
    C=\$R/boot/firmware/cmdline.txt
    G=\$R/boot/firmware/config.txt
    fehler=0
    pr() { if [ \"\$1\" = ok ]; then printf '  ok    %s\n' \"\$2\"; else printf '  FEHLT %s\n' \"\$2\"; fehler=1; fi; }

    grep -q 'nfsroot=$NAS_IP:$NAS_LANG/netboot/$ziel,' \$C && pr ok 'nfsroot zeigt auf den eigenen Baum' || pr nein 'nfsroot zeigt auf den eigenen Baum'
    grep -q 'rsize=$rw,wsize=$rw' \$C && pr ok 'rsize/wsize = $rw' || pr nein 'rsize/wsize = $rw'
    zeilen=\$(awk 'END{print NR}' \$C)
    [ \"\${zeilen:-99}\" -le 1 ] && pr ok 'cmdline.txt ist eine Zeile' || pr nein 'cmdline.txt ist eine Zeile'
    [ -c \$R/dev/console ] && pr ok '/dev/console als Device-Node' || pr nein '/dev/console als Device-Node'
    [ -c \$R/dev/null ] && pr ok '/dev/null als Device-Node' || pr nein '/dev/null als Device-Node'
    # Nur ein vorhandenes config.txt ohne wirksame Zeile ist ein ok. Eine
    # fehlende Datei darf nicht als Entwarnung durchgehen.
    if [ ! -f \$G ]; then pr nein 'config.txt vorhanden'
    elif grep -q '^[[:space:]]*auto_initramfs' \$G; then pr nein 'kein wirksames auto_initramfs'
    else pr ok 'kein wirksames auto_initramfs'; fi
    [ -f \$R/boot/firmware/$bl ] && pr ok 'Bootloader $bl vorhanden' || pr nein 'Bootloader $bl vorhanden'
    grep -q '^Package: nfs-common' \$R/var/lib/dpkg/status && pr ok 'nfs-common installiert' || pr nein 'nfs-common installiert'
    grep -q '$zhome_lang' \$R/etc/fstab && pr ok 'fstab zeigt auf das eigene Home' || pr nein 'fstab zeigt auf das eigene Home'
    [ -s $zhome/.ssh/authorized_keys ] && pr ok 'authorized_keys im Home' || pr nein 'authorized_keys im Home'
    printf 'HOSTNAME %s\n' \"\$(cat \$R/etc/hostname)\"
    printf 'FEHLER %s\n' \"\$fehler\"
  ")
  printf '%s\n' "$ergebnis" | grep -v '^FEHLER\|^HOSTNAME'
  printf '  hostname im Baum: %s\n' "$(printf '%s\n' "$ergebnis" | awk '/^HOSTNAME/{print $2}')"

  if [ "$(printf '%s\n' "$ergebnis" | awk '/^FEHLER/{print $2}')" != 0 ]; then
    echo
    rot "  Mindestens eine Pruefung ist fehlgeschlagen."
    echo "  Der Stand $ziel bleibt liegen, der Symlink wird NICHT umgebogen."
    echo "  Nach der Analyse von Hand aufraeumen:"
    echo "    ssh $NAS_SSH 'rm -rf $NETBOOT/$ziel $HOMES/$zhost/$ziel'"
    return 1
  fi
  gruen "  Alle Pruefungen bestanden."

  ZIEL_STAND="$ziel"
  return 0
}

# ------------------------------------------------------------- Umschalten

# umschalten <serial> <stand>
umschalten() {
  local serial="$1" stand="$2" typ bl alt
  typ=$(stand_typ "$stand")
  [ -n "$typ" ] || typ=$(serial_typ_bekannt "$serial")
  bl=$(typ_bootloader "$typ")
  alt=$(aktiver_stand "$serial")

  titel "Umschalten"
  cat <<EOT
  $TFTP/$serial
     bisher  -> ../${alt:-"(kein Symlink)"}/boot/firmware
     neu     -> ../$stand/boot/firmware
EOT
  # Keine Rueckfrage an dieser Stelle. Die Menuepunkte sagen zu, dass
  # umgeschaltet wird, und der Block 'Vorhaben' nennt den Symlink vor der
  # einzigen Bestaetigung der Aktion. Zweimal nach derselben Entscheidung zu
  # fragen hilft niemandem.
  #
  # Was bleibt, ist keine Frage, sondern eine Sicherung: zeigt der Symlink auf
  # einen Baum, der nicht bootet, startet der Client nicht mehr.
  nas "set -e
       [ -f $NETBOOT/$stand/boot/firmware/$bl ] || { echo 'Bootloader $bl fehlt im Ziel'; exit 1; }
       grep -q 'netboot/$stand,' $NETBOOT/$stand/boot/firmware/cmdline.txt || { echo 'nfsroot im Ziel zeigt NICHT auf $stand'; exit 1; }
      " || { abbruch "Ziel ist nicht bootbar, Symlink unveraendert."; return 1; }

  nas_schreib "set -e
       ln -sfn ../$stand/boot/firmware $TFTP/$serial
       printf 'jetzt: %s -> %s\n' $serial \"\$(readlink $TFTP/$serial)\"" \
    || { abbruch "Symlink konnte nicht gesetzt werden."; return 1; }
  gruen "  Umgeschaltet."
  echo
  echo "  Ein laufender Client merkt davon nichts, er haelt keine Verbindung"
  echo "  zum 5B. Wirksam wird es beim naechsten Start."
  [ "$typ" = 3b ] && gelb "  3B: Karte mit bootcode.bin muss stecken."
  echo "  Rueckweg, jederzeit:"
  echo "    ssh $NAS_SSH 'ln -sfn ../${alt:-ALT}/boot/firmware $TFTP/$serial'"
  return 0
}

# ------------------------------------------------------------- Repo-Export
#
# Git kann die Rootfs-Baeume nicht tragen: keine Device-Nodes, keine uid/gid,
# kein setuid, keine Hardlinks. Ins Repo kommen darum nur Artefakte je Stand:
# die drei Dateien, die man von Hand anfasst, und die Paketliste. Damit ist
# ein Vergleich zweier Staende ein diff und kein Durchgang durch 74 000 Dateien.
#
# Was hier bewusst NICHT entsteht, ist eine Zustandsuebersicht. Eine Datei,
# die den aktuellen Stand behauptet, ist veraltet, sobald sie geschrieben ist,
# sieht aber amtlich aus -- und verleitet dazu, sie zu zitieren statt zu
# messen. Der Zustand kommt aus Menuepunkt 1 oder aus den Pruefkommandos.

repo_export_stand() {
  # Getrennte Zuweisungen: 'local a=.. b=$a' sieht a noch nicht, weil local
  # erst alle Namen anlegt und dann zuweist. Unter set -u ist das ein Fehler.
  local stand="$1"
  local q="$LOKAL_NETBOOT/$stand"
  local n=0
  [ -d "$q" ] || { gelb "  $stand lokal nicht sichtbar, uebersprungen."; return 0; }

  if [ -r "$q/boot/firmware/cmdline.txt" ]; then
    cp "$q/boot/firmware/cmdline.txt" "$REPO/stand-$stand-cmdline.txt" && n=$((n+1))
  fi
  if [ -r "$q/boot/firmware/config.txt" ]; then
    cp "$q/boot/firmware/config.txt" "$REPO/stand-$stand-config.txt" && n=$((n+1))
  fi
  if [ -r "$q/etc/fstab" ]; then
    cp "$q/etc/fstab" "$REPO/stand-$stand-fstab" && n=$((n+1))
  fi
  # Der Marker traegt die Beschreibung. Damit liegt der Kommentar zu einem Stand
  # versioniert im Repo und nicht nur auf dem NAS.
  if [ -r "$q/etc/lanboot-stand" ]; then
    cp "$q/etc/lanboot-stand" "$REPO/stand-$stand-marker" && n=$((n+1))
  fi
  if [ -r "$q/var/lib/dpkg/status" ]; then
    awk '
      /^Package: /{p=$2}
      /^Version: /{v=$2}
      /^Status: /{s=$2" "$3" "$4}
      /^$/{ if (s=="install ok installed" && p!="") printf "%s\t%s\n", p, v; p="";v="";s="" }
      END{ if (s=="install ok installed" && p!="") printf "%s\t%s\n", p, v }
    ' "$q/var/lib/dpkg/status" | sort > "$REPO/stand-$stand-pakete.txt" && n=$((n+1))
  fi
  printf '  %s: %s Dateien ins Repo\n' "$stand" "$n"
}

repo_export() {
  titel "Repo-Export"
  local s
  for s in "$@"; do repo_export_stand "$s"; done
  echo
  echo "  Committen tust du, nicht das Script:"
  echo "    cd $REPO && git status --short"
}

# ------------------------------------------------------------------ Aktionen

aktion_zustand() {
  titel "Aktive Zuordnung"
  printf '  %-10s %-16s %s\n' Serial Hostname "aktiver Stand"
  printf '%s\n' "$LINKS" | while IFS='|' read -r serial s; do
    [ -n "$serial" ] || continue
    printf '  %-10s %-16s %s\n' "$serial" "$(stand_host "$s")" "$s"
  done

  titel "Alle Staende, nach Typ"
  printf '  %-4s %-26s %-10s %-16s %-16s %s\n' Typ Stand Serial Hostname angelegt Zustand
  local s typ serial host datum herk notiz z
  staende_normiert | while IFS='|' read -r typ serial s host datum herk notiz; do
    if [ "$(aktiver_stand "$serial")" = "$s" ]; then z="AKTIV"; else z="eingefroren"; fi
    printf '  %-4s %-26s %-10s %-16s %-16s %s\n' "$typ" "$s" "$serial" "${host:--}" "${datum:--}" "$z"
    [ -n "$notiz" ] && printf '  %-4s %s\n' "" "$notiz"
  done

  titel "Platz"
  printf '  NAS frei: %s MB (%s GB)\n' "$FREI_MB" "$(( FREI_MB / 1024 ))"

  titel "Clients"
  local h
  printf '%s\n' "$LINKS" | while IFS='|' read -r serial s; do
    [ -n "$serial" ] || continue
    h=$(stand_host "$s")
    [ -n "$h" ] || continue
    if client_laeuft "$h"; then printf '  %-16s laeuft\n' "$h"; else printf '  %-16s aus\n' "$h"; fi
  done
}

# Auswahl eines Stands aus einer Liste. Ergebnis in GEWAEHLT.
GEWAEHLT=""
# stand_waehlen <liste> <frage> [pingen 0|1]
#
# Mit pingen=1 steht hinter einem aktiven Stand, ob sein Geraet gerade
# antwortet. Gebraucht wird das nur beim Aufnehmen eines neuen Raspi: wird
# dort ein laufender Stand als Vorlage gewaehlt, muss sein Client
# herunterfahren, und das trifft ein Geraet, um das es gar nicht ging.
# Standardmaessig aus, weil jeder nicht antwortende Host die Liste um die
# zwei Sekunden Ping-Timeout verzoegert.
stand_waehlen() {
  local liste="$1" frage="$2"
  local pingen="${3:-0}"
  local i=1 n a s z notiz host
  GEWAEHLT=""
  echo
  # Die Beschreibung steht mit in der Liste. Sie ist der Grund, aus dem man
  # einen Stand auswaehlt -- der Verzeichnisname sagt nur, an welchem Tag er
  # entstanden ist, und an einem Tag koennen mehrere entstehen.
  printf '%s\n' "$liste" | while read -r s; do
    [ -n "$s" ] || continue
    if [ "$(aktiver_stand "$(stand_serial "$s")")" = "$s" ]; then
      z="AKTIV"
      if [ "$pingen" = 1 ]; then
        host=$(stand_host "$s")
        [ -n "$host" ] && client_laeuft "$host" && z="AKTIV, $host laeuft"
      fi
    else
      z="eingefroren"
    fi
    printf '  %2d) %-26s %-16s %s\n' "$i" "$s" "$(datum_norm "$(stand_datum "$s")")" "$z"
    notiz=$(stand_notiz "$s")
    [ -n "$notiz" ] && printf '      %s\n' "$notiz"
    i=$(( i + 1 ))
  done
  n=$(printf '%s\n' "$liste" | grep -c .)
  echo
  read -r -p "$frage [1-$n, leer = Abbruch] " a
  [ -z "$a" ] && return 1
  case "$a" in *[!0-9]*) return 1 ;; esac
  [ "$a" -ge 1 ] && [ "$a" -le "$n" ] || return 1
  GEWAEHLT=$(printf '%s\n' "$liste" | grep . | sed -n "${a}p")
  return 0
}

# Auswahl eines Geraets. Ergebnis in GEWAEHLT_SERIAL.
GEWAEHLT_SERIAL=""
geraet_waehlen() {
  local i=1 n a serial s
  GEWAEHLT_SERIAL=""
  echo
  for serial in $(alle_serials); do
    # Kein aktiver Stand in dieser Zeile. Hier wird das Geraet gewaehlt, nicht
    # der Stand; die Standnamen liessen die Liste wie eine Standauswahl
    # aussehen. Die Aktionen nennen den aktiven Stand gleich danach selbst.
    s=$(aktiver_stand "$serial")
    printf '  %2d) %-10s %s\n' "$i" "$serial" "$(stand_host "$s")"
    i=$(( i + 1 ))
  done
  n=$(alle_serials | grep -c .)
  echo
  read -r -p "Welches Geraet? [1-$n, leer = Abbruch] " a
  [ -z "$a" ] && return 1
  case "$a" in *[!0-9]*) return 1 ;; esac
  [ "$a" -ge 1 ] && [ "$a" -le "$n" ] || return 1
  GEWAEHLT_SERIAL=$(alle_serials | sed -n "${a}p")
  return 0
}

# --- Neuen Raspi aufnehmen
aktion_neuer_raspi() {
  local typ i=1 n a serial host liste notiz

  titel "Neuen Raspi aufnehmen"
  echo "  Welcher Typ?"
  echo
  for typ in $TYPEN; do
    printf '  %2d) %s   (Bootloader %s, rsize/wsize %s)\n' "$i" "$typ" "$(typ_bootloader "$typ")" "$(typ_rwsize "$typ")"
    i=$(( i + 1 ))
  done
  n=$(printf '%s\n' $TYPEN | grep -c .)
  echo
  read -r -p "Typ? [1-$n, leer = Abbruch] " a
  [ -z "$a" ] && return 0
  case "$a" in *[!0-9]*) return 0 ;; esac
  [ "$a" -ge 1 ] && [ "$a" -le "$n" ] || return 0
  typ=$(printf '%s\n' $TYPEN | sed -n "${a}p")

  # Staende dieses Typs als Vorlage
  liste=$(printf '%s\n' "$STAENDE" | awk -F'[|]' '{print $1}' | while read -r s; do
            [ -n "$s" ] || continue
            [ "$(stand_typ "$s")" = "$typ" ] && printf '%s\n' "$s"
          done)
  if [ -z "$(printf '%s\n' "$liste" | grep .)" ]; then
    rot "  Kein Stand des Typs $typ vorhanden, es fehlt eine Vorlage."
    return 1
  fi
  echo
  echo "  Welcher Stand soll als Vorlage dienen?"
  echo "  Steht hinter einem Stand, dass sein Geraet laeuft, muss dieses Geraet"
  echo "  zum Kopieren herunterfahren. Ein eingefrorener Stand kostet das nicht."
  stand_waehlen "$liste" "Vorlage?" 1 || { echo "  Abbruch."; return 0; }
  local quelle="$GEWAEHLT"

  # Seriennummer
  echo
  echo "  Seriennummer des neuen Raspi, acht Hex-Ziffern klein."
  echo "  Auf dem Geraet:  grep Serial /proc/cpuinfo | cut -c19-26"
  echo "  Oder im Log des 5B:  journalctl -u dnsmasq -f"
  while :; do
    read -r -p "  Seriennummer? [leer = Abbruch] " serial
    [ -z "$serial" ] && return 0
    case "$serial" in
      [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
      *) rot "  Genau acht Zeichen 0-9a-f erwartet."; continue ;;
    esac
    if printf '%s\n' "$LINKS" | awk -F'[|]' '{print $1}' | grep -qx "$serial"; then
      rot "  Fuer $serial gibt es schon einen TFTP-Symlink. Nimm Menuepunkt 3-1 oder 3-2."
      continue
    fi
    break
  done

  # Hostname
  echo
  while :; do
    read -r -p "  Hostname des neuen Raspi? [leer = Abbruch] " host
    [ -z "$host" ] && return 0
    case "$host" in
      [a-z0-9]*) ;;
      *) rot "  Klein anfangen, nur a-z 0-9 und Bindestrich."; continue ;;
    esac
    case "$host" in
      *[!a-z0-9-]*) rot "  Nur a-z 0-9 und Bindestrich." ; continue ;;
    esac
    if [ "$host" = "$(stand_host "$quelle")" ]; then
      rot "  Das ist der Hostname der Vorlage. Der neue Raspi braucht einen eigenen."
      continue
    fi
    break
  done

  read -r -p "  Beschreibung des neuen Stands? [leer = keine] " notiz
  [ -n "$notiz" ] || notiz="neu aufgenommen, aus $quelle"

  stand_anlegen "$quelle" "$serial" "$host" 1 "$notiz" || return 1

  zustand_lesen || return 1
  umschalten "$serial" "$ZIEL_STAND" || true
  # Nach dem Umschalten noch einmal lesen, sonst traegt der Katalog den alten
  # Symlink ein.
  zustand_lesen || return 1
  repo_export "$ZIEL_STAND"

  titel "Was jetzt noch von Hand zu tun ist"
  typ_hinweis "$typ"
  cat <<EOT
  - Reservierung in der Fritz!Box ist empfohlen, aber nicht zwingend.
    An dnsmasq und der Fritz!Box aendert sich fuer einen neuen Client NICHTS.
  - Beim ersten SSH-Zugriff den Hostkey sauber pruefen, HOWTO Abschnitt D3:
      ssh-keyscan -t ed25519 $host | ssh-keygen -lf -
      ssh $NAS_SSH 'cat $NETBOOT/$ZIEL_STAND/etc/ssh/ssh_host_ed25519_key.pub'
    Die Hostkeys sind geloescht, ssh-keygen -A erzeugt sie beim ersten Start neu.
  - Danach pruefen, dass er wirklich vom Netz laeuft:
      ssh baer@$host 'findmnt -no SOURCE,FSTYPE /; cat /etc/lanboot-stand'
EOT
}

# --- Kopie des Arbeitsstandes anlegen und darauf umschalten.
# Hier entsteht ein neuer Stand, also wird vollstaendig kopiert: Rootfs und Home.
aktion_kopie() {
  local serial quelle host notiz vorgabe ziel_name

  titel "Kopie des Arbeitsstandes anlegen"
  echo "  Es wird eine vollstaendige Kopie des aktiven Stands angelegt und"
  echo "  darauf umgeschaltet. Der bisherige Stand ist danach eingefroren,"
  echo "  weil kein Symlink mehr auf ihn zeigt."

  geraet_waehlen || { echo "  Abbruch."; return 0; }
  serial="$GEWAEHLT_SERIAL"
  quelle=$(aktiver_stand "$serial")
  echo
  echo "  Aktiver Stand von $serial: $quelle"
  host=$(stand_host "$quelle")

  # Die Beschreibung gehoert der KOPIE, die hier entsteht. Der Stand, den man
  # verlaesst, behaelt seine eigene -- er ist eingefroren, in einen
  # eingefrorenen Baum wird nicht geschrieben. Nachbessern laesst sich eine
  # Beschreibung jederzeit mit Menuepunkt 3-3.
  #
  # Gefragt wird hier, VOR dem Herunterfahren des Clients und vor dem cp.
  # Nach Minuten Wartezeit noch eine Eingabe zu verlangen, ist eine Zumutung.
  #
  # Der Name der Kopie wird dafuer schon hier bestimmt, obwohl stand_anlegen
  # ihn selbst ermittelt. Beide Aufrufe lesen dieselbe, zwischenzeitlich nicht
  # neu eingelesene Staendeliste und liefern deshalb dasselbe.
  ziel_name=$(freier_standname "$serial")
  vorgabe="Kopie von $quelle"
  titel "Beschreibung der Kopie"
  echo "  Du verlaesst $quelle und arbeitest ab dem naechsten Start in"
  echo "  der Kopie mit dem Namen $ziel_name."
  echo
  read -r -p "  Beschreibung der Kopie? [leer = $vorgabe] " notiz
  [ -n "$notiz" ] || notiz="$vorgabe"

  stand_anlegen "$quelle" "$serial" "$host" 0 "$notiz" || return 1

  zustand_lesen || return 1
  umschalten "$serial" "$ZIEL_STAND" || true
  # Nach dem Umschalten noch einmal lesen, sonst traegt der Katalog den alten
  # Symlink ein.
  zustand_lesen || return 1
  repo_export "$ZIEL_STAND"

  titel "Nach dem Start pruefen"
  cat <<EOT
  ssh baer@$host 'findmnt -no SOURCE /; findmnt -no SOURCE /home/baer; cat /etc/lanboot-stand'
EOT
  echo
  echo "  Aufraeumen erst, wenn du sicher bist. Das Script loescht nichts."
  echo "  Groessen ansehen:"
  echo "    ssh $NAS_SSH 'du -sh $NETBOOT/$serial-*'"
}

# --- Zwischen bestehenden Staenden umschalten.
#
# Umschalten ist kein Kopieren. Die Staende sind bereits vollstaendige,
# voneinander unabhaengige Baeume mit eigenem Home; welchen ein Geraet bootet,
# entscheidet allein der TFTP-Symlink. Es wird daher nichts angelegt und
# nichts veraendert ausser diesem einen Symlink.
aktion_zurueck() {
  local serial aktiv liste stand host

  titel "Auf einen Arbeitsstand zurueckfallen"
  cat <<'EOT'
  Es wird nur der TFTP-Symlink umgebogen. Keine Kopie, es wird nichts angelegt.
  Ab dem naechsten Start arbeitet das Geraet in dem gewaehlten Stand und
  schreibt in dessen Rootfs und dessen Home. Der Stand, den du verlaesst,
  bleibt stehen wie er ist -- du kannst jederzeit zurueckwechseln.
EOT

  geraet_waehlen || { echo "  Abbruch."; return 0; }
  serial="$GEWAEHLT_SERIAL"
  aktiv=$(aktiver_stand "$serial")

  echo
  fett "  Du bist auf:  $aktiv"
  printf '                %s   %s\n' \
    "$(datum_norm "$(stand_datum "$aktiv")")" "$(stand_notiz "$aktiv")"

  # Angeboten wird nur, wohin es tatsaechlich etwas umzuschalten gibt. Der
  # aktive Stand steht oben als Standortangabe, nicht als Auswahl.
  liste=$(staende_von_serial "$serial" | grep -vx "$aktiv")
  if [ "$(printf '%s\n' "$liste" | grep -c .)" -lt 1 ]; then
    echo
    rot "  Fuer $serial gibt es keinen anderen Stand."
    echo "  Einen neuen anlegen: Menuepunkt 3-1."
    return 0
  fi

  echo
  echo "  Umschalten auf:"
  stand_waehlen "$liste" "Wohin?" || { echo "  Abbruch."; return 0; }
  stand="$GEWAEHLT"

  umschalten "$serial" "$stand" || return 1

  host=$(stand_host "$stand")
  if [ -n "$host" ] && client_laeuft "$host"; then
    echo
    gelb "  $host laeuft noch im alten Stand und schreibt weiter dorthin."
    echo "    ssh baer@$host 'sudo systemctl poweroff'    # fragt nach dem Passwort"
  fi

  titel "Nach dem Start pruefen"
  echo "  ssh baer@${host:-<client>} 'findmnt -no SOURCE /; findmnt -no SOURCE /home/baer; cat /etc/lanboot-stand'"
}

# --- Beschreibung eines Stands nachtraeglich aendern.
#
# Geaendert wird genau eine Zeile im Marker des Baums, sonst nichts. Das ist
# fuer jeden Stand erlaubt, auch fuer den aktiven: eine Beschreibung ist ein
# Kommentar und hat auf den Betrieb keine Wirkung. Sie ist auch der Grund,
# aus dem man in Menuepunkt 3-2 einen Stand auswaehlt -- der Verzeichnisname
# nennt nur den Tag, an dem er entstanden ist.
aktion_beschreibung() {
  local serial stand liste alt neu
  # Zwei Dateien im Baum, beide reine Anzeige: /etc/lanboot-stand und
  # /etc/motd. Rootfs, Home, Symlink und Name bleiben unberuehrt.

  titel "Beschreibung aendern"
  cat <<'EOT'
  Geaendert werden zwei Anzeigedateien im Baum: die notiz-Zeile in
  /etc/lanboot-stand und /etc/motd. Am Rootfs, am Home, am TFTP-Symlink und am
  Namen des Stands aendert sich nichts; der Stand bootet unveraendert weiter.
EOT

  geraet_waehlen || { echo "  Abbruch."; return 0; }
  serial="$GEWAEHLT_SERIAL"
  liste=$(staende_von_serial "$serial")
  if [ "$(printf '%s\n' "$liste" | grep -c .)" -lt 1 ]; then
    echo
    rot "  Fuer $serial gibt es keinen Stand."
    return 1
  fi

  echo
  echo "  Welchen Stand willst du beschreiben?"
  stand_waehlen "$liste" "Welcher Stand?" || { echo "  Abbruch."; return 0; }
  stand="$GEWAEHLT"

  alt=$(stand_notiz "$stand")
  echo
  printf '  Stand    %s\n' "$stand"
  printf '  bisher   %s\n' "${alt:--}"
  echo
  read -r -p "  Neue Beschreibung? [leer = unveraendert] " neu
  if [ -z "$neu" ]; then
    echo
    echo "  Unveraendert."
    return 0
  fi
  neu=$(notiz_saeubern "$neu")

  titel "Schreiben"
  stand_notiz_setzen "$stand" "$neu" || return 1
  # Die motd zeigt die Beschreibung mit an. Bliebe sie stehen, widersprachen
  # sich motd und Marker im eingeloggten System.
  motd_setzen "$stand" "$(stand_typ "$stand")" "$(stand_serial "$stand")" "$neu" \
    || { rot "  motd nicht geschrieben, der Marker ist aber gesetzt."; }
  gruen "  $stand: $neu"

  # Neu einlesen, damit die Anzeige stimmt, und ins Repo nachziehen -- der
  # Marker ist eines der Artefakte.
  zustand_lesen || return 1
  repo_export "$stand"
}

# Ursprungsstand: Verzeichnisname ohne Datum, also einer der Baeume von vor
# der Einfuehrung der Staende. Sie sind der dokumentierte Rueckweg.
stand_ist_ursprung() {
  case "$1" in
    *-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

# Zeigt irgendein TFTP-Symlink auf diesen Stand?
stand_ist_verlinkt() {
  printf '%s\n' "$LINKS" | awk -F'[|]' -v s="$1" '$2==s{f=1} END{exit !f}'
}

# --- Stand loeschen. Die einzige unumkehrbare Aktion dieses Scripts.
aktion_loeschen() {
  local serial stand liste zhome home_dir groessen mb_baum mb_home a

  titel "Stand loeschen"
  cat <<'EOT'
  Die einzige unumkehrbare Aktion dieses Scripts. Angeboten werden nur
  eingefrorene Staende; der aktive, von dem ein Geraet bootet, taucht nicht
  auf. Bestaetigt wird durch Eintippen des Standnamens, nicht mit j.
EOT

  geraet_waehlen || { echo "  Abbruch."; return 0; }
  serial="$GEWAEHLT_SERIAL"

  liste=$(staende_von_serial "$serial" | grep -vx "$(aktiver_stand "$serial")")
  if [ "$(printf '%s\n' "$liste" | grep -c .)" -lt 1 ]; then
    rot "  Fuer $serial gibt es ausser dem aktiven Stand keinen weiteren."
    echo "  Es ist also nichts zu loeschen."
    return 0
  fi

  stand_waehlen "$liste" "Welchen Stand loeschen?" || { echo "  Abbruch."; return 0; }
  stand="$GEWAEHLT"

  # Doppelter Boden, auch wenn die Liste ihn gar nicht angeboten haette.
  if stand_ist_verlinkt "$stand"; then
    abbruch "auf $stand zeigt ein TFTP-Symlink. Wird nicht geloescht."
    return 1
  fi

  # Gehoert das Home zu diesem Stand? Entscheidend ist nicht der Name, sondern
  # ob der Pfad aus der fstab den Standnamen als eigenes Segment enthaelt. Bei
  # den Urspruengen ist es das gemeinsame home/<hostname>/baer -- das bleibt.
  zhome=$(stand_home "$stand")
  case "$zhome" in
    */"$stand"/baer) home_dir="${zhome%/baer}" ;;
    *)               home_dir="" ;;
  esac

  titel "Was weggeht"
  printf '  ermittle Groessen ... '
  groessen=$(nas "du -sm $NETBOOT/$stand ${home_dir} 2>/dev/null | awk '{print \$1}'")
  mb_baum=$(printf '%s\n' "$groessen" | sed -n 1p)
  mb_home=$(printf '%s\n' "$groessen" | sed -n 2p)
  echo fertig
  echo
  printf '  Stand          %s\n' "$stand"
  printf '  Typ / Serial   %s / %s\n' "$(stand_typ "$stand")" "$serial"
  printf '  Hostname       %s\n' "$(stand_host "$stand")"
  local herk notiz
  herk=$(feld 6 "$(stand_zeile "$stand")")
  notiz=$(stand_notiz "$stand")
  printf '  angelegt       %s   aus %s\n' "$(stand_datum "$stand")" "${herk:--}"
  printf '  Beschreibung   %s\n' "${notiz:--}"
  echo
  printf '  Rootfs         %s\n' "$NETBOOT/$stand"
  printf '                 %s MB   wird GELOESCHT\n' "${mb_baum:-?}"
  if [ -n "$home_dir" ]; then
    printf '  Home           %s\n' "$home_dir"
    printf '                 %s MB   wird GELOESCHT, samt allem darin\n' "${mb_home:-?}"
  else
    printf '  Home           %s\n' "$zhome"
    gelb "                 bleibt stehen, es ist NICHT standbezogen"
  fi

  if stand_ist_ursprung "$stand"; then
    echo
    gelb "  ACHTUNG: $stand ist ein Ursprungsstand."
    cat <<'EOT'
  Sein Name traegt kein Datum, er stammt aus der Zeit vor den Staenden und ist
  der dokumentierte Rueckweg fuer dieses Geraet. Sein Home ist das gemeinsame
  Home des Geraets, nicht eine Standkopie -- darin liegen Schluessel und
  known_hosts. Es wird deshalb nicht angefasst. Der Baum aber schon, und
  danach gibt es keinen Rueckweg mehr.
EOT
  fi

  echo
  echo "  Zum Loeschen den Standnamen genau eintippen."
  read -r -p "  Name? [leer = Abbruch] " a
  if [ "$a" != "$stand" ]; then
    abbruch "Name stimmt nicht ueberein, nichts geloescht."
    return 1
  fi

  # Letzte Pruefung unmittelbar vor dem rm, direkt an den Symlinks auf dem NAS.
  # Der Zustand im Script kann veraltet sein; ein Client, dessen Symlink auf
  # einen geloeschten Baum zeigt, startet nicht mehr.
  nas_schreib "set -e
    for l in $TFTP/* ; do
      [ -L \"\$l\" ] || continue
      case \"\$(readlink \"\$l\")\" in
        */$stand/boot/firmware) echo 'VERLINKT, wird nicht geloescht'; exit 1 ;;
      esac
    done
    rm -rf $NETBOOT/$stand ${home_dir}
    [ -e $NETBOOT/$stand ] && { echo 'Baum ist noch da'; exit 1; }
    echo 'geloescht'" || { abbruch "Loeschen fehlgeschlagen."; return 1; }

  gruen "  $stand ist weg."

  # Die abgeleiteten Textdateien gehen mit. Sie schreibt das Script selbst,
  # und sie beschreiben einen Stand, den es nicht mehr gibt.
  #
  # Die Endungen werden einzeln aufgezaehlt und NICHT als stand-<name>-*
  # geglobt: 'stand-451ba057-2026-10-19-' ist ein Praefix von
  # 'stand-451ba057-2026-10-19-2-cmdline.txt'. Ein Glob wuerde beim Loeschen
  # des kurzen Stands die Dateien des Zaehler-Stands mitnehmen.
  #
  # Wer hier eine Endung ergaenzt, muss sie auch in repo_export_stand
  # ergaenzen, und umgekehrt -- sonst bleiben Waisen im Repo liegen.
  titel "Abgeleitete Dateien im Repo"
  local endung f anzahl=0
  for endung in cmdline.txt config.txt fstab pakete.txt marker; do
    f="$REPO/stand-$stand-$endung"
    [ -e "$f" ] || continue
    if [ "$NAS_TROCKEN" = 1 ]; then
      printf '  TROCKENLAUF wuerde loeschen  %s\n' "${f##*/}"
    else
      rm -f "$f" && printf '  geloescht  %s\n' "${f##*/}"
    fi
    anzahl=$(( anzahl + 1 ))
  done
  [ "$anzahl" = 0 ] && echo "  keine vorhanden"

  echo
  echo "  Waren die Dateien schon committet, zeigt git sie als geloescht an:"
  echo "    cd $REPO && git status --short"
  return 0
}

# --- motd aller Staende erneuern. Aendert in jedem Baum genau eine Datei:
# /etc/motd. Sonst nichts. Wiederholbar, auch nach einer Formataenderung.
#
# Absichtlich NICHT in Punkt 4-1: der ist auf dem NAS rein lesend, und das soll
# so bleiben.
aktion_motd() {
  titel "motd aller Staende erneuern"
  echo "  Geaendert wird in jedem Baum nur /etc/motd."
  echo
  local typ serial s host datum herk notiz
  staende_normiert | while IFS='|' read -r typ serial s host datum herk notiz; do
    if motd_setzen "$s" "$typ" "$serial" "$notiz"; then
      printf '  ok     %s\n' "$s"
    else
      printf '  FEHLER %s\n' "$s"
    fi
  done
}

aktion_export_alle() {
  local alle
  alle=$(printf '%s\n' "$STAENDE" | awk -F'[|]' '{print $1}' | grep .)
  # shellcheck disable=SC2086
  repo_export $alle
}

# ------------------------------------------------------------------ Menues
#
# Zwei Stufen. Die Aktionen selbst wissen davon nichts, sie werden nur von
# einer anderen Stelle aufgerufen. 'zustand_lesen' bleibt vor jeder Aktion
# stehen: eine Aktion darf nie mit einem Katalog arbeiten, der noch aus der
# Zeit vor der vorigen Aktion stammt.
#
# 0 und die leere Eingabe fuehren im Untermenue zurueck, nicht aus dem Script.

untermenue_staende() {
  local a
  while :; do
    echo
    fett "---- Arbeitsstaende"
    cat <<'EOT'

  1) Kopie des Arbeitsstandes anlegen      (Kopie des aktiven Stands, darauf umschalten)
  2) Auf einen Arbeitsstand zurueckfallen  (Auf eine Sicherung zurueckfallen)
  3) Beschreibung aendern                  (nur der Kommentar, kein Baum wird angefasst)
  4) Stand loeschen                        (nur eingefrorene, unumkehrbar)
  0) zurueck

EOT
    read -r -p "Auswahl? " a
    case "$a" in
      1) zustand_lesen && aktion_kopie ;;
      2) zustand_lesen && aktion_zurueck ;;
      3) zustand_lesen && aktion_beschreibung ;;
      4) zustand_lesen && aktion_loeschen ;;
      0|q|Q|"") return 0 ;;
      *) rot "Unbekannt." ;;
    esac
  done
}

untermenue_pflege() {
  local a
  while :; do
    echo
    fett "---- Pflege"
    cat <<'EOT'

  1) Repo-Export aller Staende nachziehen  (liest nur, schreibt ins Repo)
  2) motd aller Staende erneuern           (Anzeige nach dem Starten des Geraetes)
  0) zurueck

EOT
    read -r -p "Auswahl? " a
    case "$a" in
      1) zustand_lesen && aktion_export_alle ;;
      2) zustand_lesen && aktion_motd ;;
      0|q|Q|"") return 0 ;;
      *) rot "Unbekannt." ;;
    esac
  done
}

hauptmenue() {
  local a
  while :; do
    echo
    fett "================================================================"
    fett " lanboot-stand -- Staende der Netboot-Clients"
    fett "================================================================"
    cat <<'EOT'

  1) Zustand zeigen
  2) Neuen Raspi aufnehmen                 (Typ und Serial erfragen, Kopie, Symlink)
  3) Arbeitsstaende                        (anlegen, wechseln, beschreiben, loeschen)
  4) Pflege                                (Repo-Export, motd)
  0) Ende

EOT
    read -r -p "Auswahl? " a
    case "$a" in
      1) zustand_lesen && aktion_zustand ;;
      2) zustand_lesen && aktion_neuer_raspi ;;
      3) untermenue_staende ;;
      4) untermenue_pflege ;;
      0|q|Q|"") echo; return 0 ;;
      *) rot "Unbekannt." ;;
    esac
  done
}

# ------------------------------------------------------------------ Start

[ -r "$SSH_KEY" ] || { rot "SSH-Schluessel $SSH_KEY nicht lesbar."; exit 1; }
[ -r "$PUBKEY" ]  || { rot "Oeffentlicher Schluessel $PUBKEY nicht lesbar."; exit 1; }
nas 'true' >/dev/null 2>&1 || { rot "NAS $NAS_SSH nicht erreichbar."; exit 1; }

hauptmenue
