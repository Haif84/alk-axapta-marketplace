"""validate_xpo — статический валидатор xpo-файлов MS Dynamics AX 2012.

Проверки:
  1. BOM (UTF-8 BOM в начале файла) и CRLF (никаких одиночных \\n).
  2. Балансировка блоков: PROJECT/ENDPROJECT, GROUP/ENDGROUP,
     BEGINNODE/ENDNODE, SOURCE/ENDSOURCE, PROPERTIES/ENDPROPERTIES.
  3. Mojibake — типичные артефакты двойной перекодировки CP1251↔UTF-8↔CP1252.
  4. Наличие маркеров axapta-mod-comments (`//<PREFIX>...` или `#//<PREFIX>...`
     внутри SOURCE) хотя бы один раз в каждом .xpo с исключением Resource/LabelFile.
  5. Уникальность имён объектов между .xpo (две CLS с одним именем = ошибка).

Запуск:
    python -m Modules.validate_xpo <file_or_dir> [--strict]
    validate-xpo <file_or_dir>           (через bin/-обёртку)
"""

import argparse
import io
import os
import pathlib
import re
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from xpo_types import XPO_TYPES, NO_MARKER_REQUIRED, dir_path_for  # noqa: E402
from config import load_config  # noqa: E402

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


ELEMENT_RE = re.compile(r"^\*\*\*Element:\s*(\w+)\s*$")
NAME_RES = {
    "CLS": re.compile(r"^\s*CLASS\s+#(\S+)"),
    "TAB": re.compile(r"^\s*TABLE\s+#(\S+)"),
    "FRM": re.compile(r"^\s*FORM\s+#(\S+)"),
    "MNU": re.compile(r"^\s*MENU\s+#(\S+)"),
    "FTM": re.compile(r"^\s*MENUITEM\s+#(\S+)"),
    "JOB": re.compile(r"^\s*JOBNODE\s+#(\S+)"),
    "QUE": re.compile(r"^\s*QUERY\s+#(\S+)"),
    "MAC": re.compile(r"^\s*MACRO\s+#(\S+)"),
    "EDT": re.compile(r"^\s*EXTENDEDTYPE\s+#(\S+)"),
    "BAS": re.compile(r"^\s*ENUMTYPE\s+#(\S+)"),
    "MAP": re.compile(r"^\s*MAP\s+#(\S+)"),
    "VIE": re.compile(r"^\s*VIEW\s+#(\S+)"),
    "RES": re.compile(r"^\s*RESOURCENODE\s+#(\S+)"),
    "LBF": re.compile(r"^\s*LABELFILE\s+#(\S+)"),
    "SRS": re.compile(r"^\s*SSRSREPORT\s+#(\S+)"),
}

MOJIBAKE_RE = re.compile(r"Ð[-¿]|Ñ[-¿]|Â[ -ÿ]|â„–|â€")

# Регулярки для подсчёта открывающих/закрывающих токенов. Привязка к началу
# строки (через re.MULTILINE) гарантирует, что ловятся ТОЛЬКО блочные
# открыватели — слова в начале логической строки. Без неё ловились:
#   * атрибуты контрола формы: `CONTROL GROUP`, `EditField TableSource`,
#     `Property #ContainedProperties` (PROPERTIES как имя свойства);
#   * `FormGroup`, `FormSource` — имена типов в составе других слов;
#   * ENDGROUP/ENDSOURCE сами по себе — они тоже на отдельной строке.
PAIRS = [
    (re.compile(r"^\s*PROJECT\b", re.M),    re.compile(r"^\s*ENDPROJECT\b", re.M),    "PROJECT"),
    (re.compile(r"^\s*GROUP\b", re.M),      re.compile(r"^\s*ENDGROUP\b", re.M),      "GROUP"),
    (re.compile(r"^\s*BEGINNODE\b", re.M),  re.compile(r"^\s*ENDNODE\b", re.M),       "BEGINNODE"),
    (re.compile(r"^\s*SOURCE\b", re.M),     re.compile(r"^\s*ENDSOURCE\b", re.M),     "SOURCE"),
    (re.compile(r"^\s*PROPERTIES\b", re.M), re.compile(r"^\s*ENDPROPERTIES\b", re.M), "PROPERTIES"),
]


class Issue:
    __slots__ = ("path", "level", "msg")

    def __init__(self, path: str, level: str, msg: str):
        self.path = path
        self.level = level  # "ERROR" | "WARN"
        self.msg = msg

    def __str__(self) -> str:
        return f"[{self.level}] {self.path}: {self.msg}"


def check_bom_and_crlf(path: pathlib.Path) -> List[Issue]:
    issues = []
    with open(path, "rb") as f:
        raw = f.read()
    if not raw.startswith(b"\xef\xbb\xbf"):
        issues.append(Issue(str(path), "ERROR", "no UTF-8 BOM"))
        body = raw
    else:
        body = raw[3:]
    # Поиск одиночных \n без \r перед ними.
    lone_lf = 0
    for i, b in enumerate(body):
        if b == 0x0A and (i == 0 or body[i - 1] != 0x0D):
            lone_lf += 1
    if lone_lf:
        issues.append(Issue(str(path), "ERROR", f"{lone_lf} lone LF (expected CRLF)"))
    return issues


def check_balance(path: pathlib.Path, text: str) -> List[Issue]:
    issues = []
    for opener_re, closer_re, label in PAIRS:
        opens = len(opener_re.findall(text))
        closes = len(closer_re.findall(text))
        if opens != closes:
            issues.append(Issue(
                str(path), "ERROR",
                f"unbalanced {label}/END{label}: {opens} vs {closes}",
            ))
    # ***Element структура: одиночный xpo = 1 type + 1 END; бандл = N types + 1 END.
    # Универсальное правило: ровно одно ***Element: END в самом конце.
    elements = re.findall(r"^\*\*\*Element:\s*(\w+)\s*$", text, flags=re.MULTILINE)
    if elements:
        ends = sum(1 for e in elements if e == "END")
        if ends == 0:
            issues.append(Issue(str(path), "ERROR", "missing ***Element: END"))
        elif ends > 1:
            issues.append(Issue(str(path), "ERROR",
                                 f"too many ***Element: END markers: {ends} (expected 1)"))
        if elements[-1] != "END":
            issues.append(Issue(str(path), "ERROR",
                                 f"last ***Element marker is {elements[-1]!r}, expected END"))
    return issues


def check_mojibake(path: pathlib.Path, text: str) -> List[Issue]:
    matches = MOJIBAKE_RE.findall(text)
    if matches:
        # Покажем первые 3 уникальных артефакта для диагностики.
        sample = ", ".join(sorted(set(matches))[:3])
        return [Issue(str(path), "ERROR",
                      f"mojibake detected ({len(matches)} occurrences, sample: {sample})")]
    return []


def check_markers(path: pathlib.Path, text: str, prefix: str) -> List[Issue]:
    if not prefix:
        return []
    name = path.name
    for nm in NO_MARKER_REQUIRED:
        if name.startswith(nm):
            return []
    # Префикс может встречаться как `// PREFIX`, `//PREFIX`, `# // PREFIX`, `#//PREFIX`.
    pattern = re.compile(
        r"(^|[\r\n])\s*#?\s*//\s*[+\-]?\s*" + re.escape(prefix) + r"_?",
    )
    if pattern.search(text):
        return []
    return [Issue(str(path), "WARN",
                  f"no axapta-mod-comments marker (expected `//{prefix}...`)")]


def detect_object(path: pathlib.Path, text: str) -> Tuple[str, str]:
    lines = text.splitlines()
    mnemonic = ""
    for line in lines[:200]:
        m = ELEMENT_RE.match(line)
        if m:
            mnemonic = m.group(1)
            break
    if not mnemonic:
        return ("", "")
    name = ""
    name_re = NAME_RES.get(mnemonic)
    if name_re:
        for line in lines[:200]:
            m = name_re.match(line)
            if m:
                name = m.group(1)
                break
    return (mnemonic, name)


def gather_files(target: pathlib.Path) -> List[pathlib.Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        out = []
        for p in sorted(target.rglob("*.xpo")):
            try:
                rel_parts = p.relative_to(target).parts
            except ValueError:
                rel_parts = (p.name,)
            if "_release" in rel_parts:
                continue
            out.append(p)
        return out
    return []


def detect_menuitem_subtype_from_text(text: str) -> str:
    """Подтип MenuItem (FTM_DISPLAY/OUTPUT/ACTION) по полю Type в PROPERTIES."""
    for line in text.splitlines()[:200]:
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


def check_layout_consistency(
    path: pathlib.Path,
    root: pathlib.Path,
    mnemonic: str,
    text: str,
) -> List[Issue]:
    """Если файл лежит в подпапке внутри root, его mnemonic должен соответствовать
    ожидаемому dir_path. Для плоского корня (path.parent == root) — OK (legacy)."""
    if not mnemonic:
        return []
    try:
        rel = path.relative_to(root)
    except ValueError:
        return []
    parent_parts = rel.parts[:-1]
    if not parent_parts:
        # Плоский корень — пропускаем (legacy layout).
        return []

    effective = mnemonic
    if effective == "FTM":
        # Подтип FTM (Display/Output/Action) не пишется в теле как `Type` —
        # AX определяет его через UTILTYPE/NODETYPE в PROPERTIES. Если файл
        # уже лежит в Menu Items/<Display|Output|Action>/, признаём это
        # корректным расположением и берём effective из пути.
        if len(parent_parts) >= 2 and parent_parts[-2] == "Menu Items":
            sub_name = parent_parts[-1]
            sub_map = {"Display": "FTM_DISPLAY",
                       "Output": "FTM_OUTPUT",
                       "Action": "FTM_ACTION"}
            if sub_name in sub_map:
                return []
        effective = detect_menuitem_subtype_from_text(text) or "FTM_OUTPUT"

    expected = dir_path_for(effective)
    if not expected:
        return []
    if parent_parts == expected:
        return []
    return [Issue(
        str(path),
        "ERROR",
        f"layout mismatch: file lies under {'/'.join(parent_parts)}/, "
        f"but ***Element {mnemonic} expects {'/'.join(expected)}/",
    )]


def validate_one(
    path: pathlib.Path,
    prefix: str,
    root: Optional[pathlib.Path] = None,
) -> Tuple[List[Issue], Tuple[str, str]]:
    issues: List[Issue] = []
    issues.extend(check_bom_and_crlf(path))
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8", errors="replace")
    issues.extend(check_balance(path, text))
    issues.extend(check_mojibake(path, text))
    issues.extend(check_markers(path, text, prefix))
    obj = detect_object(path, text)
    if root is not None and obj[0]:
        issues.extend(check_layout_consistency(path, root, obj[0], text))
    return issues, obj


def main() -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Валидатор xpo-файлов")
    parser.add_argument("target", help="Файл или директория")
    parser.add_argument("--strict", action="store_true", help="WARN'ы тоже считать ошибками (exit != 0)")
    args = parser.parse_args()

    target = pathlib.Path(args.target).resolve()
    files = gather_files(target)
    if not files:
        print(f"ERROR: нет .xpo файлов в {target}", file=sys.stderr)
        return 2

    prefix = cfg.get("ALK_PROJECT_PREFIX", "") or ""
    if "<" in prefix:
        prefix = ""

    all_issues: List[Issue] = []
    name_owners: Dict[Tuple[str, str], List[str]] = {}

    layout_root = target if target.is_dir() else None

    for f in files:
        issues, obj = validate_one(f, prefix, root=layout_root)
        all_issues.extend(issues)
        if obj[0] and obj[1]:
            name_owners.setdefault(obj, []).append(str(f))

    # Уникальность имён.
    for obj, owners in name_owners.items():
        if len(owners) > 1:
            mnemonic, name = obj
            all_issues.append(Issue(
                ", ".join(owners), "ERROR",
                f"duplicate object {mnemonic} #{name} in multiple files",
            ))

    errors = [i for i in all_issues if i.level == "ERROR"]
    warns = [i for i in all_issues if i.level == "WARN"]

    for i in all_issues:
        print(i)

    print()
    print(f"Files:  {len(files)}")
    print(f"Errors: {len(errors)}")
    print(f"Warns:  {len(warns)}")

    if errors:
        return 1
    if warns and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
