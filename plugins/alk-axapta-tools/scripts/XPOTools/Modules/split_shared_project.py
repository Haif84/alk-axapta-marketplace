"""split_shared_project — обратная операция к build-shared-project.

Принимает SharedProject_*.xpo (бандл AOT Project + тела всех его объектов в одном
файле) и нарезает его обратно на отдельные `<file_prefix><Name>.xpo` (CLS → Class_,
MNU → Menu_, FTM → MenuItemDisplay_/MenuItemOutput_/MenuItemAction_ и т.д.).

Применение:
  - Round-trip-проверка корректности сборки.
  - Восстановление XPO/*.xpo при потере исходников (когда в _release/ есть
    финальный бандл, а отдельные файлы стёрлись).

Запуск:
    python -m Modules.split_shared_project <bundle.xpo> --out <dir>
    split-shared-project <bundle.xpo> --out <dir>           (через bin/-обёртку)
"""

import argparse
import io
import os
import pathlib
import re
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from xpo_types import (  # noqa: E402
    XPO_TYPES, dir_path_for, find_object_name, detect_menuitem_subtype_from_lines,
)

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


ELEMENT_RE = re.compile(r"^\*\*\*Element:\s*(\w+)\s*$")


def read_lines(path: str) -> List[str]:
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8").splitlines()


def write_xpo(path: str, content: str) -> None:
    if not content.endswith("\n"):
        content += "\n"
    body = content.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(body)


def find_name(mnemonic: str, lines: List[str]) -> str:
    """Имя объекта. Алиасы мнемоник разрешает общая таблица в xpo_types."""
    return find_object_name(mnemonic, lines)


def split_bundle(src: pathlib.Path, dst: pathlib.Path, layout: str = "flat") -> List[Tuple[str, str]]:
    lines = read_lines(str(src))

    # Индексы строк, где встречается ***Element: ...
    starts: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = ELEMENT_RE.match(line)
        if m:
            starts.append((i, m.group(1)))
    if not starts:
        raise SystemExit(f"no ***Element markers in {src}")

    dst.mkdir(parents=True, exist_ok=True)

    written: List[Tuple[str, str]] = []
    for idx, (line_no, kind) in enumerate(starts):
        if kind in ("PRN", "END"):
            continue
        end_no = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        body = lines[line_no:end_no]
        while body and body[-1].strip() == "":
            body.pop()

        # Определяем mnemonic для FTM с подтипом.
        if kind == "FTM":
            mnemonic = detect_menuitem_subtype_from_lines(body)
            if not mnemonic:
                print(f"WARNING: не удалось определить подтип MenuItem "
                      f"(line {line_no + 1}), skipped", file=sys.stderr)
                continue
        else:
            mnemonic = kind

        meta = XPO_TYPES.get(mnemonic)
        if not meta:
            print(f"WARNING: unknown ***Element {kind} (line {line_no + 1}), skipped", file=sys.stderr)
            continue
        name = find_name(kind, body)
        if not name:
            print(f"WARNING: no name for {kind} at line {line_no + 1}, skipped", file=sys.stderr)
            continue

        out = "Exportfile for AOT version 1.0 or later\n"
        out += "Formatversion: 1\n"
        out += "\n"
        out += "\n".join(body)
        out += "\n\n***Element: END\n"

        if layout == "aot":
            sub_parts = dir_path_for(mnemonic)
            target_dir = dst.joinpath(*sub_parts) if sub_parts else dst
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{name}.xpo"
        else:
            target = dst / f"{meta['file_prefix']}{name}.xpo"

        # Молчаливая перезапись означала бы потерю объекта: одноимённые пункты
        # меню разных подтипов и раньше затирали друг друга именно так.
        if target.exists():
            print(f"WARNING: {target} уже существует, пропущен второй объект "
                  f"{kind} {name} (line {line_no + 1})", file=sys.stderr)
            continue

        write_xpo(str(target), out)
        written.append((kind, str(target)))
        print(f"  + {target}")

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Разбор SharedProject_*.xpo на отдельные xpo")
    parser.add_argument("bundle", help="Путь к SharedProject_*.xpo")
    parser.add_argument("--out", required=True, help="Выходная директория")
    parser.add_argument("--layout", choices=("flat", "aot"), default="flat",
                        help="flat (по умолчанию): Class_Foo.xpo в корне out. "
                             "aot: Foo.xpo в подпапках Classes/, Data Dictionary/Tables/, ...")
    args = parser.parse_args()

    src = pathlib.Path(args.bundle).resolve()
    if not src.is_file():
        print(f"ERROR: bundle не найден: {src}", file=sys.stderr)
        return 2

    dst = pathlib.Path(args.out).resolve()
    written = split_bundle(src, dst, layout=args.layout)
    print()
    print(f"Wrote {len(written)} файлов в {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
