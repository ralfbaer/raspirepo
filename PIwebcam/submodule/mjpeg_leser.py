"""Liest einen MJPEG-Strom (`multipart/x-mixed-replace`) über HTTP.

Quelle ist der laufende `webcam_stream.py`-Dienst auf demselben Pi. Der
Leser ist damit ein gewöhnlicher Zuschauer wie ein Browser und belegt
einen der `max_streams`-Plätze. Das ist Absicht: Ein V4L2-Gerät verträgt
nur einen Zugriff, also öffnet der Anzeige-Prozess die Kamera nicht
selbst, sondern bezieht die fertigen JPEG-Frames vom Dienst.

Die Grenzmarke zwischen den Teilen wird aus dem `Content-Type` der
Antwort gelesen, nicht fest verdrahtet. Jeder Teil nennt seine Länge im
`Content-Length`, danach folgen genau so viele JPEG-Bytes.

Bricht die Verbindung ab (Dienst neu gestartet, Netz kurz weg), wird mit
wachsendem Abstand neu verbunden, statt aufzugeben.

Nur HTTP. TLS wird nicht unterstützt: Der Dienst läuft lokal auf
`127.0.0.1`, da ist keine Verschlüsselung nötig. Für den Zugriff über
ein Netz gehört ohnehin ein SSH-Tunnel oder das Panel direkt am Pi.
"""

from __future__ import annotations

import base64
import logging
import time
from http.client import HTTPConnection, HTTPException
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


class MjpegFehler(Exception):
    """Die Antwort des Servers ist kein verwertbarer MJPEG-Strom."""


class Mjpegquelle:
    """Liefert fortlaufend JPEG-Frames aus einem MJPEG-HTTP-Strom.

    `bilder()` ist ein Generator, der Frames liefert und einen
    Verbindungsabbruch selbst überbrückt. Nur `http` wird unterstützt.
    """

    def __init__(
        self,
        basis_url: str,
        pfad: str,
        benutzer: str | None = None,
        passwort: str | None = None,
        zeitlimit: float = 15.0,
        startabstand: float = 1.0,
        maxabstand: float = 30.0,
    ) -> None:
        teile = urlsplit(basis_url)
        if teile.scheme and teile.scheme != "http":
            raise MjpegFehler(
                f"Nur http wird unterstützt, nicht '{teile.scheme}'. "
                f"Verschlüsselung über einen SSH-Tunnel lösen."
            )
        self._host = teile.hostname or "127.0.0.1"
        self._port = teile.port or 8080
        self._pfad = pfad
        self._zeitlimit = zeitlimit
        self._startabstand = startabstand
        self._maxabstand = maxabstand
        self._stop = False

        self._kopf: dict[str, str] = {}
        if passwort:
            roh = f"{benutzer or ''}:{passwort}".encode("utf-8")
            self._kopf["Authorization"] = "Basic " + base64.b64encode(roh).decode("ascii")

        self.quelle_text = f"http://{self._host}:{self._port}{pfad}"

    def stoppen(self) -> None:
        self._stop = True

    # -- Hauptschleife -----------------------------------------------------

    def bilder(self):
        """Generator: liefert JPEG-Bytes, verbindet bei Abbruch neu."""
        abstand = self._startabstand
        while not self._stop:
            conn = None
            try:
                conn, antwort, grenze = self._verbinden()
                log.info("Verbunden mit %s", self.quelle_text)
                abstand = self._startabstand
                for jpeg in self._teile(antwort, grenze):
                    if self._stop:
                        break
                    yield jpeg
            except (OSError, HTTPException, MjpegFehler) as fehler:
                if self._stop:
                    break
                log.warning(
                    "%s nicht erreichbar (%s). Neuer Versuch in %.0f s.",
                    self.quelle_text, fehler, abstand,
                )
                time.sleep(abstand)
                abstand = min(abstand * 2, self._maxabstand)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001 - Schließen darf nie werfen
                        pass

    # -- Verbindung und Zerlegung -----------------------------------------

    def _verbinden(self):
        conn = HTTPConnection(self._host, self._port, timeout=self._zeitlimit)
        conn.request("GET", self._pfad, headers=self._kopf)
        antwort = conn.getresponse()
        if antwort.status != 200:
            raise MjpegFehler(
                f"HTTP {antwort.status} {antwort.reason}. "
                f"Läuft webcam_stream.py, und stimmt die Kamera-Kennung?"
            )
        inhaltstyp = antwort.getheader("Content-Type", "")
        grenze = self._grenze_aus(inhaltstyp)
        if grenze is None:
            raise MjpegFehler(
                f"Keine MJPEG-Antwort (Content-Type: {inhaltstyp!r}). "
                f"Zeigt der Pfad auf einen Stream?"
            )
        return conn, antwort, b"--" + grenze.encode("ascii")

    @staticmethod
    def _grenze_aus(inhaltstyp: str) -> str | None:
        """Holt die Grenzmarke aus 'multipart/x-mixed-replace; boundary=…'."""
        if "multipart/x-mixed-replace" not in inhaltstyp:
            return None
        for teil in inhaltstyp.split(";"):
            teil = teil.strip()
            if teil.lower().startswith("boundary="):
                return teil[len("boundary="):].strip().strip('"')
        return None

    def _teile(self, antwort, marke: bytes):
        """Zerlegt den multipart-Strom in einzelne JPEG-Frames."""
        if not self._bis_marke(antwort, marke):
            return
        while not self._stop:
            laenge = None
            while True:
                kopf = antwort.readline()
                if not kopf:
                    return
                kopf = kopf.strip()
                if kopf == b"":
                    break
                if kopf.lower().startswith(b"content-length:"):
                    try:
                        laenge = int(kopf.split(b":", 1)[1].strip())
                    except ValueError:
                        raise MjpegFehler("Content-Length ist keine Zahl.") from None
            if laenge is None:
                raise MjpegFehler("MJPEG-Teil ohne Content-Length.")
            jpeg = self._genau_lesen(antwort, laenge)
            if jpeg is None:
                return
            yield jpeg
            if not self._bis_marke(antwort, marke):
                return

    @staticmethod
    def _bis_marke(antwort, marke: bytes) -> bool:
        """Liest Zeilen bis zur nächsten Grenzmarke. False bei Strom-Ende."""
        while True:
            zeile = antwort.readline()
            if not zeile:
                return False
            if zeile.strip() == marke:
                return True

    @staticmethod
    def _genau_lesen(antwort, anzahl: int) -> bytes | None:
        """Liest genau `anzahl` Bytes. None, wenn der Strom vorher endet."""
        stuecke = []
        rest = anzahl
        while rest > 0:
            brocken = antwort.read(rest)
            if not brocken:
                return None
            stuecke.append(brocken)
            rest -= len(brocken)
        return b"".join(stuecke)
