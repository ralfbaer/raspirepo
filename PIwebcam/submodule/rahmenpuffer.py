"""Ausgabe eines JPEG-Frames auf den Linux-Framebuffer (`/dev/fb0`).

Zweck: Ein Bild ohne grafische Oberfläche direkt auf das am Pi
angeschlossene Display bringen. Es läuft kein X und kein Wayland; der
Framebuffer ist der direkte Weg zum Panel.

Der Zugriff geht über zwei ioctls des fbdev-Treibers:

    FBIOGET_VSCREENINFO  Auflösung, Bits je Pixel, Lage der Farbbits
    FBIOGET_FSCREENINFO  Zeilenlänge (stride) und Größe des Speichers

Die Lage der Farbbits (`red`, `green`, `blue` mit Offset und Länge) wird
aus dem Treiber gelesen, nicht geraten. Damit stimmt die Umrechnung für
jedes Format, das der Treiber meldet: RGB565 (16 bpp, hier gemessen) und
XRGB8888 (32 bpp) gleichermaßen.

Gezeichnet wird in den sichtbaren Bereich (`xres` × `yres`). Es wird kein
zweiter Puffer benutzt und nicht auf den vertikalen Rücklauf gewartet;
bei schneller Bewegung ist deshalb ein Tearing-Streifen möglich. Für ein
Kamerabild ist das hinnehmbar und spart die Umschaltlogik.
"""

from __future__ import annotations

import ctypes
import fcntl
import logging
import mmap
import os
from io import BytesIO

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

# ioctl-Nummern des fbdev-Treibers (feste Werte aus <linux/fb.h>).
FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602


class RahmenpufferFehler(Exception):
    """Der Framebuffer ist nicht nutzbar oder meldet ein Format, das das
    Modul nicht beherrscht."""


class _Bitfeld(ctypes.Structure):
    """`struct fb_bitfield`: Lage einer Farbkomponente im Pixelwort."""

    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("length", ctypes.c_uint32),
        ("msb_right", ctypes.c_uint32),
    ]


class _VarInfo(ctypes.Structure):
    """`struct fb_var_screeninfo`: veränderliche Bildschirmdaten."""

    _fields_ = [
        ("xres", ctypes.c_uint32),
        ("yres", ctypes.c_uint32),
        ("xres_virtual", ctypes.c_uint32),
        ("yres_virtual", ctypes.c_uint32),
        ("xoffset", ctypes.c_uint32),
        ("yoffset", ctypes.c_uint32),
        ("bits_per_pixel", ctypes.c_uint32),
        ("grayscale", ctypes.c_uint32),
        ("red", _Bitfeld),
        ("green", _Bitfeld),
        ("blue", _Bitfeld),
        ("transp", _Bitfeld),
        ("nonstd", ctypes.c_uint32),
        ("activate", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("accel_flags", ctypes.c_uint32),
        ("pixclock", ctypes.c_uint32),
        ("left_margin", ctypes.c_uint32),
        ("right_margin", ctypes.c_uint32),
        ("upper_margin", ctypes.c_uint32),
        ("lower_margin", ctypes.c_uint32),
        ("hsync_len", ctypes.c_uint32),
        ("vsync_len", ctypes.c_uint32),
        ("sync", ctypes.c_uint32),
        ("vmode", ctypes.c_uint32),
        ("rotate", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]


class _FixInfo(ctypes.Structure):
    """`struct fb_fix_screeninfo`: feste Bildschirmdaten.

    `smem_start` und `mmio_start` sind `unsigned long`, auf dem
    64-Bit-Kernel (arm_64bit=1) also 8 Byte. ctypes richtet die Felder
    nach denselben Regeln aus wie der Kernel-Compiler; die Offsets müssen
    deshalb nicht von Hand gesetzt werden.
    """

    _fields_ = [
        ("id", ctypes.c_char * 16),
        ("smem_start", ctypes.c_ulong),
        ("smem_len", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("type_aux", ctypes.c_uint32),
        ("visual", ctypes.c_uint32),
        ("xpanstep", ctypes.c_uint16),
        ("ypanstep", ctypes.c_uint16),
        ("ywrapstep", ctypes.c_uint16),
        ("line_length", ctypes.c_uint32),
        ("mmio_start", ctypes.c_ulong),
        ("mmio_len", ctypes.c_uint32),
        ("accel", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16 * 2),
    ]


class Rahmenpuffer:
    """Hält den gemappten Framebuffer offen und zeichnet JPEG-Frames.

    Der Konstruktor öffnet das Gerät, liest die Geometrie und legt die
    Speicherabbildung an. `zeichnen_jpeg()` dekodiert ein JPEG, skaliert
    es und schreibt es in den sichtbaren Bereich. `schliessen()` löscht
    das Bild und gibt alles frei.
    """

    def __init__(self, geraet: str = "/dev/fb0") -> None:
        self._fd = os.open(geraet, os.O_RDWR)
        try:
            var = _VarInfo()
            fix = _FixInfo()
            fcntl.ioctl(self._fd, FBIOGET_VSCREENINFO, var)
            fcntl.ioctl(self._fd, FBIOGET_FSCREENINFO, fix)
        except OSError:
            os.close(self._fd)
            raise

        self.breite = int(var.xres)
        self.hoehe = int(var.yres)
        self.bpp = int(var.bits_per_pixel)
        self.stride = int(fix.line_length)

        if self.bpp not in (16, 32):
            os.close(self._fd)
            raise RahmenpufferFehler(
                f"{self.bpp} Bit je Pixel werden nicht unterstützt "
                f"(dieses Modul kann 16 und 32)."
            )
        for name, feld in (("rot", var.red), ("grün", var.green), ("blau", var.blue)):
            if not 1 <= feld.length <= 8:
                os.close(self._fd)
                raise RahmenpufferFehler(
                    f"Unerwartete Bitlage für {name}: Länge {feld.length}."
                )

        # Verschiebung je Farbe: erst die acht Eingangsbits auf die
        # Zielbreite kürzen (8 - length), dann an die richtige Stelle im
        # Pixelwort schieben (offset).
        self._rot = (8 - int(var.red.length), int(var.red.offset))
        self._gruen = (8 - int(var.green.length), int(var.green.offset))
        self._blau = (8 - int(var.blue.length), int(var.blue.offset))

        self._dtype = np.uint16 if self.bpp == 16 else np.uint32
        self._breite_bytes = self.breite * (self.bpp // 8)

        laenge = int(fix.smem_len) or self.stride * int(var.yres_virtual)
        self._sichtbar = self.stride * self.hoehe
        self._mm = mmap.mmap(
            self._fd, laenge, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE
        )

        self._cursor_setzen(sichtbar=False)
        log.info(
            "Framebuffer %s: %dx%d, %d bpp, stride %d",
            geraet, self.breite, self.hoehe, self.bpp, self.stride,
        )

    # -- Zeichnen ----------------------------------------------------------

    def zeichnen_jpeg(self, jpeg: bytes, skalierung: str = "einpassen") -> bool:
        """Dekodiert ein JPEG und zeigt es an. Gibt False bei defektem Bild."""
        try:
            bild = Image.open(BytesIO(jpeg)).convert("RGB")
        except Exception as fehler:  # noqa: BLE001 - defekter Frame soll nicht töten
            log.debug("Frame nicht dekodierbar, übersprungen: %s", fehler)
            return False

        feld = self._einpassen(bild, skalierung)
        self._schreiben(self._packen(feld))
        return True

    def _einpassen(self, bild: Image.Image, skalierung: str) -> np.ndarray:
        """Skaliert das Bild und legt es auf eine schwarze Bildschirmfläche.

        `einpassen` behält das Seitenverhältnis und lässt Ränder (Letterbox).
        `fuellen` füllt die Fläche ganz und schneidet den Überstand mittig ab.
        """
        iw, ih = bild.size
        if skalierung == "fuellen":
            faktor = max(self.breite / iw, self.hoehe / ih)
        else:
            faktor = min(self.breite / iw, self.hoehe / ih)
        nw = max(1, round(iw * faktor))
        nh = max(1, round(ih * faktor))
        skaliert = np.asarray(bild.resize((nw, nh)), dtype=np.uint8)

        flaeche = np.zeros((self.hoehe, self.breite, 3), dtype=np.uint8)
        # Ziel- und Quellbereich zuschneiden, damit sowohl ein kleineres
        # (zentriert mit Rand) als auch ein größeres Bild (mittig
        # beschnitten) passt.
        zx = (self.breite - nw) // 2
        zy = (self.hoehe - nh) // 2
        qx, qy = max(0, -zx), max(0, -zy)
        zx, zy = max(0, zx), max(0, zy)
        bw = min(nw - qx, self.breite - zx)
        bh = min(nh - qy, self.hoehe - zy)
        flaeche[zy:zy + bh, zx:zx + bw] = skaliert[qy:qy + bh, qx:qx + bw]
        return flaeche

    def _packen(self, flaeche: np.ndarray) -> np.ndarray:
        """Wandelt ein (H, B, 3)-RGB-Feld in Pixelworte des Framebuffers."""
        r = flaeche[..., 0].astype(np.uint32)
        g = flaeche[..., 1].astype(np.uint32)
        b = flaeche[..., 2].astype(np.uint32)
        wert = (r >> self._rot[0]) << self._rot[1]
        wert |= (g >> self._gruen[0]) << self._gruen[1]
        wert |= (b >> self._blau[0]) << self._blau[1]
        return wert.astype(self._dtype)

    def _schreiben(self, wert: np.ndarray) -> None:
        """Schreibt die Pixelworte zeilenweise in den sichtbaren Bereich."""
        pixel = wert.view(np.uint8).reshape(self.hoehe, self._breite_bytes)
        if self.stride == self._breite_bytes:
            self._mm[0:self._sichtbar] = pixel.tobytes()
        else:
            # Panel mit Zeilenauffüllung: jede Zeile an ihren stride-Versatz.
            rahmen = np.zeros((self.hoehe, self.stride), dtype=np.uint8)
            rahmen[:, :self._breite_bytes] = pixel
            self._mm[0:self._sichtbar] = rahmen.tobytes()

    def leeren(self) -> None:
        """Setzt den sichtbaren Bereich auf Schwarz."""
        self._mm[0:self._sichtbar] = b"\x00" * self._sichtbar

    # -- Konsole -----------------------------------------------------------

    def _cursor_setzen(self, sichtbar: bool) -> None:
        """Blendet den blinkenden Textcursor aus bzw. wieder ein.

        Nur mit bestem Bemühen: Das Schreiben auf die Konsole gelingt dem
        Benutzer nicht immer (Gerät gehört Gruppe `tty`). Scheitert es,
        ist das unkritisch — der Vollbild-Frame überdeckt den Cursor
        ohnehin bei jedem Bild. Deshalb nur ein Debug-Hinweis, kein
        Fehler.
        """
        code = b"\033[?25h" if sichtbar else b"\033[?25l"
        try:
            with open("/dev/tty1", "wb") as konsole:
                konsole.write(code)
        except OSError as fehler:
            log.debug("Cursor nicht umschaltbar (%s), Frame überdeckt ihn.", fehler)

    def schliessen(self) -> None:
        """Löscht das Bild, holt den Cursor zurück und gibt alles frei."""
        try:
            self.leeren()
        except Exception as fehler:  # noqa: BLE001 - Aufräumen soll nie werfen
            log.debug("Framebuffer-Löschen fehlgeschlagen: %s", fehler)
        self._cursor_setzen(sichtbar=True)
        try:
            self._mm.close()
        finally:
            os.close(self._fd)
