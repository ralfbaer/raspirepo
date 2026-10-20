---
inclusion: fileMatch
fileMatchPattern: 'PIwebcam/**'
---

# Projektspezifische Regeln: webcam

Zweck (festgelegt 20.10.2026): Die Bilder einer oder mehrerer am USB
angeschlossenen Webcams als Live-Stream im Browser anzeigen. Umgesetzt
und funktionsfähig.

Es gelten die Grundregeln aus `zusammenarbeit.md`, `python.md`,
`projektstruktur.md` und `git.md`. Dazu kommen die
folgenden Vorgaben, die nur für `PIwebcam/` gelten.

## Nur ein Prozess je Kamera

Ein V4L2-Gerät verträgt keine zwei gleichzeitigen Streams. Zwei Zugriffe
drücken die Bildrate von 15 auf 0,9 fps (belegt: `v4l2-ctl --stream-mmap`
parallel zum laufenden Dienst).

Konsequenz: Vor jeder Messung prüfen, dass kein `webcam_stream.py` und
kein `v4l2-ctl --stream-mmap` auf derselben Kamera läuft. Messungen
werden nie als parallele Tool-Aufrufe gemacht, sondern hintereinander.
Ein Messwert, der unter paralleler Nutzung entstand, ist unbrauchbar und
wird verworfen, nicht dokumentiert.

Zum Prüfen: `pgrep -af webcam_stream.py`. Ein als "stopped" gemeldeter
Hintergrundprozess kann noch laufen.

## Gerätepfade immer stabil

In Konfiguration, Beispielen und Dokumentation werden Kameras über
`/dev/v4l/by-id/...` angesprochen, nicht über `/dev/videoN`.

Grund: Die Nummern verschieben sich. Belegt am 20.10.2026 wechselte
dieselbe Logitech C615 beim erneuten Anstecken von `/dev/video2` auf
`/dev/video3`. Bei mehreren Kameras führt `/dev/videoN` dazu, dass eine
Konfiguration auf die falsche Kamera zeigt.

`/dev/videoN` darf im Code vorkommen, wo die Erkennung es meldet, und
als Angabe des Anwenders. Vergleiche zwischen beiden Formen laufen über
`geraet_aufloesen()`.

## Sicherer Standard beim Netzzugriff

Der Dienst bindet standardmäßig auf `127.0.0.1`. Eine Netzfreigabe
(`--host`) ohne Passwort bricht mit Exit-Code 2 ab.

Diese Regel wird nicht aufgeweicht. Wird am Zugangscode gearbeitet,
bleibt der Grundsatz: Der sichere Fall ist der Standard, die
Netzfreigabe eine ausdrückliche Handlung des Anwenders. Damit ersetzt
der Code die Rückfrage, die `zusammenarbeit.md` Regel 2 für Netzdienste
ohne Authentifizierung verlangt.

Das Passwort kommt ausschließlich aus `WEBCAM_PASSWORT` oder
`--passwort`, nie aus `webcam_stream.yml`.

## Fremde Texte werden maskiert

Kameranamen stammen aus dem USB-Deskriptor des Geräts (Feld `card`),
sind also Eingabe von außen. Jeder Text, der in HTML landet, läuft durch
`html.escape`. Das gilt auch für Namen aus der Konfigurationsdatei.

## Keine schweren Abhängigkeiten

Erlaubt sind `linuxpy`, `numpy`, `Pillow` und `PyYAML` in den Versionen
aus `requirements.txt`. OpenCV, ffmpeg-Bindings, GStreamer und
Web-Frameworks (Flask, FastAPI, aiohttp) werden nicht hinzugefügt:
`http.server` aus der Standardbibliothek erfüllt die Aufgabe.

Eine neue Abhängigkeit braucht eine Begründung in
`PIwebcam_architektur.md`, Abschnitt "Verworfene Alternativen".

## Nichts auf Platte schreiben

Der Dienst hält Frames ausschließlich im Speicher. Soll später
aufgezeichnet werden, wird der Ablageort ausdrücklich entschieden und
dokumentiert.

Aus demselben Grund werden Seiten, CSS und JavaScript einmal beim Start
gelesen und nicht pro Anfrage.

## Argparse-Defaults sind None

Alle Kommandozeilenargumente haben `None` als Standardwert, nicht den
fachlichen Standard. Nur so ist unterscheidbar, ob der Anwender etwas
angegeben hat, und nur so funktioniert die Rangfolge
Kommandozeile > Datei > eingebaute Werte.

Beim Hinzufügen eines Arguments gilt das ebenfalls. Der fachliche
Standard gehört nach `einstellungen.py` und in `webcam_stream.yml`.

## Deutsche Bezeichner

Im Code dieses Projekts sind auch Funktions-, Klassen- und
Attributnamen deutsch, ebenso die Schlüssel in `webcam_stream.yml`.
Ausnahmen: `main`, `argv` und Überschreibungen aus der
Standardbibliothek (`do_GET`, `log_message`, `handle_error`).

## Messwerte gehören belegt

Bildraten, Zeiten und Größen werden gemessen und mit dem erzeugenden
Kommando in `PIwebcam_architektur.md`, Abschnitt "Messwerte",
festgehalten. Geschätzte Zahlen werden nicht als Messwerte ausgegeben.

Wo eine Abschätzung unvermeidlich ist (etwa die USB-Bandbreite vor dem
Start), wird sie als Abschätzung benannt, samt Annahme. Fehlt eine
Information für die Abschätzung, wird das gesagt, statt still den
ungünstigsten Fall anzunehmen und als Warnung auszugeben.

## Fehler nicht stillschweigend verschlucken

`except Exception` ohne Protokollierung ist in diesem Projekt ein
Mangel. Ein Grabber darf einen Fehler überleben, aber er muss ihn
nennen. Wiederholte identische Fehler werden zusammengefasst, nicht
unterdrückt.