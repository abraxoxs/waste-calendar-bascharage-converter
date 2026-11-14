import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import waste_calendar as wc  # noqa: E402

PDF = ROOT / "input" / "22285_SIDOR_calendrier_2026.pdf"

REAL_CELLS = {
    "Déchets électriques sur RDV (2)": ["electrical_rdv"],
    "D. électr. RDV (2)  SDK® (1)": ["sdk", "electrical_rdv"],
    "Valorlux Encombrants (5)": ["valorlux", "bulky"],
    "Verre D. arbustes (3)": ["glass", "shrubs_clemency_fingig"],
    "Papiers D. arbustes (4)": ["paper", "shrubs_bascharage_hautcharage_linger"],
    "D. ménagers D. organiques": ["household", "organic"],
    "Déchets ménagers": ["household"],
    "Sapins de Noël": ["christmas_trees"],
    "D. électr. RDV (2) Sapins de Noël": ["electrical_rdv", "christmas_trees"],
    "Verre Val. Arb . (3) Sapins": ["glass", "valorlux", "christmas_trees", "shrubs_clemency_fingig"],
    "Papiers Valorlux Arb.  (4)": ["paper", "valorlux", "shrubs_bascharage_hautcharage_linger"],
    "Valorlux Verre": ["glass", "valorlux"],
    "Valorlux Papiers": ["paper", "valorlux"],
    "SDK® (1)": ["sdk"],
    "Encombrants (5)": ["bulky"],
    "Elektroapparate auf Anfrage (2)": ["electrical_rdv"],
    "Hausmüll Bioabfall": ["household", "organic"],
    "Glas Valorlux": ["glass", "valorlux"],
    "Altpapier Valorlux": ["paper", "valorlux"],
    "Spermüll(5) Valorlux": ["valorlux", "bulky"],
    "Spermüll(5)": ["bulky"],
    "Sper. (5)": ["bulky"],
    "Valorlux Sper. (5) Hecken. (3)": ["valorlux", "bulky", "shrubs_clemency_fingig"],
    "Valorlux Hecken. (4)": ["valorlux", "shrubs_bascharage_hautcharage_linger"],
    "Valorlux Glas Hecken. (3)": ["glass", "valorlux", "shrubs_clemency_fingig"],
    "Valorlux AltpapierHecken. (4)": ["paper", "valorlux", "shrubs_bascharage_hautcharage_linger"],
    "Val. Glas Heck. (3)SDK® (1)": ["glass", "valorlux", "sdk", "shrubs_clemency_fingig"],
    "Val.GlasHeck. (3)SDK® (1)": ["glass", "valorlux", "sdk", "shrubs_clemency_fingig"],
    "Haus. Val. Papier Heck.(4)": ["household", "paper", "valorlux", "shrubs_bascharage_hautcharage_linger"],
    "Valorlux  SDK® (1)": ["valorlux", "sdk"],
    "Hausmüll": ["household"],
}

HOLIDAYS = [
    "Jour de l’an/Neujahr",
    "L. de Pâques/Ostermontag",
    "Noël/1. Weihnachtsfeiertag",
    "St Etienne/2. Weihnachtsfeiertag",
    "Fête Nationale/Nationalfeiertag",
]


@pytest.mark.parametrize("cell,expected", list(REAL_CELLS.items()))
def test_classify_real_cells(cell, expected):
    assert sorted(wc.classify(cell)) == sorted(expected)


@pytest.mark.parametrize("cell", HOLIDAYS)
def test_holidays_ignored(cell):
    assert wc.classify(cell) is None


def test_unknown_cell_is_error():
    with pytest.raises(wc.ValidationError):
        wc.classify("Mystery bin")


def test_partly_understood_cell_is_error():
    with pytest.raises(wc.ValidationError, match="partly"):
        wc.classify("Hausmüll Blumenabfuhr")


@pytest.mark.parametrize("line", ["13ven/Fr D. ménagers D. organiques", "13 ven/Fr D. ménagers D. organiques"])
def test_day_line_with_and_without_space(line):
    text = "Février/Februar\n" + line + "\n"
    days, months = wc.parse_calendar_page(text, 2026)
    assert months == {2}
    assert days == [{"date": wc.dt.date(2026, 2, 13), "weekday": "Fr", "desc": "D. ménagers D. organiques"}]


def _full_year_pages(year=2026, weekday_override=None):
    """Synthetic PDF text: every day of the year, Thursdays glass, Fridays household."""
    pages = []
    for half, title in ((range(1, 7), f"CALENDRIER ÉCO-RESPONSABLE {year}"),
                        (range(7, 13), f"UMWELTKALENDER {year}")):
        lines = [title]
        for month in half:
            lines.append(wc.MONTH_PAIRS[month - 1])
            d = wc.dt.date(year, month, 1)
            while d.month == month:
                wd = wc.WEEKDAYS_DE[d.weekday()]
                cell = {3: "Glas", 4: "Hausmüll"}.get(d.weekday(), "")
                lines.append(f"{d.day} xxx/{wd} {cell}".rstrip())
                d += wc.dt.timedelta(days=1)
        lines += ["(1) SuperDreckskëscht", "Ort: Test", "Gemeindeverwaltung"]
        pages.append("\n".join(lines))
    return pages


def test_synthetic_pages_parse():
    year, events, warnings, notes = wc.parse_pdf_text(_full_year_pages())
    assert year == 2026
    assert len(events) == 52 + 52 or len(events) > 100
    assert notes == {"1": "SuperDreckskëscht Ort: Test"}


def test_validation_zero_events():
    with pytest.raises(wc.ValidationError, match="no collection"):
        wc.validate([], set(range(1, 13)))


def test_validation_missing_months():
    ev = [{"date": "2026-01-02", "types": ["household"], "raw": "Hausmüll"}]
    with pytest.raises(wc.ValidationError, match="12 months"):
        wc.validate(ev, {1, 2})


def test_validation_warnings():
    ev = [{"date": "2026-01-02", "types": ["household"], "raw": "Hausmüll"}]
    w = wc.validate(ev, set(range(1, 13)))
    assert any("glass" in x for x in w) and any("paper" in x for x in w) and any("household" in x for x in w)


def test_validation_wrong_weekday():
    pages = _full_year_pages()
    pages[0] = pages[0].replace("2 xxx/Fr", "2 xxx/Mo", 1)
    with pytest.raises(wc.ValidationError, match="weekday mismatch"):
        wc.parse_pdf_text(pages)


def test_wrong_year_override_fails_weekday_check():
    with pytest.raises(wc.ValidationError, match="weekday mismatch"):
        wc.parse_pdf_text(_full_year_pages(), year=2027)


def test_validation_unknown_cell():
    pages = _full_year_pages()
    pages[0] = pages[0].replace("2 xxx/Fr Hausmüll", "2 xxx/Fr Hausmüll Quatsch", 1)
    with pytest.raises(wc.ValidationError, match="2026-01-02"):
        wc.parse_pdf_text(pages)


def test_year_from_title():
    assert wc.detect_year(["CALENDRIER ÉCO-RESPONSABLE 2031\nfoo"]) == 2031
    assert wc.detect_year(["nothing"]) is None


EVENTS = [
    {"date": "2026-01-02", "types": ["household", "organic"], "raw": "D. ménagers D. organiques"},
    {"date": "2026-02-19", "types": ["valorlux", "bulky"], "raw": "Valorlux Encombrants (5)"},
    {"date": "2026-03-12", "types": ["glass", "valorlux", "sdk", "shrubs_clemency_fingig"], "raw": "x"},
    {"date": "2026-04-23", "types": ["paper", "shrubs_bascharage_hautcharage_linger"], "raw": "y"},
    {"date": "2026-05-06", "types": ["electrical_rdv"], "raw": "z"},
]
NOTES = {"1": "SDK-Text " * 30, "5": "Sperrmüll-Text; mit, Zeichen"}


def _unfold(data: bytes) -> list[str]:
    return data.decode("utf-8").replace("\r\n ", "").split("\r\n")


def _vevents(data: bytes) -> list[list[str]]:
    out, cur = [], None
    for ln in _unfold(data):
        if ln == "BEGIN:VEVENT":
            cur = []
        elif ln == "END:VEVENT":
            out.append(cur)
            cur = None
        elif cur is not None:
            cur.append(ln)
    return out


def test_ics_format():
    data = wc.build_ics(EVENTS, NOTES)
    assert data.endswith(b"\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")
    for phys in data.decode("utf-8").split("\r\n")[:-1]:
        assert len(phys.encode("utf-8")) <= 75
        assert phys.strip() != "" or phys == ""
        assert phys != " "
    assert "\r\n \r\n" not in data.decode("utf-8")
    assert "X-WR-CALNAME:" in data.decode("utf-8")


def test_ics_one_vevent_per_type_with_fixed_labels_and_unique_uids():
    data = wc.build_ics(EVENTS, NOTES)
    vevents = _vevents(data)
    assert len(vevents) == sum(len(e["types"]) for e in EVENTS)
    summaries = {next(l for l in v if l.startswith("SUMMARY:"))[8:] for v in vevents}
    assert summaries <= set(wc.TYPE_LABEL.values())
    uids = [next(l for l in v if l.startswith("UID:")) for v in vevents]
    assert len(set(uids)) == len(uids)
    assert "UID:kaerjeng-waste-20260219-bulky@waste-calendar" in uids
    assert all("TRANSP:TRANSPARENT" in v for v in vevents)
    assert all("DTSTAMP:20260101T000000Z" in v for v in vevents)


def test_ics_deterministic():
    assert wc.build_ics(EVENTS, NOTES) == wc.build_ics(EVENTS, NOTES)


def test_ics_alarm_default_custom_none_and_on_request():
    def alarms(data):
        res = {}
        for v in _vevents(data):
            uid = next(l for l in v if l.startswith("UID:"))
            m = re.match(r"UID:kaerjeng-waste-(\d+)-(\w+)@", uid)
            res[m.group(1) + "-" + m.group(2)] = [l for l in v if l.startswith("TRIGGER")]
        return res

    default = alarms(wc.build_ics(EVENTS))
    assert default["20260102-household"] == ["TRIGGER:-PT5H"]
    assert default["20260219-bulky"] == []
    assert default["20260506-electrical_rdv"] == []
    assert alarms(wc.build_ics(EVENTS, alarm="18:30"))["20260102-household"] == ["TRIGGER:-PT5H30M"]
    assert all(v == [] for v in alarms(wc.build_ics(EVENTS, alarm=None)).values())
    valarm = [v for v in _vevents(wc.build_ics(EVENTS)) if "BEGIN:VALARM" in v][0]
    assert "ACTION:DISPLAY" in valarm


def test_ics_description_has_footnote_and_on_request_note():
    text = wc.build_ics(EVENTS, NOTES).decode("utf-8").replace("\r\n ", "")
    assert "Sperrmüll-Text\\; mit\\, Zeichen" in text
    assert "auf Anfrage" in text


def test_ics_locality_and_exclude_filters():
    labels = lambda d: [l[8:] for v in _vevents(d) for l in v if l.startswith("SUMMARY:")]
    d = wc.build_ics(EVENTS, locality="fingig")
    assert labels(d).count("Heckenschnitt") == 1
    assert not any("Bascharage" in l for l in labels(d))
    d = wc.build_ics(EVENTS)
    assert "Heckenschnitt Clemency/Fingig" in labels(d)
    assert "Heckenschnitt Bascharage/Hautcharage/Linger" in labels(d)
    d = wc.build_ics(EVENTS, exclude={"electrical_rdv", "glass"})
    assert "Elektrogeräte" not in labels(d) and "Glas" not in labels(d)


def test_fold_never_emits_blank_continuation():
    for n in range(60, 160):
        folded = wc._fold_line("DESCRIPTION:" + "ä " * n)
        for phys in folded.split("\r\n"):
            assert len(phys.encode("utf-8")) <= 75
        assert "\r\n \r\n" not in folded and not folded.endswith("\r\n ")


def test_merge_two_years(tmp_path):
    (tmp_path / "x_2027.json").write_text(json.dumps([{"date": "2027-01-04", "types": ["glass"], "raw": "Glas"}]))
    (tmp_path / "x_2026.json").write_text(json.dumps([{"date": "2026-12-17", "types": ["bulky"], "raw": "S"}]))
    (tmp_path / "x_2026.notes.json").write_text(json.dumps({"5": "n"}))
    (tmp_path / "other_2026.json").write_text("[]")
    merged, notes = wc.merge_year_files(tmp_path, "x")
    assert [e["date"] for e in merged] == ["2026-12-17", "2027-01-04"]
    assert notes == {"5": "n"}


def test_failed_validation_leaves_outputs_untouched(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    out.mkdir()
    sentinel = out / "kaerjeng_waste_2026.json"
    sentinel.write_text("SENTINEL")
    other = out / "kaerjeng_waste.ics"
    other.write_text("SENTINEL2")
    pages = _full_year_pages()
    pages[0] = pages[0].replace("2 xxx/Fr", "2 xxx/Mo", 1)
    monkeypatch.setattr(wc, "read_pdf_pages", lambda p: pages)
    rc = wc.main([str(tmp_path / "fake.pdf"), "--outdir", str(out)])
    assert rc != 0
    assert "weekday mismatch" in capsys.readouterr().err
    assert sentinel.read_text() == "SENTINEL" and other.read_text() == "SENTINEL2"
    assert sorted(p.name for p in out.iterdir()) == ["kaerjeng_waste.ics", "kaerjeng_waste_2026.json"]


def test_main_with_synthetic_pages_writes_all_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wc, "read_pdf_pages", lambda p: _full_year_pages())
    rc = wc.main(["fake.pdf", "--outdir", str(tmp_path), "--no-alarm"])
    assert rc == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted([
        "kaerjeng_waste.csv", "kaerjeng_waste.ics", "kaerjeng_waste.json",
        "kaerjeng_waste_2026.csv", "kaerjeng_waste_2026.ics", "kaerjeng_waste_2026.json",
        "kaerjeng_waste_2026.notes.json",
    ])
    assert "VALARM" not in (tmp_path / "kaerjeng_waste.ics").read_text()
    assert "days with collection" in capsys.readouterr().out


@pytest.mark.skipif(not PDF.exists(), reason="real PDF not available")
def test_end_to_end_real_pdf(tmp_path):
    pytest.importorskip("pypdf")
    rc = wc.main([str(PDF), "--outdir", str(tmp_path)])
    assert rc == 0
    events = json.loads((tmp_path / "kaerjeng_waste_2026.json").read_text(encoding="utf-8"))
    assert len(events) == 147
    assert events[0]["date"] == "2026-01-02"
    dates = lambda t: [e["date"] for e in events if t in e["types"]]
    assert dates("bulky") == ["2026-02-19", "2026-04-16", "2026-06-18", "2026-08-20", "2026-10-15", "2026-12-17"]
    assert len(dates("glass")) == 12
    assert len(dates("paper")) == 12
    assert [e["date"] for e in events] == sorted(e["date"] for e in events)
    assert json.loads((tmp_path / "kaerjeng_waste.json").read_text(encoding="utf-8")) == events
    notes = json.loads((tmp_path / "kaerjeng_waste_2026.notes.json").read_text(encoding="utf-8"))
    assert set(notes) == {"1", "2", "3", "4", "5", "6"}
    ics = (tmp_path / "kaerjeng_waste.ics").read_bytes()
    assert ics == (tmp_path / "kaerjeng_waste.ics").read_bytes()
    assert b"UID:kaerjeng-waste-20261217-bulky@waste-calendar" in ics
    assert b"BEGIN:VALARM" in ics
    # second run is byte-identical
    first = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert wc.main([str(PDF), "--outdir", str(tmp_path)]) == 0
    assert first == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    for line in ics.decode("utf-8").split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
