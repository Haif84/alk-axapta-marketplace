# Fixture tests for session-memory.ps1. The hook reads the memory index and the
# superpowers plugin cache from $env:USERPROFILE, so each case runs against a
# temp home.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\session-memory.test.ps1
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$hook = Join-Path $PSScriptRoot 'session-memory.ps1'
$tmp = Join-Path $env:TEMP ('session-memory-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$realHome = $env:USERPROFILE
$failed = 0

function New-Home {
    $fake = Join-Path $tmp ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Join-Path $fake '.claude\memory') -Force | Out-Null
    '# Memory Index — Global' | Out-File -LiteralPath (Join-Path $fake '.claude\memory\MEMORY.md') -Encoding utf8
    return $fake
}

function Invoke-Hook {
    param([string]$FakeHome)
    $event = @{ hook_event_name = 'SessionStart'; session_id = 'test'; source = 'startup'; cwd = 'C:\Proj\ClaudeOps' } | ConvertTo-Json -Compress
    $env:USERPROFILE = $FakeHome
    try {
        $out = $event | & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hook
    } finally {
        $env:USERPROFILE = $realHome
    }
    $raw = ($out -join '')
    $ctx = if ($raw) { ($raw | ConvertFrom-Json).hookSpecificOutput.additionalContext } else { '' }
    return [pscustomobject]@{ Raw = $raw; Context = $ctx }
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

Test-Case 'индекс памяти подан' {
    $r = Invoke-Hook (New-Home)
    Assert-True ($r.Context -match 'MEMORY INDEX') 'индекс памяти не подан'
}

Test-Case 'о модели не говорит — это дело model-notice.ps1' {
    $r = Invoke-Hook (New-Home)
    Assert-True ($r.Context -notmatch 'МОДЕЛЬ СЕССИИ') "предупреждение о модели осталось в SessionStart: $($r.Context)"
}

function Add-PluginHook {
    param([string]$FakeHome, [switch]$WithSessionStart)
    $dir = Join-Path $FakeHome '.claude\plugins\cache\claude-plugins-official\superpowers\6.3.0\hooks'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $cfg = if ($WithSessionStart) { '{ "hooks": { "SessionStart": [] } }' } else { '{ "hooks": {} }' }
    $cfg | Out-File -LiteralPath (Join-Path $dir 'hooks.json') -Encoding utf8
}

Test-Case 'обновление плагина вернуло впрыск superpowers — предупреждение' {
    $fake = New-Home
    Add-PluginHook $fake -WithSessionStart
    $r = Invoke-Hook $fake
    Assert-True ($r.Context -match 'superpowers-hook-off') "нет команды снятия впрыска: $($r.Context)"
}

Test-Case 'впрыск снят — молчим' {
    $fake = New-Home
    Add-PluginHook $fake
    $r = Invoke-Hook $fake
    Assert-True ($r.Context -notmatch 'superpowers') "лишнее слово про плагин: $($r.Context)"
}

Test-Case 'плагина нет — молчим' {
    $r = Invoke-Hook (New-Home)
    Assert-True ($r.Context -notmatch 'superpowers') "плагин не установлен, говорить не о чем: $($r.Context)"
}

$env:USERPROFILE = $realHome
Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
if ($failed -gt 0) { Write-Host "`n$failed провалено"; exit 1 }
Write-Host "`nвсе тесты пройдены"
exit 0
