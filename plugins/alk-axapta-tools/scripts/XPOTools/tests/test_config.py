"""validate_config: AX_AOT_PATH выведен из обязательных ключей.

С живым MCP-сервером AX офлайн-выгрузка AOT-Prod нужна только sync-xpo,
который сам сообщает об отсутствии пути в момент использования, — поэтому
глобальный preflight-гейт больше не блокируется отсутствием AX_AOT_PATH.

Запуск (без pytest):
    python tests/test_config.py
"""

import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

import config  # noqa: E402

# Полный набор обязательных значений — БЕЗ AX_AOT_PATH.
FULL_ENV = {
    "AX_PROJECT_ID": "ALK_DEVAX12",
    "AX_USER_NICK": "akaz",
    "AX_OBJECT_PREFIX": "alk_",
}


def validate_with_env(env):
    """validate_config() в изоляции: без config-файлов, без .axapta.json,
    ENV ровно такой, как передан (clear=True)."""
    with mock.patch.object(config, "_read_json", return_value={}), \
         mock.patch.object(config, "find_project_config", return_value=None), \
         mock.patch.dict(config.os.environ, env, clear=True):
        return config.validate_config()


class TestAotPathOptional(unittest.TestCase):
    def test_full_config_without_aot_path_passes(self):
        self.assertEqual(validate_with_env(FULL_ENV), [])

    def test_placeholder_aot_path_still_passes(self):
        env = dict(FULL_ENV, AX_AOT_PATH="<path_to_AOT-Prod>")
        self.assertEqual(validate_with_env(env), [])

    def test_other_required_keys_still_blocking(self):
        env = dict(FULL_ENV)
        del env["AX_USER_NICK"]
        errors = validate_with_env(env)
        self.assertTrue(any("AX_USER_NICK" in e for e in errors))
        self.assertFalse(any("AX_AOT_PATH" in e for e in errors))

    def test_empty_env_never_mentions_aot_path(self):
        errors = validate_with_env({})
        self.assertTrue(errors)  # PROJECT_ID, USER_NICK, аффикс — по-прежнему ошибки
        self.assertFalse(any("AX_AOT_PATH" in e for e in errors))


class TestModificationCommentForm(unittest.TestCase):
    def test_dax_hyphen(self):
        self.assertEqual(config.modification_comment_form("DAX-12768"), "DAX_012768")

    def test_dax_underscore_padded(self):
        self.assertEqual(config.modification_comment_form("DAX_012579"), "DAX_012579")

    def test_dax_leading_zeros_stripped_then_padded(self):
        self.assertEqual(config.modification_comment_form("DAX-0011233"), "DAX_011233")

    def test_mod_app_untouched(self):
        self.assertEqual(config.modification_comment_form("MOD-240-APP"), "MOD-240-APP")


class TestAotProjectName(unittest.TestCase):
    def _cfg(self, **kwargs):
        base = {
            "AX_PROJECT_ID": "ALK_DEVAX12",
            "AX_USER_NICK": "akaz",
            "AX_MODIFICATION_ID": "DAX-12579",
            "AX_AOT_PROJECT": "",
        }
        base.update(kwargs)
        return base

    def test_derived_dax(self):
        self.assertEqual(
            config.aot_project_name(self._cfg()),
            "ALK_DEVAX12_DAX_012579_akaz",
        )

    def test_explicit_wins(self):
        self.assertEqual(
            config.aot_project_name(self._cfg(
                AX_AOT_PROJECT="ALK_CDT000_MOD_240_APP_MCPServer_akaz")),
            "ALK_CDT000_MOD_240_APP_MCPServer_akaz",
        )

    def test_missing_mod_empty(self):
        self.assertEqual(config.aot_project_name(self._cfg(AX_MODIFICATION_ID="")), "")


if __name__ == "__main__":
    unittest.main()
