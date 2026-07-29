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

from validate_xpo import check_form_objectbank  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
