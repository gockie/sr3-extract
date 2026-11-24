# Contributing to SR3-Extract

Thanks for your interest in improving SR3-Extract. Contributions of all kinds
are welcome: bug reports, feature requests, documentation, and code.

## Reporting a bug or requesting a feature

Please open an issue on the
[issue tracker](https://github.com/gockie/sr3-extract/issues). For a bug,
include:

- what you ran (the command and any options),
- what you expected to happen and what happened instead,
- the error message or the relevant lines of the report,
- your operating system and Python version (`python --version`).

If the problem involves a particular SR3 file, the output of a small probe of
its structure is far more useful than the file itself, which is usually too
large to share.

## Proposing a change

1. Fork the repository and create a branch for your change.
2. Make your change, keeping the code style consistent with the existing file.
3. Add or update tests in `tests/` so the behaviour is covered.
4. Run the tests locally (see below) and make sure they pass.
5. Open a pull request describing the change and why it is needed.

## Running the tests

```bash
pip install numpy pandas h5py openpyxl pytest
pytest
```

The tests build small synthetic SR3 files and CMG decks in memory, so they need
no external data and run in a couple of seconds.

## Adding a formation profile

Extraction profiles live in the `PROFILES` dictionary near the top of
`extract_sr3.py`. Each entry is a list of columns, and each column is a tuple of
`(output header, group, origin, CMG key)`. A component-specific key is written
as a tuple such as `("GASADSMOL", "CO2")`, which is resolved to the correct
index by component name at run time. To add a formation, add a keyword entry to
`PROFILES` and, if needed, a new column building block above it.

## Code of conduct

Please be respectful and constructive in all interactions. We follow the spirit
of the [Contributor Covenant](https://www.contributor-covenant.org/).
