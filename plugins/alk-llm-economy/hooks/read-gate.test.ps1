# Fixture tests for read-gate.ps1. Runs the hook as Claude Code runs it:
# a PreToolUse event for Read on stdin, a file on disk, JSON on stdout.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\read-gate.test.ps1
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$hook = Join-Path $PSScriptRoot 'read-gate.ps1'
$tmp = Join-Path $env:TEMP ('read-gate-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$failed = 0

# Файл на N строк; каждая строка ≈60 байт, чтобы 350 строк давали больше 16 КБ
# и проверка размера не отсекала их до подсчёта строк.
function New-File {
    param([int]$Lines, [string]$Ext = '.cs')
    $path = Join-Path $tmp ([guid]::NewGuid().ToString('N') + $Ext)
    $body = 1..$Lines | ForEach-Object { "line $_ " + ('x' * 50) }
    $body | Out-File -LiteralPath $path -Encoding utf8
    return $path
}

# Файл того же размера, но с объявлениями: каждая $Every-я строка — функция.
function New-CodeFile {
    param([int]$Lines, [int]$Every = 50, [string]$Ext = '.js')
    $path = Join-Path $tmp ([guid]::NewGuid().ToString('N') + $Ext)
    $body = 1..$Lines | ForEach-Object {
        if ($_ % $Every -eq 0) { "function fn$_ () {" } else { "  line $_ " + ('x' * 50) }
    }
    $body | Out-File -LiteralPath $path -Encoding utf8
    return $path
}

function Invoke-Hook {
    param([string]$File, [hashtable]$Extra = @{}, [string]$ToolName = 'Read')
    $input_ = @{ file_path = $File } + $Extra
    $event = @{
        hook_event_name = 'PreToolUse'
        session_id      = [guid]::NewGuid().ToString('N')
        transcript_path = (Join-Path $tmp 'none.jsonl')
        cwd             = 'C:\Proj\ClaudeOps'
        tool_name       = $ToolName
        tool_input      = $input_
    } | ConvertTo-Json -Compress -Depth 9
    $out = $event | & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hook
    return [pscustomobject]@{ Raw = ($out -join ''); Code = $LASTEXITCODE }
}

function Test-Case {
    param([string]$Name, [scriptblock]$Body)
    try {
        & $Body
        Write-Host "PASS  $Name"
    } catch {
        $script:failed++
        Write-Host "FAIL  $Name`n      $($_.Exception.Message)"
    }
}

function Assert-True { param([bool]$Cond, [string]$Msg) if (-not $Cond) { throw $Msg } }
function Assert-Silent { param($r) Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"; Assert-True ($r.Code -eq 0) "код возврата $($r.Code)" }
function Assert-Deny {
    param($r)
    Assert-True ($r.Raw -ne '') 'ожидался отказ, хук промолчал'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.hookSpecificOutput.hookEventName -eq 'PreToolUse') "hookEventName: $($r.Raw)"
    Assert-True ($j.hookSpecificOutput.permissionDecision -eq 'deny') "permissionDecision: $($r.Raw)"
    Assert-True ($r.Raw -notmatch '[^\x00-\x7F]') 'вывод должен быть чистым ASCII (кириллица через \uXXXX)'
    return $j.hookSpecificOutput.permissionDecisionReason
}

Test-Case 'файл на 100 строк — проходит' {
    Assert-Silent (Invoke-Hook (New-File 100))
}

Test-Case 'файл ровно на пороге 350 строк — проходит' {
    Assert-Silent (Invoke-Hook (New-File 350))
}

Test-Case 'файл на 351 строку без диапазона — отказ с путём, числом строк и порогом' {
    $f = New-File 351
    $reason = Assert-Deny (Invoke-Hook $f)
    Assert-True ($reason -match [regex]::Escape($f)) "в причине нет пути: $reason"
    Assert-True ($reason -match '351') "в причине нет числа строк: $reason"
    Assert-True ($reason -match '350') "в причине нет порога: $reason"
    Assert-True ($reason -match 'grep -n') "в причине нет подсказки grep -n: $reason"
    Assert-True ($reason -match 'offset') "в причине нет подсказки про offset/limit: $reason"
}

Test-Case 'файл на 1000 строк с limit 300 — проходит при любом offset' {
    $f = New-File 1000
    Assert-Silent (Invoke-Hook $f @{ limit = 300 })
    Assert-Silent (Invoke-Hook $f @{ offset = 500; limit = 300 })
}

Test-Case 'файл на 1000 строк с limit 800 — отказ: окно шире порога' {
    Assert-Deny (Invoke-Hook (New-File 1000) @{ limit = 800 }) | Out-Null
}

Test-Case 'offset у конца файла без limit — проходит: до конца меньше порога' {
    Assert-Silent (Invoke-Hook (New-File 1000) @{ offset = 700 })
}

Test-Case 'offset в начале большого файла без limit — отказ' {
    Assert-Deny (Invoke-Hook (New-File 1000) @{ offset = 100 }) | Out-Null
}

Test-Case 'файл на 30000 строк — отказ, подсчёт останавливается на потолке 20000' {
    $f = New-File 30000
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $reason = Assert-Deny (Invoke-Hook $f)
    $sw.Stop()
    Assert-True ($reason -match 'более 20000') "в причине нет потолка: $reason"
    Assert-True ($reason -notmatch '30000') "подсчёт дошёл до конца файла: $reason"
}

Test-Case 'отказ несёт оглавление: номера строк объявлений' {
    $f = New-CodeFile 400 50
    $reason = Assert-Deny (Invoke-Hook $f)
    Assert-True ($reason -match '50: function fn50') "в причине нет первого объявления: $reason"
    Assert-True ($reason -match '400: function fn400') "в причине нет последнего объявления: $reason"
}

Test-Case 'оглавление ограничено по длине и доходит до конца файла' {
    $f = New-CodeFile 2000 10
    $reason = Assert-Deny (Invoke-Hook $f)
    $entries = ([regex]::Matches($reason, 'function fn\d+')).Count
    Assert-True ($entries -le 40) "оглавление длиннее 40 записей: $entries"
    Assert-True ($entries -ge 10) "оглавление пустое или обрезано до начала файла: $entries"
    Assert-True ($reason -match '2000: function fn2000') "оглавление не доходит до конца файла: $reason"
}

Test-Case 'заголовки markdown идут в оглавление' {
    $path = Join-Path $tmp ([guid]::NewGuid().ToString('N') + '.md')
    $body = 1..400 | ForEach-Object { if ($_ % 40 -eq 0) { "## Section $_" } else { "text $_ " + ('x' * 50) } }
    $body | Out-File -LiteralPath $path -Encoding utf8
    $reason = Assert-Deny (Invoke-Hook $path)
    Assert-True ($reason -match '40: ## Section 40') "в причине нет заголовка: $reason"
}

Test-Case 'файл без объявлений — отказ без оглавления' {
    $reason = Assert-Deny (Invoke-Hook (New-File 400))
    Assert-True ($reason -notmatch 'Оглавление') "оглавление выдано там, где объявлений нет: $reason"
}

Test-Case 'отсутствующий файл — проходит, ошибку выдаст сам Read' {
    Assert-Silent (Invoke-Hook (Join-Path $tmp 'nope.cs'))
}

Test-Case 'картинка и PDF — проходят без подсчёта строк' {
    Assert-Silent (Invoke-Hook (New-File 1000 '.png'))
    Assert-Silent (Invoke-Hook (New-File 1000 '.pdf') @{ pages = '1-5' })
}

Test-Case 'чужой tool_name — проходит даже с большим файлом' {
    Assert-Silent (Invoke-Hook (New-File 1000) @{} 'Edit')
}

Test-Case 'кривой JSON на входе — молчит' {
    $out = 'not json' | & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hook
    Assert-True (($out -join '') -eq '') "ожидалось молчание, получено: $out"
    Assert-True ($LASTEXITCODE -eq 0) "код возврата $LASTEXITCODE"
}

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
if ($failed -gt 0) { Write-Host "`n$failed провалено"; exit 1 }
Write-Host "`nвсе тесты пройдены"
exit 0
