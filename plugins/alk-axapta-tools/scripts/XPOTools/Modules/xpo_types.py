"""Каталог типов AOT для xpo-сборщика и валидатора.

Ключ — мнемоника после `***Element: ` в xpo-файле.
Значение:
    utiltype     — числовой UTILTYPE для BEGINNODE.
    nodetype     — числовой NODETYPE для BEGINNODE.
    group_path   — путь от корня PROJECT до конечной GROUP в PRN-блоке
                   SharedProject (формат AOS Export). Имена слитные:
                   ["Classes"], ["MenuItems", "Output"], ["DataSets"].
    dir_path     — путь от корня XPO/-папки задачи до конечной директории
                   в AOT-layout (как в E:\\ZeroCoder\\Axapta\\ERP\\AOT-Prod).
                   Часто совпадает с group_path, но в FS встречаются имена
                   с пробелами там, где PRN использует слитные:
                       MenuItems  → "Menu Items"
                       DataSets   → "Data Sets"
                   По умолчанию dir_path = tuple(group_path); явное значение
                   указано там, где FS отличается от PRN.
    group_type   — значение ProjectGroupType для соответствующих PROPERTIES
                   (для вложенных Output/Display/Action — ProjectGroupType
                   совпадает с именем подгруппы).
    file_prefix  — префикс имени файла при разбивке бандла на отдельные xpo
                   (используется в плоском layout). В AOT-layout файлы лежат
                   в подпапках без префикса (например, Classes/Foo.xpo).

Источник данных — таблица в SKILL.md §8 axapta-project-export. При появлении
новых типов — добавлять сюда и в SKILL.md одновременно.
"""

XPO_TYPES = {
    "TAB": {"utiltype": 44, "nodetype": 204, "group_path": ["Data Dictionary", "Tables"], "group_type": "Tables", "file_prefix": "Table_"},
    "MAP": {"utiltype": 44, "nodetype": 236, "group_path": ["Data Dictionary", "Maps"], "group_type": "Maps", "file_prefix": "Map_"},
    "VIE": {"utiltype": 44, "nodetype": 243, "group_path": ["Data Dictionary", "Views"], "group_type": "Views", "file_prefix": "View_"},
    "EDT": {"utiltype": 41, "nodetype": 228, "group_path": ["Data Dictionary", "Extended Data Types"], "group_type": "Extended Data Types", "file_prefix": "EDT_"},
    "BAS": {"utiltype": 40, "nodetype": 209, "group_path": ["Data Dictionary", "Base Enums"], "group_type": "Base Enums", "file_prefix": "BaseEnum_"},
    "LIC": {"utiltype": 15, "nodetype": 311, "group_path": ["Data Dictionary", "License Codes"], "group_type": "License Codes", "file_prefix": "LicenseCode_"},
    "CFG": {"utiltype": 35, "nodetype": 312, "group_path": ["Data Dictionary", "Configuration Keys"], "group_type": "Configuration Keys", "file_prefix": "ConfigurationKey_"},
    "TBC": {"utiltype": 48, "nodetype": 211, "group_path": ["Data Dictionary", "Table Collections"], "group_type": "Table Collections", "file_prefix": "TableCollection_"},
    "PER": {"utiltype": 66, "nodetype": 1311, "group_path": ["Data Dictionary", "Perspectives"], "group_type": "Perspectives", "file_prefix": "Perspective_"},
    "MAC": {"utiltype": 4, "nodetype": 218, "group_path": ["Macros"], "group_type": "Macros", "file_prefix": "Macro_"},
    "CLS": {"utiltype": 45, "nodetype": 329, "group_path": ["Classes"], "group_type": "Classes", "file_prefix": "Class_"},
    "FRM": {"utiltype": 11, "nodetype": 201, "group_path": ["Forms"], "group_type": "Forms", "file_prefix": "Form_"},
    "REF": {"utiltype": 53, "nodetype": 822, "group_path": ["References"], "group_type": "References", "file_prefix": "Reference_"},
    "DTS": {"utiltype": 72, "nodetype": 207, "group_path": ["DataSets"], "dir_path": ("Data Sets",), "group_type": "DataSets", "file_prefix": "DataSet_"},
    "INP": {"utiltype": 81, "nodetype": 1429, "group_path": ["Parts", "Info Parts"], "group_type": "Info Parts", "file_prefix": "InfoPart_"},
    "FRP": {"utiltype": 82, "nodetype": 1431, "group_path": ["Parts", "Form Parts"], "group_type": "Form Parts", "file_prefix": "FormPart_"},
    "CUE": {"utiltype": 98, "nodetype": 1543, "group_path": ["Parts", "Cues"], "group_type": "Cues", "file_prefix": "Cue_"},
    "CUG": {"utiltype": 99, "nodetype": 1544, "group_path": ["Parts", "CueGroups"], "group_type": "CueGroups", "file_prefix": "CueGroup_"},
    "SRS": {"utiltype": 85, "nodetype": 1439, "group_path": ["SSRS Reports", "Reports"], "group_type": "Reports", "file_prefix": "SSRSReport_"},
    "LBF": {"utiltype": 117, "nodetype": 831, "group_path": ["LabelFiles"], "group_type": "LabelFiles", "file_prefix": "LabelFile_"},
    "VSP": {"utiltype": 127, "nodetype": 1531, "group_path": ["Visual Studio Projects", "Dynamics AX Model Projects"], "group_type": "Dynamics AX Model Projects", "file_prefix": "VSProject_"},
    "CSP": {"utiltype": 128, "nodetype": 1531, "group_path": ["Visual Studio Projects", "C Sharp Projects"], "group_type": "C Sharp Projects", "file_prefix": "CSProject_"},
    "QUE": {"utiltype": 20, "nodetype": 330, "group_path": ["Queries"], "group_type": "Queries", "file_prefix": "Query_"},
    "JOB": {"utiltype": 5, "nodetype": 215, "group_path": ["Jobs"], "group_type": "Jobs", "file_prefix": "Job_"},
    "MNU": {"utiltype": 16, "nodetype": 205, "group_path": ["Menus"], "group_type": "Menus", "file_prefix": "Menu_"},
    # MenuItem (FTM) делится на 3 подтипа по UTILTYPE: 1=Display, 2=Output, 3=Action.
    # Подтип определяется в build-shared-project.py по имени файла или по содержимому
    # (`MenuItemDisplay_*.xpo` / `MenuItemOutput_*.xpo` / `MenuItemAction_*.xpo`).
    "FTM_DISPLAY": {"utiltype": 1, "nodetype": 296, "group_path": ["MenuItems", "Display"], "dir_path": ("Menu Items", "Display"), "group_type": "Display", "file_prefix": "MenuItemDisplay_"},
    "FTM_OUTPUT": {"utiltype": 2, "nodetype": 296, "group_path": ["MenuItems", "Output"], "dir_path": ("Menu Items", "Output"), "group_type": "Output", "file_prefix": "MenuItemOutput_"},
    "FTM_ACTION": {"utiltype": 3, "nodetype": 296, "group_path": ["MenuItems", "Action"], "dir_path": ("Menu Items", "Action"), "group_type": "Action", "file_prefix": "MenuItemAction_"},
    "SVC": {"utiltype": 76, "nodetype": 1321, "group_path": ["Services"], "group_type": "Services", "file_prefix": "Service_"},
    "SVG": {"utiltype": 137, "nodetype": 1325, "group_path": ["Service Groups"], "group_type": "Service Groups", "file_prefix": "ServiceGroup_"},
    "WFC": {"utiltype": 71, "nodetype": 1423, "group_path": ["Workflow", "Workflow Categories"], "group_type": "Workflow Categories", "file_prefix": "WorkflowCategory_"},
    "WFA": {"utiltype": 70, "nodetype": 1421, "group_path": ["Workflow", "Approvals"], "group_type": "Approvals", "file_prefix": "WorkflowApproval_"},
    "WFT": {"utiltype": 69, "nodetype": 1417, "group_path": ["Workflow", "Tasks"], "group_type": "Tasks", "file_prefix": "WorkflowTask_"},
    "WAT": {"utiltype": 95, "nodetype": 1409, "group_path": ["Workflow", "Automated Tasks"], "group_type": "Automated Tasks", "file_prefix": "WorkflowAutomatedTask_"},
    "WFY": {"utiltype": 68, "nodetype": 1412, "group_path": ["Workflow", "Workflow Types"], "group_type": "Workflow Types", "file_prefix": "WorkflowType_"},
    "WFH": {"utiltype": 139, "nodetype": 1397, "group_path": ["Workflow", "Providers", "HierarchyAssignment"], "group_type": "HierarchyAssignment", "file_prefix": "WorkflowHierarchyProvider_"},
    "CDP": {"utiltype": 115, "nodetype": 1608, "group_path": ["Security", "Code Permissions"], "group_type": "Code Permissions", "file_prefix": "CodePermission_"},
    "PRV": {"utiltype": 134, "nodetype": 1628, "group_path": ["Security", "Privileges"], "group_type": "Privileges", "file_prefix": "Privilege_"},
    "DUT": {"utiltype": 135, "nodetype": 1630, "group_path": ["Security", "Duties"], "group_type": "Duties", "file_prefix": "Duty_"},
    "ROL": {"utiltype": 133, "nodetype": 1626, "group_path": ["Security", "Roles"], "group_type": "Roles", "file_prefix": "Role_"},
    "PCY": {"utiltype": 136, "nodetype": 1636, "group_path": ["Security", "Process Cycles"], "group_type": "Process Cycles", "file_prefix": "ProcessCycle_"},
    "POL": {"utiltype": 119, "nodetype": 1619, "group_path": ["Security", "Policies"], "group_type": "Policies", "file_prefix": "Policy_"},
    "RES": {"utiltype": 21, "nodetype": 820, "group_path": ["Resources"], "group_type": "Resources", "file_prefix": "Resource_"},
}

# Алиасы для реальных AX-mnemonics, которые AOS Export пишет в ***Element:
# (синонимы для ключей XPO_TYPES выше). Подключаем после основного словаря,
# чтобы не дублировать metadata.
# Источник: реальные xpo-выгрузки из E:\ZeroCoder\Axapta\ERP\AOT-Prod (DBT для
# Table, DBE для Base Enum, CON для ConfigurationKey, UTS/UTI/UTQ/UTR/UTE/UTW
# для EDT по underlying-типу, SDT для Duty, SPV для Privilege).
_AX_MNEMONIC_ALIASES = {
    "DBT": "TAB",   # Table
    "DBE": "BAS",   # Base Enum
    "CON": "CFG",   # Configuration Key
    "UTS": "EDT",   # EDT String
    "UTI": "EDT",   # EDT Integer
    "UTW": "EDT",   # EDT Int64
    "UTR": "EDT",   # EDT Real
    "UTQ": "EDT",   # EDT Container (Queue)
    "UTE": "EDT",   # EDT Enum (Extended Enum)
    "UTU": "EDT",   # EDT UtcDateTime / Date / Time (встречаются варианты)
    "UTG": "EDT",   # EDT Guid
    "SPV": "PRV",   # Security Privilege
    "SDT": "DUT",   # Security Duty
    "SRO": "ROL",   # Security Role (AOS Export: ***Element: SRO)
    "SPC": "PCY",   # Security Process Cycle
    "SPO": "POL",   # Security Policy
    "SCP": "CDP",   # Security Code Permission
}
for _alias, _target in _AX_MNEMONIC_ALIASES.items():
    if _target in XPO_TYPES and _alias not in XPO_TYPES:
        XPO_TYPES[_alias] = XPO_TYPES[_target]

# Префиксы файлов, для которых маркеры мод-комментариев необязательны.
# Resource/LabelFile — бинарные/служебные.
# Menu/MenuItem — по SKILL.md axapta-project-export §9a: маркеры в `;`-шапке
# Menu/MenuItem ломают парсер AX 2012 R2, поэтому маркер для них живёт
# только в docs/CHANGES.md задачи, а не внутри .xpo.
NO_MARKER_REQUIRED = {"Resource_", "LabelFile_", "Menu_", "MenuItem"}

# Элементы-маркеры, которые не являются объектами (служебные).
SERVICE_ELEMENTS = {"PRN", "END"}


def detect_menuitem_subtype(filename: str) -> str:
    """По имени файла MenuItem*_*.xpo вернуть FTM_DISPLAY/OUTPUT/ACTION."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    low = name.lower()
    if low.startswith("menuitemdisplay_"):
        return "FTM_DISPLAY"
    if low.startswith("menuitemoutput_"):
        return "FTM_OUTPUT"
    if low.startswith("menuitemaction_"):
        return "FTM_ACTION"
    return ""


def dir_path_for(mnemonic: str):
    """Возвращает кортеж имён директорий для AOT-layout (с пробелами там, где
    AOT-Prod использует пробелы). Fallback — `group_path` из словаря."""
    meta = XPO_TYPES.get(mnemonic)
    if not meta:
        return ()
    if "dir_path" in meta:
        return tuple(meta["dir_path"])
    return tuple(meta["group_path"])


# Обратный индекс: tuple(dir_path) → mnemonic. Используется в flatten/validate
# для определения ожидаемого типа по реальному расположению файла.
DIR_PATH_INDEX = {}
for _mnemonic, _meta in list(XPO_TYPES.items()):
    _dp = tuple(_meta.get("dir_path", _meta["group_path"]))
    # Только основные типы попадают в индекс — алиасы DBT/DBE/CON/SPV/... дают
    # тот же tuple, что и их базовый mnemonic, поэтому первая запись побеждает.
    DIR_PATH_INDEX.setdefault(_dp, _mnemonic)


# Индекс: file_prefix → mnemonic. Используется в organize для определения типа
# по плоскому имени файла (Class_Foo.xpo → CLS).
PREFIX_INDEX = {
    _meta["file_prefix"]: _mnemonic
    for _mnemonic, _meta in XPO_TYPES.items()
    if _meta.get("file_prefix")
}
