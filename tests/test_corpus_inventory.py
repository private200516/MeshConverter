"""Synthetic containers only: no Bethesda assets are copied into the repository."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corpus_inventory import HeaderError, inspect_header, inventory


def nif_bytes(bs=155, types=("NiNode",), indices=(0,), blocks=(b"abc",), roots=(0,)):
    pack = lambda fmt, *values: struct.pack("<" + fmt, *values)
    sized = lambda text: pack("I", len(text.encode())) + text.encode()
    data = b"Gamebryo File Format, Version 20.2.0.7\n" + pack("IBIII", 0x14020007, 1, 12, len(blocks), bs)
    data += b"\1\0" + (pack("I", 0) if bs > 130 else b"\1\0") + b"\1\0\1\0"
    data += pack("H", len(types)) + b"".join(sized(kind) for kind in types)
    data += pack("H" * len(indices), *indices) + pack("I" * len(blocks), *(len(block) for block in blocks))
    data += pack("III", 0, 0, 0) + b"".join(blocks)
    return data + pack("I", len(roots)) + pack("i" * len(roots), *roots)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_bethesda_versions_and_used_types(self):
        for bs in (130, 155):
            result = inspect_header(self.save(f"{bs}.nif", nif_bytes(bs, types=("NiNode", "Unused"))))
            self.assertEqual(result["bs"], bs)
            self.assertEqual(result["types"], ["NiNode"])
            self.assertEqual(result["payload_bytes"], 3)
            self.assertEqual(result["trailing_bytes"], 0)

    def test_rejects_corrupt_directory_and_footer(self):
        cases = [nif_bytes(indices=(1,)), nif_bytes()[:-1], nif_bytes(roots=(99,)), b"not a nif\n"]
        for index, data in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(HeaderError):
                inspect_header(self.save(f"bad{index}.nif", data))

    def test_signatures_ignore_type_order(self):
        a = inspect_header(self.save("a.nif", nif_bytes(types=("NiNode", "BSTriShape"), indices=(0, 1), blocks=(b"a", b"b"))))
        b = inspect_header(self.save("b.nif", nif_bytes(types=("BSTriShape", "NiNode"), indices=(1, 0), blocks=(b"a", b"b"))))
        self.assertEqual(a["signature"], b["signature"])

    def test_inventory_streams_errors_and_retains_small_representative(self):
        self.save("big.nif", nif_bytes(blocks=(b"a" * 1000,)))
        self.save("small.nif", nif_bytes())
        self.save("bad.nif", b"bad")
        out = io.StringIO()
        summary = inventory(self.root, out, representatives=1, progress_every=0)
        self.assertEqual((summary["total_files"], summary["parsed_files"], summary["errors"]), (3, 2, 1))
        self.assertEqual(len(out.getvalue().splitlines()), 3)
        self.assertEqual(next(iter(summary["signatures"].values()))["representatives"][0]["relative_path"], "small.nif")
        self.assertEqual(sum(json.loads(line)["status"] == "error" for line in out.getvalue().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
