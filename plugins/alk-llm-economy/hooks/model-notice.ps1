# UserPromptSubmit hook: one line about a non-default model or effort, once per
# session. The team default is Sonnet 5 medium (claude/settings.fragment.json;
# medium because modelSettings caps Sonnet there), but /model and /effort write the last
# session's choice into settings.json, so a session after Fable or after a
# lowered effort silently starts on it and the owner pays another rate.
# Why not SessionStart, where this check used to live: settings.json is the only
# source (neither payload carries the model, and CLAUDE_EFFORT is set only for
# hooks inside a tool-use context), and at session start that file still holds
# the previous session's value — the harness writes the new one a beat later,
# after the hook has read it. Twice on 2026-09-16 the line named a model the
# session was not running, and each false alarm costs the owner a turn. By the
# first prompt the file is already rewritten, so the same read tells the truth.
# The live values are also in the statusline (global/statusline.ps1); this line
# exists because the owner reads the agent's text and not always the statusline.
# A --model flag on the command line still goes unnoticed — a known gap, not
# worth its own mechanism.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')
$raw = [Console]::In.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }

# Один раз за сессию: дальше строка уже в контексте, повтор — платный шум.
$marker = Join-Path $env:TEMP ("claude-model-notice-{0}.flag" -f $j.session_id)
if (Test-Path -LiteralPath $marker) { exit 0 }

$settingsPath = Join-Path $env:USERPROFILE '.claude\settings.json'
if (-not (Test-Path -LiteralPath $settingsPath)) { exit 0 }
$s = $null
try { $s = Get-Content -LiteralPath $settingsPath -Raw -Encoding utf8 | ConvertFrom-Json } catch { $s = $null }
if (-not $s) { exit 0 }

$model = [string]$s.model
$effort = [string]$s.effortLevel
$bare = ($model -replace '\[1m\]$', '').Trim().ToLowerInvariant()
# Ключа нет — сессия идёт на дефолте самого Claude Code, а это не Sonnet.
$isDefaultModel = ($bare -match '^(claude-)?sonnet(-5)?$')
$isDefaultEffort = ($effort -eq 'medium')
if ($isDefaultModel -and $isDefaultEffort) { exit 0 }

# Цены вход/выход за 1M — scripts/prices.js.
$defaultPrice = '$2/$10'
$price = '$5/$25'
if ($bare -eq '') { $price = '' }
elseif ($bare -match 'fable|mythos') { $price = '$10/$50' }
elseif ($bare -match 'opus-5-5') { $price = '$4/$20' }
elseif ($bare -match 'sonnet-4-6') { $price = '$3/$15' }
elseif ($bare -match 'sonnet') { $price = '$2/$10' }
elseif ($bare -match 'haiku') { $price = '$1/$5' }
$shownModel = if ($model) { $model } else { '(не задан)' }
$shownEffort = if ($effort) { $effort } else { '(не задан)' }
$line = "=== МОДЕЛЬ СЕССИИ ===`nsettings.json: model=$shownModel, effort=$shownEffort — не дефолт команды (Sonnet 5 medium)."
if (-not $price) {
    $line += " Без ключа model сессия идёт на модели Claude Code по умолчанию; дефолт команды ставит /alk-llm-economy:economy-setup."
} elseif ($price -eq $defaultPrice) {
    $line += " Цена за токен та же ($price за 1M), отличается глубина думанья."
} else {
    $line += " Цена $price за 1M токенов против $defaultPrice у Sonnet 5."
}
$line += " Модель и effort меняются до первого сообщения: внутри сессии переключение сбрасывает кэш. Если это не намеренно, скажи владельцу до начала работы."

New-Item -ItemType File -Path $marker -Force | Out-Null
ConvertTo-AsciiJson @{ hookSpecificOutput = @{ hookEventName = 'UserPromptSubmit'; additionalContext = $line } }
exit 0
