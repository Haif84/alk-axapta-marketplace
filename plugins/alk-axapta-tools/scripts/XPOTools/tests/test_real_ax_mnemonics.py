"""Разбор выгрузки, сделанной самим AX, а не сборщиком проектов.

Регрессия на реальный случай: на выгрузке приложения из 555 элементов
split_shared_project молча пропускал 256 объектов — каждую таблицу, EDT,
перечисление и ключ конфигурации, — потому что NAME_RES ключевался
каноническими мнемониками (TAB, EDT, BAS, CFG), а AX пишет в ***Element свои
(DBT, UTS, DBE, CON). Плюс каждый пункт меню уезжал в Output, и одноимённые
пункты разных подтипов затирали друг друга на диске.
"""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

import split_shared_project as splitter  # noqa: E402
from xpo_types import (  # noqa: E402
    find_object_name, name_re_for, detect_menuitem_subtype_from_lines,
)


class TestNameDetection(unittest.TestCase):
    """Имя объекта берётся по мнемонике из выгрузки, а не по канонической."""

    CASES = [
        ("DBT", "  TABLE #BMRunStat", "BMRunStat"),
        ("DBE", "  ENUMTYPE #BMStatus", "BMStatus"),
        ("CON", "  CONFIGURATIONKEY #BM", "BM"),
        ("UTS", "  USERTYPE #BMRunId", "BMRunId"),
        ("UTI", "  USERTYPE #BMLoops", "BMLoops"),
        ("UTR", "  USERTYPE #BMASU", "BMASU"),
        ("UTE", "  USERTYPE #BMScopeVersion", "BMScopeVersion"),
        ("UTQ", "  USERTYPE #BMDBCon", "BMDBCon"),
        ("UTD", "  USERTYPE #BMFinishDate", "BMFinishDate"),
        ("UTT", "  USERTYPE #BMFinishTime", "BMFinishTime"),
        ("RG", "  REPORT #BMLabComputers", "BMLabComputers"),
        ("MCR", "  SOURCE #BMScripts", "BMScripts"),
        ("CLS", "  CLASS #BMInit", "BMInit"),
        ("EDT", "  EXTENDEDTYPE #SomeType", "SomeType"),
        ("MAC", "  MACRO #SomeMacro", "SomeMacro"),
    ]

    def test_name_found_for_every_mnemonic(self):
        for mnemonic, line, expected in self.CASES:
            with self.subTest(mnemonic=mnemonic):
                self.assertIsNotNone(name_re_for(mnemonic),
                                     f"нет регекспа для {mnemonic}")
                self.assertEqual(find_object_name(mnemonic, [line]), expected)


class TestMenuItemSubtype(unittest.TestCase):
    """Подтип пункта меню — из строки `Type: N`, как её пишет AX."""

    def test_numeric_form(self):
        for code, expected in (("1", "FTM_DISPLAY"), ("2", "FTM_OUTPUT"), ("3", "FTM_ACTION")):
            with self.subTest(code=code):
                body = ["  MENUITEM #Foo", f"    Type: {code}"]
                self.assertEqual(detect_menuitem_subtype_from_lines(body), expected)

    def test_word_form_still_supported(self):
        body = ["  MENUITEM #Foo", "    Type                #Action"]
        self.assertEqual(detect_menuitem_subtype_from_lines(body), "FTM_ACTION")

    def test_unknown_is_empty_not_output(self):
        """Пустая строка, а не FTM_OUTPUT: прежний молчаливый дефолт и приводил
        к тому, что все пункты меню оказывались в одной папке."""
        self.assertEqual(detect_menuitem_subtype_from_lines(["  MENUITEM #Foo"]), "")

    def test_subtype_mnemonic_still_resolves_name(self):
        """Регрессия: detect_object уточняет FTM до FTM_DISPLAY ДО поиска имени.

        Без сведения FTM_* -> FTM в name_re_for каждый пункт меню оставался
        безымянным — и проверки дублей и длины имени для них молча отключались
        (ложные дубли «исчезали» через потерю имени, а не через подтипы).
        """
        for sub in ("FTM_DISPLAY", "FTM_OUTPUT", "FTM_ACTION"):
            with self.subTest(sub=sub):
                self.assertEqual(
                    find_object_name(sub, ["  MENUITEM #BMBuild"]), "BMBuild")


BUNDLE = """Exportfile for AOT version 1.0 or later
Formatversion: 1

***Element: DBT

  TABLE #BMRunStat
  ENDTABLE

***Element: UTS

  USERTYPE #BMRunId
  ENDUSERTYPE

***Element: RG

  REPORT #BMLabComputers
  ENDREPORT

***Element: FTM

  MENUITEM #BMBuild
    Type: 1
  ENDMENUITEM

***Element: FTM

  MENUITEM #BMBuild
    Type: 3
  ENDMENUITEM

***Element: END
"""


class TestSplitRealExport(unittest.TestCase):
    def test_every_element_lands_in_its_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "bundle.xpo"
            src.write_text(BUNDLE, encoding="utf-8")
            out = pathlib.Path(tmp) / "out"
            written = splitter.split_bundle(src, out, layout="aot")

        self.assertEqual(len(written), 5, "ни один элемент не должен потеряться")
        produced = {pathlib.Path(p).relative_to(out).as_posix() for _, p in written}
        self.assertEqual(produced, {
            "Data Dictionary/Tables/BMRunStat.xpo",
            "Data Dictionary/Extended Data Types/BMRunId.xpo",
            "Reports/BMLabComputers.xpo",
            # одноимённые пункты меню разных подтипов — в разные папки,
            # раньше второй затирал первый
            "Menu Items/Display/BMBuild.xpo",
            "Menu Items/Action/BMBuild.xpo",
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)
