"""
Zentrale Startup-Sequenz für alle Hauptprogramme.

Bündelt EnvLoader, ConfigLoader, Log-Erstellung und das Loggen
der Umgebungsvariablen in einer einzigen Funktion.
"""

import os
import re
import sys

from base_resources.config_loader import ConfigLoader
from base_resources.env_loader import EnvLoader

# Muster für sensible Schlüsselnamen (case-insensitive)
_SENSIBEL_MUSTER = re.compile(
    r"(pwd|password|passwort|kennwort|secret|token|credential|auth|key)",
    re.IGNORECASE,
)


def _maskiere_wert(wert):
    """
    Maskiert einen sensiblen Wert für die Log-Ausgabe.

    Bei 7+ Zeichen: erste 3 + *** + letzte 3 (z.B. HWS***BKR).
    Bei kürzeren Werten: komplett ***.
    """
    if len(wert) >= 7:
        return f"{wert[:3]}***{wert[-3:]}"
    return "***"


def maskiere_wert(wert):
    """
    Maskiert einen sensiblen Wert nach Projektvorgabe für die Log-Ausgabe.

    Öffentlicher Zugang zur Maskierungsregel aus `project-standards.md`
    (Abschnitt „Kennwort-Maskierung in Log-Ausgaben"), damit andere Module sie
    nicht ein zweites Mal implementieren müssen.

    Parameter:
        wert: Der zu maskierende Wert.

    Rückgabe:
        str: Bei 7+ Zeichen erste 3 + *** + letzte 3, sonst ***.
    """
    return _maskiere_wert(str(wert))


def _log_wert(schluessel, wert):
    """
    Gibt den Wert zurück — maskiert, falls der Schlüsselname
    auf ein Kennwort oder Secret hindeutet.
    """
    if _SENSIBEL_MUSTER.search(schluessel):
        return _maskiere_wert(str(wert))
    return wert


def initialisierung(projektroot):
    """
    Führt die Standard-Startup-Sequenz für ein Hauptprogramm aus.

    1. EnvLoader — Umgebungsvariablen aus .*_env-Dateien laden
    2. ConfigLoader — YML-Konfiguration laden (mit ${VARIABLE}-Ersetzung)
    3. Log — Log-Instanz über config.erstelle_log() erstellen
    4. Umgebungsvariablen ins Log schreiben

    Parameter:
        projektroot (str): Pfad zum Workspace-Root (für den EnvLoader)

    Rückgabe:
        tuple: (config, log) — ConfigLoader-Instanz und Log-Instanz
    """

    # 1. Umgebungsvariablen aus .*_env-Dateien laden (immer als erstes!)
    env = EnvLoader(workspace_root=projektroot)

    # 2. Konfiguration laden (--config oder automatisch aus Programmname)
    # Das aufrufende Hauptprogramm bestimmt Verzeichnis und Name
    hauptprogramm = os.path.abspath(sys.argv[0])
    programm_verzeichnis = os.path.dirname(hauptprogramm)
    programmname = os.path.splitext(os.path.basename(hauptprogramm))[0]

    config_pfad = None
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            config_pfad = sys.argv[i + 1]

    if config_pfad is None:
        config_pfad = os.path.join(programm_verzeichnis, f"{programmname}.yml")

    config = ConfigLoader(config_pfad=config_pfad)

    # 3. Log-Instanz aus der Konfiguration erstellen
    log = config.erstelle_log()

    # 4. Konfigurationsdatei ins Log schreiben
    log.info("Konfigurationsdatei: %s", os.path.abspath(config_pfad))
    log.info("Geladene Env-Dateien: %s", env.geladene_dateien)

    # 5. Umgebungsvariablen ins Log schreiben (Pflicht nach Programmstart!)
    if env.geladene_variablen:
        log.info("%d Umgebungsvariable(n) geladen:", len(env.geladene_variablen))
        for schluessel, wert in env.geladene_variablen.items():
            log.info("  %s = %s", schluessel, _log_wert(schluessel, wert))
    else:
        log.info("Keine Env-Dateien geladen — verwende vorhandene Umgebungsvariablen")

    if env.uebersprungene_variablen:
        log.info("%d Umgebungsvariable(n) übersprungen (bereits gesetzt):", len(env.uebersprungene_variablen))
        for schluessel in env.uebersprungene_variablen:
            log.info("  %s = %s", schluessel, _log_wert(schluessel, os.environ.get(schluessel, "")))

    # 6. Alle YML-Variablen mit Herkunft (env/hard) ausgeben
    if config.yml_variablen:
        log.info("YML-Variablen (%d):", len(config.yml_variablen))
        for pfad, (wert, herkunft) in config.yml_variablen.items():
            log.info("  %s = %s (%s)", pfad, _log_wert(pfad, wert), herkunft)

    return config, log


def beenden(config, log):
    """
    Beendet ein Hauptprogramm sauber.

    Führt den letzten S3-Upload des Logfiles durch (falls aktiv)
    und schreibt die Abschlussmeldung ins Log.

    Muss am Ende jedes Hauptprogramms aufgerufen werden:

        config, log = initialisierung(projektroot)
        main(config, log)
        beenden(config, log)

    Parameter:
        config: ConfigLoader-Instanz (aus initialisierung())
        log: Log-Instanz (aus initialisierung())
    """
    # Programmname aus sys.argv[0] ermitteln
    programmname = os.path.splitext(os.path.basename(os.path.abspath(sys.argv[0])))[0]
    log.info("!!!!!!!!!! Programm %s beendet !!!!!!!!!!", programmname)
    config.beenden()
