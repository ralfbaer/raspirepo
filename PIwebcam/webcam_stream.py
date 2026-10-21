#!/usr/bin/env python3
"""Startet einen Webserver, der die Bilder der USB-Webcams im Browser zeigt.

Aufruf (gemeinsames venv, kein System-Python):

    /home/baer/gitrepos/raspirepo/.venv/bin/python webcam_stream.py

Danach im Browser http://127.0.0.1:8080 öffnen. Sind mehrere Kameras
angeschlossen, zeigt die Startseite alle nebeneinander.

Einstellungen stehen in `webcam_stream.yml` im selben Verzeichnis.
Kommandozeilenargumente haben Vorrang vor der Datei.

Standardmäßig lauscht der Dienst nur auf 127.0.0.1, ist also nur von
diesem Rechner erreichbar. Wer ihn im Netz erreichbar machen will,
setzt `--host` und braucht dann ein Passwort (`WEBCAM_PASSWORT`), weil
einen offenen Videostream im Netz niemand sehen soll, der nicht gefragt
wurde. Mit `--ohne-anmeldung` lässt sich das ausdrücklich abschalten.
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
import os
import signal
import socket
import sys
import threading
from pathlib import Path

from einstellungen import (
    PROTOKOLLSTUFEN,
    STANDARD_BREITE,
    STANDARD_HOEHE,
    Dienstkonfiguration,
)
from kamera import FORMATWAHL, Kameraregister, kameras_erkennen, verfuegbare_regler
from konfiguration import KONFIGURATIONSDATEI, Konfigurationsfehler, konfiguration_bauen
from server import Zugangsdaten, server_bauen

log = logging.getLogger("webcam")

VERZEICHNIS = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Argumente
# ---------------------------------------------------------------------------


def aufloesung_pruefen(wert: str) -> tuple[int, int]:
    """Prüft eine Angabe der Form BREITExHOEHE."""
    try:
        breite, hoehe = (int(teil) for teil in wert.lower().split("x", 1))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{wert}' ist keine Auflösung. Erwartet wird etwa 640x480."
        ) from None
    if breite <= 0 or hoehe <= 0 or breite % 2:
        raise argparse.ArgumentTypeError(
            "Breite und Höhe müssen positiv sein, die Breite zusätzlich gerade "
            "(YUYV speichert je zwei Pixel gemeinsam)."
        )
    return breite, hoehe


def regler_pruefen(wert: str) -> tuple[str, int]:
    """Prüft eine Angabe der Form name=zahl."""
    name, trenner, zahl = wert.partition("=")
    if not trenner or not name:
        raise argparse.ArgumentTypeError(
            f"'{wert}' ist keine Reglerangabe. Erwartet wird etwa brightness=10."
        )
    try:
        return name.strip(), int(zahl)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Der Wert für '{name}' muss eine ganze Zahl sein, nicht '{zahl}'."
        ) from None


def argumente_lesen(argv: list[str] | None = None) -> argparse.Namespace:
    """Liest die Kommandozeile.

    Alle Argumente haben `None` als Standardwert, nicht den fachlichen
    Standard. Nur so lässt sich unterscheiden, ob der Anwender etwas
    angegeben hat; der fachliche Standard kommt aus der Datei oder aus
    `einstellungen.py`.
    """
    zerleger = argparse.ArgumentParser(
        prog="webcam_stream.py",
        description=(
            "Zeigt die Bilder der angeschlossenen USB-Webcams im Browser. "
            f"Einstellungen stehen in {KONFIGURATIONSDATEI}, "
            "Argumente haben Vorrang."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            "  Alle Kameras, nur auf diesem Rechner:\n"
            "    webcam_stream.py\n"
            "  Anderer Port:\n"
            "    webcam_stream.py --port 9000\n"
            "  Im Heimnetz freigeben, mit Passwort:\n"
            "    WEBCAM_PASSWORT=geheim webcam_stream.py --host 0.0.0.0\n"
            "  Zwei Kameras mit Namen:\n"
            "    webcam_stream.py --kamera Garten=/dev/video0 "
            "--kamera Tuer=/dev/video2\n"
            "  Nachsehen, was angeschlossen ist:\n"
            "    webcam_stream.py --kameras-liste\n"
        ),
    )

    netz = zerleger.add_argument_group("Netz und Zugang")
    netz.add_argument(
        "--host",
        default=None,
        help="Adresse, auf der gelauscht wird. Standard 127.0.0.1 "
        "(nur dieser Rechner). 0.0.0.0 gibt den Dienst im Netz frei.",
    )
    netz.add_argument(
        "--port", type=int, default=None, help="Portnummer. Standard 8080."
    )
    netz.add_argument(
        "--benutzer", default=None, help="Benutzername für die Anmeldung."
    )
    netz.add_argument(
        "--passwort",
        default=None,
        help="Passwort für die Anmeldung. Besser über die Umgebungsvariable "
        "WEBCAM_PASSWORT setzen, weil Argumente in der Prozessliste sichtbar sind.",
    )
    netz.add_argument(
        "--ohne-anmeldung",
        action="store_true",
        help="Gibt den Stream ohne Passwort frei, auch im Netz. Jeder, der die "
        "Adresse erreicht, sieht dann das Kamerabild.",
    )
    netz.add_argument(
        "--zertifikat",
        type=Path,
        default=None,
        help="PEM-Datei für HTTPS. Ohne TLS geht das Passwort im Klartext "
        "durchs Netz (HTTP Basic ist nur base64-kodiert).",
    )
    netz.add_argument(
        "--schluessel",
        type=Path,
        default=None,
        help="Privater Schlüssel zu --zertifikat, falls nicht in derselben Datei.",
    )
    netz.add_argument(
        "--max-streams",
        type=int,
        default=None,
        dest="max_streams",
        help="Höchstzahl gleichzeitiger Streams über alle Kameras. Standard 4.",
    )

    kameras = zerleger.add_argument_group("Kameras")
    kameras.add_argument(
        "--kamera",
        action="append",
        default=[],
        metavar="[NAME=]GERAET",
        help="Kamera festlegen, mehrfach möglich: --kamera /dev/video0 oder "
        "--kamera Garten=/dev/video0. Ohne Angabe werden alle "
        "angeschlossenen Kameras erkannt.",
    )
    kameras.add_argument(
        "--aufloesung",
        type=aufloesung_pruefen,
        default=None,
        metavar="BREITExHOEHE",
        help="Bildgröße für alle Kameras. Standard 640x480.",
    )
    kameras.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Obergrenze der Bildrate für alle Kameras. Standard 15. Mehr als "
        "rund 16 schafft dieser Pi bei 640x480 nicht, weil er jedes Bild "
        "selbst nach JPEG wandeln muss.",
    )
    kameras.add_argument(
        "--qualitaet",
        type=int,
        default=None,
        choices=range(1, 101),
        metavar="1-100",
        help="JPEG-Qualität für alle Kameras. Standard 75.",
    )
    kameras.add_argument(
        "--format",
        default=None,
        choices=FORMATWAHL,
        help="Bildformat der Kameras. 'auto' (Standard) nimmt MJPEG, wo die "
        "Kamera es kann, und gibt die Bilder dann ohne Umwandlung weiter; "
        "das spart CPU und USB-Bandbreite.",
    )
    kameras.add_argument(
        "--regler",
        type=regler_pruefen,
        action="append",
        default=[],
        metavar="NAME=WERT",
        help="Kameraregler setzen, mehrfach möglich, etwa brightness=10.",
    )

    sonstiges = zerleger.add_argument_group("Sonstiges")
    sonstiges.add_argument(
        "--konfiguration",
        type=Path,
        default=None,
        metavar="DATEI",
        help=f"Andere Konfigurationsdatei als {KONFIGURATIONSDATEI}.",
    )
    sonstiges.add_argument("--titel", default=None, help="Überschrift der Seite.")
    sonstiges.add_argument(
        "--protokoll",
        default=None,
        choices=PROTOKOLLSTUFEN,
        help="Ausführlichkeit der Meldungen. Standard info.",
    )
    sonstiges.add_argument(
        "--kameras-liste",
        action="store_true",
        dest="kameras_liste",
        help="Nennt die angeschlossenen Kameras samt Auflösungen und beendet sich.",
    )
    sonstiges.add_argument(
        "--regler-liste",
        action="store_true",
        dest="regler_liste",
        help="Nennt die Regler der Kameras und beendet sich.",
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
    # linuxpy meldet jedes Öffnen und Schließen des Geräts auf INFO.
    # Das ist nur beim Suchen von Fehlern interessant.
    logging.getLogger("linuxpy").setLevel(
        logging.DEBUG if wert <= logging.DEBUG else logging.WARNING
    )


# ---------------------------------------------------------------------------
# Auskunftsbefehle
# ---------------------------------------------------------------------------


def kameras_auflisten() -> int:
    """Gibt aus, welche Kameras erkannt werden."""
    try:
        erkannt = kameras_erkennen()
    except Exception as fehler:  # noqa: BLE001 - Meldung statt Traceback
        log.error("Kameras nicht abfragbar: %s", fehler)
        return 1

    if not erkannt:
        print("Keine Kamera gefunden.")
        print()
        print("Mögliche Ursachen: Kein USB-Gerät angeschlossen, oder der")
        print("Benutzer ist nicht in der Gruppe 'video'.")
        return 1

    print(f"{len(erkannt)} Kamera(s) gefunden:")
    for kamera in erkannt:
        groessen = ", ".join(f"{b}x{h}" for b, h in kamera.aufloesungen)
        print()
        print(f"  {kamera.name}")
        print(f"    Gerät jetzt : {kamera.geraet}")
        if kamera.pfad_by_id:
            print(f"    Stabil      : {kamera.pfad_by_id}")
        if kamera.pfad_by_path:
            print(f"    Nach Port   : {kamera.pfad_by_path}")
        print(f"    Treiber     : {kamera.treiber}")
        print(f"    Bus         : {kamera.bus}")
        print(f"    Formate     : {', '.join(kamera.pixelformate)}")
        if kamera.kann_mjpeg:
            print("                  (MJPEG: Bilder gehen ohne Umwandlung durch)")
        print(f"    Auflösungen : {groessen}")

    print()
    print("Zum Übernehmen in webcam_stream.yml:")
    print()
    print("kameras:")
    for nummer, kamera in enumerate(erkannt, start=1):
        # Die Standardauflösung vorschlagen, wenn die Kamera sie kann.
        # Das Maximum vorzuschlagen würde ungefragt viel Bandbreite und
        # CPU kosten.
        groesse = next(
            (
                (b, h)
                for b, h in kamera.aufloesungen
                if b <= STANDARD_BREITE and h <= STANDARD_HOEHE
            ),
            kamera.aufloesungen[0] if kamera.aufloesungen else (640, 480),
        )
        print(f"  - geraet: {kamera.empfohlener_pfad}")
        print(f"    name: {kamera.name or f'Kamera {nummer}'}")
        print(f'    aufloesung: "{groesse[0]}x{groesse[1]}"')

    if any(kamera.pfad_by_id for kamera in erkannt):
        print()
        print("Hinweis: Die Nummern unter /dev/videoN können sich beim")
        print("Neustarten oder Umstecken verschieben. Die oben gezeigten")
        print("Pfade unter /dev/v4l/by-id/ bleiben an der Kamera.")
    return 0


def regler_auflisten(konfiguration: Dienstkonfiguration) -> int:
    """Gibt die Regler aller konfigurierten Kameras aus."""
    rueckgabe = 0
    for kamera in konfiguration.kameras:
        print(f"{kamera.anzeigename} ({kamera.geraet}):")
        try:
            for name in verfuegbare_regler(kamera.geraet):
                print(f"  {name}")
        except Exception as fehler:  # noqa: BLE001 - eine Kamera darf scheitern
            print(f"  nicht lesbar: {fehler}")
            rueckgabe = 1
        print()
    return rueckgabe


# ---------------------------------------------------------------------------
# Zugang
# ---------------------------------------------------------------------------


def ist_nur_lokal(host: str) -> bool:
    """True, wenn die Adresse ausschließlich von diesem Rechner erreichbar ist."""
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def zugang_klaeren(konfiguration: Dienstkonfiguration) -> Zugangsdaten | None:
    """Setzt die Zugangsregel oder gibt None zurück, wenn sie unsicher wäre.

    Regel: Ein Stream, der über das Netz erreichbar ist, braucht ein
    Passwort. Wer das nicht will, muss es mit --ohne-anmeldung
    ausdrücklich sagen.
    """
    passwort = konfiguration.passwort or os.environ.get("WEBCAM_PASSWORT") or None
    nur_lokal = ist_nur_lokal(konfiguration.host)

    if konfiguration.ohne_anmeldung:
        if not nur_lokal:
            log.warning(
                "Der Stream ist auf %s ohne Anmeldung erreichbar. Jeder im Netz "
                "kann das Kamerabild sehen.",
                konfiguration.host,
            )
        return Zugangsdaten(None, None)

    if passwort:
        if not nur_lokal and konfiguration.zertifikat is None:
            log.warning(
                "Anmeldung über HTTP ohne TLS: Das Passwort geht nur base64-kodiert "
                "durchs Netz und ist mitlesbar. Für echten Schutz --zertifikat setzen."
            )
        return Zugangsdaten(konfiguration.benutzer, passwort)

    if nur_lokal:
        log.info(
            "Kein Passwort gesetzt. Unkritisch, weil %s nur von diesem Rechner "
            "erreichbar ist.",
            konfiguration.host,
        )
        return Zugangsdaten(None, None)

    log.error(
        "Abbruch: host %s macht den Stream im Netz erreichbar, aber es ist kein "
        "Passwort gesetzt.\n"
        "        Passwort setzen:   WEBCAM_PASSWORT=... %s --host %s\n"
        "        oder ausdrücklich ohne Schutz freigeben: --ohne-anmeldung",
        konfiguration.host,
        Path(sys.argv[0]).name,
        konfiguration.host,
    )
    return None


def erreichbare_adressen(host: str, port: int, tls: bool) -> list[str]:
    """Baut die Adressen, die der Anwender im Browser eingeben kann."""
    schema = "https" if tls else "http"
    if host not in ("0.0.0.0", "::", ""):
        gezeigt = f"[{host}]" if ":" in host else host
        return [f"{schema}://{gezeigt}:{port}/"]

    adressen = [f"{schema}://127.0.0.1:{port}/"]
    try:
        # Verbindungsloser Trick, um die eigene LAN-Adresse zu erfahren,
        # ohne Pakete zu senden und ohne DNS zu befragen.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as test:
            test.connect(("192.0.2.1", 1))
            adressen.append(f"{schema}://{test.getsockname()[0]}:{port}/")
    except OSError:
        pass
    return adressen


# ---------------------------------------------------------------------------
# Hauptlauf
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argumente = argumente_lesen(argv)

    # Vorläufige Protokollstufe, damit Meldungen aus dem Einlesen der
    # Konfiguration schon sichtbar sind.
    protokoll_einrichten(argumente.protokoll or "info")

    if argumente.kameras_liste:
        return kameras_auflisten()

    try:
        konfiguration = konfiguration_bauen(argumente, VERZEICHNIS)
    except Konfigurationsfehler as fehler:
        log.error("%s", fehler)
        return 2

    protokoll_einrichten(konfiguration.protokoll)

    if argumente.regler_liste:
        return regler_auflisten(konfiguration)

    zugang = zugang_klaeren(konfiguration)
    if zugang is None:
        return 2

    if konfiguration.zertifikat is not None and not konfiguration.zertifikat.is_file():
        log.error("Zertifikatsdatei nicht gefunden: %s", konfiguration.zertifikat)
        return 1

    try:
        register = Kameraregister(konfiguration.kameras, konfiguration.zeiten)
    except ValueError as fehler:
        log.error("Kameras nicht verwendbar: %s", fehler)
        return 2

    try:
        server = server_bauen(
            register=register,
            host=konfiguration.host,
            port=konfiguration.port,
            zugang=zugang,
            titel=konfiguration.titel,
            zertifikat=konfiguration.zertifikat,
            schluessel=konfiguration.schluessel,
        )
    except FileNotFoundError as fehler:
        log.error("Datei für die Weboberfläche fehlt: %s", fehler)
        return 1
    except OSError as fehler:
        log.error(
            "Server startet nicht auf %s:%s — %s",
            konfiguration.host,
            konfiguration.port,
            fehler,
        )
        return 1

    def beenden(signalnummer, rahmen) -> None:  # noqa: ARG001 - Signatur vorgegeben
        log.info("Beende (Signal %s)", signalnummer)
        # shutdown() aus dem Signalkontext heraus würde blockieren,
        # deshalb in einem eigenen Thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, beenden)
    signal.signal(signal.SIGTERM, beenden)

    schutz = "mit Anmeldung" if zugang.aktiv else "ohne Anmeldung"
    log.info(
        "%d Kamera(n) %s, %s. Zum Beenden Strg+C.",
        len(register),
        konfiguration.quelle_der_kameras,
        schutz,
    )
    for kamera in konfiguration.kameras:
        log.info(
            "  %-18s %s  %dx%d  %.0f fps  Q%d  ->  /kamera/%s",
            kamera.anzeigename,
            kamera.geraet,
            kamera.breite,
            kamera.hoehe,
            kamera.bildrate,
            kamera.qualitaet,
            kamera.kennung,
        )
    for adresse in erreichbare_adressen(
        konfiguration.host, konfiguration.port, konfiguration.zertifikat is not None
    ):
        log.info("  %s", adresse)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        register.alle_stoppen()
        server.server_close()
        log.info("Beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
