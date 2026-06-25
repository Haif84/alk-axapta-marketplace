"""organize-xpo — раскладка/уплощение xpo-файлов задачи под AOT-layout.

Подкоманды:
  organize  плоский xpo/*.xpo → AOT-структура (xpo/Classes/Foo.xpo,
            xpo/Data Dictionary/Tables/Bar.xpo, xpo/Menu Items/Display/...).
            Префикс типа в имени файла удаляется по умолчанию.
  flatten   AOT-структура → плоский xpo/*.xpo с префиксами (обратная операция).

Запуск:
    organize-xpo organize --root .\\XPO [--dry-run | --yes] [--keep-prefix]
    organize-xpo flatten  --root .\\XPO [--dry-run | --yes] [--out <dir>]

Скрипт не модифицирует содержимое файлов — только перемещает их.
_release/ исключается из обработки.
"""

import argparse
import io
import os
import pathlib
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Modules"))
from xpo_types import (  # noqa: E402
    XPO_TYPES,
    DIR_PATH_INDEX,
    PREFIX_INDEX,
    detect_menuitem_subtype,
    dir_path_for,
)

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


ELEMENT_RE = re.compile(r"^\*\*\*Element:\s*(\w+)\s*$")


def read_head_lines(path: pathlib.Path, limit: int = 200) -> List[str]:
    with open(path, "rb") as f:
        raw = f.read(64 * 1024)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace").splitlines()[:limit]


def detect_mnemonic_from_body(path: pathlib.Path) -> str:
    """Прочитать первые ~200 строк и вытащить мнемонику ***Element:."""
    for line in read_head_lines(path):
        m = ELEMENT_RE.match(line)
        if m:
            return m.group(1)
    return ""


def detect_menuitem_subtype_from_body(path: pathlib.Path) -> str:
    """FTM → FTM_DISPLAY/OUTPUT/ACTION по строке `Type ... #Display`."""
    for line in read_head_lines(path):
        s = line.strip()
        if s.startswith("Type") and "#" in s:
            v = s.split("#", 1)[-1].strip().lower()
            if v == "display":
                return "FTM_DISPLAY"
            if v == "output":
                return "FTM_OUTPUT"
            if v == "action":
                return "FTM_ACTION"
    return ""


def is_inside_release(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return "_release" in rel.parts


def strip_prefix(name: str) -> Tuple[str, str]:
    """('Class_ALK_Foo.xpo') → ('Class_', 'ALK_Foo.xpo'). Если префикс
    не найден — ('', name)."""
    for prefix in sorted(PREFIX_INDEX.keys(), key=len, reverse=True):
        if name.startswith(prefix):
            return prefix, name[len(prefix):]
    return "", name


def resolve_mnemonic_for_file(path: pathlib.Path) -> Tuple[str, str]:
    """Возвращает (mnemonic, reason). reason — отладочный: 'prefix' / 'body' / ''."""
    prefix, _ = strip_prefix(path.name)
    if prefix:
        mnemonic = PREFIX_INDEX[prefix]
        # MenuItem*_*.xpo даёт mnemonic с подтипом сразу.
        return mnemonic, "prefix"
    mnemonic = detect_mnemonic_from_body(path)
    if mnemonic == "FTM":
        sub = detect_menuitem_subtype_from_body(path) or "FTM_OUTPUT"
        return sub, "body"
    if mnemonic in XPO_TYPES:
        return mnemonic, "body"
    return "", ""


# ====== organize ============================================================

def plan_organize(root: pathlib.Path, keep_prefix: bool) -> Tuple[List[Dict], List[str], List[str]]:
    """Возвращает (moves, unknowns, collisions). moves — список планируемых
    операций перемещения; unknowns/collisions — ошибки."""
    moves: List[Dict] = []
    unknowns: List[str] = []
    collisions: List[str] = []

    target_index: Dict[pathlib.Path, pathlib.Path] = {}

    for xpo in sorted(root.glob("*.xpo")):
        if xpo.is_dir():
            continue
        mnemonic, _reason = resolve_mnemonic_for_file(xpo)
        if not mnemonic:
            unknowns.append(xpo.name)
            continue

        dir_parts = dir_path_for(mnemonic)
        if not dir_parts:
            unknowns.append(f"{xpo.name} (no dir_path for {mnemonic})")
            continue

        if keep_prefix:
            new_name = xpo.name
        else:
            _, stripped = strip_prefix(xpo.name)
            new_name = stripped

        target = root.joinpath(*dir_parts) / new_name

        if target.exists() and target.resolve() != xpo.resolve():
            collisions.append(f"{xpo.name} → {target}: уже существует")
            continue
        if target in target_index:
            collisions.append(
                f"{xpo.name} → {target}: конфликт с {target_index[target].name}",
            )
            continue
        target_index[target] = xpo

        moves.append({
            "src": xpo,
            "target": target,
            "mnemonic": mnemonic,
        })

    return moves, unknowns, collisions


def print_plan_table(moves: List[Dict], root: pathlib.Path) -> None:
    by_type: Dict[str, int] = {}
    dirs_set = set()
    for m in moves:
        by_type[m["mnemonic"]] = by_type.get(m["mnemonic"], 0) + 1
        dirs_set.add(m["target"].parent)
    print(f"Файлов:    {len(moves)}")
    print(f"Папок:     {len(dirs_set)}")
    print()
    print("По типам:")
    for mn in sorted(by_type):
        print(f"  [{mn:>11}] {by_type[mn]:>3}")
    print()
    print("Примеры перемещений:")
    for m in moves[:10]:
        try:
            rel_target = m["target"].relative_to(root)
        except ValueError:
            rel_target = m["target"]
        print(f"  {m['src'].name:<45} → {rel_target}")
    if len(moves) > 10:
        print(f"  ... и ещё {len(moves) - 10}")


def confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes", "д", "да")


def cmd_organize(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root не существует: {root}", file=sys.stderr)
        return 2

    moves, unknowns, collisions = plan_organize(root, keep_prefix=args.keep_prefix)

    if unknowns:
        print("ERROR: не определён тип у файлов:", file=sys.stderr)
        for u in unknowns:
            print(f"  - {u}", file=sys.stderr)
        print(
            "Добавь mnemonic в Modules/xpo_types.py "
            "(см. axapta-project-export\\SKILL.md §8).",
            file=sys.stderr,
        )
        return 4

    if collisions:
        print("ERROR: коллизии целевых путей:", file=sys.stderr)
        for c in collisions:
            print(f"  - {c}", file=sys.stderr)
        return 4

    if not moves:
        print(f"В {root} нет плоских .xpo для раскладки.")
        return 0

    print(f"Root: {root}")
    print()
    print_plan_table(moves, root)
    print()

    if args.dry_run:
        print("[dry-run] изменения не применены.")
        return 0

    if not args.yes:
        if not confirm("Применить? [y/N] "):
            print("Отменено.")
            return 0

    moved = 0
    for m in moves:
        m["target"].parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(m["src"]), str(m["target"]))
        moved += 1
    print()
    print(f"Перемещено: {moved} файлов.")
    return 0


# ====== flatten =============================================================

def resolve_mnemonic_for_aot_file(path: pathlib.Path, root: pathlib.Path) -> str:
    """Для файла в AOT-layout: определить mnemonic по содержимому, fallback —
    по родительской директории."""
    mnemonic = detect_mnemonic_from_body(path)
    if mnemonic == "FTM":
        # Подтип определяется по родительской папке (Menu Items/Display →
        # FTM_DISPLAY) — это надёжнее, чем парсинг Type в теле.
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        parts = rel.parts[:-1]
        if len(parts) >= 2 and parts[-2] == "Menu Items":
            sub = parts[-1]
            if sub == "Display":
                return "FTM_DISPLAY"
            if sub == "Output":
                return "FTM_OUTPUT"
            if sub == "Action":
                return "FTM_ACTION"
        sub = detect_menuitem_subtype_from_body(path)
        return sub or "FTM_OUTPUT"
    if mnemonic in XPO_TYPES:
        return mnemonic

    # Fallback: по родительской директории.
    try:
        rel = path.relative_to(root)
    except ValueError:
        return ""
    parent_parts = rel.parts[:-1]
    return DIR_PATH_INDEX.get(parent_parts, "")


def plan_flatten(root: pathlib.Path, out: pathlib.Path) -> Tuple[List[Dict], List[str], List[str]]:
    moves: List[Dict] = []
    unknowns: List[str] = []
    collisions: List[str] = []
    target_index: Dict[pathlib.Path, pathlib.Path] = {}

    for xpo in sorted(root.rglob("*.xpo")):
        if xpo.is_dir():
            continue
        if is_inside_release(xpo, root):
            continue
        if xpo.parent == root and out == root:
            # Уже плоский в той же папке — пропустить.
            continue

        mnemonic = resolve_mnemonic_for_aot_file(xpo, root)
        if not mnemonic or mnemonic not in XPO_TYPES:
            unknowns.append(str(xpo.relative_to(root) if xpo.is_relative_to(root) else xpo))
            continue

        meta = XPO_TYPES[mnemonic]
        new_name = meta.get("file_prefix", "") + xpo.stem + ".xpo"
        target = out / new_name

        if target.exists() and target.resolve() != xpo.resolve():
            collisions.append(f"{xpo.name} → {target}: уже существует")
            continue
        if target in target_index:
            collisions.append(
                f"{xpo.name} → {target}: конфликт с {target_index[target]}",
            )
            continue
        target_index[target] = xpo

        moves.append({
            "src": xpo,
            "target": target,
            "mnemonic": mnemonic,
        })

    return moves, unknowns, collisions


def cleanup_empty_dirs(root: pathlib.Path) -> int:
    removed = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        d = pathlib.Path(dirpath)
        if d == root:
            continue
        if "_release" in d.relative_to(root).parts:
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


def cmd_flatten(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root не существует: {root}", file=sys.stderr)
        return 2

    out = pathlib.Path(args.out).resolve() if args.out else root

    moves, unknowns, collisions = plan_flatten(root, out)

    if unknowns:
        print("ERROR: не определён тип у файлов:", file=sys.stderr)
        for u in unknowns:
            print(f"  - {u}", file=sys.stderr)
        return 4

    if collisions:
        print("ERROR: коллизии целевых путей:", file=sys.stderr)
        for c in collisions:
            print(f"  - {c}", file=sys.stderr)
        return 4

    if not moves:
        print(f"В {root} нет AOT-разложенных .xpo для уплощения.")
        return 0

    print(f"Source: {root}")
    print(f"Target: {out}")
    print()
    print_plan_table(moves, root)
    print()

    if args.dry_run:
        print("[dry-run] изменения не применены.")
        return 0

    if not args.yes:
        if not confirm("Применить? [y/N] "):
            print("Отменено.")
            return 0

    out.mkdir(parents=True, exist_ok=True)
    moved = 0
    for m in moves:
        shutil.move(str(m["src"]), str(m["target"]))
        moved += 1
    print()
    print(f"Перемещено: {moved} файлов.")

    if out == root:
        removed = cleanup_empty_dirs(root)
        if removed:
            print(f"Удалено пустых папок: {removed}.")
    return 0


# ====== Main ================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="organize-xpo",
        description="Раскладка/уплощение xpo-файлов задачи под AOT-layout.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    org = sub.add_parser("organize", help="плоский → AOT")
    org.add_argument("--root", required=True, help="папка задачи XPO/")
    org.add_argument("--dry-run", action="store_true", help="показать план, ничего не двигать")
    org.add_argument("--yes", action="store_true", help="не спрашивать подтверждения")
    org.add_argument("--keep-prefix", action="store_true",
                     help="оставить префикс типа в имени файла (legacy)")
    org.set_defaults(func=cmd_organize)

    fl = sub.add_parser("flatten", help="AOT → плоский")
    fl.add_argument("--root", required=True, help="папка задачи XPO/ (AOT-layout)")
    fl.add_argument("--out", default=None, help="выходная папка (по умолчанию = --root)")
    fl.add_argument("--dry-run", action="store_true", help="показать план, ничего не двигать")
    fl.add_argument("--yes", action="store_true", help="не спрашивать подтверждения")
    fl.set_defaults(func=cmd_flatten)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
