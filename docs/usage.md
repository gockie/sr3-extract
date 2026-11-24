# Usage guide

This page covers how to install and run SR3-Extract. A formatted version of the
full user guide is also provided as `SR3_Extractor_User_Guide.docx` in this
folder.

## Requirements

- 64-bit Python 3.10 or newer.
- The libraries `numpy`, `pandas`, `h5py`, and `openpyxl`.

Install them with:

```bash
pip install "numpy<2.1" "pandas<2.3" "h5py>=3.11" openpyxl
```

The version pins guarantee prebuilt wheels on Python 3.10, which avoids a
source build of `h5py`. On newer Python you can install the latest versions
without pins.

## Quick start

1. Put `extract_sr3.py` in the folder that holds your `.sr3` files. If the CMG
   `.dat` decks are in the same folder, the completeness check is enabled
   automatically.
2. Open a terminal in that folder.
3. Run:

   ```bash
   python extract_sr3.py
   ```

The tool creates an `extracted_xlsx` subfolder, writes one spreadsheet per
`.sr3` file (named to match the source), and saves a timestamped report there.

## Choosing inputs and outputs

```bash
# process a different folder
python extract_sr3.py --indir "C:\\path\\to\\sr3files"

# send outputs somewhere specific
python extract_sr3.py --outdir "C:\\path\\to\\output"

# only files matching a pattern
python extract_sr3.py --glob "DUVY_Scenario_*.sr3"

# specific files
python extract_sr3.py case1.sr3 case2.sr3
```

## Auditing options

```bash
# change the row-count flag threshold
python extract_sr3.py --min-rows 500

# require a run to reach 99.5% of the project duration to count as complete
python extract_sr3.py --complete-frac 0.995

# set the project duration explicitly instead of reading it from the .dat files
python extract_sr3.py --project-days 18263
```

## Reading the report

Each run writes a report named `extraction_report_<timestamp>.txt` into the
output folder. It opens with the settings used and the project duration found,
then lists:

- successful files with their formation and row count,
- suspicious results, each with the row count and how far the run reached
  versus the project length,
- failed files with the reason,
- files skipped for an unrecognised formation,
- `.dat` decks with no matching `.sr3` (simulations that were never run).

A result is `SUSPICIOUS` if it has fewer rows than the threshold or if its final
simulation time does not reach the project end. The spreadsheet is still
written so you can inspect the partial data.

## Troubleshooting

- "No .sr3 files found": check you are in the right folder or that `--indir`
  points at the files.
- A file skipped for unknown formation: the filename needs to start with a
  recognised keyword (`BAKN`, `DUVY`, `MONT`, `HRNR`). Rename it or add a
  profile.
- A memory error on a very large file: make sure you are running 64-bit Python.
- A "timestep count mismatch" note: harmless; the tool keeps every complete
  timestep and trims a single trailing record some runs store.
