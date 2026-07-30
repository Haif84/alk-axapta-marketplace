"""Тесты структурных проверок X++ внутри xpo.

Обе проверки родились из реальных поломок, а не из теории: автоматическая
правка исходников один раз сняла префикс '#' со всех строк (файл внешне
остался валидным, AX его не понял), а другой раз вставила скобку не туда.

Запуск (без pytest):
    python tests/test_validate_xpp.py
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from validate_xpo import (  # noqa: E402
    check_source_prefix,
    check_xpp_brace_balance,
    xpp_code_only,
)

FAKE = pathlib.Path("MyClass.xpo")


def cls_xpo(body_lines) -> str:
    """Класс с одним методом; body_lines — строки X++ БЕЗ префикса."""
    body = "\n".join(f"        #{ln}" for ln in body_lines)
    return (
        "Exportfile for AOT version 1.0 or later\n"
        "Formatversion: 1\n"
        "\n"
        "***Element: CLS\n"
        "\n"
        "  CLSVERSION 1\n"
        "\n"
        "  CLASS #MyClass\n"
        "    METHODS\n"
        "      SOURCE #doWork\n"
        f"{body}\n"
        "      ENDSOURCE\n"
        "    ENDMETHODS\n"
        "  ENDCLASS\n"
        "\n"
        "***Element: END\n"
    )


GOOD = ["void doWork()", "{", "    if (x)", "    {", "        y = 1;", "    }", "}"]


class TestSourcePrefix(unittest.TestCase):

    def test_good(self):
        self.assertEqual(check_source_prefix(FAKE, cls_xpo(GOOD)), [])

    def test_missing_hash_detected(self):
        # Снимаем '#' ровно с одной строки тела, не полагаясь на её точный отступ:
        # первая версия теста промахнулась мимо строки и «ломала» файл вхолостую.
        text = cls_xpo(GOOD)
        target = "        #        y = 1;"
        self.assertIn(target, text, "фикстура должна содержать эту строку")
        broken = text.replace(target, "                y = 1;")

        issues = check_source_prefix(FAKE, broken)
        self.assertEqual(len(issues), 1)
        self.assertIn("без префикса", issues[0].msg)

    def test_counts_all_broken_lines(self):
        """В сообщении должно быть общее число — по одной строке не понять масштаб."""
        broken = cls_xpo(GOOD).replace("        #", "        ")
        issues = check_source_prefix(FAKE, broken)
        self.assertEqual(len(issues), 1)
        self.assertIn(f"{len(GOOD)}", issues[0].msg)


class TestBraceBalance(unittest.TestCase):

    def test_balanced(self):
        self.assertEqual(check_xpp_brace_balance(FAKE, cls_xpo(GOOD)), [])

    def test_missing_closing_brace(self):
        issues = check_xpp_brace_balance(FAKE, cls_xpo(GOOD[:-1]))
        self.assertEqual(len(issues), 1)
        self.assertIn("не сходятся", issues[0].msg)

    def test_brace_in_string_literal_is_not_counted(self):
        """`if (line == '{')` — скобка в литерале, а не открытие блока."""
        body = ["void doWork()", "{", "    if (line == '{')", "    {", "        y = 1;",
                "    }", "}"]
        self.assertEqual(check_xpp_brace_balance(FAKE, cls_xpo(body)), [])

    def test_brace_in_comment_is_not_counted(self):
        body = ["void doWork()", "{", "    // тут скобка { в комментарии", "    y = 1;", "}"]
        self.assertEqual(check_xpp_brace_balance(FAKE, cls_xpo(body)), [])

    def test_block_comment_across_lines(self):
        body = ["void doWork()", "{", "    /* скобка { внутри", "       блочного } комментария */",
                "    y = 1;", "}"]
        self.assertEqual(check_xpp_brace_balance(FAKE, cls_xpo(body)), [])

    def test_multiline_string_literal(self):
        """Литерал через несколько строк — так в X++ вставляют XAML и XML.

        Ровно на этом проверка сначала дала ложную тревогу на боевом
        CIT_DevToolPanel.xamlResources: разбор шёл построчно, состояние кавычек
        сбрасывалось, и скобки из `{TemplateBinding}` считались за код.
        """
        body = [
            "void doWork()",
            "{",
            '    str xaml = @"<Grid Background="""{TemplateBinding Background}""">',
            '        <ColumnDefinition Width="""*"""/>',
            '        </Grid>";',
            "    y = 1;",
            "}",
        ]
        self.assertEqual(check_xpp_brace_balance(FAKE, cls_xpo(body)), [])

    def test_nested_block_comment_is_skipped(self):
        """Вложенный /* внутри /* — метод пропускается, а не объявляется битым.

        Реальный случай из боевого кода (MPJournalFormTrans.formInitPost):
        закомментировали блок, внутри которого уже был свой комментарий.
        Текстовый подсчёт скобок там даёт -3, хотя класс компилируется.
        """
        body = ["void doWork()", "{", "    /*", "    if (a)", "    {",
                "        /*else", "        {", "        }*/", "    }", "}"]
        self.assertEqual(check_xpp_brace_balance(FAKE, cls_xpo(body)), [])

    def test_paired_insert_in_wrong_place_is_NOT_detected(self):
        """Граница применимости, зафиксированная намеренно.

        Парная вставка `{`/`}` не в том месте баланс не нарушает — проверка её
        не увидит. Тест закрепляет это как известное ограничение, чтобы на
        балансе не строили ложной уверенности.
        """
        body = ["void doWork()", "{", "    if (a)", "    {", "        return;",
                "    switch (b)", "    {", "        case 1:", "            c = 1;",
                "    }", "            d = 2;", "    }", "}"]
        self.assertEqual(check_xpp_brace_balance(FAKE, cls_xpo(body)), [])


class TestCodeOnly(unittest.TestCase):

    def test_url_in_literal_is_not_a_comment(self):
        code, _ = xpp_code_only("url = 'http://host/ping';")
        self.assertIn(";", code)

    def test_verbatim_string_with_backslash(self):
        """@'\\Classes\\' — обратный слэш не экранирует закрывающую кавычку."""
        code, _ = xpp_code_only(r"path = @'\Classes\' + name;")
        self.assertTrue(code.rstrip().endswith(";"))

    def test_trailing_comment_removed(self):
        code, _ = xpp_code_only("return;   // штатная ситуация")
        self.assertTrue(code.rstrip().endswith(";"))
        self.assertNotIn("штатная", code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
