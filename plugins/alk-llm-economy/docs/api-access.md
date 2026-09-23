# Claude API: доступ, цены, варианты подключения

Проверено 2026-09-16 по живой документации Anthropic (список источников в
конце). Дополняет [subscription-limits.md](subscription-limits.md), где описаны
лимиты подписки Max, и [costs.md](costs.md), где лежат замеры фактической
стоимости сессий.

Все ссылки в документе проверены `curl` на дату проверки; методика — в разделе
[Проверка ссылок](#проверка-ссылок).

---

## 1. Первая развилка: подписка или API

| | Подписка (Pro/Max) | API-ключ |
|---|---|---|
| Что покупается | доступ к claude.ai, Claude Code, Cowork под своим логином | токены по счётчику |
| Лимиты | окно 5 часов + недельный потолок, без денежного счёта | RPM/ITPM/OTPM + месячный потолок расхода |
| Своя автоматизация | **только для себя**, под своим OAuth | да, любая |
| Продукт для чужих пользователей | **нельзя** | да |
| Расход | фиксированный платёж | плавающий, измеримый до цента |

Ограничение сформулировано в [обзоре Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview):
«Unless previously approved, Anthropic does not allow third party developers to
offer claude.ai login or rate limits for their products, including agents built
on the Claude Agent SDK. Use the API key authentication methods…».

Следствие: личные скрипты и агенты, которые запускает владелец аккаунта, можно
гонять на Max (Claude Code в headless-режиме, Agent SDK под своим логином). Как
только решение обслуживает кого-то ещё, ставится сервисом на сервер или
продаётся — нужен API-ключ. Это условие лицензии, а не техническое ограничение.

---

## 2. Как получить API-ключ

Пошагово, по [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication):

1. Консоль → **Settings → API keys**: <https://platform.claude.com/settings/keys>
2. **Create Key**, в диалоге задаются:
   - **имя** — по назначению, не по человеку (`prod-telbot`, `ci-tests`);
   - **срок жизни** — 3 часа / 1 день / 7 дней / 30 дней / произвольный /
     `Never`. После истечения ключ отдаёт `401`, письма-предупреждения приходят
     заранее;
   - **linked account** — ключ умирает вместе с доступом этого пользователя,
     поэтому для прода берётся сервис-аккаунт;
   - **workspace** — конкретный или без привязки.
3. Значение (`sk-ant-api...`) показывается **один раз** — сразу в секрет-менеджер.

### Типы ключей

| Тип | Привязка | Когда |
|---|---|---|
| Personal key | к пользователю | эксперименты, локальная разработка |
| Service account key | к сервис-аккаунту организации | прод, CI — переживает уход человека |
| Workspace key (legacy) | к воркспейсу | устаревший, заменяется парой «ключ + `anthropic-workspace-id`» |
| Admin key (`sk-ant-admin...`) | к организации | [Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api): ключи, лимиты, отчёты |

**Disable** обратим (ключ переходит в `inactive`), **Delete** — навсегда
(`archived`). Ротация: создать новый → выкатить → disable старый → подождать →
delete.

### Проверка ключа

```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-opus-5","max_tokens":1024,
       "messages":[{"role":"user","content":"Hello, Claude"}]}'
```

Канонический вид — `Authorization: Bearer <key>`; `x-api-key` оставлен для
совместимости. Заголовок `anthropic-version: 2023-06-01` обязателен.

Ключу без привязки к воркспейсу добавляется `anthropic-workspace-id: wrkspc_...`;
для уже привязанного ключа этот заголовок даёт `400`, для несуществующего id —
`404`. Подробности — [Workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces).

### Альтернативы ключу

| Способ | Как работает | Для чего |
|---|---|---|
| [**Workload Identity Federation**](https://platform.claude.com/docs/en/manage-claude/wif-reference) | OIDC-токен (GitHub Actions, GKE, EKS) → `POST /v1/oauth/token` → короткоживущий access token | CI и k8s без долгоживущих секретов |
| **App Attest** | аттестация устройства Apple | iOS/macOS-приложения |
| **OAuth-профили** `ant auth login` | профили в `~/.config/anthropic/`, выбор через `ANTHROPIC_PROFILE` | локальная разработка без экспорта ключа |

Порядок разрешения учётных данных в SDK: `ANTHROPIC_API_KEY` →
`ANTHROPIC_AUTH_TOKEN` → активный OAuth-профиль → переменные WIF → профиль по
умолчанию.

---

## 3. Цены

Источник: [Pricing](https://platform.claude.com/docs/en/about-claude/pricing).
Все суммы в USD за миллион токенов (MTok), первая сторона.

### Токены

| Модель | Вход | Запись кэша 5 мин | Запись кэша 1 час | Чтение кэша | Выход |
|---|---|---|---|---|---|
| Fable 5.1 | $10 | $12.50 | $20 | **$0.25** | $50 |
| Mythos 5.1 (ограниченный доступ) | $10 | $12.50 | $20 | $0.25 | $50 |
| Fable 5 | $10 | $12.50 | $20 | $1 | $50 |
| Opus 5 | $5 | $6.25 | $10 | $0.50 | $25 |
| Opus 4.8 / 4.7 / 4.6 / 4.5 | $5 | $6.25 | $10 | $0.50 | $25 |
| Sonnet 5 | $2 | $2.50 | $4 | $0.20 | $10 |
| Sonnet 4.6 / 4.5 | $3 | $3.75 | $6 | $0.30 | $15 |
| Haiku 4.5 | $1 | $1.25 | $2 | $0.10 | $5 |

Два факта, меняющих арифметику:

- **$2/$10 у Sonnet 5 — постоянная цена.** Подъём до $3/$15, объявленный
  на 1 сентября 2026, отменён.
- **У Fable 5.1 и Mythos 5.1 чтение кэша стоит 0.025× входа** ($0.25/MTok),
  у остальных моделей — 0.1×. Кэшированный Fable 5.1 по входу дешевле
  некэшированного Haiku.

Отдельно: **модели 4.7 и новее используют новый токенизатор, дающий примерно
на 30 % больше токенов на тот же текст.** При сравнении Opus 5 ($5) с
Sonnet 4.6 ($3) разрыв по счёту больше, чем по прайсу.

### Множители и скидки

| Механизм | Эффект |
|---|---|
| [**Batch API**](https://platform.claude.com/docs/en/build-with-claude/batch-processing) | −50 % на вход и выход (Opus 5 — $2.50/$12.50, Sonnet 5 — $1/$5, Haiku 4.5 — $0.50/$2.50) |
| [**Запись кэша**](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) 5 мин | 1.25× входа — окупается с первого попадания |
| **Запись кэша** 1 час | 2× входа — окупается со второго попадания |
| **Чтение кэша** | 0.1× входа (0.025× на Fable 5.1 / Mythos 5.1) |
| [**Длинный контекст**](https://platform.claude.com/docs/en/build-with-claude/context-windows) | **надбавки нет**: весь 1M-контекст по обычной ставке, запрос на 900k стоит столько же за токен, сколько на 9k |
| [**`inference_geo: "us"`**](https://platform.claude.com/docs/en/manage-claude/data-residency) (модели 4.6+) | ×1.1 на всё: вход, выход, записи и чтения кэша |
| [**Fast mode**](https://platform.claude.com/docs/en/build-with-claude/fast-mode) (research preview, Opus 5 / 4.8) | $10/$50 вместо $5/$25, на весь контекст; только первая сторона, с Batch несовместим |
| Региональные эндпоинты Bedrock / Google Cloud | +10 % к глобальным (модели 4.5+) |

Скидки складываются: Batch и кэш комбинируются, множители fast mode и data
residency накладываются поверх кэш-множителей.

### Инструменты и платформенные надбавки

| Что | Цена |
|---|---|
| [Web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool) | **$10 за 1 000 поисков** + токены выдачи |
| [Web fetch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool) | **бесплатно**, только токены загруженного контента |
| [Code execution](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool) | **бесплатно вместе с web search / web fetch**; иначе 1 550 бесплатных часов в месяц на организацию, дальше **$0.05 за час на контейнер**; минимальный интервал 5 минут; при наличии файлов в запросе время тарифицируется, даже если инструмент не вызван |
| [Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview) | токены по обычным ставкам + **$0.08 за час сессии** (считается только статус `running`); Batch-скидка и партнёрские облака не применяются |
| Bash tool | +325 вх. токенов (Opus 5/4.8/4.7), +244 (более ранние) |
| Text editor tool | +700 вх. токенов |
| Computer use (`computer_toolset_20260801`) | ~4 500 вх. токенов на объявление набора |
| Browser use (`browser_toolset_20260801`) | ~6 600 вх. токенов на объявление набора |
| Любой `tools` в запросе | системный промпт тул-юза: Opus 5 — 286 токенов (`auto`/`none`) или 406 (`any`/`tool`), Sonnet 5 — 354 / 474 |

Пример из документации — часовая сессия Managed Agent на Opus 5, 50k вход /
15k выход: $0.25 + $0.375 + $0.08 = **$0.705**. С кэшем (40k входа — попадания):
**$0.525**.

### Подписки, для сравнения

По [claude.com/pricing](https://claude.com/pricing):

| План | Цена |
|---|---|
| Free | $0 |
| Pro | $17/мес при годовой оплате ($200 вперёд), $20/мес помесячно |
| Max 5× | «от $100/мес» |
| Max 20× | страница показывает ту же отметку «от $100/мес»; точная цена 20×-уровня видна при выборе тарифа в биллинге — **цифру со страницы брать нельзя** |
| Team, стандартное место | $20/мес при годовой, $25 помесячно |
| Team, premium-место | $100/мес при годовой, $125 помесячно (5× лимитов стандартного) |
| Enterprise | $20/место/мес при годовой + использование по API-ставкам |

Новым аккаунтам выдаётся небольшой бесплатный кредит. Минимальной суммы
пополнения нет, оплата картой или по счёту, всё в USD, счёт по фактическому
месячному расходу.

---

## 4. Потолки и лимиты

Тир поднимается автоматически по истории платежей
([Rate limits](https://platform.claude.com/docs/en/api/rate-limits)).

| Тир | Месячный потолок расхода |
|---|---|
| Start | $500 |
| Build | $1 000 |
| Scale | $200 000 |
| Custom | без потолка ([через продажи](https://claude.com/contact-sales)) |

Потолок расхода отдаёт `429` с `"details": {"error_code":
"enforced_spend_limit_reached"}` и **без** `retry-after` — ретраи бесполезны,
нужно поднимать лимит в [Settings → Limits](https://platform.claude.com/settings/limits).
Попытка выставить собственный лимит выше тирового — `400 invalid_request_error`.

Лимиты скорости (запросы в минуту / входные токены в минуту / выходные в минуту):

| Модель | Start | Build | Scale |
|---|---|---|---|
| Opus 5 | 1 000 / 2M / 400K | 5 000 / 5M / 1M | 10 000 / 10M / 2M |
| Fable 5.x | 1 000 / 500K / 100K | 2 000 / 1.5M / 300K | 4 000 / 4M / 800K |

Две детали:

- **ITPM учитывает кэш**: `total_input_tokens = cache_read + cache_creation +
  input`. Попадания в кэш дешевле по деньгам, но место в лимите занимают.
- Заголовки ответа `anthropic-ratelimit-*` показывают остаток по каждому ведру —
  бэкофф строится на них. У fast mode свои лимиты и заголовки `anthropic-fast-*`.

Managed Agents: 300 запросов/мин на создание сессий, 1 200 на чтение.
Программный доступ к лимитам и расходу —
[Rate limits API](https://platform.claude.com/docs/en/manage-claude/rate-limits-api)
и [Usage & Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api).

---

## 5. Варианты подключения

### По уровню сложности

| Задача | Поверхность |
|---|---|
| Классификация, извлечение, суммаризация, Q&A | один вызов Messages API |
| Пакетная обработка, не срочно | Batch API (−50 %) |
| Многошаговый пайплайн, логику ведёт свой код | Messages API + [tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) |
| Агент со своими инструментами | Tool Runner |
| Агент на сервере с песочницей и расписанием | Managed Agents |
| Кодовый/файловый агент на своей инфраструктуре | Claude Agent SDK |

### Четыре способа построить агента

Разделяющий вопрос один: кто даёт **harness** (цикл + управление контекстом) и
кто даёт **деплой**.

| # | Способ | Пишется своё | Harness / деплой | Когда |
|---|---|---|---|---|
| 1 | Ручной цикл `while stop_reason == "tool_use"` | весь цикл | своё / своё | нужен полный контроль, без бета-зависимостей |
| 2 | **Tool Runner** (`client.beta.messages.tool_runner`, `@beta_tool` / `betaZodTool`) | только функции-инструменты | SDK / своё | обычный агент со своими инструментами — дефолт |
| 3 | [**Managed Agents**](https://platform.claude.com/docs/en/managed-agents/overview) (REST, beta) | конфиг агента и результаты своих инструментов | Anthropic / Anthropic | долгие сессии, расписания, версионируемые конфиги, песочница с bash и файлами |
| 4 | [**Claude Agent SDK**](https://code.claude.com/docs/en/agent-sdk/overview) | промпт + опции | SDK (Claude Code как библиотека) / своё | готовый кодовый агент: Read/Write/Edit/Bash/Glob/Grep/Web*, MCP, сабагенты, хуки, скиллы из `.claude/` |

Agent SDK есть только для [Python](https://github.com/anthropics/claude-agent-sdk-python)
и [TypeScript](https://github.com/anthropics/claude-agent-sdk-typescript); из
других языков тот же цикл запускается как подпроцесс CLI:
`claude -p … --output-format json` ([headless](https://code.claude.com/docs/en/headless)).
Старт — [Agent SDK quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart).

Клиентские [SDK](https://platform.claude.com/docs/en/api/client-sdks): Python,
TypeScript/JS, Java (и Kotlin, Scala), Go, Ruby, C#, PHP. Tool Runner и Managed
Agents поддержаны во всех.

### Через облачных провайдеров

| Маршрут | Счёт выставляет | Особенности |
|---|---|---|
| Claude API (первая сторона) | Anthropic | полный набор фич и бет, fast mode, глобальная маршрутизация по умолчанию |
| [Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock) | AWS | партнёрские цены, префикс модели `anthropic.`, региональные эндпоинты +10 % |
| [Google Vertex AI](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai) | Google | проект + регион, аутентификация через ADC, свои цены; web fetch недоступен, web search только базовый `web_search_20250305` |
| [Claude Platform on AWS](https://platform.claude.com/docs/en/build-with-claude/claude-platform-on-aws) | AWS Marketplace | **оператор — Anthropic**, паритет фич в день релиза; биллинг в CCU, только постоплата, Start-тир; **Opus 5 не предлагается**, fast mode нет |
| [Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry) | Azure Marketplace | ставки первой стороны, тоже CCU; US Data Zone — множитель ×1.1 |

CCU (Claude Consumption Unit) — единица счёта для маркетплейса: расход считается
в долларах по обычным ставкам, применяется скидка, результат конвертируется в
CCU по $0.01 за штуку и раз в час отправляется в маркетплейс.

Список выведенных из обращения моделей и дат —
[Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations);
характеристики действующих — [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview).

---

## 6. Следствия для ClaudeOps

1. **Max остаётся** для интерактивной работы и личных автоматизаций. Замер
   $8.04 за пакет из [costs.md](costs.md) означает, что Max 5× окупается
   примерно с двенадцатой такой сессии в месяц — пока работа идёт руками,
   подписка выигрывает с запасом.
2. **API-ключ заводится параллельно, не вместо**: он нужен всему, что работает
   без владельца — CI, боты, бэкенды, планировщики. Каналы независимы.
3. Ключ сразу на **сервис-аккаунт** и в отдельный воркспейс со своим лимитом
   расхода: сорвавшийся ночной джоб не съест месячный потолок организации.
4. Первый прод — в **Start**-тире: $500 потолка и 1 000 RPM на Opus 5
   покрывают личный сервис; апгрейд придёт сам.
5. Экономика по убыванию эффекта: кэш системного промпта и контекста (при
   цикличном агенте −70…−90 % входного счёта) → Batch на всём, что терпит
   (−50 %) → маршрутизация по моделям (Haiku 4.5 на разметку, Sonnet 5 на
   массу, Opus 5 на трудное) → web fetch вместо web search, где известен URL.
6. Для CI — **WIF вместо ключа**: короткоживущий токен из OIDC, нечему утекать
   из логов.
7. Оценка токенов до запроса — [token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting);
   факт постфактум — `usage` в ответе и Usage & Cost API.

---

## Проверка ссылок

Все ссылки проверены 2026-09-16 запросом `curl -sS -L -o /dev/null -w
"%{http_code}"`. Для каждого хоста отдельно проверялся заведомо несуществующий
адрес (контроль на ложные 200): `platform.claude.com`, `code.claude.com` и
`support.claude.com` на выдуманном пути отдают `404`, поэтому статус `200`
у них означает существующую страницу. `claude.com` отдаёт `200` на любой путь,
поэтому две ссылки на него (`/pricing`, `/contact-sales`) проверены по
содержимому `<title>`.

Результат: все ссылки документа рабочие. Единственное исключение —
`https://aws.amazon.com/bedrock/pricing/`: хост недоступен из рабочей сети
(`curl` возвращает `000` и на реальный, и на контрольный адрес), ссылка взята
из официальной страницы цен Anthropic и в документ не вынесена.

Устаревшая ссылка, которую можно встретить в старых материалах:
`https://platform.claude.com/docs/en/pricing` — `404`. Актуальный адрес —
`https://platform.claude.com/docs/en/about-claude/pricing`.

## Источники

- [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — цены на модели, кэш, инструменты, Managed Agents, CCU
- [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) — характеристики и даты вывода моделей
- [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations)
- [Rate limits](https://platform.claude.com/docs/en/api/rate-limits) — тиры, потолки расхода, RPM/ITPM/OTPM, заголовки
- [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication) — создание ключей, типы, WIF, App Attest
- [Workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces)
- [Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api)
- [Usage & Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api)
- [Rate limits API](https://platform.claude.com/docs/en/manage-claude/rate-limits-api)
- [WIF reference](https://platform.claude.com/docs/en/manage-claude/wif-reference)
- [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency)
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [Fast mode](https://platform.claude.com/docs/en/build-with-claude/fast-mode)
- [Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [Tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
- [Web fetch tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool)
- [Code execution tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool)
- [Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview)
- [Client SDKs](https://platform.claude.com/docs/en/api/client-sdks)
- [Claude Platform on AWS](https://platform.claude.com/docs/en/build-with-claude/claude-platform-on-aws)
- [Claude in Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock)
- [Claude on Vertex AI](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai) · [цены Google Cloud](https://cloud.google.com/vertex-ai/generative-ai/pricing)
- [Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry)
- [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) · [quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart) · [headless](https://code.claude.com/docs/en/headless)
- [claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python) · [claude-agent-sdk-typescript](https://github.com/anthropics/claude-agent-sdk-typescript)
- [Plans & Pricing](https://claude.com/pricing) · [Contact sales](https://claude.com/contact-sales)
- Консоль: [API keys](https://platform.claude.com/settings/keys) · [Limits](https://platform.claude.com/settings/limits)
- [What is the Max plan?](https://support.claude.com/en/articles/11049741-what-is-the-max-plan) · [Use Claude Code with your Pro or Max plan](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)
