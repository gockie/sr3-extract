"""
Tests for extract_sr3.py.

These build small synthetic SR3 (HDF5) files and CMG .dat decks on the fly and
exercise the public functions: formation detection, the .dat duration parser,
component-by-name mapping, the completeness logic, and a full extraction.

Run with:  pytest
"""

import os
import sys
import datetime

import numpy as np
import h5py
import openpyxl
import pytest

# Make extract_sr3.py importable whether tests are run from the repo root or
# from the tests/ directory.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import extract_sr3 as ex


# ---------------------------------------------------------------------------
# Helpers to build synthetic inputs
# ---------------------------------------------------------------------------
def _nrec(names):
    """Encode names the way CMG stores them, e.g. (b'NAME',)."""
    return np.array(["(b'%s',)" % n for n in names], dtype=h5py.string_dtype())


def make_sr3(path, components, well_vars, sector_vars, ntimes, end_days,
             producer="Producer", injector="Injector"):
    """Write a minimal SR3-like HDF5 file spanning 0..end_days over ntimes rows."""
    start = datetime.date(2000, 1, 1)
    with h5py.File(path, "w") as f:
        g = f.create_group("General")
        mtt = np.zeros((ntimes, 3))
        for i in range(ntimes):
            frac = i / (ntimes - 1) if ntimes > 1 else 1.0
            day = frac * end_days
            d = start + datetime.timedelta(days=day)
            mtt[i, 0] = i
            mtt[i, 1] = day
            mtt[i, 2] = float("%d%02d%02d" % (d.year, d.month, d.day))
        g.create_dataset("MasterTimeTable", data=mtt)
        g.create_dataset("ComponentTable", data=_nrec(components))

        ts = f.create_group("TimeSeries")
        w = ts.create_group("WELLS")
        w.create_dataset("Origins", data=_nrec([producer, injector]))
        w.create_dataset("Variables", data=_nrec(well_vars))
        w.create_dataset("Timesteps", data=np.arange(ntimes))
        wd = np.zeros((ntimes, len(well_vars), 2))
        for vi in range(len(well_vars)):
            wd[:, vi, 0] = vi * 10.0 + 1.0   # producer (origin 0)
            wd[:, vi, 1] = vi * 100.0 + 1.0  # injector (origin 1)
        w.create_dataset("Data", data=wd)

        s = ts.create_group("SECTORS")
        s.create_dataset("Origins", data=_nrec(["MATRIX", "FRACTURE", "FIELD"]))
        s.create_dataset("Variables", data=_nrec(sector_vars))
        s.create_dataset("Timesteps", data=np.arange(ntimes))
        sd = np.zeros((ntimes, len(sector_vars), 3))
        for vi in range(len(sector_vars)):
            sd[:, vi, 2] = vi + 1.0  # FIELD (origin 2)
        s.create_dataset("Data", data=sd)


def make_dat(path, end_year):
    """Write a CMG deck with monthly DATE keywords from 2000-01-01 to end_year-01-01."""
    with open(path, "w") as fh:
        fh.write("** synthetic deck\nDATE 2000 1 1\n")
        for y in range(2000, end_year + 1):
            for m in range(1, 13):
                if y == 2000 and m == 1:
                    continue
                if y == end_year and m > 1:
                    break
                fh.write("DATE %d %d  1.00000\n" % (y, m))
        fh.write("STOP\n")


DUVY_COMPS = ["CH4", "CO2", "tracer", "WATER"]
DUVY_WELL = ["GASVOLSC", "OILVOLSC", "GASRATSC", "OILRATSC",
             "GASCMOLSC(1)", "GASCMOLSC(2)", "GASCMOLSC(3)"]
DUVY_SEC = ["PRSCUMSEC", "GASADSMOL(1)", "GASADSMOL(2)", "GASADSMOL(3)"]


# ---------------------------------------------------------------------------
# Formation detection
# ---------------------------------------------------------------------------
def test_detect_formation_by_prefix():
    assert ex.detect_formation("BAKN_Scenario_0001.sr3") == "BAKN"
    assert ex.detect_formation("DUVY_Scenario_0800.sr3") == "DUVY"
    assert ex.detect_formation("MONT_x.sr3") == "MONT"
    assert ex.detect_formation("HRNR_1.sr3") == "HRNR"


def test_detect_formation_unknown():
    assert ex.detect_formation("RANDOM_0001.sr3") is None


# ---------------------------------------------------------------------------
# .dat project-duration parser
# ---------------------------------------------------------------------------
def test_parse_dat_target_days(tmp_path):
    dat = tmp_path / "case.dat"
    make_dat(str(dat), 2050)  # 2000-01-01 to 2050-01-01
    assert ex.parse_dat_target_days(str(dat)) == 18263


def test_parse_dat_missing_returns_none(tmp_path):
    assert ex.parse_dat_target_days(str(tmp_path / "nope.dat")) is None


# ---------------------------------------------------------------------------
# Completeness logic
# ---------------------------------------------------------------------------
def test_completeness_complete():
    is_complete, shortfall = ex.completeness(18263, 18263, 0.999)
    assert is_complete is True
    assert shortfall == 0.0


def test_completeness_incomplete():
    is_complete, shortfall = ex.completeness(12045, 18263, 0.999)
    assert is_complete is False
    assert shortfall == pytest.approx(6218, abs=1)


def test_completeness_unknown_target():
    is_complete, shortfall = ex.completeness(10000, None, 0.999)
    assert is_complete is None


# ---------------------------------------------------------------------------
# Component-by-name mapping (index order differs between decks)
# ---------------------------------------------------------------------------
def test_component_mapping_by_name(tmp_path):
    # Here CO2 is component 2; a BAKN-style deck would have CO2 at index 6.
    sr3 = tmp_path / "DUVY_x.sr3"
    make_sr3(str(sr3), DUVY_COMPS, DUVY_WELL, DUVY_SEC, ntimes=10, end_days=100)
    with h5py.File(str(sr3), "r") as f:
        comp_idx, _ = ex.component_index_map(f)
    assert comp_idx["CH4"] == 1
    assert comp_idx["CO2"] == 2
    assert ex.resolve_key(("GASADSMOL", "CO2"), comp_idx) == "GASADSMOL(2)"
    assert ex.resolve_key(("GASADSMOL", "CH4"), comp_idx) == "GASADSMOL(1)"


# ---------------------------------------------------------------------------
# Full extraction: columns and row count
# ---------------------------------------------------------------------------
def test_extract_duvy_columns(tmp_path):
    sr3 = tmp_path / "DUVY_Scenario_0800.sr3"
    make_sr3(str(sr3), DUVY_COMPS, DUVY_WELL, DUVY_SEC, ntimes=689, end_days=18263)
    out = tmp_path / "out.xlsx"
    n, final_day = ex.extract_one(str(sr3), str(out), "DUVY",
                                  "Injector", "Producer", "FIELD")
    assert n == 689
    assert final_day == pytest.approx(18263, abs=1)

    ws = openpyxl.load_workbook(str(out))["Data"]
    header = [c.value for c in next(ws.iter_rows(max_row=1))]
    assert header == [
        "Time (day)", "Date",
        "Injector-Cumulative Gas SC (m3)",
        "Producer-Cumulative Gas SC (m3)",
        "Injector-Gas Rate SC (m3/day)",
        "Producer-Gas Rate SC (m3/day)",
        "FIELD-Ave Pres POVO SCTR (kPa)",
        "FIELD-Gas Adsorbed Moles SCTR(CH4) (gmole)",
        "FIELD-Gas Adsorbed Moles SCTR(CO2) (gmole)",
    ]


def test_extract_hrnr_has_eleven_columns(tmp_path):
    sr3 = tmp_path / "HRNR_Scenario_0001.sr3"
    make_sr3(str(sr3), DUVY_COMPS, DUVY_WELL, DUVY_SEC, ntimes=631, end_days=18263)
    out = tmp_path / "out.xlsx"
    n, _ = ex.extract_one(str(sr3), str(out), "HRNR",
                          "Injector", "Producer", "FIELD")
    ws = openpyxl.load_workbook(str(out))["Data"]
    header = [c.value for c in next(ws.iter_rows(max_row=1))]
    assert len(header) == 11
    assert "Producer-Cumulative Gas Moles(CH4) SC (gmole)" in header
    assert "Producer-Cumulative Gas Moles(CO2) SC (gmole)" in header


# ---------------------------------------------------------------------------
# Folder-level duration sampling
# ---------------------------------------------------------------------------
def test_determine_folder_target_agrees(tmp_path):
    sr3s = []
    for name in ["DUVY_A", "DUVY_B"]:
        p = tmp_path / (name + ".sr3")
        make_sr3(str(p), DUVY_COMPS, DUVY_WELL, DUVY_SEC, 10, 18263)
        make_dat(str(tmp_path / (name + ".dat")), 2050)
        sr3s.append(str(p))
    target, info = ex.determine_folder_target(str(tmp_path), sr3s, sample=3)
    assert info["mode"] == "folder"
    assert target == 18263


def test_determine_folder_target_mixed(tmp_path):
    make_sr3(str(tmp_path / "DUVY_A.sr3"), DUVY_COMPS, DUVY_WELL, DUVY_SEC, 10, 18263)
    make_dat(str(tmp_path / "DUVY_A.dat"), 2050)   # 50 years
    make_sr3(str(tmp_path / "DUVY_B.sr3"), DUVY_COMPS, DUVY_WELL, DUVY_SEC, 10, 7305)
    make_dat(str(tmp_path / "DUVY_B.dat"), 2020)   # 20 years
    sr3s = [str(tmp_path / "DUVY_A.sr3"), str(tmp_path / "DUVY_B.sr3")]
    target, info = ex.determine_folder_target(str(tmp_path), sr3s, sample=3)
    assert info["mode"] == "mixed"
    assert target is None


def test_check_missing_sims(tmp_path):
    # A .dat with a matching .sr3, and one without.
    make_sr3(str(tmp_path / "DUVY_A.sr3"), DUVY_COMPS, DUVY_WELL, DUVY_SEC, 10, 100)
    make_dat(str(tmp_path / "DUVY_A.dat"), 2050)
    make_dat(str(tmp_path / "DUVY_B.dat"), 2050)  # no .sr3
    missing = ex.check_missing_sims(str(tmp_path))
    assert missing == ["DUVY_B"]
