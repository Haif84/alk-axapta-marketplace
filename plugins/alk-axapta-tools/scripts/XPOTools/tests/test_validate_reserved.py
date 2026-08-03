"""Тесты проверки зарезервированных слов X++ в именах переменных.

Проверка родилась из реальной поломки и здесь же чинится её продолжение:
объявление `int from;` дважды уехало в AX и дважды не было поймано, потому что
на строку выше стоял обычный комментарий. Сканирование локальных переменных
прекращается на первой строке, не похожей на объявление, — и комментарий,
штатно стоящий среди объявлений, прятал всё, что было под ним.

Запуск (без pytest):
    python tests/test_validate_reserved.py
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from validate_xpo import check_reserved_identifiers  # noqa: E402

FAKE = pathlib.Path("MyClass.xpo")


def method(body: str) -> str:
    """Оборачивает тело метода в минимальный SOURCE-блок xpo."""
    lines = ["    SOURCE #probe"]
    lines += [f"      #{line}" if line else "      #" for line in body.splitlines()]
    lines.append("    ENDSOURCE")
    return "\n".join(lines)


class ReservedIdentifiers(unittest.TestCase):

    def test_plain_declaration_is_reported(self):
        text = method("private void probe()\n{\n    int from;\n    ;\n}")
        issues = check_reserved_identifiers(FAKE, text)
        self.assertEqual(len(issues), 1)
        self.assertIn("'from'", issues[0].msg)

    def test_comment_above_does_not_hide_declaration(self):
        """Комментарий среди объявлений не должен обрывать поиск."""
        text = method("private void probe()\n{\n    // пояснение\n    int from;\n    ;\n}")
        issues = check_reserved_identifiers(FAKE, text)
        self.assertEqual(len(issues), 1, "комментарий спрятал объявление ниже себя")

    def test_macro_directive_does_not_hide_declaration(self):
        text = method("private void probe()\n{\n    #define.limit(10)\n    int from;\n    ;\n}")
        issues = check_reserved_identifiers(FAKE, text)
        self.assertEqual(len(issues), 1, "макро-директива спрятала объявление ниже себя")

    def test_executable_statement_still_stops_the_scan(self):
        """Ради чего ограничение и заводилось: после кода объявлений уже нет.

        `select from ...` — исполняемый оператор; принять его за объявление
        переменной `from` было бы ложным срабатыванием.
        """
        text = method("private void probe()\n{\n    int i;\n    ;\n"
                      "    info(strFmt('%1', i));\n    select from custTable;\n}")
        self.assertEqual(check_reserved_identifiers(FAKE, text), [])

    def test_ordinary_name_is_silent(self):
        text = method("private void probe()\n{\n    // пояснение\n    int counter;\n    ;\n}")
        self.assertEqual(check_reserved_identifiers(FAKE, text), [])


if __name__ == "__main__":
    unittest.main()
