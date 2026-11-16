# Validate a CSV Import Without Rewriting the Source File

A CSV file can parse successfully and still be a bad import. A row may have one field too many. Two records may share the same identifier. An amount may contain `NaN` or an unexpected exponent. None of those problems requires opening the file in a spreadsheet and saving a changed copy.

This tutorial builds a small Python command-line checker that reads a CSV, checks an explicit schema, and prints JSON. It does not repair the data, upload it, or write a replacement file. The accompanying tests check both the validation results and the original file bytes.

The example is deliberately narrow: a synthetic import with two columns, `id` and `amount`. It is a teaching project, not a report of a production migration. The code and tests below were run with Python 3.10.12 using only the standard library.

## What you will build

A successful check produces a report like this:

```json
{
  "ok": true,
  "bytes_read": 24,
  "sha256": "badc4c0074c84f30dfe95832f16c2e4cac103d292001a294ad7162418f50082f",
  "records_checked": 2,
  "errors": []
}
```

The command returns exit code `0` for a passing file, `1` for a validation failure, or `2` if it cannot read the path. That makes it usable in a shell script without guessing from a sentence in the output.

There are two distinct questions:

1. Does the file satisfy the import rules?
2. Did this checker leave the file's bytes alone?

A CSV parser helps with the first question, but it does not define your business rules. A hash identifies the bytes read, but by itself it does not answer the second question. We will test preservation explicitly.

## Define the schema before opening the file

For this example, the rules are:

- The header must be exactly `id,amount`, in that order, with no extra spaces.
- There must be at least one data record.
- Every data record must have exactly two fields.
- Identifiers must be nonempty, unique, and free of leading or trailing whitespace. They are case-sensitive.
- An amount must contain ASCII digits, optionally followed by a decimal point and one or two digits. Negative numbers, exponents, spaces, and special floating-point values are not accepted.
- Input must be UTF-8, with an optional UTF-8 byte-order mark.
- Input larger than 8 MiB is rejected.

These are application choices, not universal CSV rules. For example, another import might allow negative adjustments or a different column order. Change the schema deliberately rather than silently stripping spaces or converting values until they look acceptable.

The amount rule checks spelling, not financial meaning. It allows `00.50`, imposes no business maximum, and does not perform arithmetic. A payment system would need additional rules for currency, range, settlement, and precision.

## Parse records, not lines

Do not use `line.split(',')` to read CSV. Commas and line breaks may occur inside quoted fields. The standard library's [`csv.reader`](https://docs.python.org/3/library/csv.html) understands those cases.

We use `csv.reader`, rather than immediately converting each row to a dictionary, because an exact field-count check is part of the contract. The header and the number of fields remain visible instead of being folded into key/value mappings.

The reader's `line_num` counts physical lines consumed. A quoted record can span several lines, so the report labels both the data-record number and the physical line where it ends. Record 1 is the first data record after the header.

`strict=True` asks the parser to report malformed CSV that it recognizes. It is not a promise of complete RFC conformance or a substitute for the schema checks.

## Read one bounded snapshot

The checker opens the path with `rb`, reads at most the limit plus one byte, then closes the handle. A separate size check before an unbounded read would be weaker: the file could grow between those operations.

For an oversized input, the checker refuses it without treating the partial bytes as a complete file. Its hash is therefore `null`. For an input within the size limit, it hashes the raw bytes before decoding. A byte-order mark and the original newline bytes are included in that hash.

The [`utf-8-sig` decoder](https://docs.python.org/3/library/codecs.html#encodings-and-unicode) accepts UTF-8 and removes a leading UTF-8 byte-order mark from the decoded text. Invalid UTF-8 fails instead of being replaced with guessed characters. The CSV parser receives an in-memory text stream with `newline=''`, allowing it to handle embedded newlines.

This approach intentionally trades some memory for clarity. Both raw bytes and decoded text exist in memory. The input limit bounds their size, but the Python objects, duplicate-ID set, and error list also use memory. This is not a constant-memory streaming validator or a parser sandbox for hostile uploads.

## Implement the checker

Save this as `check_csv.py`:

```python
"""Read a bounded CSV snapshot and report errors without changing its bytes."""
import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
EXPECTED_HEADER = ["id", "amount"]
AMOUNT = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?\Z")


def check_csv(path: Path, max_bytes: int = MAX_BYTES) -> dict:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    # Read at most one byte beyond the limit, even if the file grows.
    with path.open("rb") as source:
        raw = source.read(max_bytes + 1)
    report = {"ok": False, "bytes_read": len(raw), "sha256": None,
              "records_checked": 0, "errors": []}
    if len(raw) > max_bytes:
        report["errors"].append(f"file exceeds {max_bytes}-byte limit")
        return report
    report["sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        report["errors"].append("input is not valid UTF-8")
        return report
    # newline='' lets the CSV parser handle embedded CRLFs correctly.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    seen = set()
    try:
        header = next(reader, None)
        if header != EXPECTED_HEADER:
            report["errors"].append("header must be exactly id,amount")
            return report
        for record_number, row in enumerate(reader, start=1):
            report["records_checked"] += 1
            label = f"record {record_number} (ends at line {reader.line_num})"
            if len(row) != 2:
                report["errors"].append(f"{label}: expected 2 fields, got {len(row)}")
                continue
            identifier, amount = row
            if not identifier or identifier != identifier.strip():
                report["errors"].append(f"{label}: id is empty or has edge whitespace")
            elif identifier in seen:
                report["errors"].append(f"{label}: duplicate id")
            else:
                seen.add(identifier)
            if not AMOUNT.fullmatch(amount):
                report["errors"].append(f"{label}: amount must be unsigned decimal with at most 2 places")
    except csv.Error:
        report["errors"].append(f"CSV parsing failed near line {reader.line_num}")
    if report["records_checked"] == 0:
        report["errors"].append("at least one data record is required")
    report["ok"] = not report["errors"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        report = check_csv(args.path)
    except OSError:
        # No raw values or exception details in the machine-readable report.
        report = {"ok": False, "errors": ["could not read input file"]}
        exit_code = 2
    else:
        exit_code = 0 if report["ok"] else 1
    print(json.dumps(report, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
```

Notice what the checker does not do. It does not call `strip()` to fix an identifier. It compares the original identifier with its stripped form and reports the problem. It does not convert an amount to a floating-point number. It checks the permitted decimal representation directly.

It also avoids copying raw identifiers and amounts into error messages. Record numbers and rule names are usually enough to locate an error without echoing data into a log. The report still contains a content hash, which may itself be sensitive for predictable inputs. Keep reports with the same care as their source data.

## Run it on synthetic data

Create a file called `valid.csv` with this content:

```csv
id,amount
a1,12.50
a2,0
```

Run:

```bash
python check_csv.py valid.csv
```

If those exact contents end with a newline, the report shown at the beginning is the expected result. A different line ending or final newline changes the hash, even when the parsed values are identical.

Now try a separate fixture called `invalid.csv`:

```csv
id,amount
a1,12.50
a1,NaN
a2,1,unexpected
```

The second data record has a duplicate identifier and an invalid amount. The third has three fields instead of two. The checker reports each problem and exits with code `1`. It does not change `NaN`, delete the extra field, or choose which duplicate should win.

On a POSIX shell, inspect the exit status immediately after the command:

```bash
python check_csv.py invalid.csv
echo $?
```

Do not redirect output onto the input path. A shell command such as `python check_csv.py input.csv > input.csv` truncates the file before Python opens it. Read-only behavior inside a program cannot undo a destructive redirection outside it. Use the terminal or a distinct report path.

## Test failure cases and file preservation

Place `test_check_csv.py` from the accompanying source bundle next to the checker. Run:

```bash
python -m unittest -v
```

The test helper writes only temporary synthetic fixtures. It saves their bytes, runs the checker, and compares the bytes afterward. For complete snapshots it also compares the reported SHA-256 with an independently calculated digest.

The suite covers:

- Valid CRLF data and UTF-8 with a byte-order mark.
- A quoted identifier containing both a comma and a newline.
- Rows with missing or extra fields, duplicate IDs, empty IDs, and edge whitespace.
- Invalid amounts, including `NaN`, `Infinity`, an exponent, excess decimal places, and a formula-like value.
- An incorrect header, an empty input, and a header without data.
- Invalid UTF-8, an unclosed quoted field, and a file over the configured size limit.
- Command-line exit codes for valid data, invalid data, and a missing input path.

The executed result on Python 3.10.12 was:

```text
Ran 14 tests
OK
```

These are 14 test methods, some with multiple subcases. They establish the behavior for the supplied cases on that interpreter. They are not a fuzzing campaign, cross-platform certification, or proof that every possible CSV input is handled safely.

## Know the boundary of the result

A passing report means only that the bytes read met this schema. It does not prove that a customer exists, an invoice is genuine, a sum reconciles, or an import is authorized.

The SHA-256 comes from the snapshot read by this run. It is not a trusted signature. If the source file changes concurrently, the checker does not create an atomic filesystem snapshot or lock another process out. It also does not refuse symlinks. For a controlled import, stage a stable, authorized file first, then validate and import the same staged bytes. Do not validate one path and later assume that a new read from that path contains the same data.

The checker leaves file contents alone in the tested cases, but reading may update filesystem access metadata. Nor does it make an arbitrary input safe for a spreadsheet: the amount column rejects formula-like text, but the ID column has no spreadsheet-formula policy. Exporting to a spreadsheet needs a separate threat model and escaping policy.

That separation is useful. A validator should tell you exactly what it checked, preserve the evidence you need, and fail visibly when the contract does not hold. Repairing data and importing it can remain separate, reviewed steps.

## Sources and reproducibility

- Python CSV documentation: https://docs.python.org/3/library/csv.html
- Python hashing documentation: https://docs.python.org/3/library/hashlib.html
- Pathlib file-opening documentation: https://docs.python.org/3/library/pathlib.html#pathlib.Path.open
- UTF-8 byte-order mark behavior: https://docs.python.org/3/library/codecs.html#encodings-and-unicode

The source bundle includes `check_csv.py`, `test_check_csv.py`, synthetic fixtures, the example JSON report, and the captured test output. No real client or personal data is needed to reproduce it.
