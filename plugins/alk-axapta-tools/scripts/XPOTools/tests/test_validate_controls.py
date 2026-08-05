"""Тесты проверок формы, связанных с CONTROL-блоками:
check_control_autodeclaration и check_invalid_control_properties.

Оба случая взяты из живого поиска в этой же сессии: контрол-обёртка GROUP без
AutoDeclaration, на который тем не менее ссылался код инициализации формы, дал
на импорте Err:9 «Переменная ... не была объявлена»; свойства Label/WidthMode
на STATICTEXT и ShowLabel на TREE молча проглатывались импортом («пропускается
свойство X»), хотя таких свойств у этих типов контролов не существует вовсе —
сверено с боевыми формами SysImportDialog/SysCompareForm в реальном AOT.

Запуск (без pytest):
    python tests/test_validate_controls.py
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from validate_xpo import (  # noqa: E402
    check_control_autodeclaration, check_invalid_control_properties,
)

FAKE = pathlib.Path("MyForm.xpo")


def form_with_controls(init_body: str, controls: str) -> str:
    return (
        "***Element: FRM\n"
        "FORM #MyForm\n"
        "  METHODS\n"
        "    SOURCE #init\n"
        f"{init_body}"
        "    ENDSOURCE\n"
        "  ENDMETHODS\n"
        "  DESIGN\n"
        "    CONTAINER\n"
        f"{controls}"
        "    ENDCONTAINER\n"
        "  ENDDESIGN\n"
        "***Element: END\n"
    )


class TestControlAutoDeclaration(unittest.TestCase):

    def test_undeclared_control_used_in_code_is_flagged(self):
        text = form_with_controls(
            "      #public void init()\n"
            "      #{\n"
            "      #    objectsTree.setImagelist(x);\n"
            "      #}\n",
            "      CONTROL TREE\n"
            "        PROPERTIES\n"
            "          Name                #objectsTree\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        issues = check_control_autodeclaration(FAKE, text, "FRM")
        self.assertEqual(len(issues), 1)
        self.assertIn("objectsTree", issues[0].msg)
        self.assertIn("Err:9", issues[0].msg)

    def test_declared_control_is_not_flagged(self):
        text = form_with_controls(
            "      #public void init()\n"
            "      #{\n"
            "      #    objectsTree.setImagelist(x);\n"
            "      #}\n",
            "      CONTROL TREE\n"
            "        PROPERTIES\n"
            "          Name                #objectsTree\n"
            "          AutoDeclaration     #Yes\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        self.assertEqual(check_control_autodeclaration(FAKE, text, "FRM"), [])

    def test_undeclared_but_unused_control_is_not_flagged(self):
        """Контрол без AutoDeclaration, на который никто не ссылается по имени —
        не ошибка (обычное дело для контролов, управляемых только через datasource)."""
        text = form_with_controls(
            "      #public void init()\n"
            "      #{\n"
            "      #    ;\n"
            "      #}\n",
            "      CONTROL TREE\n"
            "        PROPERTIES\n"
            "          Name                #objectsTree\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        self.assertEqual(check_control_autodeclaration(FAKE, text, "FRM"), [])

    def test_managedhost_exempt_even_without_autodeclaration(self):
        """MANAGEDHOST/ACTIVEX/HTML оборачивают внешний объект — обращение по
        имени работает и без AutoDeclaration (проверено на боевых формах
        ALK_MarkLabelItem, ALK_FilePreview, SysImportDialog)."""
        text = form_with_controls(
            "      #public void init()\n"
            "      #{\n"
            "      #    ManagedHost.control();\n"
            "      #}\n",
            "      CONTROL MANAGEDHOST\n"
            "        PROPERTIES\n"
            "          Name                #ManagedHost\n"
            "          TypeName            #System.Windows.Controls.TabControl\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        self.assertEqual(check_control_autodeclaration(FAKE, text, "FRM"), [])

    def test_non_form_ignored(self):
        text = form_with_controls("      #void x() {}\n", "")
        self.assertEqual(check_control_autodeclaration(FAKE, text, "CLS"), [])


class TestInvalidControlProperties(unittest.TestCase):

    def test_statictext_label_flagged(self):
        text = form_with_controls(
            "      #void x() {}\n",
            "      CONTROL STATICTEXT\n"
            "        PROPERTIES\n"
            "          Name                #ErrorDetailText\n"
            "          Label               #Ошибка\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        issues = check_invalid_control_properties(FAKE, text, "FRM")
        self.assertEqual(len(issues), 1)
        self.assertIn("Label", issues[0].msg)
        self.assertIn("STATICTEXT", issues[0].msg)

    def test_tree_showlabel_flagged(self):
        text = form_with_controls(
            "      #void x() {}\n",
            "      CONTROL TREE\n"
            "        PROPERTIES\n"
            "          Name                #objectsTree\n"
            "          ShowLabel           #No\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        issues = check_invalid_control_properties(FAKE, text, "FRM")
        self.assertEqual(len(issues), 1)
        self.assertIn("ShowLabel", issues[0].msg)

    def test_unbound_stringedit_stringsize_flagged(self):
        text = form_with_controls(
            "      #void x() {}\n",
            "      CONTROL STRINGEDIT\n"
            "        PROPERTIES\n"
            "          Name                #SessionFilterEdit\n"
            "          AutoDeclaration     #Yes\n"
            "          StringSize          #60\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        issues = check_invalid_control_properties(FAKE, text, "FRM")
        self.assertEqual(len(issues), 1)
        self.assertIn("StringSize", issues[0].msg)

    def test_stringedit_label_is_fine(self):
        """Label — валидное свойство StringEdit (в отличие от StringSize у
        несвязанного контрола); блок-лист не должен цеплять чужие пары."""
        text = form_with_controls(
            "      #void x() {}\n",
            "      CONTROL STRINGEDIT\n"
            "        PROPERTIES\n"
            "          Name                #commentEdit\n"
            "          AutoDeclaration     #Yes\n"
            "          Label               #Комментарий\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        self.assertEqual(check_invalid_control_properties(FAKE, text, "FRM"), [])

    def test_non_form_ignored(self):
        text = form_with_controls(
            "      #void x() {}\n",
            "      CONTROL STATICTEXT\n"
            "        PROPERTIES\n"
            "          Name                #X\n"
            "          Label               #Y\n"
            "        ENDPROPERTIES\n"
            "      ENDCONTROL\n",
        )
        self.assertEqual(check_invalid_control_properties(FAKE, text, "CLS"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
