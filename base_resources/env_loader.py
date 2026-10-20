"""
Zentraler Environment-Loader für alle Projekte.

Sucht im Workspace-Root alle Dateien nach dem Muster .*_env (z.B. .dev_env,
.db_env) und lädt die darin definierten Key-Value-Paare als Umgebungsvariablen.

Bereits gesetzte Umgebungsvariablen (z.B. aus Docker) werden NICHT überschrieben.
"""

import os
import re


class EnvLoader:
    """
    Lädt Umgebungsvariablen aus .*_env-Dateien im Workspace-Root.

    Parameter:
        workspace_root (str | None): Pfad zum Workspace-Root.
                                      Standard: None (automatische Ermittlung
                                      über das übergeordnete Verzeichnis des
                                      aufrufenden Programms).
    """

    # Muster für gültige Env-Dateien: beginnt mit Punkt, endet mit _env
    DATEI_MUSTER = re.compile(r"^\..+_env$")

    def __init__(self, workspace_root: str | None = None):
        """
        Initialisiert den EnvLoader und lädt alle gefundenen Env-Dateien.

        Parameter:
            workspace_root (str | None): Expliziter Pfad zum Workspace-Root.
                                          Falls None, wird das übergeordnete
                                          Verzeichnis des Skripts verwendet.
        """
        if workspace_root is not None:
            self._workspace_root = os.path.abspath(workspace_root)
        else:
            # Übergeordnetes Verzeichnis des aufrufenden Programms
            programm_verzeichnis = os.path.dirname(os.path.abspath(__file__))
            self._workspace_root = os.path.dirname(programm_verzeichnis)

        self._geladene_dateien: list[str] = []
        self._geladene_variablen: dict[str, str] = {}
        self._uebersprungene_variablen: list[str] = []

        self._env_dateien_laden()

    def _env_dateien_laden(self) -> None:
        """Sucht und lädt alle .*_env-Dateien im Workspace-Root."""
        if not os.path.isdir(self._workspace_root):
            return

        # Alle passenden Dateien im Workspace-Root finden
        dateien = sorted(
            datei
            for datei in os.listdir(self._workspace_root)
            if self.DATEI_MUSTER.match(datei)
            and os.path.isfile(os.path.join(self._workspace_root, datei))
        )

        for datei in dateien:
            dateipfad = os.path.join(self._workspace_root, datei)
            self._datei_parsen(dateipfad, datei)

    def _datei_parsen(self, dateipfad: str, dateiname: str) -> None:
        """
        Parst eine einzelne Env-Datei und setzt die Umgebungsvariablen.

        Format pro Zeile: KEY=VALUE
        Kommentare (#) und Leerzeilen werden ignoriert.
        Bereits gesetzte Variablen werden nicht überschrieben.

        Parameter:
            dateipfad (str): Vollständiger Pfad zur Env-Datei.
            dateiname (str): Name der Datei (für Protokollierung).
        """
        try:
            with open(dateipfad, "r", encoding="utf-8") as datei:
                for zeile in datei:
                    zeile = zeile.strip()

                    # Leerzeilen und Kommentare überspringen
                    if not zeile or zeile.startswith("#"):
                        continue

                    # KEY=VALUE aufteilen (nur beim ersten '=')
                    if "=" not in zeile:
                        continue

                    schluessel, wert = zeile.split("=", 1)
                    schluessel = schluessel.strip()
                    wert = wert.strip()

                    if not schluessel:
                        continue

                    # Bereits gesetzte Variablen nicht überschreiben
                    if schluessel in os.environ:
                        self._uebersprungene_variablen.append(schluessel)
                        continue

                    os.environ[schluessel] = wert
                    self._geladene_variablen[schluessel] = wert

            self._geladene_dateien.append(dateiname)

        except (PermissionError, OSError):
            # Datei konnte nicht gelesen werden — still überspringen
            pass

    # --- Öffentliche Properties ---

    @property
    def geladene_dateien(self) -> list[str]:
        """Gibt die Liste der erfolgreich geladenen Env-Dateien zurück."""
        return self._geladene_dateien

    @property
    def geladene_variablen(self) -> dict[str, str]:
        """Gibt die geladenen Variablen als Dictionary zurück."""
        return self._geladene_variablen

    @property
    def uebersprungene_variablen(self) -> list[str]:
        """Gibt die Liste der übersprungenen (bereits gesetzten) Variablen zurück."""
        return self._uebersprungene_variablen

    @property
    def workspace_root(self) -> str:
        """Gibt den verwendeten Workspace-Root-Pfad zurück."""
        return self._workspace_root
