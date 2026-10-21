# webcam — Architektur und technische Details

Stand: 2026-10-21

Zweck: Die Bilder einer oder mehrerer USB-Webcams als Live-Stream im
Browser anzeigen.

## 1. Überblick

```
Kamera A (MJPEG) ──JPEG───────────────────┐
/dev/v4l/by-id/...                        │
                                    Grabber-Thread A ──┐
                                                       │
Kamera B (YUYV) ──roh──► numpy ──► Pillow ──► JPEG     │   neuester
/dev/v4l/by-id/...  614400 B/Frame   14 ms             ├─► Frame je
                                    Grabber-Thread B ──┘   Kamera
                                                            │
                                               ┌────────────┴───────────┐
                                        HTTP-Thread            HTTP-Thread
                                        (ein Zuschauer)        (ein Zuschauer)
                                               │                        │
                                          MJPEG-Strom              MJPEG-Strom
                                               ▼                        ▼
                                            Browser                 Browser
```

Je Kamera ein Grabber-Thread, der genau den neuesten JPEG-Frame in einer
Variablen hält. Alle HTTP-Threads lesen daraus. Es gibt keine
Warteschlange und keinen Ringpuffer.

Das folgt direkt aus der Hardware. Bei 1,8 GiB RAM auf einem
NFS-Wurzeldateisystem ist jede Pufferung von Bildfolgen unangebracht,
und mehrere Zuschauer dürfen dieselbe Kamera nicht mehrfach öffnen: Zwei
gleichzeitige Zugriffe auf `/dev/video0` drückten im Test die Bildrate
von 15 auf 0,9 fps.

## 2. Komponenten

Struktur nach dem `projektstruktur.md`-Schema (am 2026-10-21 umgestellt):
Hauptprogramm, YAML und Startskript im Projektordner, die Code-Module im
Paket `submodule/`, die Oberfläche in `resources/`, die Doku in `DOKU/`.

| Datei | Aufgabe |
|---|---|
| `webcam_stream.py` | Entrypoint (Projektordner). Argumente, Protokoll, Zugangsregel, Auskunftsbefehle, Signale. |
| `webcam_stream.yml` | Konfiguration mit Standardwerten, kommentiert (Projektordner). |
| `webcam_stream.sh` | Startskript, ruft das Programm über das gemeinsame venv auf. |
| `submodule/__init__.py` | Paketmarker. |
| `submodule/einstellungen.py` | Nur Datenklassen und Standardwerte. Keine Logik, keine Hardware. |
| `submodule/konfiguration.py` | `webcam_stream.yml` lesen, prüfen, mit der Kommandozeile zusammenführen. |
| `submodule/kamera.py` | V4L2-Zugriff, Grabber, Formatwahl, Erkennung, `Kameraregister`. |
| `submodule/server.py` | HTTP-Adressen, MJPEG-Rahmenbildung, Anmeldung (Formular + Sitzung), optional TLS. |
| `resources/seite_uebersicht.html`, `resources/seite_einzel.html`, `resources/seite_anmelden.html` | Vorlagen, beim Start einmal gefüllt. |
| `resources/stil.css`, `resources/webcam.js` | Gestaltung und Bedienlogik der Seiten. |
| `requirements.txt` | Gepinnte Abhängigkeiten. |

`submodule/einstellungen.py` existiert, um einen Importzyklus zu
vermeiden: `konfiguration.py` braucht `kamera.py` für die Erkennung, und
`kamera.py` braucht die Datentypen. Die Typen liegen deshalb in einem
dritten Modul, das von keinem der beiden abhängt.

Die Code-Module liegen im Paket `submodule/` und werden durchgängig mit
`submodule.`-Präfix importiert, auch untereinander
(`from submodule.kamera import …`). `webcam_stream.py` bleibt als
Hauptprogramm im Projektordner; weil es als Skript mit absolutem Pfad
gestartet wird, liegt der Projektordner in `sys.path`, und
`import submodule.…` löst auf, ohne dass `sys.path` von Hand ergänzt
werden muss. Die frühere flache Modulstruktur wurde mit dem Umbau auf
das `projektstruktur.md`-Schema aufgegeben.

Die statischen Dateien der Oberfläche (HTML-Vorlagen, CSS, JavaScript)
liegen in `resources/`. `server.py` liegt in `submodule/` und liest sie
beim Start aus `Path(__file__).resolve().parent.parent / "resources"`.
Die gleichnamige Konfigurationsdatei `webcam_stream.yml` bleibt neben dem
Programm, wie es die Projektstruktur verlangt.

## 3. Konfiguration

### 3.1 Rangfolge

```
Kommandozeile  >  webcam_stream.yml  >  Standardwerte in einstellungen.py
```

Damit das funktioniert, haben **alle** argparse-Argumente den
Standardwert `None`, nicht den fachlichen Standard. Nur so ist
unterscheidbar, ob der Anwender etwas angegeben hat. Der fachliche
Standard kommt aus `einstellungen.py`.

### 3.2 Verhalten bei Problemen

| Fall | Verhalten | geprüft |
|---|---|---|
| Datei fehlt | Hinweis, Standardwerte, Weiterlauf | ja |
| Datei leer | Warnung, Standardwerte | nein |
| `--konfiguration` zeigt auf nichts | Abbruch, Exit 2 | ja |
| YAML-Syntaxfehler | Abbruch mit Pfad, Zeile, Spalte | ja |
| unbekannter Schlüssel | Abbruch mit Liste der erlaubten | ja |
| Wert außerhalb des Bereichs | Abbruch mit Grenzwert | ja |
| falscher Typ | Abbruch mit gefundenem Typ | nein |

Eine fehlende Datei ist kein Fehler, eine fehlerhafte schon. Ein stiller
Rückfall auf Standardwerte würde eine Fehlkonfiguration verschleiern.

Unbekannte Schlüssel werden abgelehnt, nicht übergangen. Ein übergangener
Tippfehler bedeutet eine wirkungslose Einstellung, ohne dass es
auffällt.

Gelesen wird ausschließlich mit `yaml.safe_load`. `yaml.load` kann
beliebige Python-Objekte erzeugen und wird nicht verwendet.

### 3.3 Parameter

Dienstebene:

| Schlüssel | Typ | Standard | Wirkung |
|---|---|---|---|
| `host` | Text | `127.0.0.1` | Bindeadresse |
| `port` | 1–65535 | `8080` | Portnummer |
| `titel` | Text | `Webcam` | Überschrift |
| `protokoll` | debug/info/warnung/fehler | `info` | Protokollstufe |

`anmeldung`:

| Schlüssel | Typ | Standard | Wirkung |
|---|---|---|---|
| `benutzer` | Text | `webcam` | Benutzername für HTTP Basic |
| `ohne_anmeldung` | bool | `false` | Netzfreigabe ohne Passwort erlauben |
| `zertifikat` | Pfad | leer | PEM-Datei für TLS |
| `schluessel` | Pfad | leer | privater Schlüssel, falls getrennt |

Das Passwort steht bewusst **nicht** in der Datei, sondern in
`WEBCAM_PASSWORT`.

`grenzen` (alle Zeiten in Sekunden):

| Schlüssel | Bereich | Standard | Wirkung |
|---|---|---|---|
| `max_streams` | 1–64 | `4` | gleichzeitige Streams über alle Kameras |
| `leerlauf` | 0–3600 | `5.0` | Nachlauf bis zur Freigabe der Kamera |
| `wiederholung` | 0,1–3600 | `2.0` | Pause vor erneutem Öffnen nach Fehler |
| `erstes_bild` | 0,5–300 | `8.0` | Wartezeit auf das erste Bild |
| `stream_stille` | 0,5–3600 | `10.0` | Abbruch eines stummen Streams |
| `fehlanmeldung` | 0–60 | `0.5` | Verzögerung nach falschem Passwort |
| `usb_richtwert` | ≥1e6 | `24000000` | Byte/s, nur für die Startwarnung |

`vorgaben` gelten für alle Kameras ohne eigenen Wert: `aufloesung`,
`fps`, `qualitaet`, `format`.

`kameras` ist eine Liste. Je Eintrag: `geraet` (Pflicht), `name`,
`kennung`, `aufloesung`, `fps`, `qualitaet`, `format`, `regler`.

## 4. Mehrere Kameras

### 4.1 Erkennung

`kameras_erkennen()` in `kamera.py` nutzt `iter_video_capture_devices()`
und filtert nach dem Typ der Bildgrößen:

- **echte Kamera:** meldet feste Größen (`Frmsizetypes.DISCRETE`)
- **Verarbeitungseinheit des Pi:** meldet Bereiche (`STEPWISE`)

Belegt am 20.10.2026: `/dev/video0` liefert fünf DISCRETE-Einträge,
`/dev/video14` und `/dev/video15` (bcm2835-isp) je nur STEPWISE. Damit
fallen `bcm2835-isp`, `bcm2835-codec` und `rpi-hevc-dec` heraus, ohne
dass Treibernamen fest verdrahtet werden müssen.

Der Metadaten-Node der Kamera (`/dev/video1`) taucht gar nicht auf, weil
er keine Video-Capture-Fähigkeit meldet.

Die Erkennung läuft genau einmal pro Start. Sie öffnet jedes Videogerät
des Systems; ein zweiter Durchlauf würde auch gerade belegte Geräte
anfassen.

### 4.2 Stabile Gerätepfade

**Dies ist der wichtigste Punkt beim Mehrkamerabetrieb.**

Die Nummern unter `/dev/videoN` hängen von der Erkennungsreihenfolge ab.
Belegt: Dieselbe Logitech C615 war erst `/dev/video2`, nach erneutem
Anstecken `/dev/video3`. Eine Konfiguration mit `/dev/video2` hätte
danach auf die andere Kamera gezeigt.

Verwendet werden deshalb die udev-Symlinks:

| Verzeichnis | gebunden an | Wahl |
|---|---|---|
| `/dev/v4l/by-id/` | Hersteller, Modell, Seriennummer | erste Wahl |
| `/dev/v4l/by-path/` | USB-Port | bei baugleichen Kameras ohne Seriennummer |

`ErkannteKamera.empfohlener_pfad` liefert by-id, sonst by-path, sonst
`/dev/videoN`. Die automatische Erkennung und die Ausgabe von
`--kameras-liste` verwenden diesen Pfad.

Belegt: Nach dem Wegfall und Wiedererscheinen der C615 blieb
`usb-046d_HD_Webcam_C615_90CE6170-video-index0` unverändert, während die
Nummer wechselte.

Nur der `-video-index0`-Link wird genommen; `index1` ist der
Metadaten-Node.

Vergleiche zwischen Konfiguration und Erkennung laufen über
`geraet_aufloesen()` (`Path.resolve`), weil die Konfiguration einen
Symlink nennen darf, die Erkennung aber `/dev/videoN` meldet.

### 4.3 Kennungen

Jede Kamera bekommt eine URL-sichere Kennung für
`/kamera/<kennung>/...`. Gebildet aus dem Namen: Umlaute ersetzt,
Nicht-Alphanumerisches zu `-`, auf 32 Zeichen gekürzt, bei Dopplung
numeriert.

`namen_aufraeumen()` entfernt vorher die Wiederholung, die UVC-Kameras
im Feld `card` oft liefern: "USB2.0 Camera: USB2.0 Camera" wird
"USB2.0 Camera" und damit die Kennung `usb2-0-camera` statt
`usb2-0-camera-usb2-0-camera`.

### 4.4 Gemeinsame Grenzen

`Kameraregister` hält die Quellen und verwaltet die Streamplätze
**gemeinsam**: CPU, RAM und USB-Bandbreite werden geteilt und stehen
nicht pro Kamera zur Verfügung. Der fünfte Zuschauer bekommt 503, auch
wenn er die erste Kamera ist, die noch keinen hat.

## 5. Bildformate

### 5.1 Zwei Wege

| | MJPEG | YUYV |
|---|---|---|
| Wer komprimiert | die Kamera | der Pi |
| CPU je Frame | praktisch null | 14 ms bei 640x480 |
| USB-Last 640x480@30 | rund 2,3 MB/s | 18,4 MB/s |
| Qualität einstellbar | nein, Kamera bestimmt | ja, über `qualitaet` |
| Auflösung über 640x480 | möglich | an USB 2.0 nicht machbar |

Bei `format: auto` wird MJPEG genommen, wo die Kamera es anbietet. Das
ist fast immer richtig: 1920x1080 wären als YUYV rund 124 MB/s und über
USB 2.0 unmöglich.

Die Wahl trifft `Kameraquelle._format_bestimmen()` beim Öffnen, nicht
die Konfiguration. Grund: Nur beim Öffnen ist sicher bekannt, was das
Gerät wirklich anbietet.

### 5.2 FourCC-Falle

V4L2 identifiziert Formate über einen FourCC, also genau vier Zeichen.
linuxpy meldet Motion-JPEG als `MJPEG` (fünf Zeichen), der FourCC lautet
aber `MJPG`. `set_format` entpackt den String in
`v4l2_fourcc(a, b, c, d)` und scheitert an fünf Zeichen mit
`TypeError: v4l2_fourcc() takes 4 positional arguments but 5 were given`.

Deshalb gibt es die Tabelle `FOURCC` in `kamera.py`, die den gemeldeten
Namen auf den FourCC abbildet. Das war ein echter Fehler im ersten
Entwurf, gefunden beim Streamen der C615.

### 5.3 Prüfung der Frames

Die Prüfung muss sich nach dem Format richten:

- **YUYV:** Länge muss `breite*hoehe*2` sein. Trat real auf: beim
  Formatwechsel kam ein Frame mit 150020 statt 153600 Byte. Ohne Prüfung
  würde `numpy.reshape` eine Ausnahme werfen.
- **MJPEG:** Länge ist variabel, also nicht prüfbar. Stattdessen werden
  die Rahmenmarken `FFD8` und `FFD9` geprüft (`ist_jpeg()`).

Verworfene Frames werden gezählt und stehen im Status.

### 5.4 Farbraum bei YUYV

Der Weg führt **nicht** über RGB. JPEG speichert intern YCbCr, also wird
YUYV nur auf YCbCr 4:4:4 hochgerechnet und direkt so an Pillow übergeben
(`Image.frombuffer("YCbCr", ..., "raw", "YCbCr", 0, 1)`). Die
RGB-Transformation samt Rücktransformation beim Kodieren entfällt.

Chroma-Upsampling per Duplizierung statt Interpolation: JPEG tastet die
Chroma anschließend ohnehin wieder unter.

## 6. Drosselung der Bildrate

Nicht trivial, deshalb ausführlich. Ein naiver Rate-Limiter
(`if jetzt < naechste_ausgabe: continue`) halbiert die Ausgaberate,
sobald die Quelle nur knapp schneller liefert als gewünscht. Gemessen:
Quelle 16,6 fps, Soll 15 fps, angekommen **7,5 fps**. Jeder zweite Frame
fiel in das Sperrfenster.

Umsetzung jetzt: Ein Frame wird akzeptiert, wenn
`jetzt >= naechste_ausgabe - quellintervall/2`. Das Quellintervall wird
als gleitender Mittelwert der Eingangsabstände geschätzt. Der Zeitplan
wird mit `naechste_ausgabe = max(jetzt, naechste_ausgabe) + mindestabstand`
fortgeschrieben, damit sich kein Drift aufbaut.

Nachgemessen: Soll 15 → 15,1 ist; Soll 5 → 4,9 ist.

Jeder Frame wird abgeholt, auch der verworfene. Frames im Treiberpuffer
liegen zu lassen würde die Latenz erhöhen.

## 7. Messung der Ist-Werte

Die Statusanzeige mittelt über **Intervalle und Bildgrößen**, nicht über
die Bildrate selbst:

```python
intervall_ist = intervall_ist * 0.8 + abstand * 0.2
bildrate_ist  = 1 / intervall_ist
datenrate     = groesse_ist / intervall_ist
```

Ein gleitender Mittelwert über Kehrwerte ist verzerrt: Ein einzelner
sehr kurzer Abstand ergibt einen riesigen Kehrwert und zieht das
Ergebnis nach oben. Beobachtet wurden so 22,2 fps bei tatsächlich
11,4 fps. Nach der Korrektur stimmen Server- und Clientmessung überein
(12,5 gegen 12,6 fps; 15,1 gegen 15,0 fps).

## 8. Lebenszyklus der Kameras

`Kameraquelle` zählt Zuschauer je Kamera. Von 0 auf 1 startet den
Grabber, der Übergang auf 0 stoppt ihn nach `leerlauf` Sekunden
Nachlaufzeit. Die Nachlaufzeit verhindert, dass ein Seitenreload die
Kamera neu initialisieren muss.

Im Ruhezustand ist kein Gerät geöffnet, es läuft kein Thread und es wird
keine USB-Bandbreite belegt.

`snapshot.jpg` nutzt denselben Mechanismus: anmelden, auf einen Frame
warten, abmelden.

Bricht eine Kamera weg, fängt `_grabber_schleife()` die Ausnahme, weckt
wartende Clients und öffnet nach `wiederholung` Sekunden erneut.
Wiederholte identische Fehler werden zusammengefasst (bei Versuch 5, 50
und dann alle 500), damit ein dauerhaft fehlendes Gerät das Protokoll
nicht füllt.

## 9. Protokoll: warum MJPEG über HTTP

Gewählt: `multipart/x-mixed-replace` mit JPEG-Einzelteilen, angezeigt in
einem schlichten `<img>`-Tag.

Begründung:

- Funktioniert in jedem Browser ohne JavaScript, ohne Videocontainer.
- Kameras ohne eigene Komprimierung erzwingen ohnehin eine Kodierung auf
  dem Host; Kameras mit MJPEG liefern bereits das Format, das gebraucht
  wird. In beiden Fällen ist JPEG der direkte Weg.
- `ffmpeg` und GStreamer sind nicht installiert (belegt:
  `which ffmpeg fswebcam streamer mjpg_streamer gst-launch-1.0` liefert
  nichts). Eine Installation bräuchte `sudo`.

Preis: MJPEG komprimiert schlechter als H.264. Gemessen 260 KiB/s für
640x480 YUYV-Kamera und 912 KiB/s für die MJPEG-Kamera je Zuschauer. Im
Heimnetz unkritisch, über Mobilfunk nicht.

### 9.1 Verworfene Alternativen

| Alternative | Warum nicht |
|---|---|
| WebRTC | Signalisierung, STUN/TURN, Codec-Aushandlung. Vielfacher Aufwand für einen Stream im eigenen Netz. |
| HLS oder DASH | Segmentierung schreibt ständig Dateien. Wurzeldateisystem liegt auf NFS, `/tmp` kostet RAM. Zusätzlich Latenz von Sekunden. |
| `ffmpeg`/`mjpg_streamer` als Subprozess | Nicht installiert, Installation braucht `sudo`. |
| OpenCV | Rund 90 MB installiert. Für YUYV→JPEG reichen numpy und Pillow. Unverhältnismäßig bei 1,8 GiB RAM. |
| Hardware-Encoder des Pi (`bcm2835-codec`) | Erzeugt H.264, nicht JPEG, und bräuchte Container plus Player. Bei MJPEG-Kameras ohnehin gegenstandslos. |
| TOML statt YAML für die Konfiguration | Erst so gebaut, dann auf die Projektvorgabe YAML umgestellt (`projektstruktur.md`: gleichnamige YAML beim Programm). |
| Kameraliste über JavaScript aus `status.json` aufbauen | Die Liste ändert sich zur Laufzeit nicht. Serverseitig einmal bauen funktioniert auch ohne JavaScript. |

## 10. HTTP-Adressen

| Pfad | Antwort | Anmerkung |
|---|---|---|
| `GET /` | `text/html` | Übersicht aller Kameras |
| `GET /anmelden` | `text/html` | Anmeldeformular |
| `POST /anmelden` | 303 bzw. 401 | Anmeldung abschicken |
| `GET /abmelden` | 303 | Sitzung beenden, Cookie löschen |
| `GET /stil.css` | `text/css` | `max-age=3600`, ohne Anmeldung erreichbar |
| `GET /webcam.js` | `text/javascript` | `max-age=3600` |
| `GET /status.json` | `application/json` | Zustand aller Kameras |
| `GET /kamera/<kennung>` | `text/html` | Einzelansicht |
| `GET /kamera/<kennung>/stream.mjpg` | `multipart/x-mixed-replace` | fortlaufend |
| `GET /kamera/<kennung>/snapshot.jpg` | `image/jpeg` | Einzelbild |
| `GET /stream.mjpg` | wie oben | erste Kamera, alte Adresse |
| `GET /snapshot.jpg` | wie oben | erste Kamera, alte Adresse |

Die beiden Adressen ohne Kameraangabe bleiben erhalten, damit Lesezeichen
aus der Einkamera-Fassung weiter funktionieren.

Jeder Teil des MJPEG-Stroms trägt `Content-Type: image/jpeg` und
`Content-Length`. Letzteres ist nicht zwingend, erlaubt einem Client aber
das Zerlegen ohne Suche nach der Grenzmarke.

`protocol_version = "HTTP/1.1"`, aber der Stream setzt
`close_connection = True` und `Connection: close`, weil er weder eine
Gesamtlänge kennt noch chunked kodiert ist.

Kennungen werden ausschließlich über ein `dict` aufgelöst, nie über das
Dateisystem. Ein Pfadwechsel über `..` ist damit ausgeschlossen.

## 11. Sicherheit

### 11.1 Zugangsregel

| Bindung | Passwort | Verhalten |
|---|---|---|
| Loopback (Standard) | keins | läuft, Hinweis im Protokoll |
| Loopback | gesetzt | läuft mit Anmeldung |
| im Netz erreichbar | gesetzt | läuft, Warnung bei fehlendem TLS |
| im Netz erreichbar | keins | **Abbruch, Exit 2**, mit Anleitung |
| im Netz erreichbar | `--ohne-anmeldung` | läuft, deutliche Warnung |

Geprüft: `--host 0.0.0.0` ohne Passwort bricht ab. Mit Passwort wird ein
nicht angemeldeter Seitenaufruf auf `/anmelden` umgeleitet (303),
Unterressourcen (Stream, Snapshot, `status.json`) antworten mit 401. Mit
gültiger Sitzung oder gültigem Basic-Kopf antworten alle Adressen mit
200.

### 11.2 Anmeldeverfahren: Formular und Sitzung

Ist ein Passwort gesetzt, läuft der Zugang über ein Anmeldeformular und
eine Sitzung per Cookie, **nicht** über HTTP-Basic. Grund: In verwalteten
Browsern ist HTTP-Basic teils administrativ abgeschaltet; dann erscheint
weder ein Anmeldefenster noch werden Zugangsdaten in der URL akzeptiert.
Ein Formular umgeht das, weil es ein gewöhnlicher POST ist.

Ablauf:

- `GET /anmelden` liefert das Formular (Felder `benutzer`, `passwort`).
- `POST /anmelden` prüft die Felder mit `secrets.compare_digest`. Bei
  Erfolg wird ein zufälliges Token (`secrets.token_urlsafe(32)`) erzeugt,
  in `Sitzungsverwaltung` abgelegt und als Cookie gesetzt
  (`webcam_sitzung=...; Path=/; HttpOnly; SameSite=Strict`, bei TLS
  zusätzlich `Secure`). Danach 303 auf `/`. Bei Fehlschlag:
  `fehlanmeldung`-Verzögerung und das Formular erneut mit Hinweis (401).
- Jede geschützte Anfrage prüft das Cookie gegen die
  `Sitzungsverwaltung`.
- `GET /abmelden` entfernt die Sitzung und löscht das Cookie
  (`Max-Age=0`).

`Sitzungsverwaltung` hält die Token mit Ablaufzeitpunkt (monotone Uhr)
in einem `dict`, geschützt durch ein `threading.Lock`, weil der Server
mehrere Anfragen parallel bedient. Die Ablage ist flüchtig: Nach einem
Neustart des Dienstes müssen sich alle neu anmelden. Die Gültigkeitsdauer
ist fest (`STANDARD_SITZUNGSDAUER`, 12 Stunden in `einstellungen.py`) und
bewusst nicht konfigurierbar.

Ein gültiger HTTP-Basic-Kopf wird weiterhin akzeptiert, damit Werkzeuge
wie `curl` unverändert arbeiten. Das Formular ist der Weg für Browser,
Basic der Weg für Skripte.

CSS und JavaScript sind ohne Anmeldung erreichbar, damit das
Anmeldeformular gestaltet ist; sie enthalten keine Kameradaten.

### 11.3 Weitere Maßnahmen

- Passwortvergleich durchgehend mit `secrets.compare_digest` statt `==`.
- `fehlanmeldung`-Verzögerung (Standard 0,5 s) nach jedem falschen
  Passwort, sowohl beim Formular als auch beim Basic-Rückfall.
- Passwort ausschließlich über `WEBCAM_PASSWORT` oder `--passwort`,
  **nicht** über die Konfigurationsdatei. Die Datei ist zum Einchecken
  gedacht.
- Optional TLS über `--zertifikat` und `--schluessel`.
- `max_streams` begrenzt gleichzeitige Streams.
- `noindex, nofollow` in den Seiten.
- **Alle eingesetzten Texte werden mit `html.escape` behandelt.** Das ist
  nicht Formsache: Der Kameraname kann aus dem USB-Deskriptor des Geräts
  stammen (Feld `card`), also aus einer Quelle, die das Projekt nicht
  kontrolliert. Ein Gerät mit `<script>` im Namen soll nichts bewirken.
- Konfigurationswerte werden auf Typ und Bereich geprüft, bevor sie
  benutzt werden. Die Datei ist Eingabe von außen.

### 11.4 Ausdrücklich nicht gelöst

- **Ohne TLS gehen Passwort und Sitzungs-Cookie im Klartext durchs
  Netz.** Das Passwort steht im POST-Körper, das Cookie in jedem
  Folgeaufruf; beides ist im LAN mitlesbar. Das Formular ist also eine
  Bedienlösung für die Browser-Sperre, keine Sicherheitsverbesserung
  gegenüber Basic. Das Programm warnt beim Start. Echten Schutz gibt erst
  TLS oder ein SSH-Tunnel.
- Nur ein Benutzer und ein Passwort für alle Kameras, keine
  Benutzerverwaltung, keine Rechtetrennung zwischen Kameras.
- Kein CSRF-Token am Anmeldeformular. `SameSite=Strict` am Cookie
  begrenzt das Risiko; für einen Einbenutzer-Heimdienst vertretbar.
- **Der TLS-Pfad ist ungetestet.** Es wurde kein Zertifikat erzeugt.
- Kein Schutz gegen einen Angreifer, der bereits Zugriff auf den Pi hat.

## 12. Geprüfte Umgebung

### 12.1 Host

| Eigenschaft | Wert | Belegstelle |
|---|---|---|
| Modell | Raspberry Pi 4 Model B Rev 1.1 | `grep Model /proc/cpuinfo` |
| RAM | 1.888.904 kB (≈ 1,80 GiB) | `grep MemTotal /proc/meminfo` |
| Kernel | 6.18.50 | `v4l2-ctl --all` |
| Swap | ausschließlich `/dev/zram0`, zstd | `swapon --show` |
| Lokale Datenträger | keine | `lsblk` |
| `/` und `/home/baer` | NFSv3 von `192.168.188.26`, `hard` | `mount` |
| `/tmp` | tmpfs, 923 M (im RAM) | `df -h /tmp` |
| USB-Controller | VL805 über PCIe, dazu VIA-Hub `2109:3431` | `lsusb` |
| Python | 3.13.5 im venv `/home/baer/gitrepos/raspirepo/.venv` | `python --version` |

Konsequenzen für jede Designentscheidung:

- Arbeitsspeicher ist knapp, zram-Swap liegt selbst im RAM. Pufferung
  von Bildfolgen ist keine Option.
- Jeder Dateizugriff unter `/` und `/home/baer` geht über das Netz.
  Deshalb werden Seiten, CSS und JS einmal beim Start gelesen, und es
  werden keine Frames auf Platte geschrieben.
- Fällt der NFS-Server aus, blockiert der Dateizugriff (`hard`-Mount).
  Der laufende Stream ist davon nicht betroffen, weil er vollständig im
  Speicher arbeitet.

### 12.2 Kamera 1: einfache UVC-Kamera

| Eigenschaft | Wert |
|---|---|
| USB-Kennung | `1e4e:0102` Cubeternet GL-UPC822 |
| Name (`card`) | `USB2.0 Camera: USB2.0 Camera` |
| Stabiler Pfad | `/dev/v4l/by-id/usb-Etron_Technology__Inc._USB2.0_Camera-video-index0` |
| Pixelformat | **nur** `YUYV` 4:2:2 |
| Auflösungen | 640x480, 352x288, 320x240, 176x144, 160x120 |
| Gemeldete Bildrate | 30,000 (30/1), `v4l2-ctl --get-parm` |
| **Tatsächliche Bildrate** | **16,66 fps**, `--stream-mmap --stream-count=90` |

Die Lücke zwischen gemeldeten 30 und gemessenen 16,66 fps ist
reproduzierbar. Die Belichtungsnachführung ist **nicht** die Ursache: Mit
`exposure_dynamic_framerate=0` wurden erneut 16,66 fps gemessen.

*Vermutung, nicht geprüft:* Die isochrone USB-Bandbreite reicht nicht.
640×480×2×30 ≈ 18,4 MB/s liegt nahe an der praktischen Grenze von USB
2.0, und die Kamera hängt hinter einem Hub. 16,66 fps entspricht exakt
60 ms je Frame.

Regler: `auto_exposure`, `brightness`, `contrast`,
`exposure_dynamic_framerate`, `exposure_time_absolute`, `gamma`, `hue`,
`power_line_frequency`, `saturation`, `sharpness`,
`white_balance_automatic`, `white_balance_temperature`.

### 12.3 Kamera 2: Logitech C615

| Eigenschaft | Wert |
|---|---|
| USB-Kennung | `046d:082c`, Seriennummer `90CE6170` |
| Stabiler Pfad | `/dev/v4l/by-id/usb-046d_HD_Webcam_C615_90CE6170-video-index0` |
| Pixelformate | `MJPEG`, `YUYV` |
| Auflösungen | 1920x1080 bis 160x120, 15 Stufen |
| Erreichte Bildrate | 15,1 fps bei 640x480 (Soll 15), 10,1 bei 1280x720 |

**Diese Kamera ist auf diesem Host instabil.** Sie fiel während eines
Tests aus, der Kernel meldete:

```
usb 1-1-port3: Cannot enable. Maybe the USB cable is bad?
usb 1-1-port3: attempt power cycle
usb 1-1-port3: unable to enumerate USB device
```

Kurz darauf war sie wieder da, mit neuer Gerätenummer. *Vermutung, nicht
geprüft:* Stromversorgung oder Kabel. Ein USB-Hub mit eigenem Netzteil
wäre der nächste Schritt.

Der Vorfall war unfreiwillig der Test für den Wegfall einer Kamera im
Betrieb: Die andere Kamera lief weiter, der Dienst antwortete mit 503
und blieb am Leben.

### 12.4 Keine CSI-Kamera

`rpicam-hello --list-cameras` meldet "No cameras available!". libcamera
und `picamera2` sind gegenstandslos, der Zugriffsweg ist V4L2.

## 13. Abhängigkeiten

| Paket | Version | Zweck | Wheel für aarch64 |
|---|---|---|---|
| `linuxpy` | 0.25.0 | V4L2 über ctypes | `py3-none-any` |
| `numpy` | 2.3.4 | YUYV→YCbCr | `cp313-manylinux_2_28` |
| `Pillow` | 11.3.0 | JPEG-Kodierung | `cp313-manylinux_2_28` |
| `PyYAML` | 6.0.3 | Konfigurationsdatei | `cp313-manylinux_2_28` |

Alle vier liegen als fertige Wheels vor, es wird nichts kompiliert
(geprüft mit `pip download --no-deps` bzw. `pip install --dry-run`). Das
war wichtig: Ein Quellbau von numpy oder Pillow bei 1,8 GiB RAM wäre
riskant.

Alles Weitere aus der Standardbibliothek: `http.server`, `http.cookies`,
`ssl`, `threading`, `urllib.parse`, `argparse`, `json`, `secrets`,
`base64`, `html`.

## 14. Messwerte

Alle Werte auf diesem Host gemessen.

| Messung | Ergebnis |
|---|---|
| Kamera 1 roh, 640x480 | 16,66 fps |
| Kamera 1 im Dienst, Soll 15 | 12,5 fps, 21 KiB/Frame, 260 KiB/s |
| Kamera 2 im Dienst, Soll 15, MJPEG | 15,1 fps, 61 KiB/Frame, 912 KiB/s |
| Kamera 2 bei 1280x720, MJPEG | 10,3 fps, 150 KiB/Frame, 1544 KiB/s |
| Kamera 2 bei 800x600, MJPEG | 10,8 fps, 87 KiB/Frame, 936 KiB/s |
| **Beide gleichzeitig** | 12,6 + 15,0 fps, keine verworfenen Frames |
| YUYV→YCbCr (numpy), 640x480 | 5,8 ms je Frame |
| YCbCr→JPEG (Pillow, Q75) | 8,2 ms je Frame |
| Soll 5 fps, 320x240, Q60 | 4,9 fps, 7 KiB/Frame |
| Übersichtsseite | 1,9 KiB |
| `stil.css` / `webcam.js` | 3,2 / 5,5 KiB |

Die YUYV-Kamera bleibt mit 12,5 fps unter dem Soll von 15, weil sie roh
nur 16,66 fps liefert und die Drosselung dann nicht jeden Frame
durchlassen kann. Die MJPEG-Kamera erreicht den Sollwert.

## 15. Verifikation

Geprüft:

- Frame-Grab: 1.843.200 Byte für 3 Frames = exakt 3 × 640×480×2.
- Farbrichtigkeit: Testframes beider Kameras als JPEG angesehen, Farben
  plausibel, keine vertauschten Kanäle, kein Versatz.
- MJPEG-Struktur: Eigener Parser prüfte Content-Type, Grenzmarken,
  `Content-Length` je Teil, `FFD8`/`FFD9` jedes Frames. Alle vollständig.
- Bewegtbild statt Standbild: 139 verschiedene Frame-Größen bei 151
  Frames.
- **Beide Kameras gleichzeitig**, je ein eigener Grabber, unabhängige
  Bildraten und Formate.
- Zwei gleichzeitige Clients auf derselben Kamera erhalten denselben
  Strom aus einem Grabber.
- Streamgrenze: Der fünfte Stream bei `max_streams: 4` erhält 503.
- Kamera wird nach dem letzten Zuschauer freigegeben.
- Formular-Anmeldung: über echte HTTP-Anfragen mit einem Stub-Register
  (ohne Kamera) auf dem Entwicklungs-Host (Pi 5) geprüft — zehn Punkte:
  Umleitung des nicht angemeldeten Seitenaufrufs auf `/anmelden`,
  Formular und CSS öffentlich erreichbar, falsches Passwort → 401 mit
  Hinweis, richtiges Passwort → 303 mit `Set-Cookie`
  (`HttpOnly`, `SameSite=Strict`), Zugang mit Sitzungs-Cookie,
  Abmelden löscht das Cookie und macht das Token ungültig, Basic-Kopf
  bleibt für Werkzeuge gültig, `status.json` ohne Anmeldung → 401 ohne
  Umleitung. Der Test lief gegen den laufenden Server, nicht gegen
  Attrappen.
- Sicherheitsabbruch bei Netzbindung ohne Passwort.
- Fehlendes Gerät: 503 mit Begründung, Dienst läuft weiter.
- **Wegfall einer Kamera im laufenden Betrieb** (USB-Ausfall der C615):
  andere Kamera lief weiter, 503 für die ausgefallene, kein Absturz.
- Stabile Pfade: by-id blieb über einen Gerätewechsel
  (`video2`→`video3`) unverändert gültig.
- Automatische Erkennung findet beide Kameras und keine Pi-Plattform-
  geräte.
- Konfiguration: Syntaxfehler mit Zeilenangabe, unbekannter Schlüssel,
  Wertebereich, fehlende Datei, ausdrücklich angegebene fehlende Datei.
- Vorrang: `--port` und `--fps` überschreiben die Datei.
- Unbekannte Kamera: 404 mit Liste der vorhandenen. Unbekannte Adresse:
  404.
- Unbekannter Regler: Warnung, Dienst läuft weiter.
- Unvollständiger YUYV-Frame wird verworfen (real beobachtet).
- Ist-Bildrate stimmt mit der Clientmessung überein.

## 16. Ausdrücklich ungeprüft

- **Darstellung in einem echten Browser.** Auf diesem Pi läuft keine
  grafische Oberfläche. Geprüft ist, dass der Strom dem
  multipart-Format entspricht und gültige JPEGs enthält, nicht, dass
  Firefox oder Chrome es anzeigen. Das gilt auch für die Übersichtsseite
  mit mehreren gleichzeitigen Streams in einem Tab, für `webcam.js`
  (Pause, Vollbild, Wiederverbinden, Statusanzeige), für das
  Kachelraster und für die **Darstellung der Anmeldeseite** im Browser
  (der Anmeldefluss selbst ist über HTTP geprüft, siehe Abschnitt 15,
  nur das gerenderte Formular nicht). **Das ist die größte offene
  Lücke.**
- **TLS-Pfad** (`--zertifikat`). Kein Zertifikat erzeugt.
- **Mehr als zwei Kameras.** Getestet wurden zwei.
- **Vier gleichzeitige Streams über mehrere Kameras.** Die Grenze wurde
  geprüft, nicht aber, ob der Pi vier Streams flüssig bedient.
- **Dauerbetrieb.** Längster Lauf etwa 15 Sekunden am Stück.
  Speicherverhalten über Stunden unbekannt. Ob mehrere Grabber-Threads
  über längere Zeit am GIL hängen, ist nicht gemessen.
- **IPv6.** Der Code wählt `AF_INET6` bei einem Doppelpunkt im Host.
  Nicht ausprobiert.
- **`by-path` als Rückfall.** Der Code bevorzugt `by-id`; der Fall
  "Kamera ohne Seriennummer" trat nicht auf.
- **Leere Konfigurationsdatei** und **falscher Typ** in der
  Konfiguration. Der Code behandelt beides, es wurde nicht ausgelöst.
- **`format: mjpeg` an einer Kamera ohne MJPEG.** Die Fehlermeldung ist
  vorbereitet, nicht ausgelöst.
- Rolle von `/dev/video1`, Hardware-Encoder des Pi.

## 17. Betrieb

Kein Dienst, keine systemd-Unit, kein Autostart. Start von Hand über das
Startskript `webcam_stream.sh` (ruft `webcam_stream.py` über das
gemeinsame venv auf und reicht Argumente durch) oder direkt mit dem
venv-Python. Ende mit `Strg+C` (`SIGINT` und `SIGTERM` werden behandelt,
`server.shutdown()` läuft in einem eigenen Thread, weil es aus dem
Signalkontext heraus blockieren würde).

Eine systemd-Unit würde `sudo` brauchen und ist nicht angefordert.
Solange nichts anderes gesagt ist, bleibt der Aufruf bei Bedarf die
richtige Form: Im Ruhezustand sollen die Kameras nicht laufen.
