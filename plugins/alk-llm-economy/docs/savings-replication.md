# Перенос экономящей конфигурации Claude Code на другую машину

Инструкция для агента. Читатель — Claude Code на новой машине, которому
поручено воспроизвести настройки, хуки и правила из этого репозитория.
Здесь только то, что работает и измерено; механизм и число — при каждой
мере. Откуда числа и что отклонено — `savings-report-2026-09-18.md` рядом.

Папка, в которой лежит этот файл, самодостаточна: `hooks/`, `scripts/`,
`agents/`, `global/`, `templates/`, `docs/`, `deploy.ps1`,
`settings.fragment.json` — всё здесь (состав в `README.md`). Пути ниже —
относительно неё.

Допущения: Windows 10/11, Windows PowerShell 5.1 (все хуки — `.ps1`), Node
20+, git, Claude Code 2.1.x. Папка кладётся на постоянное место, например
`C:\Proj\ClaudeOps`: `deploy.ps1` делает junction из `~/.claude` на её
подпапки, и переезд папки их сломает. `<HOME>` — домашняя папка владельца
(`$env:USERPROFILE`). Ничего не ставить из сети без явного разрешения
владельца; папка и `node --test` сети не требуют.

---

## 1. Что переносится и почему это экономит

Модель платы: каждый ход платит за весь накопленный контекст; чтение кэша
стоит ×0.1 от входа, запись ×1.25 (TTL 5 мин) или ×2 (TTL 1 час); любая смена
префикса (модель, `settings.json`, `CLAUDE.md`) переписывает кэш целиком.
За 2026-09-15…18 ($888.34, 13 367 ходов): чтение кэша 46.0 %, запись 35.1 %,
выход 18.9 %. Поэтому меры бьют по четырём точкам: постоянная база хода,
скорость роста контекста, сохранность кэша, потолок контекста.

| Группа | Мера | Механизм | Замер | Где в репо |
|---|---|---|---|---|
| A. База хода | `permissions.deny` на `Artifact`, `Workflow`, `NotebookEdit`, `ScheduleWakeup` | Схема запрещённого инструмента не попадает в системный промпт; `disabledTools` так не делает | −20 928 токенов в каждом ходу | `settings.json` (блок ниже) |
| A | `skillOverrides` | Листинг скиллов в промпте короче: `name-only` для справочных, `user-invocable-only` для редких, `off` для ненужных | 10 972 → 4 419 знаков, ≈−1 640 токенов на ход | `settings.json` |
| A | Снять впрыск `using-superpowers` со старта | Плагин вешает SessionStart-хук, который вставляет ≈890 токенов в каждый ход; скрипт выключает его в кэше плагина, хук `session-memory.ps1` проверяет при каждом старте, не вернуло ли обновление | −890 токенов на ход, ≈$1.5 в день | `scripts/superpowers-hook-off.js` |
| A | Глобальная инструкция на английском, только правила | 9 289 знаков = 3,4k токенов; объяснения вынесены в `docs/decisions/` | 7,1 % контекста вместе с индексом памяти | `global/CLAUDE.md` |
| A | Индекс памяти на старте | Хук вставляет `MEMORY.md` детерминированно, без хода «загрузи память» | ≈600 токенов, ноль ходов | `hooks/session-memory.ps1` |
| B. Рост контекста | `bashOutputMaxChars: 12000` | Вывод команды больше 12 КБ уходит в файл, модель получает путь и 2 КБ | Закрывает обход `read-gate` через `cat`; обхода после замера нет | `settings.json` |
| B | Отказ на `Read` файла длиннее 350 строк без `offset`/`limit` | PreToolUse-хук возвращает `deny` с оглавлением файла (заголовки и строки) | Доля `Read` в читаемом контексте 49 → 38 %; `Read` с диапазоном 36 → 56 %; средний `Read` 1.77k → 1.30k токенов | `hooks/read-gate.ps1` |
| B | Сводка вместо вывода `dotnet test` | PostToolUse-хук на Bash заменяет зелёный прогон на итог, код возврата сохраняет | −95 % символов | `hooks/test-output-filter.ps1` |
| B | Свой Explore на Haiku | Агент с `model: haiku`, только чтение; общий агент строит свежий префикс на дорогой модели | $0.08 за вызов против $1.24 у `general-purpose` | `agents/explore.md` |
| C. Кэш | `promptCacheTtl: "1h"` | Разрыв между ходами дольше 5 мин на 5m-TTL переписывает весь префикс | Контрфакт 5m: +$77.64 за четыре дня (276 разрывов из 13 002) | `settings.json` |
| C | Пинги по cron в паузе | Первый ход сессии ставит `CronCreate 13,43 * * * *`; хук пропускает пинг, только если он дешевле перезаписи, лимит 6, шестой пишет handoff | Пинг $0.05 против $1.00 за перезапись на 100k Opus; живьём: 5 пингов $0.50 | `hooks/keepalive-gate.ps1`, правило в `global/CLAUDE.md` |
| C | Блок первого хода после паузы больше часа | Кэш истёк; хук один раз останавливает ход и предлагает новую сессию | 8 разрывов >100k за неделю ≈ $12 | `hooks/pause-guard.ps1` |
| C | Страж смены модели посреди сессии | PreModelSwitch-хук блокирует один раз; повтор проходит | Смена на 150k Opus ≈ $1.50 | `hooks/model-switch-guard.ps1` |
| C | Предупреждение о недефолтной модели | На первом промпте (на SessionStart `settings.json` ещё старый) | Ноль токенов, пока модель дефолтная | `hooks/model-notice.ps1` |
| D. Потолок | `autoCompactWindow: 133000` | Порог автосжатия = окно − 33k буфера сводки; 133k даёт порог 100k и на модели с окном 1M | С 09-17 ходов >100k нет; средний контекст 90k → 64k; дневное чтение кэша $237 → $30–58 | `settings.json` |
| D | Красные ступени 150k и каждые 100k дальше | UserPromptSubmit-хук блокирует промпт владельца; `/compact` и `/remember` проходят | Тяжёлых сессий 5 из 63 против 21 из 98 до | `hooks/context-budget.ps1` |
| D | Handoff выжимкой из транскрипта | Скрипт даёт дайджест, сабагент Haiku пишет `.remember/remember.md` | $0.02–0.06 против $1.50 за возврат в контекст | `scripts/handoff-from-transcript.js` |
| E. Модели | Водитель Opus 5 `high`, Fable только соло на решениях | Пара пакетов L: Opus $49.18 против Fable $52.09, разница 5.9 % при пороге 25 % | измерено | `global/CLAUDE.md`, `settings.json` |
| E | Рецензент — Opus 5 явным `model` в `Agent`, исполнители Sonnet 5 по умолчанию | Сабагент читает кэш на 71 % против 97 % у водителя, дорогая модель бьёт по записи; за запрос: Fable $0.252, Opus $0.101, Sonnet $0.029, Haiku $0.007 | −$93 (≈9 %) на пакете $1058 | `global/CLAUDE.md`, `docs/agent-prompts.md`, `env` в `settings.json` |
| E | Замер каждой сессии | Скрипты считают цену по транскриптам; правила калибруются по `docs/costs.md` | Денег не экономит, без него правила не проверить | `scripts/session-cost.js`, `cost-structure.js` |

---

## 2. Установка

### 2.1. Папка и тесты

```
cd C:\Proj\ClaudeOps          # куда положена папка
node --test scripts/*.test.js
powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\read-gate.test.ps1
```

Тесты хуков — восемь файлов `hooks\*.test.ps1`, каждый запускается той же
строкой. Красный тест — стоп и отчёт владельцу, дальше не идти.

### 2.2. Раскладка `~/.claude`

```
.\deploy.ps1          # показывает diff и состояние junction, ничего не пишет
.\deploy.ps1 -Apply   # копирует global\CLAUDE.md и statusline.ps1, создаёт junction
```

Junction: `<HOME>\.claude\hooks`, `scripts`, `agents`, `docs` → папки репо.
Если в `<HOME>\.claude` уже есть такие папки с содержимым — не удалять,
показать владельцу. `global/CLAUDE.md` правится только в репо и деплоится;
деплой переписывает кэш всех открытых сессий, поэтому делается в конце дня.

### 2.3. `settings.json`

Файл `<HOME>\.claude\settings.json` не переносится целиком: там машинный
allowlist. Ключи ниже лежат в `settings.fragment.json`; скрипт вливает их в
существующий файл, ничего из него не удаляя, подставляет `<HOME>` и делает
резервную копию `settings.json.bak-<метка>`:

```
node scripts\merge-settings.js settings.fragment.json --dry-run   # показать результат
node scripts\merge-settings.js settings.fragment.json             # записать
```

Правила слияния: `permissions.deny` объединяется, `allow` не трогается;
`hooks` заменяются по событию, чужие события остаются; `env`,
`modelSettings`, `skillOverrides` сливаются по ключам. Для сверки — тот же
фрагмент целиком:

```json
{
  "model": "claude-opus-5",
  "effortLevel": "high",
  "promptCacheTtl": "1h",
  "autoCompactWindow": 133000,
  "bashOutputMaxChars": 12000,
  "switchModelsOnFlag": false,
  "env": {
    "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"
  },
  "modelSettings": {
    "claude-sonnet-5": { "maxEffortLevel": "medium" },
    "claude-haiku-4-5": { "maxEffortLevel": "medium" }
  },
  "permissions": {
    "deny": ["Artifact", "Workflow", "NotebookEdit", "ScheduleWakeup"]
  },
  "skillOverrides": {
    "claude-api": "name-only",
    "dataviz": "user-invocable-only",
    "design": "user-invocable-only",
    "run": "user-invocable-only",
    "loop": "user-invocable-only",
    "schedule": "user-invocable-only",
    "security-review": "user-invocable-only",
    "init": "user-invocable-only",
    "simplify": "user-invocable-only",
    "fewer-permission-prompts": "user-invocable-only",
    "keybindings-help": "user-invocable-only",
    "artifact-capabilities": "off",
    "artifact-diagramming": "off",
    "workflow-authoring": "off"
  },
  "statusLine": {
    "type": "command",
    "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\statusline.ps1\""
  },
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "timeout": 10,
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\session-memory.ps1\"" } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [
        { "type": "command", "timeout": 10, "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\keepalive-gate.ps1\"" },
        { "type": "command", "timeout": 10, "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\context-budget.ps1\"" },
        { "type": "command", "timeout": 10, "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\pause-guard.ps1\"" },
        { "type": "command", "timeout": 10, "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\model-notice.ps1\"" }
      ] }
    ],
    "PreToolUse": [
      { "matcher": "Read", "hooks": [ { "type": "command", "timeout": 10,
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\read-gate.ps1\"" } ] }
    ],
    "PostToolUse": [
      { "matcher": "AskUserQuestion", "hooks": [ { "type": "command", "timeout": 10,
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\pause-guard.ps1\"" } ] },
      { "matcher": "Bash", "hooks": [ { "type": "command", "timeout": 15,
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\test-output-filter.ps1\"" } ] }
    ],
    "PreModelSwitch": [
      { "hooks": [ { "type": "command", "timeout": 20,
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\model-switch-guard.ps1\"" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "timeout": 15,
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<HOME>\\.claude\\hooks\\commit-reminder.ps1\"" } ] }
    ]
  }
}
```

Пояснения к ключам:

- `model` — дефолт Opus 5; Fable выбирается на сессию до первого сообщения.
- `effortLevel: high` и `switchModelsOnFlag: false` — чтобы клиент не менял
  модель и усилие сам: смена рушит кэш.
- `modelSettings` ограничивает effort исполнителей и Explore до `medium`,
  водителя не трогает.
- Не ставить `CLAUDE_CODE_GOAL_CHECKIN_MINUTES: 0` из исходной машины:
  его эффект не измерен.
- Хук `commit-reminder.ps1` (Stop) денег не экономит, но входит в
  «коммит после каждого куска» и нужен правилам; `log-commands.ps1` в
  репо есть, но никуда не подключён — не подключать.
- `test-output-filter.ps1` заточен под `dotnet test`; на другом стеке хук
  безвреден, но и не работает — правится под свой раннер (тест рядом).

### 2.4. Плагины

Включить в Claude Code: `superpowers`, `context7`, `remember`
(`claude-plugins-official`); `csharp-lsp` — только для .NET-проектов.
Прочие из маркетплейса выключены. Маркетплейсы `alkor-local` и
`alk-axapta` — владельческие, не переносить.

После установки `superpowers` снять его стартовый впрыск:

```
node scripts\superpowers-hook-off.js --check   # показывает состояние
node scripts\superpowers-hook-off.js           # выключает
```

Обновление плагина возвращает впрыск; `session-memory.ps1` предупреждает
об этом на старте сессии, тогда скрипт запускается снова.

### 2.5. Память и шаблоны

- `<HOME>\.claude\memory\MEMORY.md` — индекс, одна строка на файл памяти.
  Создать пустой с заголовком, если нет; хук `session-memory.ps1` вставляет
  его на старте. Содержимое памяти владельца не переносится.
- `templates/CLAUDE.md`, `tech-debt.md`, `results.md` — копируются в новый
  проект руками, не деплоем.

### 2.6. Правила, которые уже в `global/CLAUDE.md`

Деплой переносит их сам; здесь только чтобы знать, что за ними стоит:

- Таблица моделей по ролям и уровни S/M/L (замеры в `docs/costs.md`).
- Первый ход сессии — `CronCreate 13,43 * * * *` с промптом
  `keepalive: ответь точкой`; без `keepalive-gate.ps1` это правило вредно
  (каждый пинг платит), ставить только вместе с хуком.
- Порог контекста — `/compact` в той же сессии, не новая сессия.
- `Read` над 350 строк — `grep -n` и диапазон; обзор — сабагенту.
- Рецензент ≠ автор, у каждого `Agent` в пакете явный `model`.
- `/remember` начинается с `session-cost.js --since <дата>` и строкой в
  `docs/costs.md`.

---

## 3. Проверка после установки

Каждый пункт — команда и ожидаемое; расхождение — отчёт владельцу, не
подгонка.

| Что | Как | Ожидание |
|---|---|---|
| Хуки подключены | `/hooks` в сессии | шесть событий, девять записей, все пути существуют |
| Схемы сняты | `/context` в новой сессии | `Artifact`, `Workflow`, `NotebookEdit`, `ScheduleWakeup` в списке инструментов нет; системный промпт ≈ на 21k токенов меньше, чем без `deny` |
| Листинг скиллов | `node scripts\skill-usage.js --listing` | ≈4.4k знаков при тех же плагинах (`/context` скиллы считает неверно, ему не верить) |
| Впрыск плагина | `node scripts\superpowers-hook-off.js --check` | выключен |
| `read-gate` | в сессии попросить прочитать файл длиннее 350 строк без диапазона | отказ с оглавлением; с `offset`/`limit` проходит |
| Потолок вывода | `Bash` с выводом больше 12 КБ | в контексте путь к файлу и хвост 2 КБ |
| Фильтр тестов | зелёный `dotnet test` через `Bash` | одна строка итога, код возврата 0; красный прогон приходит целиком |
| Пауза | оставить сессию на час и написать | первый промпт заблокирован один раз, повтор проходит |
| Keepalive | `CronCreate 13,43 * * * *` и пауза 30 мин | пинг проходит при контексте ≥60k, при меньшем — блок за ноль токенов |
| Автосжатие | сессия до ≈100k | сжатие срабатывает у 100k, не у 1M; в строке статуса контекст падает до 30–40k |
| Страж модели | `/model` посреди сессии | один блок с объяснением, повтор проходит |
| Структура платы | через неделю `node scripts\cost-structure.js --since <дата>` | чтение кэша ≈45–50 %, вход без кэша <1 %, ходов свыше 100k нет, средний контекст 60–65k |

---

## 4. Что не переносить

Проверено на исходной машине и отклонено; повторять не надо, подробности в
разделе 8 отчёта:

- часовой кэш для сабагентов (+$36 без выигрыша), `disabledTools` вместо
  `permissions.deny` (схемы остаются), `MAX_THINKING_TOKENS`, команды
  агентов (≈7× токенов), инструмент `Workflow` (+6 290 токенов на ход);
- Sonnet-водитель (6 % экономии вместо ожидаемых 35 %), Fable-рецензент
  ($0.252 за запрос при меньшем числе находок), Fable-водитель по умолчанию;
- ключи `model:` и `paths:` во frontmatter скиллов (потолок ≈$0.55 за
  сессию), локальные копии шаблонов `superpowers`;
- `autoCompactWindow` ниже 133k до замера цены хода сжатия; хук
  `PreCompact` (делает платным каждое сжатие);
- чистка allowlist, отключение фонового трафика CLI, роутеры скиллов.

---

## 5. Привязано к владельцу или машине

- `settings.json` целиком, `.credentials.json`, транскрипты, память,
  `.remember/` — не копировать.
- Маркетплейсы `alkor-local` (`c:\Proj\CreateBotAgent`) и `alk-axapta`.
- Список `skillOverrides` собран по замеру `skill-usage.js --cost` на этой
  машине: скиллы, которые владелец ни разу не вызывал за две недели. На
  новой машине через две недели пересобрать той же командой.
- Порог 350 строк в `read-gate.ps1` и потолок 12 КБ откалиброваны на
  .NET-репозиториях и Markdown; для стека с длинными файлами перемерить
  (`docs/decisions/2026-09-18-read-gate-remeasure.md` — как).
- `CronCreate 13,43` — минуты подобраны под пятиминутный шаг хука; при
  другом расписании держать интервал ≤30 мин, иначе кэш 1h истечёт между
  пингами при пропуске.
- Все числа выше — с подписки Max и цен на 2026-09-18 (`scripts/prices.js`);
  пропорции переносятся, доллары — нет.
