#!/usr/bin/env python3
"""Zeigt den Kamerastream auf dem am Pi angeschlossenen Display.

Holt den MJPEG-Strom vom laufenden `webcam_stream.py` (standardmäßig
`http://127.0.0.1:8080`) und schreibt die Bilder in den Linux-Framebuffer
`/dev/fb0`. So erscheint das Kamerabild ohne Browser und ohne grafische
Oberfläche direkt auf dem Panel.

Aufruf (gemeinsames venv):

    /home/baer/gitrepos/raspirepo/.venv/bin/python webcam_display.py

Voraussetzung: `webcam_stream.py` läuft bereits und liefert mindestens
eine Kamera. Grund für den Umweg über den Dienst statt eines direkten
Kamerazugriffs: Ein V4L2-Gerät verträgt nur einen Zugriff gleichzeitig.
Der Dienst ist der eine Besitzer der Kamera, dieser Prozess ist ein
weiterer Zuschauer und belegt einen `max_streams`-Platz.

Einstellungen stehen in `webcam_display.yml` daneben. Argumente der
Kommandozeile haben Vorrang.

Dieses Programm nutzt bewusst **kein** `base_resources` (framework-frei).
Begründung in `DOKU/PIwebcam.md`, Abschnitt "Framework-frei".
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import urllib.parse
from pathlib import Path

import yaml

from submodule.einstellungen import PROTOKOLLSTUFEN, STANDARD_BENUTZER
from submodule.mjpeg_leser import Mjpegquelle, MjpegFehler
from submodule.rahmenpuffer import Rahmenpuffer, RahmenpufferFehler

log = logging.getLogger("webcam_display")

VERZEICHNIS = Path(__file__).resolve().parent
KONFIGURATIONSDATEI = "webcam_display.yml"

STANDARD_SERVER = "http://127.0.0.1:8080"
STANDARD_RAHMENPUFFER = "/dev/fb0"
STANDARD_SKALIERUNG = "einpassen"
STANDARD_PROTOKOLL = "info"

SKALIERUNGSWAHL = ("einpassen", "fuellen")
ERLAUBT_OBEN = {"server", "kamera", "benutzer", "rahmenpuffer", "skalierung", "protokoll"}


class Konfigurationsfehler(Exception):
    """Die Einstellungen sind fehlerhaft oder unbrauchbar."""


# ---------------------------------------------------------------------------
# Argumente
# ---------------------------------------------------------------------------


def argumente_lesen(argv: list[str] | None = None) -> argparse.Namespace:
    """Liest die Kommandozeile.

    Alle Argumente haben `None` als Standardwert (bzw. das Programm
    bildet den Standard erst in `konfiguration_bauen`). Nur so ist die
    Rangfolge Kommandozeile > Datei > eingebaute Werte umsetzbar.
    """
    zerleger = argparse.ArgumentParser(
        prog="webcam_display.py",
        description=(
            "Zeigt den Kamerastream von webcam_stream.py auf dem "
            f"angeschlossenen Display. Einstellungen in {KONFIGURATIONSDATEI}, "
            "Argumente haben Vorrang."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            "  Erste Kamera auf /dev/fb0:\n"
            "    webcam_display.py\n"
            "  Bestimmte Kamera (Kennung aus der Übersicht):\n"
            "    webcam_display.py --kamera werkstatt\n"
            "  Bild formatfüllend statt mit Rand:\n"
            "    webcam_display.py --skalierung fuellen\n"
        ),
    )
    zerleger.add_argument(
        "--server",
        default=None,
        help=f"Adresse des laufenden Dienstes. Standard {STANDARD_SERVER}.",
    )
    zerleger.add_argument(
        "--kamera",
        default=None,
        help="Kennung der anzuzeigenden Kamera (siehe Übersichtsseite). "
        "Ohne Angabe wird die erste Kamera gezeigt.",
    )
    zerleger.add_argument(
        "--benutzer",
        default=None,
        help="Benutzername, falls der Dienst ein Passwort verlangt. "
        f"Standard {STANDARD_BENUTZER}.",
    )
    zerleger.add_argument(
        "--passwort",
        default=None,
        help="Passwort, falls der Dienst eines verlangt. Besser über die "
        "Umgebungsvariable WEBCAM_PASSWORT setzen (Prozessliste).",
    )
    zerleger.add_argument(
        "--rahmenpuffer",
        default=None,
        help=f"Framebuffer-Gerät. Standard {STANDARD_RAHMENPUFFER}.",
    )
    zerleger.add_argument(
        "--skalierung",
        default=None,
        choices=SKALIERUNGSWAHL,
        help="'einpassen' (Standard) behält das Seitenverhältnis mit Rand, "
        "'fuellen' füllt die Fläche und schneidet den Überstand ab.",
    )
    zerleger.add_argument(
        "--protokoll",
        default=None,
        choices=PROTOKOLLSTUFEN,
        help="Ausführlichkeit der Meldungen. Standard info.",
    )
    zerleger.add_argument(
        "--konfiguration",
        type=Path,
        default=None,
        metavar="DATEI",
        help=f"Andere Konfigurationsdatei als {KONFIGURATIONSDATEI}.",
    )
    return zerleger.parse_args(argv)


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------


def protokoll_einrichten(stufe: str) -> None:
    stufen = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warnung": logging.WARNING,
        "fehler": logging.ERROR,
    }
    wert = stufen.get(stufe, logging.INFO)
    wurzel = logging.getLogger()
    wurzel.setLevel(wert)
    if not wurzel.handlers:
        ausgabe = logging.StreamHandler()
        ausgabe.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        wurzel.addHandler(ausgabe)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------


def konfiguration_bauen(argumente: argparse.Namespace) -> dict:
    """Führt Standardwerte, Datei und Kommandozeile zusammen."""
    konf = {
        "server": STANDARD_SERVER,
        "kamera": None,
        "benutzer": STANDARD_BENUTZER,
        "rahmenpuffer": STANDARD_RAHMENPUFFER,
        "skalierung": STANDARD_SKALIERUNG,
        "protokoll": STANDARD_PROTOKOLL,
    }

    # --- Datei ---
    if argumente.konfiguration is not None:
        pfad = argumente.konfiguration
        if not pfad.is_file():
            raise Konfigurationsfehler(f"Konfigurationsdatei nicht gefunden: {pfad}")
    else:
        kandidat = VERZEICHNIS / KONFIGURATIONSDATEI
        pfad = kandidat if kandidat.is_file() else None

    if pfad is None:
        log.info(
            "Keine Konfigurationsdatei (%s) gefunden, es gelten die Standardwerte.",
            VERZEICHNIS / KONFIGURATIONSDATEI,
        )
    else:
        try:
            inhalt = yaml.safe_load(pfad.read_text(encoding="utf-8"))
        except yaml.MarkedYAMLError as fehler:
            stelle = fehler.problem_mark
            ort = (
                f"{pfad}, Zeile {stelle.line + 1}, Spalte {stelle.column + 1}"
                if stelle
                else str(pfad)
            )
            raise Konfigurationsfehler(f"{ort}: {fehler.problem or 'YAML-Fehler'}") from None
        except (yaml.YAMLError, OSError) as fehler:
            raise Konfigurationsfehler(f"{pfad} nicht lesbar: {fehler}") from None

        if inhalt is None:
            log.warning("%s ist leer, es gelten die Standardwerte.", pfad)
            inhalt = {}
        if not isinstance(inhalt, dict):
            raise Konfigurationsfehler(
                f"{pfad}: Die oberste Ebene muss eine Zuordnung sein "
                f"(etwa 'server: http://127.0.0.1:8080')."
            )
        unbekannt = set(map(str, inhalt)) - ERLAUBT_OBEN
        if unbekannt:
            raise Konfigurationsfehler(
                f"{pfad}: unbekannte Einstellung(en): {', '.join(sorted(unbekannt))}. "
                f"Erlaubt sind: {', '.join(sorted(ERLAUBT_OBEN))}."
            )
        for schluessel in ERLAUBT_OBEN:
            if inhalt.get(schluessel) is not None:
                konf[schluessel] = inhalt[schluessel]

    # --- Kommandozeile schlägt die Datei ---
    for name in ("server", "kamera", "benutzer", "rahmenpuffer", "skalierung", "protokoll"):
        wert = getattr(argumente, name)
        if wert is not None:
            konf[name] = wert

    # --- Prüfen ---
    konf["server"] = str(konf["server"])
    konf["benutzer"] = str(konf["benutzer"])
    konf["rahmenpuffer"] = str(konf["rahmenpuffer"])
    konf["kamera"] = str(konf["kamera"]).strip() if konf["kamera"] else None
    konf["skalierung"] = str(konf["skalierung"]).strip().lower()
    konf["protokoll"] = str(konf["protokoll"]).strip().lower()

    if konf["skalierung"] not in SKALIERUNGSWAHL:
        raise Konfigurationsfehler(
            f"'skalierung' muss einer von {', '.join(SKALIERUNGSWAHL)} sein, "
            f"nicht '{konf['skalierung']}'."
        )
    if konf["protokoll"] not in PROTOKOLLSTUFEN:
        raise Konfigurationsfehler(
            f"'protokoll' muss einer von {', '.join(PROTOKOLLSTUFEN)} sein, "
            f"nicht '{konf['protokoll']}'."
        )
    return konf


def stream_pfad(kamera: str | None) -> str:
    """Baut den HTTP-Pfad des Streams.

    Ohne Kennung die alte Adresse `/stream.mjpg` (erste Kamera), mit
    Kennung `/kamera/<kennung>/stream.mjpg`.
    """
    if kamera:
        return f"/kamera/{urllib.parse.quote(kamera)}/stream.mjpg"
    return "/stream.mjpg"


# ---------------------------------------------------------------------------
# Hauptlauf
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argumente = argumente_lesen(argv)
    protokoll_einrichten(argumente.protokoll or STANDARD_PROTOKOLL)

    try:
        konf = konfiguration_bauen(argumente)
    except Konfigurationsfehler as fehler:
        log.error("%s", fehler)
        return 2

    protokoll_einrichten(konf["protokoll"])

    passwort = argumente.passwort or os.environ.get("WEBCAM_PASSWORT") or None
    pfad = stream_pfad(konf["kamera"])

    try:
        puffer = Rahmenpuffer(konf["rahmenpuffer"])
    except (OSError, RahmenpufferFehler) as fehler:
        log.error("Framebuffer %s nicht nutzbar: %s", konf["rahmenpuffer"], fehler)
        log.error(
            "Prüfen: Ist ein Display angeschlossen, existiert %s, und ist der "
            "Benutzer in der Gruppe 'video'?",
            konf["rahmenpuffer"],
        )
        return 1

    quelle = Mjpegquelle(
        konf["server"], pfad, benutzer=konf["benutzer"], passwort=passwort
    )

    def beenden(signalnummer, rahmen=None):  # noqa: ARG001 - Signatur vorgegeben
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, beenden)

    log.info(
        "Zeige %s auf %s (%dx%d, %d bpp). Zum Beenden Strg+C.",
        quelle.quelle_text, konf["rahmenpuffer"], puffer.breite, puffer.hoehe, puffer.bpp,
    )

    erster = True
    try:
        for jpeg in quelle.bilder():
            if puffer.zeichnen_jpeg(jpeg, konf["skalierung"]) and erster:
                log.info("Erstes Bild angezeigt.")
                erster = False
    except KeyboardInterrupt:
        log.info("Beende.")
    except MjpegFehler as fehler:
        log.error("%s", fehler)
        return 1
    finally:
        puffer.schliessen()
        log.info("Beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
