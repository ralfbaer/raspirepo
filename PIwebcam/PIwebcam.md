# webcam — Arbeitsstand (für Kiro, nicht für menschliche Leser)

Letzte Aktualisierung: 2026-10-20

## Status

**Funktionsfähig, mehrkamerafähig.** Beliebig viele USB-Webcams werden
erkannt und einzeln als MJPEG-Stream im Browser angeboten. Mit zwei
echten Kameras gleichzeitig geprüft.

```bash
cd /home/baer/gitrepos/raspirepo/PIwebcam
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py
```

## Dateien

| Datei | Inhalt |
|---|---|
| `webcam_stream.py` | Entrypoint: argparse (alle Defaults `None`!), `zugang_klaeren()`, `kameras_auflisten()`, Signale |
| `einstellungen.py` | Nur Datenklassen: `Kameraeinstellung`, `Zeiten`, `Dienstkonfiguration` + Standardwerte |
| `konfiguration.py` | YAML lesen/prüfen, CLI mischen, `kameras_automatisch()`, `bandbreite_pruefen()` |
| `kamera.py` | `Kameraquelle`, `Kameraregister`, `kameras_erkennen()`, `stabile_pfade()`, Format- und Farbumwandlung |
| `server.py` | `WebcamHandler` (Routing), `seiten_bauen()`, `Zugangsdaten` |
| `webcam_stream.yml` | Konfiguration, kommentiert, mit Standardwerten |
| `seite_uebersicht.html`, `seite_einzel.html`, `stil.css`, `webcam.js` | Oberfläche |
| `requirements.txt` | linuxpy 0.25.0, numpy 2.3.4, Pillow 11.3.0, PyYAML 6.0.3 — alle installiert |

`einstellungen.py` existiert nur, um den Importzyklus
`konfiguration` → `kamera` → Datentypen aufzubrechen. Nicht
zurückbauen.

Flache Module, kein Paketverzeichnis.

## Fehler, die gefunden und behoben wurden — nicht wieder einbauen

### 1. Naive Ratendrosselung halbiert die Bildrate

Bei Quellrate knapp über Zielrate fällt jeder zweite Frame ins
Sperrfenster. Gemessen: Quelle 16,6 fps, Soll 15, angekommen **7,5**.

Behoben durch Toleranz von einem halben, laufend geschätzten
Quellintervall:

```python
if jetzt < naechste_ausgabe - quellintervall / 2:
    continue
naechste_ausgabe = max(jetzt, naechste_ausgabe) + mindestabstand
```

### 2. FourCC hat vier Zeichen, der linuxpy-Name fünf

`set_format(b, h, "MJPEG")` → `TypeError: v4l2_fourcc() takes 4
positional arguments but 5 were given`. Der FourCC ist `MJPG`, der
Enum-Name `MJPEG`. Dafür gibt es die Tabelle `FOURCC` in `kamera.py`.

### 3. Gleitender Mittelwert über Kehrwerte ist verzerrt

`bildrate_ist` wurde als EWMA von `1/abstand` gebildet. Ein kurzer
Abstand ergibt einen riesigen Kehrwert. Gemeldet wurden 22,2 fps bei
tatsächlich 11,4.

Behoben: EWMA über **Intervalle** und **Bildgrößen**, Kehrwert erst bei
der Ausgabe. Server- und Clientmessung stimmen jetzt überein.

### 4. Stilles `except Exception` verdeckte die Ursache

`bandbreite_pruefen` verschluckte den Fehler der Kameraerkennung und
meldete dann eine falsche Warnung (59,9 statt 22,0 MB/s). Jetzt wird
protokolliert, und wenn Erkennungsdaten fehlen, wird das in der Meldung
gesagt statt still der ungünstigere Fall angenommen.

## Geprüfte Fakten

### Hardware

- **Zwei Kameras angeschlossen:**
  - `1e4e:0102` Cubeternet, nur YUYV, max. 640x480. Meldet 30 fps,
    liefert gemessen **16,66** (`--stream-mmap --stream-count=90`).
    `exposure_dynamic_framerate=0` ändert nichts, also nicht die
    Belichtungsnachführung. *Vermutung:* USB-Bandbreite.
  - `046d:082c` Logitech C615, **MJPEG und YUYV**, bis 1920x1080.
    Erreicht bei MJPEG den Sollwert (15,1 bei Soll 15).
- **Die C615 ist auf diesem Host instabil.** Fiel im Test aus,
  `journalctl -k`: "usb 1-1-port3: Cannot enable. Maybe the USB cable is
  bad?", "unable to enumerate USB device", danach wieder da.
  *Vermutung:* Stromversorgung. Hub mit Netzteil wäre der nächste
  Schritt.
- **`/dev/videoN` ist nicht stabil.** Die C615 war `/dev/video2`, nach
  erneutem Anstecken `/dev/video3`. Deshalb `/dev/v4l/by-id/`.
  Belegt: Der by-id-Pfad blieb über den Wechsel gültig.
- **Zwei gleichzeitige Zugriffe auf dasselbe Gerät zerstören die Rate**
  (15 → 0,9 fps). Deshalb genau ein Grabber je Kamera. **Beim Messen
  nie `v4l2-ctl` und den Dienst parallel laufen lassen** — das ist mir
  einmal passiert und hat einen falschen Messwert erzeugt.

### Software

- Kameraerkennung: `Frmsizetypes.DISCRETE` (Wert 1) unterscheidet echte
  Kameras von Pi-Plattformgeräten (`STEPWISE`, Wert 3). Belegt:
  `/dev/video0` fünf DISCRETE, `/dev/video14`/`15` nur STEPWISE.
  `Frmsizetypes` liegt in `linuxpy.video.raw`, **nicht** in `.device`.
- MJPEG-Frames haben variable Länge, deshalb Prüfung über `FFD8`/`FFD9`
  statt Länge. YUYV-Frames über die Länge — ein Frame mit 150020 statt
  153600 Byte trat real auf.
- Kodierung YUYV: 14 ms je Frame bei 640x480 (numpy 5,8 + Pillow 8,2).
  Bei MJPEG praktisch null.
- `iter_video_capture_devices()` liefert ein belegtes Gerät
  möglicherweise nicht. Dann fehlt die Kamera in der Erkennung.

## Entscheidungen und Begründung

1. **MJPEG über `multipart/x-mixed-replace`.** Kein JS nötig, kein
   ffmpeg nötig (nicht installiert, bräuchte `sudo`).
2. **Format pro Kamera automatisch: MJPEG wenn möglich, sonst YUYV.**
   Entscheidend, nicht Komfort: 1920x1080 wären als YUYV 124 MB/s und
   über USB 2.0 unmöglich.
3. **Stabile Gerätepfade `/dev/v4l/by-id/`** statt `/dev/videoN`.
   Zwingend bei mehreren Kameras, siehe oben.
4. **Je Kamera ein Grabber, gemeinsame Streamgrenze.** CPU, RAM und USB
   werden geteilt, stehen also nicht pro Kamera zur Verfügung.
5. **Neuester Frame in einer Variablen**, keine Warteschlange.
6. **`linuxpy` statt `v4l2-ctl`-Subprozess oder eigenem ioctl-Code.**
   Reines Python, kein Build, Reglersteuerung inklusive.
7. **Kein OpenCV.** 90 MB für etwas, das numpy und Pillow in 14 ms
   erledigen.
8. **YUYV→YCbCr direkt, nicht über RGB.** JPEG speichert intern YCbCr.
9. **Kameras nur bei Zuschauern offen**, 5 s Nachlauf.
10. **Standardbindung 127.0.0.1**, Netzfreigabe erfordert Passwort oder
    ausdrückliches `--ohne-anmeldung`. Löst die Freigabepflicht aus
    `zusammenarbeit.md` Regel 2 durch einen sicheren Standard, statt
    zu fragen.
11. **Passwort nie in der YAML**, nur `WEBCAM_PASSWORT` oder
    `--passwort`. Vorgabe aus `konfiguration.md`.
12. **YAML statt TOML.** Erst mit `tomllib` gebaut, dann auf die
    Projektvorgabe umgestellt (`.kiro/steering/konfiguration.md`).
    Dateiname `webcam_stream.yml`, gleichnamig zum Programm.
13. **Alle argparse-Defaults sind `None`.** Sonst ist die Rangfolge
    CLI > Datei > Standard nicht umsetzbar. **Wichtig beim Erweitern.**
14. **Seiten beim Start einmal bauen**, nicht pro Anfrage. Die
    Kameraliste ändert sich zur Laufzeit nicht, und das Verzeichnis
    liegt auf NFS.
15. **`html.escape` auf allen eingesetzten Texten.** Der Kameraname
    kommt aus dem USB-Deskriptor, also von außen.
16. **Alte Adressen `/stream.mjpg` und `/snapshot.jpg`** bleiben als
    Verweis auf die erste Kamera.
17. **Deutsche Bezeichner im Code**, auch Funktions- und
    Attributnamen. Ausnahmen: `main`, `argv`, Überschreibungen der
    Standardbibliothek (`do_GET`, `log_message`, `handle_error`).

## Messwerte

| Messung | Ergebnis |
|---|---|
| Kamera 1 (YUYV) im Dienst, Soll 15 | 12,5 fps, 21 KiB, 260 KiB/s |
| Kamera 2 (MJPEG) im Dienst, Soll 15 | 15,1 fps, 61 KiB, 912 KiB/s |
| Kamera 2 bei 1280x720 | 10,3 fps, 150 KiB, 1544 KiB/s |
| Beide gleichzeitig | 12,6 + 15,0 fps, 0 verworfen |
| Soll 5 fps, 320x240, Q60 | 4,9 fps, 7 KiB |

## Ungeprüft (nicht als gegeben behandeln)

- **Darstellung in einem echten Browser.** Kein Display am Pi. Geprüft
  ist die multipart-Struktur mit eigenem Parser, nicht die Anzeige. Das
  betrifft auch `webcam.js` (Pause, Vollbild, Reconnect, Status) und
  das Kachelraster der Übersicht mit mehreren Streams in einem Tab.
  **Größte offene Lücke.**
- TLS-Pfad (`--zertifikat`): kein Zertifikat erzeugt.
- Mehr als zwei Kameras.
- Vier gleichzeitige Streams flüssig (nur die Grenze ist geprüft).
- Dauerbetrieb: längster Lauf etwa 15 s. GIL-Verhalten mehrerer Grabber
  über Stunden unbekannt.
- `by-path` als Rückfall (Kamera ohne Seriennummer trat nicht auf).
- Leere YAML, falscher Typ in der YAML, `format: mjpeg` an einer Kamera
  ohne MJPEG. Code behandelt alle drei, nicht ausgelöst.
- IPv6-Pfad.
- Rolle von `/dev/video1`, Hardware-Encoder des Pi.

## Umgebungshinweis für künftige Sitzungen

Der Kiro-Agent wurde auf diesem Host vom OOM-Killer beendet (belegt:
`journalctl -k`, drei Kills am 20.10.2026 um 09:13:25, 09:14:45 und
09:15:58, je bei rund 1,42 GiB residentem Speicher). Ursache ist die
RAM-Knappheit des Hosts.

Konsequenz: Sitzungen kurz halten, große rekursive Leseoperationen über
NFS vermeiden. Diese Datei ist der Wiedereinstiegspunkt.

**Beim Testen:**
- Nur ein Prozess je Kameragerät.
- `control_bash_process` meldet "stopped", ohne dass der Prozess
  immer wirklich weg ist. Einmal blockierte ein Altprozess Port 8080
  und lieferte eine Antwort im alten Format, was wie ein Fehler
  aussah. Mit `pgrep -af webcam_stream.py` prüfen.
- Dateien für Tests vor dem Start des Prozesses schreiben; parallele
  Tool-Aufrufe sind sonst in der falschen Reihenfolge.

## Nächster Schritt

Keiner zwingend. Naheliegende Anschlüsse, wenn gewünscht:

1. Darstellung im Browser bestätigen (nur der Benutzer kann das).
2. USB-Hub mit Netzteil gegen den Ausfall der C615.
3. Autostart als systemd-Unit (braucht `sudo`, also Freigabe).
4. Aufzeichnung oder Zeitraffer — die Frames liegen im Grabber bereits
   als JPEG vor.
