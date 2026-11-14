#!/usr/bin/env python3
"""
Convert the Käerjeng (SIDOR) waste collection PDF calendar into JSON, CSV and ICS.

Per year, in --outdir:
  <name>_<year>.json        complete, unfiltered list of {"date", "types", "raw"}
  <name>_<year>.csv         same data as CSV (types joined with "|")
  <name>_<year>.ics         calendar, one VEVENT per waste type and day
  <name>_<year>.notes.json  German footnotes (1)-(6) of the PDF, keyed "1".."6"
Then all <name>_????.json files are merged into <name>.json/.csv/.ics (no year in
the file name, so subscriptions keep working across the year change).

Usage:
  python waste_calendar.py input/22285_SIDOR_calendrier_2026.pdf --outdir output
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path


class ValidationError(Exception):
    """Raised when the PDF content cannot be understood completely."""


MONTH_PAIRS = [
    "Janvier/Januar",
    "Février/Februar",
    "Mars/März",
    "Avril/April",
    "Mai/Mai",
    "Juin/Juni",
    "Juillet/Juli",
    "Août/August",
    "Septembre/September",
    "Octobre/Oktober",
    "Novembre/November",
    "Décembre/Dezember",
]

MONTH_MAP = {m: i + 1 for i, m in enumerate(MONTH_PAIRS)}

STOP_MARKERS = [
    "Administration Communale",
    "Gemeindeverwaltung",
    "ECO-CENTER",
    "Service technique",
    "Le centre de recyclage",
    "Congés scolaires",
]

WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

DAY_RE = re.compile(r"^(\d{1,2})\s*([A-Za-zÀ-ÿ]{2,4}/[A-Za-zÀ-ÿ]{1,3})\s*(.*)$")

# Type keys in a fixed order (used to order types within a day).
TYPE_ORDER = [
    "household",
    "organic",
    "paper",
    "glass",
    "valorlux",
    "bulky",
    "sdk",
    "electrical_rdv",
    "christmas_trees",
    "shrubs_clemency_fingig",
    "shrubs_bascharage_hautcharage_linger",
]

TYPE_LABEL = {
    "household": "Hausmüll",
    "organic": "Bioabfall",
    "paper": "Papier",
    "glass": "Glas",
    "valorlux": "Valorlux",
    "bulky": "Sperrmüll",
    "sdk": "SuperDrecksKëscht",
    "electrical_rdv": "Elektrogeräte",
    "christmas_trees": "Weihnachtsbäume",
    "shrubs_clemency_fingig": "Heckenschnitt Clemency/Fingig",
    "shrubs_bascharage_hautcharage_linger": "Heckenschnitt Bascharage/Hautcharage/Linger",
}

SHRUB_TYPES = ("shrubs_clemency_fingig", "shrubs_bascharage_hautcharage_linger")
ON_REQUEST_TYPES = ("electrical_rdv", "bulky")

LOCALITY_TYPE = {
    "clemency": "shrubs_clemency_fingig",
    "fingig": "shrubs_clemency_fingig",
    "bascharage": "shrubs_bascharage_hautcharage_linger",
    "hautcharage": "shrubs_bascharage_hautcharage_linger",
    "linger": "shrubs_bascharage_hautcharage_linger",
}

# Footnote number -> type (footnotes are signals in addition to the words).
FOOTNOTE_TYPE = {
    "1": "sdk",
    "2": "electrical_rdv",
    "3": "shrubs_clemency_fingig",
    "4": "shrubs_bascharage_hautcharage_linger",
    "5": "bulky",
    "6": "christmas_trees",
}

# Type -> footnote key holding the German explanation.
TYPE_NOTE_KEY = {
    "sdk": "1",
    "electrical_rdv": "2",
    "shrubs_clemency_fingig": "3",
    "shrubs_bascharage_hautcharage_linger": "4",
    "bulky": "5",
    "christmas_trees": "6",
}

# Aliases on normalised text (lowercase, no whitespace). Order matters: longer first.
# Entry: (type key | "_shrubword" | None, regex)
ALIASES: list[tuple[str | None, str]] = [
    ("household", r"déchetsménagers"),
    ("household", r"d\.ménagers"),
    ("household", r"hausmüll"),
    ("household", r"haus\."),
    ("organic", r"déchetsorganiques"),
    ("organic", r"d\.organiques"),
    ("organic", r"bioabfall"),
    ("paper", r"altpapier"),
    ("paper", r"papiers"),
    ("paper", r"papier"),
    ("glass", r"verre"),
    ("glass", r"glas"),
    ("valorlux", r"valorlux"),
    ("valorlux", r"val\."),
    ("bulky", r"déchetsencombrants"),
    ("bulky", r"encombrants"),
    ("bulky", r"spermüll"),  # typo in the PDF
    ("bulky", r"sperrmüll"),
    ("bulky", r"sper\."),
    ("sdk", r"superdrecksk[eë]scht"),
    ("sdk", r"sdk®?"),
    ("electrical_rdv", r"déchetsélectriques"),
    ("electrical_rdv", r"d\.électr\."),
    ("electrical_rdv", r"elektroapparate"),
    ("christmas_trees", r"sapinsdenoël"),
    ("christmas_trees", r"sapins"),
    ("christmas_trees", r"weihnachtsbäume"),
    ("_shrubword", r"déchetsd[’']arbustes"),
    ("_shrubword", r"d\.arbustes"),
    ("_shrubword", r"arbustes"),
    ("_shrubword", r"heckenschnitt"),
    ("_shrubword", r"hecken\."),
    ("_shrubword", r"heck\."),
    ("_shrubword", r"arb\."),
    # filler tokens that carry no type of their own
    (None, r"surrdv"),
    (None, r"aufanfrage"),
    (None, r"rdv"),
]
_COMPILED_ALIASES = [(t, re.compile(rx)) for t, rx in ALIASES]
_FOOTNOTE_RE = re.compile(r"\(([1-6])\)")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def preprocess(text: str) -> str:
    """Insert hard line breaks around month headers if the PDF extraction glued them."""
    for mp in MONTH_PAIRS:
        text = re.sub(r"(?<!\n)" + re.escape(mp), "\n" + mp + "\n", text)
    return text


def normalize(desc: str) -> str:
    """NFC, lowercase, no whitespace."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", desc)).lower()


def classify(desc: str) -> list[str] | None:
    """Map a calendar cell to a list of type keys.

    Returns None for a holiday cell (contains "/" and no waste alias).
    Raises ValidationError if the cell is unknown or only partly understood.
    """
    n = normalize(desc)
    types: set[str] = set()
    shrubword = False
    matched_any = False

    def sub_marker(m: re.Match) -> str:
        nonlocal matched_any
        types.add(FOOTNOTE_TYPE[m.group(1)])
        matched_any = True
        return "|"

    n = _FOOTNOTE_RE.sub(sub_marker, n)
    for typ, rx in _COMPILED_ALIASES:
        if rx.search(n):
            if typ == "_shrubword":
                shrubword = True
            elif typ is not None:
                types.add(typ)
            matched_any = True
            n = rx.sub("|", n)

    residue = n.replace("|", "").replace("®", "")
    if not types and not shrubword and "/" in desc:
        return None  # holiday
    if residue:
        raise ValidationError(f"cell only partly understood (residue {residue!r}): {desc!r}")
    if shrubword and not (types & set(SHRUB_TYPES)):
        raise ValidationError(f"shrub cell without footnote (3)/(4): {desc!r}")
    if not types:
        raise ValidationError(f"unclassified cell: {desc!r}")
    return [t for t in TYPE_ORDER if t in types]


def parse_calendar_page(text: str, year: int) -> tuple[list[dict], set[int]]:
    """Parse one page. Returns (days, months_seen).

    Each day is {"date": date, "weekday": "Fr", "desc": "..."} (desc may be empty).
    """
    lines = [ln.strip() for ln in preprocess(text).splitlines() if ln.strip()]
    current_month: int | None = None
    months: set[int] = set()
    days: list[dict] = []
    for ln in lines:
        if any(ln.startswith(sm) for sm in STOP_MARKERS):
            break
        if ln in MONTH_MAP:
            current_month = MONTH_MAP[ln]
            months.add(current_month)
            continue
        m = DAY_RE.match(ln)
        if m and current_month:
            day = int(m.group(1))
            try:
                date = dt.date(year, current_month, day)
            except ValueError:
                raise ValidationError(f"invalid date {day}.{current_month}.{year}: {ln!r}")
            wd = m.group(2).split("/", 1)[1]
            days.append({"date": date, "weekday": wd, "desc": (m.group(3) or "").strip()})
    return days, months


def detect_year(pages: list[str]) -> int | None:
    years = set()
    for p in pages:
        m = re.search(r"(?:CALENDRIER|UMWELTKALENDER)[^\n]*?\b(\d{4})\b", p)
        if m:
            years.add(int(m.group(1)))
    if len(years) > 1:
        raise ValidationError(f"conflicting years in PDF titles: {sorted(years)}")
    return years.pop() if years else None


def build_events(days: list[dict]) -> list[dict]:
    """Check weekdays, classify cells, return sorted events (holidays ignored)."""
    events: list[dict] = []
    seen: set[dt.date] = set()
    for d in days:
        date = d["date"]
        expected = WEEKDAYS_DE[date.weekday()]
        if d["weekday"] != expected:
            raise ValidationError(
                f"weekday mismatch on {date.isoformat()}: PDF says {d['weekday']!r}, "
                f"calendar says {expected!r} (wrong --year?)"
            )
        if date in seen:
            raise ValidationError(f"date {date.isoformat()} appears twice in the PDF")
        seen.add(date)
        if not d["desc"]:
            continue
        try:
            types = classify(d["desc"])
        except ValidationError as e:
            raise ValidationError(f"{date.isoformat()}: {e}") from None
        if types is None:
            continue
        events.append({"date": date.isoformat(), "types": types, "raw": d["desc"]})
    events.sort(key=lambda e: e["date"])
    return events


def validate(events: list[dict], months: set[int]) -> list[str]:
    """Hard checks raise ValidationError; returns a list of warnings."""
    if not events:
        raise ValidationError("no collection events found")
    if months != set(range(1, 13)):
        missing = sorted(set(range(1, 13)) - months)
        raise ValidationError(f"not all 12 months found, missing: {missing}")
    warnings: list[str] = []
    for typ, minimum in (("glass", 12), ("paper", 12), ("household", 52)):
        n = sum(1 for e in events if typ in e["types"])
        if n < minimum:
            warnings.append(f"only {n} {typ} dates found (expected at least {minimum})")
    return warnings


def extract_footnotes(page_text: str) -> dict[str, str]:
    """Parse the German footnotes (1)-(6); returns {} if the block is not found."""
    try:
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        last_day = max(i for i, ln in enumerate(lines) if DAY_RE.match(ln))
        end = next(i for i in range(last_day + 1, len(lines)) if lines[i].startswith("Gemeindeverwaltung"))
        notes: dict[str, list[str]] = {}
        keys: list[str] = []
        for ln in lines[last_day + 1:end]:
            m = re.match(r"^((?:\(\d\))+)\s*(.*)$", ln)
            if m:
                keys = re.findall(r"\d", m.group(1))
                for k in keys:
                    notes[k] = [m.group(2)]
            elif keys:
                for k in keys:
                    notes[k].append(ln)
        out: dict[str, str] = {}
        for k, parts in notes.items():
            text = parts[0]
            for part in parts[1:]:
                if text.endswith("-") and len(text) > 1 and text[-2].isalpha():
                    text = text[:-1] + part
                elif text.endswith("Uhr"):
                    text += "\n" + part
                else:
                    text += " " + part
            out[k] = text.strip()
        return {k: out[k] for k in sorted(out)}
    except (ValueError, StopIteration):
        return {}


def parse_pdf_text(pages: list[str], year: int | None = None) -> tuple[int, list[dict], list[str], dict[str, str]]:
    """Pure core: page texts -> (year, events, warnings, notes). Raises ValidationError."""
    if year is None:
        year = detect_year(pages)
    if year is None:
        raise ValidationError("could not read the year from the PDF title; pass --year")
    days: list[dict] = []
    months: set[int] = set()
    for p in pages:
        d, m = parse_calendar_page(p, year)
        days.extend(d)
        months |= m
    events = build_events(days)
    warnings = validate(events, months)
    german = [p for p in pages if "UMWELTKALENDER" in p] or pages[-1:]
    notes = extract_footnotes(german[0]) if german else {}
    return year, events, warnings, notes


def read_pdf_pages(path: Path) -> list[str]:
    import pypdf  # lazy: the module stays importable without pypdf

    reader = pypdf.PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


# ---------------------------------------------------------------------------
# ICS
# ---------------------------------------------------------------------------

def _escape_text(value: str) -> str:
    r"""RFC 5545 TEXT escaping: backslash, semicolon, comma, newline."""
    v = value.replace("\r\n", "\n").replace("\r", "\n")
    v = v.replace("\\", "\\\\")
    v = v.replace(";", "\\;").replace(",", "\\,")
    v = v.replace("\n", "\\n")
    return v


def _fold_line(line: str, limit: int = 75) -> str:
    """Fold a content line to at most 75 octets per physical line (RFC 5545).

    Continuation lines start with one space, so they carry limit-1 octets of content.
    """
    line = line.rstrip(" ")  # a trailing space could end up alone on a continuation line
    chunks: list[str] = []
    cur_chars: list[str] = []
    cur_len = 0
    cur_limit = limit
    for ch in line:
        bl = len(ch.encode("utf-8"))
        if cur_len + bl > cur_limit:
            chunks.append("".join(cur_chars))
            cur_chars = [ch]
            cur_len = bl
            cur_limit = limit - 1
        else:
            cur_chars.append(ch)
            cur_len += bl
    if cur_chars:
        chunks.append("".join(cur_chars))
    if len(chunks) <= 1:
        return chunks[0] if chunks else ""
    return chunks[0] + "".join("\r\n " + c for c in chunks[1:])


def alarm_trigger(hhmm: str) -> str:
    """Trigger relative to the all-day start for HH:MM on the evening before."""
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", hhmm)
    if not m:
        raise ValueError(f"invalid alarm time {hhmm!r}, expected HH:MM")
    before = 24 * 60 - (int(m.group(1)) * 60 + int(m.group(2)))
    h, mi = divmod(before, 60)
    return "-PT" + (f"{h}H" if h else "") + (f"{mi}M" if mi else "")


def labels_for(locality: str | None) -> dict[str, str]:
    labels = dict(TYPE_LABEL)
    if locality:
        for k in SHRUB_TYPES:
            labels[k] = "Heckenschnitt"
    return labels


def filter_types(types: list[str], locality: str | None, exclude: set[str]) -> list[str]:
    out = []
    for t in types:
        if t in exclude:
            continue
        if locality and t in SHRUB_TYPES and t != LOCALITY_TYPE[locality]:
            continue
        out.append(t)
    return out


def build_ics(
    events: list[dict],
    notes: dict[str, str] | None = None,
    municipality: str = "Käerjeng",
    calname: str | None = None,
    uid_prefix: str = "kaerjeng-waste",
    alarm: str | None = "19:00",
    locality: str | None = None,
    exclude: set[str] | None = None,
) -> bytes:
    """Build the ICS from JSON-style events. Deterministic (no clock)."""
    notes = notes or {}
    exclude = exclude or set()
    labels = labels_for(locality)
    trigger = alarm_trigger(alarm) if alarm else None
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{municipality} Waste Calendar//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape_text(calname or 'Müllabfuhr ' + municipality)}",
    ]
    for ev in sorted(events, key=lambda e: e["date"]):
        date = dt.date.fromisoformat(ev["date"])
        dtstart = date.strftime("%Y%m%d")
        dtend = (date + dt.timedelta(days=1)).strftime("%Y%m%d")
        for typ in filter_types(ev["types"], locality, exclude):
            label = labels.get(typ, typ)
            descr = [f"Gemeinde: {municipality}"]
            if typ in ON_REQUEST_TYPES:
                descr.append("Abholung nur auf Anfrage")
            note = notes.get(TYPE_NOTE_KEY.get(typ, ""))
            if note:
                descr.append(note)
            ev_lines = [
                "BEGIN:VEVENT",
                f"UID:{uid_prefix}-{dtstart}-{typ}@waste-calendar",
                f"DTSTAMP:{date.year:04d}0101T000000Z",
                f"DTSTART;VALUE=DATE:{dtstart}",
                f"DTEND;VALUE=DATE:{dtend}",
                f"SUMMARY:{_escape_text(label)}",
                f"DESCRIPTION:{_escape_text(chr(10).join(descr))}",
                "TRANSP:TRANSPARENT",
            ]
            if trigger and typ not in ON_REQUEST_TYPES:
                ev_lines += [
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:{_escape_text(label)}",
                    f"TRIGGER:{trigger}",
                    "END:VALARM",
                ]
            ev_lines.append("END:VEVENT")
            lines.extend(_fold_line(l) for l in ev_lines)
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------

def write_json(path: Path, events: list[dict]) -> None:
    path.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "types", "raw"])
        for ev in events:
            w.writerow([ev["date"], "|".join(ev["types"]), ev["raw"]])


def merge_year_files(outdir: Path, name: str) -> tuple[list[dict], dict[str, str]]:
    """Merge all <name>_YYYY.json (and .notes.json) in outdir; sorted, later years win."""
    pat = re.compile(re.escape(name) + r"_(\d{4})\.json")
    files = sorted(p for p in outdir.iterdir() if pat.fullmatch(p.name))
    by_date: dict[str, dict] = {}
    notes: dict[str, str] = {}
    for p in files:
        for ev in json.loads(p.read_text(encoding="utf-8")):
            by_date[ev["date"]] = ev
        np_ = p.with_name(p.stem + ".notes.json")
        if np_.exists():
            try:
                notes.update(json.loads(np_.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
    return [by_date[d] for d in sorted(by_date)], notes


def write_outputs(
    outdir: Path,
    name: str,
    year: int,
    events: list[dict],
    notes: dict[str, str],
    ics_kwargs: dict,
) -> tuple[int, int]:
    """Write per-year files and the merged year-less files. Returns (year ics events, merged ics events)."""
    outdir.mkdir(parents=True, exist_ok=True)
    base = outdir / f"{name}_{year}"
    write_json(base.with_suffix(".json"), events)
    write_csv(base.with_suffix(".csv"), events)
    base.with_suffix(".notes.json").write_text(
        json.dumps(notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    year_ics = build_ics(events, notes, **ics_kwargs)
    base.with_suffix(".ics").write_bytes(year_ics)

    merged, merged_notes = merge_year_files(outdir, name)
    write_json(outdir / f"{name}.json", merged)
    write_csv(outdir / f"{name}.csv", merged)
    merged_ics = build_ics(merged, merged_notes, **ics_kwargs)
    (outdir / f"{name}.ics").write_bytes(merged_ics)
    return year_ics.count(b"BEGIN:VEVENT"), merged_ics.count(b"BEGIN:VEVENT")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _alarm_arg(value: str) -> str:
    try:
        alarm_trigger(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))
    return value


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Convert the SIDOR Käerjeng waste calendar PDF to JSON, CSV and ICS.")
    ap.add_argument("pdf", type=Path, help="Path to the calendar PDF.")
    ap.add_argument("--outdir", type=Path, default=Path("."), help="Output directory (default: .).")
    ap.add_argument("--year", type=int, help="Override the year read from the PDF title.")
    ap.add_argument("--name", default="kaerjeng_waste", help="File name prefix (default: kaerjeng_waste).")
    ap.add_argument("--municipality", default="Käerjeng", help="Municipality name (default: Käerjeng).")
    ap.add_argument("--locality", choices=sorted(LOCALITY_TYPE), help="ICS only: keep only this locality's shrub collection.")
    ap.add_argument("--exclude", nargs="+", choices=TYPE_ORDER, default=[], metavar="TYPE",
                    help="ICS only: drop these type keys (" + ", ".join(TYPE_ORDER) + ").")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--alarm", type=_alarm_arg, default="19:00", metavar="HH:MM",
                   help="Reminder time on the evening before (default: 19:00).")
    g.add_argument("--no-alarm", action="store_true", help="Do not add reminders.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        try:
            pages = read_pdf_pages(args.pdf)
        except ImportError:
            raise
        except Exception as e:  # unreadable or non-PDF input
            raise ValidationError(f"cannot read PDF {args.pdf}: {e}") from e
        year, events, warnings, notes = parse_pdf_text(pages, args.year)
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    ics_kwargs = dict(
        municipality=args.municipality,
        uid_prefix=args.name.replace("_", "-"),
        alarm=None if args.no_alarm else args.alarm,
        locality=args.locality,
        exclude=set(args.exclude),
    )
    n_year, _ = write_outputs(args.outdir, args.name, year, events, notes, ics_kwargs)
    print(f"{len(events)} days with collection, {n_year} ICS events, output: {args.outdir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
