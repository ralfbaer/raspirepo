"""
Zentrales Konfigurationsmodul für YAML-basierte Projektkonfigurationen.

Liest eine YAML-Konfigurationsdatei ein, validiert das Pflichtfeld
(config/loglevel) und stellt das Konfigurationsobjekt
als Python-Dictionary bereit. Bietet zusätzlich eine Convenience-Methode
zur Erstellung einer fertig konfigurierten Log-Instanz.
"""

import copy
import logging
import os
import re
import sys
from typing import NoReturn

import yaml

from base_resources.log import Log


class ConfigLoader:
    """
    Lädt und validiert eine YAML-Konfigurationsdatei.

    Parameter:
        config_pfad (str | None): Optionaler expliziter Pfad zur YAML-Datei.
                                   Standard: None (automatische Ermittlung).
    """

    # Gültige Log-Level als Menge für schnelle Prüfung
    GUELTIGE_LOG_LEVEL = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    def __init__(self, config_pfad: str | None = None):
        """
        Initialisiert den ConfigLoader, liest und validiert die YAML-Datei.

        Bei Fehlern wird eine Meldung auf stderr ausgegeben und das
        Programm mit Exit-Code 1 beendet.
        """
        # YAML-Dateipfad ermitteln (Task 2.1)
        self._pfad = self._dateipfad_ermitteln(config_pfad)

        # YAML-Datei einlesen und parsen (Task 2.2)
        self._daten = self._datei_einlesen()

        # Umgebungsvariablen in Konfigurationswerten ersetzen (${VARIABLE})
        self._referenzierte_variablen = {}
        self._yml_variablen = {}  # Schlüssel → (aufgelöster Wert, "env"|"hard")
        self._rohdaten = copy.deepcopy(self._daten)  # Original-Daten vor Ersetzung merken
        self._daten = self._variablen_ersetzen(self._daten)
        self._yml_variablen_sammeln(self._daten, self._rohdaten)

        # Pflichtfelder validieren (Task 2.3)
        self._pflichtfelder_validieren()

        # Logger-Referenz (wird nach erstelle_log() gesetzt)
        self._log = None

    # --- Öffentliche Methoden und Properties (Tasks 2.4, 2.5) ---

    def get(self, *schluessel: str) -> any:
        """
        Gibt einen Konfigurationswert per Schlüsselpfad zurück.

        Parameter:
            *schluessel: Beliebig viele Schlüssel für verschachtelte Zugriffe.
                         z.B. get("config", "loglevel")

        Rückgabe:
            Der Wert am angegebenen Pfad oder None, falls nicht vorhanden.
        """
        # Verschachtelt durch das Dictionary navigieren
        ergebnis = self._daten
        for s in schluessel:
            if isinstance(ergebnis, dict):
                ergebnis = ergebnis.get(s)
            else:
                return None
        return ergebnis

    @property
    def config(self) -> dict:
        """Gibt das vollständige Konfigurationsobjekt (Dictionary) zurück."""
        return self._daten

    @property
    def referenzierte_variablen(self) -> dict[str, str]:
        """
        Gibt alle in der YML referenzierten Umgebungsvariablen als Dictionary zurück.

        Schlüssel: Variablenname (z.B. 'S3_Mapcloud')
        Wert: Aufgelöster Wert aus os.environ
        """
        return self._referenzierte_variablen

    @property
    def yml_variablen(self) -> dict[str, tuple[str, str]]:
        """
        Gibt alle in der YML definierten Variablen mit Herkunft zurück.

        Schlüssel: Punkt-separierter Pfad (z.B. 'config.logpath')
        Wert: Tuple (aufgelöster_wert, herkunft) — herkunft ist "env" oder "hard"
        """
        return self._yml_variablen

    def erstelle_log(self, **kwargs) -> "Log":
        """
        Erstellt eine Log-Instanz anhand der geladenen Konfiguration.

        Logfiles landen immer in <Programmverzeichnis>/logs/.
        Der loglevel-String wird in den entsprechenden logging-Integer umgewandelt.

        Zusätzlich wird geprüft, ob das feste Verzeichnis /logs existiert und
        beschreibbar ist. Ist es das nicht (z.B. lokale Entwicklung ohne
        Container-Mount), wird ein S3-Sync des Logfiles gestartet, damit
        die Logs zentral verfügbar sind.

        Parameter:
            **kwargs: Zusätzliche Parameter, die an den Log-Konstruktor
                      weitergereicht werden (z.B. silent, max_mb).

        Rückgabe:
            Log: Eine konfigurierte Instanz der Log-Klasse.
        """
        # Loglevel aus der Konfiguration lesen
        loglevel_str = self._daten["config"]["loglevel"]

        # Optionaler Logfile-Name aus der Konfiguration (Standard: <Programmname>.log)
        logfile_name = self._daten["config"].get("logfile_name")

        # Optionale Log-Rotation nach Größe (in MB). Fehlt der Wert, ist die
        # Größen-Rotation deaktiviert (None). Der Wert kann als Zahl oder String
        # (z.B. aus einer ${VARIABLE}-Ersetzung) in der YML stehen.
        logfile_max_mb = self._daten["config"].get("logfile_max_mb")
        if logfile_max_mb is not None:
            try:
                logfile_max_mb = float(logfile_max_mb)
            except (TypeError, ValueError):
                logfile_max_mb = None

        # Programmverzeichnis aus sys.argv[0] ermitteln
        programm_verzeichnis = os.path.dirname(os.path.abspath(sys.argv[0]))

        # Lokales Log-Verzeichnis: local_logpath (relativ zum Programmverzeichnis) oder Standard
        local_logpath = self._daten["config"].get("local_logpath")
        if local_logpath:
            lokaler_logpath = os.path.normpath(os.path.join(programm_verzeichnis, local_logpath))
        else:
            lokaler_logpath = os.path.join(programm_verzeichnis, "logs")

        # Alte Logdateien bereinigen (älter als 1 Tag)
        self._alte_logs_bereinigen(lokaler_logpath)

        # Loglevel-String in logging-Integer umwandeln
        log_level_int = getattr(logging, loglevel_str)

        # --silent aus Kommandozeile prüfen
        silent = "--silent" in sys.argv

        # Ein explizit übergebenes max_mb (via erstelle_log(max_mb=...)) hat
        # Vorrang vor dem YML-Wert.
        kwargs.setdefault("max_mb", logfile_max_mb)

        # Log-Instanz erstellen
        log = Log(
            log_verzeichnis=lokaler_logpath,
            log_level=log_level_int,
            logfile_name=logfile_name,
            silent=silent,
            **kwargs,
        )

        # Logger-Referenz speichern
        self._log = log

        # Programmname ermitteln und als erste Zeile ins Log schreiben
        programmname = os.path.splitext(os.path.basename(os.path.abspath(sys.argv[0])))[0]
        log.info("########## Programm %s gestartet ##########", programmname)
        log.info("Logpath: %s", lokaler_logpath)

        return log

    def beenden(self) -> None:
        """
        Platz für Aufräumarbeiten am Programmende.

        Wird von `base_resources.startup.beenden()` aufgerufen. Aktuell
        gibt es keine Hintergrundprozesse zu stoppen.
        """
        return None

    @staticmethod
    def _alte_logs_bereinigen(log_verzeichnis: str, max_alter_tage: int = 1) -> None:
        """
        Löscht Dateien und leere Unterverzeichnisse im Log-Verzeichnis,
        die älter als max_alter_tage sind.

        Die Log-Struktur ist: <log_verzeichnis>/<YYYY-MM-DD>/<logfile>.
        Verzeichnisse, deren Datumsname älter als gestern ist, werden
        komplett entfernt.

        Parameter:
            log_verzeichnis (str): Pfad zum Log-Basisverzeichnis.
            max_alter_tage (int): Maximales Alter in Tagen. Standard: 1.
        """
        import shutil
        from datetime import datetime, timedelta

        if not os.path.isdir(log_verzeichnis):
            return

        grenze = datetime.now() - timedelta(days=max_alter_tage)
        grenz_datum = grenze.strftime("%Y-%m-%d")

        for eintrag in os.listdir(log_verzeichnis):
            eintrag_pfad = os.path.join(log_verzeichnis, eintrag)

            if not os.path.isdir(eintrag_pfad):
                continue

            # Nur Verzeichnisse im Format YYYY-MM-DD berücksichtigen
            try:
                datetime.strptime(eintrag, "%Y-%m-%d")
            except ValueError:
                continue

            # Alles löschen, was älter als heute ist (nur heutiges Datum bleibt)
            if eintrag <= grenz_datum:
                try:
                    shutil.rmtree(eintrag_pfad)
                except OSError:
                    pass

    # --- Private Hilfsmethoden ---

    # Muster für Variablenplatzhalter: ${VARIABLE_NAME} oder ${VARIABLE_NAME:-default}
    _VARIABLEN_MUSTER = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

    def _yml_variablen_sammeln(self, daten, rohdaten, prefix=""):
        """
        Durchläuft die aufgelöste YML-Struktur rekursiv und sammelt alle
        Blatt-Werte mit ihrer Herkunft (env oder hard).

        Ein Wert gilt als "env", wenn der zugehörige Rohwert (vor Ersetzung)
        einen ${...}-Platzhalter enthielt. Andernfalls ist er "hard".

        Parameter:
            daten: Aufgelöste YAML-Datenstruktur (dict, list, str, etc.)
            rohdaten: Ursprüngliche YAML-Datenstruktur (vor Variablenersetzung)
            prefix (str): Aktueller Schlüsselpfad (punkt-separiert).
        """
        if isinstance(daten, dict):
            for schluessel, wert in daten.items():
                pfad = f"{prefix}.{schluessel}" if prefix else schluessel
                roh_wert = rohdaten.get(schluessel) if isinstance(rohdaten, dict) else None
                self._yml_variablen_sammeln(wert, roh_wert, pfad)
        elif isinstance(daten, list):
            for i, element in enumerate(daten):
                pfad = f"{prefix}[{i}]"
                roh_element = rohdaten[i] if isinstance(rohdaten, list) and i < len(rohdaten) else None
                self._yml_variablen_sammeln(element, roh_element, pfad)
        elif isinstance(daten, str):
            # Herkunft bestimmen: Enthielt der Rohwert einen ${...}-Platzhalter?
            herkunft = "hard"
            if isinstance(rohdaten, str) and self._VARIABLEN_MUSTER.search(rohdaten):
                herkunft = "env"
            self._yml_variablen[prefix] = (daten, herkunft)
        else:
            # Nicht-String-Werte (int, bool, etc.) sind immer "hard"
            if prefix:
                self._yml_variablen[prefix] = (str(daten), "hard")

    def _variablen_ersetzen(self, daten: dict) -> dict:
        """
        Ersetzt rekursiv Platzhalter der Form ${VARIABLE} in String-Werten
        durch die entsprechenden Umgebungsvariablen.

        Sammelt alle nicht aufgelösten Platzhalter und bricht das Programm
        mit einer Fehlermeldung ab, falls Umgebungsvariablen fehlen.

        Parameter:
            daten: Beliebige YAML-Datenstruktur (dict, list, str, etc.)

        Rückgabe:
            Die Datenstruktur mit ersetzten Variablen.
        """
        fehlende_variablen = set()
        ergebnis = self._variablen_ersetzen_rekursiv(daten, fehlende_variablen)

        if fehlende_variablen:
            variablen_liste = ", ".join(sorted(fehlende_variablen))
            self._fehler_und_beenden(
                f"FEHLER: Fehlende Umgebungsvariable(n) in {self._pfad}: {variablen_liste}"
            )

        return ergebnis

    def _variablen_ersetzen_rekursiv(self, daten, fehlende_variablen):
        """
        Rekursive Hilfsmethode für die Variablenersetzung.

        Ersetzt ${VARIABLE}- und ${VARIABLE:-default}-Platzhalter durch
        Umgebungsvariablen und sammelt nicht auflösbare Variablennamen
        in der übergebenen Menge.

        Syntax:
            ${VARIABLE}           — Pflicht, Fehler wenn nicht gesetzt
            ${VARIABLE:-default}  — Optional, verwendet default wenn nicht gesetzt

        Parameter:
            daten: Beliebige YAML-Datenstruktur (dict, list, str, etc.)
            fehlende_variablen (set): Menge, in die fehlende Variablennamen
                                       eingetragen werden.

        Rückgabe:
            Die Datenstruktur mit ersetzten Variablen.
        """
        if isinstance(daten, dict):
            return {
                k: self._variablen_ersetzen_rekursiv(v, fehlende_variablen)
                for k, v in daten.items()
            }
        if isinstance(daten, list):
            return [
                self._variablen_ersetzen_rekursiv(element, fehlende_variablen)
                for element in daten
            ]
        if isinstance(daten, str):
            # Fehlende Variablen sammeln (nur wenn kein Default angegeben)
            for treffer in self._VARIABLEN_MUSTER.finditer(daten):
                variablenname = treffer.group(1)
                default_wert = treffer.group(2)  # None wenn kein :- angegeben
                if variablenname not in os.environ:
                    if default_wert is None:
                        # Kein Default → Variable ist Pflicht
                        fehlende_variablen.add(variablenname)
                else:
                    # Referenzierte Variable mit aufgelöstem Wert merken
                    self._referenzierte_variablen[variablenname] = os.environ[variablenname]

            # Variablen ersetzen: Umgebungsvariable oder Default-Wert
            def _ersetze(m):
                variablenname = m.group(1)
                default_wert = m.group(2)  # None wenn kein :- angegeben
                if variablenname in os.environ:
                    return os.environ[variablenname]
                if default_wert is not None:
                    return default_wert
                # Platzhalter unverändert lassen (wird als fehlend gemeldet)
                return m.group(0)

            return self._VARIABLEN_MUSTER.sub(_ersetze, daten)
        return daten

    def _fehler_und_beenden(self, nachricht: str) -> NoReturn:
        """Gibt eine Fehlermeldung auf stderr aus und beendet das Programm."""
        print(nachricht, file=sys.stderr)
        sys.exit(1)

    def _dateipfad_ermitteln(self, config_pfad: str | None) -> str:
        """
        Ermittelt den Pfad zur YAML-Konfigurationsdatei.

        Bei explizitem Pfad wird dieser direkt verwendet.
        Andernfalls wird der Programmname aus sys.argv[0] abgeleitet
        und eine gleichnamige .yml-Datei im selben Verzeichnis gesucht.
        """
        if config_pfad is not None:
            # Expliziter Pfad wurde angegeben
            return config_pfad

        # Programmname aus sys.argv[0] ableiten
        programm_pfad = os.path.abspath(sys.argv[0])
        programm_verzeichnis = os.path.dirname(programm_pfad)
        programmname = os.path.basename(programm_pfad)

        # Dateiendung entfernen und .yml anhängen
        basisname = os.path.splitext(programmname)[0]
        yaml_datei = f"{basisname}.yml"

        return os.path.join(programm_verzeichnis, yaml_datei)

    def _datei_einlesen(self) -> dict:
        """
        Liest die YAML-Datei ein und gibt das geparste Dictionary zurück.

        Behandelt Fehler: Datei nicht gefunden, nicht lesbar,
        ungültiges YAML, leere Datei.
        """
        # Prüfen ob die Datei existiert
        if not os.path.exists(self._pfad):
            self._fehler_und_beenden(
                f"FEHLER: Konfigurationsdatei nicht gefunden: {self._pfad}"
            )

        # Datei einlesen mit Fehlerbehandlung
        try:
            with open(self._pfad, "r", encoding="utf-8") as datei:
                inhalt = yaml.safe_load(datei)
        except PermissionError as e:
            self._fehler_und_beenden(
                f"FEHLER: Konfigurationsdatei nicht lesbar: {self._pfad} ({e})"
            )
        except yaml.YAMLError as e:
            self._fehler_und_beenden(
                f"FEHLER: Ungültiges YAML in {self._pfad}: {e}"
            )

        # Prüfen ob die Datei leer ist (yaml.safe_load gibt None zurück)
        if inhalt is None:
            self._fehler_und_beenden(
                f"FEHLER: Konfigurationsdatei ist leer: {self._pfad}"
            )

        return inhalt

    def _pflichtfelder_validieren(self) -> None:
        """
        Validiert die Pflichtfelder der Konfiguration.

        Prüft: config-Schlüssel, config/loglevel, gültiger Loglevel-Wert.
        """
        # Prüfen ob 'config'-Schlüssel existiert
        if "config" not in self._daten:
            self._fehler_und_beenden(
                f"FEHLER: Pflichtabschnitt 'config' fehlt in {self._pfad}"
            )

        config_abschnitt = self._daten["config"]

        # Prüfen ob 'loglevel' vorhanden ist
        if "loglevel" not in config_abschnitt:
            self._fehler_und_beenden(
                f"FEHLER: Pflichtschlüssel 'loglevel' fehlt unter 'config' in {self._pfad}"
            )

        # Prüfen ob loglevel ein gültiger Wert ist
        loglevel = config_abschnitt["loglevel"]
        if loglevel not in self.GUELTIGE_LOG_LEVEL:
            self._fehler_und_beenden(
                f"FEHLER: Ungültiger Loglevel '{loglevel}' in {self._pfad}. "
                f"Erlaubt: DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )


def lade_config(config_pfad: str | None = None) -> ConfigLoader:
    """
    Convenience-Funktion zum Erstellen eines ConfigLoader.

    Parameter:
        config_pfad (str | None): Optionaler expliziter Pfad zur YAML-Datei.

    Rückgabe:
        ConfigLoader: Die geladene und validierte Konfiguration.
    """
    return ConfigLoader(config_pfad=config_pfad)
