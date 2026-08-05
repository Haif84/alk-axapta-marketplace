"""Тест на gather_files — поиск .xpo файлов для fix-mojibake.

До правки 04.08.2026 использовался нерекурсивный `glob("*.xpo")`: на канонической
AOT-раскладке (XPO/Classes/, XPO/Data Dictionary/Tables/, ...), которую сам же
плагин предписывает (см. axapta-project-export), команда `fix-mojibake .\\XPO`
находила 0 файлов и молча ничего не проверяла — "Files: 0; fixed: 0" читается
как "всё чисто", а не как "ничего не просканировано". validate_xpo.gather_files
уже был рекурсивным (`rglob`) — теперь оба модуля ищут одинаково.

Запуск (без pytest):
    python tests/test_fix_mojibake.py
"""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from fix_mojibake import gather_files  # noqa: E402


class TestGatherFiles(unittest.TestCase):
    def test_finds_files_in_nested_aot_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "Classes").mkdir()
            (root / "Classes" / "Foo.xpo").write_text("x", encoding="utf-8")
            (root / "Data Dictionary" / "Tables").mkdir(parents=True)
            (root / "Data Dictionary" / "Tables" / "Bar.xpo").write_text("x", encoding="utf-8")

            found = {p.name for p in gather_files(root)}

        self.assertEqual(found, {"Foo.xpo", "Bar.xpo"})

    def test_excludes_release_at_any_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "Classes").mkdir()
            (root / "Classes" / "Foo.xpo").write_text("x", encoding="utf-8")
            (root / "_release").mkdir()
            (root / "_release" / "SharedProject_Foo.xpo").write_text("x", encoding="utf-8")
            # архив релизов лежит на уровень глубже _release/ — тоже не должен попасть
            (root / "_release" / "_archive").mkdir()
            (root / "_release" / "_archive" / "Old.xpo").write_text("x", encoding="utf-8")

            found = {p.name for p in gather_files(root)}

        self.assertEqual(found, {"Foo.xpo"})

    def test_single_file_target_returned_as_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "Foo.xpo"
            f.write_text("x", encoding="utf-8")

            self.assertEqual(gather_files(f), [f])


if __name__ == "__main__":
    unittest.main()
