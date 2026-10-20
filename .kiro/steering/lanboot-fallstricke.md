---
inclusion: fileMatch
fileMatchPattern: 'lanboot/**'
---

# Fallstricke und Prüfkommandos

Diese Datei wird geladen, sobald an `lanboot/` gearbeitet wird. Jeder Eintrag ist am Gerät gemessen, nicht
abgeschrieben; wo eine Angabe aus einer Messung stammt, steht die Methode dabei.

**Vor jeder Aussage über den Zustand die Prüfkommandos ausführen, nicht diese Datei
zitieren.**

---

## Zustand messen

```bash
# Welcher Stand ist wo aktiv, was gibt es, wie viel Platz
cd ~/gitrepos/raspirepo/lanboot && ./lanboot-stand.sh      # Menuepunkt 1

# oder direkt
ssh sshd@baernas 'ls -l /nfs/pi/netboot/tftpboot/; ls -d /nfs/pi/netboot/*/; df -h /mnt/HD/HD_a2'
```

```bash
# Server
systemctl is-active dnsmasq nas-export-guard.timer
systemctl list-timers nas-export-guard.timer
grep pxe-service /etc/dnsmasq.d/pxe.conf | sed 's/$/|/'   # | markiert das Ende
journalctl -u dnsmasq -f

# NAS-Mounts des 5B -- findmnt nimmt nur EIN Ziel je Aufruf
for m in /srv/nfs/netboot /srv/nfs/home; do findmnt -no SOURCE,FSTYPE "$m" || echo "$m fehlt"; done

# Exportzeilen, zwei erwartet
sudo /usr/local/sbin/nas-export-guard.sh
ssh sshd@baernas 'grep no_root_squash /etc/exports; exportfs -v'

# In welchem Stand laeuft ein Client? Das ist der einzige Nachweis.
ssh baer@<client> 'findmnt -no SOURCE,FSTYPE /; findmnt -no SOURCE /home/baer; cat /etc/lanboot-stand'

# TFTP. NICHT ueber den eigenen Namen, siehe unten.
curl -s -o /tmp/t tftp://127.0.0.1/<serial>/cmdline.txt && cat /tmp/t
ssh baer@<client> 'curl -s -o /tmp/t tftp://raspberrypi5/<serial>/start4.elf; md5sum /tmp/t'

# Kernel und TFTP-Auslieferung identisch?
ssh baer@<client> 'md5sum /boot/firmware/kernel8.img'
sudo md5sum /srv/nfs/netboot/tftpboot/<serial>/kernel8.img

# Laeuft ein Client aus dem erwarteten Baum? Unabhaengig von SSH-Vertrauen.
ssh-keyscan -t ed25519 <client> | ssh-keygen -lf -
ssh sshd@baernas 'cat /nfs/pi/netboot/<stand>/etc/ssh/ssh_host_ed25519_key.pub' > /tmp/k.pub && ssh-keygen -lf /tmp/k.pub

# OTP-Zustand eines 3B -- nur beim Pi 3 aussagekraeftig
ssh baer@<client> 'vcgencmd otp_dump | grep ^17:'   # 3020000a = Netboot frei

# Startvorgaenge zaehlen, nicht DHCP-Runden
journalctl -u dnsmasq --since today | grep -cE 'sent.*(start4.elf|start.elf)'

# Platz. Ein volles / auf dem 5B legt den Bootserver still.
df -h /
ssh sshd@baernas 'df -h /mnt/HD/HD_a2'
```

---

## Bootkette

### Der Boot-String braucht genau 17 Zeichen

```
pxe-service=0,"Raspberry Pi Boot"
```

**Ohne** angehängte Leerzeichen. Die Raspberry-Pi-Doku behauptet unter „Known problems",
das BootROM brauche drei zusätzliche Leerzeichen — der im **selben** Dokument abgedruckte
funktionierende Paketmitschnitt hat sie nicht. Für dnsmasq gilt der Mitschnitt: dnsmasq
baut Option 43 selbst und setzt das Längenfeld korrekt. Die drei Leerzeichen gehören nur in
Konfigurationen, in denen man das Feld von Hand zusammensetzt, etwa ISC dhcpd.

Kontrolle im Log, `log-dhcp` muss dafür aktiv sein:

```
richtig:  option: 43 vendor-encap  06:01:03:0a:04:00:50:58:45:09:14:00:00:11...
                                                                  ^^ 0x11 = 17
falsch:   option: 43 vendor-encap  06:01:03:0a:04:00:50:58:45:09:17:00:00:14...
                                                                  ^^ 0x14 = 20
```

### bootcode.bin gehört in die TFTP-Wurzel

Das BootROM des Pi 3 holt `bootcode.bin` **ohne** Präfix aus der Wurzel. Erst das geladene
`bootcode.bin` versucht `<serial>/start.elf`, und ab da bekommen alle weiteren Dateien das
Präfix. Liegt die Datei nur im Seriennummer-Verzeichnis, passiert nichts.

Pi 4 und 5 brauchen kein `bootcode.bin`, bei ihnen steckt der Bootloader im SPI-EEPROM. Der
Pi 4 verwendet `start4.elf` und `fixup4.dat` statt `start.elf` und `fixup.dat`.

### Der Netboot-ROM des Pi 3B ist defekt, die Abhilfe ist eine SD-Karte

Beim 3B steckt der Netboot-Code in der Maskenmaske des Chips und ist nicht aktualisierbar.
Dokumentierte, erst im 3B+ behobene Fehler: Abbruch nach fünf DHCP-Versuchen, fehlerhafte
Längenberechnung des Boot-Strings, kein DHCPREQUEST, abbrechende ARP-Antworten mitten in
TFTP-Übertragungen, TFTP-Server in anderem Subnetz nicht unterstützt.

Gemessen am 18.10.2026 vormittags, als der 3B noch rein per ROM startete: drei Versuche,
zwei Fehlschläge, ein Erfolg. Die DHCP-Antworten des Servers waren dabei byteweise
identisch — also eine Wettlaufsituation im ROM, nichts Konfigurierbares. Nachmittags
brauchte ein Neustart vier Versuche.

Seit dem 18.10.2026 steckt im 3B eine SD-Karte mit ausschließlich `bootcode.bin`, 52 624
Bytes, FAT32, Label `BOOTCODE`. Belegt am Protokollvergleich zweier Startvorgänge desselben
Geräts:

```
14:05, ohne Karte:  48 TFTP-Zeilen, darunter 1x "sent bootcode.bin"
14:25, mit Karte :  46 TFTP-Zeilen, darunter 0x "sent bootcode.bin"
```

Sonst ist das Profil Zeile für Zeile gleich. Drei Startvorgänge mit Karte, alle beim ersten
Versuch erfolgreich, je neun Sekunden.

Messtechnische Einschränkung: **die Zahl der Fehlversuche ist nicht aus dem Protokoll
belegbar**, solange `log-dhcp` abgeschaltet ist. Tritt später ein Fehlversuch auf, ist das
kein Widerspruch zu dieser Zählung.

### Der TFTP-Selbsttest über den eigenen Namen scheitert immer

`tftp raspberrypi5` **auf dem 5B** läuft in einen Timeout, ohne dass dnsmasq den Versuch
protokolliert. Der Dienst ist dabei einwandfrei.

Ursache: Debian trägt den eigenen Hostnamen in `/etc/hosts` auf **`127.0.1.1`** ein.
dnsmasq bindet nur an `127.0.0.1` und die eth0-Adresse — auf `127.0.1.1` horcht nichts.
Nachweis: `getent ahosts raspberrypi5` liefert auf dem 5B `127.0.1.1`, auf dem 4B
`192.168.188.89`.

Kurios, aber erklärbar: mit `curl -6` klappt es auch auf dem Server, weil `/etc/hosts` für
den Namen keinen IPv6-Eintrag hat, der Resolver auf die Fritz!Box ausweicht und die globale
IPv6-Adresse des 5B erhält — auf der ist dnsmasq gebunden.

### TFTP-Protokollzeilen, die harmlos sind

`failed sending <datei>` heißt nicht, dass etwas schiefging. Die Zeile unmittelbar davor
nennt den Grund: `error 0 Early terminate received`. Der Client hat ein TFTP-ERROR-Paket
geschickt, also sinngemäß „ich habe genug". dnsmasq hat für einen absichtlich abgebrochenen
Transfer keine eigene Kategorie.

Der Bootloader **beider** Pi-Generationen arbeitet so. Er liest zuerst nur den Anfang des
Kernel-Images, offenbar um Header, Größe und Ladeadresse zu bestimmen, besorgt damit
Gerätebaum und Overlays, und holt den Kernel ganz zum Schluss komplett:

```
14:47:40  error 0 Early terminate  +  failed sending kernel8.img   (dreimal)
          ... dazwischen: DTB, config.txt, Overlays, cmdline.txt ...
14:47:46  sent kernel8.img                      <- erst hier vollstaendig
```

Belegt über neun Ladevorgänge am 18.10.2026 auf 3B und 4B: achtmal die Signatur „dreimal
abgebrochen, dann einmal vollständig". Die fünf Sekunden dazwischen sind **kein Timeout**.
Eine Ausnahme bleibt unerklärt: die Auslieferung um 09:42:53 hatte keine abgebrochenen
Leseversuche davor.

Ebenfalls harmlos sind Suchmeldungen nach optionalen Dateien, die es bewusst nicht gibt:
`recovery.elf`, `recovery8.img`, `autoboot.txt`, `bootcfg.txt`, `dt-blob.bin`,
`armstub8.bin`. `start.elf` und `start4.elf` werden regulär zweimal ausgeliefert.

Zur Blockrechnung, weil `tftp-no-blocksize` die Blockgröße auf 512 Byte festlegt:
`kernel8.img` des 3B ist 10 192 324 Bytes groß, also 19 906 Blöcke. Der 16-Bit-Blockzähler
läuft erst bei 65 535 Blöcken über, das entspricht 31 MiB.

### Fehlversuche sind unsichtbar, solange log-dhcp aus ist

Ein Startversuch, der im ROM scheitert und nie bis TFTP kommt, hinterlässt **gar keine
Spur**. Aus dem Journal lässt sich nur die Zahl der **erfolgreichen** Starts ermitteln, an
den TFTP-Zeilen.

Hier ist genau dieser Fehler passiert: `grep -c '188.210'` im Journal liefert eine
dreistellige Zahl, die ausschließlich TFTP-Meldungen eines **einzigen** erfolgreichen
Startvorgangs zählt — dreizehnmal `Early terminate`, mehrfach `failed sending`, dazu die
Auslieferungen. Sie wurde zuerst als „48 DHCP-Antworten" gedeutet und daraus auf
Fehlversuche geschlossen. Falsch. Erst `sed | sort | uniq -c` zeigt, was die Zeilen sind.

### Zwei Prüfungen, die falsche Defekte melden

`test -w /boot/firmware` als `baer` meldet **nein**, und das ist korrekt: das Verzeichnis
gehört root mit Modus 755. Die Prüfung gehört hinter `sudo`.

`grep -c auto_initramfs` zählt **Kommentarzeilen mit**. Die `config.txt` des 4B erwähnt in
zwei Kommentaren, dass die Einstellung bewusst fehlt. Nur `grep -n` zeigt, dass keine
wirksame Zeile dahintersteckt.

### „kein /dev/mmcblk" taugt beim 3B nicht als Nachweis

Seit der bootcode-Karte existiert dort `/dev/mmcblk0` und `/dev/mmcblk0p1`, obwohl Root und
Home auf dem NAS liegen. Nachweis für plattenlosen Betrieb ist allein `findmnt -no
SOURCE,FSTYPE /`. Sinnvoll prüfbar ist, dass die Karte **nicht gemountet** ist:

```bash
ssh baer@raspberrypi3b 'findmnt -S /dev/mmcblk0p1 || echo "Karte nicht gemountet, richtig"'
```

Beim 4B gilt die alte Prüfung weiter, dort steckt keine Karte.

### rmtab ist nicht zuverlässig

`ssh sshd@baernas 'cat /var/lib/nfs/rmtab'` enthält auch alte Einträge. Für die Frage
„läuft dieser Client gerade" ist `findmnt` auf dem Client die bessere Antwort.

---

## Shell und Scripting, am eigenen Code gemessen

### ssh frisst das stdin des Scripts

Ohne `-n` liest `ssh` das stdin des aufrufenden Scripts leer. Die nächste `read`-Abfrage
bekommt EOF, und ein interaktives Menü bricht lautlos ab — es sieht aus, als hätte das
Script nichts getan. Jeder `ssh`-Aufruf aus einem Script, der kein stdin braucht, bekommt
`-n`.

Bei `ssh -t ... sudo ...` ist das Gegenteil nötig: dort wird das Terminal gebraucht, damit
sudo nach dem Passwort fragen kann.

### IFS=$'\t' kollabiert leere Felder

Tab gilt in bash als **IFS-Whitespace**. Aufeinanderfolgende Tabs werden deshalb zu einem
Trenner zusammengefasst und leere Felder verschwinden — die Spalten verrutschen. Für
Tabellen mit potentiell leeren Feldern einen Trenner nehmen, der kein Whitespace ist, etwa
`|`, und `IFS='|'` setzen.

In `awk` dann `-F'[|]'` schreiben, nicht `-F'|'`, damit es nicht als Alternation gelesen
wird.

### local sieht die eigene Variable noch nicht

```bash
local a="$1" b="$a"      # b ist LEER, und unter set -u ein Abbruch
```

`local` legt erst alle Namen an und weist dann zu. Beim Auswerten von `b` ist `a` die
gerade erzeugte, noch leere lokale Variable. Getrennt zuweisen.

### Die Shell des NAS ist busybox ash

Gemessen: `/bin/sh` zeigt auf `/bin/busybox`. Daneben liegen GNU-coreutils. Praktische
Folgen: `cat -A` gibt es nicht, `stat -c %y` schon.

`set -e` verhält sich dort wie erwartet — geprüft:

```sh
set -e; [ -e /gibtesnicht ] && { echo BAD; exit 1; }; echo ERREICHT   # -> ERREICHT, exit 0
set -e; [ -e /tmp ]         && { echo TRIFFT; exit 1; }; echo FALSCH  # -> TRIFFT, exit 1
```

Der fehlschlagende Test bricht also nicht ab. Diese Konstruktion ist als Vorbedingung
brauchbar.

### Präfix-Globs beim Löschen abgeleiteter Dateien

`stand-451ba057-2026-10-19-` ist ein Präfix von `stand-451ba057-2026-10-19-2-cmdline.txt`.
Ein `rm -f stand-<name>-*` beim Löschen des kürzeren Stands nimmt die Dateien des
Zähler-Stands mit. Endungen einzeln aufzählen, nicht globben.

Derzeit sind es fünf: `cmdline.txt`, `config.txt`, `fstab`, `pakete.txt`, `marker`. Die
Liste steht an zwei Stellen in `lanboot-stand.sh`, in `repo_export_stand` und in
`aktion_loeschen`. Wer eine ergänzt und die andere vergisst, hinterlässt Waisen im Repo
oder exportiert zu wenig.

### Ein Trockenlauf muss vollständig trocken sein

`NAS_TROCKEN=1` in `lanboot-stand.sh` fing zuerst nur die schreibenden NAS-Kommandos ab.
Das Herunterfahren des Clients und ein lokales `rm` liefen daran vorbei und wären im
Trockenlauf **wirklich** passiert. Wer einen solchen Schalter einbaut: jeder verändernde
Schritt muss darüber laufen, egal auf welchem Rechner er wirkt.

**Ein Loch ist noch offen:** `repo_export_stand` kopiert mit lokalem `cp` ins Repo, ohne
`nas_schreib` und ohne Abfrage des Schalters. Ein Trockenlauf von Menüpunkt 3-1, 3-3 oder
4-1 schreibt die `stand-<name>-*`-Dateien also wirklich. Folgenarm, weil die Quelle dabei
unverändert ist und dieselben Inhalte herauskommen — aber `git status` zeigt danach
Änderungen, die man nicht ausgelöst zu haben glaubt.

---

## Quellen

- [Raspberry Pi Doku, Network booting (boot-net)](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/boot-net.adoc)
  — Bootablauf, TFTP-Reihenfolge, OTP, Liste der BootROM-Fehler
- [Raspberry Pi Doku, Network boot your Raspberry Pi](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/remote-access/network-boot-raspberry-pi.adoc)
  — die funktionierende dnsmasq-Konfiguration
- [rpi-eeprom Issue #563](https://github.com/raspberrypi/rpi-eeprom/issues/563)
  — `TFTP_PREFIX` nutzt im Standard die Seriennummer als Verzeichnis
- [WD Community, /etc/exports wird überschrieben](https://community.wd.com/t/etc-export-changes/286736)
- [WD Community, SSH-Zugang und Standardlogin](https://community.wd.com/t/an-explanation-of-ssh-for-less-savvy-users/214247)
- [Kiro, Permissions](https://kiro.dev/docs/permissions.md) — Schema, Präzedenz, Glob-Semantik

Inhalte der verlinkten Quellen wurden für die Lizenzkonformität umformuliert.
