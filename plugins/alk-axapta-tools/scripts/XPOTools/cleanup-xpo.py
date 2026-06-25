"""cleanup-xpo — чистка папки задачи после многократных перекладок и сборок.

Операции (включаются явными флагами, без флагов скрипт ничего не делает):

  --empty-dirs    удалить пустые подпапки внутри --root. _release/ не трогаем,
                  даже если он пустой.
  --keep N        в _release/ оставить N последних SharedProject_*.xpo по mtime.
                  Лишние перемещаются в _release/_archive/ (безопасно).
                  С --purge — физическое удаление (требует --yes).

`--dry-run` показывает план. `--yes` пропускает интерактивное подтверждение.
"""

import argparse
import io
import os
import pathlib
import shutil
import sys
from typing import List

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Modules"))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes", "д", "да")


def plan_empty_dirs(root: pathlib.Path) -> List[pathlib.Path]:
    """Список пустых подпапок (снизу вверх). _release/ и его потомки — пропускаем."""
    candidates: List[pathlib.Path] = []
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        d = pathlib.Path(dirpath)
        if d == root:
            continue
        try:
            rel = d.relative_to(root)
        except ValueError:
            continue
        if "_release" in rel.parts:
            continue
        try:
            if not any(d.iterdir()):
                candidates.append(d)
        except OSError:
            pass
    return candidates


def plan_release_archive(root: pathlib.Path, keep: int):
    """Возвращает (kept, moved) — какие бандлы остаются, какие двигаем
    в _release/_archive/."""
    release = root / "_release"
    if not release.is_dir():
        return [], []
    bundles = sorted(
        (p for p in release.glob("SharedProject_*.xpo") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    kept = bundles[:keep]
    moved = bundles[keep:]
    return kept, moved


def cmd_run(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root не существует: {root}", file=sys.stderr)
        return 2

    if not args.empty_dirs and args.keep is None:
        print("Ничего не делаю: укажи --empty-dirs и/или --keep N.")
        return 0

    empty: List[pathlib.Path] = []
    if args.empty_dirs:
        empty = plan_empty_dirs(root)
        print(f"Пустых папок к удалению: {len(empty)}")
        for d in empty:
            print(f"  - {d.relative_to(root)}")
        print()

    kept: List[pathlib.Path] = []
    moved: List[pathlib.Path] = []
    if args.keep is not None:
        if args.keep < 0:
            print("ERROR: --keep N должно быть >= 0.", file=sys.stderr)
            return 2
        kept, moved = plan_release_archive(root, args.keep)
        print(f"В _release/ оставить: {len(kept)} последних")
        for p in kept:
            print(f"  + {p.name}")
        action = "удалить" if args.purge else "переместить в _release/_archive/"
        print(f"{action.capitalize()}: {len(moved)}")
        for p in moved:
            print(f"  - {p.name}")
        print()

    if args.dry_run:
        print("[dry-run] изменения не применены.")
        return 0

    if not args.yes:
        if not confirm("Применить? [y/N] "):
            print("Отменено.")
            return 0

    if args.purge and moved:
        # Защита от случайного удаления — отдельное подтверждение, если не --yes
        # уже дал согласие, но всё равно повторим: пользователь должен явно
        # подтвердить физическое удаление.
        if not args.yes:
            if not confirm(f"PURGE удалит {len(moved)} файл(ов) безвозвратно. Точно? [y/N] "):
                print("Отменено.")
                return 0

    # 1) Архив/удаление релизов
    if moved:
        archive_dir = root / "_release" / "_archive"
        if not args.purge:
            archive_dir.mkdir(parents=True, exist_ok=True)
        for p in moved:
            if args.purge:
                p.unlink()
            else:
                target = archive_dir / p.name
                if target.exists():
                    # Не перезаписываем — добавляем суффикс.
                    base, ext = p.stem, p.suffix
                    for v in range(2, 100):
                        cand = archive_dir / f"{base}_arch{v}{ext}"
                        if not cand.exists():
                            target = cand
                            break
                shutil.move(str(p), str(target))

    # 2) Пустые папки (после move могли появиться новые — пересчитаем).
    if args.empty_dirs:
        if moved:
            empty = plan_empty_dirs(root)
        for d in empty:
            try:
                d.rmdir()
            except OSError as exc:
                print(f"WARN: не удалось удалить {d}: {exc}", file=sys.stderr)

    print()
    summary = []
    if args.empty_dirs:
        summary.append(f"empty_dirs_removed={len(empty)}")
    if args.keep is not None:
        verb = "purged" if args.purge else "archived"
        summary.append(f"{verb}={len(moved)}")
    print("Done. " + " ".join(summary))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cleanup-xpo",
        description="Чистка папки задачи (пустые подпапки, старые релизы).",
    )
    parser.add_argument("--root", required=True, help="папка задачи XPO/")
    parser.add_argument("--empty-dirs", action="store_true",
                        help="удалить пустые подпапки (кроме _release/)")
    parser.add_argument("--keep", type=int, default=None,
                        help="оставить N последних SharedProject_*.xpo в _release/, "
                             "остальные — в _release/_archive/")
    parser.add_argument("--purge", action="store_true",
                        help="с --keep: физически удалить (опасно), а не архивировать")
    parser.add_argument("--dry-run", action="store_true", help="показать план")
    parser.add_argument("--yes", action="store_true", help="не спрашивать")
    args = parser.parse_args()
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
