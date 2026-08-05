"""Тесты check_unbound_str_in_query: `str` без объявленной длины в where/like.

Случай не выдуман: ровно на нём в живом проекте компилятор AX дал Err:103
(«Использование контейнеров и полей с неограниченными строками в выражении
WHERE не допускается») сразу в двух методах — сообщение видно только на
компиляции, xpo-импорт его не ловит.

Запуск (без pytest):
    python tests/test_validate_unbound_str.py
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from validate_xpo import check_unbound_str_in_query  # noqa: E402

FAKE = pathlib.Path("MyClass.xpo")


def cls_with_method(body: str) -> str:
    return (
        "***Element: CLS\n"
        "CLASS #MyClass\n"
        "  METHODS\n"
        "    SOURCE #find\n"
        f"{body}"
        "    ENDSOURCE\n"
        "  ENDMETHODS\n"
        "***Element: END\n"
    )


class TestUnboundStrInQuery(unittest.TestCase):

    def test_unbound_param_in_where_flagged(self):
        text = cls_with_method(
            "      #static Foo find(str _sessionId)\n"
            "      #{\n"
            "      #    Foo f;\n"
            "      #    ;\n"
            "      #\n"
            "      #    select firstonly f\n"
            "      #        where f.SessionId == _sessionId;\n"
            "      #\n"
            "      #    return f;\n"
            "      #}\n"
        )
        issues = check_unbound_str_in_query(FAKE, text)
        self.assertEqual(len(issues), 1)
        self.assertIn("_sessionId", issues[0].msg)
        self.assertIn("Err:103", issues[0].msg)

    def test_bound_length_param_is_fine(self):
        text = cls_with_method(
            "      #static Foo find(str 60 _sessionId)\n"
            "      #{\n"
            "      #    Foo f;\n"
            "      #    ;\n"
            "      #\n"
            "      #    select firstonly f\n"
            "      #        where f.SessionId == _sessionId;\n"
            "      #\n"
            "      #    return f;\n"
            "      #}\n"
        )
        self.assertEqual(check_unbound_str_in_query(FAKE, text), [])

    def test_unbound_local_in_where_flagged(self):
        text = cls_with_method(
            "      #static Foo find(int _id)\n"
            "      #{\n"
            "      #    Foo f;\n"
            "      #    str  pattern;\n"
            "      #    ;\n"
            "      #\n"
            "      #    pattern = '*x*';\n"
            "      #\n"
            "      #    select firstonly f\n"
            "      #        where f.Name like pattern;\n"
            "      #\n"
            "      #    return f;\n"
            "      #}\n"
        )
        issues = check_unbound_str_in_query(FAKE, text)
        self.assertEqual(len(issues), 1)
        self.assertIn("pattern", issues[0].msg)

    def test_unbound_str_outside_where_is_fine(self):
        """str без длины, который никогда не попадает в where/like — не ошибка
        этого рода (обычный случай для строк, которые только конкатенируются)."""
        text = cls_with_method(
            "      #static str greet(str _name)\n"
            "      #{\n"
            "      #    return 'Привет, ' + _name;\n"
            "      #}\n"
        )
        self.assertEqual(check_unbound_str_in_query(FAKE, text), [])

    def test_like_outside_select_is_not_query_expression(self):
        """`like` вне query-оператора (обычный `if`) — валидный оператор
        сравнения строк, компилируется нормально. Err:103 — только про
        query-выражения (select/insert_recordset/update_recordset/delete_from);
        флагать здесь unbound-`str` было бы ложным срабатыванием."""
        text = cls_with_method(
            "      #boolean probe(str _mask)\n"
            "      #{\n"
            "      #    str name;\n"
            "      #    ;\n"
            "      #\n"
            "      #    name = 'abc';\n"
            "      #\n"
            "      #    if (name like _mask)\n"
            "      #    {\n"
            "      #        return true;\n"
            "      #    }\n"
            "      #\n"
            "      #    return false;\n"
            "      #}\n"
        )
        self.assertEqual(check_unbound_str_in_query(FAKE, text), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
