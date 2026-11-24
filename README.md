# SR3-Extract

Formation-aware batch extraction and completeness auditing of Computer
Modelling Group (CMG) reservoir simulation time-series from binary SR3 output
files.

`SR3-Extract` reads CMG SR3 files directly, extracts a study-specific set of
time-series parameters chosen automatically from a keyword in each filename,
and writes one spreadsheet per run named to match its source. It reads only the
datasets it needs, so it runs comfortably on ordinary 64-bit desktop and laptop
hardware. A built-in audit stage reports simulations that were never run, runs
flagged by low row count, and runs that stopped before reaching the end of the
project (checked against the duration declared in each CMG input deck).

## Why

A reservoir screening study can involve tens or hundreds of scenario runs, each
stored as a large SR3 file from which only a handful of parameters is needed.
Exporting them one at a time through the CMG Results interface is slow,
repetitive, and error-prone, and gives no systematic check that the ensemble is
complete. `SR3-Extract` automates the whole process from a single command.

## Installation

Requires 64-bit Python 3.10 or newer.

```bash
pip install "numpy<2.1" "pandas<2.3" "h5py>=3.11" openpyxl
```

The version pins ensure prebuilt wheels are available for Python 3.10. On newer
Python versions you may omit them:

```bash
pip install numpy pandas h5py openpyxl
```

Then download `extract_sr3.py` from this repository. No installation step is
needed beyond the libraries above; the tool is a single self-contained script.

## Usage

Put `extract_sr3.py` in the folder with your `.sr3` files (and their `.dat`
decks, if available) and run:

```bash
python extract_sr3.py
```

It finds every `.sr3` in the folder, creates an `extracted_xlsx` subfolder,
writes one spreadsheet per file, and saves a timestamped report there.

### Options

```
python extract_sr3.py --indir  PATH     folder to search (default: current)
python extract_sr3.py --outdir PATH     where to write outputs
python extract_sr3.py --glob   PATTERN  filename pattern (default: *.sr3)
python extract_sr3.py FILE1.sr3 FILE2.sr3    process specific files

--injector NAME       injector well name (default: auto-detect / "Injector")
--producer NAME       producer well name (default: auto-detect / "Producer")
--sector   NAME       sector for field values (default: "FIELD")
--min-rows N          row-count flag threshold (default: 600)
--complete-frac F     fraction of project duration a run must reach to count
                      as complete (default: 0.999)
--project-days D      override the project duration instead of reading it
                      from the .dat files
```

## Formation profiles

The parameter set is chosen from a keyword at the start of the filename. The
profiles shipped with the tool are:

| Keyword | Extracts | Columns |
|---------|----------|---------|
| `BAKN`  | injector/producer cumulative gas and gas rate, producer cumulative oil and oil rate, field average pressure | 9 |
| `DUVY`  | gas and pressure, plus field gas-adsorbed moles (CH4, CO2) | 9 |
| `MONT`  | same as `DUVY` | 9 |
| `HRNR`  | `DUVY` set plus producer cumulative gas moles (CH4, CO2) | 11 |

Each output spreadsheet begins with `Time (day)` and `Date`, followed by the
formation-specific parameters with explicit units in the column headers.
Component-specific quantities are matched to CH4 and CO2 by component name read
from each file, because the component index order can differ between decks.

Profiles are defined in the `PROFILES` dictionary near the top of
`extract_sr3.py` and can be edited or extended for other studies.

## The completeness check

If a `.dat` deck is present for a case, the tool reads the intended project
duration as the span from its first `DATE` keyword to its last. A run whose
final `Time (day)` does not reach `--complete-frac` of that duration is flagged
as suspicious. Because all cases in a folder normally share one duration, only a
few decks are sampled; if they disagree, each case is checked against its own
`.dat`.

## Report

The report lists totals, then: successful files with their formation and row
count; suspicious results with how far each ran versus the project length;
failed files with the reason; files skipped for an unknown formation; and `.dat`
decks with no matching `.sr3` (never-run simulations).

`FAILED` means the spreadsheet could not be produced (corrupt file, missing
variable). `SUSPICIOUS` means it was produced but warrants review (low rows or
an incomplete run); the partial data is still written.

## Testing

```bash
pip install pytest
pytest
```

The tests build small synthetic SR3 files in memory and check extraction,
formation detection, component-by-name mapping, the `.dat` duration parser, and
the completeness logic.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to
report issues, propose changes, and run the tests.

## Citation

If you use `SR3-Extract` in your work, please cite it. See
[CITATION.cff](CITATION.cff).

## License

MIT. See [LICENSE](LICENSE).
