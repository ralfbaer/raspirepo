---
inclusion: fileMatch
fileMatchPattern: 'lanboot/**'
---

# Aufbau des Netboot: Invarianten, Geräte, Layout

Diese Datei wird geladen, sobald an `lanboot/` gearbeitet wird. Sie enthält, was sich **nicht** mit jedem
Eingriff ändert. Welche Stände es gerade gibt und welcher aktiv ist, steht hier
absichtlich nicht — das wird gemessen, siehe `lanboot-fallstricke.md`.

Erklärung für Menschen: `lanboot/DOKU/ARCHITEKTUR.md`. Handgriffe: `lanboot/DOKU/HOWTO.md`.

---

## Invarianten der Bootkette

Vier Eigenschaften, auf die sich jede Änderung stützen darf.

**Der Client erfährt die Adresse des TFTP-Servers dynamisch** aus DHCP-Option 54. In der
`cmdline.txt` steht unter `nfsroot=` die **NAS**-Adresse, nie die des Servers. Ein
Serverwechsel erfordert daher an keinem Client eine Änderung. Belegt durch den
Serverwechsel 4B → 5B am 17.10.2026, der den laufenden 3B nicht gestört hat.

**Der Server wird nur zum Starten gebraucht.** Ein laufender Client hält keine Verbindung
zum 5B; seine NFS-Mounts gehen direkt zum NAS. Kehrseite: fällt der 5B aus oder läuft seine
Systempartition voll, startet kein Client mehr.

**Die Zuordnung Hardware → System steckt allein im TFTP-Symlink.** Nicht im DHCP, nicht in
einer MAC-Tabelle, nicht in der Serverkonfiguration. Das BootROM fragt von sich aus nach
`<eigene-seriennummer>/start4.elf`; `TFTP_PREFIX` steht im Standard auf die Seriennummer.
Daraus folgt das ganze Stand-Verfahren.

**Der Kernel mountet das Root-Dateisystem ohne Userspace**, über `CONFIG_ROOT_NFS`. In
diesem Moment existiert kein Resolver, keine `/etc/resolv.conf`, keine `/etc/hosts` — sie
lägen auf genau dem Dateisystem, das gemountet werden soll. Deshalb muss in `nfsroot=` eine
IP-Adresse stehen; ein Name dort verhindert den Start garantiert. Der Home-Mount ist der
Gegenbeweis: den macht systemd aus `/etc/fstab`, also im Userspace, und dort darf ein Name
stehen.

### Das Symlink-Muster

`tftpboot/<serial>` ist ein **relativer** Symlink auf `../<verzeichnis>/boot/firmware`.
Damit liefert TFTP genau die Dateien aus, die ein `apt upgrade` auf dem Client selbst
aktualisiert; Kernel und Module bleiben zusammen. Relativ, damit ein Verschieben des
`netboot`-Baums die Links nicht bricht und ein Klon per `cp -a` seine Bootdateien mitnimmt.

Dass `/boot/firmware` im Rootfs auf NFS liegt und kein Mountpunkt ist, akzeptiert
`raspi-firmware` wegen einer Ausnahme in `/etc/kernel/postinst.d/z50-raspi-firmware`:

```sh
elif [ "$(stat -f -c %T "${firmware_dst}")" = "nfs" ]; then
  true   # NFS -> Mountpunkt-Pruefung ueberspringen
```

## Stände

Ein **Stand** ist ein vollständiger, eigenständiger Rootfs-Baum **mit eigenem Home**.
Keine Hardlinks, kein overlayfs, nichts geteilt.

- Verzeichnis: `netboot/<serial>-<YYYY-MM-DD>`, bei mehreren am selben Tag mit Zähler
  `-2`, `-3`. Ohne Datum im Namen: ein **Ursprungsstand** aus der Zeit vor dem Verfahren.
- Home: `home/<hostname>/<stand>/baer`. Beim Ursprungsstand `home/<hostname>/baer`, also
  das gemeinsame Home des Geräts.
- Markerdatei `<baum>/etc/lanboot-stand` mit `typ`, `serial`, `stand`, `hostname`, `home`,
  `angelegt`, `herkunft`, `notiz`. Jeder Stand hat eine, auch die Ursprungsstände; fehlt
  sie, legt `stand_notiz_setzen` eine vollständige an. Der Fallback im Script bleibt
  bestehen: ohne Marker werden Typ und Serial aus dem Verzeichnisnamen und einer Tabelle
  abgeleitet.
- Die **Beschreibung** steht in `notiz=`. Sie gehört dem Stand, der sie bei seiner
  Entstehung bekommt: gefragt wird in Menüpunkt 3-1 nach der *Kopie*, Vorgabe `Kopie von
  <quellstand>`. Der Stand, den man dabei verlässt, wird nicht angefasst — in einen
  eingefrorenen Baum wird nicht geschrieben. Nachträglich ändern: Menüpunkt 3-3.
- `<baum>/etc/motd` nennt den Stand, damit man im eingeloggten System sieht, wo man ist.

**Eingefroren** ist ein Stand, sobald kein TFTP-Symlink mehr auf ihn zeigt — dann schreibt
kein Gerät aus dem Betrieb hinein. Es gibt kein read-only-Flag, das wäre auf diesem NAS
nicht tragfähig, und es ist kein Schreibschutz: Menüpunkt 3-3 ändert die Beschreibung auch
in einem eingefrorenen Baum, dort aber nur `/etc/lanboot-stand` und `/etc/motd`.

**Umschalten ist kein Kopieren.** Zwischen bestehenden Ständen wechselt man, indem der
Symlink umgebogen wird. Nichts wird angelegt, nichts verändert außer diesem Symlink, und es
wirkt beim nächsten Start des Geräts. Kopiert wird nur, wenn ein **neuer** Stand entstehen
soll.

Verwaltet wird das mit `lanboot-stand.sh` im Workspace. Alles Schwere läuft per `ssh` auf
dem NAS, damit keine Gigabytes über den 5B laufen. Das Script braucht auf dem 5B kein
`sudo`. `NAS_TROCKEN=1` zeigt alle verändernden Schritte nur an.

Das Menü ist zweistufig, Schreibweise `3-1` heißt erst `3`, dann `1`:

```
1) Zustand zeigen
2) Neuen Raspi aufnehmen
3) Arbeitsstaende    1) Kopie anlegen  2) zurueckfallen  3) Beschreibung aendern  4) loeschen
4) Pflege            1) Repo-Export    2) motd erneuern
```

---

## Geräte

| | Pi 5B | Pi 4B | Pi 3B | NAS |
|---|---|---|---|---|
| Hostname | `raspberrypi5` | `raspberrypi4b` | `raspberrypi3b` | `baernas` |
| IP | 192.168.188.89 | 192.168.188.211 | 192.168.188.210 | 192.168.188.26 |
| Seriennummer | `948857e5` | `451ba057` | `bf7cac06` | — |
| MAC eth0 | `88:a2:9e:05:5a:3d` | `dc:a6:32:01:83:23` | `b8:27:eb:7c:ac:06` | — |
| Modell | Pi 5 Model B Rev 1.1 | Pi 4 Model B Rev 1.1 | Pi 3 Model B Rev 1.2 | WD EX2 Ultra |
| RAM | 7,9 GB | 1,8 GB | 905 MB | — |
| LAN | 1000 Mbit | 1000 Mbit | **100 Mbit** | 1000 Mbit |
| SSH-Benutzer | `baer` (1000:1000) | `baer` (1000:1000) | `baer` (1000:1000) | `sshd` (**uid 0**) |
| sudo ohne Passwort | ja | **nein** | **nein** | entfällt (ist root) |
| Rolle | Server + Kiro | Client, plattenlos | Client, plattenlos | Datenspeicher |
| Ursprungsstand | — | `netboot/451ba057` | `netboot/bf7cac06` | — |
| Bootloader | `start4.elf`, SPI-EEPROM | `start4.elf`, SPI-EEPROM | `start.elf` per TFTP | — |
| `bootcode.bin` | entfällt | entfällt | **von SD-Karte** | — |
| Netboot freigeschaltet | EEPROM `BOOT_ORDER` | EEPROM `BOOT_ORDER=0xf21` | OTP 17 = `3020000a` | — |
| `rsize/wsize` | — | 131072 | 32768 | — |

Die Seriennummer ist der Schlüssel: sie ist der Name, den das BootROM per TFTP anfragt.
Beim Pi 3 stimmen MAC-Ende und Serial überein (`7c:ac:06` zu `bf7cac06`), beim Pi 4 und 5
nicht.

**OTP-Register 17** ist nur beim Pi 3 aussagekräftig. Der 4B zeigt dort `000008b0`, und das
bedeutet nichts.

Typtabelle für neue Geräte steht oben in `lanboot-stand.sh` und ist dort zu erweitern.

---

## Das NAS

WD My Cloud EX2 Ultra. **NFSv2 und v3, kein NFSv4** — daher `vers=3` in allen Mounts.
`/bin/sh` ist **busybox ash**, daneben liegen GNU-coreutils (`cp`, `stat`, `awk`, `sed`,
`find`, `rsync`).

SSH-Benutzer `sshd` hat **uid 0**, ist also echter root. Sein Home ist **`/home/root`**,
nicht `/root`; Schlüssel gehören nach `/home/root/.ssh/authorized_keys`. In `sshd_config`
steht `AllowUsers sshd`.

### Zwei Pfadschreibweisen für dasselbe

`/nfs/pi/...` ist der Name in der Weboberfläche, `/mnt/HD/HD_a2/pi/...` der echte Pfad. In
SSH-Kommandos auf dem NAS funktionieren beide, in `nfsroot=` und `/etc/fstab` **nur der
lange**.

### Falle: all_squash in den verwalteten Freigaben

Von der Weboberfläche erzeugte Exportzeilen enthalten `all_squash` mit
`anonuid=501,anongid=1000`. Jeder Zugriff landet auf `nobody:share`. Ein Root-Dateisystem
ist darauf unmöglich: kein `chown`, kein `mknod`, also kein `/dev/console`. Deshalb zwei
**von Hand eingetragene** Zeilen in `/etc/exports`:

```
"/nfs/pi/netboot" 192.168.188.0/24(rw,sync,no_wdelay,no_root_squash,no_subtree_check,insecure,insecure_locks)
"/nfs/pi/home"    192.168.188.0/24(rw,sync,no_wdelay,no_root_squash,no_subtree_check,insecure,insecure_locks)
```

Original liegt als `/etc/exports.pxe-backup`.

Eigentümer in Verzeichnislisten verrät den Zugriffsweg: `baernasu share` heißt SMB von
Windows, `nobody share` heißt NFS über eine all_squash-Freigabe, `root root` heißt Zugriff
über die handgetragene Freigabe.

### Falle: die Firmware überschreibt /etc/exports

Jede Änderung einer Netzwerk- oder Share-Einstellung in der Weboberfläche schreibt
`/etc/exports` neu; die handgetragenen Zeilen verschwinden. Im Betrieb verlieren die
Clients dadurch mitten im Lauf ihr Root-Dateisystem. Dagegen läuft
`nas-export-guard.timer` auf dem 5B alle fünf Minuten: prüft per SSH, trägt nach, ruft
`exportfs -ra`.

Offener Sicherheitspunkt: `/nfs/pi` und `/nfs/Data` sind an `*` exportiert, für jedes Gerät
im LAN mountbar. War schon vor dem Projekt so. Einschränkung auf `192.168.188.0/24` wäre
sinnvoll.

---

## Dateilayout

### NAS

```
/mnt/HD/HD_a2/pi/              (= /nfs/pi in der Weboberflaeche)
├── netboot/                   Export mit no_root_squash
│   ├── <serial>/              Ursprungsstand eines Geraets
│   ├── <serial>-<datum>/      Stand, mit boot/firmware/ darin
│   └── tftpboot/              TFTP-Wurzel
│       ├── bootcode.bin       echte Datei, 52 624 Bytes, fuer alle Pi 3 gleich
│       └── <serial>           Symlink -> ../<stand>/boot/firmware
└── home/                      Export mit no_root_squash
    └── <hostname>/
        ├── baer/              Home des Ursprungsstands, gemeinsam
        └── <stand>/baer/      Home eines Stands
```

### 5B

```
/etc/dnsmasq.d/pxe.conf                                Proxy-DHCP und TFTP
/etc/systemd/system/dnsmasq.service.d/nfs-mount.conf   RequiresMountsFor
/usr/local/sbin/nas-export-guard.sh                    Watchdog, Timer alle 5 Minuten
/etc/systemd/system/nas-export-guard.{service,timer}
/srv/nfs/netboot, /srv/nfs/home                        NAS-Mounts, fstab mit nofail
/mnt/BaerNas                                           vorbestehender Mount von /nfs/Data
/backup/BaerNas                                        TABU
~/gitrepos/raspirepo/lanboot                           Projektordner im Monorepo
```

### Repository

Die Projektdateien liegen in `lanboot/` des Monorepos `raspirepo`. Die drei
Steering-Dateien fuer den Agenten liegen eine Ebene hoeher in `.kiro/steering/`,
weil Kiro Steering nur von dort laedt, nicht aus einem Projektunterverzeichnis.

```
lanboot/DOKU/ARCHITEKTUR.md        wie es funktioniert, fuer Menschen
lanboot/DOKU/HOWTO.md              Handgriffe, fuer Menschen
lanboot/lanboot-stand.sh           Staende verwalten
lanboot/dnsmasq-pxe.conf           -> /etc/dnsmasq.d/pxe.conf
lanboot/nas-export-guard.sh        -> /usr/local/sbin/nas-export-guard.sh
lanboot/stand-<name>-cmdline.txt   Artefakte je Stand, von Menuepunkt 4-1 geschrieben
lanboot/stand-<name>-config.txt
lanboot/stand-<name>-fstab
lanboot/stand-<name>-pakete.txt    Paketliste, der brauchbare Weg zwei Staende zu vergleichen
lanboot/stand-<name>-marker        Kopie von /etc/lanboot-stand, traegt die Beschreibung
.kiro/steering/lanboot-regeln.md       Regeln, fuer den Agenten
.kiro/steering/lanboot-fallstricke.md  Fallstricke und Pruefkommandos
.kiro/steering/lanboot-aufbau.md       dieser Aufbau
```

Git kann die Rootfs-Bäume nicht tragen: keine Device-Nodes, keine uid/gid, kein setuid,
keine Hardlinks, und 74 000 Einträge über NFSv3. Deshalb nur Artefakte.

---

## Ausspielverfahren für Konfiguration

Bearbeitet wird **im Workspace**, ausgespielt mit

```bash
sudo install -o root -g root -m 0644 <datei> <ziel>
```

Danach `diff -q` gegen das Ziel, dann Dienst neu starten. Das hält die Versionsgeschichte
vollständig und der laufende Dienst sieht nie eine halbfertige Datei.

### dnsmasq-pxe.conf → /etc/dnsmasq.d/pxe.conf

```
port=0
interface=eth0
except-interface=wlan0
bind-interfaces
no-hosts
no-resolv
dhcp-range=192.168.188.255,proxy
pxe-service=0,"Raspberry Pi Boot"
enable-tftp
tftp-root=/srv/nfs/netboot/tftpboot
tftp-no-blocksize
#log-dhcp
```

`port=0` schaltet DNS ab, das macht die Fritz!Box. `bind-interfaces` bindet dnsmasq beim
Start an die Adresse von eth0 — ändert sie sich durch einen neuen Lease, braucht dnsmasq
einen Neustart; daher die Fritz-Reservierungen beibehalten.

`log-dhcp` ist seit 18.10.2026 aus. **Ohne die Zeile protokolliert dnsmasq keine einzige
DHCP-Zeile**, also auch nicht die Längenkontrolle des Boot-Strings, und ein im ROM
gescheiterter Startversuch hinterlässt gar keine Spur. Für Fehlersuche an der Bootkette
entkommentieren, ausspielen, neu starten. TFTP-Zeilen (`sent …`) kommen unabhängig davon.

### Pflichten in jedem Rootfs

`/dev/console` (c 5 1, Modus 600) und `/dev/null` (c 1 3, Modus 666) müssen existieren,
sonst bricht der Start ab, bevor der Kernel devtmpfs über `/dev` legt. `nfs-common` muss
installiert sein, sonst kann der Client sein Home nicht mounten — das Root-Dateisystem
selbst mountet der Kernel ohne Userspace-Werkzeug. Im Home muss eine `authorized_keys`
liegen; fehlt sie, gibt es `Permission denied (publickey,password)` bei einem einwandfrei
gebooteten Client. Dieser Fehler ist schon passiert.
