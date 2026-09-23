# PreModelSwitch hook: stops a model switch made in the middle of a live session.
# The rule "model and effort are set before the first message, not switched
# inside the session" lives in CLAUDE.md, but a rule is a hope — pause-guard and
# read-gate showed that only what cannot be rationalised actually holds.
# Why it pays: a switch invalidates the cached prefix, so the very next turn is
# billed as a full rewrite of everything accumulated (docs/costs.md: 150k on
# Opus is about $1.50, and the session keeps paying the higher read price after).
# The hook stays silent until the first assistant turn: choosing the model at
# session start is exactly what the rule asks for and costs nothing.
# Like pause-guard, the block is a single one — a repeat switch to the same
# model goes through, so the owner's deliberate decision is never lost.
# Effort changes do not fire this event; only /model, fast mode and the client.
$ErrorActionPreference = 'SilentlyContinue'

$MinContext = 30000      # below this the rewrite is under $0.30 — not worth a stop
# 1h cache write is 2.0 of the base input price, per million tokens:
# Opus $5, Fable 5.1 twice that, Sonnet $3, Haiku $1 (docs/costs.md).
$PricePerKTok = @{ opus = 0.010; fable = 0.020; sonnet = 0.006; haiku = 0.002 }

$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
$raw = $reader.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }
if ($j.hook_event_name -ne 'PreModelSwitch') { exit 0 }

$to = [string]$j.to_model
$from = [string]$j.from_model
if (-not $to -or $to -eq $from) { exit 0 }

$path = $j.transcript_path
if (-not $path -or -not (Test-Path -LiteralPath $path)) { exit 0 }

# Same walk as pause-guard: the last real assistant turn of the main thread.
# A subagent runs on its own prefix, so its usage says nothing about ours.
$ctx = 0
$lines = @(Get-Content -LiteralPath $path -Tail 300 -Encoding utf8)
[array]::Reverse($lines)
foreach ($line in $lines) {
    if ($line -notmatch '"type":"assistant"' -or $line -notmatch '"usage"') { continue }
    if ($line -match '"isSidechain":true') { continue }
    try { $entry = $line | ConvertFrom-Json } catch { continue }
    $u = $entry.message.usage
    if (-not $u) { continue }
    $ctx = [int]$u.input_tokens + [int]$u.cache_creation_input_tokens + [int]$u.cache_read_input_tokens
    break
}
# No assistant turn yet — the session has nothing cached to lose.
if ($ctx -lt $MinContext) { exit 0 }

$marker = Join-Path $env:TEMP ("claude-model-switch-{0}.flag" -f $j.session_id)
if ((Test-Path -LiteralPath $marker) -and ((Get-Content -LiteralPath $marker -Raw).Trim() -eq $to)) { exit 0 }
Set-Content -LiteralPath $marker -Value $to -Encoding ascii

$family = 'opus'
foreach ($name in 'fable', 'sonnet', 'haiku', 'opus') { if ($to -match $name) { $family = $name; break } }
$k = [int]($ctx / 1000)
$price = [string]::Format([cultureinfo]::InvariantCulture, '{0:0.00}', $ctx / 1000 * $PricePerKTok[$family])
$msg = "Смена модели на $to посреди сессии рушит кэш: контекст ${k}k, следующий ход оплатит перезапись ≈`$$price. По соглашению модель выставляется до первого сообщения. Нужна другая модель — дешевле закрыть сессию (/remember) и начать новую на ней. Решение осознанное — переключи ещё раз, второй раз пройдёт."

# stdout of a PreModelSwitch hook is not the channel for a refusal; exit 2 blocks
# the switch and the reason goes to stderr. Written as raw UTF-8 bytes past the
# console codepage (CP866 here), which would otherwise mangle the Cyrillic.
$bytes = (New-Object System.Text.UTF8Encoding $false).GetBytes($msg + "`n")
$err = [Console]::OpenStandardError()
$err.Write($bytes, 0, $bytes.Length)
$err.Flush()
exit 2
