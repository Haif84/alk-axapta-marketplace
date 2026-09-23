# UserPromptSubmit hook: watches the context size. One threshold, one addressee.
# At 150k it blocks the prompt, by the pause-guard pattern: the price of ten
# more turns here against a compacted context, the turn never reaches the model,
# and resending the same message passes. A warning would be paid for at the very
# rate it warns about, and "keep going" would stay the default answer; a block
# makes the owner decide once.
# The 100k notice this hook used to print is gone (2026-09-17). It spoke to the
# agent, not the owner, so it cost a turn on the full context just to raise an
# AskUserQuestion — and autocompact fires at ~100k of context itself
# (autoCompactWindow 133k minus the 30k output buffer), so the notice landed on
# top of a compaction that was already happening. 100k stays the budget: it is
# the step of the ladder above, not a trigger.
# The way out is /compact, not a new session (docs/decisions/2026-09-15-compact-at-threshold.md):
# the summary is written by the model that saw everything, the session, model
# and effort stay, and the transcript stays on disk in the same .jsonl.
# The model cannot see its own context size, so the hook reads the usage of
# the last assistant message from the transcript: context of the last request
# = input + cache_creation + cache_read tokens. Thresholds are absolute tokens,
# not a share of the window (docs/costs.md, "Порог бюджета контекста").
# Fires once per session per threshold; stdout goes into the model's context.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')
. (Join-Path $PSScriptRoot 'lib\system-prompt.ps1')
$raw = [Console]::In.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }
# Системный промпт владелец не набирал и повторить не может: блокировка его
# теряет. Ворота стоят до флага порога, иначе уведомление израсходует флаг.
if (Test-SystemPrompt $j.prompt) { exit 0 }
# Сжатие и сохранение состояния — те самые выходы, которые советует красный
# порог: блокировать их значит требовать двух отправок ради собственного
# совета. Рядом с воротами системного промпта и по той же причине — чтобы флаг
# порога остался владельцу. Прочие команды плагина (/remember:doctor)
# исключением не являются.
if ($j.prompt -match '^\s*/(remember(:remember)?|compact)(\s|$)') { exit 0 }
$path = $j.transcript_path
if (-not $path -or -not (Test-Path -LiteralPath $path)) { exit 0 }

$ctx = 0
$lines = @(Get-Content -LiteralPath $path -Tail 300 -Encoding utf8)
[array]::Reverse($lines)
foreach ($line in $lines) {
    if ($line -notmatch '"type":"assistant"' -or $line -notmatch '"usage"') { continue }
    try { $u = ($line | ConvertFrom-Json).message.usage } catch { continue }
    if (-not $u) { continue }
    $ctx = [int]$u.input_tokens + [int]$u.cache_creation_input_tokens + [int]$u.cache_read_input_tokens
    break
}
$BudgetTokens = 100000   # бюджет из global/CLAUDE.md: шаг ступеней, не порог срабатывания
$BlockTokens = 150000
# Единственное падение контекста внутри сессии — сжатие. Флаги порогов к нему
# уже израсходованы, и без сброса второй набор до 150k прошёл бы молча.
if ($ctx -lt $BlockTokens) {
    Get-ChildItem -Path $env:TEMP -Filter ("claude-context-budget-{0}-*.flag" -f $j.session_id) -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    exit 0
}

# Ступень, а не один флаг на сессию: порог повторяется каждый следующий бюджет
# сверх него — 150k, 250k, 350k. Одна блокировка отпускала контекст сколь угодно
# далеко: после «продолжаем здесь» на 150k сессия 2026-09-15 доехала до 345k,
# где ход стоит вчетверо дороже названного, и второго сигнала владелец уже не
# получал.
$level = $BlockTokens + [math]::Floor(($ctx - $BlockTokens) / $BudgetTokens) * $BudgetTokens
$marker = Join-Path $env:TEMP ("claude-context-budget-{0}-{1}.flag" -f $j.session_id, $level)
if (Test-Path $marker) { exit 0 }
New-Item -ItemType File -Path $marker -Force | Out-Null

$k = [int]($ctx / 1000)
# Порог адресован владельцу, а не модели: ход останавливается до запроса,
# поэтому текст модель не увидит и указаний ей не содержит.
$CacheReadPerKTok = 0.0005   # Opus 5: $0.50 за 1M токенов чтения кэша (scripts/prices.js)
$BaseContext = 40000         # контекст после сжатия ≈ старт новой сессии (docs/costs.md)
$here  = [string]::Format([cultureinfo]::InvariantCulture, '{0:0.00}', $ctx * 10 * $CacheReadPerKTok / 1000)
$fresh = [string]::Format([cultureinfo]::InvariantCulture, '{0:0.00}', $BaseContext * 10 * $CacheReadPerKTok / 1000)
# Доля бюджета считается, а не названа словом: «полтора» верно только на
# первой ступени, а текст тот же и на 250k, и на 350k.
$budgets = [string]::Format([cultureinfo]::InvariantCulture, '{0:0.0}', $ctx / $BudgetTokens)
$budget = [int]($BudgetTokens / 1000)
$msg = "Контекст ${k}k — $budgets бюджета по ${budget}k. Десять ходов отсюда ≈`$$here только за чтение кэша против ≈`$$fresh после сжатия, и дальше дороже с каждым ходом. Ход к модели не ушёл. Продолжить здесь — отправь сообщение ещё раз; дешевле сжать: /compact блокировкой не задерживается, сводку пишет эта же модель, транскрипт остаётся в .jsonl (выжимка — handoff-from-transcript.js). Закрыть сессию — /remember, тоже без блокировки."
ConvertTo-AsciiJson @{ decision = 'block'; reason = $msg }
exit 0
