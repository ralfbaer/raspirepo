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
```

Jedes Projekt bekommt sein eigenes Unterverzeichnis. Quellcode,
Konfiguration und Dokumentation eines Projekts liegen vollständig in
diesem Unterverzeichnis. Keine Projektdateien direkt im Stammverzeichnis.

Zu jedem ausführbaren Programm gehört eine gleichnamige
YAML-Konfigurationsdatei im selben Verzeichnis.

## Pflichtdokumentation pro Projekt

Zu jedem Projekt gehören drei Markdown-Dateien im Projektverzeichnis.
Alle drei werden aktuell gehalten, nicht nur beim Anlegen geschrieben.

### `<projekt>.md` — Arbeitsstand für Kiro

Technischer Stand des Projekts, geschrieben von Kiro für Kiro. **Nicht
für menschliche Leser gedacht.** Zweck: eine neue Sitzung kann exakt am
letzten Punkt weiterarbeiten, ohne das Projekt neu zu erschließen.

Inhalt: aktueller Umsetzungsstand, erledigte und offene Schritte,
getroffene Entscheidungen samt Begründung, bekannte Probleme, geprüfte
und ungeprüfte Annahmen, nächster konkreter Arbeitsschritt.

Diese Datei wird am Ende jeder Arbeitseinheit aktualisiert.

### `<projekt>_user.md` — Anleitung für den Anwender

Bedienungsanleitung für den menschlichen Anwender. **Keine technischen
Details**, keine Implementierungsinterna, keine Dateistruktur.

Inhalt: was das Projekt tut, wie es gestartet und bedient wird, welche
Eingaben erwartet werden, welche Ausgaben entstehen, was bei Fehlern zu
tun ist.

### `<projekt>_architektur.md` — Technische Dokumentation

Detaillierte technische Beschreibung für Entwickler.

Inhalt: Architektur und Komponenten, Datenflüsse, Schnittstellen,
Datenmodelle, Abhängigkeiten, Konfiguration, Betriebs- und
Hardwarevoraussetzungen, bewusst verworfene Alternativen.

## Vor der Arbeit an einem Projekt: dessen Doku lesen

Sobald an einem Projektunterverzeichnis gearbeitet wird – seine Dateien
lesen, ändern oder erweitern – werden zuvor alle Markdown-Dateien dieses
Projektverzeichnisses gelesen. Das geschieht einmal je Sitzung, nicht vor
jedem einzelnen Schritt.

Reihenfolge: zuerst `<projekt>.md` (Arbeitsstand), damit die Sitzung am
letzten Punkt weitermacht. Danach die übrigen nach Bedarf –
`<projekt>_architektur.md` bei technischen Fragen, `<projekt>_user.md`
bei Fragen zur Bedienung.

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