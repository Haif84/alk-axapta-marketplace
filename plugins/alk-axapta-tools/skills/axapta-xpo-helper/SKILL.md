---
name: axapta-xpo-helper
description: |
  Низкоуровневая сборка отдельных AOT-артефактов Microsoft Dynamics AX 2012 (ALK), которых нет в project-export / project-manage / mod-comments.
  ОБЯЗАТЕЛЬНО используй при: упаковке AOT Resource из xlsx/бинарника; «битый xlsx из Resource» / Excel recovery после выгрузки;
  шаблонах XMLExcelReport_RU (Header/Body, именованные диапазоны, даты как серийники, пропавшие заголовки столбцов);
  «собери Resource», «build-resource-xpo», «SysResourceType BINARY», «FF FF FF».
  Не заменяет axapta-project-export (SharedProject), axapta-project-manage (раскладка XPO/) и axapta-mod-comments (маркеры).
---

# Axapta XPO Helper

Helper для создания/упаковки отдельных объектов AOT. v1 — **Resource BINARY** и конвенции Excel-шаблонов под `XMLExcelReport_RU`.

## Preflight

```powershell
python "$pluginRoot\scripts\XPOTools\Modules\config.py"
```

Ненулевой exit → `/alk-axapta-tools:setup`. Resolve `$pluginRoot` как в скилле `setup`.

## 1. Упаковка AOT Resource

### Когда

- Новый Excel-шаблон отчёта (`XMLExcelReport_RU` / Resource в AOT)
- Любой бинарный Resource (xlsx в первую очередь)
- Excel recovery / обрезанный zip при выгрузке Resource из AX

### Команда

```powershell
python "$pluginRoot\scripts\XPOTools\build-resource-xpo.py" `
  --file .\docs\templates\MyReport.xlsx `
  --name ALK_MyReport `
  --out .\XPO\Resources\ALK_MyReport.xpo
```

Опции: `--filename` (по умолчанию basename `--file`), `--origin {GUID}`.

Регресс:

```powershell
python -m unittest "$pluginRoot\scripts\XPOTools\tests\test_resource_wrapper.py"
```

### BINARY-wrapper (канон AOS)

Эталон: `%AX_AOT_PATH%\Resources\ALK_ExcelEmpty.xpo` и др.

| Элемент | Значение |
|---------|----------|
| Заголовок | 55 байт `SysResourceType` |
| payload | `file_bytes + FF FF FF` |
| uint32 @44 | `len(payload) + 5` |
| uint32 @51 | **`len(file_bytes)`** — длина при выгрузке файла из AX |
| BINARY N | `len(header)+len(payload)` |

**Анти-паттерн:** `field@51 = len(file)-3` без trailing `FF` → AX отдаёт файл на 3 байта короче → Excel recovery (`error*_01.xml`), ZIP EOCD битый.

После сборки проверить: extract по field@51 == исходный файл; для xlsx — `zipfile.testzip()` is None.

### Качество xlsx перед упаковкой

- Не сдавать «голый» `openpyxl.save` как финальный шаблон (часто Excel repair).
- База: Excel-native структура (`ALK_ExcelEmpty`) или OOXML с declaration / `xmlns:r` / sharedStrings.
- Маркер модификации для Resource — только в `docs/CHANGES.md` (`validate-xpo` не требует маркера в `.xpo`).

## 2. Конвенции `XMLExcelReport_RU` + Excel Resource

Движок в template mode **очищает `sheetData`** и копирует в результат **только строки исполненных секций** (`insertRowsByBookmark` / `copyRowsTemplate`).

### Named ranges

1. **`Header` / `Body` — только целые строки:** `Sheet!$1:$1`, `Sheet!$3:$3`, multi-row `Sheet!$1:$2`.  
   Ячейки `$A$1:$I$1` → `@GLS64284` в `getNamedRangeHeightFixed` (требует `fromCol=toCol=0`).
2. **Заголовки столбцов** класть **внутрь Header** (`Header = $1:$2`: title + captions). Строка между `$1:$1` и Body **не копируется**.
3. Не включать строку заголовков в Body — иначе она повторится на каждой записи.
4. Закладки полей (`reportDate`, колонки) — одиночные ячейки; секции печати — row-range.

### Даты

`OXMLCell_RU` пишет `Types::Date` как OADate (`t="n"`) **без** NumberFormat.

- Предпочтительно: в шаблоне `numFmtId="14"` (+ `applyNumberFormat`) на ячейках дат; в X++ сырой `TransDate` (эталон Bonus).
- Запасной путь: `date2StrUsr(..., DateFlags::FormatAll)` в `insertValueToSection`.

### Ширина колонок

`<cols>` шаблона сохраняются. Excel AutoFit в OpenXML-стеке нет — при необходимости `OXMLWorksheet_RU.columnWidth` + `parmSaveColumnWidths(true)` (см. SysMon / отчёты задачи).

### Не переписывать на `CIT_SysExcelReport_NET` «ради автоширины»

NET = COM Interop + `.xlt`, column AutoFit тоже не встроен. Для табличных HR-отчётов предпочтителен `XMLExcelReport_RU` + Resource xlsx.

## 3. Каркасы объектов, которые пишутся руками

### Правило образца (главное)

Структуру xpo брать **из боевой выгрузки AX 2012** — `%AX_AOT_PATH%\<Тип>\`.
Не из `BM.xpo` (это экспорт **AX 3.0**: там нет `REFERENCEDATASOURCES`,
`PARTREFERENCES` и части свойств) и не по аналогии с соседним объектом **другого
вида** — у формы с источником данных и без него разный `OBJECTBANK`, у таблицы
`INDICES` устроен не как `GROUPS`.

Проверка образца — одной командой, до того как писать:

```powershell
# найти реальный объект нужного вида и посмотреть его скелет
Select-String -Path "$env:AX_AOT_PATH\Forms\*.xpo" -Pattern "^  OBJECTBANK" -Context 0,4 |
  Select-Object -First 3
```

Балансировка блоков в `validate-xpo` такие ошибки **не ловит** — скобки сходятся,
а порядок и обязательность секций нарушены. Ошибка вылезает только при импорте в
AX, и формулировки там уводят в сторону («ожидалось ENDFORM»).

### Форма БЕЗ источников данных

`PROPERTIES` обязателен, `DATASOURCE` не должно быть вовсе:

```
  OBJECTBANK
    PROPERTIES
    ENDPROPERTIES

  ENDOBJECTBANK
```

Порядок секций формы: `PROPERTIES` → `METHODS` → `OBJECTBANK` →
`REFERENCEDATASOURCES` → `JOINS` → `PARTREFERENCES` → `DESIGN` → `PERMISSIONS` →
`ENDFORM`.

| Ошибка | Что скажет AX |
|--------|---------------|
| внутри пустой `DATASOURCE` с `METHODS` | `ожидалось OBJECTPOOL, но обнаружено METHODS` |
| `OBJECTBANK` совсем пустой, без `PROPERTIES` | `ожидалось ENDFORM, но обнаружено REFERENCEDATASOURCES` |

У формы С источником данных `METHODS` идёт **после** `ENDOBJECTPOOL` — отсюда и
соблазн скопировать блок не у той формы.

### Диалог подтверждения (текст + две кнопки)

Кнопки класть в `BUTTONGROUP`, а не в обычный `GROUP`. Команды кнопок — числовые:
**263 = OK**, **264 = Cancel**; `closedOk()` вернёт результат вызывающему.
Многострочный текст — `STRINGEDIT` с числовым `DisplayHeight`, `AllowEdit #No`,
`ShowLabel #No`, `AutoDeclaration #Yes` (иначе к контролу не обратиться из кода).

Проверенные значения свойств: `FrameType #None`, `Columns #2`, `ShowLabel #No`,
`ButtonDisplay #Text only`. Открытие из X++:

```xpp
args = new Args();
args.name(formStr(МояФорма));
args.parm(текст);

formRun = classFactory.formRunClass(args);
formRun.init();
formRun.run();
formRun.wait();     // модально

return formRun.closedOk();
```

### Таблица

Блок `INDICES` **без** обёрток `INDEX`/`ENDINDEX` (в отличие от `GROUPS`, где
`GROUP`/`ENDGROUP` обязательны) — проверяется `check_indices_shape`.

## 4. Backlog v2+ (не делать молча в v1)

- Каркасы Privilege / Duty / Role / MenuItemOutput под `AX_OBJECT_PREFIX`
- Round-trip extract Resource из `.xpo` → hash compare CLI
- Иконки/PDF теми же правилами wrapper

## Связанные скиллы

- Маркеры кода → `axapta-mod-comments`
- Раскладка `XPO/` → `axapta-project-manage`
- SharedProject релиз → `axapta-project-export` (после Resource — включить в бандл)
