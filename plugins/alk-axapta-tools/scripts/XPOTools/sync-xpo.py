"""sync-xpo — сверка состава задачи с боевой выгрузкой AOT-Prod.

Read-only сравнение по `(mnemonic, name)` объектов:

  * **New**             — в задаче есть, в AOT-Prod нет. Свежие разработки.
  * **Modifications**   — в обоих местах с тем же именем. Потенциальные правки
                          боевого кода. Подсказка: должен быть маркер
                          axapta-mod-comments в теле.
  * **Missing in task** — в указанном bundle (_release/SharedProject_*.xpo)
                          есть, в xpo/-папке задачи нет. Потерянный исходник.

Запуск:
    sync-xpo --task-root .\\XPO [--prod-root <path>] [--bundle <path>]
             [--with-content-diff]
"""

import argparse
import difflib
import io
import pathlib
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Modules"))
from xpo_types import XPO_TYPES  # noqa: E402
from config import load_config, validate_config, print_config_warnings  # noqa: E402

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


ELEMENT_RE = re.compile(r"^\*\*\*Element:\s*(\w+)\s*$")

# Регулярки имени объекта по mnemonic. Полный набор повторяет
# build-shared-project.NAME_RES, чтобы детектор давал тот же результат.
NAME_RES = {
    "CLS": re.compile(r"^\s*CLASS\s+#(\S+)"),
    "TAB": re.compile(r"^\s*TABLE\s+#(\S+)"),
    "FRM": re.compile(r"^\s*FORM\s+#(\S+)"),
    "MNU": re.compile(r"^\s*MENU\s+#(\S+)"),
    "FTM": re.compile(r"^\s*MENUITEM\s+#(\S+)"),
    # Job не оборачивается в NODE (в отличие от CLASS/TABLE/...) — реальный
    # экспорт AX 2012 идёт сразу JOBVERSION -> SOURCE #<Name> -> PROPERTIES,
    # без JOBNODE. У задачи ровно один SOURCE-блок, и это сам джоб.
    "JOB": re.compile(r"^\s*SOURCE\s+#(\S+)"),
    "QUE": re.compile(r"^\s*QUERY\s+#(\S+)"),
    "MAC": re.compile(r"^\s*MACRO\s+#(\S+)"),
    "EDT": re.compile(r"^\s*EXTENDEDTYPE\s+#(\S+)"),
    "BAS": re.compile(r"^\s*ENUMTYPE\s+#(\S+)"),
    "MAP": re.compile(r"^\s*MAP\s+#(\S+)"),
    "VIE": re.compile(r"^\s*VIEW\s+#(\S+)"),
    "RES": re.compile(r"^\s*RESOURCENODE\s+#(\S+)"),
    "LBF": re.compile(r"^\s*LABELFILE\s+#(\S+)"),
    "SRS": re.compile(r"^\s*SSRSREPORT\s+#(\S+)"),
    "DBT": re.compile(r"^\s*TABLE\s+#(\S+)"),
    "DBE": re.compile(r"^\s*ENUMTYPE\s+#(\S+)"),
    "CON": re.compile(r"^\s*CONFIGURATIONKEY\s+#(\S+)"),
    "UTS": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "UTI": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "UTW": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "UTR": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "UTQ": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "UTE": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "UTU": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "UTG": re.compile(r"^\s*USERTYPE\s+#(\S+)"),
    "SPV": re.compile(r"^\s*PRIVILEGE\s+#(\S+)"),
    "SDT": re.compile(r"^\s*DUTY\s+#(\S+)"),
    "SRL": re.compile(r"^\s*ROLE\s+#(\S+)"),
    "SPC": re.compile(r"^\s*PROCESSCYCLE\s+#(\S+)"),
    "SPO": re.compile(r"^\s*POLICY\s+#(\S+)"),
    "SCP": re.compile(r"^\s*CODEPERMISSION\s+#(\S+)"),
}

# Карта алиасов к каноническим mnemonic (повторяет _AX_MNEMONIC_ALIASES в
# xpo_types). Нужна для нормализации ключа сравнения: задача и Prod могут
# использовать разные мнемоники для одного типа (UTS vs EDT).
CANONICAL = {
    "DBT": "TAB", "DBE": "BAS", "CON": "CFG",
    "UTS": "EDT", "UTI": "EDT", "UTW": "EDT", "UTR": "EDT",
    "UTQ": "EDT", "UTE": "EDT", "UTU": "EDT", "UTG": "EDT",
    "SPV": "PRV", "SDT": "DUT", "SRL": "ROL",
    "SPC": "PCY", "SPO": "POL", "SCP": "CDP",
}


def canonicalize(mnemonic: str) -> str:
    return CANONICAL.get(mnemonic, mnemonic)


def read_head_lines(path: pathlib.Path, limit: int = 200) -> List[str]:
    with open(path, "rb") as f:
        raw = f.read(64 * 1024)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace").splitlines()[:limit]


def detect_element(lines: List[str]) -> Tuple[str, str]:
    mnemonic = ""
    for line in lines:
        m = ELEMENT_RE.match(line)
        if m:
            mnemonic = m.group(1)
            break
    if not mnemonic:
        return ("", "")
    rx = NAME_RES.get(mnemonic)
    if not rx:
        return (mnemonic, "")
    for line in lines:
        m = rx.match(line)
        if m:
            return (mnemonic, m.group(1))
    return (mnemonic, "")


def is_inside_release(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return "_release" in rel.parts


def scan_directory(root: pathlib.Path) -> Dict[Tuple[str, str], pathlib.Path]:
    """Сканирует root рекурсивно (исключая _release/), возвращает индекс
    `(canonical_mnemonic, object_name) → file_path`."""
    index: Dict[Tuple[str, str], pathlib.Path] = {}
    for p in sorted(root.rglob("*.xpo")):
        if p.is_dir():
            continue
        if is_inside_release(p, root):
            continue
        mnemonic, name = detect_element(read_head_lines(p))
        if not mnemonic or not name:
            continue
        key = (canonicalize(mnemonic), name)
        # Первый встретившийся файл побеждает (стабильность сортировки).
        index.setdefault(key, p)
    return index


def scan_bundle(bundle_path: pathlib.Path) -> Set[Tuple[str, str]]:
    """Парсит SharedProject_*.xpo, возвращает множество `(mnemonic, name)`
    объектов из бандла (без PRN/END-маркеров)."""
    with open(bundle_path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    lines = raw.decode("utf-8", errors="replace").splitlines()

    starts: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = ELEMENT_RE.match(line)
        if m:
            starts.append((i, m.group(1)))

    out: Set[Tuple[str, str]] = set()
    for idx, (line_no, kind) in enumerate(starts):
        if kind in ("PRN", "END"):
            continue
        end_no = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        body = lines[line_no:end_no]
        rx = NAME_RES.get(kind)
        if not rx:
            continue
        for line in body[:200]:
            m = rx.match(line)
            if m:
                out.add((canonicalize(kind), m.group(1)))
                break
    return out


def latest_bundle(release_dir: pathlib.Path) -> Optional[pathlib.Path]:
    if not release_dir.is_dir():
        return None
    candidates = sorted(
        (p for p in release_dir.glob("SharedProject_*.xpo") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def short_content_diff(task_file: pathlib.Path, prod_file: pathlib.Path, max_lines: int = 50) -> List[str]:
    """Unified diff первых 200 строк task vs prod (без BOM)."""
    def read(p: pathlib.Path) -> List[str]:
        with open(p, "rb") as f:
            raw = f.read()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return raw.decode("utf-8", errors="replace").splitlines()[:200]

    task_lines = read(task_file)
    prod_lines = read(prod_file)
    diff = list(difflib.unified_diff(
        prod_lines, task_lines,
        fromfile=str(prod_file), tofile=str(task_file),
        lineterm="", n=2,
    ))
    return diff[:max_lines]


def main() -> int:
    print_config_warnings(validate_config())
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="sync-xpo",
        description="Сверка xpo задачи с боевой AOT-Prod (read-only)")
    parser.add_argument("--task-root", required=True, help="папка задачи XPO/")
    parser.add_argument("--prod-root", default=cfg.get("AX_AOT_PATH", ""),
                        help="папка AOT-Prod (по умолчанию из AX_AOT_PATH)")
    parser.add_argument("--bundle", default=None,
                        help="бандл из _release/ (по умолчанию: самый свежий)")
    parser.add_argument("--with-content-diff", action="store_true",
                        help="для каждой Modification напечатать short unified diff")
    args = parser.parse_args()

    task_root = pathlib.Path(args.task_root).resolve()
    if not task_root.is_dir():
        print(f"ERROR: --task-root не существует: {task_root}", file=sys.stderr)
        return 2

    prod_root = pathlib.Path(args.prod_root).resolve() if args.prod_root else None
    if not prod_root or not prod_root.is_dir():
        print(
            "ERROR: --prod-root не указан или не существует. "
            "Укажи через флаг или AX_AOT_PATH (см. /alk-axapta-tools:setup).",
            file=sys.stderr,
        )
        return 2

    bundle_path: Optional[pathlib.Path] = None
    if args.bundle:
        bundle_path = pathlib.Path(args.bundle).resolve()
        if not bundle_path.is_file():
            print(f"ERROR: --bundle не существует: {bundle_path}", file=sys.stderr)
            return 2
    else:
        bundle_path = latest_bundle(task_root / "_release")

    print(f"Task:   {task_root}")
    print(f"Prod:   {prod_root}")
    if bundle_path:
        print(f"Bundle: {bundle_path}")
    else:
        print("Bundle: (нет)")
    print()
    print("Сканирую task...")
    task_index = scan_directory(task_root)
    print(f"  → {len(task_index)} объектов")
    print("Сканирую prod (может занять минуту)...")
    prod_index = scan_directory(prod_root)
    print(f"  → {len(prod_index)} объектов")
    print()

    new_keys = sorted(k for k in task_index if k not in prod_index)
    mod_keys = sorted(k for k in task_index if k in prod_index)
    bundle_keys: Set[Tuple[str, str]] = set()
    if bundle_path:
        bundle_keys = scan_bundle(bundle_path)

    print("=" * 70)
    print(f"NEW ({len(new_keys)})  — есть в задаче, нет в Prod (свежие разработки):")
    for mn, nm in new_keys:
        print(f"  [{mn:>3}] {nm}")
    print()

    print("=" * 70)
    print(f"MODIFICATIONS ({len(mod_keys)})  — поверх боевого кода. "
          "Должен быть маркер axapta-mod-comments внутри файла.")
    for mn, nm in mod_keys:
        print(f"  [{mn:>3}] {nm}")
        if args.with_content_diff:
            diff = short_content_diff(task_index[(mn, nm)], prod_index[(mn, nm)])
            for line in diff:
                print(f"    {line}")
    print()

    missing_keys: List[Tuple[str, str]] = []
    if bundle_path:
        print("=" * 70)
        missing_keys = sorted(k for k in bundle_keys if k not in task_index)
        print(f"MISSING IN TASK ({len(missing_keys)})  — есть в bundle, нет в задаче "
              "(потерянные исходники).")
        for mn, nm in missing_keys:
            print(f"  [{mn:>3}] {nm}")
        print()

    print("=" * 70)
    print(f"Summary: new={len(new_keys)}  modifications={len(mod_keys)}  "
          f"missing_in_task={len(missing_keys)}")
    return 1 if missing_keys else 0


if __name__ == "__main__":
    sys.exit(main())
