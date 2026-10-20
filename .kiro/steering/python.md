---
inclusion: always
---

# Python-Umgebung

## Basissprache

Basisprogrammiersprache für alle Projekte in diesem Stammverzeichnis ist
Python. Abweichungen werden pro Projekt ausdrücklich festgelegt.

## Gemeinsames venv

Es gibt genau ein venv für alle Projekte. Es liegt im Stammverzeichnis:

```
/home/baer/gitrepos/raspirepo/.venv
```

Jede Ausführung von Python und jede Installation von Paketen läuft über
dieses venv. Nie über das System-Python, nie mit `sudo pip`.

Aufruf ohne vorherige Aktivierung (bevorzugt, weil eindeutig):

```bash
/home/baer/gitrepos/raspirepo/.venv/bin/python   skript.py
/home/baer/gitrepos/raspirepo/.venv/bin/pip      install paketname
```

Aufruf mit Aktivierung:

```bash
source /home/baer/gitrepos/raspirepo/.venv/bin/activate
```

## Abhängigkeiten

Jedes Projekt pflegt seine eigene `requirements.txt` im
Projektverzeichnis. Versionen werden gepinnt (`paket==1.2.3`), nicht
offen gelassen.

Da alle Projekte dasselbe venv teilen, wird vor dem Hinzufügen eines
Pakets geprüft, ob es mit den bereits installierten Versionen kollidiert
(`pip list`, `pip install --dry-run`). Eine Kollision wird gemeldet,
nicht stillschweigend überschrieben.

## Zentrale Basis-Bausteine: base_resources

Jedes neue Hauptprogramm (mit `if __name__ == "__main__"`) nutzt das
Paket `base_resources` im Stammverzeichnis für Start, Konfiguration und
Logging. Kein eigenes `logging.basicConfig`, kein `print` für
Programmausgaben, keine eigene YAML-Ladelogik.

Einstieg immer nach diesem Muster:

```python
import os, sys

projektroot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, projektroot)

from base_resources.startup import initialisierung, beenden


def main(config, log):
    ...


if __name__ == "__main__":
    config, log = initialisierung(projektroot)
    try:
        main(config, log)
    finally:
        beenden(config, log)
```

`projektroot` ist der Workspace-Root – das Verzeichnis, das
`base_resources/` und `.venv/` enthält, **nicht** das Projektverzeichnis.
Die Zahl der `dirname`-Schritte richtet sich nach der Ablagetiefe des
Programms (eine Datei direkt in `<projekt>/` braucht zwei Schritte).

Pflicht-Konfiguration: eine gleichnamige `<programm>.yml` neben dem
Programm mit mindestens

```yaml
config:
  loglevel: INFO        # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

Zugriff im Code über `config.get("config", "loglevel")` und die
Log-Methoden `log.info(...)`, `log.debug(...)`, `log.warning(...)`,
`log.error(...)`, `log.critical(...)`. Programmausgaben laufen über das
Log, nicht über `print`.

Das Framework erledigt: Laden der `.*_env`-Dateien,
`${VARIABLE}`-Ersetzung in der YML, Maskierung sensibler Werte im Log,
die Argumente `--silent` und `--config`, Tagesordner für Logs und das
Aufräumen alter Logs.

Ausnahme: Ein bewusst framework-freies Programm (wie
`schulportal_standalone.py`) ist erlaubt, muss aber in `<projekt>.md`
mit Begründung dokumentiert sein.

## Hinweis zur Laufzeitumgebung

Geprüft am 20.10.2026: Das System ist ein Raspberry Pi 5 Model B Rev 1.1
mit rund 7,9 GiB RAM (`/proc/meminfo`: `MemTotal 8252416 kB`). `/` liegt
auf einer lokalen NVMe-SSD (`/dev/nvme0n1p2`, ext4; `findmnt /`),
`/home/baer` ist kein eigener Mount und fällt damit ebenfalls auf diese
NVMe. Swap ist ausschließlich zram (`/dev/zram0`, 2 GiB;
`swapon --show`).

NFS ist vorhanden, betrifft aber nicht das Arbeitsverzeichnis: Es gibt
Exporte unter `/srv/nfs/netboot` und `/srv/nfs/home` (Server `baernas`)
sowie einen Datenmount `/mnt/BaerNas` (`findmnt -t nfs,nfs4`).

Konsequenz für die Umsetzung: Arbeitsspeicher und lokale Datei-Zugriffe
sind unkritisch. Zugriffe, die gezielt über die NFS-Mounts laufen
(`/mnt/BaerNas`, `/srv/nfs/*`), werden dagegen als potenziell langsam
behandelt und benannt.