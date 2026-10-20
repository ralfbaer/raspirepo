---
inclusion: fileMatch
fileMatchPattern: 'lanboot/**'
---

# Regeln für den Netboot-Aufbau

Diese Datei wird geladen, sobald an `lanboot/` gearbeitet wird. Sie enthält die Verbote und die
Arbeitsvereinbarungen für dieses Projekt. Sie beschreibt **keinen Zustand** —
der wird gemessen, nicht nachgelesen.

Arbeitsplatz ist der Pi 5B (`raspberrypi5`), Benutzer `baer`, Workspace
`~/gitrepos/raspirepo/lanboot`.

---

## Harte Verbote

**`/backup/BaerNas` auf dem 5B ist tabu.** Das ist das Backup des NAS. Dort wird nichts
gelöscht, nichts geändert, nichts analysiert, auch nicht zur Platzsuche. Alle Datenwege
laufen direkt über das NAS, nicht über dieses Verzeichnis und nicht über den 5B.

**Nichts löschen ohne ausdrückliche Anweisung.** Betriebsmodus, nicht Entwicklungsmodus.
Eine Frage wie „Das kann also weg?" ist eine Frage, keine Freigabe — dieser Fehler ist
schon passiert.

**Keinen Stand löschen, auf den ein TFTP-Symlink zeigt.** Danach startet das Gerät nicht
mehr. Vor jedem Löschen die Symlinks lesen, nicht den eigenen Zustandsspeicher befragen.

**Das Home der Ursprungsstände ist das gemeinsame Home des Geräts**, also
`home/<hostname>/baer`, nicht eine Standkopie. Darin liegen Schlüssel und `known_hosts`.
Beim Löschen eines Ursprungsstands wird nur der Baum entfernt, niemals dieses Home.

**Kein Rootfs zwischen laufenden Clients teilen.** Zwei Maschinen, die gleichzeitig in
dieselbe `/var/lib/dpkg`, `/var/log` und `/etc/machine-id` schreiben, zerstören sich den
Systemzustand. NFS schlichtet nicht. Teilen nur schreibgeschützt mit overlayfs.

**Keine Kopie eines laufenden Clients.** `cp -a` eines laufenden Systems liefert eine
inkonsistente Kopie: dpkg-Datenbank, Journal und offene Dateien sind mitten im Schreiben.
Client vorher herunterfahren.

**Rootfs nicht erneut von einer SD-Karte spiegeln.** In `bf7cac06` wurde `nfs-common`
direkt im Baum nachinstalliert. Ein weiterer `rsync` von der Karte würde
`/var/lib/dpkg/status` darüberbügeln: Dateien vorhanden, dpkg hält das Paket für nicht
installiert.

**`auto_initramfs=1` gehört nicht in die `config.txt` eines Netboot-Clients.** Das
NFS-Root mountet der Kernel direkt; ein initramfs drängt sich dazwischen und kann
`root=/dev/nfs` nicht auflösen.

**Die SD-Karte im 3B nicht entfernen, nicht formatieren, nichts darauf ablegen.** Sie
enthält ausschließlich `bootcode.bin`. Ohne sie startet der 3B nicht mehr, ein zusätzliches
`start.elf` oder eine `config.txt` darauf würde den Netboot aushebeln.

**Den 3B nicht ohne Not neu starten.** Vor der bootcode-Karte scheiterten grob zwei von
drei Startversuchen, und er wacht nach einem Fehlschlag nicht von allein auf. Mit Karte ist
es zuverlässig, aber ein Start braucht physisch Strom.

---

## Arbeitsvereinbarungen

**Vor jeder Änderung fragen.** Das gilt für Dateien im Workspace, für Konfiguration auf
Server und Clients, für das NAS und für die Dokumentation. Lesen, messen und
diagnostizieren darf ohne Rückfrage geschehen; schreiben, ausspielen, verschieben und
löschen nicht.

Die Frage soll den **vollständigen Plan** enthalten, damit eine einzige Antwort genügt.
Alle Fragen auf einmal stellen, dann durcharbeiten, nicht schrittweise rückfragen.

**Eine Rückfrage des Benutzers ist keine Freigabe.** Auch eine ungeduldige nicht. Erst ein
„ja", „los" oder eine ausdrückliche Anweisung.

**Commits macht der Benutzer**, wenn eine Aufgabe fertig ist. Nie von sich aus committen.

**Sprache Deutsch, englische Fachbegriffe bevorzugt.** Keine eingedeutschten Ersatzwörter
für etablierte Begriffe: `userspace`, `kernel space`, `boot`, `mount`, `export`, `symlink`,
`lease`, `timer`, `fence`. Wo zwei englische Varianten umlaufen, die gängigere nehmen.

**Dateien im Repository sind umlautfrei.** Scripte laufen gegen die busybox-Shell des NAS
und über SSH-Strecken mit unklarem Encoding.

**Namen statt IP-Adressen**, wo es geht. Drei zwingende Ausnahmen: `nfsroot=` in der
`cmdline.txt`, `dhcp-range` in der dnsmasq-Konfiguration, und der TFTP-Selbsttest auf dem
Server selbst.

**Beim Löschen von Verzeichnissen `rmdir` statt `rm -rf`**, wo möglich: es weigert sich bei
nicht-leeren Verzeichnissen und ist damit seine eigene Kontrolle. Bei Rootfs-Bäumen geht
das nicht, dort tritt eine getippte Bestätigung an seine Stelle.

**Vor unumkehrbaren Schritten fragen.** Beim OTP-Bit des 3B wurde so verfahren.

**Nicht raten, nachsehen.** Die Fehler dieses Projekts kamen daher, dass
Prosa-Dokumentation über einen echten Paketmitschnitt gestellt wurde, eine MAC aus einer
IPv6-Adresse ohne Blick auf das Interface abgeleitet wurde, `/root` als Home angenommen
statt `getent passwd` gelesen wurde, DHCP-Runden in einem Zeitfenster einem einzigen
Startvorgang zugeschrieben wurden, `findmnt` mit mehreren Zielen aufgerufen wurde, und
`test -w` als unprivilegierter Benutzer für eine Defektmeldung gehalten wurde. Messen,
dann sagen.

**Keine Zustandsdokumente anlegen.** Eine Datei, die den aktuellen Zustand behauptet, ist
veraltet, sobald sie geschrieben ist, sieht aber amtlich aus und verleitet zum Zitieren
statt zum Messen. Zustand kommt aus Messung, nie aus einer Datei.

**Wenige große Schreibvorgänge statt vieler kleiner**, weil jede Unterbrechung
Arbeitszeit kostet.

---

## Kiro-Umgebung

Rückfragen regelt `~/.kiro/settings/permissions.yaml`. Sie liegt außerhalb des
Repositorys, ist nicht versioniert, und der Agent **kann sie nicht schreiben** —
Schreibzugriff auf `~/.kiro/settings/` ist hart gedenied. Änderungen muss der Benutzer
ablegen, danach Kiro neu starten.

`deny` geht vor `ask` vor `allow`, scope-unabhängig. Bei `shell` ist `*` die einzige
Wildcard; `**`, `?` und Zeichenklassen gelten nur bei `fs_read` und `fs_write`. Ein
Leerzeichen vor dem abschließenden `*` schließt das nackte Kommando aus: `git push *`
greift bei `git push` nicht, `git push*` schon. Ein `ask` lässt sich durch kein `allow`
zurückholen; eine Ausnahme gehört in das `exclude` derselben Regel.

Kiro schreibt selbst in die Datei — jedes „Always allow" hängt eine Zeile an. Sie driftet.
