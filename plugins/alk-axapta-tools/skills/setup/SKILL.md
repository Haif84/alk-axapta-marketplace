---
name: setup
description: Разовая настройка рабочего места ALK Axapta Tools — записывает user-level ENV-переменные (AX_USER_NICK, AX_PROJECT_ID, AX_OBJECT_PREFIX/AX_OBJECT_SUFFIX — обязательны для любого другого скилла плагина, preflight-гейт; AX_AOT_PATH — опционально, нужен только sync-xpo), которые XPOTools читает приоритетно. Запускай ОДИН РАЗ на компьютере после установки плагина, либо когда нужно сменить ник разработчика, путь к боевой выгрузке AOT-Prod, ID проекта или аффикс именования. Триггеры — «настрой alk», «setup alk», «пропиши ник», «задать путь к AOT-Prod», «задать аффикс именования», «первичная настройка», а также автоматически — когда другой скилл плагина обнаруживает неполную конфигурацию через preflight-проверку.
disable-model-invocation: true
---

# ALK Axapta Tools — первичная настройка

Разовая настройка рабочего места: записывает user-level ENV-переменные в профиль
пользователя (`HKCU\Environment`). Они переживают любые обновления плагина и не требуют
прав администратора. Клонировать репозиторий не нужно — скрипт входит в состав плагина.

Записываются переменные:

| Переменная | Назначение | Обязательность |
|------------|------------|----------------|
| `AX_USER_NICK` | Ник разработчика — подставляется в комментарии модификаций | да |
| `AX_AOT_PATH` | Путь к боевой выгрузке AOT-Prod — нужен только для `sync-xpo` | нет — опционально; при работе через живой MCP-сервер AX офлайн-выгрузка не требуется |
| `AX_PROJECT_ID` | ID/префикс проектов ALK (напр. `ALK_DEVAX12`) | да |
| `AX_OBJECT_PREFIX` | Аффикс новых идентификаторов, lowercase (напр. `alk_`) — конвенция именования в `axapta-mod-comments` | ровно один из пары |
| `AX_OBJECT_SUFFIX` | Постфикс-альтернатива `AX_OBJECT_PREFIX` | ровно один из пары |

`AX_OBJECT_PREFIX`/`AX_OBJECT_SUFFIX` — взаимоисключающая пара: должен быть задан **ровно
один**, не оба и не ни одного. Скрипт настройки останавливается с ошибкой при нарушении.

ENV-переменные имеют **приоритет** над `config.local.json` (тот лежит в кэше плагина и стирается
при обновлении) — поэтому вся конфигурация, заданная здесь, переживает обновления плагина.

### Конфиг уровня проекта — `.axapta.json`

ENV настраивается один раз на машину, но отдельный репозиторий может вести модификацию
под **другим** кодом проекта или другим аффиксом. Для этого рядом с репозиторием кладётся
`.axapta.json` — он **перекрывает ENV** и ищется вверх по дереву от текущей директории,
поэтому работает и при запуске инструментов из подкаталога:

```json
{
  "AX_PROJECT_ID": "ALK_CDT000",
  "AX_OBJECT_PREFIX": "",
  "AX_OBJECT_SUFFIX": "_cdt",

  "AX_AOT_PROJECT": "ALK_CDT000_MOD_240_APP_MCPServer_akaz",
  "AX_MODIFICATION_ID": "MOD-240-APP",
  "AX_MODIFICATION_DESC": "Разработка MCP-сервера для Axapta (by AKAZ)"
}
```

Задавать здесь нужно **только то, что отличается от машинных настроек**. `AX_AOT_PATH`
и `AX_USER_NICK` одинаковы для всех задач разработчика, поэтому их место в ENV —
дублировать в каждом репозитории незачем.

Нижние три ключа — **параметры модификации**, и место им именно здесь, а не в ENV:
они меняются от задачи к задаче, и машинная переменная молча подставила бы их в
соседнем репозитории, где модификация уже другая. Из `AX_PROJECT_ID`,
`AX_MODIFICATION_ID` и `AX_USER_NICK` собирается и мод-маркер, и **имя AOT-проекта**
через `config.aot_project_name()`:

```
//{AX_PROJECT_ID}, {DAX_NNNNNN}, {AX_MODIFICATION_DESC}, {дата}, {AX_USER_NICK}
ALK_DEVAX12_DAX_012579_akaz
```

Явный `AX_AOT_PROJECT` в `.axapta.json` нужен только если имя **не** этого вида
(например CDT: `ALK_CDT000_MOD_240_APP_MCPServer_akaz`). Для обычного DAX-тикета
его можно не задавать — сборка релиза выведет сама. Готовый маркер отдаёт
`config.modification_marker('ДД.ММ.ГГГГ')` — формат живёт в одном месте, а не
собирается заново в каждой сессии.

Аффикс в настройке — всегда в **мемберной** (нижней) форме (`_cdt`, `alk_`); UPPER-форму
для имён AOT-объектов (`_CDT`, `ALK_`) скилл `axapta-mod-comments` выводит из неё сам
(см. там §«Деривация аффикса»).

Итоговый приоритет: **`.axapta.json` → ENV → `config.local.json` → `config.example.json`**.

Задавать в файле нужно только перекрываемые ключи, остальные подхватятся из ENV.
Пустая строка значима: `"AX_OBJECT_PREFIX": ""` при заданном суффиксе гасит префикс,
унаследованный из ENV, — иначе XOR-проверка увидела бы оба значения и упала.

`python config.py` печатает путь найденного файла проекта — по нему видно, какой конфиг
реально применился.

## Resolve plugin root (Claude + Cursor)

Перед любым вызовом скриптов плагина разреши `$pluginRoot` (в Cursor `CLAUDE_PLUGIN_ROOT`
часто пуст):

```powershell
$pluginRoot = $env:CLAUDE_PLUGIN_ROOT
if ([string]::IsNullOrWhiteSpace($pluginRoot) -or -not (Test-Path "$pluginRoot\scripts\XPOTools")) {
    $cache = Join-Path $env:USERPROFILE '.claude\plugins\cache\alk-axapta\alk-axapta-tools'
    if (Test-Path $cache) {
        # Кэш накапливает несколько версий (напр. 1.6.9 и 1.6.10) — сортируем по
        # [version], а не по имени: лексически "1.6.9" > "1.6.10", выбралась бы старая.
        $pluginRoot = Get-ChildItem $cache -Directory |
            Sort-Object { try { [version]$_.Name } catch { [version]'0.0' } } -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if ([string]::IsNullOrWhiteSpace($pluginRoot) -or -not (Test-Path "$pluginRoot\scripts\XPOTools")) {
    $cursorPlugins = Join-Path $env:USERPROFILE '.cursor\plugins'
    if (Test-Path $cursorPlugins) {
        $hit = Get-ChildItem $cursorPlugins -Directory -Recurse -Filter 'alk-axapta-tools' -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName 'scripts\XPOTools') } |
            Select-Object -First 1
        if ($hit) { $pluginRoot = $hit.FullName }
    }
}
if ([string]::IsNullOrWhiteSpace($pluginRoot) -or -not (Test-Path "$pluginRoot\scripts\XPOTools")) {
    throw 'alk-axapta-tools plugin root not found. Reinstall the plugin (Customize / Claude marketplace) and retry.'
}
```

Все пути ниже — через `"$pluginRoot\scripts\..."`, не через голый `${CLAUDE_PLUGIN_ROOT}`.

## Preflight-конвенция (используется всеми остальными скиллами)

Любой скилл плагина, работающий с X++ модификациями (`axapta-mod-comments`,
`axapta-project-export`, `axapta-project-manage`), **обязан** в самом начале:
1) разрешить `$pluginRoot` (блок выше); 2) прогнать проверку конфигурации:

```powershell
python "$pluginRoot\scripts\XPOTools\Modules\config.py"
```

Exit code `0` — конфигурация полная, можно продолжать. Exit code `1` — в stderr выведен
список отсутствующих/некорректных переменных; скилл должен **остановиться** и направить
пользователя сюда, на `/alk-axapta-tools:setup` — не продолжать работу с неполным
конфигом (не переспрашивать значения вручную, не подставлять тихие дефолты).

## Миграция со старых имён (`ALK_*` → `AX_*`)

Если на машине ранее были заданы `ALK_USER_NICK`, `ALK_AOT_PROD`, `ALK_PROJECT_PREFIX`,
`ALK_IDENTIFIER_PREFIX`/`ALK_IDENTIFIER_SUFFIX` (старые имена) — скрипт настройки
подхватывает их значения как дефолты для новых `AX_*`-параметров автоматически (можно
перезапустить `setup-env.ps1` вовсе без аргументов, если старые значения устраивают),
и удаляет старые переменные после успешной записи новых. Ручной перенос не нужен.

## Шаг 1. Собрать параметры

Спроси пользователя через `AskUserQuestion` (или возьми из memory, если уже сохранены):

1. **Ник разработчика** (`AX_USER_NICK`) — обязательно. Если в memory типа `user` уже есть
   ник — предложи его по умолчанию.
2. **Источник AOT** — спроси через `AskUserQuestion` с двумя вариантами:
   - **«Локальная папка»** — есть офлайн-выгрузка AOT-Prod на диске: запроси путь
     и запиши его в `AX_AOT_PATH` (нужен для `sync-xpo` — сверки с Prod).
   - **«MCP-сервер»** — работа идёт через живой MCP-сервер AX (см.
     `axapta-mcp-helper`), офлайн-выгрузки нет: `AX_AOT_PATH` НЕ записывается
     и не запрашивается. `sync-xpo` без него завершится понятной ошибкой,
     остальные инструменты не пострадают; задать путь позже можно повторным
     запуском setup.
3. **ID проекта** (`AX_PROJECT_ID`) — обязательно, по умолчанию `ALK_DEVAX12`, если
   пользователь не называет другой явно.
4. **Аффикс именования** — обязательно выбрать **один** тип: prefix или suffix, и дать
   значение в нижнем регистре (напр. `alk_`). Применяется к методам/переменным/параметрам
   в существующих объектах; для новых AOT-объектов скилл `axapta-mod-comments` берёт
   UPPER-версию (`ALK_`). Задать можно только один из двух — не оба.

### Параметры модификации — спрашивать и писать в `.axapta.json`

Если работа идёт в репозитории с кодом (есть папка `XPO/` или уже лежит
`.axapta.json`), спроси дополнительно и **запиши в `.axapta.json`, а не в ENV**:

5. **Код модификации** (`AX_MODIFICATION_ID`) — например `DAX-12768` (любой вид;
   в `.axapta.json` храни settings-форму `DAX-12768`, в маркерах и имени AOT —
   comment-форму `DAX_012768`, см. `axapta-mod-comments` §«Нормализация»).
6. **Описание модификации** (`AX_MODIFICATION_DESC`) — то, что попадёт в маркер
   дословно, например `Обогатить отчет физ. резервов для инвентаризации`.
7. **Имя AOT-проекта** (`AX_AOT_PROJECT`) — **не выдумывать смысловую часть**.
   Собери через `config.aot_project_name()`:
   `{AX_PROJECT_ID}_{код модификации в comment-форме}_{ник}`.
   Для DAX-тикета это `ALK_DEVAX12_DAX_012579_akaz`. Предложи это имя и дай
   подтвердить. Переопределение — только если заказчик требует другой формат
   (CDT со смысловой частью: `ALK_CDT000_MOD_240_APP_MCPServer_akaz`).
   Если пользователь согласен с выведенным именем, в `.axapta.json` ключ можно
   записать явно или опустить — `build-shared-project` выведет его сам.

Зачем спрашивать код и описание сразу: из них плюс машинных `AX_PROJECT_ID`/`AX_USER_NICK`
собирается мод-маркер и имя AOT-проекта, и без них `axapta-mod-comments` будет
выпрашивать те же значения в начале каждой сессии.
Пока их нет, `python config.py` печатает предупреждение, но не падает — чтение и
раскладка xpo работают и без них.

Проверить, что модификация настроена:

```powershell
python "$pluginRoot\scripts\XPOTools\Modules\config.py"
```

Блок `[задача — из .axapta.json]` должен показать `AX_MODIFICATION_ID` и
`AX_MODIFICATION_DESC`. Если `AX_AOT_PROJECT` пуст — строка
`(AOT-проект выведен) ALK_DEVAX12_DAX_012579_akaz`.

## Шаг 2. Запустить скрипт

Сначала разреши `$pluginRoot` (§«Resolve plugin root»). Затем вызови bundled-скрипт.
Пример с ником `akaz`, путём к AOT-Prod, ID проекта и аффиксом `alk_`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$pluginRoot\scripts\setup-env.ps1" -UserNick akaz -AotPath "E:\Axapta\AOT-Prod" -ProjectId ALK_DEVAX12 -ObjectPrefix alk_
```

При варианте «MCP-сервер» (Шаг 1 п.2) параметр `-AotPath` просто опусти —
скрипт не требует его и не затирает уже настроенный `AX_AOT_PATH`, если тот
был задан раньше.

Если на машине уже стоят старые `ALK_*`-значения и пользователь просто хочет их
мигрировать без изменений — запуск без аргументов тоже сработает (дефолты подхватятся
из старых переменных); но текущий скилл почти всегда вызывается именно потому, что
чего-то не хватает — так что параметры обычно нужно передать явно.

Скрипт также проверит наличие Python >= 3.9 (нужен XPOTools) и предупредит, если его нет.

## Шаг 3. Сохранить в memory и напомнить о перезапуске

- Сохрани ник, ID проекта и аффикс именования в memory типа `user`, чтобы не переспрашивать
  в других задачах.
- Предупреди пользователя: ENV-переменные подхватятся только в **новой** сессии PowerShell/cmd
  или после перезапуска VS Code. Проверка: `$env:AX_USER_NICK`.
- Если скилл вызван автоматически (preflight другого скилла обнаружил неполноту) — после
  успешной настройки вернись к прерванному скиллу и повтори preflight-проверку.
