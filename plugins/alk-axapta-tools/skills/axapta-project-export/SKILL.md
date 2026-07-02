---
name: axapta-project-export
description: Собирает финальный xpo-файл задачи в Microsoft Dynamics AX (объект AOT Project + тела всех его объектов в одном файле) по конвенции ALK. Используй при завершении работ по тикету или по явному запросу пользователя ("собери выгрузку", "делаем релиз", "упакуй проект", "закрываем тикет"). Также предложи (вопросом, не молча) промежуточный чекпоинт-релиз при завершении фазы/milestone в многофазных проектах ("фаза завершена", "спайк готов", "этап реализован") — не дожидаясь закрытия всего тикета. Папка XPO/ в корне проекта ОБЯЗАТЕЛЬНА для любого проекта с Axapta-модификациями — если её нет, скилл создаёт её (переносит существующие .xpo или готовит пустую). Формирует имя SharedProject_<AOTProjectName>_<YYYYMMDD>_<HHMM>.xpo, проверяет наличие всех объектов, размещает файл в XPO/_release/. Перед сборкой запрашивает подтверждение имени AOT Project (по умолчанию ALK_DEVAX12_<TicketCode> из активной memory) и списка включаемых объектов.
---

# Axapta Project Export

В проектах ALK Microsoft Dynamics AX 2012 финал каждой задачи — единый импортируемый `.xpo` файл, содержащий и сам объект AOT Project (с разложенными по подпапкам ссылками на объекты задачи), и тела этих объектов. Заказчик импортирует одной командой, без риска забыть отдельный объект.

## Когда применять

**Проактивно**, когда пользователь сигнализирует о завершении задачи:
- «всё, задача готова», «закрываем тикет», «передаём заказчику»
- «делаем релиз», «собираем выгрузку», «упакуй проект»
- «финальная xpo», «итоговый файл»

**По явному запросу** — пользователь зовёт навык напрямую.

**НЕ применять** в середине работы, когда правки ещё идут — выгрузка делается после того, как все маркеры расставлены и тестирование пройдено.

### Промежуточные чекпоинты в многофазных проектах

Правило «жди явного закрытия тикета» рассчитано на типичную ALK-задачу (одна сессия,
один день). Для проекта, разбитого на несколько фаз/этапов на много сессий (roadmap
в плане, epic-тикет) — ждать финального закрытия тикета означает не иметь ни одного
снапшота неделями. Если план/задача явно фиксирует завершение фазы или значимого
milestone («Фаза N реализована», «спайк работает», «этап готов») — **спроси**
пользователя через `AskUserQuestion`, не собрать ли промежуточный чекпоинт-релиз
(не заменяет финальную выгрузку при реальном закрытии тикета, а фиксирует прогресс).
Не собирай его молча без вопроса — решение всегда за пользователем.

### Папка `XPO/` обязательна для любого проекта с Axapta-модификациями

Любой репозиторий/проект, содержащий X++ модификации (`.xpo` под маркерами
`axapta-mod-comments`), **ДОЛЖЕН** иметь в корне папку `XPO/` — это не рекомендация,
а требование. Весь инструментарий `XPOTools` (`organize-xpo`, `sync-xpo`, `cleanup-xpo`,
`build-shared-project`, `validate-xpo`) и скилл `axapta-project-manage` по умолчанию
рассчитаны на эту точку входа; расхождение ломает композицию инструментов между собой.

Это касается и репозиториев смешанного типа (например, тулинг с C#/другим кодом плюс
сопутствующие X++ объекты) — X++ исходники всё равно кладутся в `XPO/` в корне
репозитория (или в корне суб-проекта), даже если остальной код лежит по другой
структуре (`src/` и т.п.).

**Если папки `XPO/` нет — создать её**, а не просто предупредить:
1. Если в проекте уже есть `.xpo`-файлы вне `XPO/` (например, разбросаны по `src/`) —
   переместить их в `XPO/` (сохраняя AOT-подпапки, если они уже были логически
   разложены по типу — `Classes/`, `Jobs/`, и т.п.; иначе положить плоско и предложить
   `organize-xpo` для раскладки по типам).
2. Если проект только начинается — создать пустую `XPO/` сразу при первом же
   `.xpo`-файле, до вызова `axapta-mod-comments`.
3. Сообщить пользователю, что папка создана/файлы перенесены, одним коротким абзацем.

## Исполнитель сборки

**Основной путь** — Python-скрипт `XPOTools/build-shared-project.py` (общий инструмент для всех ALK-проектов, бандлирован в плагин — `${CLAUDE_PLUGIN_ROOT}/scripts/XPOTools/`, документация — `${CLAUDE_PLUGIN_ROOT}/scripts/XPOTools/README.md`). Плагин автоматически добавляет `bin/` в PATH, поэтому команды доступны сразу:

```powershell
build-shared-project --root .\XPO --project-name ALK_DEVAX12_<TICKET> --dry-run
build-shared-project --root .\XPO --project-name ALK_DEVAX12_<TICKET> --yes
validate-xpo .\XPO --strict
fix-mojibake .\XPO --dry-run
split-shared-project .\XPO\_release\SharedProject_*.xpo --out .\XPO
```

**Fallback при не настроенном PATH** — полный путь через переменную плагина:

```powershell
python "${CLAUDE_PLUGIN_ROOT}/scripts/XPOTools/build-shared-project.py" --root .\XPO ...
```

**Ручная сборка через Write** — последний fallback при отсутствии Python (нужно повторить алгоритм из §1–§9 строго). Использовать только если ничего другого нет: ручная сборка дрейфует от формата AOS Export, текстовая склейка уже автоматизирована.

## Параметры сборки

| Параметр | Источник | Пример |
|----------|----------|--------|
| `<AOTProjectName>` | По умолчанию `ALK_DEVAX12_<TicketCode>` из memory `project_current_modification.md` | `ALK_DEVAX12_DAX_012234` |
| `<YYYYMMDD>` | Системная дата (`Get-Date -Format yyyyMMdd`) | `20260508` |
| `<HHMM>` | Системное время (`Get-Date -Format HHmm`) | `1430` |
| `<Origin>` GUID | Сгенерировать новый при первой сборке проекта; для повторной — взять из предыдущей выгрузки | `{9D28BF0C-8A7C-416E-A95D-CD64E7397797}` |
| Список объектов | Сканирование `XPO/*.xpo` в папке задачи | Class, Table, Form, Resource, ... |

**Дату/время бери только из системы**, не из памяти и не из `currentDate` (последний даёт только дату). Команда: `Get-Date -Format "yyyyMMdd_HHmm"`.

## Алгоритм

### 0. Проверка конфига (ПЕРВЫЙ ШАГ — до любых инструментов)

Проверь наличие `config.local.json` в папке XPOTools:

```powershell
Test-Path "C:/Users/$env:USERNAME/.claude/plugins/cache/alk-axapta/alk-axapta-tools/1.0.0/scripts/XPOTools/config.local.json"
```

Если файл **отсутствует** — через `AskUserQuestion` запроси у пользователя три значения:
- `ALK_PROJECT_PREFIX` (например `ALK_DEVAX12`)
- `ALK_USER_NICK` (ник разработчика)
- `ALK_AOT_PROD` (путь к папке AOT-Prod, можно оставить пустым)

Затем создай файл через `Write`:
```json
{
  "ALK_PROJECT_PREFIX": "<значение>",
  "ALK_USER_NICK": "<значение>",
  "ALK_AOT_PROD": "<значение или пустая строка>"
}
```

Без этого файла `validate-xpo` не проверяет маркеры модификаций и не ловит ошибки типа «блок вместо header».

### 1. Сбор контекста

0. **Проверь layout XPO/.** Если файлы лежат плоско (`xpo\Class_*.xpo`, `xpo\Table_*.xpo`, ...) и в задаче ≥10 объектов разных типов — предложи пользователю сначала прогнать `organize-xpo organize --root .\XPO --dry-run` (скилл [axapta-project-manage](file:///C:/Users/akaz/.claude/skills/axapta-project-manage/SKILL.md)). Это упрощает навигацию и diff с боевой выгрузкой `AOT-Prod`. На саму сборку `build-shared-project` это **не влияет** — сборщик поддерживает оба layout (плоский и AOT) через рекурсивный glob. Шаг опциональный, но рекомендуется перед финальным релизом.
1. Прочитай активную memory — `~/.claude/projects/<encoded-project-path>/memory/project_current_modification.md`. Возьми оттуда `<TicketCode>`, `<Description>`, `<UserNick>`.
2. Если memory не найдена или устарела (другой тикет) — спроси через `AskUserQuestion`.

### 2. Подтверждение имени AOT Project

Через `AskUserQuestion` предложи `ALK_DEVAX12_<TicketCode>` как имя по умолчанию, дай возможность переопределить.

### 3. Сканирование объектов

**Рекурсивный** `Glob "**/*.xpo"` в `XPO/` папки задачи (поддерживает оба layout — плоский корень `XPO/Class_*.xpo` и AOT-структуру `XPO/Classes/*.xpo`, `XPO/Data Dictionary/Tables/*.xpo`, ...). Для каждого файла:
- прочти первые 50 строк, определи тип секций (`***Element: DBT/MAP/VIE/CLS/FRM/...`);
- извлеки имена объектов (после `TABLE #`, `CLASS #`, `FORM #` и т.п.);
- сгруппируй по типу.

Файлы из `XPO/_release/` — пропускать (это предыдущие сборки, не исходники). Фильтр рекурсивный: `if "_release" in path.relative_to(root).parts` — учитывает и `XPO/_release/`, и `XPO/_release/_archive/`.

**Перед сборкой обязательно прогнать `validate-xpo`:**

```powershell
validate-xpo <project>\XPO --strict
```

Валидатор проверяет: BOM+CRLF, балансировку блоков (PROJECT/ENDPROJECT, GROUP/ENDGROUP, BEGINNODE/ENDNODE, SOURCE/ENDSOURCE, PROPERTIES/ENDPROPERTIES), отсутствие mojibake, наличие маркеров `axapta-mod-comments`, уникальность имён объектов между .xpo. Если exit ≠ 0 — **остановиться**, разобрать ошибки.

При обнаружении mojibake (артефакты вроде `Ð`, `Ñ`, `â„–`) — вызвать `fix-mojibake <project>\XPO`, повторить `validate-xpo`. Только после зелёного валидатора переходить к §4.

### 4. Подтверждение списка

Покажи пользователю таблицу «тип → имена объектов» и спроси через `AskUserQuestion`, всё ли включаем. Дай опцию «добавить вручную» (например, новые объекты, ещё не выгруженные). Если пользователь хочет добавить — попроси приклеить .xpo в `XPO/` или указать путь.

**Маркеры мод-комментариев** (`axapta-mod-comments`) — `validate-xpo --strict` уже проверил их в §3. Если он выдал WARN (не ERROR) о маркерах — спроси через `AskUserQuestion`: «В файле X маркер модификации не найден. Это допустимо для Resource/LabelFile/Menu/MenuItem (для них маркер живёт только в `docs/CHANGES.md`), для остальных типов — обычно ошибка. Включать в сборку?» — и действуй по ответу.

### 4a. Dry-run preview

Перед записью бандла обязательно прогнать `--dry-run`, чтобы увидеть PRN-структуру и порядок объектов в группах:

```powershell
build-shared-project --root <project>\XPO --project-name ALK_DEVAX12_<TICKET> --dry-run
```

Покажи пользователю распечатанный список объектов (сгруппированных по PRN-группам) и попроси подтверждения через `AskUserQuestion`. Это последний шанс заметить «забытый» или «лишний» объект до записи на диск.

### 5. Время сборки

```powershell
$dt = Get-Date -Format "yyyyMMdd_HHmm"
```

Сохрани в переменную, дальше используй для имени файла.

### 6. GUID для Project

Только если это **первая** сборка проекта. Поищи предыдущие выгрузки в `XPO/_release/SharedProject_<AOTProjectName>_*.xpo`:
- если есть — прочти, найди `Origin #{...}` в секции `PRN`, переиспользуй;
- если нет — сгенерируй новый: `[guid]::NewGuid().ToString().ToUpper()` → обернуть в `{...}`.

### 7. Сборка содержимого

Структура итогового файла:

```
Exportfile for AOT version 1.0 or later
Formatversion: 1

<тела объектов в порядке групп проекта: CLS → MNU → FTM → ...>

***Element: PRN

; Microsoft Dynamics AX Project : <AOTProjectName> unloaded
; --------------------------------------------------------------------------------
  PROJECTVERSION 2
  
  PROJECT #<AOTProjectName>
  SHARED
  PROPERTIES
    Name                #<AOTProjectName>
    Origin              #<GUID>
  ENDPROPERTIES
  
    PROJECTCLASS ProjectNode
    GROUP #Classes
      PROPERTIES
        Name                #Classes
        ProjectGroupType    #Classes
        GroupMask           #
        PreventEditProperties #No
      ENDPROPERTIES
      
      BEGINNODE
        FILETYPE 0
        UTILTYPE 45
        UTILOBJECTID 0
        NODETYPE 329
        NAME #ALK_eActDeviationActReport
      ENDNODE
      ENDGROUP
      
    GROUP #Menus
      PROPERTIES
        Name                #Menus
        ProjectGroupType    #Menus
        GroupMask           #
        PreventEditProperties #No
      ENDPROPERTIES
      
      BEGINNODE
        FILETYPE 0
        UTILTYPE 16
        UTILOBJECTID 0
        NODETYPE 205
        NAME #ALK_BackOffice
      ENDNODE
      ENDGROUP
      
    GROUP #MenuItems
      PROPERTIES
        Name                #MenuItems
        ProjectGroupType    #MenuItems
        GroupMask           #
        PreventEditProperties #No
      ENDPROPERTIES
      
      GROUP #Output
        PROPERTIES
          Name                #Output
          ProjectGroupType    #Output
          GroupMask           #
          PreventEditProperties #No
        ENDPROPERTIES
        
        BEGINNODE
          FILETYPE 0
          UTILTYPE 2
          UTILOBJECTID 0
          NODETYPE 296
          NAME #ALK_eActDeviationActReport
        ENDNODE
        ENDGROUP
        
      ENDGROUP
      
  ENDPROJECT
  

***Element: END
```

**Не пересортировывать методы** внутри `SOURCE/ENDSOURCE`! Порядок методов в классе должен оставаться таким же, каким он был в исходнике (`Class_*.xpo`). AOS Export фиксирует порядок (классы методов идут в стабильном порядке: `classDeclaration`, далее по алфавиту), и текстовая сборка должна это сохранять — иначе `diff` между релизами будет шумным, и hardcoded-ranges-инструменты (как `extract_methods_from_xpo.py` в эталонном репо DynamicsAX) ломаются.

**ВКЛЮЧАЙ ТОЛЬКО НЕПУСТЫЕ ГРУППЫ.** Реальный AOS Export не выгружает пустые `GROUP` — только те, где есть `BEGINNODE` (или есть подгруппа с `BEGINNODE`). Скелет «как в TEMPLATE.xpo» — это каталог всех возможных групп, а не образец итогового файла. Сравнивай с реальным экспортом из работающего проекта (например, `XPO/SharedProject_ALK_DEVAX12_DAX_012135.xpo` в этой задаче), а не с TEMPLATE.

**Порядок тел объектов** должен совпадать с порядком групп в PRN: сначала Classes-bodies (`***Element: CLS`), затем Menus (`MNU`), затем Menu Items (`FTM`), и т.д. AX принимает любой порядок при импорте, но удобнее держать как в оригинальном экспорте — диф между релизами становится читаемым.

**ВАЖНО про названия групп**: реальный экспорт использует **слитные** идентификаторы (без пробела) для составных названий — `MenuItems`, `LabelFiles`, `DataSets`, `CueGroups`, `ServiceGroups`, `WorkflowApprovals`, и т.д. В TEMPLATE.xpo для красоты человеческого восприятия некоторые из них записаны с пробелом (`Menu Items`, `Cue Groups`) — **это вводит в заблуждение**. Всегда проверяй в реальном AOS Export для интересующего типа. Корректные имена `Name`/`#GROUP` для часто встречающихся групп:

| Группа | `Name` (в `#GROUP` и `Name #...`) | `ProjectGroupType` |
|--------|------------------------------------|--------------------|
| Classes | `Classes` | `Classes` |
| Forms | `Forms` | `Forms` |
| Menus | `Menus` | `Menus` |
| Menu Items (контейнер) | `MenuItems` | `MenuItems` |
| · Display | `Display` | `Display` |
| · Output | `Output` | `Output` |
| · Action | `Action` | `Action` |
| Resources | `Resources` | `Resources` |
| Queries | `Queries` | `Queries` |
| Jobs | `Jobs` | `Jobs` |
| Macros | `Macros` | `Macros` |
| Data Dictionary (контейнер) | `Data Dictionary` | `DataDictionary` |
| · Tables | `Tables` | `Tables` |
| · Maps | `Maps` | `Maps` |
| · Views | `Views` | `Views` |

### 8. Запись BEGINNODE

```
BEGINNODE
  FILETYPE 0
  UTILTYPE <type>
  UTILOBJECTID <id>
  NODETYPE <node>
  NAME #<ObjectName>
ENDNODE
```

Таблица UTILTYPE/NODETYPE (проверена на эталоне `SharedProject_ALK_DEVAX12_TEMPLATE.xpo`, расширена 08.05.2026):

| Тип объекта | UTILTYPE | NODETYPE | Группа в Project |
|-------------|----------|----------|-------------------|
| Table | 44 | 204 | `Data Dictionary > Tables` |
| Map | 44 | 236 | `Data Dictionary > Maps` |
| View | 44 | 243 | `Data Dictionary > Views` |
| Extended Data Type | 41 | 228 | `Data Dictionary > Extended Data Types` |
| Base Enum | 40 | 209 | `Data Dictionary > Base Enums` |
| License Code | 15 | 311 | `Data Dictionary > License Codes` |
| Configuration Key | 35 | 312 | `Data Dictionary > Configuration Keys` |
| Table Collection | 48 | 211 | `Data Dictionary > Table Collections` |
| Perspective | 66 | 1311 | `Data Dictionary > Perspectives` |
| Macro | 4 | 218 | `Macros` |
| Class | 45 | 329 | `Classes` |
| Form | 11 | 201 | `Forms` |
| Reference (.NET assembly) | 53 | 822 | `References` |
| DataSet | 72 | 207 | `DataSets` |
| Info Part | 81 | 1429 | `Parts > Info Parts` |
| Form Part | 82 | 1431 | `Parts > Form Parts` |
| Cue | 98 | 1543 | `Parts > Cues` |
| Cue Group | 99 | 1544 | `Parts > Cue Groups` |
| SSRS Report | 85 | 1439 | `SSRS Reports > Reports` |
| Label File | 117 | 831 | `LabelFiles` |
| VS Dynamics AX Model Project | 127 | 1531 | `Visual Studio Projects > Dynamics AX Model Projects` |
| VS C# Project | 128 | 1531 | `Visual Studio Projects > C Sharp Projects` |
| Query | 20 | 330 | `Queries` |
| Job | 5 | 215 | `Jobs` |
| Menu | 16 | 205 | `Menus` |
| Menu Item — Display | 1 | 296 | `Menu Items > Display` |
| Menu Item — Output | 2 | 296 | `Menu Items > Output` |
| Menu Item — Action | 3 | 296 | `Menu Items > Action` |
| Service | 76 | 1321 | `Services` |
| Service Group | 137 | 1325 | `Service Groups` |
| Workflow Category | 71 | 1423 | `Workflow > Workflow Categories` |
| Workflow Approval | 70 | 1421 | `Workflow > Approvals` |
| Workflow Task | 69 | 1417 | `Workflow > Tasks` |
| Workflow Automated Task | 95 | 1409 | `Workflow > Automated Tasks` |
| Workflow Type | 68 | 1412 | `Workflow > Workflow Types` |
| Workflow Hierarchy Provider | 139 | 1397 | `Workflow > Providers > HierarchyAssignment` |
| Code Permission | 115 | 1608 | `Security > Code Permissions` |
| Privilege | 134 | 1628 | `Security > Privileges` |
| Duty | 135 | 1630 | `Security > Duties` |
| Role | 133 | 1626 | `Security > Roles` |
| Process Cycle | 136 | 1636 | `Security > Process Cycles` |
| Policy | 119 | 1619 | `Security > Policies` |
| Resource | 21 | 820 | `Resources` |

Если встречается тип, **отсутствующий** в таблице:
1. Создай в DEV-AOS Shared Project с одним объектом этого типа.
2. Сделай AOS Export.
3. Открой полученный xpo, выпиши `UTILTYPE` и `NODETYPE` соответствующего `BEGINNODE`.
4. Дополни эту таблицу в SKILL.md (правка через Edit) и в `docs/CONVENTIONS.md` §9 в проекте.
5. Используй полученные значения для текущей и будущих сборок.

`UTILOBJECTID` — внутренний ID в AOS. Безопасное значение `0` (AX подменит при импорте). Если знаешь точный ID — поставь его.

### 9. Запись файла

Путь:
```
<task-folder>/XPO/_release/SharedProject_<AOTProjectName>_<YYYYMMDD>_<HHMM>.xpo
```

**Никогда не перезаписывай существующий файл.** Если файл с таким именем уже есть (например, повторная сборка в ту же минуту) — увеличь время на 1 минуту или добавь суффикс `_v2`, `_v3` и т.д.

**Кодировка обязательно UTF-8 with BOM + CRLF** — AX 2012 R2 не парсит UTF-8 без BOM (русские буквы в комментариях ломают разбор, в трее импорта появляются «фантомные» узлы вроде `Menus → MNUVERSION 5`). Все исходные `XPO/*.xpo` тоже должны быть в этой кодировке, иначе при сборке через `splitlines()` BOM «всплывёт» в середине файла. Перед сборкой нормализуй каждый исходник:

```python
def write_xpo(path, content):
    if not content.endswith("\n"):
        content += "\n"
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(content.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
```

Проверка через PowerShell (точная, не зависит от наличия `file` из coreutils):

```powershell
$b = [System.IO.File]::ReadAllBytes($p)[0..2]
if ($b[0] -ne 0xEF -or $b[1] -ne 0xBB -or $b[2] -ne 0xBF) { throw "no BOM" }
```

**Канонический инструмент проверки** — `validate-xpo` (из `XPOTools/`): он делает BOM/CRLF/балансировку/mojibake/маркеры/уникальность за один вызов. Прогонять и до сборки (на исходниках), и после (на финальном бандле):

```powershell
validate-xpo <project>\XPO\_release\SharedProject_*.xpo --strict
```

Используй `Write` или прямой бинарный `open(..., "wb")` для создания файла. Перед этим — `ls` папки `_release/`, чтобы увидеть существующие сборки.

### 9a. Шапка-комментарии в исходных .xpo

В каждом `***Element: ...` AX-Prod держит **ровно 2** строки `;`-комментариев в шапке:

```
***Element: MNU

; Microsoft Dynamics AX Menu : <Name> unloaded
; --------------------------------------------------------------------------------
  MNUVERSION 5
```

**Не добавляй дополнительные `;`-строки** (даже как маркер модификации). AX 2012 R2 после этого начинает парсить тело некорректно: для меню — берёт `MNUVERSION 5` как имя меню; для MenuItem — теряет `Type:` и кладёт элемент не в ту группу (Output → Action) с ошибкой «Неизвестный тип пункта меню» / «Метод AOTLayers() не поддерживается для узла дерева».

Маркер модификации для Menu/MenuItem ставится **в `docs/CHANGES.md`** (отдельный раздел про правку меню), а не в `;`-шапке xpo. Маркер в `;`-шапке допустим только для типов, у которых тело уже всё равно проходит через `;`-парсер (Class через `#//маркер` внутри `SOURCE #classDeclaration` — это другой случай, тут шапка не трогается).

### 10. Отчёт пользователю

Кратко:
- путь к собранному файлу;
- размер (байты);
- число объектов по типам;
- ссылка на инструкцию импорта (`docs/CONVENTIONS.md` §9 «Импорт у заказчика»).

**Обязательно** дописать запись о релизе в `docs/CHANGES.md` задачи (после успешной записи бандла):

```markdown
## YYYY-MM-DD HH:MM — Release SharedProject_<AOTProjectName>_<YYYYMMDD>_<HHMM>.xpo
- Включено объектов: N (Classes: a, Tables: b, MenuItems: c)
- Origin GUID: {...}
- Размер: N байт
- Импорт у заказчика: AOT → File → Import → выбрать файл (см. `docs/CONVENTIONS.md` §9).
```

Без этой записи задача считается **не закрытой**: история сборок задачи теряется (в `_release/` остаются только файлы с timestamp'ами в именах, без описания состава).

### 11. Round-trip-проверка через DEV-AOS (рекомендуется)

После сборки — импортировать бандл в DEV-AOS, сделать AOS Export того же проекта обратно, прогнать `diff` против локальной сборки. Ожидаемые расхождения:

- `UTILOBJECTID 0` → реальный ID объекта в AOS (текстовая сборка не знает реальные ID).
- Иногда — порядок свойств внутри `PROPERTIES` (если AX добавил какие-то дефолты).

Любые **другие** расхождения — это регресс текстовой сборки; стоп, разобрать.

Если round-trip не делался — отчёт о релизе должен явно сказать «текстовая сборка, импорт-проверка пользователем не выполнена».

### 12. Round-trip через split-shared-project (восстановление)

Если `XPO/*.xpo` потеряны, а `_release/<последний>.xpo` сохранился — восстановить исходники через `split-shared-project`:

```powershell
split-shared-project <project>\XPO\_release\SharedProject_*.xpo --out <project>\XPO
```

Это даст `<file_prefix><Name>.xpo` для каждого `***Element: <type>` из бандла (например, `Class_ALK_*.xpo`, `Menu_ALK_*.xpo`, `MenuItemOutput_ALK_*.xpo`). Проверить байт-в-байт совпадение с прежними исходниками — если в `git`-репо были коммиты, `git diff` это покажет.

## Эталонные пути

- **Шаблон-каталог Project xpo**: `E:\ZeroCoder\Axapta\ERP\SharedProject_ALK_DEVAX12_TEMPLATE.xpo` — каталог всех возможных групп с примерами `BEGINNODE` для всех ключевых типов (см. таблицу UTILTYPE/NODETYPE). **Используй ТОЛЬКО для извлечения UTILTYPE/NODETYPE**, не для копирования структуры PRN — там полный скелет с пустыми группами и местами не совпадающими названиями (`Menu Items` vs реальное `MenuItems`).
- **Реальный AOS Export для сверки формата (плоский XPO/)**: например, `E:\ZeroCoder\LT_DAX-12135\XPO\SharedProject_ALK_DEVAX12_DAX_012135.xpo` (только Class+Menu+MenuItem) — образец компактного PRN-формата с тремя группами и без скелета.
- **Пример задачи в AOT-layout**: `E:\ZeroCoder\LT_DAX-Verme\xpo\` — 44 файла, разложены по `Classes\`, `Data Dictionary\Tables\`, `Menu Items\Display\`, `Security\Privileges\` и т.д. через `organize-xpo` (скилл [axapta-project-manage](file:///C:/Users/akaz/.claude/skills/axapta-project-manage/SKILL.md)). `build-shared-project` собирает релиз из такой структуры через рекурсивный glob.
- **Боевая выгрузка**: `E:\ZeroCoder\Axapta\ERP\AOT-Prod` — для примеров тел объектов и эталона AOT-структуры (`Classes\`, `Data Dictionary\Tables\`, ...).

## Anti-patterns

- **Не перезаписывай** файлы в `_release/`. История сборок важнее места на диске.
- **Не используй дату из памяти.** Только `Get-Date` в момент сборки.
- **Не пропускай пользователя.** Перед записью обязательно покажи список объектов и спроси подтверждение — могут быть забытые объекты или включённые лишние.
- **Не выдумывай UTILTYPE/NODETYPE** для типов, которых нет в эталоне. Лучше остановиться, попросить разработчика сделать ручной AOS Export для расширения таблицы, чем испортить выгрузку.
- **Не пиши без BOM.** UTF-8 без BOM в .xpo с русскими комментариями ломает парсер AX 2012 R2 (см. §9). Только UTF-8 with BOM + CRLF.
- **Не добавляй лишние `;`-комментарии в шапку** Menu/MenuItem/etc. (см. §9a). Ровно 2 стандартные строки.
- **Не редактируй тела объектов** в момент сборки — они должны быть финализированы до. Сборка — read-only операция над `XPO/` (за исключением нормализации кодировки исходников, см. §9).
- **Не вставляй пустые `GROUP` в PRN.** Только группы с реальными `BEGINNODE` или с непустыми подгруппами. AX принимает оба варианта, но «полный скелет» отличается от формата AOS Export → диф между релизами шумит.
- **Не доверяй TEMPLATE.xpo для имён групп.** Эталон `MenuItems`/`Menu Items` и аналогичные расхождения видны только при сравнении с реальным AOS Export проекта (см. таблицу в §7). Сомневаешься — попроси разработчика выгрузить пробный проект.
- **Не текстовая склейка вместо AOS Export** для критических релизов. Текстовая сборка — best-effort, обязательно проверять импортом в DEV-AOS перед передачей. Если у разработчика есть доступ к AOS, рекомендуй ему стандартный путь (AOT → Project → Export).
- **Не игнорируй mojibake-warning** валидатора. Ð/Ñ/â„– в .xpo — это сломанная кодировка, после импорта в AX русские комментарии превратятся в мусор и метаданные тоже могут поехать. Сначала `fix-mojibake`, потом сборка.
- **Не пропускай запись в `docs/CHANGES.md`** после сборки. Файлы в `_release/` хранят только timestamp в имени; без записи в CHANGES.md через месяц нельзя понять, что было в каждом релизе.
- **Не переписывай build-скрипт под захардкоженные значения тикета** (старая привычка из `_build_shared_project.py` в `LT_DAX-12135/docs/templates/`). Используй CLI-флаги `--project-name`, `--guid`, `--dt-stamp`. Хардкод дрейфует, а универсальный сборщик идёт в общий git-репо `XPOTools/` и улучшается централизованно.
- **Не зашивай локальные пути в код** (например `E:\ZeroCoder\LT_*\XPO`). Все ALK-специфичные значения — через ENV-переменные `ALK_PROJECT_PREFIX`/`ALK_USER_NICK`/`ALK_AOT_PROD` (задаются один раз через скилл `/alk-axapta-tools:setup`).
- **Не запускай `organize-xpo` непосредственно перед `build-shared-project` без `validate-xpo`.** Правильный порядок: organize → validate-xpo --strict (в т.ч. layout-consistency check) → build. Если layout-consistency находит несоответствие — это значит organize ошибся, и в бандле объект окажется не в той группе.

## Workflow с разработчиком

Если в DEV-AOS есть готовый Project с уже разложенными объектами — лучший путь:

1. Спроси: «Project в AOS уже собран? Если да — экспортируй вручную через AOT → правый клик на проекте → Export → сохрани в `XPO/_release/SharedProject_<AOTProjectName>_<YYYYMMDD>_<HHMM>.xpo`.»
2. После экспорта проверь — открой файл, убедись в корректности имени, наличии секции `***Element: PRN` и нужных объектов.
3. Если разработчик попросил собрать через Claude — иди по основному алгоритму выше.

## Формат отчёта

Один абзац по схеме:

> Собрал релиз `SharedProject_ALK_DEVAX12_DAX_012234_20260508_1430.xpo` в `XPO/_release/`. Размер: ~35 KB. Включено: 1 Class (`SysMonUserOnDutyScheduleReport_CDT`). Импорт у заказчика — AOT → File → Import → выбрать файл (см. `docs/CONVENTIONS.md` §9).

Без эмодзи, без лишних украшений.
