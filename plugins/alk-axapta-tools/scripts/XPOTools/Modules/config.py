"""Конфигурация XPOTools.

Источники значений (по убыванию приоритета):
  1. .axapta.json в папке проекта (ищется вверх от текущей директории) —
     перекрывает всё остальное; нужен репозиториям, чья модификация ведётся не
     под глобальным кодом проекта (например CIT000 при AX_PROJECT_ID=ALK_DEVAX12)
  2. Переменные окружения AX_PROJECT_ID, AX_USER_NICK, AX_AOT_PATH,
     AX_OBJECT_PREFIX, AX_OBJECT_SUFFIX
  3. <XPOTools>/config.local.json (gitignored)
  4. <XPOTools>/config.example.json (под git, плейсхолдеры)

Файл проекта задаёт только те ключи, которые нужно перекрыть, — остальные
подхватываются из ENV как обычно. Пустая строка в нём тоже значима (например
"AX_OBJECT_PREFIX": "" при заданном суффиксе), поэтому ключ учитывается по факту
присутствия, а не по непустому значению.

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

# Обязателен, пока минимум XPOTools — Python 3.9: аннотации PEP 604
# (`pathlib.Path | None` в find_project_config) без него вычисляются при импорте
# и роняют весь модуль (а с ним preflight и все команды) с TypeError на 3.9.
from __future__ import annotations

import json
import os
import pathlib

#: Ключи уровня МАШИНЫ: одинаковы для всех задач разработчика.
MACHINE_KEYS = (
    "AX_PROJECT_ID",
    "AX_USER_NICK",
    "AX_AOT_PATH",
    "AX_OBJECT_PREFIX",
    "AX_OBJECT_SUFFIX",
)

#: Ключи уровня ЗАДАЧИ: меняются от модификации к модификации, поэтому их место —
#: .axapta.json рядом с кодом. В машинном ENV они по определению устареют и молча
#: подставятся в соседнем репозитории, где модификация уже другая.
#:
#: Из них собирается мод-маркер целиком:
#:   //{AX_PROJECT_ID}, {AX_MODIFICATION_ID}, {AX_MODIFICATION_DESC}, {дата}, {AX_USER_NICK}
#: а AX_AOT_PROJECT даёт имя AOT-проекта для сборки релиза. Вывести его из
#: AX_PROJECT_ID нельзя: смысловая часть имени и ник произвольные.
MODIFICATION_KEYS = (
    "AX_AOT_PROJECT",
    "AX_MODIFICATION_ID",
    "AX_MODIFICATION_DESC",
)

KEYS = MACHINE_KEYS + MODIFICATION_KEYS

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

# Конфиг уровня папки проекта. Ищется вверх от CWD — так он работает и когда
# инструмент запускают из подкаталога репозитория.
PROJECT_CONFIG_NAME = ".axapta.json"


def find_project_config(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """Ближайший .axapta.json вверх по дереву от start (по умолчанию — CWD)."""
    current = (start or pathlib.Path.cwd()).resolve()
    for folder in (current, *current.parents):
        candidate = folder / PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


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

    # Конфиг проекта — последним, он важнее ENV. Ключ учитывается по присутствию:
    # пустая строка здесь legitimate (гасит унаследованный из ENV префикс, когда
    # проект использует суффикс).
    project_path = find_project_config()
    if project_path:
        project = _read_json(project_path)
        out.update({k: v for k, v in project.items() if k in KEYS})

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


def validate_modification() -> list[str]:
    """Ошибки по ключам уровня ЗАДАЧИ (AX_AOT_PROJECT и параметры маркера).

    Отдельно от validate_config намеренно: без них прекрасно работают чтение
    и раскладка xpo, а нужны они только там, где ставится мод-маркер или
    собирается релиз. Делать их глобально обязательными значило бы ломать
    сценарии, которым они не нужны.
    """
    import re
    placeholder_re = re.compile(r"^<.*>$")
    cfg = load_config()
    errors = []

    for k in MODIFICATION_KEYS:
        v = cfg.get(k, "")
        if not v or placeholder_re.match(v):
            errors.append(
                f"{k} не задан — нужен для мод-маркеров и сборки релиза. "
                f"Задай в .axapta.json проекта (см. /alk-axapta-tools:setup)."
            )

    return errors


def modification_marker(date_str: str, inline: bool = False) -> str:
    """Мод-маркер целиком из конфига. date_str — дата в формате ДД.ММ.ГГГГ.

    Смысл в том, чтобы формат жил в ОДНОМ месте: раньше его собирали руками в
    каждой сессии, и код проекта успел разъехаться с реальным (в одном
    репозитории 24 маркера ушли под неверным кодом).

    Пробел после `//` зависит от места: в шапке объекта и в блоках `+/-`
    маркер стоит отдельной строкой и пишется как `// CIT000, …`, а хвостовой
    комментарий у одиночной вставленной строки — слитно, `код; //CIT000, …`.
    inline=True даёт вторую форму.
    """
    cfg = load_config()
    return (f"//{'' if inline else ' '}{cfg['AX_PROJECT_ID']}, {cfg['AX_MODIFICATION_ID']}, "
            f"{cfg['AX_MODIFICATION_DESC']}, {date_str}, {cfg['AX_USER_NICK']}")


def print_config_warnings(warns: list[str]) -> None:
    import sys
    if warns:
        print("\n".join(warns), file=sys.stderr)
        print("", file=sys.stderr)


if __name__ == "__main__":
    import sys
    cfg = load_config()

    project_path = find_project_config()
    if project_path:
        print(f"[конфиг проекта] {project_path} (перекрывает ENV)")

    print("[машина]")
    for k in MACHINE_KEYS:
        print(f"  {k} = {cfg[k]!r}")

    print("[задача — из .axapta.json]")
    for k in MODIFICATION_KEYS:
        print(f"  {k} = {cfg[k]!r}")

    errors = validate_config()
    if errors:
        print("\n[FAIL] Конфигурация неполная:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # Ключи задачи не блокируют работу целиком — сообщаем, но не валимся:
    # чтение и раскладка xpo без них работают.
    mod_errors = validate_modification()
    if mod_errors:
        print("\n[WARN] Не заданы параметры модификации "
              "(мод-маркеры и сборка релиза работать не будут):", file=sys.stderr)
        for e in mod_errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(0)

    print("\n[OK] Все переменные заданы, включая параметры модификации.")
    sys.exit(0)
