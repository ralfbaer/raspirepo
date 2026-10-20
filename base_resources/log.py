"""
Zentrale Logging-Klasse für alle Projekte.

Stellt eine einheitliche Log-Konfiguration bereit, die aus jedem Projekt
heraus genutzt werden kann. Logfiles werden automatisch im konfigurierten
Verzeichnis unter einem Unterordner mit dem aktuellen Datum abgelegt.
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _aktueller_tages_logfile_pfad(log_verzeichnis: str, logfile_name: str, datum: str) -> str:
    """
    Ermittelt den Logfile-Pfad im Tages-Ordner des angegebenen Datums und
    legt den Ordner bei Bedarf an.
    """
    tages_ordner = os.path.join(log_verzeichnis, datum)
    os.makedirs(tages_ordner, exist_ok=True)
    return os.path.join(tages_ordner, logfile_name)


def _tageswechsel_pruefen(handler: logging.FileHandler) -> None:
    """
    Schaltet einen Datei-Handler bei einem Datumswechsel auf den Tages-Ordner
    des neuen Tages um.

    Beim Datumswechsel wird ein neuer Tages-Ordner (YYYY-MM-DD) angelegt und
    der Ausgabestream auf die Logdatei im neuen Ordner umgeschaltet. Dadurch
    schreiben dauerhaft laufende Programme nach Mitternacht automatisch in den
    Ordner des neuen Tages, statt weiter in den Ordner des Vortags.

    Der Handler muss die Attribute _log_verzeichnis, _logfile_name und
    _aktuelles_datum tragen.
    """
    heute = datetime.now().strftime("%Y-%m-%d")
    if heute == handler._aktuelles_datum:  # type: ignore[attr-defined]
        return

    handler._aktuelles_datum = heute  # type: ignore[attr-defined]
    # baseFilename auf die Logdatei im neuen Tages-Ordner setzen
    handler.baseFilename = os.path.abspath(
        _aktueller_tages_logfile_pfad(
            handler._log_verzeichnis,  # type: ignore[attr-defined]
            handler._logfile_name,  # type: ignore[attr-defined]
            heute,
        )
    )

    # Alten Stream schließen; neuen bei Bedarf öffnen
    if handler.stream is not None:
        handler.stream.close()
        handler.stream = None  # type: ignore[assignment]
    if not handler.delay:
        handler.stream = handler._open()


class _TagesFileHandler(logging.FileHandler):
    """FileHandler mit automatischem Tages-Rollover (siehe _tageswechsel_pruefen)."""

    def __init__(self, log_verzeichnis: str, logfile_name: str, encoding=None):
        self._log_verzeichnis = log_verzeichnis
        self._logfile_name = logfile_name
        self._aktuelles_datum = datetime.now().strftime("%Y-%m-%d")
        pfad = _aktueller_tages_logfile_pfad(
            log_verzeichnis, logfile_name, self._aktuelles_datum
        )
        super().__init__(pfad, encoding=encoding)

    def emit(self, record: logging.LogRecord) -> None:
        """Prüft vor jeder Ausgabe auf Tageswechsel und schreibt dann."""
        _tageswechsel_pruefen(self)
        super().emit(record)


class _TagesRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler mit zusätzlichem Tages-Rollover."""

    def __init__(
        self,
        log_verzeichnis: str,
        logfile_name: str,
        max_bytes: int,
        backup_count: int,
        encoding=None,
    ):
        self._log_verzeichnis = log_verzeichnis
        self._logfile_name = logfile_name
        self._aktuelles_datum = datetime.now().strftime("%Y-%m-%d")
        pfad = _aktueller_tages_logfile_pfad(
            log_verzeichnis, logfile_name, self._aktuelles_datum
        )
        super().__init__(
            pfad,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Prüft vor jeder Ausgabe auf Tageswechsel und schreibt dann."""
        _tageswechsel_pruefen(self)
        super().emit(record)


class Log:
    """
    Basis-Logging-Klasse.

    Erzeugt beim Instanziieren ein Logfile im angegebenen Verzeichnis.
    Der Logfile-Name entspricht standardmäßig dem Namen des aufrufenden
    Programms mit der Endung .log.

    Parameter:
        log_verzeichnis (str): Pfad zum Ausgabeverzeichnis für Logfiles.
        log_level (int): Loglevel (z.B. logging.DEBUG, logging.INFO).
                         Standard: logging.INFO
        logfile_name (str | None): Optionaler Name für das Logfile.
                                   Standard: <Programmname>.log
        silent (bool): Wenn True, wird keine Konsolenausgabe erzeugt.
                       Standard: False
        max_mb (float | None): Maximale Größe des Logfiles in MB für
                               Log-Rotation. None = keine Rotation.
                               Standard: None
        logger_name (str | None): Optionaler Name für den zugrunde liegenden
                               Python-Logger. Standard: <Programmname> aus
                               sys.argv[0]. Wird benötigt, wenn ein Programm
                               mehrere unabhängige Log-Instanzen (z.B. eine
                               zweite Logdatei) parallel betreiben will —
                               ohne eigenen Namen würden sich beide Instanzen
                               denselben Logger teilen und ihre Handler
                               gegenseitig überschreiben.
    """

    # Einheitliches Log-Format: Zeitstempel - Level - Logger-Name - Nachricht
    LOG_FORMAT = "%(asctime)s - %(levelname)-8s - %(name)s - %(message)s"
    DATUM_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(
        self,
        log_verzeichnis: str,
        log_level: int = logging.INFO,
        logfile_name: str | None = None,
        silent: bool = False,
        max_mb: float | None = None,
        logger_name: str | None = None,
    ):
        self._log_level = log_level
        self._silent = silent
        self._max_mb = max_mb

        # Programmname aus sys.argv[0] ermitteln
        programmname = os.path.basename(sys.argv[0])
        # Dateiendung entfernen, falls vorhanden
        programmname_ohne_endung = os.path.splitext(programmname)[0]

        # Logfile-Name bestimmen
        if logfile_name is not None:
            self._logfile_name = logfile_name
        else:
            self._logfile_name = f"{programmname_ohne_endung}.log"

        # Basis-Log-Verzeichnis merken (der Tages-Ordner wird dynamisch vom
        # Datei-Handler verwaltet, damit Dauerläufer nach Mitternacht
        # automatisch in den Ordner des neuen Tages schreiben)
        self._log_verzeichnis = log_verzeichnis

        # Logger erstellen. Standardmäßig aus dem Programmnamen abgeleitet;
        # über logger_name kann ein eigener Name gesetzt werden, damit mehrere
        # Log-Instanzen (z.B. eine zweite Logdatei) sich nicht denselben
        # Python-Logger teilen und ihre Handler gegenseitig löschen.
        self._logger = logging.getLogger(logger_name or programmname_ohne_endung)
        self._logger.setLevel(self._log_level)

        # Vorhandene Handler entfernen, um Duplikate zu vermeiden
        self._logger.handlers.clear()

        # Formatter erstellen
        formatter = logging.Formatter(self.LOG_FORMAT, datefmt=self.DATUM_FORMAT)

        # Datei-Handler konfigurieren (verwaltet den Tages-Ordner dynamisch)
        self._datei_handler = self._erstelle_datei_handler(formatter)
        self._logger.addHandler(self._datei_handler)

        # Konsolen-Handler nur wenn nicht silent
        if not self._silent:
            konsolen_handler = logging.StreamHandler(sys.stdout)
            konsolen_handler.setLevel(self._log_level)
            konsolen_handler.setFormatter(formatter)
            self._logger.addHandler(konsolen_handler)

    def _erstelle_datei_handler(
        self, formatter: logging.Formatter
    ) -> logging.FileHandler:
        """
        Erstellt den passenden Datei-Handler.

        Bei aktivierter Log-Rotation (max_mb ist gesetzt) wird ein
        RotatingFileHandler verwendet, ansonsten ein normaler FileHandler.
        Beide Varianten schalten bei einem Datumswechsel automatisch auf den
        Tages-Ordner des neuen Tages um (Tages-Rollover).

        Parameter:
            formatter (logging.Formatter): Das zu verwendende Log-Format.

        Rückgabe:
            logging.FileHandler: Der konfigurierte Datei-Handler.
        """
        if self._max_mb is not None and self._max_mb > 0:
            # Rotation aktiviert: Größe in Bytes umrechnen
            max_bytes = int(self._max_mb * 1024 * 1024)
            handler = _TagesRotatingFileHandler(
                self._log_verzeichnis,
                self._logfile_name,
                max_bytes=max_bytes,
                backup_count=5,
                encoding="utf-8",
            )
        else:
            # Keine Rotation
            handler = _TagesFileHandler(
                self._log_verzeichnis,
                self._logfile_name,
                encoding="utf-8",
            )

        handler.setLevel(self._log_level)
        handler.setFormatter(formatter)
        return handler

    # --- Öffentliche Log-Methoden ---

    def debug(self, nachricht: str, *args, **kwargs) -> None:
        """Schreibt eine DEBUG-Nachricht."""
        self._logger.debug(nachricht, *args, **kwargs)

    def info(self, nachricht: str, *args, **kwargs) -> None:
        """Schreibt eine INFO-Nachricht."""
        self._logger.info(nachricht, *args, **kwargs)

    def warning(self, nachricht: str, *args, **kwargs) -> None:
        """Schreibt eine WARNING-Nachricht."""
        self._logger.warning(nachricht, *args, **kwargs)

    def error(self, nachricht: str, *args, **kwargs) -> None:
        """Schreibt eine ERROR-Nachricht."""
        self._logger.error(nachricht, *args, **kwargs)

    def critical(self, nachricht: str, *args, **kwargs) -> None:
        """Schreibt eine CRITICAL-Nachricht."""
        self._logger.critical(nachricht, *args, **kwargs)

    # --- Properties ---

    @property
    def logfile_pfad(self) -> str:
        """
        Gibt den vollständigen Pfad zur aktuellen Logdatei zurück.

        Der Pfad wird dynamisch aus dem aktuellen Tages-Ordner des
        Datei-Handlers ermittelt und wechselt daher nach Mitternacht
        automatisch mit.
        """
        return self._datei_handler.baseFilename

    @property
    def log_pfad(self) -> str:
        """
        Gibt den Pfad zum aktuellen Tages-Log-Verzeichnis zurück.

        Wechselt nach Mitternacht automatisch auf den Ordner des neuen Tages.
        """
        return os.path.dirname(self._datei_handler.baseFilename)

    @property
    def log_basis_verzeichnis(self) -> str:
        """
        Gibt das konfigurierte Basis-Log-Verzeichnis zurück (ohne Tages-Ordner).

        Nützlich, um eine zweite Log-Instanz mit anderem Dateinamen im selben
        Verzeichnis anzulegen (gleicher Tages-Rollover, gleicher Log-Agent).
        """
        return self._log_verzeichnis

    @property
    def logger(self) -> logging.Logger:
        """Gibt den zugrunde liegenden Python-Logger zurück."""
        return self._logger
