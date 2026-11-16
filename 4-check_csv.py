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
