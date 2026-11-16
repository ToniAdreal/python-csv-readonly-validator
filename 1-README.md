# Validate a CSV Import Without Rewriting the Source File

Source code and tests for the tutorial by Toni Adreal.

- `check_csv.py` - bounded, read-only CSV checker (Python standard library only)
- `test_check_csv.py` - 14 tests, including a check that the input bytes are unchanged
- `valid.csv`, `invalid.csv` - synthetic fixtures; `example-report.json`, `invalid-report.json` - sample output
- `test-results.txt` - captured test run (Python 3.10.12)
- `tutorial.md` - the tutorial text; `index.html` is the same text as a web page
- `SHA256SUMS.txt` - checksums of the source files

Run the tests: `python -m unittest -v`

All data is synthetic. No client or personal data is included.
