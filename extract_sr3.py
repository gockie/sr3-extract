"""
extract_sr3.py  (formation-aware, lean, memory-safe)
----------------------------------------------------
Batch-extract target time-series parameters from CMG SR3 files into one Excel
workbook per input file (named to match the source .sr3).

FORMATION-AWARE: the formation is read from a keyword in each filename and
decides which parameters are extracted:

    BAKN  (Bakken)      gas + oil, no adsorption          -> 9 columns
    DUVY  (Duvernay)    gas + adsorbed moles, no oil      -> 9 columns
    MONT  (Montney)     same as Duvernay                  -> 9 columns
    HRNR  (Horn River)  gas + producer component moles
                        + adsorbed moles                  -> 11 columns

Reads ONLY the datasets it needs directly from each file, so it uses little
memory and runs on 32-bit or low-memory PCs. Needs only: h5py, numpy, pandas,
openpyxl. It does NOT need sr3_reader.py.

REPORT also covers:
  * Missing simulations: every .dat in the folder is checked for a matching
    .sr3. A .dat with no .sr3 is reported as a run that was not completed.
  * Suspicious results: a spreadsheet is flagged (and still written) if EITHER
      - it has fewer than 600 rows (the primary, human-readable signal), OR
      - its final Time (day) does not reach the end of the project.
    The project duration is read from the CMG .dat deck: the span from the
    first DATE keyword to the last DATE keyword (the full provided time). All
    cases in a folder normally share one duration, so only 2-3 .dat files are
    sampled once; if they disagree, each case is checked against its own .dat.
    A run that stalls on convergence can still have many rows while stopping
    years early, so the final-day check catches what the row count alone misses.
  * Unknown formation: a filename with no BAKN/DUVY/MONT/HRNR keyword is
    reported and skipped so nothing is mis-extracted.

A note on "failed" vs "suspicious": FAILED means the spreadsheet could not be
produced at all (corrupt file, missing key). SUSPICIOUS means it was produced
but a check says verify it (low rows, or an incomplete run). Incomplete runs
are suspicious, not failed, because the partial data is still written.

USAGE
-----
Put this file in the folder with your .sr3 (and .dat) files and run:
    py extract_sr3.py
It finds every .sr3, writes one spreadsheet per file into an "extracted_xlsx"
subfolder, and writes a report .txt there.

Options:
    py extract_sr3.py --indir "C:\\path\\to\\files"
    py extract_sr3.py --outdir "C:\\path\\to\\output"
    py extract_sr3.py --glob "*.sr3"
    py extract_sr3.py file1.sr3 file2.sr3
    --injector NAME     injector well name (default: auto-detect / "Injector")
    --producer NAME     producer well name (default: auto-detect / "Producer")
    --sector  NAME      sector for field values (default: "FIELD")
    --min-rows N        row-count flag threshold (default: 600)
    --complete-frac F   final day must reach this fraction of project duration
                        to count as complete (default: 0.999)
    --project-days D    override the project duration instead of reading .dat
"""

import sys
import os
import gc
import glob as globmod
import argparse
import math
import datetime as _dt

import numpy as np
import pandas as pd
import h5py


SUSPICIOUS_MIN_ROWS = 600

# ---------------------------------------------------------------------------
# Formation profiles
# ---------------------------------------------------------------------------
# Each column is described by:
#   label  : exact output header
#   group  : "WELLS" or "SECTORS"
#   origin : "injector" | "producer" | "sector"  (resolved to real names later)
#   key    : CMG variable name, OR a ("GASADSMOL", "CH4") / ("GASCMOLSC","CO2")
#            tuple meaning "this component-indexed key, component matched BY NAME"
#
# Component keys are matched by component NAME (CH4, CO2), because the index
# order differs between formations (e.g. BAKN CO2 = index 6, DUVY CO2 = index 2).

# shared building blocks
INJ_CUMGAS  = ("Injector-Cumulative Gas SC (m3)",        "WELLS",   "injector", "GASVOLSC")
PRO_CUMGAS  = ("Producer-Cumulative Gas SC (m3)",        "WELLS",   "producer", "GASVOLSC")
PRO_CUMOIL  = ("Producer-Cumulative Oil SC (m3)",        "WELLS",   "producer", "OILVOLSC")
INJ_GASRATE = ("Injector-Gas Rate SC (m3/day)",          "WELLS",   "injector", "GASRATSC")
PRO_GASRATE = ("Producer-Gas Rate SC (m3/day)",          "WELLS",   "producer", "GASRATSC")
PRO_OILRATE = ("Producer-Oil Rate SC (m3/day)",          "WELLS",   "producer", "OILRATSC")
FIELD_PRES  = ("FIELD-Ave Pres POVO SCTR (kPa)",         "SECTORS", "sector",   "PRSCUMSEC")
FIELD_ADS_CH4 = ("FIELD-Gas Adsorbed Moles SCTR(CH4) (gmole)", "SECTORS", "sector", ("GASADSMOL", "CH4"))
FIELD_ADS_CO2 = ("FIELD-Gas Adsorbed Moles SCTR(CO2) (gmole)", "SECTORS", "sector", ("GASADSMOL", "CO2"))
PRO_GMOL_CH4  = ("Producer-Cumulative Gas Moles(CH4) SC (gmole)", "WELLS", "producer", ("GASCMOLSC", "CH4"))
PRO_GMOL_CO2  = ("Producer-Cumulative Gas Moles(CO2) SC (gmole)", "WELLS", "producer", ("GASCMOLSC", "CO2"))

PROFILES = {
    "BAKN": [
        INJ_CUMGAS, PRO_CUMGAS, PRO_CUMOIL,
        INJ_GASRATE, PRO_GASRATE, PRO_OILRATE,
        FIELD_PRES,
    ],
    "DUVY": [
        INJ_CUMGAS, PRO_CUMGAS,
        INJ_GASRATE, PRO_GASRATE,
        FIELD_PRES, FIELD_ADS_CH4, FIELD_ADS_CO2,
    ],
    "MONT": [
        INJ_CUMGAS, PRO_CUMGAS,
        INJ_GASRATE, PRO_GASRATE,
        FIELD_PRES, FIELD_ADS_CH4, FIELD_ADS_CO2,
    ],
    "HRNR": [
        INJ_CUMGAS, PRO_CUMGAS,
        INJ_GASRATE, PRO_GASRATE,
        PRO_GMOL_CH4, PRO_GMOL_CO2,
        FIELD_PRES, FIELD_ADS_CH4, FIELD_ADS_CO2,
    ],
}

# Component name matching: accept common spellings for CH4 and CO2.
COMPONENT_ALIASES = {
    "CH4": ["CH4", "C1", "METHANE"],
    "CO2": ["CO2", "CARBON DIOXIDE"],
}


def detect_formation(filename):
    """Pick the formation from the filename.

    Files are named like 'BAKN_Scenario_0875.sr3', so the keyword is matched at
    the START of the name first (the reliable case). Only if no name starts with
    a keyword do we fall back to a contained-keyword search, and if that finds
    more than one distinct keyword the name is ambiguous and we return None so
    it is reported rather than mis-extracted.
    """
    name = os.path.basename(filename).upper()
    # 1. strongest: name starts with a formation keyword
    for form in PROFILES:
        if name.startswith(form):
            return form
    # 2. fallback: keyword appears somewhere; require it to be unambiguous
    found = [form for form in PROFILES if form in name]
    if len(found) == 1:
        return found[0]
    return None  # none found, or ambiguous (more than one keyword)


def _decode(arr):
    out = []
    for name in arr:
        s = str(name)
        out.append(s.split("'")[1] if "'" in s else s)
    return out


def _build_dates(master_time_table):
    days, dates = [], []
    shift = 0
    for n, t in enumerate(master_time_table):
        val = t[2]
        day = math.floor(val)
        frac = val % 1
        hour = math.floor(frac * 24); frac = (frac * 24) % 1
        minute = math.floor(frac * 60); frac = (frac * 60) % 1
        second = math.floor(frac * 60)
        date_str = "%d %d:%d:%d" % (day, hour, minute, second)
        try:
            dt = _dt.datetime.strptime(date_str, "%Y%m%d %H:%M:%S")
            days.append(t[1]); dates.append(dt)
        except Exception:
            shift -= 1
    return np.asarray(days, dtype=float), dates


def _days_lookup(f):
    mtt = f["General/MasterTimeTable"][:]
    days, dates = _build_dates(mtt)
    return np.round(days, 9), pd.to_datetime(dates)


def component_index_map(f):
    """Return {'CH4': i, 'CO2': j} 1-based indices from General/ComponentTable."""
    comps = _decode(f["General/ComponentTable"][:])
    upper = [c.upper() for c in comps]
    out = {}
    for target, aliases in COMPONENT_ALIASES.items():
        idx = None
        for i, c in enumerate(upper, 1):
            if c in aliases:
                idx = i
                break
        out[target] = idx
    return out, comps


def resolve_key(key, comp_idx):
    """Resolve a key spec into the literal CMG variable name.
    key may be a plain string, or (base, 'CH4'/'CO2')."""
    if isinstance(key, tuple):
        base, comp = key
        i = comp_idx.get(comp)
        if i is None:
            raise KeyError("component %s not found in this file" % comp)
        return "%s(%d)" % (base, i)
    return key


def _group_arrays(f, group):
    """Read one TimeSeries group's names, timestep index and the Data handle."""
    base = "TimeSeries/" + group
    origins = _decode(f[base + "/Origins"][:])
    variables = _decode(f[base + "/Variables"][:])
    ts_ind = np.asarray(f[base + "/Timesteps"][:])
    data = f[base + "/Data"]        # (ntimes, nvars, norigins) h5py dataset
    # guard against data/timesteps length mismatch (CMG trailing record)
    n = min(data.shape[0], len(ts_ind))
    return origins, variables, ts_ind[:n], data, n


def auto_pick_wells(origins, injector_hint, producer_hint, well_oil_sum=None):
    names = list(origins)
    inj = injector_hint if injector_hint in names else None
    pro = producer_hint if producer_hint in names else None
    if inj is None and "Injector" in names:
        inj = "Injector"
    if pro is None and "Producer" in names:
        pro = "Producer"
    if inj is None:
        for n in names:
            if "INJ" in n.upper():
                inj = n; break
    if pro is None:
        for n in names:
            if "PRO" in n.upper() or "PRD" in n.upper():
                pro = n; break
    if inj is None or pro is None:
        raise ValueError("Could not identify injector/producer from wells %s. "
                         "Pass --injector and --producer." % names)
    return inj, pro


def extract_one(infile, outpath, formation, injector_hint, producer_hint, sector_name):
    profile = PROFILES[formation]
    out_columns = ["Time (day)", "Date"] + [c[0] for c in profile]

    with h5py.File(infile, "r") as f:
        days_all, dates_all = _days_lookup(f)
        n_dates = len(days_all)
        comp_idx, _comps = component_index_map(f)

        # --- WELLS ---
        w_origins, w_vars, w_tsind, w_data, w_n = _group_arrays(f, "WELLS")
        inj_name, pro_name = auto_pick_wells(w_origins, injector_hint, producer_hint)

        # --- SECTORS ---
        s_origins, s_vars, s_tsind, s_data, s_n = _group_arrays(f, "SECTORS")
        if sector_name not in s_origins:
            raise ValueError("Sector '%s' not found. Available: %s" % (sector_name, s_origins))

        def tsind_to_days_dates(ts_ind):
            idx = ts_ind.astype(int)
            valid = (idx >= 0) & (idx < n_dates)
            return idx, valid

        def pull(group, origin_name, var_key):
            """Return a 1-D array of the series for one origin+variable, trimmed to n."""
            if group == "WELLS":
                origins, vars_, tsind, data, n = w_origins, w_vars, w_tsind, w_data, w_n
            else:
                origins, vars_, tsind, data, n = s_origins, s_vars, s_tsind, s_data, s_n
            if var_key not in vars_:
                raise KeyError("%s not in %s variables" % (var_key, group))
            vi = vars_.index(var_key)
            oi = origins.index(origin_name)
            return np.asarray(data[:n, vi, oi], dtype=float), tsind, n

        # Build a per-group time frame (Days unique) once, then merge columns on Days.
        def group_days(group):
            if group == "WELLS":
                tsind, n = w_tsind, w_n
            else:
                tsind, n = s_tsind, s_n
            idx = tsind.astype(int)
            valid = (idx >= 0) & (idx < n_dates)
            days = np.full(n, np.nan)
            dates = np.empty(n, dtype="datetime64[ns]")
            days[valid] = days_all[idx[valid]]
            dates[valid] = dates_all.values[idx[valid]]
            return days, dates, valid

        w_days, w_dates, w_valid = group_days("WELLS")
        s_days, s_dates, s_valid = group_days("SECTORS")

        # Resolve origin label per column
        def origin_label(kind):
            return {"injector": inj_name, "producer": pro_name, "sector": sector_name}[kind]

        # Collect each column's (days, values) then merge on Days.
        series = {}   # label -> DataFrame[Days, value]
        for label, group, kind, key_spec in profile:
            key = resolve_key(key_spec, comp_idx)
            vals, _tsind, _n = pull(group, origin_label(kind), key)
            days = w_days if group == "WELLS" else s_days
            valid = w_valid if group == "WELLS" else s_valid
            d = pd.DataFrame({"Days": np.round(days, 9), label: vals})
            d = d.loc[valid].drop_duplicates(subset="Days", keep="last")
            series[label] = d

        # Base frame: producer wells timeline (defines the row set)
        base_days = np.round(w_days, 9)
        base = pd.DataFrame({"Days": base_days, "Date": w_dates})
        base = base.loc[w_valid].drop_duplicates(subset="Days", keep="last")

    # file closed; assemble
    out = base.copy()
    for label, _g, _k, _spec in profile:
        out = out.merge(series[label], on="Days", how="left")
    out = out.rename(columns={"Days": "Time (day)"})
    out = out[out_columns]
    out.to_excel(outpath, sheet_name="Data", index=False)

    n = len(out)
    final_day = float(out["Time (day)"].iloc[-1]) if n else 0.0
    del out, base, series
    gc.collect()
    return n, final_day


def friendly_error(e):
    msg = str(e).strip()
    low = msg.lower()
    if "unable to allocate" in low:
        return ("Ran out of usable memory (install 64-bit Python and re-run). [" + msg + "]")
    if "filter returned failure" in low or "can't synchronously read" in low:
        return ("File is compressed with a filter this h5py build can't read, or is "
                "partially corrupt. Re-export this run from CMG. [" + msg + "]")
    if "component" in low and "not found" in low:
        return ("A component (CH4/CO2) expected by this formation was not found. [" + msg + "]")
    if msg == "":
        return ("Empty/invalid SR3 (truncated, still being written, or not a valid SR3).")
    return msg


def gather_inputs(args):
    files = []
    for p in args.files:
        files.extend(globmod.glob(p))
    if not files:
        files = globmod.glob(os.path.join(args.indir, args.glob))
    return sorted({f for f in files if f.lower().endswith(".sr3")})


def check_missing_sims(indir):
    """Return a list of .dat basenames (no extension) that have no .sr3."""
    dats = globmod.glob(os.path.join(indir, "*.dat"))
    missing = []
    for d in sorted(dats):
        stem = os.path.splitext(os.path.basename(d))[0]
        sr3 = os.path.join(indir, stem + ".sr3")
        if not os.path.exists(sr3):
            missing.append(stem)
    return missing


# ---------------------------------------------------------------------------
# Reading the intended project duration from a CMG .dat deck
# ---------------------------------------------------------------------------
# A CMG deck schedules time with DATE keywords, e.g.
#     DATE 2000 1 1
#     DATE 2000 2  1.00000
#     ...
#     DATE 2050 1  1.00000
#     STOP
# The first DATE is the simulation start, the last DATE is the full intended
# end of the schedule. The project duration in days is (last DATE - first DATE).
# We read the FULL provided time (the last scheduled DATE), not just a stop point.


def parse_dat_target_days(dat_path):
    """Parse a CMG .dat deck and return the intended project duration in days,
    computed as (last DATE - first DATE). Returns None if it can't be read."""
    import re
    date_re = re.compile(r"^\s*\*?DATE\s+(\d{1,4})\s+(\d{1,2})\s+(\d{1,2})(?:\.\d+)?",
                         re.IGNORECASE)
    first = None
    last = None
    try:
        with open(dat_path, "r", errors="ignore") as fh:
            for line in fh:
                m = date_re.match(line)
                if not m:
                    continue
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    dt = _dt.date(y, mo, d)
                except ValueError:
                    continue
                if first is None:
                    first = dt
                last = dt
    except Exception:
        return None
    if first is None or last is None:
        return None
    return (last - first).days


def determine_folder_target(indir, sr3_files, sample=3):
    """Sample up to `sample` .dat files (matched to the .sr3 cases being
    processed) and establish one shared project-duration target for the folder.

    Returns (target_days, info) where info is a dict describing what happened:
       mode: 'folder' (all samples agree)        -> use target_days for all
             'mixed'  (samples disagree)          -> caller falls back per-case
             'none'   (no .dat files to sample)   -> target_days is None
    """
    # Prefer .dat files that correspond to the .sr3 cases we will process.
    stems = [os.path.splitext(os.path.basename(s))[0] for s in sr3_files]
    candidates = []
    for stem in stems:
        dp = os.path.join(indir, stem + ".dat")
        if os.path.exists(dp):
            candidates.append(dp)
    # Fall back to any .dat in the folder if none match by name.
    if not candidates:
        candidates = sorted(globmod.glob(os.path.join(indir, "*.dat")))

    if not candidates:
        return None, {"mode": "none", "sampled": [], "targets": []}

    sampled = sorted(candidates)[:max(1, sample)]
    targets = []
    for dp in sampled:
        t = parse_dat_target_days(dp)
        if t is not None:
            targets.append((os.path.basename(dp), t))

    if not targets:
        return None, {"mode": "none", "sampled": [os.path.basename(x) for x in sampled],
                      "targets": []}

    distinct = set(t for _n, t in targets)
    if len(distinct) == 1:
        return targets[0][1], {"mode": "folder",
                               "sampled": [n for n, _t in targets],
                               "targets": targets}
    # disagreement -> mixed durations in this folder
    return None, {"mode": "mixed",
                  "sampled": [n for n, _t in targets],
                  "targets": targets}


def completeness(final_day, target_days, frac):
    """Return (is_complete, shortfall_days). target_days may be None (unknown)."""
    if target_days is None or target_days <= 0:
        return None, None
    threshold = frac * target_days
    is_complete = final_day >= threshold
    shortfall = max(0.0, target_days - final_day)
    return is_complete, shortfall


def main():
    ap = argparse.ArgumentParser(description="Formation-aware batch extractor for CMG SR3 files.")
    ap.add_argument("files", nargs="*", help="specific .sr3 files (optional)")
    ap.add_argument("--indir", default=".", help="folder to search (default: current folder)")
    ap.add_argument("--glob", default="*.sr3", help="filename pattern (default: *.sr3)")
    ap.add_argument("--outdir", default=None,
                    help="output folder (default: an 'extracted_xlsx' subfolder inside --indir)")
    ap.add_argument("--injector", default="Injector", help="injector well name")
    ap.add_argument("--producer", default="Producer", help="producer well name")
    ap.add_argument("--sector", default="FIELD", help="sector name for field values")
    ap.add_argument("--min-rows", type=int, default=SUSPICIOUS_MIN_ROWS,
                    help="flag outputs with fewer rows than this as suspicious (default: 600)")
    ap.add_argument("--complete-frac", type=float, default=0.999,
                    help="a run is complete if its final day reaches this fraction "
                         "of the project duration read from the .dat deck (default: 0.999)")
    ap.add_argument("--project-days", type=float, default=None,
                    help="override the project duration in days instead of reading it "
                         "from the .dat files")
    args = ap.parse_args()

    indir_abs = os.path.abspath(args.indir)
    files = gather_inputs(args)
    if not files:
        print("No .sr3 files found. Looked in '%s' with pattern '%s'." % (args.indir, args.glob))
        sys.exit(1)

    outdir = args.outdir if args.outdir else os.path.join(indir_abs, "extracted_xlsx")
    os.makedirs(outdir, exist_ok=True)
    print("Output folder:", outdir)
    print("Found %d SR3 file(s)." % len(files))

    import struct
    bits = struct.calcsize("P") * 8

    # 1. Missing-simulation check (.dat without .sr3)
    missing_sims = check_missing_sims(indir_abs)

    # 2. Establish the folder's project duration (sample 2-3 .dat files once).
    #    Per the design: all cases in a folder normally share one duration, so
    #    we read a few decks, not every one. If the samples disagree, we fall
    #    back to reading each case's own .dat.
    per_case_target = False
    duration_note = ""
    if args.project_days is not None:
        folder_target = args.project_days
        duration_note = "project duration set by --project-days: %.0f days" % folder_target
    else:
        folder_target, dinfo = determine_folder_target(indir_abs, files, sample=3)
        if dinfo["mode"] == "folder":
            duration_note = ("project duration read from %d .dat file(s) (%s): %.0f days (%.1f years)"
                             % (len(dinfo["sampled"]), ", ".join(dinfo["sampled"]),
                                folder_target, folder_target / 365.25))
        elif dinfo["mode"] == "mixed":
            per_case_target = True
            pairs = ", ".join("%s=%d" % (n, t) for n, t in dinfo["targets"])
            duration_note = ("mixed project durations detected across sampled .dat files "
                             "(%s); checking each case against its own .dat" % pairs)
        else:
            duration_note = ("no .dat files found to read the project duration; "
                             "completeness cannot be checked")
    print(duration_note)

    def target_for(stem):
        """Resolve the target duration for one case."""
        if per_case_target:
            dp = os.path.join(indir_abs, stem + ".dat")
            if os.path.exists(dp):
                return parse_dat_target_days(dp)
            return None
        return folder_target

    succeeded = []    # (name, formation, rows, status, final_day, target, shortfall, note)
                      # status in {"ok", "suspicious"}
    failed = []       # (name, reason)
    skipped = []      # (name, reason)  -- unknown formation

    for i, infile in enumerate(files, 1):
        base = os.path.basename(infile)
        stem = os.path.splitext(base)[0]
        outpath = os.path.join(outdir, stem + ".xlsx")
        formation = detect_formation(infile)
        if formation is None:
            print("[%d/%d] %s -> SKIPPED (unknown formation)" % (i, len(files), base))
            skipped.append((base, "no BAKN/DUVY/MONT/HRNR keyword in filename"))
            continue
        print("[%d/%d] %s  [%s] -> %s" % (i, len(files), base, formation, os.path.basename(outpath)))
        try:
            n, final_day = extract_one(infile, outpath, formation,
                                       args.injector, args.producer, args.sector)
            # PRIMARY check: row count (human-readable).
            low_rows = n < args.min_rows
            # SECONDARY check: did it reach the end of the project (from the .dat)?
            tgt = target_for(stem)
            is_complete, shortfall = completeness(final_day, tgt, args.complete_frac)
            incomplete = (is_complete is False)

            reasons = []
            if low_rows:
                reasons.append("only %d rows (< %d)" % (n, args.min_rows))
            if incomplete:
                reasons.append("reached %.0f of %.0f days (%.0f short, ~%.1f yr short)"
                               % (final_day, tgt, shortfall, shortfall / 365.25))
            status = "suspicious" if (low_rows or incomplete) else "ok"

            if status == "suspicious":
                print("    wrote %d rows  *** SUSPICIOUS: %s ***" % (n, "; ".join(reasons)))
            elif is_complete is None:
                print("    wrote %d rows  (reached %.0f days; completeness not checked)"
                      % (n, final_day))
            else:
                print("    wrote %d rows  (complete: reached %.0f days)" % (n, final_day))

            succeeded.append((base, formation, n, status, final_day, tgt, shortfall,
                              "; ".join(reasons)))
        except Exception as e:
            fe = friendly_error(e)
            print("    FAILED:", fe)
            failed.append((base, fe))
        finally:
            gc.collect()

    # ---- Report ----
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fstamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(outdir, "extraction_report_" + fstamp + ".txt")

    suspicious_list = [r for r in succeeded if r[3] == "suspicious"]

    def yr(days):
        return days / 365.25

    L = []
    L.append("SR3 EXTRACTION REPORT")
    L.append("Generated: " + stamp)
    L.append("Python: %d-bit" % bits)
    L.append("Input folder:  " + indir_abs)
    L.append("Output folder: " + outdir)
    L.append("Row-count flag: fewer than %d rows (primary)" % args.min_rows)
    L.append("Completeness: final day must reach %.1f%% of project duration (secondary)"
             % (args.complete_frac * 100))
    L.append("Project duration: " + duration_note)
    L.append("")
    L.append("SR3 files found:     %d" % len(files))
    L.append("Succeeded:           %d" % len(succeeded))
    L.append("  of which suspicious: %d" % len(suspicious_list))
    L.append("Failed:              %d" % len(failed))
    L.append("Skipped (unknown formation): %d" % len(skipped))
    L.append("Missing simulations (.dat without .sr3): %d" % len(missing_sims))
    L.append("")

    L.append("=" * 72)
    L.append("SUCCESSFUL (%d)" % len(succeeded))
    L.append("=" * 72)
    if succeeded:
        for name, form, rows, status, fday, tgt, short, note in succeeded:
            tag = "  <-- SUSPICIOUS" if status == "suspicious" else ""
            L.append("  OK   %-34s [%s] %6d rows%s" % (name, form, rows, tag))
    else:
        L.append("  (none)")
    L.append("")

    L.append("=" * 72)
    L.append("SUSPICIOUS RESULTS (%d)  - spreadsheet written, please verify" % len(suspicious_list))
    L.append("=" * 72)
    if suspicious_list:
        for name, form, rows, status, fday, tgt, short, note in suspicious_list:
            # PRIMARY line: row count. SECONDARY line: the time detail.
            L.append("  !    %-34s [%s] %d rows" % (name, form, rows))
            if tgt:
                L.append("         reached %.0f days (year %.0f) of %.0f (year %.0f), %.0f days short (~%.1f yr)"
                         % (fday, yr(fday), tgt, yr(tgt), short, yr(short)))
            else:
                L.append("         reached %.0f days (year %.0f); project duration unknown"
                         % (fday, yr(fday)))
    else:
        L.append("  (none)")
    L.append("")

    L.append("=" * 64)
    L.append("FAILED (%d)" % len(failed))
    L.append("=" * 64)
    if failed:
        for name, err in failed:
            L.append("  FAIL %-38s %s" % (name, err))
    else:
        L.append("  (none)")
    L.append("")

    L.append("=" * 64)
    L.append("SKIPPED - UNKNOWN FORMATION (%d)" % len(skipped))
    L.append("=" * 64)
    if skipped:
        for name, reason in skipped:
            L.append("  SKIP %-38s %s" % (name, reason))
    else:
        L.append("  (none)")
    L.append("")

    L.append("=" * 64)
    L.append("MISSING SIMULATIONS (%d)  - .dat present but no .sr3 (run not completed?)" % len(missing_sims))
    L.append("=" * 64)
    if missing_sims:
        for stem in missing_sims:
            L.append("  MISS %s.dat  ->  no %s.sr3" % (stem, stem))
    else:
        L.append("  (none)")
    L.append("")

    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    print("\nDone. %d succeeded (%d suspicious), %d failed, %d skipped, %d missing sims."
          % (len(succeeded), len(suspicious_list), len(failed), len(skipped), len(missing_sims)))
    print("Report written to:", report_path)


if __name__ == "__main__":
    main()
