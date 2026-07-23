# -*- coding: utf-8 -*-
import importlib.util
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_resource_xpo", ROOT / "build-resource-xpo.py"
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
build_blob = _mod.build_blob
extract_file = _mod.extract_file


class ResourceWrapperTest(unittest.TestCase):
    def test_ax_extraction_preserves_complete_file(self):
        payload = b"PK\x03\x04test-data-PK\x05\x06" + (b"\x00" * 18)
        blob = build_blob(payload)

        self.assertEqual(blob[55 + len(payload) :], b"\xff\xff\xff")
        self.assertEqual(struct.unpack_from("<I", blob, 51)[0], len(payload))
        self.assertEqual(struct.unpack_from("<I", blob, 44)[0], len(payload) + 3 + 5)
        self.assertEqual(extract_file(blob), payload)

    def test_wrong_old_formula_would_truncate(self):
        """Document the bug: field2=len-3 without sentinel truncates ZIP EOCD."""
        xlsx = b"PK" + (b"\x00" * 100) + b"ENDMARK"
        good = build_blob(xlsx)
        self.assertTrue(extract_file(good).endswith(b"ENDMARK"))
        hdr = bytearray(good[:55])
        struct.pack_into("<I", hdr, 51, len(xlsx) - 3)
        broken = bytes(hdr) + xlsx
        self.assertEqual(len(extract_file(broken)), len(xlsx) - 3)
        self.assertFalse(extract_file(broken).endswith(b"ENDMARK"))


if __name__ == "__main__":
    unittest.main()
