"""Конфигурация XPOTools.

Источники значений (по убыванию приоритета):
  1. Переменные окружения ALK_PROJECT_PREFIX, ALK_USER_NICK, ALK_AOT_PROD
  2. <XPOTools>/config.local.json (gitignored)
  3. <XPOTools>/config.example.json (под git, плейсхолдеры)

Использование:
    from config import load_config
    cfg = load_config()
    prefix = cfg["ALK_PROJECT_PREFIX"]
"""

import json
import os
import pathlib

KEYS = ("ALK_PROJECT_PREFIX", "ALK_USER_NICK", "ALK_AOT_PROD")

_ROOT = pathlib.Path(__file__).resolve().parent.parent  # XPOTools/


def _read_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def load_config() -> dict:
    example = _read_json(_ROOT / "config.example.json")
    local = _read_json(_ROOT / "config.local.json")
    out = {k: example.get(k, "") for k in KEYS}
    out.update({k: v for k, v in local.items() if k in KEYS})
    for k in KEYS:
        env = os.environ.get(k)
        if env:
            out[k] = env
    return out


if __name__ == "__main__":
    cfg = load_config()
    for k in KEYS:
        print(f"{k} = {cfg[k]!r}")
