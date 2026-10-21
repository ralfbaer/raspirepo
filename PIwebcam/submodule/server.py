"""HTTP-Server, der die Kamerabilder als MJPEG an den Browser liefert.

Gewählt ist `multipart/x-mixed-replace` mit JPEG-Einzelbildern. Grund:
Das zeigt jeder Browser in einem schlichten `<img>`-Tag an, ohne
JavaScript, ohne WebRTC-Stack und ohne Videocontainer. Die Kameras
dieses Aufbaus können weder MJPEG noch H.264 selbst, es wird also
ohnehin auf dem Host kodiert; damit fällt der Vorteil eines Videocodecs
weg, während sein Aufwand (ffmpeg oder GStreamer, beide nicht
installiert) bliebe.

Preis dieser Wahl: MJPEG komprimiert schlechter als H.264, der Stream
braucht mehr Bandbreite. Im Heimnetz ist das unkritisch.

Adressen:
    GET  /                              Übersicht aller Kameras
    GET  /anmelden                      Anmeldeformular
    POST /anmelden                      Anmeldung abschicken
    GET  /abmelden                      Sitzung beenden
    GET  /stil.css                      Gestaltung
    GET  /status.json                   Betriebszustand aller Kameras
    GET  /kamera/<kennung>              Einzelansicht
    GET  /kamera/<kennung>/stream.mjpg  fortlaufender MJPEG-Stream
    GET  /kamera/<kennung>/snapshot.jpg aktuelles Einzelbild
    GET  /stream.mjpg                   erste Kamera (alte Adresse)
    GET  /snapshot.jpg                  erste Kamera (alte Adresse)

Anmeldung: Ist ein Passwort gesetzt, läuft der Zugang über ein
Anmeldeformular und eine Sitzung per Cookie, nicht über HTTP-Basic. So
funktioniert er auch in Browsern, in denen Basic-Auth administrativ
abgeschaltet ist. Ein gültiger Basic-Header wird zusätzlich akzeptiert,
damit Werkzeuge wie curl unverändert arbeiten. Über HTTP ohne TLS gehen
Passwort und Cookie im Klartext durchs Netz; echten Schutz gibt erst
TLS (--zertifikat) oder ein SSH-Tunnel.

Die Dateien der Oberfläche liegen im Unterverzeichnis `resources/`. Die
Seiten werden beim Start einmal gebaut und danach aus dem Speicher
ausgeliefert. Die Kameraliste ändert sich zur Laufzeit nicht, und das
Projektverzeichnis liegt auf NFS: Jeder Dateizugriff geht über das Netz.
"""

from __future__ import annotations

import html
import json
import logging
import secrets
import socket
import ssl
import threading
import time
import urllib.parse
from base64 import b64decode
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from submodule.einstellungen import STANDARD_SITZUNGSDAUER
from submodule.kamera import Kameraquelle, Kameraregister  # noqa: F401 - Typ

log = logging.getLogger(__name__)

GRENZE = "webcamframe"

# Name des Sitzungs-Cookies, das die Anmeldung trägt.
SITZUNGSKEKS = "webcam_sitzung"


class Sitzungsverwaltung:
    """Hält die gültigen Anmelde-Sitzungen im Speicher.

    Eine Sitzung ist ein zufälliges Token, das als Cookie im Browser
    liegt. Zu jedem Token wird der Ablaufzeitpunkt gespeichert. Die
    Ablage ist absichtlich flüchtig: Nach einem Neustart des Dienstes
    müssen sich alle neu anmelden. Das genügt für einen Heimdienst und
    spart jede Persistenz.

    Der Server bedient mehrere Anfragen gleichzeitig in Threads, deshalb
    schützt eine Sperre den gemeinsamen Zustand.
    """

    def __init__(self, dauer: float = STANDARD_SITZUNGSDAUER) -> None:
        self._dauer = dauer
        self._ablauf: dict[str, float] = {}
        self._sperre = threading.Lock()

    def neu(self) -> str:
        """Legt eine neue Sitzung an und gibt ihr Token zurück."""
        token = secrets.token_urlsafe(32)
        with self._sperre:
            self._ablauf[token] = time.monotonic() + self._dauer
        return token

    def gueltig(self, token: str | None) -> bool:
        """Prüft, ob das Token eine lebende Sitzung bezeichnet."""
        if not token:
            return False
        jetzt = time.monotonic()
        with self._sperre:
            ablauf = self._ablauf.get(token)
            if ablauf is None:
                return False
            if ablauf < jetzt:
                # Abgelaufen: gleich wegräumen.
                del self._ablauf[token]
                return False
            return True

    def entfernen(self, token: str | None) -> None:
        """Beendet eine Sitzung (Abmelden)."""
        if not token:
            return
        with self._sperre:
            self._ablauf.pop(token, None)


class Zugangsdaten:
    """Anmeldedaten. `None` als Passwort heißt: kein Schutz.

    Die Prüfung gibt es in zwei Formen: `pruefen` für einen
    HTTP-Basic-Kopf (Werkzeuge) und `pruefen_klartext` für die Felder
    aus dem Anmeldeformular.
    """

    def __init__(self, benutzer: str | None, passwort: str | None) -> None:
        self.benutzer = benutzer
        self.passwort = passwort

    @property
    def aktiv(self) -> bool:
        return bool(self.passwort)

    def pruefen_klartext(self, benutzer: str, passwort: str) -> bool:
        """Vergleicht Benutzer und Passwort im Klartext."""
        if not self.aktiv:
            return True
        # compare_digest statt == , damit die Laufzeit nichts verrät.
        benutzer_ok = secrets.compare_digest(benutzer, self.benutzer or "")
        passwort_ok = secrets.compare_digest(passwort, self.passwort or "")
        return benutzer_ok and passwort_ok

    def pruefen(self, kopfzeile: str | None) -> bool:
        """Prüft einen HTTP-Basic-Kopf (für curl und andere Werkzeuge)."""
        if not self.aktiv:
            return True
        if not kopfzeile or not kopfzeile.startswith("Basic "):
            return False
        try:
            entschluesselt = b64decode(kopfzeile[6:], validate=True).decode("utf-8")
            benutzer, _, passwort = entschluesselt.partition(":")
        except Exception:  # noqa: BLE001 - defekter Kopf gilt als falsch
            return False
        return self.pruefen_klartext(benutzer, passwort)


class WebcamHandler(BaseHTTPRequestHandler):
    """Bedient die Adressen. Pro Anfrage ein Thread."""

    server_version = "webcam/2.0"
    protocol_version = "HTTP/1.1"

    # Werden von `server_bauen` auf der Klasse gesetzt.
    register: Kameraregister
    zugang: Zugangsdaten
    sitzungen: Sitzungsverwaltung
    seiten: dict[str, bytes]
    # Unveränderliche Beigaben: Dateiname -> (Inhalt, Inhaltstyp)
    beiwerk: dict[str, tuple[bytes, str]]
    # True, wenn der Server über TLS läuft. Steuert das Secure-Flag am Cookie.
    tls: bool = False

    # -- Grundgerüst --------------------------------------------------------

    def log_message(self, format: str, *args) -> None:
        log.info("%s %s", self.address_string(), format % args)

    def _pfadteile(self) -> list[str]:
        """Zerlegt den Pfad der Anfrage in seine nicht leeren Teile."""
        pfad = self.path.split("?", 1)[0]
        return [teil for teil in pfad.split("/") if teil]

    def do_GET(self) -> None:
        self._bedienen(mit_koerper=True)

    def do_HEAD(self) -> None:
        self._bedienen(mit_koerper=False)

    def do_POST(self) -> None:
        teile = self._pfadteile()
        if teile == ["anmelden"]:
            self._anmeldung_verarbeiten()
            return
        self._fehler(HTTPStatus.NOT_FOUND, "Unbekannte Adresse.")

    def _bedienen(self, mit_koerper: bool) -> None:
        """Prüft den Zugang und leitet dann an die Behandlung weiter."""
        teile = self._pfadteile()
        if self.zugang.aktiv and not self._oeffentlich(teile) and not self._angemeldet():
            self._abweisen(teile)
            return
        self._verteilen(teile, mit_koerper)

    # -- Zugang -------------------------------------------------------------

    def _oeffentlich(self, teile: list[str]) -> bool:
        """Adressen, die ohne Anmeldung erreichbar bleiben müssen."""
        if teile in (["anmelden"], ["abmelden"]):
            return True
        # CSS und JS, damit das Anmeldeformular gestaltet ist. Sie
        # enthalten keine Kameradaten.
        return len(teile) == 1 and teile[0] in self.beiwerk

    def _sitzungstoken(self) -> str | None:
        """Liest das Sitzungs-Token aus dem Cookie-Kopf."""
        roh = self.headers.get("Cookie")
        if not roh:
            return None
        keks = SimpleCookie()
        try:
            keks.load(roh)
        except CookieError:
            return None
        eintrag = keks.get(SITZUNGSKEKS)
        return eintrag.value if eintrag else None

    def _angemeldet(self) -> bool:
        """True, wenn die Anfrage eine gültige Sitzung oder Basic-Daten trägt."""
        if self.sitzungen.gueltig(self._sitzungstoken()):
            return True
        # Basic-Kopf als Rückfall für Werkzeuge wie curl.
        return self.zugang.pruefen(self.headers.get("Authorization"))

    def _abweisen(self, teile: list[str]) -> None:
        """Antwortet auf eine nicht angemeldete Anfrage.

        Seitenaufrufe werden auf das Anmeldeformular umgeleitet.
        Unterressourcen (Streams, Snapshots, Status) bekommen 401 ohne
        Umleitung, damit kein HTML in einem <img> oder fetch landet.
        """
        if self.headers.get("Authorization"):
            # Fehlgeschlagener Basic-Versuch: Durchprobieren bremsen.
            time.sleep(self.register.zeiten.fehlanmeldung)
        ist_seite = (not teile) or (teile[0] == "kamera" and len(teile) == 2)
        if ist_seite:
            self._umleiten("/anmelden")
        else:
            self._fehler(HTTPStatus.UNAUTHORIZED, "Anmeldung erforderlich.")

    def _anmeldung_verarbeiten(self) -> None:
        """Nimmt das abgeschickte Anmeldeformular entgegen."""
        try:
            laenge = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            laenge = 0
        # Missbrauch abwehren: ein Anmeldeformular ist winzig.
        if laenge < 0 or laenge > 4096:
            self._fehler(HTTPStatus.BAD_REQUEST, "Ungültige Anmeldung.")
            return
        roh = self.rfile.read(laenge) if laenge else b""
        felder = urllib.parse.parse_qs(roh.decode("utf-8", "replace"))
        benutzer = (felder.get("benutzer") or [""])[0]
        passwort = (felder.get("passwort") or [""])[0]

        if self.zugang.pruefen_klartext(benutzer, passwort):
            token = self.sitzungen.neu()
            self._umleiten("/", keks=self._keks_wert(token))
            return

        # Fehlschlag: Durchprobieren bremsen und das Formular mit
        # Hinweis erneut zeigen.
        time.sleep(self.register.zeiten.fehlanmeldung)
        self._html_antwort(
            self.seiten["anmelden_fehler"],
            HTTPStatus.UNAUTHORIZED,
            mit_koerper=True,
        )

    def _abmelden(self) -> None:
        """Beendet die Sitzung und löscht das Cookie."""
        self.sitzungen.entfernen(self._sitzungstoken())
        self._umleiten("/anmelden", keks=self._keks_wert("", loeschen=True))

    def _keks_wert(self, token: str, loeschen: bool = False) -> str:
        """Baut den Set-Cookie-Wert für die Sitzung."""
        teile = [
            f"{SITZUNGSKEKS}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
        ]
        if loeschen:
            teile.append("Max-Age=0")
        if self.tls:
            teile.append("Secure")
        return "; ".join(teile)

    def _verteilen(self, teile: list[str], mit_koerper: bool) -> None:
        """Ordnet die Adresse einer Behandlung zu."""
        # Übersicht
        if not teile:
            self._seite_senden("uebersicht", mit_koerper)
            return

        if len(teile) == 1:
            if teile[0] == "anmelden":
                self._seite_senden("anmelden", mit_koerper)
                return
            if teile[0] == "abmelden":
                self._abmelden()
                return
            if teile[0] in self.beiwerk:
                daten, typ = self.beiwerk[teile[0]]
                self._antwort(daten, typ, mit_koerper, zwischenspeichern=True)
                return
            if teile[0] == "status.json":
                self._status_senden(mit_koerper)
                return
            # Alte Adressen ohne Kameraangabe: erste Kamera.
            if teile[0] == "stream.mjpg":
                self._stream_senden(self.register.erste)
                return
            if teile[0] == "snapshot.jpg":
                self._snapshot_senden(self.register.erste, mit_koerper)
                return

        # /kamera/<kennung>[/...]
        if teile[0] == "kamera" and len(teile) in (2, 3):
            quelle = self.register.holen(teile[1])
            if quelle is None:
                self._fehler(
                    HTTPStatus.NOT_FOUND,
                    f"Unbekannte Kamera '{teile[1]}'. Vorhanden: "
                    + ", ".join(self.register.quellen),
                )
                return
            if len(teile) == 2:
                self._seite_senden(f"kamera:{teile[1]}", mit_koerper)
                return
            if teile[2] == "stream.mjpg":
                self._stream_senden(quelle)
                return
            if teile[2] == "snapshot.jpg":
                self._snapshot_senden(quelle, mit_koerper)
                return

        self._fehler(HTTPStatus.NOT_FOUND, "Unbekannte Adresse.")

    # -- Antworten ----------------------------------------------------------

    def _umleiten(self, ziel: str, keks: str | None = None) -> None:
        """Schickt eine 303-Umleitung, optional mit Set-Cookie."""
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", ziel)
        if keks is not None:
            self.send_header("Set-Cookie", keks)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _html_antwort(
        self, daten: bytes, status: HTTPStatus, mit_koerper: bool = True
    ) -> None:
        """Sendet eine HTML-Seite mit frei wählbarem Statuscode."""
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        if mit_koerper:
            self._koerper_senden(daten, "text/html; charset=utf-8")
        else:
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()

    def _fehler(self, status: HTTPStatus, text: str) -> None:
        self.send_response(status)
        self._koerper_senden(f"{text}\n".encode(), "text/plain; charset=utf-8")

    def _koerper_senden(self, daten: bytes, inhaltstyp: str) -> None:
        self.send_header("Content-Type", inhaltstyp)
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)

    def _antwort(
        self,
        daten: bytes,
        inhaltstyp: str,
        mit_koerper: bool = True,
        zwischenspeichern: bool = False,
    ) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Cache-Control", "max-age=3600" if zwischenspeichern else "no-store"
        )
        if mit_koerper:
            self._koerper_senden(daten, inhaltstyp)
        else:
            self.send_header("Content-Type", inhaltstyp)
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()

    def _seite_senden(self, schluessel: str, mit_koerper: bool) -> None:
        seite = self.seiten.get(schluessel)
        if seite is None:
            self._fehler(HTTPStatus.NOT_FOUND, "Seite nicht vorhanden.")
            return
        self._antwort(seite, "text/html; charset=utf-8", mit_koerper)

    def _status_senden(self, mit_koerper: bool) -> None:
        zustand = self.register.zustand()
        zustand["authentifizierung"] = "Passwort" if self.zugang.aktiv else "keine"
        daten = json.dumps(zustand, ensure_ascii=False, indent=2).encode("utf-8")
        self._antwort(daten, "application/json; charset=utf-8", mit_koerper)

    def _snapshot_senden(self, quelle: Kameraquelle, mit_koerper: bool) -> None:
        jpeg = quelle.einzelbild()
        if jpeg is None:
            self._fehler(
                HTTPStatus.SERVICE_UNAVAILABLE,
                f"Kein Bild von {quelle.einstellung.anzeigename}. "
                f"{quelle.letzter_fehler or ''}".strip(),
            )
            return
        self._antwort(jpeg, "image/jpeg", mit_koerper)

    def _stream_senden(self, quelle: Kameraquelle) -> None:
        if not self.register.streamplatz_belegen():
            self._fehler(
                HTTPStatus.SERVICE_UNAVAILABLE,
                f"Zu viele gleichzeitige Streams (Grenze "
                f"{self.register.max_streams} über alle Kameras).",
            )
            return

        quelle.anmelden()
        try:
            # Auf den ersten Frame warten, damit ein Kamerafehler noch als
            # HTTP-Status gemeldet werden kann und nicht mitten im Stream.
            erstes = quelle.auf_frame_warten(0, zeitlimit=quelle.zeiten.erstes_bild)
            if erstes is None:
                self._fehler(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    f"{quelle.einstellung.anzeigename} liefert kein Bild. "
                    f"{quelle.letzter_fehler or ''}".strip(),
                )
                return

            # Ein MJPEG-Stream hat keine bekannte Länge und wird nicht
            # chunked kodiert. Unter HTTP/1.1 muss die Verbindung deshalb
            # als nicht wiederverwendbar gekennzeichnet werden.
            self.close_connection = True
            self.send_response(HTTPStatus.OK)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.send_header(
                "Content-Type", f"multipart/x-mixed-replace; boundary={GRENZE}"
            )
            self.end_headers()

            jpeg, nummer = erstes
            while True:
                self._frame_teil_senden(jpeg)
                naechstes = quelle.auf_frame_warten(
                    nummer, zeitlimit=quelle.zeiten.stream_stille
                )
                if naechstes is None:
                    log.info(
                        "Stream %s beendet: kein neuer Frame innerhalb %.0f s",
                        quelle.einstellung.kennung,
                        quelle.zeiten.stream_stille,
                    )
                    return
                jpeg, nummer = naechstes
        except (BrokenPipeError, ConnectionResetError):
            # Normalfall: Der Browser hat den Tab geschlossen.
            log.info("Stream %s vom Client beendet", quelle.einstellung.kennung)
        finally:
            quelle.abmelden()
            self.register.streamplatz_freigeben()

    def _frame_teil_senden(self, jpeg: bytes) -> None:
        kopf = (
            f"--{GRENZE}\r\n"
            f"Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(jpeg)}\r\n\r\n"
        ).encode("ascii")
        self.wfile.write(kopf)
        self.wfile.write(jpeg)
        self.wfile.write(b"\r\n")


class WebcamServer(ThreadingHTTPServer):
    """Threading-Server, der auch auf IPv6-Adressen lauschen kann."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, adresse: tuple[str, int], handler, ipv6: bool = False) -> None:
        if ipv6:
            self.address_family = socket.AF_INET6
        super().__init__(adresse, handler)

    def handle_error(self, request, client_address) -> None:
        """Abgebrochene Verbindungen nicht als Traceback ausgeben."""
        import sys

        fehler = sys.exc_info()[1]
        if isinstance(fehler, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            log.info("Verbindung zu %s abgebrochen", client_address[0])
            return
        log.exception("Fehler bei Anfrage von %s", client_address[0])


# ---------------------------------------------------------------------------
# Seiten bauen
# ---------------------------------------------------------------------------


def seiten_bauen(verzeichnis: Path, titel: str, register: Kameraregister) -> dict[str, bytes]:
    """Baut Übersicht und je eine Einzelansicht pro Kamera.

    Alle eingesetzten Texte werden mit `html.escape` behandelt. Das ist
    nicht nur Formsache: Der Kameraname kann aus dem USB-Deskriptor des
    Geräts stammen (Feld `card`), also aus einer Quelle, die das Projekt
    nicht kontrolliert.
    """
    vorlage_uebersicht = (verzeichnis / "seite_uebersicht.html").read_text(
        encoding="utf-8"
    )
    vorlage_einzel = (verzeichnis / "seite_einzel.html").read_text(encoding="utf-8")
    vorlage_anmelden = (verzeichnis / "seite_anmelden.html").read_text(
        encoding="utf-8"
    )

    kameras = register.uebersicht()
    mehrzahl = len(kameras) > 1

    kacheln = []
    for kamera in kameras:
        kennung = html.escape(kamera["kennung"])
        name = html.escape(kamera["name"])
        aufloesung = html.escape(kamera["auflösung"])
        geraet = html.escape(kamera["geraet"])
        kacheln.append(
            f"""      <article class="kachel">
        <h2><a href="/kamera/{kennung}">{name}</a></h2>
        <a class="bildrahmen" href="/kamera/{kennung}">
          <img src="/kamera/{kennung}/stream.mjpg" alt="Live-Bild von {name}"
               data-kennung="{kennung}">
        </a>
        <p class="meta">{aufloesung} &middot; {geraet}</p>
      </article>"""
        )

    seiten: dict[str, bytes] = {}
    seiten["uebersicht"] = (
        vorlage_uebersicht.replace("{{TITEL}}", html.escape(titel))
        .replace("{{KACHELN}}", "\n".join(kacheln))
        .replace("{{ANZAHL}}", str(len(kameras)))
        .replace(
            "{{UNTERTITEL}}",
            f"{len(kameras)} Kameras" if mehrzahl else "1 Kamera",
        )
        .encode("utf-8")
    )

    for kamera in kameras:
        kennung = kamera["kennung"]
        seiten[f"kamera:{kennung}"] = (
            vorlage_einzel.replace("{{TITEL}}", html.escape(titel))
            .replace("{{KENNUNG}}", html.escape(kennung))
            .replace("{{NAME}}", html.escape(kamera["name"]))
            .replace("{{AUFLOESUNG}}", html.escape(kamera["auflösung"]))
            .replace("{{GERAET}}", html.escape(kamera["geraet"]))
            .encode("utf-8")
        )

    # Anmeldeseite in zwei Festfassungen: ohne Hinweis und mit
    # Fehlermeldung. Beide werden hier einmal gebaut, damit zur Laufzeit
    # kein Dateizugriff und kein Zusammensetzen nötig ist.
    def anmeldeseite(meldung_html: str) -> bytes:
        return (
            vorlage_anmelden.replace("{{TITEL}}", html.escape(titel))
            .replace("{{MELDUNG}}", meldung_html)
            .encode("utf-8")
        )

    seiten["anmelden"] = anmeldeseite("")
    seiten["anmelden_fehler"] = anmeldeseite(
        '<p class="fehler" role="alert">Benutzer oder Passwort stimmt nicht.</p>'
    )

    return seiten


def server_bauen(
    register: Kameraregister,
    host: str,
    port: int,
    zugang: Zugangsdaten,
    titel: str,
    zertifikat: Path | None = None,
    schluessel: Path | None = None,
) -> WebcamServer:
    """Stellt den HTTP- bzw. HTTPS-Server bereit, ohne ihn zu starten."""
    # server.py liegt in submodule/, die Oberfläche eine Ebene höher in
    # <projekt>/resources/.
    verzeichnis = Path(__file__).resolve().parent.parent / "resources"
    WebcamHandler.register = register
    WebcamHandler.zugang = zugang
    WebcamHandler.sitzungen = Sitzungsverwaltung()
    WebcamHandler.tls = zertifikat is not None
    WebcamHandler.seiten = seiten_bauen(verzeichnis, titel, register)
    WebcamHandler.beiwerk = {
        "stil.css": (
            (verzeichnis / "stil.css").read_bytes(),
            "text/css; charset=utf-8",
        ),
        "webcam.js": (
            (verzeichnis / "webcam.js").read_bytes(),
            "text/javascript; charset=utf-8",
        ),
    }

    ipv6 = ":" in host
    server = WebcamServer((host, port), WebcamHandler, ipv6=ipv6)

    if zertifikat is not None:
        kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        kontext.load_cert_chain(
            certfile=str(zertifikat), keyfile=str(schluessel or zertifikat)
        )
        server.socket = kontext.wrap_socket(server.socket, server_side=True)
        log.info("TLS aktiv, Zertifikat %s", zertifikat)

    return server
