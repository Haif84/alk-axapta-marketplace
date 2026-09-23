# Cursor preToolUse (matcher Read): тот же read-gate, что у Claude (hooks/read-gate.ps1),
# через перевод формата. Логика порога и оглавления живёт в одном месте — здесь
# только вход Cursor -> вход Claude и отказ Claude -> отказ Cursor.
# Имена полей инструмента Read в Cursor документация не фиксирует, поэтому путь и
# диапазон берутся из нескольких вариантов имён; неизвестный вход — молча пропустить.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot '..\hooks\lib\ascii-json.ps1')

$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
try { $j = $reader.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
if ($j.tool_name -ne 'Read') { exit 0 }
$in = $j.tool_input

function First($o, [string[]]$names) {
    foreach ($n in $names) { if ($null -ne $o.$n -and "$($o.$n)" -ne '') { return $o.$n } }
    return $null
}
$path   = First $in 'file_path', 'target_file', 'path'
if (-not $path) { exit 0 }
# Относительный путь — от первого корня рабочей области.
if (-not [IO.Path]::IsPathRooted($path) -and $j.workspace_roots) { $path = Join-Path @($j.workspace_roots)[0] $path }
$offset = First $in 'offset', 'start_line', 'start_line_one_indexed'
$limit  = First $in 'limit'
$endAt  = First $in 'end_line', 'end_line_one_indexed_inclusive'
if (-not $limit -and $endAt) { $limit = [int]$endAt - $(if ($offset) { [int]$offset } else { 1 }) + 1 }

$claudeIn = @{ file_path = "$path" }
if ($offset) { $claudeIn.offset = [int]$offset }
if ($limit)  { $claudeIn.limit  = [int]$limit }
$payload = ConvertTo-AsciiJson @{ hook_event_name = 'PreToolUse'; tool_name = 'Read'; tool_input = $claudeIn }

$gate = Join-Path $PSScriptRoot '..\hooks\read-gate.ps1'
$out = $payload | powershell.exe -NoProfile -ExecutionPolicy Bypass -File $gate
if (-not $out) { exit 0 }
try { $r = ($out -join "`n") | ConvertFrom-Json } catch { exit 0 }
$reason = $r.hookSpecificOutput.permissionDecisionReason
if ($r.hookSpecificOutput.permissionDecision -ne 'deny' -or -not $reason) { exit 0 }
ConvertTo-AsciiJson @{ permission = 'deny'; agent_message = $reason; user_message = 'read-gate: длинный файл без диапазона, агенту выдано оглавление' }
exit 0
