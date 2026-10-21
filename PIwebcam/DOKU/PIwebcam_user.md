# webcam — Anleitung

## Was dieses Programm tut

Es zeigt die Bilder der am Raspberry Pi angeschlossenen USB-Webcams im
Browser an, als laufendes Live-Bild. Dazu startet das Programm einen
kleinen Webserver auf dem Pi.

Sind mehrere Kameras angesteckt, zeigt die Startseite alle nebeneinander.
Ein Klick auf eine Kachel öffnet die Einzelansicht mit Pause, Vollbild
und einem Knopf für ein Einzelbild.

Es wird nichts aufgezeichnet. Es landen keine Bilder auf der Festplatte,
außer denen, die Sie selbst über "Einzelbild speichern" herunterladen.

## Starten

Am einfachsten über das Startskript:

```bash
/home/baer/gitrepos/raspirepo/PIwebcam/webcam_stream.sh
```

Gleichwertig der direkte Aufruf über das gemeinsame venv:

```bash
cd /home/baer/gitrepos/raspirepo/PIwebcam
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py
```

Dann im Browser auf demselben Rechner öffnen:

```
http://127.0.0.1:8080
```

Beenden mit `Strg+C` im Terminal.

Beim Start listet das Programm auf, welche Kameras es gefunden hat und
unter welcher Adresse die Seite erreichbar ist. Angeschlossene Kameras
werden von selbst erkannt, Sie müssen nichts eintragen.

## Einen anderen Port verwenden

Zwei Wege, beide gleichwertig:

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py --port 9000
```

Oder dauerhaft in der Datei `webcam_stream.yml` im Projektverzeichnis:

```yaml
port: 9000
```

Die Angabe auf der Kommandozeile hat Vorrang vor der Datei. Portnummern
unter 1024 sind dem Systemverwalter vorbehalten, nehmen Sie 1024 oder
höher.

## Mehrere Kameras

Stecken Sie einfach mehrere Webcams an. Beim Start werden alle erkannt,
die Startseite zeigt sie nebeneinander, jede hat ihre eigene
Einzelansicht.

Nachsehen, was gefunden wird:

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py --kameras-liste
```

Die Ausgabe nennt zu jeder Kamera den Namen, die möglichen Bildgrößen
und einen fertigen Abschnitt zum Übernehmen in `webcam_stream.yml`.

### Eigene Namen vergeben

Ohne Zutun heißen die Kameras so, wie sie sich selbst melden, etwa
"HD Webcam C615". Für sprechende Namen tragen Sie sie in
`webcam_stream.yml` ein:

```yaml
kameras:
  - geraet: /dev/v4l/by-id/usb-Etron_Technology__Inc._USB2.0_Camera-video-index0
    name: Garten
    aufloesung: "640x480"

  - geraet: /dev/v4l/by-id/usb-046d_HD_Webcam_C615_90CE6170-video-index0
    name: Werkstatt
    aufloesung: "800x600"
    fps: 12
```

Die langen Pfade bekommen Sie mit `--kameras-liste` zum Kopieren.

### Warum diese langen Gerätepfade?

Weil die kurzen nicht verlässlich sind. Eine Kamera, die heute
`/dev/video2` ist, kann nach dem Neustarten `/dev/video3` sein. Das
wurde hier beobachtet: Dieselbe Kamera wechselte beim erneuten Anstecken
die Nummer.

Bei einer Kamera ist das harmlos, weil sie ohnehin automatisch gefunden
wird. Bei mehreren Kameras wäre es ärgerlich: Ihre Konfiguration sagt
"Garten", gezeigt wird die Werkstatt.

Die Pfade unter `/dev/v4l/by-id/` enthalten Modell und Seriennummer und
bleiben deshalb an der Kamera, egal an welchem Port sie steckt.

### Schnell, ohne Datei

Für einen einmaligen Versuch geht es auch direkt:

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py \
  --kamera Garten=/dev/video0 --kamera Tuer=/dev/video2
```

### Wie viele Kameras gehen?

Technisch so viele, wie Sie anstecken. Praktisch begrenzen zwei Dinge:

- **USB-Bandbreite.** Alle Kameras teilen sich einen Anschluss am Pi.
  Das Programm warnt beim Start, wenn die Summe zu groß wird, und sagt,
  was zu tun ist (kleinere Auflösung wählen).
- **Stromversorgung.** Hier ist beim Betrieb von zwei Kameras eine
  ausgefallen, der Kernel meldete einen Portfehler. Wenn Kameras
  sporadisch verschwinden, hilft ein USB-Hub mit eigenem Netzteil.

Gleichzeitig zuschauen können standardmäßig vier Geräte, über alle
Kameras zusammen. Der fünfte bekommt eine Meldung. Die Zahl lässt sich
in `webcam_stream.yml` unter `grenzen: max_streams` ändern.

## Von einem anderen Gerät zuschauen

In der Grundeinstellung ist der Stream **nur auf dem Pi selbst**
erreichbar. Das ist Absicht: Ein Kamerabild soll nicht versehentlich für
alle im Netz sichtbar sein.

Damit Sie vom Handy oder Notebook zuschauen können, geben Sie den Dienst
ausdrücklich frei und setzen dabei ein Passwort:

```bash
WEBCAM_PASSWORT=IhrPasswort /home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py --host 0.0.0.0
```

Das Programm nennt dann die Adresse im Heimnetz, etwa
`http://192.168.188.x:8080`. Statt irgendein Bild zu zeigen, erscheint
zuerst eine Anmeldeseite. Tragen Sie dort Benutzername und Passwort ein:
Der Benutzername ist `webcam`, das Passwort das, das Sie gesetzt haben.
Nach der Anmeldung bleiben Sie angemeldet, bis Sie sich abmelden oder
einige Stunden vergangen sind.

Zum Abmelden rufen Sie `http://.../abmelden` auf.

Diese Anmeldeseite ist ein gewöhnliches Formular. Sie funktioniert auch
in Browsern, in denen das ältere Anmeldefenster (die kleine Abfrage
ganz oben) abgeschaltet ist.

Ohne Passwort verweigert das Programm die Freigabe ins Netz und sagt
Ihnen das auch. Wenn Sie den Stream wirklich ungeschützt freigeben
wollen, hängen Sie `--ohne-anmeldung` an. Dann kann jeder, der die
Adresse erreicht, Ihr Kamerabild sehen.

**Zwei Dinge, die Sie dabei wissen sollten:**

- Das Passwort wird bei einer normalen `http://`-Verbindung nicht
  verschlüsselt übertragen. Wer im selben Netz mitliest, kann es
  mitlesen. Im eigenen Heimnetz ist das meist hinnehmbar, in einem
  fremden WLAN nicht.
- Geben Sie den Dienst nicht aus dem Internet erreichbar frei, also
  keine Portweiterleitung im Router darauf richten. Dafür ist er nicht
  gebaut.

### Sicherer: über einen SSH-Tunnel

Wenn Sie sich mit SSH auf den Pi verbinden können, gibt es einen
geschützten Weg ganz ohne Netzfreigabe und ohne Passwort im Dienst. Der
Dienst bleibt in der Grundeinstellung (nur auf dem Pi selbst), und Sie
bauen vom eigenen Rechner einen Tunnel:

```bash
ssh -L 8081:127.0.0.1:8080 benutzer@pi-adresse
```

Lassen Sie dieses Fenster offen und öffnen Sie dann im Browser
`http://localhost:8081`. Die Verbindung läuft verschlüsselt durch SSH,
und der Stream ist für niemanden sonst im Netz sichtbar.

Das Passwort gehört **nicht** in `webcam_stream.yml`. Diese Datei ist
für Einstellungen gedacht, nicht für Geheimnisse.

## Das Bild auf einem Display am Pi zeigen

Hängt am Pi ein Bildschirm (zum Beispiel ein kleines HDMI-Panel), lässt
sich das Kamerabild direkt dort anzeigen, ganz ohne Browser. Dafür gibt
es ein zweites Programm, `webcam_display.py`.

Ein Befehl genügt:

```bash
/home/baer/gitrepos/raspirepo/PIwebcam/webcam_display.sh
```

Auf dem angeschlossenen Bildschirm erscheint das Kamerabild. Beenden mit
`Strg+C`; der Bildschirm wird dabei wieder geleert.

Das Startskript kümmert sich selbst um den Kameradienst: Läuft er noch
nicht, startet es ihn mit und beendet ihn beim Verlassen wieder. Läuft
bereits ein Dienst (etwa weil Sie ohnehin im Browser zuschauen), benutzt
die Anzeige ihn mit und lässt ihn beim Beenden unangetastet. Sie können
also gleichzeitig auf dem Display **und** im Browser zuschauen.

Warum überhaupt ein Dienst im Hintergrund? Eine Webcam kann immer nur von
einer Stelle gleichzeitig gelesen werden. Deshalb liest der Dienst die
Kamera, und die Anzeige holt sich das fertige Bild bei ihm ab.

Hinweis: Der automatisch mitgestartete Dienst läuft mit seinen
Standardwerten (nur auf dem Pi erreichbar, Port 8080). Wenn Sie einen
anderen Port oder eine Netzfreigabe mit Passwort brauchen, starten Sie
Dienst und Anzeige weiterhin getrennt (siehe „Starten" oben und „Von
einem anderen Gerät zuschauen").

Nützliche Angaben:

| Angabe | Wirkung | Standard |
|---|---|---|
| `--kamera KENNUNG` | Welche Kamera aufs Display, bei mehreren | erste Kamera |
| `--skalierung fuellen` | Bild füllt die ganze Fläche (schneidet Ränder ab) | `einpassen` (mit Rand) |

Die Kennung einer Kamera steht auf der Übersichtsseite im Browser und in
der Startmeldung des Dienstes (hinter `-> /kamera/...`).

Wenn statt des Bildes eine Fehlermeldung zum Framebuffer erscheint:
Prüfen Sie, ob wirklich ein Display angeschlossen ist. Erscheint
„nicht erreichbar", läuft der Dienst aus Schritt 1 vermutlich noch nicht
— die Anzeige versucht es dann von selbst in wachsenden Abständen erneut.

## Einstellungen

Alles Wichtige steht in `webcam_stream.yml` im Projektverzeichnis, mit
Erklärung zu jedem Wert. Die Datei ist ihre eigene Anleitung.

Was Sie auch ohne Datei auf der Kommandozeile angeben können:

| Angabe | Wirkung | Standard |
|---|---|---|
| `--port 9000` | Portnummer | 8080 |
| `--aufloesung 320x240` | Bildgröße aller Kameras | 640x480 |
| `--fps 8` | Bilder pro Sekunde (Obergrenze) | 15 |
| `--qualitaet 60` | Bildqualität, 1 bis 100 | 75 |
| `--titel Werkstatt` | Überschrift der Seite | Webcam |
| `--max-streams 2` | Gleichzeitige Zuschauer | 4 |
| `--kamera NAME=GERAET` | Kamera festlegen, mehrfach möglich | alle erkannten |

Die vollständige Liste zeigt:

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py --help
```

Wenn das Bild ruckelt oder die Verbindung schwach ist, hilft eine
kleinere Bildgröße und eine niedrigere Bildrate:

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py --aufloesung 320x240 --fps 8 --qualitaet 60
```

## Bildeinstellungen der Kamera

Helligkeit, Kontrast und Ähnliches lassen sich mitgeben:

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py --regler brightness=20 --regler contrast=70
```

Welche Regler Ihre Kameras kennen, zeigt:

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py --regler-liste
```

Für einzelne Kameras gehen die Regler auch in `webcam_stream.yml`. Ein
Regler, den die Kamera nicht kennt, wird übersprungen und gemeldet; das
Programm läuft weiter.

## Wie gut wird das Bild?

Das hängt stark von der Kamera ab, und zwar an einer einzigen Stelle:
Kann die Kamera selbst komprimieren?

| | einfache Kamera | Kamera mit MJPEG |
|---|---|---|
| Beispiel hier | USB2.0 Camera | Logitech C615 |
| Erreichte Bildrate | 12,5 pro Sekunde | 15,1 pro Sekunde |
| Mögliche Bildgröße | bis 640x480 | bis 1920x1080 |
| Rechenlast am Pi | hoch | praktisch keine |

Einfache Kameras liefern nur unkomprimierte Rohbilder. Der Pi muss dann
jedes Bild selbst umrechnen, was ihn bremst und die Bildgröße begrenzt.
Kameras mit eigener Komprimierung sind dem Pi diese Arbeit los, liefern
mehr Bilder pro Sekunde und erlauben größere Auflösungen.

Das Programm erkennt das von selbst und wählt jeweils den besseren Weg.
Im Status auf der Webseite steht unter "Format", welcher Weg benutzt
wird.

## Was tun, wenn etwas nicht funktioniert

**Die Seite lässt sich nicht öffnen.**
Läuft das Programm noch? Im Terminal nachsehen. Prüfen Sie, ob Sie die
Adresse samt Portnummer verwenden, die das Programm genannt hat.

**"Address already in use" beim Start.**
Auf dem Port läuft noch ein anderer Dienst, oft eine vergessene
Instanz dieses Programms. Entweder beenden oder `--port` mit einer
anderen Nummer verwenden.

**Eine Kachel bleibt leer, die anderen zeigen Bild.**
Nur diese eine Kamera macht Probleme; die übrigen laufen weiter. Die
Seite versucht es von selbst erneut, mit wachsendem Abstand. Im Terminal
steht die Ursache.

**Eine Kamera verschwindet im Betrieb.**
Meist die Stromversorgung. Ein USB-Hub mit eigenem Netzteil hilft.
Taucht die Kamera wieder auf, verbindet sich das Programm von selbst
neu, Sie müssen es nicht neu starten.

**Nach dem Neustarten zeigt eine Kamera das falsche Bild.**
Sie haben `/dev/video0` statt des langen Pfads unter
`/dev/v4l/by-id/` eingetragen. Mit `--kameras-liste` die stabilen Pfade
holen und eintragen.

**"Zu viele gleichzeitige Streams".**
Es schauen bereits vier Geräte zu, über alle Kameras zusammen. Einen Tab
schließen, oder `max_streams` in `webcam_stream.yml` erhöhen.

**Das Bild ist dunkel oder farbstichig.**
Mit `--regler brightness=20` nachhelfen. Die Kamera regelt Belichtung
und Weißabgleich selbst, braucht dafür aber einige Sekunden.

**"Kein Bild von ..." mit einem Hinweis auf das Gerät.**
Die Kamera ist nicht ansprechbar. USB-Stecker prüfen, dann
`--kameras-liste` aufrufen: Erscheint sie dort, ist sie in Ordnung.
Erscheint sie nicht, sieht das System sie nicht.

**Das Programm bricht mit einer Meldung zu `webcam_stream.yml` ab.**
Die Datei hat einen Fehler. Die Meldung nennt Zeile und Problem. Häufig:
falsche Einrückung oder ein vertippter Name. Zur Probe können Sie die
Datei umbenennen, dann läuft das Programm mit den Standardwerten.

**Das Bild steht still.**
Auf "Weiter" drücken, falls vorher "Pause" gedrückt wurde. Im
angehaltenen Zustand zeigt die Seite absichtlich nur ein Einzelbild.

## Was das Programm nicht tut

- Es zeichnet nichts auf und speichert nichts von selbst.
- Es überträgt keinen Ton.
- Es erkennt keine Bewegung.
- Es läuft nicht von selbst beim Hochfahren des Pi mit. Es muss von Hand
  gestartet werden.
