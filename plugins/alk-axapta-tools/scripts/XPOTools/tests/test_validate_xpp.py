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
    check_method_name_length,
    check_object_name_length,
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

    def test_lone_cr_inside_source_line(self):
        """Одиночный CR внутри строки исходника — это символ, а не перевод строки.

        Реальный случай (SitesSvcSyncErrorInfoAction.run):
        `case #X:<CR>    this.doIt();` — для AX одна строка с префиксом '#'.
        Разбор через splitlines() видел вторую строку «без префикса» и ругался
        на совершенно целый файл.
        """
        crlf = cls_xpo(GOOD).replace(chr(10), chr(13) + chr(10))
        text = crlf.replace("        #        y = 1;",
                            "        #        y = 1;" + chr(13) + "        z = 2;")
        self.assertEqual(check_source_prefix(FAKE, text), [])
        self.assertEqual(check_xpp_brace_balance(FAKE, text), [])


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


class TestNameLength(unittest.TestCase):
    """Предел 40 символов (EDT SysUtilElementName) — общий для имён объектов
    и методов, оба хранятся в UtilElements.Name. Найдено 04.08.2026 на живом
    компиляторе (Err:110) на методах, которые validate-xpo раньше пропускал."""

    def test_object_name_within_limit_is_clean(self):
        self.assertEqual(check_object_name_length(FAKE, "A" * 40), [])

    def test_object_name_over_limit_is_error(self):
        issues = check_object_name_length(FAKE, "A" * 41)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].level, "ERROR")
        self.assertIn("41", issues[0].msg)

    @staticmethod
    def _method_xpo(method_name: str) -> str:
        """Класс с одним методом по имени SOURCE #<method_name> — то самое имя,
        которое AX хранит в UtilElements.Name (не сигнатура внутри тела)."""
        return (
            "***Element: CLS\n"
            "  CLASS #MyClass\n"
            "    METHODS\n"
            f"      SOURCE #{method_name}\n"
            f"        #void {method_name}()\n"
            "        #{\n"
            "        #}\n"
            "      ENDSOURCE\n"
            "    ENDMETHODS\n"
            "  ENDCLASS\n"
        )

    def test_method_name_within_limit_is_clean(self):
        text = self._method_xpo("a" * 40)
        self.assertEqual(check_method_name_length(FAKE, text), [])

    def test_method_name_over_limit_is_error(self):
        long_name = "a" * 41
        issues = check_method_name_length(FAKE, self._method_xpo(long_name))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].level, "ERROR")
        self.assertIn(long_name, issues[0].msg)

    def test_job_source_name_is_not_double_reported(self):
        """SOURCE #<ИмяДжоба> в ***Element: JOB — это имя объекта, не метода:
        его покрывает check_object_name_length, здесь дублировать не нужно."""
        long_name = "a" * 41
        text = (
            "***Element: JOB\n"
            f"      SOURCE #{long_name}\n"
            f"        #void {long_name}()\n"
            "        #{\n"
            "        #}\n"
            "      ENDSOURCE\n"
        )
        self.assertEqual(check_method_name_length(FAKE, text), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
