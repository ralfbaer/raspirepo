"""Einstellungen aus `webcam_stream.yml` und Kommandozeile zusammenführen.

Rangfolge, von stark nach schwach:

    1. Kommandozeilenargumente
    2. webcam_stream.yml
    3. eingebaute Standardwerte in `einstellungen.py`

Fehlt die Datei, läuft das Programm mit den Standardwerten weiter und
schreibt einen Hinweis ins Protokoll. Eine vorhandene, aber fehlerhafte
Datei führt dagegen zum Abbruch mit Angabe von Pfad und Zeile: Ein
stiller Rückfall auf Standardwerte würde eine Fehlkonfiguration
verschleiern.

Unbekannte Schlüssel werden gemeldet, nicht übergangen. Sie sind in der
Regel Tippfehler, und ein übergangener Tippfehler bedeutet, dass eine
Einstellung wirkungslos bleibt, ohne dass es auffällt.

Gelesen wird ausschließlich mit `yaml.safe_load`. `yaml.load` kann
beliebige Python-Objekte erzeugen und wird nicht verwendet.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from einstellungen import (
    PROTOKOLLSTUFEN,
    STANDARD_BILDRATE,
    STANDARD_BREITE,
    STANDARD_FORMAT,
    STANDARD_HOEHE,
    STANDARD_QUALITAET,
    Dienstkonfiguration,
    Kameraeinstellung,
    Zeiten,
)
from kamera import FORMATWAHL, geraet_aufloesen, kameras_erkennen, kennung_bilden

log = logging.getLogger(__name__)

# Die Konfigurationsdatei heißt wie das Programm und liegt daneben.
KONFIGURATIONSDATEI = "webcam_stream.yml"

# Erlaubte Schlüssel. Alles andere gilt als Tippfehler.
ERLAUBT_OBEN = {
    "host", "port", "titel", "protokoll", "anmeldung", "grenzen", "vorgaben",
    "kameras",
}
ERLAUBT_ANMELDUNG = {"benutzer", "ohne_anmeldung", "zertifikat", "schluessel"}
ERLAUBT_GRENZEN = {
    "max_streams", "leerlauf", "wiederholung", "erstes_bild", "stream_stille",
    "fehlanmeldung", "usb_richtwert",
}
ERLAUBT_VORGABEN = {"aufloesung", "fps", "qualitaet", "format"}
ERLAUBT_KAMERA = {
    "geraet", "kennung", "name", "aufloesung", "fps", "qualitaet", "format", "regler",
}


class Konfigurationsfehler(Exception):
    """Die Einstellungen sind fehlerhaft, widersprüchlich oder unbrauchbar."""


# ---------------------------------------------------------------------------
# Datei lesen und prüfen
# ---------------------------------------------------------------------------


def datei_lesen(pfad: Path) -> dict:
    """Liest die YAML-Datei und prüft Grundstruktur und Schlüsselnamen."""
    try:
        text = pfad.read_text(encoding="utf-8")
    except OSError as fehler:
        raise Konfigurationsfehler(f"{pfad} nicht lesbar: {fehler}") from None

    try:
        inhalt = yaml.safe_load(text)
    except yaml.MarkedYAMLError as fehler:
        stelle = fehler.problem_mark
        ort = f"{pfad}, Zeile {stelle.line + 1}, Spalte {stelle.column + 1}" if stelle else str(pfad)
        raise Konfigurationsfehler(
            f"{ort}: {fehler.problem or 'YAML-Fehler'}"
        ) from None
    except yaml.YAMLError as fehler:
        raise Konfigurationsfehler(f"{pfad} ist kein gültiges YAML: {fehler}") from None

    if inhalt is None:
        log.warning("%s ist leer, es gelten die Standardwerte.", pfad)
        return {}
    if not isinstance(inhalt, dict):
        raise Konfigurationsfehler(
            f"{pfad}: Die oberste Ebene muss eine Zuordnung sein "
            f"(etwa 'port: 8080'), gefunden wurde {type(inhalt).__name__}."
        )

    _schluessel_pruefen(inhalt, ERLAUBT_OBEN, str(pfad), "oberste Ebene")
    for name, erlaubt in (
        ("anmeldung", ERLAUBT_ANMELDUNG),
        ("grenzen", ERLAUBT_GRENZEN),
        ("vorgaben", ERLAUBT_VORGABEN),
    ):
        abschnitt = inhalt.get(name)
        if abschnitt is None:
            continue
        if not isinstance(abschnitt, dict):
            raise Konfigurationsfehler(
                f"{pfad}: '{name}' muss ein Abschnitt mit Unterschlüsseln sein."
            )
        _schluessel_pruefen(abschnitt, erlaubt, str(pfad), name)

    kameras = inhalt.get("kameras")
    if kameras is not None:
        if not isinstance(kameras, list):
            raise Konfigurationsfehler(
                f"{pfad}: 'kameras' muss eine Liste sein. Jeder Eintrag beginnt "
                f"mit '- geraet: /dev/video0'."
            )
        for nummer, abschnitt in enumerate(kameras, start=1):
            if not isinstance(abschnitt, dict):
                raise Konfigurationsfehler(
                    f"{pfad}: Kameraeintrag {nummer} muss Unterschlüssel haben, "
                    f"mindestens 'geraet'."
                )
            _schluessel_pruefen(
                abschnitt, ERLAUBT_KAMERA, str(pfad), f"Kameraeintrag {nummer}"
            )

    return inhalt


def _schluessel_pruefen(
    abschnitt: dict, erlaubt: set[str], pfad: str, ort: str
) -> None:
    unbekannt = set(map(str, abschnitt)) - erlaubt
    if unbekannt:
        raise Konfigurationsfehler(
            f"{pfad}: unbekannte Einstellung(en) in {ort}: "
            f"{', '.join(sorted(unbekannt))}. "
            f"Erlaubt sind: {', '.join(sorted(erlaubt))}."
        )


# ---------------------------------------------------------------------------
# Werte prüfen
# ---------------------------------------------------------------------------


def zahl_lesen(
    wert, name: str, woher: str, mindestens: float | None = None,
    hoechstens: float | None = None, ganz: bool = False,
):
    """Prüft einen Zahlenwert aus der Konfiguration auf Typ und Bereich."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        raise Konfigurationsfehler(
            f"{woher}: '{name}' muss eine Zahl sein, gefunden wurde "
            f"{wert!r} ({type(wert).__name__})."
        )
    if ganz and int(wert) != wert:
        raise Konfigurationsfehler(
            f"{woher}: '{name}' muss eine ganze Zahl sein, nicht {wert}."
        )
    if mindestens is not None and wert < mindestens:
        raise Konfigurationsfehler(
            f"{woher}: '{name}' muss mindestens {mindestens} sein, nicht {wert}."
        )
    if hoechstens is not None and wert > hoechstens:
        raise Konfigurationsfehler(
            f"{woher}: '{name}' darf höchstens {hoechstens} sein, nicht {wert}."
        )
    return int(wert) if ganz else float(wert)


def aufloesung_zerlegen(wert, woher: str) -> tuple[int, int]:
    """Akzeptiert '640x480' sowie [640, 480]."""
    if isinstance(wert, (list, tuple)):
        if len(wert) != 2:
            raise Konfigurationsfehler(
                f"{woher}: 'aufloesung' braucht zwei Zahlen, nicht {len(wert)}."
            )
        try:
            breite, hoehe = int(wert[0]), int(wert[1])
        except (TypeError, ValueError):
            raise Konfigurationsfehler(
                f"{woher}: 'aufloesung' enthält keine Zahlen: {wert!r}."
            ) from None
    else:
        try:
            breite, hoehe = (int(teil) for teil in str(wert).lower().split("x", 1))
        except ValueError:
            raise Konfigurationsfehler(
                f"{woher}: '{wert}' ist keine Auflösung. Erwartet wird etwa 640x480."
            ) from None

    if breite <= 0 or hoehe <= 0:
        raise Konfigurationsfehler(f"{woher}: Auflösung muss positiv sein.")
    if breite % 2:
        raise Konfigurationsfehler(
            f"{woher}: Die Breite muss gerade sein, YUYV speichert je zwei Pixel "
            f"gemeinsam. {breite} geht nicht."
        )
    return breite, hoehe


def format_pruefen(wert, woher: str) -> str:
    """Prüft die Formatangabe gegen die erlaubten Werte."""
    gewaehlt = str(wert).strip().lower()
    if gewaehlt not in FORMATWAHL:
        raise Konfigurationsfehler(
            f"{woher}: 'format' muss einer von {', '.join(FORMATWAHL)} sein, "
            f"nicht '{wert}'."
        )
    return gewaehlt


def zeiten_lesen(abschnitt: dict, woher: str) -> Zeiten:
    """Baut die Zeitgrenzen aus dem Abschnitt 'grenzen'."""
    zeiten = Zeiten()
    if not abschnitt:
        return zeiten

    if "max_streams" in abschnitt:
        zeiten.max_streams = zahl_lesen(
            abschnitt["max_streams"], "max_streams", woher, mindestens=1,
            hoechstens=64, ganz=True,
        )
    for name, mindestens, hoechstens in (
        ("leerlauf", 0.0, 3600.0),
        ("wiederholung", 0.1, 3600.0),
        ("erstes_bild", 0.5, 300.0),
        ("stream_stille", 0.5, 3600.0),
        ("fehlanmeldung", 0.0, 60.0),
    ):
        if name in abschnitt:
            setattr(
                zeiten,
                name,
                zahl_lesen(abschnitt[name], name, woher, mindestens, hoechstens),
            )
    if "usb_richtwert" in abschnitt:
        zeiten.usb_richtwert = zahl_lesen(
            abschnitt["usb_richtwert"], "usb_richtwert", woher,
            mindestens=1_000_000, ganz=True,
        )
    return zeiten


# ---------------------------------------------------------------------------
# Kameras zusammenstellen
# ---------------------------------------------------------------------------


def kamera_aus_abschnitt(
    abschnitt: dict,
    nummer: int,
    vergeben: set[str],
    woher: str,
    vorgabe_breite: int,
    vorgabe_hoehe: int,
    vorgabe_fps: float,
    vorgabe_qualitaet: int,
    vorgabe_format: str = STANDARD_FORMAT,
) -> Kameraeinstellung:
    """Baut eine Kameraeinstellung aus einem Eintrag der Liste 'kameras'."""
    ort = f"{woher}, Kamera {nummer}"

    geraet = str(abschnitt.get("geraet", "") or "").strip()
    if not geraet:
        raise Konfigurationsfehler(
            f"{ort}: 'geraet' fehlt. Erwartet wird etwa /dev/video0."
        )

    if "aufloesung" in abschnitt:
        breite, hoehe = aufloesung_zerlegen(abschnitt["aufloesung"], ort)
    else:
        breite, hoehe = vorgabe_breite, vorgabe_hoehe

    bildrate = (
        zahl_lesen(abschnitt["fps"], "fps", ort, mindestens=0.0, hoechstens=120.0)
        if "fps" in abschnitt
        else vorgabe_fps
    )
    qualitaet = (
        zahl_lesen(
            abschnitt["qualitaet"], "qualitaet", ort, mindestens=1, hoechstens=100,
            ganz=True,
        )
        if "qualitaet" in abschnitt
        else vorgabe_qualitaet
    )

    name = str(abschnitt.get("name") or f"Kamera {nummer}")
    kennung = kennung_bilden(str(abschnitt.get("kennung") or name), vergeben)
    vergeben.add(kennung)

    regler = abschnitt.get("regler") or {}
    if not isinstance(regler, dict):
        raise Konfigurationsfehler(
            f"{ort}: 'regler' muss Unterschlüssel haben, etwa 'brightness: 10'."
        )
    steuerwerte = {
        str(schluessel): zahl_lesen(
            wert, f"regler.{schluessel}", ort, mindestens=-100_000,
            hoechstens=100_000, ganz=True,
        )
        for schluessel, wert in regler.items()
    }

    bildformat = (
        format_pruefen(abschnitt["format"], ort)
        if "format" in abschnitt
        else vorgabe_format
    )

    return Kameraeinstellung(
        geraet=geraet,
        kennung=kennung,
        anzeigename=name,
        breite=breite,
        hoehe=hoehe,
        bildrate=bildrate,
        qualitaet=qualitaet,
        bildformat=bildformat,
        steuerwerte=steuerwerte,
    )


def kameras_automatisch(
    erkannt: list,
    breite: int, hoehe: int, bildrate: float, qualitaet: int,
    bildformat: str = STANDARD_FORMAT,
    steuerwerte: dict[str, int] | None = None,
) -> list[Kameraeinstellung]:
    """Stellt die erkannten Kameras zusammen.

    Jede Kamera erhält die größte Auflösung, die sie kann, aber nicht
    mehr als vorgegeben. Grund: 640x480 ist das Maximum der einen
    angeschlossenen Kamera, eine andere kann mehr — dann soll nicht
    ungefragt eine höhere Datenrate entstehen.
    """
    if not erkannt:
        raise Konfigurationsfehler(
            "Keine Kamera gefunden. Steckt eine Webcam am USB-Port? "
            "Mit --kameras-liste nachsehen, mit --kamera /dev/video0 ein "
            "Gerät erzwingen."
        )

    einstellungen: list[Kameraeinstellung] = []
    vergeben: set[str] = set()
    for nummer, kamera in enumerate(erkannt, start=1):
        passend = [(b, h) for b, h in kamera.aufloesungen if b <= breite and h <= hoehe]
        gewaehlt = (
            passend[0]
            if passend
            else min(kamera.aufloesungen, key=lambda wh: wh[0] * wh[1])
        )
        if gewaehlt != (breite, hoehe):
            log.info(
                "%s kann %dx%d nicht, gewählt wird %dx%d",
                kamera.geraet, breite, hoehe, gewaehlt[0], gewaehlt[1],
            )

        name = kamera.name or f"Kamera {nummer}"
        kennung = kennung_bilden(name, vergeben)
        vergeben.add(kennung)
        if kamera.kann_mjpeg and bildformat == "auto":
            log.info(
                "%s kann MJPEG und wird ohne Umwandlung durchgereicht.", kamera.geraet
            )
        einstellungen.append(
            Kameraeinstellung(
                # Den stabilen Pfad nehmen, damit ein Neustart nach dem
                # Umstecken nicht auf einer anderen Kamera landet.
                geraet=kamera.empfohlener_pfad,
                kennung=kennung,
                anzeigename=name,
                breite=gewaehlt[0],
                hoehe=gewaehlt[1],
                bildrate=bildrate,
                qualitaet=qualitaet,
                bildformat=bildformat,
                steuerwerte=dict(steuerwerte or {}),
            )
        )
    return einstellungen


def bandbreite_pruefen(
    kameras: list[Kameraeinstellung], erkannt: list, richtwert: int
) -> None:
    """Warnt, wenn die Kameras zusammen zu viel USB-Bandbreite fordern.

    Die Abschätzung braucht die Information, ob eine Kamera MJPEG
    liefert, denn das macht einen Faktor von rund acht aus. Liegt diese
    Information für eine Kamera nicht vor, etwa weil das Gerät gerade
    belegt ist, wird mit dem ungünstigeren Fall gerechnet. Dann wird
    auch gesagt, dass die Zahl unsicher ist: Eine Warnung, die auf einer
    stillen Annahme beruht, ist wertlos.
    """
    if len(kameras) < 2:
        return

    # Über den aufgelösten Pfad vergleichen: Die Konfiguration darf
    # /dev/v4l/by-id/... nennen, die Erkennung meldet /dev/videoN.
    nach_geraet = {geraet_aufloesen(kamera.geraet): kamera for kamera in erkannt}

    summe = 0.0
    unbekannt: list[str] = []
    for kamera in kameras:
        gefunden = nach_geraet.get(geraet_aufloesen(kamera.geraet))
        if kamera.bildformat == "mjpeg":
            mjpeg = True
        elif kamera.bildformat == "yuyv":
            mjpeg = False
        elif gefunden is not None:
            mjpeg = gefunden.kann_mjpeg
        else:
            mjpeg = False
            unbekannt.append(kamera.geraet)
        summe += kamera.rohdatenrate(mjpeg)

    zusatz = ""
    if unbekannt:
        zusatz = (
            f" Für {', '.join(unbekannt)} war nicht feststellbar, ob MJPEG "
            f"genutzt wird; dafür ist der ungünstigere Fall gerechnet, die "
            f"Summe kann also deutlich zu hoch sein."
        )

    log.info(
        "%d Kameras, zusammen bis zu %.1f MB/s über USB (Abschätzung mit "
        "30 fps je Kamera).%s",
        len(kameras), summe / 1e6, zusatz,
    )
    if summe > richtwert and not unbekannt:
        log.warning(
            "Das liegt über dem Richtwert von %.0f MB/s für USB 2.0. Wenn Bilder "
            "ausbleiben oder die Bildrate einbricht, die Auflösung einzelner "
            "Kameras senken (etwa aufloesung: \"320x240\").",
            richtwert / 1e6,
        )

    # Kameras am selben USB-Controller teilen sich die Bandbreite
    # wirklich, nicht nur rechnerisch. Darauf lohnt ein eigener Hinweis.
    nach_bus: dict[str, list[str]] = {}
    for kamera in kameras:
        gefunden = nach_geraet.get(geraet_aufloesen(kamera.geraet))
        if gefunden and gefunden.bus:
            nach_bus.setdefault(gefunden.bus.rsplit("-", 1)[0], []).append(
                kamera.geraet
            )
    for bus, geraete in nach_bus.items():
        if len(geraete) > 1:
            log.info(
                "Am Bus %s hängen mehrere Kameras (%s). Sie teilen sich die "
                "Bandbreite dieses Controllers.",
                bus, ", ".join(geraete),
            )


# ---------------------------------------------------------------------------
# Zusammenführung
# ---------------------------------------------------------------------------


def konfiguration_bauen(argumente, verzeichnis: Path) -> Dienstkonfiguration:
    """Führt Standardwerte, Datei und Kommandozeile zusammen.

    Ein Wert aus der Kommandozeile gilt nur dann als gesetzt, wenn er
    nicht `None` ist. Deshalb haben die Argumente in `webcam_stream.py`
    keine Standardwerte, sondern `None`: Nur so ist unterscheidbar, ob
    der Anwender etwas angegeben hat oder nicht.
    """
    konfiguration = Dienstkonfiguration()

    # --- Datei ---
    pfad: Path | None = argumente.konfiguration
    if pfad is not None:
        if not pfad.is_file():
            raise Konfigurationsfehler(f"Konfigurationsdatei nicht gefunden: {pfad}")
    else:
        kandidat = verzeichnis / KONFIGURATIONSDATEI
        pfad = kandidat if kandidat.is_file() else None

    inhalt: dict = {}
    if pfad is None:
        log.info(
            "Keine Konfigurationsdatei (%s) gefunden, es gelten die eingebauten "
            "Standardwerte.",
            verzeichnis / KONFIGURATIONSDATEI,
        )
        konfiguration.quelle_der_datei = "keine Datei, Standardwerte"
    else:
        inhalt = datei_lesen(pfad)
        konfiguration.quelle_der_datei = str(pfad)

    woher = str(pfad) if pfad else "Standardwerte"

    # --- Dienstebene aus der Datei ---
    if "host" in inhalt:
        konfiguration.host = str(inhalt["host"])
    if "port" in inhalt:
        konfiguration.port = zahl_lesen(
            inhalt["port"], "port", woher, mindestens=1, hoechstens=65535, ganz=True
        )
    if "titel" in inhalt:
        konfiguration.titel = str(inhalt["titel"])
    if "protokoll" in inhalt:
        konfiguration.protokoll = str(inhalt["protokoll"]).lower()

    anmeldung = inhalt.get("anmeldung") or {}
    if "benutzer" in anmeldung:
        konfiguration.benutzer = str(anmeldung["benutzer"])
    if "ohne_anmeldung" in anmeldung:
        if not isinstance(anmeldung["ohne_anmeldung"], bool):
            raise Konfigurationsfehler(
                f"{woher}: 'ohne_anmeldung' muss true oder false sein."
            )
        konfiguration.ohne_anmeldung = anmeldung["ohne_anmeldung"]
    if anmeldung.get("zertifikat"):
        konfiguration.zertifikat = Path(str(anmeldung["zertifikat"])).expanduser()
    if anmeldung.get("schluessel"):
        konfiguration.schluessel = Path(str(anmeldung["schluessel"])).expanduser()

    konfiguration.zeiten = zeiten_lesen(inhalt.get("grenzen") or {}, woher)

    # --- Kommandozeile schlägt die Datei ---
    for name in ("host", "titel", "benutzer", "protokoll"):
        wert = getattr(argumente, name, None)
        if wert is not None:
            setattr(konfiguration, name, wert)
    if argumente.port is not None:
        konfiguration.port = argumente.port
    if argumente.max_streams is not None:
        konfiguration.zeiten.max_streams = argumente.max_streams
    if argumente.ohne_anmeldung:
        konfiguration.ohne_anmeldung = True
    if argumente.passwort is not None:
        konfiguration.passwort = argumente.passwort
    if argumente.zertifikat is not None:
        konfiguration.zertifikat = argumente.zertifikat
    if argumente.schluessel is not None:
        konfiguration.schluessel = argumente.schluessel

    if konfiguration.protokoll not in PROTOKOLLSTUFEN:
        raise Konfigurationsfehler(
            f"{woher}: 'protokoll' muss einer von "
            f"{', '.join(PROTOKOLLSTUFEN)} sein, nicht "
            f"'{konfiguration.protokoll}'."
        )
    if not 1 <= konfiguration.port <= 65535:
        raise Konfigurationsfehler(
            f"Port {konfiguration.port} liegt außerhalb von 1 bis 65535."
        )
    if konfiguration.port < 1024:
        log.warning(
            "Port %d ist ein privilegierter Port. Ohne root-Rechte scheitert das "
            "Binden; 8080 oder höher ist die sichere Wahl.",
            konfiguration.port,
        )

    # --- Vorgaben, die für alle Kameras gelten ---
    vorgaben = inhalt.get("vorgaben") or {}
    vorgabe_breite, vorgabe_hoehe = STANDARD_BREITE, STANDARD_HOEHE
    if "aufloesung" in vorgaben:
        vorgabe_breite, vorgabe_hoehe = aufloesung_zerlegen(
            vorgaben["aufloesung"], f"{woher}, vorgaben"
        )
    vorgabe_fps = (
        zahl_lesen(vorgaben["fps"], "fps", woher, mindestens=0.0, hoechstens=120.0)
        if "fps" in vorgaben
        else STANDARD_BILDRATE
    )
    vorgabe_qualitaet = (
        zahl_lesen(
            vorgaben["qualitaet"], "qualitaet", woher, mindestens=1, hoechstens=100,
            ganz=True,
        )
        if "qualitaet" in vorgaben
        else STANDARD_QUALITAET
    )
    vorgabe_format = (
        format_pruefen(vorgaben["format"], f"{woher}, vorgaben")
        if "format" in vorgaben
        else STANDARD_FORMAT
    )

    # Kommandozeile überschreibt die Vorgaben und damit auch die
    # Einzelwerte der Kameras: Wer --fps 5 tippt, meint alle Kameras.
    if argumente.aufloesung is not None:
        vorgabe_breite, vorgabe_hoehe = argumente.aufloesung
    if argumente.fps is not None:
        vorgabe_fps = argumente.fps
    if argumente.qualitaet is not None:
        vorgabe_qualitaet = argumente.qualitaet
    if argumente.format is not None:
        vorgabe_format = argumente.format

    # --- Kameras ---
    # Die Erkennung läuft genau einmal: Sie öffnet jedes Videogerät des
    # Systems, und ein zweiter Durchlauf würde auch die gerade belegten
    # Geräte anfassen.
    try:
        erkannt = kameras_erkennen()
    except Exception as fehler:  # noqa: BLE001 - ohne Erkennung geht es weiter
        log.warning("Kameraerkennung fehlgeschlagen: %s", fehler)
        erkannt = []

    if argumente.kamera:
        vergeben: set[str] = set()
        kameras = []
        for nummer, angabe in enumerate(argumente.kamera, start=1):
            # Form: /dev/video0  oder  Garten=/dev/video0
            name, trenner, geraet = angabe.partition("=")
            if not trenner:
                geraet, name = angabe, ""
            abschnitt: dict = {"geraet": geraet.strip()}
            if name.strip():
                abschnitt["name"] = name.strip()
            if argumente.regler:
                abschnitt["regler"] = dict(argumente.regler)
            kameras.append(
                kamera_aus_abschnitt(
                    abschnitt, nummer, vergeben, "--kamera",
                    vorgabe_breite, vorgabe_hoehe, vorgabe_fps, vorgabe_qualitaet,
                    vorgabe_format,
                )
            )
        konfiguration.kameras = kameras
        konfiguration.quelle_der_kameras = "Kommandozeile"

    elif inhalt.get("kameras"):
        vergeben = set()
        konfiguration.kameras = [
            kamera_aus_abschnitt(
                abschnitt, nummer, vergeben, woher,
                vorgabe_breite, vorgabe_hoehe, vorgabe_fps, vorgabe_qualitaet,
                vorgabe_format,
            )
            for nummer, abschnitt in enumerate(inhalt["kameras"], start=1)
        ]
        konfiguration.quelle_der_kameras = woher
        # Ausdrücklich getippte Werte gelten für alle Kameras, auch
        # gegen abweichende Einzelangaben in der Datei.
        for kamera in konfiguration.kameras:
            if argumente.aufloesung is not None:
                kamera.breite, kamera.hoehe = argumente.aufloesung
            if argumente.fps is not None:
                kamera.bildrate = argumente.fps
            if argumente.qualitaet is not None:
                kamera.qualitaet = argumente.qualitaet
            if argumente.format is not None:
                kamera.bildformat = argumente.format

    else:
        konfiguration.kameras = kameras_automatisch(
            erkannt,
            vorgabe_breite, vorgabe_hoehe, vorgabe_fps, vorgabe_qualitaet,
            vorgabe_format,
            dict(argumente.regler) if argumente.regler else None,
        )
        konfiguration.quelle_der_kameras = "automatisch erkannt"

    bandbreite_pruefen(
        konfiguration.kameras, erkannt, konfiguration.zeiten.usb_richtwert
    )
    return konfiguration
