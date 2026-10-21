"""Datenklassen und Standardwerte für alle Einstellungen.

Dieses Modul enthält nur Daten, keine Logik und keine Abhängigkeit zu
Hardware oder Netz. Es liegt getrennt, damit `kamera.py`, `server.py`
und `konfiguration.py` dieselben Typen benutzen können, ohne sich
gegenseitig zu importieren.

Die Standardwerte hier sind die dritte und schwächste Stufe der
Rangfolge: Kommandozeile schlägt `webcam_stream.yml`, und die schlägt
diese Werte. Sie sind so gewählt, dass das Programm ohne jede
Konfigurationsdatei startet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- Dienst ---------------------------------------------------------------

STANDARD_HOST = "127.0.0.1"
STANDARD_PORT = 8080
STANDARD_BENUTZER = "webcam"
STANDARD_TITEL = "Webcam"
STANDARD_PROTOKOLL = "info"

# --- Bild -----------------------------------------------------------------

STANDARD_BREITE = 640
STANDARD_HOEHE = 480
STANDARD_BILDRATE = 15.0
STANDARD_QUALITAET = 75

# "auto" nimmt MJPEG, wenn die Kamera es kann, sonst YUYV.
STANDARD_FORMAT = "auto"

# --- Grenzen und Zeiten ---------------------------------------------------

STANDARD_MAX_STREAMS = 4
STANDARD_LEERLAUF = 5.0
STANDARD_WIEDERHOLUNG = 2.0
STANDARD_ERSTES_BILD = 8.0
STANDARD_STREAM_STILLE = 10.0
STANDARD_FEHLANMELDUNG = 0.5

# Wie lange eine über das Anmeldeformular erzeugte Sitzung gilt, in
# Sekunden. Nach Ablauf ist eine neue Anmeldung nötig. Bewusst nicht in
# der YAML konfigurierbar: ein fester, einfacher Wert genügt.
STANDARD_SITZUNGSDAUER = 12 * 60 * 60

# Richtwert für die nutzbare USB-2.0-Bandbreite in Byte/s. Grob und
# absichtlich vorsichtig: Am Pi 4 hängen alle USB-Ports über einen
# VL805-Controller an PCIe. Dient nur dazu, beim Start zu warnen.
STANDARD_USB_RICHTWERT = 24_000_000

PROTOKOLLSTUFEN = ("debug", "info", "warnung", "fehler")


@dataclass
class Zeiten:
    """Zeitgrenzen und Grenzwerte des Betriebs, alle in Sekunden.

    Ausnahmen: `max_streams` ist eine Anzahl, `usb_richtwert` ist eine
    Datenrate in Byte/s.
    """

    max_streams: int = STANDARD_MAX_STREAMS
    leerlauf: float = STANDARD_LEERLAUF
    wiederholung: float = STANDARD_WIEDERHOLUNG
    erstes_bild: float = STANDARD_ERSTES_BILD
    stream_stille: float = STANDARD_STREAM_STILLE
    fehlanmeldung: float = STANDARD_FEHLANMELDUNG
    usb_richtwert: int = STANDARD_USB_RICHTWERT


@dataclass
class Kameraeinstellung:
    """Was beim Öffnen einer Kamera und beim Kodieren gelten soll.

    `kennung` ist der Name in der Adresse (`/kamera/<kennung>/...`) und
    muss eindeutig und URL-sicher sein. `anzeigename` ist der Text, den
    der Anwender in der Oberfläche sieht.
    """

    geraet: str = "/dev/video0"
    kennung: str = "kamera1"
    anzeigename: str = "Kamera 1"
    breite: int = STANDARD_BREITE
    hoehe: int = STANDARD_HOEHE
    bildrate: float = STANDARD_BILDRATE
    qualitaet: int = STANDARD_QUALITAET
    bildformat: str = STANDARD_FORMAT
    steuerwerte: dict[str, int] = field(default_factory=dict)

    def rohdatenrate(self, mjpeg: bool = False) -> float:
        """Grobe USB-Last in Byte/s, gerechnet mit der Kamerarate.

        Entscheidend ist die Rate, mit der die Kamera liefert, nicht die
        gedrosselte Ausgaberate: Jeder Frame wird abgeholt, auch wenn er
        nicht kodiert wird. Gerechnet wird mit 30 fps, weil Kameras das
        üblicherweise melden.

        Für MJPEG wird mit einem Achtel der Rohdatenmenge gerechnet.
        Das ist eine Schätzung, keine Messung: Die tatsächliche Größe
        hängt vom Bildinhalt und der Kameraeinstellung ab.
        """
        roh = self.breite * self.hoehe * 2 * 30.0
        return roh / 8.0 if mjpeg else roh


@dataclass
class Dienstkonfiguration:
    """Alles, was der Dienst zum Starten braucht."""

    host: str = STANDARD_HOST
    port: int = STANDARD_PORT
    titel: str = STANDARD_TITEL
    protokoll: str = STANDARD_PROTOKOLL
    benutzer: str = STANDARD_BENUTZER
    passwort: str | None = None
    ohne_anmeldung: bool = False
    zertifikat: Path | None = None
    schluessel: Path | None = None
    zeiten: Zeiten = field(default_factory=Zeiten)
    kameras: list[Kameraeinstellung] = field(default_factory=list)

    # Nur für die Startmeldung: woher die Kameraliste stammt.
    quelle_der_kameras: str = "Standardwerte"
    quelle_der_datei: str = "keine Datei"
