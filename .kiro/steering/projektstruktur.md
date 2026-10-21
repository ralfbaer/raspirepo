---
inclusion: always
---

# Projektstruktur

## Stammverzeichnis

```
/home/baer/gitrepos/raspirepo/
├── .kiro/steering/      Grundlegende Regeln für Kiro (dieses Verzeichnis)
├── .venv/               Gemeinsames Python-venv für alle Projekte
└── <projekt>/           Ein Unterverzeichnis pro Projekt
    ├── <programm>.py        Hauptprogramm (if __name__ == "__main__")
    ├── <programm>.yml       Gleichnamige YAML-Konfiguration
    ├── <programm>.sh        Startskript, benannt wie das Programm
    ├── requirements.txt     Gepinnte Abhängigkeiten
    ├── DOKU/                Pflicht-Markdown-Dokumentation
    ├── resources/           Assets (HTML, CSS, JS, Bilder, Daten)
    └── submodule/           Projekt-private .py-Module (Paket)
```

Jedes Projekt bekommt sein eigenes Unterverzeichnis. Quellcode,
Konfiguration und Dokumentation eines Projekts liegen vollständig in
diesem Unterverzeichnis. Keine Projektdateien direkt im Stammverzeichnis.

Zu jedem ausführbaren Programm gehört eine gleichnamige
YAML-Konfigurationsdatei im selben Verzeichnis.

Die folgenden Vorgaben zu Projektordner-Inhalt, `resources/`,
`submodule/`, `DOKU/` und Startskript gelten für neu angelegte Projekte.
Bestehende Projekte werden nicht nachträglich umgebaut, solange das nicht
ausdrücklich verlangt wird.

## Inhalt des Projektordners

Direkt im Projektordner liegen nur das oder die Hauptprogramme (mit
`if __name__ == "__main__"`), ihre gleichnamige YAML-Konfiguration, ihr
Startskript und `requirements.txt`. Alles andere liegt in
Unterverzeichnissen.

## Ressourcen und projekt-private Module

`resources/` enthält die Assets, die ein Programm lädt oder ausliefert:
HTML, CSS, JavaScript, Vorlagen, Bilder, Datendateien. Kein Quellcode.

`submodule/` enthält die projekt-privaten `.py`-Module, die ein Programm
importiert. Es ist ein Paket (`submodule/__init__.py`), der Import
erfolgt durchgängig mit `submodule.`-Präfix
(`from submodule.kamera import ...`), auch zwischen den Modulen
untereinander. Module dürfen von mehreren Programmen desselben Projekts
geteilt werden; geteilt wird innerhalb des Projekts, nicht darüber
hinaus.

Das projektübergreifend geteilte `base_resources/` im Stammverzeichnis
ist kein projekt-privates Modul und bleibt unberührt.

## Startskript

Zu jedem Programm gehört ein Startskript im Projektordner, benannt wie
das Programm mit Endung `.sh` (z. B. `webcam_stream.sh`). Es startet das
Programm über das gemeinsame venv
(`/home/baer/gitrepos/raspirepo/.venv/bin/python`), passend zum
Einstiegsmuster aus `python.md`.

Müssen für ein Projekt mehrere Programme gestartet werden, wird vor dem
Anlegen gefragt, wie das Startskript heißen soll.

## Pflichtdokumentation pro Projekt

Zu jedem Projekt gehören drei Markdown-Dateien in einem Unterverzeichnis
`DOKU/` im Projektordner. Alle drei werden aktuell gehalten, nicht nur
beim Anlegen geschrieben.

### `DOKU/<projekt>.md` — Arbeitsstand für Kiro

Technischer Stand des Projekts, geschrieben von Kiro für Kiro. **Nicht
für menschliche Leser gedacht.** Zweck: eine neue Sitzung kann exakt am
letzten Punkt weiterarbeiten, ohne das Projekt neu zu erschließen.

Inhalt: aktueller Umsetzungsstand, erledigte und offene Schritte,
getroffene Entscheidungen samt Begründung, bekannte Probleme, geprüfte
und ungeprüfte Annahmen, nächster konkreter Arbeitsschritt.

Diese Datei wird am Ende jeder Arbeitseinheit aktualisiert.

### `DOKU/<projekt>_user.md` — Anleitung für den Anwender

Bedienungsanleitung für den menschlichen Anwender. **Keine technischen
Details**, keine Implementierungsinterna, keine Dateistruktur.

Inhalt: was das Projekt tut, wie es gestartet und bedient wird, welche
Eingaben erwartet werden, welche Ausgaben entstehen, was bei Fehlern zu
tun ist.

### `DOKU/<projekt>_architektur.md` — Technische Dokumentation

Detaillierte technische Beschreibung für Entwickler.

Inhalt: Architektur und Komponenten, Datenflüsse, Schnittstellen,
Datenmodelle, Abhängigkeiten, Konfiguration, Betriebs- und
Hardwarevoraussetzungen, bewusst verworfene Alternativen.

## Vor der Arbeit an einem Projekt: dessen Doku lesen

Sobald an einem Projektunterverzeichnis gearbeitet wird – seine Dateien
lesen, ändern oder erweitern – werden zuvor alle Markdown-Dateien im
`DOKU/`-Verzeichnis dieses Projekts gelesen. Das geschieht einmal je
Sitzung, nicht vor jedem einzelnen Schritt.

Reihenfolge: zuerst `DOKU/<projekt>.md` (Arbeitsstand), damit die Sitzung
am letzten Punkt weitermacht. Danach die übrigen nach Bedarf –
`DOKU/<projekt>_architektur.md` bei technischen Fragen,
`DOKU/<projekt>_user.md` bei Fragen zur Bedienung.

Sind die Docs widersprüchlich oder veraltet gegenüber dem Code, wird das
benannt, nicht stillschweigend übergangen.

## Projektspezifische Regeln

Zusätzliche Regeln für ein einzelnes Projekt werden als eigene
Steering-Datei im Stammverzeichnis abgelegt, begrenzt auf das
Projektverzeichnis:

```markdown
---
inclusion: fileMatch
fileMatchPattern: '<projekt>/**'
---
```

Grund: Kiro lädt Steering aus dem `.kiro/steering` des geöffneten
Workspace. Solange der Workspace das Stammverzeichnis ist, wird ein
`.kiro/steering` innerhalb eines Projektunterverzeichnisses nicht
geladen. Wird ein Projekt später als eigener Workspace geöffnet, kann
dort zusätzlich ein eigenes `.kiro/steering` liegen.

Projektspezifische Regeln haben Vorrang vor den Grundregeln, wenn sie
sich widersprechen. Ein Widerspruch wird benannt, nicht stillschweigend
aufgelöst.