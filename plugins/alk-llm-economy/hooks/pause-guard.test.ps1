# Fixture tests for pause-guard.ps1. Runs the hook as Claude Code runs it:
# a JSON event on stdin, a transcript on disk, JSON on stdout.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\pause-guard.test.ps1
$ErrorActionPreference = 'Stop'
# Claude Code hands the hook UTF-8 bytes on stdin; without this the pipe would
# re-encode them in the console codepage and the test would not match reality.
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$hook = Join-Path $PSScriptRoot 'pause-guard.ps1'
$tmp = Join-Path $env:TEMP ('pause-guard-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$failed = 0

function New-Transcript {
    param([double]$MinutesAgo, [int]$Ctx, [string]$Text = 'Готово. Делаем сейчас или после замера?', [double]$SidechainMinutesAgo = -1)
    $ts = [datetime]::UtcNow.AddMinutes(-$MinutesAgo).ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $path = Join-Path $tmp ([guid]::NewGuid().ToString('N') + '.jsonl')
    $user = @{ type = 'user'; timestamp = $ts; message = @{ role = 'user'; content = 'привет' } }
    $asst = @{
        type      = 'assistant'
        timestamp = $ts
        message   = @{
            role    = 'assistant'
            usage   = @{ input_tokens = 12; cache_creation_input_tokens = 0; cache_read_input_tokens = ($Ctx - 12) }
            content = @(@{ type = 'text'; text = $Text })
        }
    }
    $lines = @(($user | ConvertTo-Json -Compress -Depth 9), ($asst | ConvertTo-Json -Compress -Depth 9))
    if ($SidechainMinutesAgo -ge 0) {
        $side = $asst.Clone()
        $side.timestamp = [datetime]::UtcNow.AddMinutes(-$SidechainMinutesAgo).ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
        $side.isSidechain = $true
        $lines += ($side | ConvertTo-Json -Compress -Depth 9)
    }
    $lines | Out-File -LiteralPath $path -Encoding utf8
    return $path
}

function Invoke-Hook {
    param([string]$Transcript, [string]$SessionId, [string]$Prompt = 'продолжаем')
    $event = @{
        hook_event_name = 'UserPromptSubmit'
        session_id      = $SessionId
        transcript_path = $Transcript
        cwd             = 'C:\Proj\ClaudeOps'
        prompt          = $Prompt
    } | ConvertTo-Json -Compress
    $out = $event | & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hook
    return [pscustomobject]@{ Raw = ($out -join ''); Code = $LASTEXITCODE }
}

# Ответ на висящий вопрос приходит хуку как PostToolUse с matcher AskUserQuestion:
# выбор лежит в tool_response.answers, а сам ход к модели ещё не ушёл.
function Invoke-AnswerHook {
    param([string]$Transcript, [string]$SessionId, [string]$ToolName = 'AskUserQuestion')
    $event = @{
        hook_event_name = 'PostToolUse'
        session_id      = $SessionId
        transcript_path = $Transcript
        cwd             = 'C:\Proj\ClaudeOps'
        tool_name       = $ToolName
        tool_input      = @{ questions = @(@{ question = '13:20 — вливаем ветку?'; header = 'Ветка' }) }
        tool_response   = @{ answers = @(@{ header = 'Ветка'; choice = 'Вливаем' }) }
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

Test-Case 'пауза 3 ч и контекст 150k — блокирует, называет цену и хвост вопроса' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code), ожидался 0"
    Assert-True ($r.Raw -ne '') 'вывод пустой, ожидалась блокировка'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "decision=$($j.decision)"
    Assert-True ($j.reason -match 'кэш истёк') "в тексте нет отметки об истёкшем кэше: $($j.reason)"
    Assert-True ($j.reason -match '150k') "в тексте нет размера контекста: $($j.reason)"
    Assert-True ($j.reason -match '1\.50') "в тексте нет цены перезаписи: $($j.reason)"
    Assert-True ($j.reason -match 'после замера') "в тексте нет хвоста последнего ответа: $($j.reason)"
    # Заблокированный промпт интерфейс печатает сам строкой Original prompt,
    # повторять его в тексте хука незачем.
    Assert-True ($j.reason -notmatch 'Твоё сообщение') "текст дублирует промпт: $($j.reason)"
}

# После истечения кэша /remember здесь оплачивает полную перезапись контекста
# (при 345k ≈$3.45), поэтому советовать его нельзя — но и молчать о способе
# сохранить состояние тоже: выжимка транскрипта сабагентом стоит ≈$0.02
# (docs/scripts.md, handoff-from-transcript.js).
Test-Case 'текст истёкшего кэша называет дешёвый сбор handoff' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match 'транскрипт') "в тексте нет дешёвого пути к handoff: $($j.reason)"
    Assert-True ($j.reason -notmatch '/remember') "текст советует дорогой /remember: $($j.reason)"
}

Test-Case 'остановка на ответе называет дешёвый сбор handoff' {
    $r = Invoke-AnswerHook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.stopReason -match 'транскрипт') "в тексте нет дешёвого пути к handoff: $($j.stopReason)"
}

Test-Case 'пауза 56 мин — блокирует и предупреждает, что кэш ещё жив' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 56 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -ne '') 'вывод пустой, ожидалась блокировка'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "decision=$($j.decision)"
    Assert-True ($j.reason -match 'истекает через') "нет предупреждения о живом кэше: $($j.reason)"
}

Test-Case 'пауза 10 мин — молчит' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 10 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'контекст 20k — молчит даже после долгой паузы' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 300 -Ctx 20000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
}

Test-Case 'повторная отправка того же сообщения проходит' {
    $t = New-Transcript -MinutesAgo 180 -Ctx 150000
    $sid = [guid]::NewGuid().ToString('N')
    $first = Invoke-Hook $t $sid
    Assert-True ($first.Raw -ne '') 'первая отправка должна блокироваться'
    $second = Invoke-Hook $t $sid
    Assert-True ($second.Raw -eq '') "вторая отправка должна проходить, получено: $($second.Raw)"
}

Test-Case 'следующая пауза в той же сессии блокирует снова' {
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook (New-Transcript -MinutesAgo 180 -Ctx 150000) $sid | Out-Null
    $r = Invoke-Hook (New-Transcript -MinutesAgo 120 -Ctx 150000) $sid
    Assert-True ($r.Raw -ne '') 'новая пауза должна блокироваться, несмотря на маркер'
    Assert-True ((($r.Raw | ConvertFrom-Json).decision) -eq 'block') "ожидался decision=block, получено: $($r.Raw)"
}

Test-Case 'свежий ответ сабагента не считается активностью основной беседы' {
    $t = New-Transcript -MinutesAgo 180 -Ctx 150000 -SidechainMinutesAgo 5
    $r = Invoke-Hook $t ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -ne '') 'пауза основной беседы 3 ч — ожидалась блокировка'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "ожидался decision=block, получено: $($r.Raw)"
    Assert-True ($j.reason -match 'Пауза 18\d мин') "пауза посчитана по сабагенту: $($j.reason)"
}

Test-Case 'кириллица уходит ASCII-экранированной' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($r.Raw)
    Assert-True (-not ($bytes | Where-Object { $_ -gt 127 })) 'в выводе есть не-ASCII байты'
    Assert-True ($r.Raw -match '\\u04') 'нет ни одной \uXXXX-последовательности'
}

Test-Case 'нет транскрипта — молчит' {
    $r = Invoke-Hook (Join-Path $tmp 'nope.jsonl') ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'ответ на висящий вопрос после 3 ч — останавливает ход и называет цену' {
    $r = Invoke-AnswerHook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code), ожидался 0"
    Assert-True ($r.Raw -ne '') 'вывод пустой, ожидалась остановка хода'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.'continue' -eq $false) "continue=$($j.'continue'), ожидалось false"
    Assert-True ($j.stopReason -match '150k') "в тексте нет размера контекста: $($j.stopReason)"
    Assert-True ($j.stopReason -match '1\.50') "в тексте нет цены перезаписи: $($j.stopReason)"
    Assert-True ($j.stopReason -match 'Ответ сохран') "в тексте не сказано, что ответ сохранён: $($j.stopReason)"
    # Блокировки промпта тут нет: ход остановлен после инструмента, поэтому
    # совет «отправь сообщение ещё раз» был бы неверным.
    Assert-True ($j.stopReason -notmatch 'ещё раз') "текст советует повторную отправку: $($j.stopReason)"
    # /remember — скилл, он сам стоит дорогого хода; советовать его тут нельзя.
    Assert-True ($j.stopReason -notmatch '/remember') "текст советует /remember: $($j.stopReason)"
    Assert-True ($j.decision -eq $null) "ответ содержит decision, лишний для PostToolUse: $($r.Raw)"
}

Test-Case 'PostToolUse от другого инструмента — молчит, даже после долгой паузы' {
    # Ветку выбирает не только matcher из settings.json: расширь его случайно —
    # и любой инструмент после простоя останавливал бы ход с текстом про ответ.
    $r = Invoke-AnswerHook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N')) -ToolName 'Bash'
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
}

Test-Case 'ответ на вопрос через 10 мин — молчит' {
    $r = Invoke-AnswerHook (New-Transcript -MinutesAgo 10 -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'ответ на вопрос при контексте 20k — молчит даже после долгой паузы' {
    $r = Invoke-AnswerHook (New-Transcript -MinutesAgo 300 -Ctx 20000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
}

Test-Case 'остановка на ответе и следом сообщение — вторая остановка не нужна' {
    $t = New-Transcript -MinutesAgo 180 -Ctx 150000
    $sid = [guid]::NewGuid().ToString('N')
    $first = Invoke-AnswerHook $t $sid
    Assert-True ($first.Raw -ne '') 'ответ после паузы должен останавливать ход'
    $second = Invoke-Hook $t $sid
    Assert-True ($second.Raw -eq '') "цена уже названа, сообщение должно проходить: $($second.Raw)"
}

# Сабагент работает часами: его уведомление о завершении приходит ровно в
# «пауза дольше часа». Владелец его не набирал и повторить не может — блокировка
# теряет результат задачи, а оркестратор остаётся ждать уже готовую работу.
Test-Case 'уведомление о завершении сабагента после паузы — не блокируется' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N')) '<task-notification>
<task-id>a5a5d72c719ae2a7</task-id>
<status>completed</status>
</task-notification>'
    Assert-True ($r.Raw -eq '') "уведомление сабагента заблокировано: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'сообщение из соседней сессии после паузы — не блокируется' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N')) '<cross-session-message from="claudeops-fb">беру 4 файла</cross-session-message>'
    Assert-True ($r.Raw -eq '') "сообщение соседней сессии заблокировано: $($r.Raw)"
}

# Маркер держит отметку хода, на котором хук сработал: израсходуй его на
# уведомление — и цену паузы владелец не увидит.
Test-Case 'уведомление не расходует маркер паузы' {
    $t = New-Transcript -MinutesAgo 180 -Ctx 150000
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook $t $sid '<task-notification><status>completed</status></task-notification>' | Out-Null
    $r = Invoke-Hook $t $sid
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "маркер израсходован уведомлением: $($r.Raw)"
}

# Пинг keepalive ставит cron самой сессии, чтобы читать кэш и не давать ему
# истечь (docs/decisions/2026-09-18-keepalive-cron.md). Блокировка теряет
# ровно тот ход, ради которого пинг и пришёл: повторить его некому.
Test-Case 'keepalive-пинг после паузы — не блокируется' {
    $r = Invoke-Hook (New-Transcript -MinutesAgo 180 -Ctx 150000) ([guid]::NewGuid().ToString('N')) 'keepalive: ответь точкой'
    Assert-True ($r.Raw -eq '') "пинг keepalive заблокирован: $($r.Raw)"
}


Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $env:TEMP -Filter 'claude-pause-guard-*.flag' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
if ($failed -gt 0) { Write-Host "`n$failed провалено"; exit 1 }
Write-Host "`nвсе тесты пройдены"
exit 0
