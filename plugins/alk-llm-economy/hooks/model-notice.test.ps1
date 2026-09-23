# Fixture tests for model-notice.ps1. The hook reads settings.json from
# $env:USERPROFILE and keeps its once-per-session flag in $env:TEMP, so each
# case runs against a temp home and its own session_id.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\model-notice.test.ps1
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$hook = Join-Path $PSScriptRoot 'model-notice.ps1'
$tmp = Join-Path $env:TEMP ('model-notice-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$realHome = $env:USERPROFILE
$failed = 0
$sessions = @()

function New-Home {
    param([hashtable]$Settings, [switch]$NoSettings)
    $fake = Join-Path $tmp ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Join-Path $fake '.claude') -Force | Out-Null
    if (-not $NoSettings) {
        ($Settings | ConvertTo-Json -Depth 5) | Out-File -LiteralPath (Join-Path $fake '.claude\settings.json') -Encoding utf8
    }
    return $fake
}

function Invoke-Hook {
    param([string]$FakeHome, [string]$SessionId, [string]$Prompt = 'дальше')
    if (-not $SessionId) { $SessionId = 'mn-' + [guid]::NewGuid().ToString('N') }
    $script:sessions += $SessionId
    $event = @{ hook_event_name = 'UserPromptSubmit'; session_id = $SessionId; prompt = $Prompt; cwd = 'C:\Proj\ClaudeOps' } | ConvertTo-Json -Compress
    $env:USERPROFILE = $FakeHome
    try {
        $out = $event | & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hook
    } finally {
        $env:USERPROFILE = $realHome
    }
    $raw = ($out -join '')
    $ctx = if ($raw) { ($raw | ConvertFrom-Json).hookSpecificOutput.additionalContext } else { '' }
    return [pscustomobject]@{ Raw = $raw; Context = $ctx; SessionId = $SessionId }
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

Test-Case 'дефолт sonnet medium — молчит' {
    $r = Invoke-Hook (New-Home @{ model = 'sonnet'; effortLevel = 'medium' })
    Assert-True ($r.Context -notmatch 'МОДЕЛЬ СЕССИИ') "о дефолте сообщать нечего: $($r.Context)"
}

Test-Case 'полный id claude-sonnet-5[1m] medium — тоже дефолт' {
    $r = Invoke-Hook (New-Home @{ model = 'claude-sonnet-5[1m]'; effortLevel = 'medium' })
    Assert-True ($r.Context -notmatch 'МОДЕЛЬ СЕССИИ') "id вместо псевдонима — не отклонение: $($r.Context)"
}

Test-Case 'Fable вместо Sonnet — строка с ценой за токен' {
    $r = Invoke-Hook (New-Home @{ model = 'claude-fable-5-1[1m]'; effortLevel = 'high' })
    Assert-True ($r.Context -match 'МОДЕЛЬ СЕССИИ') "нет строки о модели: $($r.Context)"
    Assert-True ($r.Context -match 'fable') "в строке нет имени модели: $($r.Context)"
    Assert-True ($r.Context -match '\$10/\$50') "в строке нет цены модели: $($r.Context)"
    Assert-True ($r.Context -match '\$2/\$10') "в строке нет цены дефолта: $($r.Context)"
}

Test-Case 'Opus 5 — своя цена' {
    $r = Invoke-Hook (New-Home @{ model = 'opus'; effortLevel = 'medium' })
    Assert-True ($r.Context -match '\$5/\$25') "в строке нет цены Opus 5: $($r.Context)"
}

Test-Case 'Opus 5.5 — своя цена, не Opus 5' {
    $r = Invoke-Hook (New-Home @{ model = 'claude-opus-5-5[1m]'; effortLevel = 'medium' })
    Assert-True ($r.Context -match '\$4/\$20') "в строке нет цены Opus 5.5: $($r.Context)"
}

Test-Case 'effort выше дефолта при Sonnet — строка про effort, без смены цены' {
    $r = Invoke-Hook (New-Home @{ model = 'sonnet'; effortLevel = 'high' })
    Assert-True ($r.Context -match 'МОДЕЛЬ СЕССИИ') "нет строки о настройках: $($r.Context)"
    Assert-True ($r.Context -match 'high') "в строке нет текущего effort: $($r.Context)"
    Assert-True ($r.Context -match 'та же') "цена та же, а строка говорит о другой: $($r.Context)"
}

Test-Case 'нет settings.json — молчит' {
    $r = Invoke-Hook (New-Home -NoSettings)
    Assert-True ($r.Raw -eq '') "без settings.json сказать нечего: $($r.Raw)"
}

Test-Case 'model не задан — не дефолт команды, говорим' {
    $r = Invoke-Hook (New-Home @{ effortLevel = 'medium' })
    Assert-True ($r.Context -match 'МОДЕЛЬ СЕССИИ') "без ключа сессия идёт не на Sonnet: $($r.Context)"
    Assert-True ($r.Context -match 'не задан') "в строке не сказано, что ключа нет: $($r.Context)"
}

Test-Case 'второй промпт той же сессии — молчит' {
    $fake = New-Home @{ model = 'claude-fable-5-1[1m]'; effortLevel = 'high' }
    $sid = 'mn-' + [guid]::NewGuid().ToString('N')
    $first = Invoke-Hook $fake $sid
    Assert-True ($first.Context -match 'МОДЕЛЬ СЕССИИ') "первый промпт обязан сказать: $($first.Context)"
    $second = Invoke-Hook $fake $sid
    Assert-True ($second.Raw -eq '') "предупреждение повторилось: $($second.Raw)"
}

Test-Case 'другая сессия — говорит заново' {
    $fake = New-Home @{ model = 'claude-fable-5-1[1m]'; effortLevel = 'high' }
    $first = Invoke-Hook $fake
    $second = Invoke-Hook $fake
    Assert-True ($first.Context -match 'МОДЕЛЬ СЕССИИ') "первая сессия молчит: $($first.Context)"
    Assert-True ($second.Context -match 'МОДЕЛЬ СЕССИИ') "вторая сессия молчит: $($second.Context)"
}

$env:USERPROFILE = $realHome
foreach ($s in ($sessions | Select-Object -Unique)) {
    Remove-Item -LiteralPath (Join-Path $env:TEMP ("claude-model-notice-{0}.flag" -f $s)) -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
if ($failed -gt 0) { Write-Host "`n$failed провалено"; exit 1 }
Write-Host "`nвсе тесты пройдены"
exit 0
