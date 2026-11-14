# Käerjeng Waste Calendar

Converts the waste collection calendar of the municipality of Käerjeng, Luxembourg (PDF from SIDOR) into JSON, CSV and ICS, and publishes it to a web server. The ICS can be subscribed to in calendar apps or in Home Assistant.

## Quick start

Requirements: Python 3.12+, [Task](https://taskfile.dev), and SSH access to a web server (only needed for deployment, configured in `.env`).

```
task setup     # once: create venv, install dependencies
task all       # test, convert, upload, verify online
```

## Source PDF

The municipality's calendar PDF is not part of this repository. Download it from the municipality's website and put it into `input/` (for example `input/22285_SIDOR_calendrier_2026.pdf`). The folder `input/` is git-ignored.

The calendar is bilingual (French on the first page, German on the second). The parser relies on the layout and abbreviations of the 2026 edition; see [Known limits](#known-limits).

## Project layout

```
waste_calendar.py        converter (PDF -> JSON, CSV, ICS)
tests/                   pytest tests
input/                   source PDFs (git-ignored, not in the repository)
output/                  generated files (git-ignored, not in the repository)
Taskfile.yml             convert and deploy commands
.env.example             template for the server settings (copy to .env)
requirements.txt         pypdf, pytest
```

## Task commands

Run `task` without arguments to list all commands.

| Command | Effect |
|---|---|
| `task setup` | create the venv and install dependencies |
| `task test` | run the tests |
| `task convert` | convert the newest PDF in `input/`. Other PDF: `PDF=input/x.pdf`. Extra options after `--`, e.g. `task convert -- --no-alarm` |
| `task convert:force` | convert even if nothing changed |
| `task upload` | upload the files to the server (replaced files are backed up there, mode 644) |
| `task verify` | check that the ICS is reachable online and identical to the local file |
| `task deploy` | `upload`, then `verify` |
| `task all` | `test`, `convert:force`, `deploy` |

Server settings come from `.env` (see [Deployment](#deployment)).

## New year

1. Put the new PDF into `input/`.
2. Run `task all`.
3. The files without a year now contain both years. The URL used for subscriptions and Home Assistant stays the same.

## Running the converter directly

```
.venv/bin/python waste_calendar.py input/22285_SIDOR_calendrier_2026.pdf --outdir output
```

| Option | Meaning |
|---|---|
| `--outdir DIR` | output directory (default `.`) |
| `--year YYYY` | override the year (default: read from the PDF title) |
| `--name NAME` | file name prefix (default `kaerjeng_waste`) |
| `--municipality NAME` | municipality name used in event descriptions (default `Käerjeng`) |
| `--locality {clemency,fingig,bascharage,hautcharage,linger}` | keep only the shrub collection of this locality in the ICS |
| `--exclude TYPE …` | leave waste types (keys, see below) out of the ICS |
| `--alarm HH:MM` | reminder time on the evening before (default 19:00) |
| `--no-alarm` | write no reminders (`VALARM`) to the ICS |

`--locality` and `--exclude` only affect the ICS. JSON and CSV always contain everything.

## Output files

In `output/` (git-ignored, recreated by every run):

- **Per year:** `kaerjeng_waste_<year>.json`, `.csv`, `.ics`, and `kaerjeng_waste_<year>.notes.json` (footnote texts from the PDF, only used when merging, not uploaded).
- **Without year:** `kaerjeng_waste.json`, `.csv`, `.ics`. They merge all years present in the output folder. The name stays the same across years, so this is the file to subscribe to.

The ICS contains one event per waste type and day with a stable UID. Two runs produce identical files.

Event titles and descriptions are in German, because the target calendar is used in German.

## Waste types

| Key | Title in the ICS |
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

With `--locality`, the shrub collection is simply called `Heckenschnitt`. Bulky waste and electrical appliances (on request only) get no reminder.

## Home Assistant

The [Waste Collection Schedule](https://github.com/mampfes/hacs_waste_collection_schedule) integration reads the ICS through its generic `ics` source. The waste type is taken from the event title.

```yaml
waste_collection_schedule:
  sources:
    - name: ics
      args:
        url: "https://example.com/waste/kaerjeng_waste.ics"   # your public URL
      customize:
        - type: Elektrogeräte
          show: false                    # optional: hide
  sensors:
    - name: Hausmüll
      types:
        - Hausmüll
```

- Since version 2.0.0 the integration can also be set up in the Home Assistant UI, with the same arguments.
- For Home Assistant, generate the file with `--locality <place>` so that only your own shrub collection is included.
- The integration's documentation does not say how it handles reminders (`VALARM`). Check after the first import; if they cause trouble, regenerate with `--no-alarm`.

## Deployment

Deployment is configured through a local `.env` file, which is git-ignored. Copy `.env.example` to `.env` and fill in:

| Variable | Meaning |
|---|---|
| `HOST` | SSH host of the web server (as in `~/.ssh/config`) |
| `REMOTE_DIR` | directory on the server that the web server publishes |
| `BACKUP_ROOT` | directory on the server for backups, outside the public folder |
| `URL` | public base URL of that directory, used by `task verify` |

`task deploy` copies `kaerjeng_waste*.{ics,json,csv}` with rsync to `REMOTE_DIR`. Before files are overwritten, changed ones are moved to `BACKUP_ROOT/backup-waste-<timestamp>/`. Afterwards the task sets file mode 644 on the target, otherwise a web server running as another user may answer with 403 (macOS rsync has no `--chmod`). Then `task verify` downloads the ICS from `URL` and compares it with the local file.

The data is harmless (a public waste collection calendar), but keep in mind that a published folder with directory listing is visible to everyone.

## Validation

The converter aborts without writing anything (non-zero exit) if it

- finds no events,
- does not find all 12 months,
- finds a weekday that does not match the date,
- cannot fully classify a cell, or
- cannot read the file as a PDF.

For an unknown cell, add an entry to the alias table in `waste_calendar.py`. Warnings go to stderr if there are fewer than 12 glass or paper dates, or fewer than 52 household waste dates.

## Tests

```
task test
```

The end-to-end test uses the real PDF and is skipped if it is missing from `input/`.

## Known limits

- Clothing collection, association paper collection and school holidays appear in the PDF only as symbols or colours and are not extracted.
- Public holidays in the PDF are ignored.
- Classification is tuned to the spelling used in the 2026 calendar. A new PDF may contain new abbreviations; the converter reports them as an error instead of silently dropping events.
