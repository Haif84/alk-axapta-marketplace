# Разведка мер экономии 2026-09-14: документация Anthropic и практика

Продолжение `cost-audit-2026-09-14.md`. Повод: вопрос владельца «что ещё можно
сделать для снижения стоимости разработки, по документации Anthropic и
интернету». Источники: страницы `code.claude.com/docs` (costs, prompt-caching,
context-window, sub-agents, settings-reference, env-vars, model-config, skills,
statusline, monitoring-usage), issues `anthropics/claude-code`, замеры из блогов
и один опыт в этой сессии. Claude Code 2.1.269. Что уже есть и работает —
таблица в аудите, здесь не повторяется.

## Проверено в этой сессии

1. **Встроенный Explore игнорирует `CLAUDE_CODE_SUBAGENT_MODEL`.** Переменная
   в окружении сессии равна `sonnet`, сессия на Fable 5.1, тривиальный Explore
   без параметра модели отработал на `claude-opus-5` (транскрипт
   `subagents/agent-ad3084c1ba0324a3f.jsonl` этой сессии). Три Explore в Batch
   12-го тоже шли на Opus 5, но это было до ввода переменной. С 2.1.198 Explore
   берёт модель сессии с потолком Opus вместо Haiku. Базовый контекст у него
   малый — 15.8k токенов записи кэша, CLAUDE.md не грузит — но по тарифу Opus.
   Правило «разведка → Explore» считает его дешёвым; это неверно.
2. **Отложенная загрузка схем инструментов уже включена.** В этой сессии
   список отложенных инструментов (Cron*, LSP, WebFetch, MCP context7 и т. д.)
   виден в системном напоминании; `ENABLE_TOOL_SEARCH` не задан, значит
   работает дефолт. Делать ничего не надо.
3. **`settings.json` держит `model: claude-fable-5-1[1m]`** после `/model`
   в этой сессии; хук `session-memory.ps1` предупреждает только на старте.
   Дефолт `opus[1m]` вернуть в конце сессии.

## Меры к внедрению

Порядок — по ожидаемому эффекту на наш профиль (55 % чтение кэша, 18 % вывод,
19 % запись 1h, 8 % запись 5m, база 57k). Все уровня S, кроме 4 (замер).

### 1. Свой Explore на Haiku

Файл `~/.claude/agents/explore.md` (в репозитории — `agents/`, junction или
`deploy.ps1`): `model: haiku`, `tools: Read, Grep, Glob, Bash`, промпт как у
встроенного (только чтение, выдержки, не обзор целиком). Allowlist `tools:`
сжимает набор схем в системном промпте агента. Правило в `global/CLAUDE.md`
«Разведка и справки → `low`/`medium` или Explore» переписать на этого агента.
Эффект: разведка по тарифу Haiku ($1/$5) вместо Opus ($5/$25) при том же
базовом контексте. Проверка: `meta.json` сабагента и `"model"` в транскрипте.

### 2. Настройки против скрытых ходов и промахов кэша

Один коммит `settings.json` (машинный, не в репозитории) + строки в
`docs/plugins.md`:

- `hooks.PreModelSwitch` — хук, который блокирует смену модели внутри
  сессии или требует подтверждения. Механизация правила «модель и effort
  выставляются до первого сообщения». Хук в `hooks/`, тест рядом.
- `promptCacheTtl: "1h"` явно. На подписке в пределах плана TTL основной
  беседы и так час, но при переходе на usage credits (наш сценарий «упёрлись
  в 50 % Fable») Claude Code молча роняет его до 5 минут. Страховка без
  цены. Проверка: `claude -p "hello" --output-format json` →
  `usage.cache_creation.ephemeral_1h_input_tokens`.
- `env.CLAUDE_CODE_GOAL_CHECKIN_MINUTES = "0"` — сессия с активной целью на
  простое делает до трёх ходов с полным контекстом.
- `crossSessionInbound: "hold"` — сообщение от соседней сессии иначе
  доставляется отдельным ходом с полным контекстом. Прямо касается техдолга 13
  (две сессии в одном дереве).
- `maxEffortLevel` по моделям — потолок effort исполнителей, чтобы Sonnet не
  уходил выше `medium` без явного решения.
- `switchModelsOnFlag: false` — запрет авто-переключения модели по
  safety-классификатору: такое переключение рушит префикс кэша. Сначала
  проверить в `settings-reference`, что ключ есть в 2.1.269.

### 3. Фильтр вывода тестов через PostToolUse

Хук `PostToolUse` с `matcher: Bash` возвращает
`hookSpecificOutput.updatedToolOutput`: для `dotnet test` оставляет строки
`Failed`, стек первого падения и итоговую строку `Passed!/Failed!`. Пример
из документации: `npm test` с десятков тысяч токенов до сотен. У нас сейчас
только `bashOutputMaxChars: 12000`, а хвост вывода Bash — заметная статья
чтений (замер аудита). Мерить: `context-composition.js`, доля хвоста Bash до
и после недели. С 2.1.133 хук получает уровень effort сессии — можно резать
сильнее на `low`.

### 4. Листинг скиллов: замер, потом `skillOverrides`

`/skill-doctor` (2.1.252+) даёт цену листинга каждого скилла, токены и
вызовы за 7 дней, невызываемые скиллы и неиспользуемые плагины. Затем
`skillOverrides` в `settings.local.json` проекта (`off`, `name-only`,
`user-invocable-only`), `skillListingMaxDescChars`, для неиспользуемых
`disableBundledSkills`. Наш замер: листинг скиллов 5.7M токенов за неделю,
7.2 % (`context-composition.js`). Оговорка: в `/context` есть баг учёта —
при скрытии скиллов сумма не меняется, токены переезжают в строку «System
tools» (issue 94174, не исправлен на 2.1.270). Поэтому эффект мерить по
`cache_creation_input_tokens` первого хода сессии, не по `/context`.

### 5. `/rewind` со сводкой вместо `/compact`

При отказе от тупикового пути `/rewind` → «Summarize up to here» читает уже
закэшированный префикс, `/compact` строит новый. Строка в правила экономии
контекста, кода нет.

## Что подтверждает наши правила числами

- Холодный старт сабагента без работы — около 54k токенов записи кэша
  (совпадает с нашей базой 57k): сабагент грузит все уровни CLAUDE.md,
  скиллы, git-снимок; Explore и Plan CLAUDE.md пропускают. Порог выгоды
  делегирования: 30–50k токенов чтения на той же модели, около 10k на
  дешёвой. Наше «сабагенты только при ≥2 независимых кусках» этому
  соответствует; числа можно добавить в правило.
- Веер сабагентов не выигрывает по времени (4:15 последовательно против 8:00
  у двух параллельных) и стоит в 2.6–5.9 раза дороже по токенам; Claude Code
  сам придерживает веер до 5 с, чтобы агенты делили первый префикс.
- Кэш привязан к машине, каталогу и git-снимку старта: worktree не делит кэш
  с основным деревом, параллельные сессии в одном каталоге делят. Правило
  «ветка в том же дереве» верное; для техдолга 13 это значит, что вторая
  сессия в дереве дешевле, чем в worktree, но опаснее по состоянию.
- Не рушат кэш: правка CLAUDE.md посреди сессии (и не применяется до
  `/clear`/`/compact`/рестарта), смена permission mode, вызов скиллов и
  команд, `/rewind`, спавн сабагента, plan mode (инструкции идут в беседу).
  Рушат: `/model`, смена effort (кроме Fable 5.1 с 2.1.260), fast mode,
  подключение MCP-сервера с незаложенными схемами, включение плагина с
  MCP-сервером, deny-правило на целый инструмент, `/compact`, обновление
  Claude Code, `opusplan` при каждом входе в plan mode.
- Вывод хуков SessionStart и UserPromptSubmit лежит в слое беседы, не в
  системном префиксе: правка хука кэш не рушит, но его вывод оплачивается
  чтением на каждом ходу. Метка времени в UserPromptSubmit безвредна.
- Сабагент `fork` (`context: fork`, `/subtask`) наследует префикс родителя и
  читает его кэш — дешёвый старт, когда нужен текущий контекст.
- `bashOutputMaxChars` (наши 12k) с 2.1.261 перебивает `BASH_MAX_OUTPUT_LENGTH`;
  сверх лимита вывод уходит в файл сессии.

## Что не брать и почему

- **`subagentPromptCacheTtl: 1h`.** Агент по документации назвал это главным
  рычагом («закрывает 8 % записи 5m»). Нет: часовая запись стоит 2.0 от
  базовой цены против 1.25 у пятиминутной, а сабагент, чьи ходы идут внутри
  пяти минут, ничего не выигрывает. Посчитано 09-13, закрыто в аудите.
  Исключение — сабагент с одиночным вызовом дольше 5 минут (долгий прогон
  тестов); таких у нас нет.
- **`MAX_THINKING_TOKENS`.** Адаптивные модели (Opus 5, Fable 5.1) ненулевое
  значение игнорируют; рычаг — effort, он уже в правилах уровней.
- **Ранний автокомпакт** (`autoCompactWindow`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`).
  Компакт читает всю беседу и строит новый префикс; наша связка «хук
  бюджета → новая сессия + handoff Haiku за $0.02» дешевле.
- **`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`** — меньше $0.04 за сессию и
  отключает серверные feature-настройки.
- **Agent teams** — около 7× токенов обычной сессии; выключены по умолчанию,
  так и оставить.
- **`CLAUDE_CODE_MAX_OUTPUT_TOKENS`** — в текущем `env-vars` не найден, по
  issues на части моделей игнорируется. Потолок вывода через effort.
- **Message Batches, серверный compaction, memory tool** — surface Messages
  API, к Claude Code не относятся.
- **Прокси сжатия вывода команд** (RTK, token-saver, tamp: 60–90 % на
  `cargo test`/`npm test`) — тот же эффект даёт мера 3 своим хуком, без
  стороннего процесса между Claude Code и оболочкой.
- **`disabledTools`** в `settings.json` блокирует выполнение, но схемы
  остаются в контексте (issue 30480) — на базу не влияет.

## Что измеримо штатно, к сведению

- `/usage`: блок сессии, `Prompt cache (main)` (2.1.251+) — доля входа из
  кэша, промахи с объёмом переписи, с 2.1.260 вероятная причина промаха;
  разрез плана по скиллам, сабагентам, плагинам, MCP-серверам, строки по
  `/loop`.
- `/context`: разбивка живого контекста (с оговоркой про баг учёта скиллов).
- Statusline JSON: `prompt_cache.{warm,hit_ratio,misses,cache_write_tokens,
  miss_recache_tokens,expires_at}`, `context_window.current_usage.*` — без
  затрат токенов; можно вывести тепло кэша и TTL в `statusline.ps1`.
- OTEL: `claude_code.token.usage` по типам, `claude_code.api_request` с
  `cost_usd_micros` — точнее разбора JSONL, если понадобится.
- `--max-budget-usd` — жёсткий потолок на запуск `claude -p`.
- `/insights` тратит токены плана; наш `analyze-sessions.mjs` бесплатен.

## Учёт на Max

- Лимиты метрятся окном использования, не долларами: скользящие 5 часов
  плюс неделя, общий пул с claude.ai; на Max у Sonnet и Opus раздельные
  корзины, недельных лимитов два — общий и модельный. «Session/weekly limit»
  общий, `/model` не помогает; «Opus limit» модельный, помогает.
- Usage credits: сверх плана оплата по токенам, и тогда TTL основной беседы
  падает до 5m без `promptCacheTtl: 1h` (мера 2).
- `autoContinueAtUsageLimit` / `/rate-limit-options` (2.1.234+) — дождаться
  сброса и продолжить прерванную задачу.

## Справочник настроек из отчёта

| Ключ | Где | Что делает |
|---|---|---|
| `promptCacheTtl`, `CLAUDE_CODE_PROMPT_CACHE_TTL` | settings / env | TTL основной беседы, `5m`/`1h` (2.1.242+) |
| `subagentPromptCacheTtl` | settings | TTL сабагентов, компакта, форков; по умолчанию 5m |
| `ENABLE_TOOL_SEARCH` | env | `auto`, `auto:N`, `true`, `false`; дефолт — отложенная загрузка |
| `MAX_MCP_OUTPUT_TOKENS` | env | потолок результата MCP-инструмента, 25k |
| `skillOverrides`, `skillListingMaxDescChars`, `skillListingBudgetFraction`, `disableBundledSkills` | settings | листинг скиллов |
| `maxEffortLevel`, `effortLevel`, `CLAUDE_CODE_EFFORT_LEVEL` | settings / env | effort и его потолок |
| `CLAUDE_CODE_GOAL_CHECKIN_MINUTES`, `crossSessionInbound` | env / settings | скрытые ходы на простое |
| `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` | env | переменная модели перебивает даже параметр вызова |
| `PreModelSwitch` | hooks | контроль смены модели |
| `experimental.cacheTtl: 1h`, `maxTurns`, `tools`, `disallowedTools`, `model`, `effort` | фронтматтер агента | экономика сабагента |
| `switchModelsOnFlag` | settings | авто-fallback модели по классификатору |

## Источники

- https://code.claude.com/docs/en/costs
- https://code.claude.com/docs/en/prompt-caching
- https://code.claude.com/docs/en/context-window
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/settings-reference
- https://code.claude.com/docs/en/env-vars
- https://code.claude.com/docs/en/model-config
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/statusline
- https://code.claude.com/docs/en/monitoring-usage
- https://code.claude.com/docs/en/agent-sdk/tool-search
- https://code.claude.com/docs/en/hooks
- https://github.com/anthropics/claude-code/issues/94174 (учёт скиллов в `/context`)
- https://github.com/anthropics/claude-code/issues/30480 (`disabledTools` не убирает схемы)
- https://github.com/anthropics/claude-code/issues/54716 (база 41k, отложенные встроенные инструменты 20k)
- https://dev.to/rulestack/what-a-claude-code-subagent-actually-costs-measuring-the-436k-token-fixed-overhead-46g6 (54k холодный старт, порог выгоды)
- https://systima.ai/blog/subagent-tax (веер сабагентов)
- https://youcanbuildthings.substack.com/p/why-claude-code-subagents-burn-so (Explore на модели сессии с 2.1.198)
- https://claudecodeguide.dev/blog/plan-mode-saves-tokens
- https://medium.com/@automation.labs/an-effort-aware-hook-for-claude-code-stop-wasting-tokens-78c81e7db054
