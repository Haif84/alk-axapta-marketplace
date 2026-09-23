# Тесты cursor/read-gate.ps1: событие preToolUse Cursor на stdin, файл на диске,
# ответ Cursor на stdout. Порог и оглавление проверяет hooks\read-gate.test.ps1,
# здесь — только перевод формата в обе стороны.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File cursor\read-gate.test.ps1
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$hook = Join-Path $PSScriptRoot 'read-gate.ps1'
$tmp = Join-Path $env:TEMP ('cursor-read-gate-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $tmp 'папка') -Force | Out-Null
$failed = 0

# 600 строк по ≈60 байт: больше порога 350 строк и больше 16 КБ.
$long = Join-Path $tmp 'папка\long.js'
1..600 | ForEach-Object { if ($_ % 50 -eq 0) { "function fn$_ () {" } else { "  line $_ " + ('x' * 50) } } |
    Out-File -LiteralPath $long -Encoding utf8

function Invoke-Hook {
    param([hashtable]$ToolInput, [string]$ToolName = 'Read')
    $event = @{
        hook_event_name = 'preToolUse'
        conversation_id = [guid]::NewGuid().ToString('N')
        workspace_roots = @($tmp)
        tool_name       = $ToolName
        tool_input      = $ToolInput
    } | ConvertTo-Json -Compress -Depth 9
    $out = $event | & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hook
    return [pscustomobject]@{ Raw = ($out -join ''); Code = $LASTEXITCODE }
}

function Check([string]$Name, [bool]$Ok) {
    if ($Ok) { Write-Host "ok   $Name" } else { Write-Host "FAIL $Name"; $script:failed++ }
}

$r = Invoke-Hook @{ file_path = $long }
$j = $r.Raw | ConvertFrom-Json
Check 'длинный файл без диапазона: deny' ($j.permission -eq 'deny')
Check 'агенту уходит оглавление' ($j.agent_message -match 'fn300')
Check 'пользователю — короткая строка' ($j.user_message -match 'read-gate')
Check 'код возврата 0' ($r.Code -eq 0)

$r = Invoke-Hook @{ target_file = $long }
Check 'путь в target_file: deny' (($r.Raw | ConvertFrom-Json).permission -eq 'deny')

$r = Invoke-Hook @{ path = 'папка\long.js' }
Check 'относительный путь от корня рабочей области: deny' (($r.Raw | ConvertFrom-Json).permission -eq 'deny')

$r = Invoke-Hook @{ file_path = $long; offset = 100; limit = 200 }
Check 'offset/limit в пределах порога: молча' ($r.Raw -eq '')

$r = Invoke-Hook @{ target_file = $long; start_line_one_indexed = 100; end_line_one_indexed_inclusive = 300 }
Check 'start/end в пределах порога: молча' ($r.Raw -eq '')

$r = Invoke-Hook @{ file_path = $long; offset = 1; limit = 500 }
Check 'limit выше порога: deny' (($r.Raw | ConvertFrom-Json).permission -eq 'deny')

$r = Invoke-Hook @{ command = 'cat x' } -ToolName 'Shell'
Check 'не Read: молча' ($r.Raw -eq '')

$r = Invoke-Hook @{ file_path = (Join-Path $tmp 'нет.txt') }
Check 'нет файла: молча' ($r.Raw -eq '')

Remove-Item -LiteralPath $tmp -Recurse -Force
if ($failed) { Write-Host "$failed FAILED"; exit 1 }
Write-Host 'all passed'
exit 0
