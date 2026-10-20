# HOWTO: Handgriffe am Netboot

Nach Vorhaben geordnet. Kein Warum — das steht in [ARCHITEKTUR.md](ARCHITEKTUR.md).

## Die Geräte

| | Pi 5B | Pi 4B | Pi 3B | NAS |
|---|---|---|---|---|
| Hostname | `raspberrypi5` | `raspberrypi4b` | `raspberrypi3b` | `baernas` |
| Seriennummer | `948857e5` | `451ba057` | `bf7cac06` | — |
| Rolle | Bootserver, Arbeitsplatz | Client | Client | Datenspeicher |
| Ursprungsstand | — | `netboot/451ba057` | `netboot/bf7cac06` | — |
| SSH | `baer@raspberrypi5` | `baer@raspberrypi4b` | `baer@raspberrypi3b` | `sshd@baernas` |
| sudo | ohne Passwort | **mit Passwort** | **mit Passwort** | ist root |
| Besonderheit | — | — | braucht die bootcode-Karte | — |

Welche Stände es gibt und welcher aktiv ist, steht hier absichtlich nicht. Das sagt dir das
Script, siehe Abschnitt E.

## Das Werkzeug

```bash
cd ~/gitrepos/raspirepo/lanboot
./lanboot-stand.sh
```

```
  1) Zustand zeigen
  2) Neuen Raspi aufnehmen                 (Typ und Serial erfragen, Kopie, Symlink)
  3) Arbeitsstaende                        (anlegen, wechseln, beschreiben, loeschen)
  4) Pflege                                (Repo-Export, motd)
  0) Ende
```

Die Punkte 3 und 4 führen in ein Untermenü. `0` oder die Eingabetaste allein geht von dort
zurück:

```
  3)  1) Kopie des Arbeitsstandes anlegen      (Kopie des aktiven Stands, darauf umschalten)
      2) Auf einen Arbeitsstand zurueckfallen  (Auf eine Sicherung zurueckfallen)
      3) Beschreibung aendern                  (nur der Kommentar, kein Baum wird angefasst)
      4) Stand loeschen                        (nur eingefrorene, unumkehrbar)

  4)  1) Repo-Export aller Staende nachziehen  (liest nur, schreibt ins Repo)
      2) motd aller Staende erneuern           (Anzeige nach dem Starten des Geraetes)
```

In diesem Text steht dafür kurz `Menüpunkt 3-1`: erst `3`, dann `1`, jeweils mit
Eingabetaste.

Kein `sudo` nötig. Passwörter fragt das Script nur dort, wo ein Client heruntergefahren
werden muss — dann fragt `sudo` auf dem Client selbst.

Zum Hinsehen ohne Folgen:

```bash
NAS_TROCKEN=1 ./lanboot-stand.sh
```

Dann wird jeder verändernde Schritt nur angezeigt. Nichts wird kopiert, nichts
umgeschaltet, kein Client heruntergefahren, keine Datei gelöscht.

---

## A — Ich will etwas ausprobieren und vorher sichern

**Menüpunkt 3-1.** Das Script legt eine vollständige Kopie des aktiven Stands an und
schaltet darauf um. Ab dem nächsten Start arbeitest du in der Kopie; der alte Stand ist
eingefroren, weil kein Symlink mehr auf ihn zeigt, und bleibt als Rückweg stehen.

Ablauf: Gerät wählen, **Beschreibung tippen**, dann `Kopieren?` bestätigen.

Die Beschreibung gehört der **Kopie**, die gerade entsteht:

```
Beschreibung der Kopie
----------------------------------------------------------------
  Du verlaesst 451ba057-2026-10-19 und arbeitest ab dem naechsten Start in
  der Kopie mit dem Namen 451ba057-2026-10-19-2.

  Beschreibung der Kopie? [leer = Kopie von 451ba057-2026-10-19] 
```

Der Stand, den du verlässt, behält seine eigene Beschreibung und wird nicht angefasst. Wenn
du schon weißt, was in die Kopie hineinkommt, schreib es hin. Wenn nicht, nimm die Vorgabe
und hol es später mit Menüpunkt 3-3 nach.

Gefragt wird vor dem Herunterfahren und vor dem Kopieren, damit du nicht nach Minuten
Wartezeit noch tippen musst.

Läuft der Client, bietet das Script an, ihn herunterzufahren — nötig, weil die Kopie eines
laufenden Systems inkonsistent wäre. Das Passwort fragt `sudo` auf dem Client.

Rechne mit einigen Minuten und gut 3 GB Platz. Danach Strom geben, und du bist im neuen
Stand.

---

## A2 — Ich will die Beschreibung eines Stands ändern

**Menüpunkt 3-3.** Gerät wählen, Stand wählen, neuen Text tippen. Die Eingabetaste allein
lässt alles, wie es ist.

Geändert wird genau eine Zeile im Marker `/etc/lanboot-stand` des Baums. Am Rootfs, am
Home, am TFTP-Symlink und am Namen des Stands ändert sich nichts, und das gilt auch für den
aktiven Stand — eine Beschreibung ist ein Kommentar und hat auf den Betrieb keine Wirkung.
Das Repo zieht das Script danach selbst nach.

Wenn das Script nicht läuft, ist es ein Einzeiler:

```bash
ssh sshd@baernas 'sed -i "s|^notiz=.*|notiz=der richtige Text|" \
    /nfs/pi/netboot/<stand>/etc/lanboot-stand'
ssh sshd@baernas 'cat /nfs/pi/netboot/<stand>/etc/lanboot-stand'
```

Danach Menüpunkt 4-1, damit das Repo es mitbekommt.

---

## B — Ich will zurück auf einen früheren Stand

**Menüpunkt 3-2.** Es wird nur der Symlink umgebogen. Nichts wird kopiert, nichts angelegt.

Ablauf: Gerät wählen, dann aus der Liste den Stand wählen. Oben steht, wo du gerade bist.

Die Liste nennt zu jedem Stand seine Beschreibung. Danach wählt man aus, nicht nach dem
Datum:

```
   1) 451ba057-2026-10-19-2      2026-10-19 13:16 AKTIV
      Kopie von 451ba057-2026-10-19
   2) 451ba057-2026-10-19        2026-10-19 07:52 eingefroren
      Docker 26.1.5, Compose 2.26.1-4, Python 3.13.5
   3) 451ba057                   2026-10-06 02:26 eingefroren
      Initiale Grundversion
```

Hier wird nichts beschriftet. Steht bei einem Stand noch die Vorgabe `Kopie von …`, obwohl
inzwischen etwas drin ist, hilft Menüpunkt 3-3.

Wirksam beim nächsten Start. Läuft der Client noch, schreibt er bis dahin weiter in den
alten Stand — das Script sagt dir das und nennt den Poweroff-Befehl.

Danach kannst du jederzeit wieder in die andere Richtung wechseln, dasselbe Menü. Der
Stand, den du verlässt, bleibt immer stehen wie er ist.

**Das Home gehört zum Stand.** Fällst du zurück, bekommst du auch das Home von damals.
Gelöscht wird nichts; das Home des verlassenen Stands ist beim Zurückwechseln wieder da.

### Wenn das Script nicht läuft

Der Symlink von Hand, das ist der ganze Vorgang:

```bash
ssh sshd@baernas 'ln -sfn ../<stand>/boot/firmware /nfs/pi/netboot/tftpboot/<serial>'
ssh sshd@baernas 'ls -l /nfs/pi/netboot/tftpboot/'
```

---

## C — Ich will einen neuen Raspi aufnehmen

An dnsmasq und der Fritz!Box ändert sich **nichts**. Der Proxy-DHCP antwortet jedem Pi.

### C1 Am Gerät, bevor das Script dran ist

Seriennummer ermitteln, auf dem Pi selbst solange er noch von SD bootet:

```bash
grep Serial /proc/cpuinfo | cut -c19-26
```

Oder ohne Zugriff: den Pi einschalten und auf dem 5B ins Log schauen, die Meldung über die
fehlende `<serial>/start.elf` nennt die Nummer.

```bash
journalctl -u dnsmasq -f
```

Netboot freischalten. **Pi 4 und 5** über das EEPROM, umkehrbar:

```bash
sudo raspi-config        # Advanced Options -> Boot Order -> Network Boot
sudo rpi-eeprom-config --edit     # oder direkt: BOOT_ORDER=0xf21
```

**Pi 3B** über ein OTP-Bit. **Das ist unumkehrbar.** Einmalig von SD booten mit
`program_usb_boot_mode=1` in der `config.txt`, neu starten, dann prüfen:

```bash
vcgencmd otp_dump | grep ^17:
# 1020000a = Werkszustand
# 3020000a = Netboot freigeschaltet
```

Danach die Zeile aus der `config.txt` wieder entfernen. Ein 3B+ bringt das Bit ab Werk mit.
Ein Pi 3 braucht außerdem die bootcode-Karte, siehe Abschnitt H.

### C2 Mit dem Script

**Menüpunkt 2.** Es fragt nach Typ, Vorlage-Stand, Seriennummer und Hostname und erledigt
dann alles: Baum kopieren, `nfsroot` umbiegen, `rsize/wsize` nach Typ setzen, Identität
trennen, Home anlegen mit `authorized_keys`, Symlink setzen, nachprüfen.

Danach Strom geben und prüfen:

```bash
ssh baer@<neuer-host> 'hostname; findmnt -no SOURCE,FSTYPE /; findmnt -no SOURCE /home/baer; systemctl --failed'
```

Beim ersten SSH-Zugriff den Hostkey sauber prüfen statt blind zu bestätigen:

```bash
ssh-keyscan -t ed25519 <neuer-host> | ssh-keygen -lf -
ssh sshd@baernas 'cat /nfs/pi/netboot/<stand>/etc/ssh/ssh_host_ed25519_key.pub' > /tmp/k.pub
ssh-keygen -lf /tmp/k.pub
# gleiche Fingerprints -> gefahrlos nach known_hosts
ssh-keyscan -t ed25519 <neuer-host> >> ~/.ssh/known_hosts
```

Eine Reservierung in der Fritz!Box ist empfohlen, aber nicht zwingend.

### C3 Von Hand, wenn es sein muss

Das macht Menüpunkt 2 für dich. Hier steht es, damit du weißt, was passiert, und damit du
es notfalls ohne das Script kannst. Im Beispiel ein Pi 4 mit Serial `aabbccdd`, Hostname
`raspberrypi4c`, abgeleitet vom Stand `451ba057`.

Klonen **auf dem NAS selbst**, sonst laufen knapp 4 GB zweimal durchs Netz. Der Quell-Client
muss aus sein:

```bash
ssh sshd@baernas 'cp -a /nfs/pi/netboot/451ba057 /nfs/pi/netboot/aabbccdd'
```

Als Vorlage einen Baum derselben Pi-Generation nehmen — die Bootloader-Dateien
unterscheiden sich (`start4.elf` gegen `start.elf`).

Identität trennen, sonst teilen beide Pis machine-id und SSH-Hostkey:

```bash
ssh sshd@baernas '
  R=/nfs/pi/netboot/aabbccdd
  echo raspberrypi4c > $R/etc/hostname
  sed -i "s/raspberrypi4b/raspberrypi4c/g" $R/etc/hosts
  : > $R/etc/machine-id
  rm -f $R/etc/ssh/ssh_host_*
'
```

`: >` macht `machine-id` leer statt sie zu löschen — systemd erzeugt sie beim ersten Start
neu, `ssh-keygen -A` ebenso die Hostkeys.

`cmdline.txt` anpassen, eine einzige Zeile, nur `nfsroot=` ändern. Die **IP** des NAS ist
Pflicht, kein Name. Bei einem 100-Mbit-Gerät `rsize/wsize=32768`:

```
nfsroot=192.168.188.26:/mnt/HD/HD_a2/pi/netboot/aabbccdd,vers=3,nolock,proto=tcp,hard,rsize=131072,wsize=131072
```

`fstab` des Klons, kein Eintrag für `/`, keiner für `/boot/firmware`, kein Swap:

```
proc  /proc  proc  defaults  0  0
baernas:/mnt/HD/HD_a2/pi/home/raspberrypi4c/baer  /home/baer  nfs  vers=3,nolock,hard,_netdev,nofail  0  0
```

`config.txt` prüfen — kein `auto_initramfs=1`, und mit `grep -n` nachsehen, nicht `grep -c`:

```bash
ssh sshd@baernas 'grep -n auto_initramfs /nfs/pi/netboot/aabbccdd/boot/firmware/config.txt'
```

Home anlegen. **Die `authorized_keys` nicht vergessen** — ohne sie bekommst du
`Permission denied (publickey,password)` bei einem einwandfrei gebooteten Client:

```bash
ssh sshd@baernas '
  mkdir -p /nfs/pi/home/raspberrypi4c/baer/.ssh
  chown -R 1000:1000 /nfs/pi/home/raspberrypi4c
  chmod 700 /nfs/pi/home/raspberrypi4c/baer/.ssh
'
cat ~/.ssh/id_ed25519.pub | ssh sshd@baernas 'cat > /nfs/pi/home/raspberrypi4c/baer/.ssh/authorized_keys'
ssh sshd@baernas 'chown 1000:1000 /nfs/pi/home/raspberrypi4c/baer/.ssh/authorized_keys; chmod 600 /nfs/pi/home/raspberrypi4c/baer/.ssh/authorized_keys'
```

Symlink anlegen, **relativ**:

```bash
ssh sshd@baernas 'ln -sfn ../aabbccdd/boot/firmware /nfs/pi/netboot/tftpboot/aabbccdd'
```

Zum Schluss prüfen, dass `/dev/console` (`c 5 1`, Modus 600) und `/dev/null` (`c 1 3`,
Modus 666) im Baum existieren und `nfs-common` installiert ist:

```bash
ssh sshd@baernas '
  ls -l /nfs/pi/netboot/aabbccdd/dev/console /nfs/pi/netboot/aabbccdd/dev/null
  grep -c "^Package: nfs-common" /nfs/pi/netboot/aabbccdd/var/lib/dpkg/status
'
```

---

## D — Ich will einen Stand loswerden

**Menüpunkt 3-4.** Angeboten werden nur eingefrorene Stände; der aktive taucht nicht auf.
Bestätigt wird durch **Eintippen des Standnamens**, nicht mit `j`. Das ist die einzige
unumkehrbare Aktion.

Mit dem Baum gehen das Home des Stands und seine fünf Textdateien im Repo. Bei einem
**Ursprungsstand** bleibt das Home stehen — es ist das gemeinsame Home des Geräts, darin
liegen deine Schlüssel.

Vorher lohnt ein Blick, was Platz belegt:

```bash
ssh sshd@baernas 'du -sh /nfs/pi/netboot/*/ ; df -h /mnt/HD/HD_a2'
```

---

## E — Ich will wissen, was es gibt und wo ich bin

**Menüpunkt 1.** Zeigt die aktive Zuordnung, alle Stände nach Typ sortiert mit Datum und
Beschreibung, den freien Platz und welche Clients laufen.

Am Gerät selbst, und nur das ist der belastbare Nachweis:

```bash
ssh baer@<client> 'findmnt -no SOURCE,FSTYPE /; findmnt -no SOURCE /home/baer; cat /etc/lanboot-stand'
```

Beim Login zeigt die `motd` den Stand und seine Beschreibung:

```
==========================================================
=== STAND 451ba057-2026-10-19-2  (Typ 4b, Serial 451ba057)
=== Weitere Tools installieren
==========================================================
```

Stimmt sie nicht mit `findmnt` überein, gilt `findmnt` — dann Menüpunkt 4-2, der schreibt
die `motd` aller Stände neu. Denselben Weg nimmt man, wenn sich die Form der `motd`
geändert hat; er ist wiederholbar und fasst in jedem Baum nur `/etc/motd` an.

---

## F — Ich will prüfen, ob alles läuft

```bash
systemctl is-active dnsmasq nas-export-guard.timer
sudo /usr/local/sbin/nas-export-guard.sh                # erwartet: OK, Exportzeilen vorhanden
for m in /srv/nfs/netboot /srv/nfs/home; do findmnt -no SOURCE,FSTYPE "$m" || echo "$m fehlt"; done
df -h /                                                  # ein volles / legt den Bootserver still
```

TFTP, **nicht** über den eigenen Namen auf dem Server — das läuft immer in einen Timeout,
obwohl der Dienst einwandfrei ist:

```bash
curl -s -o /tmp/t tftp://127.0.0.1/<serial>/cmdline.txt && cat /tmp/t
```

Die ausgelieferte `cmdline.txt` nennt den Stand, von dem das Gerät beim nächsten Start
bootet. Das ist die beste Einzelprüfung der ganzen Kette.

Kernel und Auslieferung müssen dieselbe Datei sein:

```bash
ssh baer@<client> 'md5sum /boot/firmware/kernel8.img'
sudo md5sum /srv/nfs/netboot/tftpboot/<serial>/kernel8.img
```

---

## G — Es bootet nicht

| Beobachtung | Wahrscheinliche Ursache |
|---|---|
| Pi 3B tut gar nichts | Die bootcode-Karte fehlt oder ist nicht lesbar. Siehe H. |
| DHCP-Anfragen im Log, aber kein TFTP | Boot-String falsch lang, oder `bootcode.bin` fehlt in der TFTP-**Wurzel** |
| `<serial>/start.elf not found` im Log | TFTP-Symlink fehlt oder zeigt ins Leere |
| Kernel lädt, dann Panik mit `VFS: Unable to mount root` | `nfsroot=` falsch, oder Name statt IP, oder Exportzeile verschwunden |
| Start bricht früh ab, keine Konsolenausgabe | `/dev/console` oder `/dev/null` fehlt im Rootfs |
| `root=/dev/nfs` wird nicht aufgelöst | `auto_initramfs=1` steht in der `config.txt` |
| Client bootet, SSH sagt `Permission denied (publickey)` | `authorized_keys` im Home fehlt |
| Client bootet, Home fehlt | `nfs-common` nicht installiert, oder `fstab`-Zeile falsch |
| Alle Clients verlieren im Betrieb das Root-Dateisystem | Exportzeilen vom NAS überschrieben. `nas-export-guard.sh` von Hand aufrufen. |
| `Host key verification failed` | kein `known_hosts`-Eintrag für den Namen, oder Hostkey nach einem Klon neu. Siehe C2. |
| 3B hängt beim Start, Karte steckt | Liegt ein `start.elf` oder eine `config.txt` auf der Karte? Dort darf **nur** `bootcode.bin` liegen. |
| Gerät bootet den falschen Stand | Symlink prüfen: `ssh sshd@baernas 'ls -l /nfs/pi/netboot/tftpboot/'` |

Für eine Fehlersuche an DHCP muss `log-dhcp` in `/etc/dnsmasq.d/pxe.conf` wieder
eingeschaltet werden, es ist auskommentiert. Die TFTP-Zeilen (`sent …`) protokolliert
dnsmasq unabhängig davon.

Nach einem Fehlschlag beim 3B hilft nur Strom trennen. Er wacht nicht von allein auf.

---

## H — Ich will eine bootcode-Karte für einen Pi 3 bauen

Das ist die Abhilfe gegen den defekten Netboot-ROM des Pi 3B. Größe der Karte ist belanglos,
4 GB reichen für 52 KB mehr als aus.

### H1 Karte zweifelsfrei identifizieren

**Der wichtigste Schritt.** Das System des 5B liegt auf `/dev/nvme0n1`, eine SD-Karte im
Schacht erscheint als `/dev/mmcblk0`, in einem USB-Leser als `/dev/sdX`.

```bash
lsblk -o NAME,SIZE,TYPE,RM,FSTYPE,LABEL,MOUNTPOINT,MODEL
sudo dmesg | tail -5
lsblk -no PKNAME "$(findmnt -no SOURCE /)"   # Systemtraeger, der bleibt unberuehrt
```

Prüfen: Größe passt zur Karte, Gerät ist nicht der Systemträger, nichts davon ist gemountet.

### H2 Partitionieren und formatieren

MBR, nicht GPT — das ROM des Pi 3 erwartet MBR.

```bash
SD=/dev/mmcblk0
sudo wipefs -a $SD
sudo parted -s $SD mklabel msdos
sudo parted -s $SD mkpart primary fat32 1MiB 100%
sudo partprobe $SD
sudo mkfs.vfat -F 32 -n BOOTCODE ${SD}p1
```

### H3 bootcode.bin aufbringen, und nur die

Die Datei aus dem **Rootfs des Clients** nehmen, nicht irgendeine. Dann passt sie zur
Firmware, die der Client per `apt` pflegt.

```bash
sudo mkdir -p /mnt/sdboot
sudo mount ${SD}p1 /mnt/sdboot
sudo cp /srv/nfs/netboot/<stand>/boot/firmware/bootcode.bin /mnt/sdboot/
sudo sync
sudo find /mnt/sdboot -type f            # Soll: genau eine Datei
sudo umount /mnt/sdboot
```

**Kein `start.elf`, keine `config.txt`, nichts sonst.** Fände `bootcode.bin` auf der Karte
ein `start.elf`, würde es von dort weiterladen und der Netboot wäre ausgehebelt.

### H4 Einbauen und Wirkung nachweisen

```bash
ssh baer@raspberrypi3b 'sudo systemctl poweroff'    # verlangt das Passwort
# Karte einstecken, Strom geben
```

Dieser **erste** Start läuft noch über den alten ROM-Weg, rechne mit Fehlversuchen. Ab dem
Start danach übernimmt `bootcode.bin` die Netzwerkarbeit. Der Beleg ist, dass
`bootcode.bin` **nicht mehr per TFTP angefragt** wird:

```bash
journalctl -u dnsmasq --since "-10 min" | grep -c 'sent.*bootcode.bin'      # Soll: 0
journalctl -u dnsmasq --since "-10 min" | grep -c 'sent.*/start.elf'        # Soll: 1
ssh baer@raspberrypi3b 'findmnt -no SOURCE,FSTYPE /; uptime -p'
```

Der Preis: der 3B startet jetzt **nur noch mit lesbarer Karte**. Sie ist ein
Einzelfehlerpunkt, aber einer, der nur beim Start gelesen wird.

---

## I — Ich habe eine Konfigurationsdatei geändert

Bearbeitet wird im Workspace, ausgespielt mit `install`, damit der laufende Dienst nie eine
halbfertige Datei sieht:

```bash
cd ~/gitrepos/raspirepo/lanboot
sudo install -o root -g root -m 0644 dnsmasq-pxe.conf /etc/dnsmasq.d/pxe.conf
diff -q dnsmasq-pxe.conf /etc/dnsmasq.d/pxe.conf
sudo systemctl restart dnsmasq
```

Die Dateien je Stand sind **Abbilder**, keine Vorlagen: `cmdline.txt`, `config.txt`,
`fstab`, `pakete.txt` und `marker` — letzterer ist die Kopie von `/etc/lanboot-stand` und
trägt die Beschreibung, damit sie versioniert im Repo liegt. Sie werden
von Menüpunkt 4-1 aus den Bäumen gelesen; ausgespielt wird von dort nichts. Wer eine
`cmdline.txt` ändern will, ändert sie im Baum auf dem NAS und zieht danach Menüpunkt 4-1
nach.

---

## Was das Script nie tut

- Es löscht nichts außer in Menüpunkt 3-4, und dort nur nach getippter Bestätigung.
- Es löscht keinen Stand, auf den ein Symlink zeigt. Geprüft wird unmittelbar vor dem
  Löschen, direkt an den Symlinks.
- Es kopiert nie von einem laufenden Client, sondern bietet an, ihn herunterzufahren.
- Es committet nicht. Das machst du.
- Es legt keine Zustandsübersicht an. Zustand kommt aus Menüpunkt 1, nicht aus einer Datei.
