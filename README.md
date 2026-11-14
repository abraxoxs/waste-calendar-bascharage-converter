# Müllkalender Käerjeng

Wandelt den Abfuhrkalender der Gemeinde Käerjeng (PDF von SIDOR) in JSON, CSV und ICS um. Die ICS-Datei kann in Kalender-Apps oder Home Assistant abonniert werden.

## Installation

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Aufruf

```
python waste_calendar.py input/<pdf> --outdir output
```

(Mit dem venv: `.venv/bin/python waste_calendar.py ...`)

Beispiel:

```
.venv/bin/python waste_calendar.py input/22285_SIDOR_calendrier_2026.pdf --outdir output
```

| Option | Bedeutung |
|---|---|
| `--year JJJJ` | Jahr überschreiben (Default: aus dem PDF-Titel gelesen) |
| `--name NAME` | Dateiname-Präfix (Default `kaerjeng_waste`) |
| `--municipality NAME` | Gemeindename (Default `Käerjeng`) |
| `--locality {clemency,fingig,bascharage,hautcharage,linger}` | Nur den Heckenschnitt dieses Ortes in die ICS aufnehmen |
| `--exclude TYP …` | Abfalltypen (Schlüssel, siehe unten) aus der ICS weglassen |
| `--alarm HH:MM` | Erinnerung am Vorabend zu dieser Uhrzeit (Default 19:00) |
| `--no-alarm` | Keine Erinnerung (`VALARM`) in die ICS schreiben |

`--locality` und `--exclude` wirken nur auf die ICS. JSON und CSV enthalten immer alles.

## Ausgabedateien

Im Ordner `output/`:

- Pro Jahr: `kaerjeng_waste_<jahr>.json`, `.csv`, `.ics` sowie `kaerjeng_waste_<jahr>.notes.json` (Fußnotentexte aus dem PDF, für die Zusammenführung).
- Ohne Jahr: `kaerjeng_waste.json`, `.csv`, `.ics`. Diese führen alle Jahre zusammen, die im Output-Ordner vorhanden sind. Der Name bleibt über Jahreswechsel gleich, daher eignet sich diese Datei für Abos.

Die ICS enthält einen Termin pro Abfallart und Tag. Die UIDs sind stabil, zwei Läufe liefern identische Dateien.

## Abfalltypen

| Schlüssel | Label in der ICS |
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

Mit `--locality` heißt der Heckenschnitt nur noch `Heckenschnitt`. Sperrmüll und Elektrogeräte (auf Anfrage) bekommen keine Erinnerung.

## Home Assistant

Integration: https://github.com/mampfes/hacs_waste_collection_schedule. Sie liest die ICS über die generische Quelle `ics`. Nötig ist nur `url` oder `file`. Die Abfallart kommt aus dem `SUMMARY` des Termins.

```yaml
waste_collection_schedule:
  sources:
    - name: ics
      args:
        file: "www/kaerjeng_waste.ics"   # liegt in config/www/
      customize:
        - type: Elektrogeräte
          show: false                    # optional ausblenden
  sensors:
    - name: Hausmüll
      types:
        - Hausmüll
```

- Die Datei ohne Jahr (`kaerjeng_waste.ics`) nach `config/www/` kopieren oder per URL bereitstellen. Der Pfad bleibt über den Jahreswechsel gleich.
- Laut Doku sind lokale Dateien bei manchen Installationen nur unterhalb von `config/www` lesbar; relative Pfade hängen vom Arbeitsverzeichnis von HA ab.
- Ab Version 2.0.0 lässt sich die Integration auch über die HA-Oberfläche einrichten, mit denselben Argumenten.
- Für HA am besten mit `--locality <ort>` erzeugen, damit nur der eigene Heckenschnitt enthalten ist.
- Wie die Integration `VALARM` behandelt, steht nicht in der Doku. Nach dem ersten Import prüfen, sonst für HA mit `--no-alarm` erzeugen.

## Neues Jahr

1. Neues PDF in `input/` legen.
2. Skript mit dem neuen PDF ausführen (siehe Aufruf).
3. Die Dateien ohne Jahr enthalten danach beide Jahre. Die Datei in Home Assistant bzw. im Abo-Hosting ersetzen.

## Validierung

Das Skript bricht ohne Schreiben ab (Exit ungleich 0), wenn es

- 0 Termine findet,
- nicht alle 12 Monate findet,
- einen Wochentag findet, der nicht zum Datum passt, oder
- eine Zelle nicht vollständig klassifizieren kann.

Im letzten Fall braucht die Alias-Tabelle in `waste_calendar.py` einen neuen Eintrag. Warnungen auf stderr gibt es bei weniger als 12x Glas oder Papier und weniger als 52x Hausmüll.

## Tests

```
.venv/bin/pytest
```

## Bekannte Grenzen

- Altkleidersammlung, Altpapiersammlung der Vereine und Schulferien stehen im PDF nur als Symbole/Farben und werden nicht extrahiert.
- Das Hosting der ICS-Datei für ein Abo ist nicht Teil des Tools. Das Skript schreibt nur die Datei mit festem Namen.
