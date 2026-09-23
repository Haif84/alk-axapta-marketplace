# Fixture tests for keepalive-gate.ps1. Runs the hook as Claude Code runs it:
# a JSON event on stdin, a transcript on disk, JSON on stdout.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\keepalive-gate.test.ps1
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$hook = Join-Path $PSScriptRoot 'keepalive-gate.ps1'
$tmp = Join-Path $env:TEMP ('keepalive-gate-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$failed = 0
$Ping = 'keepalive: ответь точкой'

function New-Transcript {
    param([double]$MinutesAgo, [int]$Ctx)
    $ts = [datetime]::UtcNow.AddMinutes(-$MinutesAgo).ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $path = Join-Path $tmp ([guid]::NewGuid().ToString('N') + '.jsonl')
    $asst = @{
        type      = 'assistant'
        timestamp = $ts
        message   = @{
            role    = 'assistant'
            usage   = @{ input_tokens = 12; cache_creation_input_tokens = 0; cache_read_input_tokens = ($Ctx - 12) }
            content = @(@{ type = 'text'; text = '.' })
        }
    }
    (,($asst | ConvertTo-Json -Compress -Depth 9)) | Out-File -LiteralPath $path -Encoding utf8
    return $path
}

function Invoke-Hook {
    param([string]$Transcript, [string]$SessionId, [string]$Prompt = 'keepalive: ответь точкой')
    $event = @{
        hook_event_name = 'UserPromptSubmit'
        session_id      = $SessionId
        transcript_path = $Transcript
        cwd             = 'C:\Proj\ClaudeOps'
        prompt          = $Prompt
    } | ConvertTo-Json -Compress
    $out = $event | & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hook
    $raw = ($out -join '')
    $ctx = if ($raw) { ($raw | ConvertFrom-Json).hookSpecificOutput.additionalContext } else { '' }
    return [pscustomobject]@{ Raw = $raw; Context = $ctx; Code = $LASTEXITCODE }
}

# Пинги идут по одному транскрипту: каждый ответ модели — точка, и порог
# «25 минут с последнего ответа» в тесте держится фикстурой, а не временем.
function Invoke-Pings {
    param([string]$Transcript, [string]$SessionId, [int]$Count)
    $last = $null
    for ($i = 0; $i -lt $Count; $i++) { $last = Invoke-Hook $Transcript $SessionId }
    return $last
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

Test-Case 'пауза 30 мин и контекст 100k — пинг проходит молча' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 30 -Ctx 100000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code), ожидался 0"
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
}

# Пинг стоит чтения кэша; если ответ модели свежий, продлевать нечего.
Test-Case 'пауза 10 мин — блокирует, ход к модели не уходит' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 10 -Ctx 100000) ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "decision=$($j.decision), вывод: $($r.Raw)"
}

# Тот же порог, что у pause-guard: ниже 60k перезапись дешевле шести пингов.
Test-Case 'контекст 20k — блокирует, перезапись дешевле пинга' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 30 -Ctx 20000) ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "decision=$($j.decision), вывод: $($r.Raw)"
    Assert-True ($j.reason -match '60k') "в тексте нет порога контекста: $($j.reason)"
}

Test-Case 'пятый пинг проходит молча' {
    $r = Invoke-Pings (New-Transcript -MinutesAgo 30 -Ctx 100000) ([guid]::NewGuid().ToString('N')) 5
    Assert-True ($r.Raw -eq '') "пятый пинг не должен ничего добавлять: $($r.Raw)"
}

# Шестой пинг — последний в паузе: владелец не вернулся, и сессия пишет handoff
# сама, пока видит всю работу. Замер и rename остаются за /remember владельца.
Test-Case 'шестой пинг просит написать handoff' {
    $r = Invoke-Pings (New-Transcript -MinutesAgo 30 -Ctx 100000) ([guid]::NewGuid().ToString('N')) 6
    Assert-True ($r.Raw -ne '') 'шестой пинг должен нести additionalContext'
    Assert-True ($r.Context -match '\.remember/remember\.md') "нет пути handoff: $($r.Context)"
    Assert-True ($r.Context -match 'State') "нет шаблона handoff: $($r.Context)"
    Assert-True ($r.Context -notmatch '(^|\s)/remember') "пинг советует дорогой /remember: $($r.Context)"
}

Test-Case 'седьмой пинг блокируется по лимиту' {
    $r = Invoke-Pings (New-Transcript -MinutesAgo 30 -Ctx 100000) ([guid]::NewGuid().ToString('N')) 7
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "decision=$($j.decision), вывод: $($r.Raw)"
    Assert-True ($j.reason -match '6') "в тексте нет лимита пингов: $($j.reason)"
}

# Владелец вернулся — пауза кончилась, и следующая получает полный лимит.
Test-Case 'обычный промпт обнуляет счётчик пингов' {
    $t = New-Transcript -MinutesAgo 30 -Ctx 100000
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Pings $t $sid 6 | Out-Null
    $own = Invoke-Hook $t $sid 'продолжаем'
    Assert-True ($own.Raw -eq '') "обычный промпт хук трогать не должен: $($own.Raw)"
    $r = Invoke-Hook $t $sid
    Assert-True ($r.Raw -eq '') "после возврата владельца пинг снова первый: $($r.Raw)"
}

# Уведомление сабагента приходит тем же событием, но владельца за клавиатурой
# не значит: обнуление дало бы новые шесть пингов сверх лимита паузы.
Test-Case 'уведомление сабагента счётчик не обнуляет' {
    $t = New-Transcript -MinutesAgo 30 -Ctx 100000
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Pings $t $sid 5 | Out-Null
    $note = Invoke-Hook $t $sid '<task-notification>задача 3 готова</task-notification>'
    Assert-True ($note.Raw -eq '') "уведомление хук трогать не должен: $($note.Raw)"
    $r = Invoke-Hook $t $sid
    Assert-True ($r.Context -match '\.remember/remember\.md') "уведомление обнулило счётчик, шестой пинг молчит: $($r.Raw)"
}

Test-Case 'счётчик отдельный на каждую сессию' {
    $t = New-Transcript -MinutesAgo 30 -Ctx 100000
    Invoke-Pings $t ([guid]::NewGuid().ToString('N')) 7 | Out-Null
    $r = Invoke-Hook $t ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "лимит соседней сессии перекрыл пинг: $($r.Raw)"
}

Test-Case 'транскрипт не найден — блокирует' {
    $r = Invoke-Hook (Join-Path $tmp 'нет-такого.jsonl') ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "decision=$($j.decision), вывод: $($r.Raw)"
}

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $env:TEMP -Filter 'claude-keepalive-*.flag' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
if ($failed -gt 0) { Write-Host "`n$failed провалено"; exit 1 }
Write-Host "`nвсе тесты пройдены"
exit 0
