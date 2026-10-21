"""Zugriff auf die USB-Kamera über V4L2 und Umwandlung der Frames in JPEG.

Die Kamera liefert ausschließlich YUYV 4:2:2 (geprüft: `v4l2-ctl
--list-formats-ext` kennt nur dieses Format). Jede Komprimierung muss
deshalb auf dem Host passieren.

Der Umweg über RGB wird bewusst vermieden: JPEG speichert intern
YCbCr, also wird YUYV nur auf YCbCr 4:4:4 hochgerechnet und direkt so
an Pillow gegeben. Das spart die Farbraumtransformation.

Es läuft immer nur ein Grabber-Thread, egal wie viele Clients
zuschauen. Gehalten wird ausschließlich der jeweils neueste Frame
(rund 26 KiB als JPEG), nie eine Folge von Frames. Grund: Der Host hat
nur rund 1,8 GiB RAM.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from einstellungen import Kameraeinstellung, Zeiten

log = logging.getLogger(__name__)

# Bildformate, die dieses Programm von einer Kamera entgegennehmen kann.
#
# MJPEG ist der bessere Weg, wo die Kamera es anbietet: Die Frames sind
# dann schon JPEG und werden unverändert an den Browser weitergegeben.
# Das kostet keine CPU und ein Bruchteil der USB-Bandbreite. Eine
# Logitech C615 liefert so 1920x1080, was als YUYV rund 124 MB/s wären
# und über USB 2.0 gar nicht möglich ist.
#
# YUYV ist der Rückfall für Kameras ohne eigene Komprimierung. Dann muss
# der Host jedes Bild selbst nach JPEG wandeln, rund 14 ms je Frame bei
# 640x480 (gemessen).
MJPEG = "MJPEG"
YUYV = "YUYV"
UNTERSTUETZTE_FORMATE = (MJPEG, YUYV)

# V4L2 identifiziert Formate über einen FourCC, also genau vier Zeichen.
# Der Name, unter dem linuxpy das Format meldet, ist nicht immer
# derselbe: Motion-JPEG heißt im Enum "MJPEG", der FourCC lautet aber
# "MJPG". `set_format` entpackt den String in `v4l2_fourcc(a, b, c, d)`
# und scheitert deshalb an fünf Zeichen.
FOURCC = {MJPEG: "MJPG", YUYV: "YUYV"}

# Werte, die in der Konfiguration für 'format' erlaubt sind.
FORMATWAHL = ("auto", "mjpeg", "yuyv")


def yuyv_nach_ycbcr(rohdaten: bytes, breite: int, hoehe: int) -> np.ndarray:
    """Rechnet einen YUYV-4:2:2-Frame auf YCbCr 4:4:4 hoch.

    In YUYV stehen je vier Bytes für zwei Pixel: Y0 Cb Y1 Cr. Die
    Chroma-Werte gelten für beide Pixel und werden dupliziert
    (nearest neighbour). Eine Interpolation wäre teurer und für einen
    JPEG-Stream nicht sichtbar, weil JPEG die Chroma gleich wieder
    unterabtastet.
    """
    paare = np.frombuffer(rohdaten, dtype=np.uint8).reshape(hoehe, breite // 2, 4)

    ycbcr = np.empty((hoehe, breite, 3), dtype=np.uint8)
    # Luma: Y0 auf die geraden, Y1 auf die ungeraden Spalten.
    ycbcr[:, 0::2, 0] = paare[:, :, 0]
    ycbcr[:, 1::2, 0] = paare[:, :, 2]
    # Chroma: je ein Wert auf beide Pixel des Paares.
    for kanal, quelle in ((1, 1), (2, 3)):
        werte = paare[:, :, quelle]
        ycbcr[:, 0::2, kanal] = werte
        ycbcr[:, 1::2, kanal] = werte
    return ycbcr


def ist_jpeg(daten: bytes) -> bool:
    """Prüft die JPEG-Rahmenmarken SOI und EOI.

    Nötig für MJPEG-Kameras: Deren Frames haben variable Länge, eine
    Längenprüfung wie bei YUYV ist also nicht möglich. Ein unvollständig
    übertragener Frame würde im Browser als defektes Bild erscheinen.
    """
    return len(daten) > 4 and daten[:2] == b"\xff\xd8" and daten[-2:] == b"\xff\xd9"


def ycbcr_nach_jpeg(ycbcr: np.ndarray, qualitaet: int) -> bytes:
    """Kodiert ein YCbCr-Array als JPEG."""
    hoehe, breite = ycbcr.shape[:2]
    bild = Image.frombuffer(
        "YCbCr", (breite, hoehe), ycbcr.tobytes(), "raw", "YCbCr", 0, 1
    )
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=qualitaet)
    return puffer.getvalue()


class Kameraquelle:
    """Ein Grabber-Thread, der den neuesten JPEG-Frame an alle Clients verteilt.

    Die Kamera wird erst geöffnet, wenn sich der erste Zuschauer
    anmeldet, und nach der Leerlaufzeit ohne Zuschauer wieder
    geschlossen. So belegt der Dienst im Ruhezustand weder USB-Bandbreite
    noch CPU.
    """

    def __init__(
        self, einstellung: Kameraeinstellung, zeiten: Zeiten | None = None
    ) -> None:
        self.einstellung = einstellung
        self.zeiten = zeiten or Zeiten()

        # Schützt Zuschauerzahl und Thread-Handle.
        self._verwaltung = threading.Lock()
        self._zuschauer = 0
        self._thread: threading.Thread | None = None
        self._beenden = threading.Event()

        # Schützt und signalisiert den jeweils neuesten Frame.
        self._frame_signal = threading.Condition()
        self._frame: bytes | None = None
        self._frame_nummer = 0
        self._frame_zeit = 0.0

        self._letzter_fehler: str | None = None
        self._frames_gesamt = 0
        self._verworfen = 0
        # Gleitende Mittelwerte für die Statusanzeige.
        self._intervall_ist = 0.0
        self._groesse_ist = 0.0
        self._format_benutzt: str | None = None
        self._gestartet_um: float | None = None

    # -- Zuschauerverwaltung ------------------------------------------------

    def anmelden(self) -> None:
        """Meldet einen Zuschauer an und startet bei Bedarf den Grabber."""
        with self._verwaltung:
            self._zuschauer += 1
            if self._thread is None or not self._thread.is_alive():
                self._beenden.clear()
                self._letzter_fehler = None
                self._thread = threading.Thread(
                    target=self._grabber_schleife, name="kamera-grabber", daemon=True
                )
                self._thread.start()
                log.info("Kamera gestartet (%d Zuschauer)", self._zuschauer)

    def abmelden(self) -> None:
        """Meldet einen Zuschauer ab und stoppt den Grabber nach Nachlaufzeit."""
        with self._verwaltung:
            self._zuschauer = max(0, self._zuschauer - 1)
            verbleibend = self._zuschauer
        if verbleibend == 0:
            threading.Timer(self.zeiten.leerlauf, self._leerlauf_pruefen).start()

    def _leerlauf_pruefen(self) -> None:
        """Stoppt den Grabber, wenn in der Nachlaufzeit niemand dazukam."""
        with self._verwaltung:
            if self._zuschauer > 0:
                return
            thread = self._thread
            self._thread = None
            self._beenden.set()
        if thread is not None:
            log.info("Kein Zuschauer mehr, Kamera wird freigegeben")

    def stoppen(self) -> None:
        """Beendet den Grabber endgültig, etwa beim Herunterfahren."""
        with self._verwaltung:
            self._beenden.set()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=3.0)
        with self._frame_signal:
            self._frame_signal.notify_all()

    # -- Frame-Abruf --------------------------------------------------------

    def auf_frame_warten(
        self, letzte_nummer: int, zeitlimit: float | None = None
    ) -> tuple[bytes, int] | None:
        """Wartet auf einen Frame, der neuer ist als `letzte_nummer`.

        Gibt `(jpeg, nummer)` zurück oder `None`, wenn innerhalb des
        Zeitlimits kein neuer Frame kam. Ohne Angabe gilt die Zeitgrenze
        für das erste Bild aus der Konfiguration.
        """
        if zeitlimit is None:
            zeitlimit = self.zeiten.erstes_bild
        ende = time.monotonic() + zeitlimit
        with self._frame_signal:
            while self._frame_nummer <= letzte_nummer:
                restzeit = ende - time.monotonic()
                if restzeit <= 0 or self._beenden.is_set():
                    return None
                self._frame_signal.wait(restzeit)
            assert self._frame is not None
            return self._frame, self._frame_nummer

    def einzelbild(self, zeitlimit: float | None = None) -> bytes | None:
        """Holt ein Einzelbild. Startet die Kamera, falls sie aus ist."""
        self.anmelden()
        try:
            ergebnis = self.auf_frame_warten(0, zeitlimit)
            if ergebnis is not None:
                return ergebnis[0]
            # Nach einem Neustart der Kamera ist Frame 1 schon vergeben;
            # dann liegt bereits ein Bild vor und wird direkt genommen.
            with self._frame_signal:
                return self._frame
        finally:
            self.abmelden()

    @property
    def letzter_fehler(self) -> str | None:
        return self._letzter_fehler

    def zustand(self) -> dict:
        """Momentaufnahme für die Statusanzeige."""
        with self._verwaltung:
            laeuft = self._thread is not None and self._thread.is_alive()
            zuschauer = self._zuschauer
        with self._frame_signal:
            frame_alter = (
                round(time.monotonic() - self._frame_zeit, 2) if self._frame_zeit else None
            )
            frames = self._frames_gesamt
            bildrate_ist = (
                round(1.0 / self._intervall_ist, 1) if self._intervall_ist else None
            )
            datenrate = (
                round(self._groesse_ist / self._intervall_ist / 1024, 1)
                if self._intervall_ist and self._groesse_ist
                else None
            )
        laufzeit = (
            round(time.monotonic() - self._gestartet_um, 1) if self._gestartet_um else None
        )
        return {
            "name": self.einstellung.anzeigename,
            "kamera_laeuft": laeuft,
            "zuschauer": zuschauer,
            "geraet": self.einstellung.geraet,
            "auflösung": f"{self.einstellung.breite}x{self.einstellung.hoehe}",
            "bildrate_soll": self.einstellung.bildrate,
            "bildrate_ist": bildrate_ist if laeuft else None,
            "format": self._format_benutzt,
            # Bei MJPEG bestimmt die Kamera die Qualität, der Wert aus
            # der Konfiguration wird dann nicht benutzt.
            "jpeg_qualitaet": (
                self.einstellung.qualitaet
                if self._format_benutzt != MJPEG
                else "von der Kamera"
            ),
            "datenrate_kib_s": datenrate if laeuft else None,
            "frames_gesamt": frames,
            "frames_verworfen": self._verworfen,
            "letzter_frame_alter_s": frame_alter,
            "laufzeit_s": laufzeit,
            "letzter_fehler": self._letzter_fehler,
        }

    # -- Grabber ------------------------------------------------------------

    def _grabber_schleife(self) -> None:
        """Öffnet die Kamera und liest Frames, bis zum Stopp.

        Bricht das USB-Gerät weg, wird der Fehler protokolliert und nach
        einer Pause neu geöffnet. Der HTTP-Server läuft dabei weiter.
        """
        self._gestartet_um = time.monotonic()
        voriger_fehler: str | None = None
        wiederholungen = 0

        while not self._beenden.is_set():
            try:
                self._einmal_streamen()
                voriger_fehler = None
                wiederholungen = 0
            except Exception as fehler:  # noqa: BLE001 - Dienst darf nicht sterben
                text = f"{type(fehler).__name__}: {fehler}"
                self._letzter_fehler = text

                # Denselben Fehler nicht endlos wiederholen. Ein dauerhaft
                # fehlendes Gerät würde das Protokoll sonst alle paar
                # Sekunden mit derselben Zeile füllen.
                if text == voriger_fehler:
                    wiederholungen += 1
                    if wiederholungen in (5, 50) or wiederholungen % 500 == 0:
                        log.error(
                            "%s: unverändert nach %d Versuchen: %s",
                            self.einstellung.kennung,
                            wiederholungen,
                            text,
                        )
                else:
                    log.error("%s: %s", self.einstellung.kennung, text)
                    voriger_fehler = text
                    wiederholungen = 0

                # Wartende Clients wecken, damit sie den Fehler sehen.
                with self._frame_signal:
                    self._frame_signal.notify_all()
                if self._beenden.wait(self.zeiten.wiederholung):
                    break
        self._gestartet_um = None
        log.info("Grabber beendet")

    def _einmal_streamen(self) -> None:
        """Ein Durchlauf: Kamera öffnen, Frames liefern, bis Stopp oder Fehler."""
        # Import erst hier, damit ein fehlendes linuxpy nicht den Import
        # des Moduls verhindert, sondern als Laufzeitfehler auftaucht.
        from linuxpy.video.device import Device, VideoCapture

        e = self.einstellung
        mindestabstand = 1.0 / e.bildrate if e.bildrate > 0 else 0.0

        with Device(e.geraet) as geraet:
            self._steuerwerte_setzen(geraet)
            aufnahme = VideoCapture(geraet)

            bildformat = self._format_bestimmen(geraet)
            aufnahme.set_format(e.breite, e.hoehe, FOURCC[bildformat])

            # Tatsächlich gesetztes Format übernehmen: Der Treiber darf
            # eine abweichende Auflösung zurückgeben.
            format_ist = geraet.get_format(1)
            breite, hoehe = format_ist.width, format_ist.height
            if (breite, hoehe) != (e.breite, e.hoehe):
                log.warning(
                    "%s liefert %dx%d statt %dx%d",
                    e.geraet, breite, hoehe, e.breite, e.hoehe,
                )
                e.breite, e.hoehe = breite, hoehe
            erwartete_groesse = breite * hoehe * 2

            self._format_benutzt = bildformat
            log.info(
                "%s liefert %dx%d %s%s",
                e.geraet,
                breite,
                hoehe,
                bildformat,
                " (wird unverändert weitergegeben)"
                if bildformat == MJPEG
                else f" (Umwandlung nach JPEG, Qualität {e.qualitaet})",
            )
            self._letzter_fehler = None

            naechste_ausgabe = 0.0
            letzter_eingang = 0.0
            quellintervall = 0.0

            with aufnahme:
                for frame in aufnahme:
                    if self._beenden.is_set():
                        return

                    jetzt = time.monotonic()

                    # Abstand der eintreffenden Frames mitschätzen
                    # (gleitender Mittelwert, damit einzelne Aussetzer
                    # nicht durchschlagen).
                    if letzter_eingang:
                        abstand = jetzt - letzter_eingang
                        quellintervall = (
                            abstand
                            if not quellintervall
                            else quellintervall * 0.8 + abstand * 0.2
                        )
                    letzter_eingang = jetzt

                    # Jeden Frame abholen, aber nur im Rahmen der
                    # Sollbildrate kodieren. Frames im Treiberpuffer
                    # liegen zu lassen würde die Latenz erhöhen.
                    #
                    # Die Toleranz von einem halben Quellintervall ist
                    # nötig: Ohne sie bricht die Ausgabe auf die Hälfte
                    # ein, sobald die Kamera nur knapp schneller liefert
                    # als gewünscht. Diese Kamera schafft gemessen rund
                    # 16,6 fps, bei Sollwert 15 wäre sonst jeder zweite
                    # Frame verworfen worden und 8 fps angekommen.
                    if mindestabstand:
                        if jetzt < naechste_ausgabe - quellintervall / 2:
                            continue
                        naechste_ausgabe = max(jetzt, naechste_ausgabe) + mindestabstand

                    rohdaten = bytes(frame)

                    if bildformat == MJPEG:
                        # Die Kamera hat schon JPEG geliefert. Nichts zu
                        # tun außer prüfen, ob der Frame vollständig ist.
                        if not ist_jpeg(rohdaten):
                            self._verworfen += 1
                            log.warning(
                                "%s: unvollständiger MJPEG-Frame mit %d Byte "
                                "verworfen",
                                e.geraet,
                                len(rohdaten),
                            )
                            continue
                        jpeg = rohdaten
                    else:
                        if len(rohdaten) != erwartete_groesse:
                            self._verworfen += 1
                            log.warning(
                                "%s: Frame mit %d statt %d Byte verworfen",
                                e.geraet,
                                len(rohdaten),
                                erwartete_groesse,
                            )
                            continue
                        jpeg = ycbcr_nach_jpeg(
                            yuyv_nach_ycbcr(rohdaten, breite, hoehe), e.qualitaet
                        )

                    self._frame_veroeffentlichen(jpeg)

    def _frame_veroeffentlichen(self, jpeg: bytes) -> None:
        with self._frame_signal:
            jetzt = time.monotonic()
            # Tatsächlich erreichte Ausgaberate mitschätzen, damit im
            # Status steht, was ankommt, und nicht nur, was gewünscht ist.
            # Gemittelt wird über die Abstände und die Bildgrößen, nicht
            # über die Bildrate selbst. Ein Mittelwert über Kehrwerte
            # wäre verzerrt: Ein einzelner sehr kurzer Abstand ergibt
            # einen riesigen Kehrwert und zieht das Ergebnis nach oben.
            # Beobachtet wurden so 22 fps bei tatsächlich 11,4.
            if self._frame_zeit:
                abstand = jetzt - self._frame_zeit
                if abstand > 0:
                    self._intervall_ist = (
                        abstand
                        if not self._intervall_ist
                        else self._intervall_ist * 0.8 + abstand * 0.2
                    )
            self._groesse_ist = (
                float(len(jpeg))
                if not self._groesse_ist
                else self._groesse_ist * 0.8 + len(jpeg) * 0.2
            )
            self._frame = jpeg
            self._frame_nummer += 1
            self._frames_gesamt += 1
            self._frame_zeit = jetzt
            self._frame_signal.notify_all()

    def _format_bestimmen(self, geraet) -> str:
        """Wählt das Bildformat, mit dem die Kamera geöffnet wird.

        Bei 'auto' wird MJPEG genommen, wenn die Kamera es anbietet. Das
        ist fast immer die richtige Wahl: Die Frames sind dann bereits
        JPEG, kosten keine CPU und einen Bruchteil der USB-Bandbreite.
        """
        wunsch = (self.einstellung.bildformat or "auto").lower()

        vorhanden = {
            eintrag.pixel_format.name
            for eintrag in geraet.info.formats
            if eintrag.pixel_format.name in UNTERSTUETZTE_FORMATE
        }
        if not vorhanden:
            raise RuntimeError(
                f"{self.einstellung.geraet} bietet weder MJPEG noch YUYV an. "
                f"Dieses Programm kann kein anderes Format verarbeiten."
            )

        if wunsch == "mjpeg":
            if MJPEG not in vorhanden:
                raise RuntimeError(
                    f"{self.einstellung.geraet} kann kein MJPEG. Möglich ist: "
                    f"{', '.join(sorted(vorhanden))}. In der Konfiguration "
                    f"'format: auto' oder 'format: yuyv' setzen."
                )
            return MJPEG
        if wunsch == "yuyv":
            if YUYV not in vorhanden:
                raise RuntimeError(
                    f"{self.einstellung.geraet} kann kein YUYV. Möglich ist: "
                    f"{', '.join(sorted(vorhanden))}."
                )
            return YUYV

        return MJPEG if MJPEG in vorhanden else YUYV

    def _steuerwerte_setzen(self, geraet) -> None:
        """Setzt Kameraregler wie Helligkeit, soweit vorhanden."""
        for name, wert in self.einstellung.steuerwerte.items():
            try:
                getattr(geraet.controls, name).value = wert
                log.info("Kameraregler %s = %s", name, wert)
            except Exception as fehler:  # noqa: BLE001 - Regler ist optional
                log.warning("Regler %s nicht gesetzt: %s", name, fehler)


def verfuegbare_regler(geraetepfad: str) -> list[str]:
    """Liest die Namen der Kameraregler aus. Für `--regler-liste`."""
    from linuxpy.video.device import Device

    with Device(geraetepfad) as geraet:
        return sorted(steuerung.config_name for steuerung in geraet.controls.values())


# ---------------------------------------------------------------------------
# Erkennung angeschlossener Kameras
# ---------------------------------------------------------------------------


# Von udev gepflegte Verzeichnisse mit stabilen Gerätenamen.
#
# Das ist nicht Kosmetik: Die Nummern unter /dev/videoN hängen von der
# Reihenfolge ab, in der die Geräte erkannt werden. Beobachtet am
# 20.10.2026: Dieselbe Logitech C615 war erst /dev/video2 und nach
# erneutem Anstecken /dev/video3. Bei mehreren Kameras kann eine
# Konfiguration mit /dev/videoN also auf die falsche Kamera zeigen.
#
# by-id enthält Hersteller, Modell und Seriennummer, ist damit an das
# Gerät gebunden. by-path ist an den USB-Port gebunden und die bessere
# Wahl bei zwei baugleichen Kameras ohne eigene Seriennummer.
BY_ID = Path("/dev/v4l/by-id")
BY_PATH = Path("/dev/v4l/by-path")

# Nur der Capture-Node ist interessant. index1 ist bei UVC-Kameras der
# Metadaten-Node.
CAPTURE_ENDUNG = "-video-index0"


def stabile_pfade() -> dict[str, dict[str, str]]:
    """Ordnet jedem /dev/videoN die stabilen Symlinks zu, die darauf zeigen."""
    zuordnung: dict[str, dict[str, str]] = {}
    for art, verzeichnis in (("by_id", BY_ID), ("by_path", BY_PATH)):
        if not verzeichnis.is_dir():
            continue
        for eintrag in sorted(verzeichnis.iterdir()):
            if not eintrag.name.endswith(CAPTURE_ENDUNG):
                continue
            try:
                ziel = str(eintrag.resolve(strict=True))
            except OSError:
                continue
            zuordnung.setdefault(ziel, {}).setdefault(art, str(eintrag))
    return zuordnung


def geraet_aufloesen(pfad: str) -> str:
    """Löst einen Symlink wie /dev/v4l/by-id/... auf /dev/videoN auf.

    Nötig, um Angaben aus der Konfiguration mit den Ergebnissen der
    Erkennung vergleichen zu können.
    """
    try:
        return str(Path(pfad).resolve(strict=True))
    except OSError:
        return pfad


@dataclass
class ErkannteKamera:
    """Was die Erkennung über ein gefundenes Gerät sagen kann."""

    geraet: str
    name: str
    bus: str
    treiber: str
    aufloesungen: list[tuple[int, int]]
    pixelformate: list[str]
    pfad_by_id: str | None = None
    pfad_by_path: str | None = None

    @property
    def kann_mjpeg(self) -> bool:
        """True, wenn die Kamera selbst JPEG liefern kann."""
        return MJPEG in self.pixelformate

    @property
    def empfohlener_pfad(self) -> str:
        """Der Pfad, der in die Konfiguration gehört.

        by-id zuerst, weil er an das Gerät gebunden ist und das Umstecken
        auf einen anderen Port übersteht.
        """
        return self.pfad_by_id or self.pfad_by_path or self.geraet


def kameras_erkennen() -> list[ErkannteKamera]:
    """Findet angeschlossene Kameras.

    Der Raspberry Pi bringt eine Reihe von V4L2-Geräten mit, die keine
    Kameras sind: `bcm2835-isp`, `bcm2835-codec`, `rpi-hevc-dec`. Einige
    davon melden ebenfalls "Video Capture" und tauchen in
    `iter_video_capture_devices()` auf.

    Unterscheidungsmerkmal ist der Typ der Bildgrößen: Eine echte Kamera
    meldet feste Größen (`DISCRETE`), die Verarbeitungseinheiten des Pi
    melden Bereiche (`STEPWISE`). Geprüft am 20.10.2026: `/dev/video0`
    liefert fünf DISCRETE-Einträge, `/dev/video14` und `/dev/video15`
    je nur STEPWISE.

    Der Metadaten-Node der Kamera (`/dev/video1`) taucht gar nicht auf,
    weil er keine Video-Capture-Fähigkeit meldet.
    """
    # Frmsizetypes liegt in linuxpy.video.raw, nicht in .device
    # (geprüft mit linuxpy 0.25.0).
    from linuxpy.video.device import iter_video_capture_devices
    from linuxpy.video.raw import Frmsizetypes

    verweise = stabile_pfade()
    gefunden: list[ErkannteKamera] = []
    for geraet in iter_video_capture_devices():
        pfad = str(geraet.filename)
        try:
            with geraet:
                groessen = [
                    eintrag
                    for eintrag in geraet.info.frame_sizes()
                    if eintrag.type == Frmsizetypes.DISCRETE
                ]
                if not groessen:
                    log.debug("%s übersprungen: keine festen Bildgrößen", pfad)
                    continue

                # Doppelte Auflösungen entfernen, größte zuerst.
                einzigartig = sorted(
                    {(eintrag.info.width, eintrag.info.height) for eintrag in groessen},
                    key=lambda wh: wh[0] * wh[1],
                    reverse=True,
                )
                info = geraet.info
                stabil = verweise.get(pfad, {})
                gefunden.append(
                    ErkannteKamera(
                        geraet=pfad,
                        name=namen_aufraeumen(info.card),
                        bus=info.bus_info,
                        treiber=info.driver,
                        aufloesungen=einzigartig,
                        pixelformate=sorted(
                            {eintrag.pixel_format.name for eintrag in groessen}
                        ),
                        pfad_by_id=stabil.get("by_id"),
                        pfad_by_path=stabil.get("by_path"),
                    )
                )
        except Exception as fehler:  # noqa: BLE001 - ein Gerät darf scheitern
            # Häufigster Grund: Das Gerät ist gerade von einem anderen
            # Prozess belegt. Das ist kein Fehler des Programms, aber es
            # muss sichtbar sein, weil die Kamera dann in der Liste fehlt.
            log.warning("%s nicht abfragbar: %s", pfad, fehler)

    gefunden.sort(key=lambda k: k.geraet)
    return gefunden


# Längste Kennung, die gebildet wird. Lange Gerätenamen ergeben sonst
# unhandliche Adressen.
KENNUNG_LAENGE = 32


def namen_aufraeumen(rohname: str) -> str:
    """Macht aus dem Gerätenamen des Treibers einen brauchbaren Anzeigenamen.

    UVC-Kameras melden im Feld `card` häufig denselben Text zweimal,
    getrennt durch einen Doppelpunkt: "USB2.0 Camera: USB2.0 Camera".
    Solche Wiederholungen werden entfernt.
    """
    teile = [teil.strip() for teil in rohname.split(":") if teil.strip()]
    ohne_doppel: list[str] = []
    for teil in teile:
        if teil.lower() not in {vorher.lower() for vorher in ohne_doppel}:
            ohne_doppel.append(teil)
    return ": ".join(ohne_doppel) if ohne_doppel else rohname.strip()


def kennung_bilden(vorschlag: str, vergeben: set[str]) -> str:
    """Macht aus einem Namen eine eindeutige, URL-sichere Kennung."""
    entschaerft = (
        namen_aufraeumen(vorschlag)
        .lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    kennung = "".join(
        zeichen if zeichen.isalnum() else "-" for zeichen in entschaerft
    )
    while "--" in kennung:
        kennung = kennung.replace("--", "-")
    kennung = kennung.strip("-")[:KENNUNG_LAENGE].strip("-") or "kamera"

    if kennung not in vergeben:
        return kennung
    nummer = 2
    while f"{kennung}-{nummer}" in vergeben:
        nummer += 1
    return f"{kennung}-{nummer}"


# ---------------------------------------------------------------------------
# Verwaltung mehrerer Kameras
# ---------------------------------------------------------------------------


class Kameraregister:
    """Hält alle konfigurierten Kameras und verwaltet die Streamplätze.

    Jede Kamera bekommt ihre eigene `Kameraquelle` mit eigenem
    Grabber-Thread. Die Zahl gleichzeitiger Streams wird dagegen
    gemeinsam begrenzt, weil CPU, RAM und USB-Bandbreite des Hosts
    geteilt werden und nicht pro Kamera zur Verfügung stehen.
    """

    def __init__(
        self, einstellungen: list[Kameraeinstellung], zeiten: Zeiten | None = None
    ) -> None:
        if not einstellungen:
            raise ValueError("Es muss mindestens eine Kamera konfiguriert sein.")

        self.zeiten = zeiten or Zeiten()
        self.quellen: dict[str, Kameraquelle] = {}
        for einstellung in einstellungen:
            if einstellung.kennung in self.quellen:
                raise ValueError(f"Kennung doppelt vergeben: {einstellung.kennung}")
            self.quellen[einstellung.kennung] = Kameraquelle(einstellung, self.zeiten)

        self.max_streams = self.zeiten.max_streams
        self._streams = 0
        self._stream_sperre = threading.Lock()

    def __len__(self) -> int:
        return len(self.quellen)

    @property
    def erste(self) -> Kameraquelle:
        """Für die Adressen ohne Kameraangabe."""
        return next(iter(self.quellen.values()))

    def holen(self, kennung: str) -> Kameraquelle | None:
        return self.quellen.get(kennung)

    def streamplatz_belegen(self) -> bool:
        """Belegt einen Streamplatz. False, wenn keiner frei ist."""
        with self._stream_sperre:
            if self._streams >= self.max_streams:
                return False
            self._streams += 1
            return True

    def streamplatz_freigeben(self) -> None:
        with self._stream_sperre:
            self._streams = max(0, self._streams - 1)

    @property
    def streams_aktiv(self) -> int:
        with self._stream_sperre:
            return self._streams

    def uebersicht(self) -> list[dict]:
        """Kurzbeschreibung aller Kameras für Seite und Status."""
        return [
            {
                "kennung": quelle.einstellung.kennung,
                "name": quelle.einstellung.anzeigename,
                "geraet": quelle.einstellung.geraet,
                "auflösung": f"{quelle.einstellung.breite}x{quelle.einstellung.hoehe}",
            }
            for quelle in self.quellen.values()
        ]

    def zustand(self) -> dict:
        return {
            "kameras": {
                kennung: quelle.zustand() for kennung, quelle in self.quellen.items()
            },
            "streams_aktiv": self.streams_aktiv,
            "streams_grenze": self.max_streams,
        }

    def alle_stoppen(self) -> None:
        for quelle in self.quellen.values():
            quelle.stoppen()
