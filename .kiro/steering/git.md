---
inclusion: always
---

# Git

## Nur auf ausdrückliche Aufforderung

Kiro führt schreibende Git-Operationen ausschließlich dann aus, wenn der
Benutzer das ausdrücklich verlangt. Es gibt kein automatisches Committen,
kein "ich sichere das mal schnell ab", kein Aufräumen des Index neben-
bei.

Schreibend und damit freigabepflichtig: `init`, `add`, `commit`, `push`,
`pull`, `merge`, `rebase`, `checkout`, `switch`, `branch`, `tag`,
`reset`, `revert`, `stash`, `clean`, `remote`, `config`.

Jederzeit erlaubt, weil rein lesend: `status`, `diff`, `log`, `show`,
`branch --list`, `remote -v`.

Eine Freigabe gilt für die genannte Operation, nicht als Dauerfreigabe
für alles Weitere.

## Destruktive Operationen

`push --force`, `reset --hard`, `clean -fd`, `branch -D` und
vergleichbare Befehle werden nur nach ausdrücklicher Nennung durch den
Benutzer ausgeführt. Vorher wird benannt, was dabei unwiederbringlich
verloren geht.

Hooks werden nicht übersprungen (`--no-verify` nur auf Anweisung).
Die Git-Konfiguration bleibt unangetastet.

## Commit-Konventionen

Conventional Commits. Der Type bleibt englisch (`feat`, `fix`, `chore`,
`docs`, `refactor`, `test`, `build`, `ci`), die Beschreibung und der
Body werden auf Deutsch verfasst.

```
feat(webcam): Belichtungszeit konfigurierbar machen

Die Belichtungszeit war fest verdrahtet. Sie wird jetzt aus der
Konfiguration gelesen, Standardwert bleibt unverändert.
```

Betreffzeile kurz halten, Details in den Body.

## Staging

Dateien werden einzeln und benannt gestaged, nicht per `git add .` oder
`git add -A`. Dateien, die Geheimnisse enthalten können (`.env`,
Token-Dateien, Schlüssel, Zugangsdaten), werden vor dem Staging gemeldet
und nicht ohne Rückfrage aufgenommen.

Das gemeinsame venv `/home/baer/gitrepos/raspirepo/.venv` wird nie eingecheckt.
