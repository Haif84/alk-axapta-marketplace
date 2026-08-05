"""Тесты структурной проверки формы (check_form_objectbank).

Оба «плохих» варианта — не выдумка: ровно на них подряд упал импорт в AX 2012 при
ручной сборке формы диалога, причём балансировка блоков их не видит (скобки
сходятся), а сообщения AX уводят в сторону.

Запуск (без pytest):
    python tests/test_validate_form.py
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from validate_xpo import check_control_nesting, check_form_objectbank  # noqa: E402

FAKE = pathlib.Path("MyDialog.xpo")


def form_xpo(objectbank: str) -> str:
    """Минимальная форма с подставляемым блоком OBJECTBANK."""
    return (
        "Exportfile for AOT version 1.0 or later\n"
        "Formatversion: 1\n"
        "\n"
        "***Element: FRM\n"
        "\n"
        "FRMVERSION 12\n"
        "\n"
        "FORM #MyDialog\n"
        "  PROPERTIES\n"
        "    Name                #MyDialog\n"
        "  ENDPROPERTIES\n"
        "\n"
        "  METHODS\n"
        "  ENDMETHODS\n"
        f"{objectbank}"
        "\n"
        "  REFERENCEDATASOURCES\n"
        "  ENDREFERENCEDATASOURCES\n"
        "\n"
        "ENDFORM\n"
        "\n"
        "***Element: END\n"
    )


#: Канон для формы БЕЗ источников данных — снят с боевой выгрузки AX 2012.
GOOD_BANK = (
    "  OBJECTBANK\n"
    "    PROPERTIES\n"
    "    ENDPROPERTIES\n"
    "\n"
    "  ENDOBJECTBANK\n"
)

#: AX: «ожидалось ENDFORM, но обнаружено REFERENCEDATASOURCES».
EMPTY_BANK = (
    "  OBJECTBANK\n"
    "  ENDOBJECTBANK\n"
)

#: AX: «ожидалось OBJECTPOOL, но обнаружено METHODS».
DATASOURCE_WITHOUT_POOL = (
    "  OBJECTBANK\n"
    "    PROPERTIES\n"
    "    ENDPROPERTIES\n"
    "\n"
    "    DATASOURCE\n"
    "      METHODS\n"
    "      ENDMETHODS\n"
    "    ENDDATASOURCE\n"
    "  ENDOBJECTBANK\n"
)

#: Форма С источником данных: METHODS законен, но только ПОСЛЕ ENDOBJECTPOOL.
BANK_WITH_DATASOURCE = (
    "  OBJECTBANK\n"
    "    PROPERTIES\n"
    "    ENDPROPERTIES\n"
    "\n"
    "    DATASOURCE\n"
    "      OBJECTPOOL\n"
    "        PROPERTIES\n"
    "          Name                #MyTable\n"
    "        ENDPROPERTIES\n"
    "\n"
    "        FIELDLIST\n"
    "        ENDFIELDLIST\n"
    "      ENDOBJECTPOOL\n"
    "      METHODS\n"
    "      ENDMETHODS\n"
    "    ENDDATASOURCE\n"
    "  ENDOBJECTBANK\n"
)


class TestFormObjectBank(unittest.TestCase):

    def test_good_form_without_datasource(self):
        issues = check_form_objectbank(FAKE, form_xpo(GOOD_BANK), "FRM")
        self.assertEqual(issues, [], "канон формы без источников не должен ругаться")

    def test_good_form_with_datasource(self):
        issues = check_form_objectbank(FAKE, form_xpo(BANK_WITH_DATASOURCE), "FRM")
        self.assertEqual(issues, [], "форма с источником данных законна")

    def test_empty_objectbank_rejected(self):
        issues = check_form_objectbank(FAKE, form_xpo(EMPTY_BANK), "FRM")
        self.assertEqual(len(issues), 1)
        self.assertIn("пустой OBJECTBANK", issues[0].msg)

    def test_datasource_without_objectpool_rejected(self):
        issues = check_form_objectbank(FAKE, form_xpo(DATASOURCE_WITHOUT_POOL), "FRM")
        self.assertEqual(len(issues), 1)
        self.assertIn("DATASOURCE без OBJECTPOOL", issues[0].msg)

    def test_non_form_ignored(self):
        """Проверка касается только форм: у класса блока OBJECTBANK нет вовсе."""
        issues = check_form_objectbank(FAKE, form_xpo(EMPTY_BANK), "CLS")
        self.assertEqual(issues, [])


def design_xpo(container: str) -> str:
    """Минимальная форма с подставляемым содержимым DESIGN."""
    return (
        "Exportfile for AOT version 1.0 or later\n"
        "Formatversion: 1\n"
        "\n"
        "***Element: FRM\n"
        "\n"
        "FRMVERSION 12\n"
        "\n"
        "FORM #MyDialog\n"
        "  PROPERTIES\n"
        "    Name                #MyDialog\n"
        "  ENDPROPERTIES\n"
        "\n"
        "  METHODS\n"
        "  ENDMETHODS\n"
        "\n"
        "  DESIGN\n"
        "    CONTAINER\n"
        f"{container}"
        "    ENDCONTAINER\n"
        "  ENDDESIGN\n"
        "\n"
        "ENDFORM\n"
        "\n"
        "***Element: END\n"
    )


#: Канон — Grid и его поля-столбцы плоские сиблинги, связь только через
#: HierarchyParent. Снят с боевой выгрузки AX 2012 (сканирование 400 форм).
FLAT_SIBLINGS = (
    "      CONTROL GRID\n"
    "        PROPERTIES\n"
    "          Name                #Grid\n"
    "          HierarchyParent     #TabPage\n"
    "        ENDPROPERTIES\n"
    "        METHODS\n"
    "        ENDMETHODS\n"
    "      ENDCONTROL\n"
    "\n"
    "      CONTROL STRINGEDIT\n"
    "        PROPERTIES\n"
    "          Name                #Label\n"
    "          HierarchyParent     #Grid\n"
    "        ENDPROPERTIES\n"
    "        METHODS\n"
    "        ENDMETHODS\n"
    "      ENDCONTROL\n"
)

#: AX: «ожидалось ENDCONTROL, но обнаружено CONTROL» — фатально, импорт не проходит.
NESTED_CONTROL = (
    "      CONTROL GRID\n"
    "        PROPERTIES\n"
    "          Name                #Grid\n"
    "          HierarchyParent     #TabPage\n"
    "        ENDPROPERTIES\n"
    "        METHODS\n"
    "        ENDMETHODS\n"
    "\n"
    "        CONTROL STRINGEDIT\n"
    "          PROPERTIES\n"
    "            Name                #Label\n"
    "            HierarchyParent     #Grid\n"
    "          ENDPROPERTIES\n"
    "          METHODS\n"
    "          ENDMETHODS\n"
    "        ENDCONTROL\n"
    "\n"
    "      ENDCONTROL\n"
)


class TestControlNesting(unittest.TestCase):

    def test_flat_siblings_pass(self):
        issues = check_control_nesting(FAKE, design_xpo(FLAT_SIBLINGS), "FRM")
        self.assertEqual(issues, [], "плоские сиблинги с HierarchyParent — канон, не ошибка")

    def test_physically_nested_control_rejected(self):
        issues = check_control_nesting(FAKE, design_xpo(NESTED_CONTROL), "FRM")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].level, "ERROR")
        self.assertIn("вложен внутрь CONTROL", issues[0].msg)

    def test_non_form_ignored(self):
        issues = check_control_nesting(FAKE, design_xpo(NESTED_CONTROL), "CLS")
        self.assertEqual(issues, [])

    def test_control_keyword_outside_design_ignored(self):
        """CONTROL #Name в PERMISSIONS — другая, не связанная с DESIGN конструкция
        (право доступа к конкретному контролу), проверка её не должна касаться."""
        text = (
            design_xpo(FLAT_SIBLINGS)
            .replace("ENDFORM\n", "")
            + "  PERMISSIONS #Permissions\n"
            + "    PERMISSIONSET #Read\n"
            + "      FORM #Controls\n"
            + "        CONTROL #Grid\n"
            + "          PROPERTIES\n"
            + "          ENDPROPERTIES\n"
            + "        CONTROL #Label\n"
            + "          PROPERTIES\n"
            + "          ENDPROPERTIES\n"
            + "      ENDFORM\n"
            + "    ENDPERMISSIONSET\n"
            + "  ENDPERMISSIONS\n"
            + "ENDFORM\n"
        )
        self.assertEqual(check_control_nesting(FAKE, text, "FRM"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
