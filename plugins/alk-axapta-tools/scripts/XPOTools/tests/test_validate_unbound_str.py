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


    def test_while_select_body_variable_after_where_is_not_flagged(self):
        """Регрессия: `while select ... where ...` не заканчивается `;` —
        заголовок запроса продолжается до `{`. Без отдельной границы по `{`
        тело цикла читалось бы как продолжение того же query-оператора, и
        переменная из info(_msg) внутри тела (а не в самом where) ложно
        флагалась бы как unbound-str в where/like."""
        text = cls_with_method(
            "      #void show(str _msg)\n"
            "      #{\n"
            "      #    CustTable custTable;\n"
            "      #\n"
            "      #    while select custTable\n"
            "      #        where custTable.Blocked == NoYes::No\n"
            "      #    {\n"
            "      #        info(_msg);\n"
            "      #    }\n"
            "      #}\n"
        )
        self.assertEqual(check_unbound_str_in_query(FAKE, text), [])

    def test_while_select_where_itself_still_flagged(self):
        """Граница по `{` не должна тушить проверку целиком — переменная,
        реально использованная В where, обязана флагаться и у while select."""
        text = cls_with_method(
            "      #void show(str _acc)\n"
            "      #{\n"
            "      #    CustTable custTable;\n"
            "      #\n"
            "      #    while select custTable\n"
            "      #        where custTable.AccountNum == _acc\n"
            "      #    {\n"
            "      #        info(custTable.AccountNum);\n"
            "      #    }\n"
            "      #}\n"
        )
        issues = check_unbound_str_in_query(FAKE, text)
        self.assertEqual(len(issues), 1)
        self.assertIn("_acc", issues[0].msg)

    def test_param_after_defaulted_call_argument_still_detected(self):
        """Регрессия: сигнатура бралась плоским `re.search(r"\\(([^)]*)\\)")`,
        обрывавшимся на ПЕРВОЙ `)` — параметр после дефолта с вызовом функции
        (`str _b = f(x)`) терял из виду всё, что шло следом."""
        text = cls_with_method(
            "      #static Foo find(str _a, str _b = SysMCPJSON_CDT::quote(_a), str _c)\n"
            "      #{\n"
            "      #    Foo f;\n"
            "      #    ;\n"
            "      #\n"
            "      #    select firstonly f\n"
            "      #        where f.Name == _c;\n"
            "      #\n"
            "      #    return f;\n"
            "      #}\n"
        )
        issues = check_unbound_str_in_query(FAKE, text)
        self.assertEqual(len(issues), 1)
        self.assertIn("_c", issues[0].msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
