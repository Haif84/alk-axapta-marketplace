"""validate_xpo — статический валидатор xpo-файлов MS Dynamics AX 2012.

Проверки:
  1. BOM (UTF-8 BOM в начале файла) и CRLF (никаких одиночных \\n).
  2. Балансировка блоков: PROJECT/ENDPROJECT, GROUP/ENDGROUP,
     BEGINNODE/ENDNODE, SOURCE/ENDSOURCE, PROPERTIES/ENDPROPERTIES.
  3. Mojibake — типичные артефакты двойной перекодировки CP1251↔UTF-8↔CP1252.
  4. Наличие маркеров axapta-mod-comments (`//<PREFIX>...` или `#//<PREFIX>...`
     внутри SOURCE) хотя бы один раз в каждом .xpo с исключением Resource/LabelFile.
  5. Уникальность имён объектов между .xpo (две CLS с одним именем = ошибка).
  6. Layout-consistency (только для директории): AOT-раскладка обязательна —
     плоский корень даёт WARN (валит только --strict), файл не в той AOT-подпапке
     для своего типа — ERROR (всегда).
  7. Зарезервированные слова X++ (Modules/reserved_words.py) в роли имени
     параметра метода, локальной переменной или поля classDeclaration — WARN.
     Поля tableFieldsDeclaration (столбцы таблиц, метаданные) намеренно НЕ
     проверяются. Локальные переменные детектируются только в начале тела
     метода (блок объявлений сразу после `{`, до первого исполняемого
     оператора) — не цепляет обычные операторы вида `return foo;`.
  8. Контрол формы без `AutoDeclaration #Yes`, на который тем не менее есть
     ссылка по имени (`Имя.метод(...)`) в коде формы — WARN. AX даёт
     Err:9 «Переменная ... не была объявлена» только на импорте/компиляции;
     эта проверка ловит его раньше, статически.
  9. `str` без объявленной длины (параметр метода или локальная переменная),
     использованный внутри `where`/`like` `select`-выражения — WARN. AX даёт
     Err:103 «Использование контейнеров и полей с неограниченными строками
     в выражении WHERE не допускается» только при компиляции.
  10. Свойство контрола, ЗАВЕДОМО не существующее для его типа (база знаний —
      Modules/xpo_types.py:INVALID_CONTROL_PROPERTIES) — WARN. Импорт AX
      такое свойство не отклоняет, а молча пропускает («пропускается
      свойство X»), из-за чего расхождение не видно до проверки поведения
      формы вручную.

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
from xpo_types import (  # noqa: E402
    XPO_TYPES, NO_MARKER_REQUIRED, NO_CODE_CONTAINER, dir_path_for, name_re_for,
    detect_menuitem_subtype_from_lines, INVALID_CONTROL_PROPERTIES,
)
from config import load_config, validate_config, print_config_warnings  # noqa: E402
from reserved_words import RESERVED_WORDS  # noqa: E402
from xpp_style import OBJECT_NAMED_SOURCE_ELEMENTS, check_style, iter_methods  # noqa: E402

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


ELEMENT_RE = re.compile(r"^\*\*\*Element:\s*(\w+)\s*$")

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


def check_indices_shape(path: pathlib.Path, text: str) -> List[Issue]:
    """Блок INDICES в таблице НЕ использует обёртки INDEX/ENDINDEX — в отличие от
    GROUPS, где GROUP/ENDGROUP как раз нужны. Формат:

        INDICES
          #ИмяИндекса
          PROPERTIES
            ...
          ENDPROPERTIES
          INDEXFIELDS
            #Поле
          ENDINDEXFIELDS
        ENDINDICES

    Написание `INDEX #Имя` валит импорт в AX: парсер принимает слово INDEX за имя
    индекса и падает на следующей строке («ожидалось PROPERTIES, но обнаружено
    #Имя»). Балансировка блоков такого не ловит, поэтому проверяем отдельно.
    """
    issues: List[Issue] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if re.match(r"^(INDEX|ENDINDEX)\b", stripped):
            issues.append(Issue(
                str(path), "ERROR",
                f"line {lineno}: {stripped.split()[0]} внутри INDICES — обёрток "
                f"INDEX/ENDINDEX в формате xpo нет, AX не импортирует. "
                f"Формат: INDICES -> #ИмяИндекса -> PROPERTIES"))
    return issues


#: Состояние разбора, переносимое МЕЖДУ строками метода:
#: (внутри /* */, открытая кавычка или None, литерал verbatim).
XppScanState = Tuple[bool, Optional[str], bool]
XPP_SCAN_START: XppScanState = (False, None, False)


def xpp_code_only(line: str, state: XppScanState = XPP_SCAN_START) -> Tuple[str, XppScanState]:
    """Кодовая часть строки X++: без комментариев и без содержимого литералов.

    Литералы вычищаются, а не просто пропускаются: иначе `if (line == '{')`
    посчитается за открывающую скобку. Комментарий `//` внутри литерала —
    это данные (`'http://host'`), поэтому наивная обрезка по `//` не годится.

    Состояние ОБЯЗАНО переноситься между строками: в X++ строковый литерал
    может тянуться через несколько строк (так вставляют XAML и XML), и разбор
    построчно с чистого листа принимает содержимое литерала за код.

    Возвращает (кодовая часть, новое состояние).
    """
    in_block_comment, quote, verbatim = state
    out: List[str] = []
    i, n = 0, len(line)

    while i < n:
        ch = line[i]

        if in_block_comment:
            if ch == "*" and i + 1 < n and line[i + 1] == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if quote:
            if ch == "\\" and not verbatim and i + 1 < n:
                i += 2                      # экранированный символ внутри литерала
                continue
            if ch == quote:
                # В verbatim-литерале кавычка удваивается: @"...""..." —
                # это данные, а не конец строки.
                if verbatim and i + 1 < n and line[i + 1] == quote:
                    i += 2
                    continue
                quote = None
                out.append(" ")             # литерал схлопываем в пробел
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            verbatim = i > 0 and line[i - 1] == "@"
            i += 1
            continue

        if ch == "/" and i + 1 < n and line[i + 1] == "/":
            break                            # хвостовой комментарий

        if ch == "/" and i + 1 < n and line[i + 1] == "*":
            in_block_comment = True
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out), (in_block_comment, quote, verbatim)


def iter_source_blocks(text: str):
    """Отдаёт (имя метода, номер строки SOURCE, [(номер, содержимое-после-#)]).

    Строки режем ТОЛЬКО по CRLF. `splitlines()` здесь нельзя: он делит ещё и по
    одиночному CR, а тот встречается ВНУТРИ исходника как обычный символ —
    например `case #X:<CR>    this.doIt();` в SitesSvcSyncErrorInfoAction.
    Для AX это одна строка с префиксом '#', а `splitlines()` показывал вторую,
    «потерявшую» префикс, и проверка ругалась на совершенно целый файл.
    """
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
    name: Optional[str] = None
    start = 0
    body: List[Tuple[int, Optional[str]]] = []

    for lineno, line in enumerate(lines, 1):
        m = re.match(r"^\s*SOURCE #(\S+)", line)
        if m:
            name, start, body = m.group(1), lineno, []
            continue
        if re.match(r"^\s*ENDSOURCE\b", line):
            if name is not None:
                yield name, start, body
            name = None
            continue
        if name is not None:
            m2 = re.match(r"^\s*#(.*)$", line)
            body.append((lineno, m2.group(1) if m2 else None))


def check_source_prefix(path: pathlib.Path, text: str) -> List[Issue]:
    """Каждая строка внутри SOURCE обязана начинаться с '#'.

    Ловит порчу, которую не видит ничто другое: скрипт-переписыватель снял
    префикс, xpo внешне цел (BOM, CRLF, баланс блоков в порядке), а AX такой
    файл уже не понимает. Проверено на 400 боевых выгрузках: строк без '#'
    внутри SOURCE не бывает ни одной.
    """
    issues: List[Issue] = []
    for name, _, body in iter_source_blocks(text):
        bad = [lineno for lineno, content in body if content is None]
        if bad:
            issues.append(Issue(
                str(path), "ERROR",
                f"line {bad[0]}: в теле SOURCE #{name} строка без префикса '#' "
                f"(всего таких строк: {len(bad)}). AX не прочитает такой xpo"))
    return issues


def check_xpp_brace_balance(path: pathlib.Path, text: str) -> List[Issue]:
    """Фигурные скобки внутри метода обязаны сходиться.

    Ловит обрезанный или покорёженный метод — например, когда автоматическая
    правка исходников вставила скобку не туда. Комментарии и литералы из
    подсчёта исключены, иначе `'{'` в строке даёт ложную тревогу.

    Границы применимости, обе намеренные:

    1. Парная вставка `{`/`}` не в том месте баланс НЕ нарушает, поэтому такую
       ошибку проверка не увидит — для неё нужен компилятор AX.
    2. Методы с ВЛОЖЕННЫМ блочным комментарием (`/*` внутри `/*`) пропускаются.
       Такое встречается в legacy-коде: закомментировали кусок, внутри которого
       уже был свой комментарий. Считать скобки текстом там нельзя, не зная
       точно, вложенные комментарии в X++ или нет, — а выдавать догадку за
       ошибку хуже, чем промолчать. На боевой выгрузке это ~0.6% классов.
    """
    issues: List[Issue] = []
    for name, start, body in iter_source_blocks(text):
        balance = 0
        state = XPP_SCAN_START
        ambiguous = False

        for _, content in body:
            if content is None:
                continue                     # об этом уже сказал check_source_prefix

            if state[0] and "/*" in content:
                ambiguous = True             # вложенный комментарий — не гадаем
                break

            code, state = xpp_code_only(content, state)

            # Макрос отдельной строкой может развернуться во что угодно, включая
            # открывающую скобку: `#ALK_DialogHeader` в CIT_SendAlert.dialog даёт
            # весь заголовок метода, и в тексте остаётся только `}`.
            if code.lstrip().startswith("#"):
                ambiguous = True
                break

            balance += code.count("{") - code.count("}")

        if ambiguous:
            continue

        if balance:
            issues.append(Issue(
                str(path), "ERROR",
                f"line {start}: в методе {name} не сходятся фигурные скобки "
                f"(баланс {balance:+d}) — метод обрезан или повреждён"))
    return issues


def check_form_objectbank(path: pathlib.Path, text: str, mnemonic: str) -> List[Issue]:
    """Блок OBJECTBANK формы БЕЗ источников данных обязан выглядеть так:

        OBJECTBANK
          PROPERTIES
          ENDPROPERTIES

        ENDOBJECTBANK

    PROPERTIES обязателен, DATASOURCE отсутствует. Ошибиться можно двумя
    способами, и оба ловятся только импортом в AX:

    1. Написать внутри пустой `DATASOURCE` с `METHODS` — по аналогии с формой, у
       которой источник данных ЕСТЬ (там METHODS идёт после ENDOBJECTPOOL).
       AX: «ожидалось OBJECTPOOL, но обнаружено METHODS».
    2. Оставить OBJECTBANK совсем пустым, без PROPERTIES. Парсер считает форму
       законченной и падает на следующей секции:
       «ожидалось ENDFORM, но обнаружено REFERENCEDATASOURCES».

    Эталон снят с боевой выгрузки AX 2012 (`%AX_AOT_PATH%\\Forms`), а НЕ с
    BM.xpo: BM — экспорт AX 3.0, там секции REFERENCEDATASOURCES ещё не было.
    """
    if mnemonic != "FRM":
        return []

    lines = text.splitlines()
    start = end = None
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped == "OBJECTBANK" and start is None:
            start = lineno
        elif stripped == "ENDOBJECTBANK" and start is not None:
            end = lineno
            break

    if start is None or end is None:
        return []

    block = [ln.strip() for ln in lines[start:end - 1]]
    has_properties = "PROPERTIES" in block
    has_datasource = "DATASOURCE" in block
    has_objectpool = any(ln.startswith("OBJECTPOOL") for ln in block)

    issues: List[Issue] = []

    if has_datasource and not has_objectpool:
        issues.append(Issue(
            str(path), "ERROR",
            f"line {start}: DATASOURCE без OBJECTPOOL — у формы без источников "
            f"данных блока DATASOURCE быть не должно вовсе, AX не импортирует "
            f"(«ожидалось OBJECTPOOL»). Формат: OBJECTBANK -> PROPERTIES -> "
            f"ENDPROPERTIES -> ENDOBJECTBANK"))

    if not has_properties:
        issues.append(Issue(
            str(path), "ERROR",
            f"line {start}: пустой OBJECTBANK — внутри нужен PROPERTIES/"
            f"ENDPROPERTIES, иначе парсер считает форму законченной и падает на "
            f"следующей секции («ожидалось ENDFORM»)"))

    return issues


CONTROL_START_RE = re.compile(r"^\s*CONTROL\s+(\w+)\s*$")
CONTROL_END_RE = re.compile(r"^\s*ENDCONTROL\s*$")
CONTROL_NAME_RE = re.compile(r"^\s*Name\s+#(\S+)")
CONTROL_AUTODECL_RE = re.compile(r"^\s*AutoDeclaration\s+#Yes\b")

#: Контролы, оборачивающие ВНЕШНИЙ объект (WPF/.NET-контрол, ActiveX,
#: HTML-движок) — обращение к ним по имени (`ManagedHost.control()`,
#: `HtmlView.Document()`, `html.setText(...)`) работает даже БЕЗ
#: `AutoDeclaration #Yes`. Проверено на боевых формах в реальном AOT:
#: `ALK_MarkLabelItem` (MANAGEDHOST `PictureBox`, без AutoDeclaration,
#: `PictureBox.control()` в коде), `ALK_FilePreview` (ACTIVEX `HtmlView`,
#: без AutoDeclaration, `HtmlView.Document()`), `SysImportDialog` (HTML
#: `#HTML`, без AutoDeclaration, `html.setText(...)`). Для ОБЫЧНЫХ контролов
#: (GROUP/TREE/STRINGEDIT/...) AutoDeclaration обязателен — см. живой пример
#: Err:9 на GROUP-контроле без него.
IMPLICITLY_DECLARED_CONTROL_TYPES = {"MANAGEDHOST", "ACTIVEX", "HTML"}


def _iter_form_controls(lines: List[str]):
    """(имя контрола, тип, есть ли AutoDeclaration #Yes) по каждому CONTROL-блоку.

    Контролы формы — плоские соседи внутри CONTAINER (связь между ними —
    свойство HierarchyParent, а не физическая вложенность блоков в xpo),
    поэтому парный поиск CONTROL/ENDCONTROL без стека вложенности корректен."""
    i, n = 0, len(lines)
    while i < n:
        cm = CONTROL_START_RE.match(lines[i])
        if cm:
            ctype = cm.group(1).upper()
            i += 1
            name, auto = None, False
            while i < n and not CONTROL_END_RE.match(lines[i]):
                if name is None:
                    m = CONTROL_NAME_RE.match(lines[i])
                    if m:
                        name = m.group(1)
                if CONTROL_AUTODECL_RE.match(lines[i]):
                    auto = True
                i += 1
            if name:
                yield name, ctype, auto
        i += 1


def check_control_autodeclaration(path: pathlib.Path, text: str, mnemonic: str) -> List[Issue]:
    """Контрол без `AutoDeclaration #Yes` не существует как переменная в коде
    формы — обращение к нему по имени (`objectsTree.setImagelist(...)`) даёт
    на импорте/компиляции Err:9 «Переменная ... не была объявлена». Ошибка
    видна только в живом AX; здесь она ловится статически, по совпадению
    имени контрола с идентификатором перед `.` в коде любого SOURCE-блока
    файла (уровня формы или уровня самого контрола). Контролы из
    IMPLICITLY_DECLARED_CONTROL_TYPES исключены — см. её комментарий."""
    if mnemonic != "FRM":
        return []
    lines = text.splitlines()
    controls = list(_iter_form_controls(lines))
    if not controls:
        return []
    undeclared = {name for name, ctype, auto in controls
                  if not auto and ctype not in IMPLICITLY_DECLARED_CONTROL_TYPES}
    if not undeclared:
        return []
    used = set()
    for _, _, body in iter_source_blocks(text):
        state = XPP_SCAN_START
        for _, content in body:
            if content is None:
                continue
            code, state = xpp_code_only(content, state)
            for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\.", code):
                used.add(m.group(1))
    issues = []
    for name in sorted(undeclared & used):
        issues.append(Issue(
            str(path), "WARN",
            f"control `{name}` used in code (`{name}.…`) but has no "
            f"AutoDeclaration #Yes — AX: 'Переменная {name} не была объявлена' (Err:9)",
        ))
    return issues


CONTROL_PROP_LINE_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s+#")


def check_invalid_control_properties(path: pathlib.Path, text: str, mnemonic: str) -> List[Issue]:
    """Свойство контрола, заведомо не существующее для его типа — см. базу
    знаний `INVALID_CONTROL_PROPERTIES` в xpo_types.py. AX импорт такое
    свойство молча пропускает (`[WARN] пропускается свойство X`, не ERROR),
    поэтому расхождение не видно до ручной проверки поведения формы."""
    if mnemonic != "FRM" or not INVALID_CONTROL_PROPERTIES:
        return []
    lines = text.splitlines()
    issues: List[Issue] = []
    i, n = 0, len(lines)
    while i < n:
        cm = CONTROL_START_RE.match(lines[i])
        if cm:
            ctype = cm.group(1).upper()
            i += 1
            in_props = False
            while i < n and not CONTROL_END_RE.match(lines[i]):
                stripped = lines[i].strip()
                if stripped == "PROPERTIES":
                    in_props = True
                elif stripped == "ENDPROPERTIES":
                    in_props = False
                elif in_props:
                    pm = CONTROL_PROP_LINE_RE.match(lines[i])
                    if pm:
                        reason = INVALID_CONTROL_PROPERTIES.get((ctype, pm.group(1)))
                        if reason:
                            issues.append(Issue(
                                str(path), "WARN",
                                f"line {i + 1}: свойство `{pm.group(1)}` недопустимо "
                                f"на CONTROL {ctype} — {reason}",
                            ))
                i += 1
        i += 1
    return issues


#: `str`-параметр/локальная без длины — только имя, без цифры вслед за `str`
#: (для параметра допускается хвостовое значение по умолчанию `= ...`).
UNBOUND_STR_PARAM_RE = re.compile(r"^\s*str\s+([A-Za-z_]\w*)\s*(?:=.*)?$")
UNBOUND_STR_LOCAL_RE = re.compile(r"^\s*str\s+([A-Za-z_]\w*)\s*(?:=.*)?;")
WHERE_LIKE_RE = re.compile(r"\b(where|like)\b", re.I)
#: Ключевые слова, с которых начинается query-оператор X++. Err:103 — про
#: неограниченную строку в выражении query-оператора; `like`/`where` вне его
#: (обычный `if (x like _mask)`) компилируется нормально и не должен флагаться.
QUERY_STATEMENT_RE = re.compile(
    r"\b(select|insert_recordset|update_recordset|delete_from)\b", re.I)


def check_unbound_str_in_query(path: pathlib.Path, text: str) -> List[Issue]:
    """`str` без объявленной длины, попавший в `where`/`like` `select`-запроса,
    даёт Err:103 («Использование контейнеров и полей с неограниченными
    строками в выражении WHERE не допускается») только на компиляции.
    Проверка — на уровне ОДНОГО метода: собирает имена unbound-`str`
    параметров и локальных переменных, затем ищет их внутри условия
    `where`/`like` — но только когда это условие принадлежит query-оператору
    (`select`/`insert_recordset`/`update_recordset`/`delete_from`), а не
    обычному `if`/`while`, где `like` — валидный оператор сравнения строк."""
    issues: List[Issue] = []
    for name, _, body in iter_source_blocks(text):
        codes: List[Tuple[int, str]] = []
        state = XPP_SCAN_START
        for lineno, content in body:
            if content is None:
                codes.append((lineno, ""))
                continue
            code, state = xpp_code_only(content, state)
            codes.append((lineno, code))

        unbound = set()
        sig_text = ""
        for _, code in codes:
            sig_text += " " + code
            if "{" in code:
                break
        sm = re.search(r"\(([^)]*)\)", sig_text)
        if sm:
            for part in sm.group(1).split(","):
                pm = UNBOUND_STR_PARAM_RE.match(part.strip())
                if pm:
                    unbound.add(pm.group(1))
        for _, code in codes:
            lm = UNBOUND_STR_LOCAL_RE.match(code)
            if lm:
                unbound.add(lm.group(1))
        if not unbound:
            continue

        # По X++-операторам (от `;` до `;`), не по строкам: where/like значимы
        # только внутри query-оператора целиком, а не с первого их появления
        # после произвольного `if`.
        stmt: List[Tuple[int, str]] = []
        is_query_stmt = False
        for lineno, code in codes:
            stmt.append((lineno, code))
            if QUERY_STATEMENT_RE.search(code):
                is_query_stmt = True
            if ";" not in code:
                continue
            if is_query_stmt:
                in_clause = False
                for sln, scode in stmt:
                    if WHERE_LIKE_RE.search(scode):
                        in_clause = True
                    if not in_clause:
                        continue
                    for uname in unbound:
                        if re.search(rf"\b{re.escape(uname)}\b", scode):
                            issues.append(Issue(
                                str(path), "WARN",
                                f"line {sln}: SOURCE #{name}: `{uname}` — str без "
                                f"длины использован в where/like — AX Err:103, "
                                f"объявить как `str <N> {uname}`",
                            ))
            stmt = []
            is_query_stmt = False
    return issues


#: Предел длины имени AOT-объекта в AX 2012 — EDT SysUtilElementName это STRING(40).
MAX_OBJECT_NAME_LEN = 40


def check_object_name_length(path: pathlib.Path, name: str) -> List[Issue]:
    """Имя AOT-объекта длиннее 40 символов AX не примет. Сокращать надо ЗАРАНЕЕ и
    осмысленно — ужимать самые длинные слова, сохраняя смысл
    (`CIT_DevToolPanel_Display_SysMCPParameters_CDT` -> `..._SysMCPParms_CDT`),
    а не полагаться на то, что кто-то обрежет имя за тебя."""
    if not name or len(name) <= MAX_OBJECT_NAME_LEN:
        return []
    return [Issue(
        str(path), "ERROR",
        f"имя объекта {name!r} — {len(name)} символов, предел {MAX_OBJECT_NAME_LEN}. "
        f"Сократи самые длинные слова с сохранением смысла")]


def check_method_name_length(path: pathlib.Path, text: str) -> List[Issue]:
    """Тот же предел 40 символов действует и на имена методов — оба хранятся
    в одном поле UtilElements.Name. Обнаружено 04.08.2026 на живом компиляторе
    (Err:110 «Слишком длинное имя») на методах, которые validate-xpo пропустил:
    он проверял только имена AOT-объектов, не методов внутри."""
    issues: List[Issue] = []
    for name, line, _body, element in iter_methods(text.splitlines()):
        if element in OBJECT_NAMED_SOURCE_ELEMENTS:
            continue  # SOURCE #Имя тут — имя объекта (JOB), уже покрыто check_object_name_length
        if len(name) <= MAX_OBJECT_NAME_LEN:
            continue
        issues.append(Issue(
            f"{path}:{line}", "ERROR",
            f"имя метода {name!r} — {len(name)} символов, предел {MAX_OBJECT_NAME_LEN}. "
            f"Сократи самые длинные слова с сохранением смысла"))
    return issues


def check_markers(path: pathlib.Path, text: str, prefix: str,
                  mnemonic: str = "") -> List[Issue]:
    if not prefix:
        return []
    # Отбор по типу объекта, а не только по префиксу имени файла: в AOT-layout
    # файлы лежат без префиксов (Menu Items/Display/Foo.xpo), и проверка по
    # имени там не срабатывала — на разложенной выгрузке приложения это давало
    # 283 предупреждения об отсутствии маркера у объектов, которым его негде
    # разместить: EDT, перечисления, пункты меню, ключи конфигурации.
    if mnemonic in NO_CODE_CONTAINER:
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


def check_source_block_wrapping(path: pathlib.Path, text: str, prefix: str) -> List[Issue]:
    """WARN если первая непустая строка SOURCE-блока — открывающий блок-маркер
    `// + PREFIX… -->`. Для нового метода нужен однострочный header-комментарий,
    не пара открывающий/закрывающий блок."""
    if not prefix:
        return []
    issues = []
    source_re = re.compile(r"^\s*SOURCE\s+#(\S+)\s*$", re.MULTILINE)
    open_block_re = re.compile(r"^\s*#\s*//\s*\+\s*" + re.escape(prefix))
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = source_re.match(lines[i])
        if m:
            method_name = m.group(1)
            i += 1
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped == "ENDSOURCE":
                    break
                if stripped:
                    if open_block_re.match(lines[i]):
                        issues.append(Issue(
                            str(path), "WARN",
                            f"SOURCE #{method_name}: starts with block-open marker "
                            f"`// + {prefix}…` — new method should use "
                            f"single header `// {prefix}…` instead",
                        ))
                    break
        i += 1
    return issues


DECL_RE = re.compile(
    r"^\s*([A-Za-z_][\w.]*)(?:\s*\[\s*\])?\s+"
    r"([A-Za-z_]\w*)\s*(?:=.*)?;"
)
# Ключевые слова, начинающие ОПЕРАТОР (не объявление) и способные принять форму
# "СЛОВО ИДЕНТИФИКАТОР;", которую DECL_RE иначе спутал бы с "TYPE name;"
# (самый частый случай — return true;/return false; в теле геттера).
_STATEMENT_KEYWORDS = frozenset(("return", "throw", "break", "continue", "leave", "retry"))
SIGNATURE_RE = re.compile(
    r"^\s*(?:public|private|protected|static|server|client|abstract|final)?\s*"
    r"[\w.<>\[\]]+\s+\w+\s*\(([^)]*)\)"
)
PARAM_RE = re.compile(r"^[A-Za-z_][\w.\[\]]*\s+([A-Za-z_]\w*)\s*(?:=.*)?$")


def check_reserved_identifiers(path: pathlib.Path, text: str) -> List[Issue]:
    """WARN, если имя параметра метода, локальной переменной или поля класса —
    зарезервированное слово X++ (см. Modules/reserved_words.py): компилятор AX
    выдаст синтаксическую ошибку при попытке скомпилировать такое объявление.

    Поля `tableFieldsDeclaration` (столбцы Data Dictionary) намеренно НЕ
    проверяются: это метаданные AOT, а не буквальные X++-объявления,
    парсящиеся тем же лексером — по конвенции ALK имена столбцов таблиц (и
    имена самих таблиц) МОГУТ совпадать с зарезервированными словами. Поля
    `classDeclaration` (члены класса), напротив, — обычные X++-объявления,
    проходящие тот же лексер, что параметры/локальные переменные, поэтому
    проверяются наравне с ними.

    Локальные переменные детектируются только в начале тела метода: сканирование
    останавливается на первой строке, не похожей на объявление (`TYPE name;`) —
    по конвенции ALK объявления идут единым блоком сразу после `{`, до первого
    исполняемого оператора. Это специально ограничивает область поиска, чтобы не
    цеплять обычные операторы вида `select foo;`, где первый токен — само ключевое
    слово, а не тип (форма не совпадает с DECL_RE). Отдельно — операторы вида
    `return foo;`/`throw foo;` СОВПАДАЮТ по форме с `TYPE name;` (два слова + `;`),
    поэтому `return`/`throw`/`break`/`continue`/`leave`/`retry` в позиции типа явно
    исключены (`_STATEMENT_KEYWORDS`): иначе любой геттер вида `{ return true; }`
    ложно определялся бы как объявление переменной `true`."""
    issues: List[Issue] = []
    lines = text.splitlines()
    source_re = re.compile(r"^\s*SOURCE\s+#(\S+)\s*$")
    i = 0
    while i < len(lines):
        m = source_re.match(lines[i])
        if not m:
            i += 1
            continue
        method_name = m.group(1)
        if method_name == "tableFieldsDeclaration":
            # Столбцы таблиц — метаданные, не проверяем (см. docstring).
            i += 1
            while i < len(lines) and lines[i].strip() != "ENDSOURCE":
                i += 1
            continue
        if method_name == "classDeclaration":
            # Поля класса — обычные X++-объявления, проверяем как локальные
            # переменные/параметры. Здесь нет исполняемых операторов вообще
            # (только объявления и #define-макросы), поэтому не нужна логика
            # "остановиться на первом non-decl" — просто сканируем всё тело.
            i += 1
            while i < len(lines):
                if lines[i].strip() == "ENDSOURCE":
                    break
                content = re.sub(r"^\s*#", "", lines[i])
                dm = DECL_RE.match(content)
                if (dm and dm.group(1).lower() not in _STATEMENT_KEYWORDS
                        and dm.group(2).lower() in RESERVED_WORDS):
                    issues.append(Issue(
                        str(path), "WARN",
                        f"SOURCE #classDeclaration: field '{dm.group(2)}' is a "
                        f"reserved X++ word — AX will reject this declaration",
                    ))
                i += 1
            continue
        signature_checked = False
        declarations_open = False
        in_block_comment = False
        i += 1
        while i < len(lines):
            if lines[i].strip() == "ENDSOURCE":
                break
            # Строки внутри SOURCE-блока в .xpo предварены символом `#` (иногда с
            # отступом перед ним) — сравнивать нужно очищенный контент, не сырую
            # строку, иначе `#{`/`#` (пустая строка)/`#    ;` не совпадут с "{"/""/";" .
            content = re.sub(r"^\s*#", "", lines[i])
            content_stripped = content.strip()
            if not signature_checked and content_stripped and "(" in content:
                signature_checked = True
                sm = SIGNATURE_RE.match(content)
                if sm:
                    for part in sm.group(1).split(","):
                        part = part.strip()
                        if not part:
                            continue
                        pm = PARAM_RE.match(part)
                        if pm and pm.group(1).lower() in RESERVED_WORDS:
                            issues.append(Issue(
                                str(path), "WARN",
                                f"SOURCE #{method_name}: parameter '{pm.group(1)}' is "
                                f"a reserved X++ word — AX will reject this declaration",
                            ))
                i += 1
                continue
            if signature_checked:
                if content_stripped == "{":
                    declarations_open = True
                    i += 1
                    continue
                if declarations_open:
                    if content_stripped == "" or content_stripped == ";":
                        i += 1
                        continue
                    # Комментарий и макро-директива блок объявлений НЕ обрывают:
                    # и то и другое штатно стоит среди объявлений, а сканирование
                    # прекращается на первой «не-декларации». Из-за этого одна
                    # строка `// пояснение` прятала все объявления ниже себя, и
                    # проверка молча пропускала `int from;` в трёх строках под ней.
                    #
                    # Блочный /* */ пропускается ЦЕЛИКОМ, с состоянием: строки
                    # внутри него — в том числе закомментированные объявления
                    # вида `int from;` (штатная конвенция сохранения заменённого
                    # кода, §3 mod-comments) — не сканируются вовсе. Без
                    # состояния закомментированное объявление давало бы ложный
                    # WARN, а непрефиксованная строка середины комментария
                    # обрывала бы скан, пряча объявления ниже.
                    if in_block_comment:
                        if "*/" in content_stripped:
                            in_block_comment = False
                        i += 1
                        continue
                    if content_stripped.startswith("/*"):
                        if "*/" not in content_stripped:
                            in_block_comment = True
                        i += 1
                        continue
                    if (content_stripped.startswith("//")
                            or content_stripped.startswith("*")
                            or content_stripped.startswith("#")):
                        i += 1
                        continue
                    dm = DECL_RE.match(content)
                    if not dm or dm.group(1).lower() in _STATEMENT_KEYWORDS:
                        # Либо не похоже на объявление, либо это оператор вида
                        # `return foo;`/`throw foo;` — первый токен keyword, а не тип.
                        declarations_open = False
                        i += 1
                        continue
                    if dm.group(2).lower() in RESERVED_WORDS:
                        issues.append(Issue(
                            str(path), "WARN",
                            f"SOURCE #{method_name}: local variable '{dm.group(2)}' is "
                            f"a reserved X++ word — AX will reject this declaration",
                        ))
            i += 1
    return issues


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
    # Имя пункта меню уникально в пределах СВОЕГО подтипа: Display BMBuild и
    # Action BMBuild — разные объекты, и в AOT они лежат в разных папках. Без
    # уточнения подтипа проверка уникальности считала их дублем.
    if mnemonic == "FTM":
        mnemonic = detect_menuitem_subtype_from_lines(lines[:200]) or mnemonic
    name = ""
    # AOS Export пишет алиасные мнемоники (DBT для Table, SRO для Role, UTS/UTI/...
    # для EDT) — NAME_RES ключуется каноническими, поэтому без резолва алиаса имя
    # оставалось пустым и проверки по имени (длина, дубликаты) для реальных
    # AOS-выгрузок молча не работали.
    name_re = name_re_for(mnemonic)
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


def check_layout_consistency(
    path: pathlib.Path,
    root: pathlib.Path,
    mnemonic: str,
    text: str,
) -> List[Issue]:
    """AOT-раскладка обязательна для финальной структуры (см. axapta-project-export
    SKILL.md §«Папка XPO/ обязательна»). Два случая:
      - плоский корень (файл прямо в root, без AOT-подпапки) — WARN: задача ещё не
        organize-нута. WARN, а не ERROR, чтобы --strict не начал внезапно проваливать
        уже идущие задачи с плоским layout при обновлении плагина — без --strict
        не влияет на exit code вообще.
      - файл лежит в подпапке, но не в той, что ожидается для его типа — ERROR:
        обычно значит, что organize-xpo (или ручной перенос) ошибся."""
    if not mnemonic:
        return []
    try:
        rel = path.relative_to(root)
    except ValueError:
        return []
    parent_parts = rel.parts[:-1]

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
        effective = detect_menuitem_subtype_from_lines(text.splitlines()[:200]) or "FTM_OUTPUT"

    expected = dir_path_for(effective)
    if not expected:
        return []

    if not parent_parts:
        return [Issue(
            str(path),
            "WARN",
            f"flat layout: file lies directly in {root.name}/, but AOT layout "
            f"expects {'/'.join(expected)}/ — run organize-xpo organize "
            f"--root <XPO/> before release",
        )]

    if parent_parts == expected:
        return []
    return [Issue(
        str(path),
        "ERROR",
        f"layout mismatch: file lies under {'/'.join(parent_parts)}/, "
        f"but ***Element {mnemonic} expects {'/'.join(expected)}/",
    )]


def check_xpp_style(path: pathlib.Path, text: str, affix: str) -> List[Issue]:
    """Оформление X++: регистр ключевых слов, имена, пробелы (см. xpp_style)."""
    return [Issue(f"{path}:{line}", "WARN", msg)
            for line, msg in check_style(text.splitlines(), affix)]


def validate_one(
    path: pathlib.Path,
    prefix: str,
    affix: str = "",
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
    issues.extend(check_indices_shape(path, text))
    obj = detect_object(path, text)
    issues.extend(check_markers(path, text, prefix, obj[0]))
    issues.extend(check_source_block_wrapping(path, text, prefix))
    issues.extend(check_reserved_identifiers(path, text))
    issues.extend(check_xpp_style(path, text, affix))
    issues.extend(check_object_name_length(path, obj[1]))
    issues.extend(check_method_name_length(path, text))
    issues.extend(check_form_objectbank(path, text, obj[0]))
    issues.extend(check_source_prefix(path, text))
    issues.extend(check_xpp_brace_balance(path, text))
    issues.extend(check_control_autodeclaration(path, text, obj[0]))
    issues.extend(check_unbound_str_in_query(path, text))
    issues.extend(check_invalid_control_properties(path, text, obj[0]))
    if root is not None and obj[0]:
        issues.extend(check_layout_consistency(path, root, obj[0], text))
    return issues, obj


def main() -> int:
    print_config_warnings(validate_config())
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Валидатор xpo-файлов")
    parser.add_argument("target", help="Файл или директория")
    parser.add_argument("--strict", action="store_true", help="WARN'ы тоже считать ошибками (exit != 0)")
    parser.add_argument(
        "--project-code", default="", metavar="CODE",
        help="Код проекта для проверки мод-маркеров; перекрывает AX_PROJECT_ID. "
             "Нужен репозиториям, чей код проекта отличается от глобальной ENV — "
             "например --project-code CIT000 при AX_PROJECT_ID=ALK_DEVAX12")
    args = parser.parse_args()

    target = pathlib.Path(args.target).resolve()
    files = gather_files(target)
    if not files:
        print(f"ERROR: нет .xpo файлов в {target}", file=sys.stderr)
        return 2

    # Явный --project-code важнее глобальной ENV: один репозиторий может вести
    # модификацию под чужим кодом проекта (например CIT000 в общем тулинге),
    # и тогда AX_PROJECT_ID из ENV дал бы ложные WARN на каждом файле.
    prefix = args.project_code or (cfg.get("AX_PROJECT_ID", "") or "")
    if "<" in prefix:
        prefix = ""

    # Аффикс нужен проверке var-affix: переменная не должна нести аффикс имени
    # объекта AOT. Плейсхолдер из config.example.json игнорируем.
    affix = cfg.get("AX_OBJECT_SUFFIX", "") or cfg.get("AX_OBJECT_PREFIX", "") or ""
    if "<" in affix:
        affix = ""

    all_issues: List[Issue] = []
    name_owners: Dict[Tuple[str, str], List[str]] = {}

    layout_root = target if target.is_dir() else None

    for f in files:
        issues, obj = validate_one(f, prefix, affix, root=layout_root)
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
