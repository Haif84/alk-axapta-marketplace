"""Тесты проверки каркаса заголовка xpo по эталону AOT-экспорта.

Проверка родилась из реальной поломки: у новых классов не было строки из двух
пробелов после `CLSVERSION 1`. Файл проходил все прежние проверки, а импорт AX
показывал фантомный узел PROPERTIES и терял часть классов.

Запуск (без pytest):
    python tests/test_validate_header_skeleton.py
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from validate_xpo import check_header_skeleton  # noqa: E402

FAKE = pathlib.Path("X.xpo")
DASHES = "; " + "-" * 80


def element(mnemonic, kind, version_line, sep, decl, name="Foo"):
    lines = ["***Element: " + mnemonic, "",
             f"; Microsoft Dynamics AX {kind} unloaded", DASHES,
             version_line]
    if sep is not None:
        lines.append(sep)
    lines.append(decl.format(name=name))
    lines += ["    PROPERTIES", "    ENDPROPERTIES", "", "***Element: END", ""]
    return "\n".join(lines)


GOOD = {
    "CLS": element("CLS", "Class : Foo", "  CLSVERSION 1", "  ", "  CLASS #{name}"),
    "DBT": element("DBT", "Table : Foo", "  TABLEVERSION 1", "  ", "  TABLE #{name}"),
    "DBE": element("DBE", "Enumtype : Foo", "  ENUMTYPEVERSION 1", "  ", "  ENUMTYPE #{name}"),
    "SRO": element("SRO", "ROLE : Foo", "  VERSION 1", "  ", "  ROLE #{name}"),
    "JOB": element("JOB", "Job : Foo", "  JOBVERSION 1", "  ", "SOURCE #{name}"),
    "FRM": element("FRM", "Forms", "FRMVERSION 12", "", "FORM #{name}"),
}


class HeaderSkeleton(unittest.TestCase):

    def test_reference_headers_pass(self):
        for mnemonic, text in GOOD.items():
            with self.subTest(mnemonic):
                self.assertEqual(check_header_skeleton(FAKE, text), [])

    def test_missing_separator_after_clsversion_is_error(self):
        text = element("CLS", "Class : Foo", "  CLSVERSION 1", None, "  CLASS #{name}")
        issues = check_header_skeleton(FAKE, text)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].level, "ERROR")
        self.assertIn("фантомный узел PROPERTIES", issues[0].msg)

    def test_separator_with_wrong_indent_is_error(self):
        text = element("CLS", "Class : Foo", "  CLSVERSION 1", "", "  CLASS #{name}")
        self.assertEqual(len(check_header_skeleton(FAKE, text)), 1)

    def test_form_needs_empty_separator_not_spaces(self):
        text = element("FRM", "Forms", "FRMVERSION 12", "  ", "FORM #{name}")
        self.assertEqual(len(check_header_skeleton(FAKE, text)), 1)

    def test_missing_version_line_is_error(self):
        text = "\n".join(["***Element: CLS", "", "; Microsoft Dynamics AX Class : Foo unloaded",
                          DASHES, "  CLASS #Foo", "  ", "***Element: END", ""])
        issues = check_header_skeleton(FAKE, text)
        self.assertEqual(len(issues), 1)
        self.assertIn("строка версии", issues[0].msg)

    def test_declaration_not_directly_after_separator_is_error(self):
        text = element("CLS", "Class : Foo", "  CLSVERSION 1", "  ", "  ; лишнее\n  CLASS #{name}")
        self.assertEqual(len(check_header_skeleton(FAKE, text)), 1)

    def test_crlf_input_is_accepted(self):
        text = GOOD["CLS"].replace("\n", "\r\n")
        self.assertEqual(check_header_skeleton(FAKE, text), [])

    def test_builder_style_element_is_not_checked(self):
        text = "***Element: CLS\n\n  CLASS #Foo\n***Element: END\n"
        self.assertEqual(check_header_skeleton(FAKE, text), [])

    def test_every_element_of_shared_project_is_checked(self):
        bad = element("CLS", "Class : Bar", "  CLSVERSION 1", None, "  CLASS #{name}", "Bar")
        text = GOOD["CLS"] + bad
        issues = check_header_skeleton(FAKE, text)
        self.assertEqual(len(issues), 1)


if __name__ == "__main__":
    unittest.main()
