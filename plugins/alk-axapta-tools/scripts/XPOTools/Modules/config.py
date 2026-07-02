"""Конфигурация XPOTools.

Источники значений (по убыванию приоритета):
  1. Переменные окружения ALK_PROJECT_PREFIX, ALK_USER_NICK, ALK_AOT_PROD,
     ALK_IDENTIFIER_PREFIX, ALK_IDENTIFIER_SUFFIX
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

KEYS = (
    "ALK_PROJECT_PREFIX",
    "ALK_USER_NICK",
    "ALK_AOT_PROD",
    "ALK_IDENTIFIER_PREFIX",
    "ALK_IDENTIFIER_SUFFIX",
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent  # XPOTools/


def _read_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def check_config() -> list[str]:
    """Возвращает список предупреждений о не заполненных обязательных значениях.
    Вызывать в начале main() каждого инструмента."""
    import sys
    warns = []
    local_path = _ROOT / "config.local.json"
    if not local_path.is_file():
        warns.append(
            f"[SETUP] config.local.json not found at:\n"
            f"  {local_path}\n"
            f"  Copy config.example.json → config.local.json and fill in:\n"
            f"    ALK_PROJECT_PREFIX  (e.g. ALK_DEVAX12)\n"
            f"    ALK_USER_NICK       (your nick for mod-comments)\n"
            f"    ALK_AOT_PROD        (path to AOT-Prod folder)\n"
            f"  Without it marker checks and author info are disabled."
        )
    else:
        cfg = load_config()
        placeholder_re = __import__("re").compile(r"^<.*>$")
        for k in ("ALK_PROJECT_PREFIX", "ALK_USER_NICK"):
            v = cfg.get(k, "")
            if not v or placeholder_re.match(v):
                warns.append(f"[SETUP] {k} is not set in config.local.json — marker checks disabled")
    return warns


def print_config_warnings(warns: list[str]) -> None:
    import sys
    if warns:
        print("\n".join(warns), file=sys.stderr)
        print("", file=sys.stderr)


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
