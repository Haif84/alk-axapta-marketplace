"""Конфигурация XPOTools.

Источники значений (по убыванию приоритета):
  1. Переменные окружения AX_PROJECT_ID, AX_USER_NICK, AX_AOT_PATH,
     AX_OBJECT_PREFIX, AX_OBJECT_SUFFIX
  2. <XPOTools>/config.local.json (gitignored)
  3. <XPOTools>/config.example.json (под git, плейсхолдеры)

Все пять ключей обязательны (см. validate_config()), кроме пары
AX_OBJECT_PREFIX/AX_OBJECT_SUFFIX — из них должен быть задан РОВНО ОДИН.

Старые ALK_*-ключи в config.local.json (до переименования в AX_*) мигрируются реально:
подхватываются как значения новых ключей, старые удаляются, файл переписывается один раз
(см. _migrate_legacy_local_config). ENV мигрируется отдельно скриптом setup-env.ps1.

Использование:
    from config import load_config, validate_config
    cfg = load_config()
    project_id = cfg["AX_PROJECT_ID"]

Preflight-гейт для скиллов — прогнать этот файл напрямую:
    python config.py
exit code 0 = конфигурация полная, 1 = есть ошибки (см. stderr).
"""

import json
import os
import pathlib

KEYS = (
    "AX_PROJECT_ID",
    "AX_USER_NICK",
    "AX_AOT_PATH",
    "AX_OBJECT_PREFIX",
    "AX_OBJECT_SUFFIX",
)

# Старые имена (до переименования ALK_* -> AX_*) -> новые. Используется только для
# реальной миграции config.local.json (см. _migrate_legacy_local_config); HINT-ключ
# не входит в KEYS, но тоже переименовывается для чистоты файла.
_LEGACY_KEY_MAP = {
    "ALK_PROJECT_PREFIX": "AX_PROJECT_ID",
    "ALK_USER_NICK": "AX_USER_NICK",
    "ALK_AOT_PROD": "AX_AOT_PATH",
    "ALK_IDENTIFIER_PREFIX": "AX_OBJECT_PREFIX",
    "ALK_IDENTIFIER_SUFFIX": "AX_OBJECT_SUFFIX",
    "ALK_IDENTIFIER_PREFIX_HINT": "AX_OBJECT_PREFIX_HINT",
}

_ROOT = pathlib.Path(__file__).resolve().parent.parent  # XPOTools/


def _read_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def _migrate_legacy_local_config(local: dict) -> dict:
    """Реальная миграция config.local.json: старые ALK_*-ключи (до переименования в
    AX_*) подхватываются как значения новых ключей, если новые ещё не заданы, старые
    удаляются, файл переписывается один раз. Зеркалит миграцию ENV в setup-env.ps1 —
    без этого config.local.json со старыми ключами молча читался бы как пустой после
    переименования KEYS, и validate_config() сообщал бы "всё не задано" тем, кто уже
    настраивал плагин."""
    changed = False
    for old_key, new_key in _LEGACY_KEY_MAP.items():
        if old_key not in local:
            continue
        old_value = local.pop(old_key)
        if not local.get(new_key):
            local[new_key] = old_value
        changed = True

    if changed:
        local_path = _ROOT / "config.local.json"
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(local, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return local


def load_config() -> dict:
    example = _read_json(_ROOT / "config.example.json")
    local = _migrate_legacy_local_config(_read_json(_ROOT / "config.local.json"))
    out = {k: example.get(k, "") for k in KEYS}
    out.update({k: v for k, v in local.items() if k in KEYS})
    for k in KEYS:
        env = os.environ.get(k)
        if env:
            out[k] = env
    return out


def validate_config() -> list[str]:
    """Возвращает список БЛОКИРУЮЩИХ ошибок конфигурации.
    Пустой список = все обязательные значения заданы, можно продолжать.
    Плейсхолдеры вида '<...>' (из config.example.json) считаются незаполненными."""
    import re
    placeholder_re = re.compile(r"^<.*>$")
    cfg = load_config()
    errors = []

    for k in ("AX_PROJECT_ID", "AX_USER_NICK", "AX_AOT_PATH"):
        v = cfg.get(k, "")
        if not v or placeholder_re.match(v):
            errors.append(f"{k} не задан. Запусти /alk-axapta-tools:setup.")

    prefix = cfg.get("AX_OBJECT_PREFIX", "")
    suffix = cfg.get("AX_OBJECT_SUFFIX", "")
    prefix_set = bool(prefix) and not placeholder_re.match(prefix)
    suffix_set = bool(suffix) and not placeholder_re.match(suffix)
    if not prefix_set and not suffix_set:
        errors.append(
            "Ни AX_OBJECT_PREFIX, ни AX_OBJECT_SUFFIX не заданы — нужен ровно один. "
            "Запусти /alk-axapta-tools:setup."
        )
    elif prefix_set and suffix_set:
        errors.append(
            f"Заданы оба одновременно: AX_OBJECT_PREFIX={prefix!r} и "
            f"AX_OBJECT_SUFFIX={suffix!r} — нужен ровно один, а не оба."
        )

    return errors


def print_config_warnings(warns: list[str]) -> None:
    import sys
    if warns:
        print("\n".join(warns), file=sys.stderr)
        print("", file=sys.stderr)


if __name__ == "__main__":
    import sys
    cfg = load_config()
    for k in KEYS:
        print(f"{k} = {cfg[k]!r}")

    errors = validate_config()
    if errors:
        print("\n[FAIL] Конфигурация неполная:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print("\n[OK] Все обязательные переменные заданы.")
    sys.exit(0)
