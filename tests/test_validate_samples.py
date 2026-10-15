"""Regression harness tests with synthetic subprocesses; no game assets needed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_samples import load_cases, run_process, sha256


class SampleRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_baseline_paths_are_deduplicated_and_status_retained(self):
        manifest = self.root / "cases.jsonl"
        manifest.write_text('\n'.join(json.dumps(record) for record in [
            dict(path="example.nif", status="rejected", signature="abc"),
            dict(path="example.nif", status="rejected"),
            dict(path="second.nif", status="dry_run_passed"),
        ]), encoding="utf8")
        cases = load_cases(manifest=manifest, limit=2)
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0]["baseline_status"], "rejected")
        self.assertEqual(cases[0]["path"], str(self.root / "example.nif"))

    def test_inventory_prioritizes_frequent_signatures(self):
        manifest = self.root / "inventory.json"
        manifest.write_text(json.dumps({"signatures": {
            "rare": {"files": 1, "representatives": [{"path": "rare.nif"}]},
            "common": {"files": 50, "representatives": [{"path": "common.nif"}]}
        }}), encoding="utf8")
        cases = load_cases(manifest=manifest, limit=1)
        self.assertEqual(cases[0]["signature"], "common")
        self.assertEqual(cases[0]["corpus_files_with_signature"], 50)

    def test_native_style_crash_is_reported(self):
        result = run_process([sys.executable, "-c", "raise SystemExit(7)"], 3)
        self.assertEqual(result["category"], "worker_crash")
        self.assertEqual(result["returncode"], 7)

    def test_timeout_is_bounded(self):
        result = run_process([sys.executable, "-c", "import time;time.sleep(10)"], 0.1)
        self.assertEqual(result["status"], "timeout")

    def test_worker_protocol_rejects_non_json(self):
        result = run_process([sys.executable, "-c", "print('not a report')"], 3)
        self.assertEqual(result["category"], "worker_protocol")

    def test_worker_can_log_before_json(self):
        result = run_process([sys.executable, "-c", 'print("progress");print(\'{"status":"dry_run_passed"}\')'], 3)
        self.assertEqual(result["status"], "dry_run_passed")

    def test_hash_checks_contents(self):
        path = self.root / "sample.nif"
        path.write_bytes(b"first")
        before = sha256(path)
        path.write_bytes(b"other")
        self.assertNotEqual(before, sha256(path))


if __name__ == "__main__":
    unittest.main()
