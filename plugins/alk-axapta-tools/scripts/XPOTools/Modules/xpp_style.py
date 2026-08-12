"""Проверки оформления X++ внутри xpo.

Правила собраны по разбору реального прикладного кода из Axapta 3.0, который
переносили в AX 2012: 31 тысяча строк, писанных разными людьми без единой
конвенции. Каждая проверка здесь — след конкретной найденной проблемы, а не
абстрактное пожелание.

Все проверки — WARN: компилироваться такой код будет, читаться — плохо.

  keyword-case        `TRUE`, `Return`, `ttsCommit` вместо канонического
                      написания. X++ регистр не различает, поэтому одно и то же
                      слово встречалось в четырёх видах: true, TRUE, True, TRue.
  method-name-case    имя метода с заглавной (`Update`, `CRMActivityCreate`).
                      В дереве AOT видно имя узла, и оно выбивается.
  param-underscore    параметр без ведущего подчёркивания. Подчёркивание сразу
                      отличает параметр от поля класса и от локальной переменной.
  var-affix           переменная несёт аффикс объекта AOT (`BMSetup_CDT setup`).
                      Аффикс принадлежит имени объекта, на переменной он лишний;
                      чаще всего попадает туда при массовом переименовании.
  assign-spacing      `a =b` или `a = b ;`. У присваивания пробел с обеих
                      сторон, перед точкой с запятой пробела нет.
  blank-before-return `return` вплотную к предыдущему оператору. Не считается
                      нарушением, если перед return - открывающая `{`, лишь `;`
                      или метка `case ... :` / `default :` (то же начало новой
                      ветки, что и `{`).
  param-layout        2+ параметра в одной строке, либо перенесённый параметр
                      без ведущей запятой. Конвенция: один параметр — в строке
                      с методом; два и более — каждый на своей строке со
                      смещением в один отступ, запятая уходит в начало
                      следующей строки (не остаётся хвостом предыдущей) —
                      тогда в diff видно, какая строка ДОБАВИЛА параметр.

Разбор идёт по коду, а не по тексту: `//` внутри строкового литерала не
комментарий, и слово в комментарии не идентификатор. См. mask_code().
"""

import re
from typing import Iterator, List, NamedTuple, Tuple

from reserved_words import RESERVED_WORDS

#: Ключевые слова, канон которых — написание из выгруженного списка Axapta
#: (всё строчными). Сравнение регистронезависимое, поэтому храним как есть.
CANONICAL_KEYWORDS = {w: w for w in RESERVED_WORDS}

#: Присваивание, но не сравнение: `==`, `<=`, `>=`, `!=` отсекаются.
ASSIGN_RE = re.compile(r"(?<![=<>!+\-*/])([+\-*/]?=)(?!=)")

RETURN_RE = re.compile(r"^\s*return\b", re.I)

#: `case "X":` / `case Enum::Value :` / `default :` — метка switch-case. Она
#: открывает новую ветку точно так же, как `{`, поэтому return сразу за ней
#: не нуждается в пустой строке перед собой (та же категория, что и `{`).
CASE_LABEL_RE = re.compile(r"^(case\b.*|default)\s*:$")

#: Объявление переменной: `Тип имя;`, `Тип имя = значение;`, `Тип имя[10];`.
DECL_RE = re.compile(r"^\s*(?P<type>[A-Za-z_]\w*(?:\s+\d+)?)\s+"
                     r"(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:=|,|;)")


class Masked(NamedTuple):
    code: str          # только код, литералы и комментарии заменены пробелами
    raw: str


def mask_code(lines: List[str]) -> List[Masked]:
    """Заменяет строковые литералы и комментарии пробелами, сохраняя позиции.

    Состояние переносится со строки на строку: в приложении встречаются и
    многострочные литералы, и `/* */` через несколько строк.
    """
    out = []
    quote = ""
    verbatim = False
    in_block = False
    for raw in lines:
        code = []
        i, n = 0, len(raw)
        while i < n:
            ch = raw[i]
            if in_block:
                if ch == "*" and i + 1 < n and raw[i + 1] == "/":
                    in_block = False
                    code.append("  ")
                    i += 2
                    continue
                code.append(" ")
                i += 1
            elif quote:
                # В verbatim-литерале (@'...' / @"...") бэкслеш — данные, а не
                # экранирование: @'\Classes\' закрывается второй кавычкой, и без
                # этой ветки состояние «в строке» не закрывалось до конца файла,
                # молча отключая все проверки ниже (та же семантика, что в
                # xpp_code_only из validate_xpo).
                if ch == "\\" and not verbatim and i + 1 < n:
                    code.append("  ")
                    i += 2
                    continue
                if ch == quote:
                    # Удвоенная кавычка в verbatim — данные, а не конец литерала.
                    if verbatim and i + 1 < n and raw[i + 1] == quote:
                        code.append("  ")
                        i += 2
                        continue
                    quote = ""
                code.append(" ")
                i += 1
            elif ch == "/" and i + 1 < n and raw[i + 1] == "/":
                code.append(" " * (n - i))
                i = n
            elif ch == "/" and i + 1 < n and raw[i + 1] == "*":
                in_block = True
                code.append("  ")
                i += 2
            elif ch in "'\"":
                quote = ch
                verbatim = i > 0 and raw[i - 1] == "@"
                code.append(" ")
                i += 1
            else:
                code.append(ch)
                i += 1
        out.append(Masked("".join(code), raw))
    return out


#: Элементы, у которых `SOURCE #Имя` — объявление САМОГО ОБЪЕКТА, а не метода.
#: У макроса внутри `#define`, а не сигнатура, и имя узла — имя объекта AOT,
#: к которому правила именования методов неприменимы.
OBJECT_SOURCE_ELEMENTS = {"MCR", "MAC"}

#: Элементы, у которых `SOURCE #Имя` — тоже имя объекта AOT (реальный экспорт
#: JOB идёт сразу `SOURCE #<ИмяДжоба>`, без обёртки-узла — см. NAME_RES в
#: xpo_types), но ВНУТРИ обычный X++: правила именования методов к имени узла
#: неприменимы, а стилевые проверки тела — применимы полностью.
OBJECT_NAMED_SOURCE_ELEMENTS = {"JOB"}


def iter_methods(lines: List[str]) -> Iterator[Tuple[str, int, List[str], str]]:
    """(имя метода, номер первой строки тела, строки кода без `#`, элемент)."""
    start, name = None, ""
    element = ""
    for i, line in enumerate(lines):
        s = line.strip()
        m = re.match(r"^\*\*\*Element:\s*(\w+)\s*$", s)
        if m:
            element = m.group(1)
            continue
        m = re.match(r"^SOURCE #(\S+)\s*$", s)
        if m:
            if element in OBJECT_SOURCE_ELEMENTS:
                start = None
                continue
            start, name = i + 1, m.group(1)
            continue
        if s == "ENDSOURCE" and start is not None:
            body = []
            for raw in lines[start:i]:
                idx = raw.find("#")
                body.append(raw[idx + 1:] if idx >= 0 else raw)
            yield name, start, body, element
            start = None


def _signature_span(masked: List[Masked]) -> Tuple[int, int]:
    first = next((i for i, m in enumerate(masked)
                  if m.code.strip() and not m.code.strip().startswith("//")), -1)
    if first < 0:
        return -1, -1
    col = masked[first].code.find("(")
    if col < 0:
        return first, first
    depth = 0
    for i in range(first, len(masked)):
        for j in range(col if i == first else 0, len(masked[i].code)):
            if masked[i].code[j] == "(":
                depth += 1
            elif masked[i].code[j] == ")":
                depth -= 1
                if depth == 0:
                    return first, i
    return first, first


def check_keyword_case(masked: List[Masked], base: int) -> List[Tuple[int, str]]:
    out = []
    for k, m in enumerate(masked):
        for mm in re.finditer(r"[A-Za-z_]\w*", m.code):
            word = mm.group(0)
            canon = CANONICAL_KEYWORDS.get(word.lower())
            if canon is None or word == canon:
                continue
            before = m.code[:mm.start()].rstrip()
            # после точки, решётки или `::` это не ключевое слово, а имя члена,
            # макроса или значения перечисления
            if before.endswith((".", "#", ":")):
                continue
            out.append((base + k, f"keyword-case: `{word}` — канон `{canon}`"))
    return out


def check_method_name(name: str, line: int) -> List[Tuple[int, str]]:
    if not name[:1].isupper() or name.startswith("DEL_"):
        return []
    return [(line, f"method-name-case: имя метода `{name}` начинается с заглавной")]


def check_params(masked: List[Masked], base: int) -> List[Tuple[int, str]]:
    first, last = _signature_span(masked)
    if first < 0:
        return []
    text = " ".join(m.code for m in masked[first:last + 1])
    inner = text[text.find("(") + 1:text.rfind(")")] if "(" in text and ")" in text else ""
    out = []
    for part in inner.split(","):
        m = re.match(r"^\s*[A-Za-z_]\w*(?:\s+\d+)?\s+(?P<name>[A-Za-z_]\w*)", part)
        if m and not m.group("name").startswith("_"):
            out.append((base + first,
                        f"param-underscore: параметр `{m.group('name')}` без ведущего `_`"))
    return out


def _count_top_level_commas(s: str) -> int:
    """Запятые вне вложенных скобок — чтобы значение по умолчанию вида
    `= SysMCPJSON_CDT::quote(a, b)` не считалось лишним параметром."""
    depth = 0
    count = 0
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count


def check_param_layout(masked: List[Masked], base: int) -> List[Tuple[int, str]]:
    first, last = _signature_span(masked)
    if first < 0:
        return []
    text = " ".join(m.code for m in masked[first:last + 1])
    if "(" not in text or ")" not in text:
        return []
    inner = text[text.find("(") + 1:text.rfind(")")]
    if not inner.strip():
        return []
    if _count_top_level_commas(inner) + 1 < 2:
        return []
    if first == last:
        return [(base + first,
                 "param-layout: 2+ параметров в одной строке — перенести каждый "
                 "на свою строку с ведущей запятой")]
    # Строка объявления либо обрывается ГОЛОЙ '(' — тогда первый параметр
    # уходит на следующую строку БЕЗ запятой (это не перенос, а начало
    # списка), либо несёт первый параметр сама — тогда ведущей запятой
    # требуют уже ВСЕ последующие строки.
    after_paren = masked[first].code.split("(", 1)[1].strip() \
        if "(" in masked[first].code else ""
    if after_paren:
        start = first + 1
    else:
        # Первый параметр — на ПЕРВОЙ НЕПУСТОЙ строке после голой '(': пустая
        # строка или закомментированная (после mask_code — тоже пустая) между
        # '(' и первым параметром иначе сдвигала бы фиксированный `first + 2`
        # мимо него, и настоящий первый параметр — законно без ведущей
        # запятой — сам получал бы ложный WARN.
        first_param = next(
            (i for i in range(first + 1, last + 1) if masked[i].code.strip()),
            first + 1,
        )
        start = first_param + 1
    out = []
    for i in range(start, last + 1):
        stripped = masked[i].code.strip()
        if stripped and not stripped.startswith(","):
            out.append((base + i,
                        "param-layout: перенесённый параметр должен начинаться с ','"))
    return out


def check_var_affix(masked: List[Masked], base: int, affix: str) -> List[Tuple[int, str]]:
    if not affix:
        return []
    out = []
    for k, m in enumerate(masked):
        d = DECL_RE.match(m.code)
        if d and d.group("name").upper().endswith(affix.upper()):
            out.append((base + k,
                        f"var-affix: переменная `{d.group('name')}` несёт аффикс объекта"))
    return out


def check_assign_spacing(masked: List[Masked], base: int) -> List[Tuple[int, str]]:
    out = []
    for k, m in enumerate(masked):
        for mm in ASSIGN_RE.finditer(m.code):
            left, right = m.code[:mm.start(1)], m.code[mm.end(1):]
            if left and not left[-1].isspace():
                out.append((base + k, "assign-spacing: нет пробела перед присваиванием"))
            if right and not right[0].isspace():
                out.append((base + k, "assign-spacing: нет пробела после присваивания"))
        # пробел перед `;`; одинокая `;` в X++ значима и допустима
        for pos in (i for i, ch in enumerate(m.code) if ch == ";"):
            left = m.raw[:pos]
            if left.strip() and left != left.rstrip(" \t"):
                out.append((base + k, "assign-spacing: пробел перед `;`"))
                break
    return out


def check_blank_before_return(masked: List[Masked], base: int) -> List[Tuple[int, str]]:
    out = []
    for k, m in enumerate(masked):
        if not RETURN_RE.match(m.code):
            continue
        j = k
        while j > 0 and masked[j - 1].raw.strip().startswith("//"):
            j -= 1
        if j == 0:
            continue
        prev = masked[j - 1]
        prev_code = prev.code.strip()
        if (not prev.raw.strip() or prev_code.endswith("{") or prev_code == ";"
                or CASE_LABEL_RE.match(prev_code)):
            continue
        out.append((base + k, "blank-before-return: перед `return` нужна пустая строка"))
    return out


def check_style(lines: List[str], affix: str = "") -> List[Tuple[int, str]]:
    """Все стилевые замечания по файлу: [(номер строки в файле, текст)]."""
    found: List[Tuple[int, str]] = []
    for name, base, body, element in iter_methods(lines):
        if not body:
            continue
        masked = mask_code(body)
        if element not in OBJECT_NAMED_SOURCE_ELEMENTS:
            found += check_method_name(name, base)
        found += check_keyword_case(masked, base)
        found += check_params(masked, base)
        found += check_param_layout(masked, base)
        found += check_var_affix(masked, base, affix)
        found += check_assign_spacing(masked, base)
        found += check_blank_before_return(masked, base)
    return sorted(found)
