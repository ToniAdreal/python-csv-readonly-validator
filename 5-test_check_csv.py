import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from check_csv import check_csv


class CSVChecks(unittest.TestCase):
    def inspect(self, content, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            path.write_bytes(content)
            before = path.read_bytes()
            result = check_csv(path, **kwargs)
            self.assertEqual(path.read_bytes(), before)
            if result["sha256"] is not None:
                self.assertEqual(result["sha256"], hashlib.sha256(before).hexdigest())
            return result

    def test_valid_crlf(self):
        result = self.inspect(b"id,amount\r\na1,12.50\r\na2,0\r\n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["records_checked"], 2)

    def test_bom(self):
        self.assertTrue(self.inspect(b"\xef\xbb\xbfid,amount\na1,1\n")["ok"])

    def test_quoted_comma_and_multiline(self):
        result = self.inspect(b'id,amount\n"part,one\ncontinued",1.2\n')
        self.assertTrue(result["ok"])
        self.assertEqual(result["records_checked"], 1)

    def test_short_and_long_rows(self):
        result = self.inspect(b"id,amount\na1\na2,1,extra\n")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["errors"]), 2)

    def test_duplicate(self):
        self.assertIn("duplicate id", " ".join(self.inspect(b"id,amount\na1,1\na1,2\n")["errors"]))

    def test_id_whitespace(self):
        self.assertFalse(self.inspect(b"id,amount\n a1,1\n")["ok"])

    def test_empty_id(self):
        self.assertFalse(self.inspect(b"id,amount\n,1\n")["ok"])

    def test_invalid_amounts(self):
        for amount in ["-1", "NaN", "Infinity", "1e2", "1.234", "", " 1", "=1+1"]:
            with self.subTest(amount=amount):
                self.assertFalse(self.inspect(f"id,amount\na1,{amount}\n".encode())["ok"])

    def test_wrong_header(self):
        for content in [b"amount,id\n1,a1\n", b"id,id\na1,1\n", b""]:
            with self.subTest(content=content):
                self.assertFalse(self.inspect(content)["ok"])

    def test_header_only(self):
        self.assertFalse(self.inspect(b"id,amount\n")["ok"])

    def test_invalid_utf8(self):
        self.assertFalse(self.inspect(b"id,amount\na1,\xff\n")["ok"])

    def test_malformed_quote(self):
        result = self.inspect(b'id,amount\n"a1,1\n')
        self.assertFalse(result["ok"])
        self.assertIn("CSV parsing failed", " ".join(result["errors"]))

    def test_size_limit(self):
        result = self.inspect(b"id,amount\na1,1\n", max_bytes=8)
        self.assertFalse(result["ok"])
        self.assertEqual(result["bytes_read"], 9)
        self.assertIsNone(result["sha256"])

    def test_cli_exit_codes_and_no_write(self):
        script = Path(__file__).with_name("check_csv.py")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            for raw, expected in [(b"id,amount\na1,1\n", 0), (b"id,amount\na1,no\n", 1)]:
                path.write_bytes(raw)
                run = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
                self.assertEqual(run.returncode, expected)
                self.assertIsInstance(json.loads(run.stdout)["ok"], bool)
                self.assertEqual(path.read_bytes(), raw)
            path.unlink()
            run = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(json.loads(run.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
