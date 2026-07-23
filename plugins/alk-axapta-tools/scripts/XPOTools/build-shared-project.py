"""build-shared-project — сборка финального SharedProject_*.xpo для MS Dynamics AX 2012.

Универсальная версия эталона e:\\ZeroCoder\\LT_DAX-12135\\docs\\templates\\_build_shared_project.py:
все литералы (ROOT, body_files, GROUP'ы, GUID, dt_stamp) вынесены в CLI-флаги
и автодетект, формат вывода (UTF-8+BOM+CRLF, PRN с ProjectGroupType) сохранён.

Запуск: build-shared-project [--root .\\XPO] [--project-name ...] [--dry-run] [--yes]
См. README.md в корне XPOTools/.
"""

import argparse
import datetime
import io
import os
import pathlib
import re
import sys
import uuid
from typing import Dict, List, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "Modules"))
from xpo_types import XPO_TYPES, detect_menuitem_subtype  # noqa: E402
from config import load_config, validate_config, print_config_warnings  # noqa: E402

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ====== I/O ==================================================================

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


def normalize_xpo(path: str) -> None:
    write_xpo(path, "\n".join(read_lines(path)))


def read_body(path: str) -> str:
    """Тело объекта: от ***Element: TYPE до строки перед ***Element: END."""
    lines = read_lines(path)
    start = next(i for i, l in enumerate(lines) if l.startswith("***Element:"))
    end_idx = next(i for i, l in enumerate(lines) if l.strip() == "***Element: END")
    body = lines[start:end_idx]
    while body and body[-1].strip() == "":
        body.pop()
    return "\n".join(body) + "\n"


# ====== Parsing source xpo ===================================================

ELEMENT_RE = re.compile(r"^\*\*\*Element:\s*(\w+)\s*$")

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
    # AX-export mnemonics (соответствуют алиасам в xpo_types._AX_MNEMONIC_ALIASES).
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
    "SRO": re.compile(r"^\s*ROLE\s+#(\S+)"),  # AOS Export mnemonic (same as SRL)
    "SPC": re.compile(r"^\s*PROCESSCYCLE\s+#(\S+)"),
    "SPO": re.compile(r"^\s*POLICY\s+#(\S+)"),
    "SCP": re.compile(r"^\s*CODEPERMISSION\s+#(\S+)"),
}


def detect_element_type(lines: List[str]) -> Tuple[str, str]:
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


def detect_menuitem_full(lines: List[str], filename: str, root: pathlib.Path = None) -> str:
    """Возвращает FTM_DISPLAY/OUTPUT/ACTION. Приоритет источников:
      1) префикс имени файла (плоский layout: MenuItemDisplay_*.xpo);
      2) родительская папка (AOT-layout: Menu Items/Display/Foo.xpo);
      3) поле `Type #Display` в PROPERTIES (редкий случай, для AX-export
         подтип обычно живёт в UTILTYPE, а не в Type);
      4) fallback FTM_OUTPUT (warning поведение, чтобы не упасть)."""
    sub = detect_menuitem_subtype(filename)
    if sub:
        return sub
    # AOT-layout: смотрим на путь файла относительно root.
    if root is not None:
        try:
            rel = pathlib.Path(filename).resolve().relative_to(root)
        except (ValueError, OSError):
            rel = None
        if rel is not None:
            parts = rel.parts
            if len(parts) >= 3 and parts[-3] == "Menu Items":
                sub_name = parts[-2]
                if sub_name == "Display":
                    return "FTM_DISPLAY"
                if sub_name == "Output":
                    return "FTM_OUTPUT"
                if sub_name == "Action":
                    return "FTM_ACTION"
    for line in lines[:200]:
        s = line.strip()
        if s.startswith("Type") and "#" in s:
            v = s.split("#", 1)[-1].strip().lower()
            if v == "display":
                return "FTM_DISPLAY"
            if v == "output":
                return "FTM_OUTPUT"
            if v == "action":
                return "FTM_ACTION"
    return "FTM_OUTPUT"


# ====== Tree building & PRN ==================================================

TOP_ORDER = [
    "Data Dictionary",
    "Macros",
    "Classes",
    "Forms",
    "Parts",
    "DataSets",
    "SSRS Reports",
    "Visual Studio Projects",
    "Queries",
    "Jobs",
    "Menus",
    "MenuItems",
    "Workflow",
    "Services",
    "Service Groups",
    "References",
    "Resources",
    "LabelFiles",
    "Security",
]

SUB_ORDER = {
    "Data Dictionary": ["Tables", "Maps", "Views", "Extended Data Types", "Base Enums",
                         "License Codes", "Configuration Keys", "Table Collections", "Perspectives"],
    "Parts": ["Info Parts", "Form Parts", "Cues", "CueGroups"],
    "SSRS Reports": ["Reports"],
    "Visual Studio Projects": ["Dynamics AX Model Projects", "C Sharp Projects"],
    "MenuItems": ["Display", "Output", "Action"],
    "Workflow": ["Workflow Categories", "Approvals", "Tasks", "Automated Tasks",
                  "Workflow Types", "Providers"],
    "Security": ["Code Permissions", "Privileges", "Duties", "Roles",
                  "Process Cycles", "Policies"],
}


def emit_group(indent: int, name: str, gtype: str,
               nodes: List[Dict], subgroups: List[str]) -> str:
    sp = " " * indent
    out = []
    out.append(f"{sp}GROUP #{name}")
    out.append(f"{sp}  PROPERTIES")
    out.append(f"{sp}    Name                #{name}")
    out.append(f"{sp}    ProjectGroupType    #{gtype}")
    out.append(f"{sp}    GroupMask           #")
    out.append(f"{sp}    PreventEditProperties #No")
    out.append(f"{sp}  ENDPROPERTIES")
    out.append(f"{sp}  ")
    for sg in subgroups:
        out.extend(sg.split("\n"))
    for n in nodes:
        out.append(f"{sp}  BEGINNODE")
        out.append(f"{sp}    FILETYPE 0")
        out.append(f"{sp}    UTILTYPE {n['utiltype']}")
        out.append(f"{sp}    UTILOBJECTID {n.get('utilobjectid', 0)}")
        out.append(f"{sp}    NODETYPE {n['nodetype']}")
        out.append(f"{sp}    NAME #{n['name']}")
        out.append(f"{sp}  ENDNODE")
    out.append(f"{sp}  ENDGROUP")
    out.append(f"{sp}  ")
    return "\n".join(out)


def build_tree(objects: List[Dict]) -> Dict:
    tree: Dict = {}
    for o in objects:
        cur = tree
        for i, part in enumerate(o["group_path"]):
            cur.setdefault(part, {"nodes": [], "subs": {}})
            if i == len(o["group_path"]) - 1:
                cur[part]["nodes"].append(o)
            else:
                cur = cur[part]["subs"]
    return tree


def _ordered_keys(level_keys: List[str], parent_name: str = "") -> List[str]:
    if parent_name and parent_name in SUB_ORDER:
        order = SUB_ORDER[parent_name]
    else:
        order = TOP_ORDER
    head = [n for n in order if n in level_keys]
    tail = sorted(n for n in level_keys if n not in head)
    return head + tail


def emit_tree(tree: Dict, indent: int, parent_name: str = "") -> List[str]:
    out = []
    for name in _ordered_keys(list(tree.keys()), parent_name):
        node = tree[name]
        sub_strings = emit_tree(node["subs"], indent + 2, parent_name=name) if node["subs"] else []
        out.append(emit_group(indent, name, name, node["nodes"], sub_strings))
    return out


def build_prn(project_name: str, project_guid: str, objects: List[Dict]) -> str:
    parts = []
    parts.append("***Element: PRN")
    parts.append("")
    parts.append(f"; Microsoft Dynamics AX Project : {project_name} unloaded")
    parts.append("; --------------------------------------------------------------------------------")
    parts.append("  PROJECTVERSION 2")
    parts.append("  ")
    parts.append(f"  PROJECT #{project_name}")
    parts.append("  SHARED")
    parts.append("  PROPERTIES")
    parts.append(f"    Name                #{project_name}")
    parts.append(f"    Origin              #{project_guid}")
    parts.append("  ENDPROPERTIES")
    parts.append("  ")
    parts.append("    PROJECTCLASS ProjectNode")

    tree = build_tree(objects)
    parts.extend(emit_tree(tree, indent=4))

    parts.append("  ENDPROJECT")
    parts.append("  ")
    parts.append("")
    parts.append("***Element: END")
    parts.append("")
    return "\n".join(parts)


# ====== Sorting bodies in PRN order ==========================================

def _sort_key(o: Dict) -> tuple:
    path = o["group_path"]
    top = path[0]
    top_idx = TOP_ORDER.index(top) if top in TOP_ORDER else 999
    sub_idx = 0
    if len(path) > 1:
        subs = SUB_ORDER.get(top, [])
        sub = path[1]
        sub_idx = subs.index(sub) if sub in subs else 999
    return (top_idx, sub_idx, o["name"].lower())


def sort_objects_by_prn(objects: List[Dict]) -> List[Dict]:
    return sorted(objects, key=_sort_key)


# ====== Origin reuse =========================================================

GUID_RE = re.compile(r"Origin\s+#(\{[A-F0-9-]+\})")


def reuse_origin(release_dir: pathlib.Path, project_name: str) -> str:
    """Возвращает Origin GUID из PRN-блока последнего бандла, не из Origin отдельных
    объектов (CLS/TAB/...) — в начале файла встречается множество других Origin."""
    if not release_dir.is_dir():
        return ""
    candidates = sorted(
        release_dir.glob(f"SharedProject_{project_name}_*.xpo"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for c in candidates:
        try:
            with open(c, "rb") as f:
                raw = f.read()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            text = raw.decode("utf-8", errors="ignore")
            prn_idx = text.find("***Element: PRN")
            if prn_idx < 0:
                continue
            m = GUID_RE.search(text, prn_idx)
            if m:
                return m.group(1)
        except OSError:
            continue
    return ""


# ====== Main =================================================================

def collect_objects(root: pathlib.Path) -> List[Dict]:
    objects = []
    for xpo in sorted(root.rglob("*.xpo")):
        # _release/ исключается на любой глубине вложенности (фильтр через
        # relative_to, чтобы поймать и плоский xpo/_release/, и aot-вариант).
        try:
            rel_parts = xpo.relative_to(root).parts
        except ValueError:
            rel_parts = (xpo.name,)
        if "_release" in rel_parts:
            continue
        lines = read_lines(str(xpo))
        mnemonic, name = detect_element_type(lines)
        if not mnemonic:
            print(f"WARNING: skipped (no ***Element): {xpo.name}", file=sys.stderr)
            continue
        if mnemonic == "FTM":
            mnemonic = detect_menuitem_full(lines, str(xpo), root=root)
        if mnemonic not in XPO_TYPES:
            print(f"WARNING: unknown ***Element: {mnemonic} in {xpo.name}", file=sys.stderr)
            continue
        meta = XPO_TYPES[mnemonic]
        # Fallback-имя: для legacy-плоского layout xpo.stem содержит префикс
        # (Class_Foo), для AOT-layout — уже чистое имя (Foo). Срезаем известный
        # file_prefix только если xpo.stem с него начинается.
        fallback_name = xpo.stem
        prefix = meta.get("file_prefix", "")
        if prefix and fallback_name.startswith(prefix):
            fallback_name = fallback_name[len(prefix):]
        objects.append({
            "name": name or fallback_name,
            "mnemonic": mnemonic,
            "utiltype": meta["utiltype"],
            "nodetype": meta["nodetype"],
            "group_path": list(meta["group_path"]),
            "file_path": str(xpo),
            "file_prefix": meta["file_prefix"],
        })
    return objects


def main() -> int:
    print_config_warnings(validate_config())
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Сборка SharedProject_*.xpo")
    parser.add_argument("--root", default=str(pathlib.Path.cwd() / "XPO"),
                        help="Папка с *.xpo (по умолчанию ./XPO)")
    parser.add_argument("--project-name", default=None, help="Имя AOT Project")
    parser.add_argument("--guid", default=None,
                        help="Origin GUID. По умолчанию: переиспользовать из _release/, иначе сгенерировать.")
    parser.add_argument("--dt-stamp", default=None, help="Метка yyyymmdd_HHMM (по умолчанию: текущая)")
    parser.add_argument("--dry-run", action="store_true", help="Не записывать файл, показать план")
    parser.add_argument("--yes", action="store_true", help="Пропустить интерактивное подтверждение")
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root не существует: {root}", file=sys.stderr)
        return 2

    project_name = args.project_name
    if not project_name:
        prefix = cfg.get("AX_PROJECT_ID", "")
        if not prefix or "<" in prefix:
            print("ERROR: --project-name не указан и не выводится из config", file=sys.stderr)
            return 2
        project_name = prefix + "_<TICKET>"
    if "<" in project_name:
        print("ERROR: --project-name содержит плейсхолдер: " + project_name, file=sys.stderr)
        return 2

    release_dir = root / "_release"
    guid = args.guid or reuse_origin(release_dir, project_name) or ("{" + str(uuid.uuid4()).upper() + "}")

    dt_stamp = args.dt_stamp or datetime.datetime.now().strftime("%Y%m%d_%H%M")

    objects = collect_objects(root)
    if not objects:
        print(f"ERROR: в {root} нет xpo-объектов", file=sys.stderr)
        return 3
    objects = sort_objects_by_prn(objects)

    print(f"Project:  {project_name}")
    print(f"Origin:   {guid}")
    print(f"Stamp:    {dt_stamp}")
    print(f"Source:   {root}")
    print()
    print("Объекты:")
    for o in objects:
        print(f"  [{o['mnemonic']:>11}] {o['name']:<60} -> {' / '.join(o['group_path'])}")
    print()

    out_name = f"SharedProject_{project_name}_{dt_stamp}.xpo"
    out_path = release_dir / out_name
    print(f"Target:   {out_path}")

    if args.dry_run:
        print()
        print("--- Превью PRN ---")
        print(build_prn(project_name, guid, objects))
        return 0

    if not args.yes:
        ans = input("Собрать? [y/N] ").strip().lower()
        if ans not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return 0

    for o in objects:
        normalize_xpo(o["file_path"])

    out = "Exportfile for AOT version 1.0 or later\nFormatversion: 1\n\n"
    for o in objects:
        out += read_body(o["file_path"]) + "\n"
    out += build_prn(project_name, guid, objects)

    release_dir.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        for v in range(2, 100):
            candidate = release_dir / f"SharedProject_{project_name}_{dt_stamp}_v{v}.xpo"
            if not candidate.exists():
                out_path = candidate
                break

    write_xpo(str(out_path), out)

    print()
    print(f"Wrote: {out_path}")
    print(f"Size:  {out_path.stat().st_size} bytes")
    print(f"Объектов: {len(objects)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
