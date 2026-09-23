# Fixture tests for context-budget.ps1. Runs the hook as Claude Code runs it:
# a JSON event on stdin, a transcript on disk, JSON on stdout.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\context-budget.test.ps1
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$hook = Join-Path $PSScriptRoot 'context-budget.ps1'
$tmp = Join-Path $env:TEMP ('context-budget-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$failed = 0

function New-Transcript {
    param([int]$Ctx, [string]$Model = '')
    $ts = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $path = Join-Path $tmp ([guid]::NewGuid().ToString('N') + '.jsonl')
    $user = @{ type = 'user'; timestamp = $ts; message = @{ role = 'user'; content = 'привет' } }
    $asst = @{
        type      = 'assistant'
        timestamp = $ts
        message   = @{
            role    = 'assistant'
            usage   = @{ input_tokens = 12; cache_creation_input_tokens = 0; cache_read_input_tokens = ($Ctx - 12) }
            content = @(@{ type = 'text'; text = 'Готово.' })
        }
    }
    if ($Model) { $asst.message.model = $Model }
    @(($user | ConvertTo-Json -Compress -Depth 9), ($asst | ConvertTo-Json -Compress -Depth 9)) |
        Out-File -LiteralPath $path -Encoding utf8
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

Test-Case 'контекст 150k — блокирует ход и называет цену' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code), ожидался 0"
    Assert-True ($r.Raw -ne '') 'вывод пустой, ожидалась блокировка'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "decision=$($j.decision), ожидался block"
    Assert-True ($j.reason -match '150k') "в тексте нет размера контекста: $($j.reason)"
    Assert-True ($j.reason -match '0\.75') "в тексте нет цены десяти ходов здесь: $($j.reason)"
    Assert-True ($j.reason -match '0\.20') "в тексте нет цены десяти ходов в новой сессии: $($j.reason)"
    Assert-True ($j.reason -match 'ещё раз') "в тексте нет подсказки о повторной отправке: $($j.reason)"
    # Блокировка адресована владельцу: модель её не видит, поэтому указаний
    # модели (AskUserQuestion, remember) в тексте быть не должно.
    Assert-True ($j.reason -notmatch 'AskUserQuestion') "текст блокировки адресован модели: $($j.reason)"
}

Test-Case 'повторная отправка того же сообщения проходит' {
    $t = New-Transcript -Ctx 150000
    $sid = [guid]::NewGuid().ToString('N')
    $first = Invoke-Hook $t $sid
    Assert-True ($first.Raw -ne '') 'первая отправка должна блокироваться'
    $second = Invoke-Hook $t $sid
    Assert-True ($second.Raw -eq '') "цена уже названа, повтор должен проходить: $($second.Raw)"
}

# Бюджет 100k остаётся шагом ступеней, но порогом срабатывания быть перестал
# (2026-09-17): подсказка на нём стоила хода по полному контексту, а автосжатие
# приходит примерно туда же само.
Test-Case 'контекст 120k — молчит: бюджет больше не порог' {
    $r = Invoke-Hook (New-Transcript -Ctx 120000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'контекст 80k — молчит' {
    $r = Invoke-Hook (New-Transcript -Ctx 80000) ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'нет транскрипта — молчит' {
    $r = Invoke-Hook (Join-Path $tmp 'нет-такого.jsonl') ([guid]::NewGuid().ToString('N'))
    Assert-True ($r.Raw -eq '') "ожидалось молчание, получено: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

# Системные промпты харнесса — уведомление о завершении сабагента, сообщение
# из соседней сессии, вывод локальной команды — владелец не набирал и повторно
# отправить не может: блокировка их просто теряет. Порог адресован владельцу,
# поэтому на них хук молчит, сколько бы ни было контекста.
Test-Case 'уведомление о завершении сабагента при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '<task-notification>
<task-id>a5a5d72c719ae2a7</task-id>
<status>completed</status>
</task-notification>'
    Assert-True ($r.Raw -eq '') "уведомление сабагента заблокировано: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'сообщение из соседней сессии при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '<cross-session-message from="claudeops-fb">беру 4 файла</cross-session-message>'
    Assert-True ($r.Raw -eq '') "сообщение соседней сессии заблокировано: $($r.Raw)"
}

Test-Case 'вывод локальной команды при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '<local-command-stdout>все тесты пройдены</local-command-stdout>'
    Assert-True ($r.Raw -eq '') "вывод локальной команды заблокирован: $($r.Raw)"
}

# Флаг ставится один раз на порог: пропусти хук уведомление, потратив на него
# флаг, — и владелец цены не увидит уже никогда.
Test-Case 'уведомление не расходует флаг порога' {
    $t = New-Transcript -Ctx 150000
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook $t $sid '<task-notification><status>completed</status></task-notification>' | Out-Null
    $r = Invoke-Hook $t $sid
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "флаг израсходован уведомлением: $($r.Raw)"
}

# Владелец набрал сам — блокировать можно: повторная отправка проходит.
Test-Case 'слэш-команда владельца при 150k — блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '/code-review medium'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "команда владельца пропущена: $($r.Raw)"
}

# Исключение ровно одно: сохранение состояния — это и есть выход, который
# блок советует («состояние пишется в .remember»). Заблокировать его значит
# потребовать двух отправок ради собственного совета.
Test-Case 'полное имя команды сохранения при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '/remember:remember'
    Assert-True ($r.Raw -eq '') "сохранение состояния заблокировано: $($r.Raw)"
    Assert-True ($r.Code -eq 0) "код возврата $($r.Code)"
}

Test-Case 'короткое имя команды сохранения при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '/remember'
    Assert-True ($r.Raw -eq '') "сохранение состояния заблокировано: $($r.Raw)"
}

# Тот же флаг на порог: пропусти хук сохранение, потратив на него флаг, —
# и цену владелец не увидит, если после /remember решит продолжить здесь.
Test-Case 'команда сохранения не расходует флаг порога' {
    $t = New-Transcript -Ctx 150000
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook $t $sid '/remember:remember' | Out-Null
    $r = Invoke-Hook $t $sid
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "флаг израсходован сохранением: $($r.Raw)"
}

# Диагностика плагина — обычная команда, исключение на неё не распространяется.
Test-Case 'другая команда плагина remember при 150k — блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '/remember:doctor'
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "диагностика пропущена: $($r.Raw)"
}

# Одна блокировка на сессию отпускает контекст сколь угодно далеко: после
# «продолжаем здесь» на 150k сессия 2026-09-15 доехала до 345k молча. Красный
# порог повторяется каждый следующий бюджет сверх него: 150k, 250k, 350k.
Test-Case 'следующий бюджет сверх красного порога блокирует снова' {
    $sid = [guid]::NewGuid().ToString('N')
    $first = Invoke-Hook (New-Transcript -Ctx 150000) $sid
    Assert-True ($first.Raw -ne '') 'первый блок на 150k не сработал'
    $second = Invoke-Hook (New-Transcript -Ctx 250000) $sid
    $j = $second.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "вторая ступень не сработала: $($second.Raw)"
    Assert-True ($j.reason -match '250k') "в тексте не размер контекста второй ступени: $($j.reason)"
}

Test-Case 'внутри одной ступени повтор проходит' {
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook (New-Transcript -Ctx 150000) $sid | Out-Null
    $r = Invoke-Hook (New-Transcript -Ctx 249000) $sid
    Assert-True ($r.Raw -eq '') "цена ступени уже названа, повтор должен проходить: $($r.Raw)"
}

Test-Case 'третья ступень 350k блокирует после второй' {
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook (New-Transcript -Ctx 150000) $sid | Out-Null
    Invoke-Hook (New-Transcript -Ctx 250000) $sid | Out-Null
    $r = Invoke-Hook (New-Transcript -Ctx 350000) $sid
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "третья ступень не сработала: $($r.Raw)"
}

# «Полтора бюджета» верно только на первой ступени: на 345k доля считается.
Test-Case 'текст называет долю бюджета по контексту' {
    $r = Invoke-Hook (New-Transcript -Ctx 350000) ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '3\.5 бюджета') "доля бюджета не пересчитана: $($j.reason)"
}

# Совет закрыть сессию без способа её закрыть заставлял владельца отправлять
# /remember дважды: теперь исключение названо в самом тексте.
Test-Case 'текст называет непроходящую блокировку команду сохранения' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '/remember') "в тексте нет команды сохранения: $($j.reason)"
}


# Сжатие — второй выход, который советует красный порог: сводку пишет та же
# модель, транскрипт остаётся в .jsonl. Блокировать /compact значит требовать
# двух отправок ради собственного совета.
Test-Case 'команда сжатия при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '/compact'
    Assert-True ($r.Raw -eq '') "сжатие заблокировано: $($r.Raw)"
}

Test-Case 'команда сжатия с фокусом при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) '/compact сохрани список файлов'
    Assert-True ($r.Raw -eq '') "сжатие с фокусом заблокировано: $($r.Raw)"
}

Test-Case 'команда сжатия не расходует флаг порога' {
    $t = New-Transcript -Ctx 150000
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook $t $sid '/compact' | Out-Null
    $r = Invoke-Hook $t $sid
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "флаг израсходован сжатием: $($r.Raw)"
}

# Компакт роняет контекст ниже порога, а флаги сессии уже израсходованы: без
# сброса второй набор до 150k прошёл бы молча. Единственное падение контекста
# внутри сессии — сжатие, поэтому «ниже 150k» и есть его признак.
Test-Case 'после падения контекста порог блокирует снова' {
    $sid = [guid]::NewGuid().ToString('N')
    Invoke-Hook (New-Transcript -Ctx 150000) $sid | Out-Null
    Invoke-Hook (New-Transcript -Ctx 30000) $sid | Out-Null
    $r = Invoke-Hook (New-Transcript -Ctx 150000) $sid
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.decision -eq 'block') "красный порог после сжатия не повторился: $($r.Raw)"
}

Test-Case 'текст блокировки называет сжатие' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '/compact') "в тексте нет команды сжатия: $($j.reason)"
}
# Пинг keepalive держит кэш живым как раз при большом контексте: там простой
# и стоит дорого (docs/decisions/2026-09-18-keepalive-cron.md). Заблокируй его
# порог — и пинг пропадёт вместе с кэшем, который он оплачивает.
Test-Case 'keepalive-пинг при 150k — не блокируется' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000) ([guid]::NewGuid().ToString('N')) 'keepalive: ответь точкой'
    Assert-True ($r.Raw -eq '') "пинг keepalive заблокирован: $($r.Raw)"
}


# Цена в тексте — по модели сессии из транскрипта (scripts/prices.js), а не по
# Opus: дефолт команды Sonnet, и с ценой Opus оценка врала в 2,5 раза.
Test-Case 'Sonnet 150k — цена по чтению кэша Sonnet' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000 -Model 'claude-sonnet-5') ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '0\.30') "нет цены десяти ходов по Sonnet: $($j.reason)"
    Assert-True ($j.reason -match '0\.08') "нет цены после сжатия по Sonnet: $($j.reason)"
    Assert-True ($j.reason -notmatch '0\.75') "осталась цена Opus: $($j.reason)"
}

Test-Case 'Haiku с датой сборки в id — своя цена' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000 -Model 'claude-haiku-4-5-20251001') ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '0\.15') "нет цены по Haiku: $($j.reason)"
}

Test-Case 'неизвестная модель — цена по Opus 5, как раньше' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000 -Model '<synthetic>') ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '0\.75') "нет запасной цены Opus: $($j.reason)"
}

# У Fable 5.1 чтение кэша $0.25 за 1M — дешевле Opus 5; у Fable 5 — $1.00.
# Имена похожи, цены разнятся вчетверо: префикс не должен их путать.
Test-Case 'Fable 5.1 — чтение кэша дешевле Opus 5' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000 -Model 'claude-fable-5-1') ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '0\.38') "нет цены десяти ходов по Fable 5.1: $($j.reason)"
    Assert-True ($j.reason -match '0\.10') "нет цены после сжатия по Fable 5.1: $($j.reason)"
}

Test-Case 'Fable 5 — своя цена, не Fable 5.1' {
    $r = Invoke-Hook (New-Transcript -Ctx 150000 -Model 'claude-fable-5') ([guid]::NewGuid().ToString('N'))
    $j = $r.Raw | ConvertFrom-Json
    Assert-True ($j.reason -match '1\.50') "нет цены десяти ходов по Fable 5: $($j.reason)"
    Assert-True ($j.reason -match '0\.40') "нет цены после сжатия по Fable 5: $($j.reason)"
}

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $env:TEMP -Filter 'claude-context-budget-*.flag' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
if ($failed -gt 0) { Write-Host "`n$failed провалено"; exit 1 }
Write-Host "`nвсе тесты пройдены"
exit 0
