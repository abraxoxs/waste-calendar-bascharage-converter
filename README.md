# Müllkalender Käerjeng

Wandelt den Abfuhrkalender der Gemeinde Käerjeng (PDF von SIDOR) in JSON, CSV und ICS um und veröffentlicht ihn auf `example.com`. Die ICS kann in Kalender-Apps oder Home Assistant abonniert werden.

**Abo-URL:** https://example.com/waste/kaerjeng_waste.ics

## Schnellstart

Voraussetzungen: Python 3.12+, [Task](https://taskfile.dev), SSH-Zugang zu einem Webserver zum Server (nur für das Deployment).

```
task setup     # einmalig: venv und Abhängigkeiten
task all       # Tests, Umwandeln, Hochladen, Online-Prüfung
```

## Projektstruktur

```
waste_calendar.py        Konverter (PDF -> JSON, CSV, ICS)
tests/                   pytest-Tests
input/                   Quell-PDFs der Gemeinde
output/                  erzeugte Dateien (werden mit eingecheckt)
Taskfile.yml             Befehle für Umwandeln und Deployen
requirements.txt         pypdf, pytest
```

## Task-Befehle

`task` ohne Argumente zeigt alle Befehle.

| Befehl | Wirkung |
|---|---|
| `task setup` | venv anlegen, Abhängigkeiten installieren |
| `task test` | Tests ausführen |
| `task convert` | neuestes PDF in `input/` umwandeln. Anderes PDF: `PDF=input/x.pdf`. Zusatzoptionen nach `--`, z. B. `task convert -- --no-alarm` |
| `task convert:force` | umwandeln, auch wenn sich nichts geändert hat |
| `task upload` | Dateien auf den Server laden (Backup der alten Dateien dort, Rechte 644) |
| `task verify` | prüfen, dass die ICS online erreichbar und identisch mit der lokalen ist |
| `task deploy` | `upload` und `verify` |
| `task all` | `test`, `convert:force`, `deploy` |

Server, Zielpfad und URL stehen oben in `Taskfile.yml`.

## Neues Jahr

1. Neues PDF in `input/` legen.
2. `task all` ausführen.
3. Die Dateien ohne Jahr enthalten danach beide Jahre. Die URL für Abo und Home Assistant bleibt gleich.

## Konverter direkt aufrufen

```
.venv/bin/python waste_calendar.py input/22285_SIDOR_calendrier_2026.pdf --outdir output
```

| Option | Bedeutung |
|---|---|
| `--outdir ORDNER` | Zielordner (Default `.`) |
| `--year JJJJ` | Jahr überschreiben (Default: aus dem PDF-Titel) |
| `--name NAME` | Dateiname-Präfix (Default `kaerjeng_waste`) |
| `--municipality NAME` | Gemeindename in der Terminbeschreibung (Default `Käerjeng`) |
| `--locality {clemency,fingig,bascharage,hautcharage,linger}` | nur den Heckenschnitt dieses Ortes in die ICS aufnehmen |
| `--exclude TYP …` | Abfalltypen (Schlüssel, siehe unten) aus der ICS weglassen |
| `--alarm HH:MM` | Erinnerung am Vorabend zu dieser Uhrzeit (Default 19:00) |
| `--no-alarm` | keine Erinnerung (`VALARM`) in die ICS schreiben |

`--locality` und `--exclude` wirken nur auf die ICS. JSON und CSV enthalten immer alles.

## Ausgabedateien

Im Ordner `output/`:

- **Pro Jahr:** `kaerjeng_waste_<jahr>.json`, `.csv`, `.ics` und `kaerjeng_waste_<jahr>.notes.json` (Fußnotentexte aus dem PDF, nur für die Zusammenführung, wird nicht hochgeladen).
- **Ohne Jahr:** `kaerjeng_waste.json`, `.csv`, `.ics`. Sie führen alle im Ordner vorhandenen Jahre zusammen. Der Name bleibt über den Jahreswechsel gleich, deshalb gehört diese Datei ins Abo.

Die ICS enthält einen Termin pro Abfallart und Tag mit stabiler UID. Zwei Läufe liefern identische Dateien.

## Abfalltypen

| Schlüssel | Titel in der ICS |
|---|---|
| `household` | Hausmüll |
| `organic` | Bioabfall |
| `paper` | Papier |
| `glass` | Glas |
| `valorlux` | Valorlux |
| `bulky` | Sperrmüll |
| `sdk` | SuperDrecksKëscht |
| `electrical_rdv` | Elektrogeräte |
| `christmas_trees` | Weihnachtsbäume |
| `shrubs_clemency_fingig` | Heckenschnitt Clemency/Fingig |
| `shrubs_bascharage_hautcharage_linger` | Heckenschnitt Bascharage/Hautcharage/Linger |

Mit `--locality` heißt der Heckenschnitt nur noch `Heckenschnitt`. Sperrmüll und Elektrogeräte (nur auf Anfrage) bekommen keine Erinnerung.

## Home Assistant

Die Integration [Waste Collection Schedule](https://github.com/mampfes/hacs_waste_collection_schedule) liest die ICS über die generische Quelle `ics`. Die Abfallart kommt aus dem Titel des Termins.

```yaml
waste_collection_schedule:
  sources:
    - name: ics
      args:
        url: "https://example.com/waste/kaerjeng_waste.ics"
      customize:
        - type: Elektrogeräte
          show: false                    # optional ausblenden
  sensors:
    - name: Hausmüll
      types:
        - Hausmüll
```

- Ab Version 2.0.0 geht die Einrichtung auch über die HA-Oberfläche, mit denselben Argumenten.
- Für HA am besten mit `--locality <ort>` erzeugen, damit nur der eigene Heckenschnitt enthalten ist.
- Wie die Integration die Erinnerungen (`VALARM`) behandelt, steht nicht in der Doku. Nach dem ersten Import prüfen, sonst mit `--no-alarm` neu erzeugen.

## Deployment

`task deploy` überträgt `kaerjeng_waste*.{ics,json,csv}` per rsync nach `the target directory` auf den Server. Das Verzeichnis ist in den nginx-Container eingebunden, ein Neustart ist nicht nötig. Vor dem Überschreiben landen geänderte Dateien in `/srv/web/backup-waste-<Zeitstempel>/` (außerhalb des öffentlichen Ordners). Anschließend setzt der Task die Rechte auf 644, sonst liefert nginx 403.

Der Ordner ist per Directory-Listing öffentlich einsehbar. Die Daten sind unkritisch, es ist ein öffentlicher Abfuhrkalender.

## Validierung

Der Konverter bricht ohne Schreiben ab (Exit ungleich 0), wenn er

- 0 Termine findet,
- nicht alle 12 Monate findet,
- einen Wochentag findet, der nicht zum Datum passt,
- eine Zelle nicht vollständig klassifizieren kann oder
- die Datei nicht als PDF lesen kann.

Bei einer unbekannten Zelle braucht die Alias-Tabelle in `waste_calendar.py` einen neuen Eintrag. Warnungen auf stderr gibt es bei weniger als 12× Glas oder Papier und weniger als 52× Hausmüll.

## Tests

```
task test
```

## Bekannte Grenzen

- Altkleidersammlung, Altpapiersammlung der Vereine und Schulferien stehen im PDF nur als Symbole oder Farben und werden nicht extrahiert.
- Feiertage im PDF werden ignoriert.
- Die Klassifizierung ist auf die Schreibweisen im Kalender 2026 abgestimmt. Ein neues PDF kann neue Abkürzungen enthalten. Der Konverter meldet das als Fehler, statt Termine still wegzulassen.
