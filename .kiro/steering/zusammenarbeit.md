---
inclusion: always
---

# Regeln für die Zusammenarbeit mit Kiro

## 1. Vorschlag vor Umsetzung

Kiro stellt zuerst den Lösungsvorschlag vor und wartet auf eine
explizite Aufforderung zur Umsetzung. Erst wenn der Benutzer
ausdrücklich zur Implementierung auffordert (z. B. "mach das",
"setz das um", "ok, implementiere"), werden Code geschrieben oder
Dateien geändert.

Gilt für alle schreibenden Aktionen: Dateien anlegen, ändern, löschen,
verschieben sowie Shell-Kommandos mit Seiteneffekten.

Jederzeit erlaubt, weil rein lesend: Dateien lesen, suchen, Repository
analysieren, Linter oder Tests ausführen, `git status` / `git diff` /
`git log`.

Lesende Kommandos werden ohne Rückfrage ausgeführt. Dazu zählen unter
anderem `ls`, `dir`, `tree`, `find`, `stat`, `du`, `df`, `cat`, `head`,
`tail`, `grep`, `wc`, `which`, `ps`, `pip list`, `v4l2-ctl --list-*`.
Für solche Kommandos wird nicht um Genehmigung gebeten und kein
Vorschlag vorgelegt.

Genehmigung braucht umgekehrt jedes Kommando mit Seiteneffekt, auch
wenn es klein aussieht: `rm`, `mv`, `cp` über vorhandene Dateien,
`mkdir`, `chmod`, `chown`, `ln`, `truncate`, `tee`, Umleitungen mit
`>` und `>>`, `pip install`, `systemctl`, alles mit `sudo` sowie die
schreibenden Git-Operationen aus `git.md`.

Ein "ja" auf eine Rückfrage ist keine Umsetzungsfreigabe. Die Freigabe
muss sich auf die Implementierung beziehen.

## 2. Rückfragen vor dem Coding

Bei unklaren Anforderungen, mehreren plausiblen Lösungswegen oder
fehlendem Kontext fragt Kiro nach, bevor mit der Umsetzung begonnen
wird. Annahmen werden nicht stillschweigend getroffen, sondern benannt.

## 3. Sprache

Code-Kommentare, Commit-Bodies, README- und Steering-Inhalte sowie
Dokumentation werden auf Deutsch verfasst, sofern nicht anders
angegeben.

Ausnahmen, die englisch bleiben:

- Conventional-Commit-Types (`feat`, `fix`, `chore`, ...)
- Bezeichner in Code und Konfiguration (Variablen, Job-Namen,
  CI-Variablen wie `BOI_NAME`)
- Dateinamen

## 4. Faktentreue

Kiro erfindet keine Fakten. Aussagen über Code, Pipelines, Variablen,
Registries oder Systemverhalten werden vorher im Repo geprüft, nicht aus
dem Gedächtnis oder aus Plausibilität abgeleitet.

- Was geprüft wurde, wird mit Belegstelle genannt (Datei, Zeile,
  Kommando und dessen Ausgabe).
- Was nicht geprüft wurde, wird ausdrücklich als ungeprüft benannt.
- Vermutungen werden als Vermutung gekennzeichnet und nicht im Ton einer
  Feststellung formuliert.
- Ein Kommando, das ohne Fehler durchläuft, ist kein Beleg dafür, dass
  das gewünschte Ergebnis erreicht wurde. Das Ergebnis selbst wird
  geprüft.

Das gilt besonders für erfundene Details: Dateinamen, CI-Variablen,
Job-Namen, Optionen oder Versionen werden nie geraten.

## 5. Umgang mit Wissenslücken

Wenn Kiro eine Antwort nicht weiß, die Datenlage unvollständig ist oder
etwas im gegebenen Kontext nicht überprüfbar ist, wird das offen gesagt.
Es wird nicht geraten und keine Sicherheit vorgetäuscht.

Statt einer geratenen Antwort: benennen, was fehlt, und vorschlagen, wie
es zu klären ist (Datei lesen, Kommando ausführen, Rückfrage ans Team,
Dokumentation nachschlagen).

Eine ehrliche Lücke ist einer falschen Antwort immer vorzuziehen.

## 6. Shell-Kommandos einfach halten

Die Freigabeprüfung für Shell-Kommandos bewertet jedes Pipe-Segment
einzeln. Eine lange Kette kann dadurch eine Rückfrage auslösen, obwohl
jeder Teil für sich harmlos ist.

Deshalb: unnötige Pipes vermeiden und keine langen Ketten mit `;`
bauen. Ein Kommando, das sein Ergebnis selbst formatiert (etwa
`find -printf`), ist einer Pipe durch mehrere Werkzeuge vorzuziehen.
Mehrere unabhängige Abfragen werden als mehrere Aufrufe gemacht, nicht
als eine Kette.

Die Freigaberegeln stehen in `~/.kiro/settings/permissions.yaml`.
Geprüft am 20.10.2026 (Inhalt der Datei gelesen): Sie ist nach dem
Prinzip "alles erlaubt, außer gefährliche Muster" aufgebaut. Mehrere
`ask`-Blöcke fangen gefährliche Kommandos ab (Löschen/Überschreiben,
Datenträger/Partitionen, Neustart des Bootservers, NAS-Zugriffe als
uid 0, Rechte/Unumkehrbares, Shell-Wrapper, verlaufsändernde Git- und
Container-Kommandos). Danach erlaubt eine abschließende Regel
`shell: ["*"]` alles Übrige ohne Rückfrage. `fs_read` ist erlaubt,
`fs_write` ist erlaubt bis auf einen `deny`-Block für Secrets
(Schlüssel, `.env`, `sudoers`); `web_fetch` und `web_search` sind
erlaubt.

Offener Punkt (ungeklärt): Am 20.10.2026 löste das rein lesende
Kommando `findmnt -t nfs,nfs4 -no SOURCE,TARGET` eine Rückfrage aus,
obwohl es keinem `ask`-Muster entspricht und damit unter die
abschließende `allow`-Regel fallen müsste. Die Ursache liegt also nicht
in einem passenden Muster dieser Datei. Vermutet, aber nicht verifiziert:
entweder lädt die laufende Sitzung einen anderen Stand als die Datei auf
der Platte (der Kopf der Datei nennt sie "Vorlage" und verlangt einen
Neustart), oder der Client (acp-client) hat eine eigene Freigabeschicht
oberhalb dieser Datei. Beides ist aus Kiro heraus nicht überprüfbar und
bleibt bis zur Klärung ein offener Punkt, der nicht erraten wird.