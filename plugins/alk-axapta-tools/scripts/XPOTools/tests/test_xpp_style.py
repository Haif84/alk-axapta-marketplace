"""Проверки оформления X++.

Каждый случай взят из реального прикладного кода Axapta 3.0, который переносили
в AX 2012: одно и то же слово в четырёх написаниях, параметры без подчёркивания,
`a =b ;` и `return` вплотную к предыдущему оператору.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from xpp_style import check_style, mask_code  # noqa: E402


def wrap(body: str) -> list:
    """Оборачивает тело метода в SOURCE-блок, как оно лежит в xpo."""
    lines = ["      SOURCE #someMethod"]
    lines += ["        #" + l for l in body.split("\n")]
    lines.append("      ENDSOURCE")
    return lines


def codes(body: str, affix: str = "_CDT") -> set:
    return {msg.split(":")[0] for _line, msg in check_style(wrap(body), affix)}


class TestMasking(unittest.TestCase):
    def test_slashes_inside_string_are_not_a_comment(self):
        m = mask_code(["info('a // not comment');"])[0]
        self.assertNotIn("//", m.code)
        self.assertIn("info(", m.code)

    def test_block_comment_spans_lines(self):
        got = mask_code(["/* начало", "всё ещё комментарий */ code;"])
        self.assertEqual(got[0].code.strip(), "")
        self.assertIn("code;", got[1].code)


class TestChecks(unittest.TestCase):
    def test_keyword_case(self):
        self.assertIn("keyword-case", codes("void m()\n{\n    if (TRUE)\n    {\n    }\n}"))

    def test_keyword_after_enum_marker_is_not_flagged(self):
        """`Foo::Display` — значение перечисления, а не ключевое слово."""
        self.assertNotIn("keyword-case", codes("void m()\n{\n    x = Foo::Display;\n}"))

    def test_method_name_case(self):
        found = check_style(["      SOURCE #Update", "        #void Update()", "      ENDSOURCE"])
        self.assertTrue(any("method-name-case" in m for _l, m in found))

    def test_del_prefix_is_kept(self):
        """DEL_ — соглашение платформы, а не небрежность."""
        found = check_style(["      SOURCE #DEL_new", "        #void DEL_new()", "      ENDSOURCE"])
        self.assertFalse(any("method-name-case" in m for _l, m in found))

    def test_param_without_underscore(self):
        self.assertIn("param-underscore", codes("void m(int qtyNum)\n{\n}"))

    def test_param_with_underscore_is_fine(self):
        self.assertNotIn("param-underscore", codes("void m(int _qtyNum)\n{\n}"))

    def test_param_layout_two_params_one_line_flagged(self):
        self.assertIn("param-layout", codes("void m(int _a, int _b)\n{\n}"))

    def test_param_layout_multiline_leading_comma_is_fine(self):
        self.assertNotIn("param-layout",
                         codes("void m(\n      int _a\n    , int _b)\n{\n}"))

    def test_param_layout_multiline_trailing_comma_flagged(self):
        self.assertIn("param-layout",
                      codes("void m(\n    int _a,\n    int _b)\n{\n}"))

    def test_param_layout_single_param_is_fine(self):
        self.assertNotIn("param-layout", codes("void m(int _a)\n{\n}"))

    def test_param_layout_default_value_comma_not_miscounted(self):
        """Запятая внутри вызова в значении по умолчанию — не второй параметр."""
        self.assertNotIn("param-layout", codes("void m(str _a = f(1, 2))\n{\n}"))

    def test_param_layout_comment_line_after_bare_paren_first_param_not_miscounted(self):
        """Регрессия: голая '(' на строке объявления, сразу за ней —
        закомментированная строка (маскируется в пустую). Раньше
        `start = first + 2` считал, что первый параметр стоит РОВНО на
        следующей строке, и падал прямо на комментарий — настоящий первый
        параметр (законно без ведущей запятой) получал ложный param-layout."""
        self.assertNotIn(
            "param-layout",
            codes("void m(\n      // счётчики\n      int _a\n    , int _b)\n{\n}"),
        )

    def test_variable_carrying_object_affix(self):
        self.assertIn("var-affix", codes("void m()\n{\n    BMSetup_CDT BMSetup_CDT;\n}"))

    def test_assign_spacing(self):
        got = codes("void m()\n{\n    int a;\n    a =1 ;\n}")
        self.assertIn("assign-spacing", got)

    def test_comparison_is_not_assignment(self):
        self.assertNotIn("assign-spacing", codes("void m()\n{\n    if (a==b)\n    {\n    }\n}"))

    def test_blank_line_before_return(self):
        self.assertIn("blank-before-return",
                      codes("int m()\n{\n    int a;\n    ;\n    a = 1;\n    return a;\n}"))

    def test_return_first_in_block_needs_no_blank_line(self):
        self.assertNotIn("blank-before-return",
                         codes("int m()\n{\n    if (a)\n    {\n        return 1;\n    }\n}"))

    def test_job_name_is_object_name_but_body_is_checked(self):
        """У JOB `SOURCE #Имя` — имя объекта AOT (экспорт идёт без обёртки-узла,
        см. NAME_RES в xpo_types): правило именования методов к нему
        неприменимо. Тело при этом — обычный X++, стилевые проверки работают."""
        job = ["***Element: JOB",
               "      SOURCE #BMInitData",
               "        #static void BMInitData(Args _args)",
               "        #{",
               "        #    int a;",
               "        #    a =1 ;",
               "        #}",
               "      ENDSOURCE"]
        found = check_style(job, "_CDT")
        self.assertFalse(any("method-name-case" in m for _l, m in found),
                         "имя джоба не должно флагаться как имя метода")
        self.assertTrue(any("assign-spacing" in m for _l, m in found),
                        "стилевые проверки тела джоба должны работать")

    def test_verbatim_literal_does_not_poison_following_code(self):
        """@'\\Classes\\' — бэкслеш в verbatim-литерале не экранирует кавычку.

        До фикса состояние «в строке» не закрывалось, и весь код ниже
        маскировался — проверки молча отключались до конца файла."""
        m = mask_code([r"path = @'\Classes\' + name;", "x = 1;"])
        self.assertIn("x = 1;", m[1].code)
        self.assertIn("+ name;", m[0].code)

    def test_verbatim_doubled_quote_is_data(self):
        """@"...""..." — удвоенная кавычка внутри verbatim это данные."""
        m = mask_code(['s = @"a""b" + tail;', "y = 2;"])
        self.assertIn("+ tail;", m[0].code)
        self.assertIn("y = 2;", m[1].code)

    def test_macro_element_is_not_a_method(self):
        """У макроса `SOURCE #Имя` — объявление объекта AOT, а не метода:
        правила именования методов к нему неприменимы."""
        macro = ["***Element: MCR",
                 "      SOURCE #BMScripts_CDT",
                 "        #    #define.sobs('SO-BS')",
                 "      ENDSOURCE"]
        self.assertEqual(check_style(macro, "_CDT"), [])

    def test_clean_code_produces_nothing(self):
        body = ("int m(int _qty)\n"
                "{\n"
                "    int result;\n"
                "    ;\n"
                "    result = _qty * 2;\n"
                "\n"
                "    return result;\n"
                "}")
        self.assertEqual(codes(body), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
