"""gather_files в validate_xpo — та же логика (и та же история бага), что у
fix_mojibake.gather_files (см. test_fix_mojibake.py), но копия отдельная:
проверка держится тут же, отдельным файлом, чтобы обе копии не разъезжались
незамеченными.

Запуск (без pytest):
    python tests/test_validate_gather_files.py
"""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from validate_xpo import gather_files  # noqa: E402


class TestGatherFiles(unittest.TestCase):
    def test_release_targeted_directly_returns_nothing(self):
        # Регрессия: rel_parts = p.relative_to(target).parts для файла ПРЯМО в
        # target не содержит "_release" вовсе, если target и есть _release —
        # `validate_xpo XPO\_release` переставал отказывать и пускал
        # замороженные релизные .xpo под проверку/правку как обычные.
        with tempfile.TemporaryDirectory() as tmp:
            release = pathlib.Path(tmp) / "_release"
            release.mkdir()
            (release / "SharedProject_Foo.xpo").write_text("x", encoding="utf-8")

            self.assertEqual(gather_files(release), [])

    def test_excludes_release_at_any_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "Classes").mkdir()
            (root / "Classes" / "Foo.xpo").write_text("x", encoding="utf-8")
            (root / "_release").mkdir()
            (root / "_release" / "SharedProject_Foo.xpo").write_text("x", encoding="utf-8")

            found = {p.name for p in gather_files(root)}

        self.assertEqual(found, {"Foo.xpo"})


if __name__ == "__main__":
    unittest.main()
