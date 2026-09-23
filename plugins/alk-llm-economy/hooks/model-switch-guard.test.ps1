# Fixture tests for model-switch-guard.ps1. Runs the hook as Claude Code runs it:
# a JSON event on stdin, a transcript on disk, the refusal on stderr and exit 2.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\model-switch-guard.test.ps1
$ErrorActionPreference = 'Stop'
$hook = Join-Path $PSScriptRoot 'model-switch-guard.ps1'
$tmp = Join-Path $env:TEMP ('model-switch-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$failed = 0

function New-Transcript {
    param([int]$Ctx, [switch]$Sidechain, [switch]$Empty)
    $ts = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $path = Join-Path $tmp ([guid]::NewGuid().ToString('N') + '.jsonl')
    $lines = @(@{ type = 'user'; timestamp = $ts; message = @{ role = 'user'; content = 'привет' } } | ConvertTo-Json -Compress -Depth 9)
    if (-not $Empty) {
        $asst = @{
            type      = 'assistant'
            timestamp = $ts
            message   = @{
                role    = 'assistant'
                usage   = @{ input_tokens = 12; cache_creation_input_tokens = 0; cache_read_input_tokens = ($Ctx - 12) }
                content = @(@{ type = 'text'; text = 'готово' })
            }
        }
        if ($Sidechain) { $asst.isSidechain = $true }
        $lines += ($asst | ConvertTo-Json -Compress -Depth 9)
    }
    $lines | Out-File -LiteralPath $path -Encoding utf8
    return $path
}

# stderr is captured through cmd, not a PowerShell redirect: in 5.1 a native
# command's stderr comes back as ErrorRecords and would fail the test on exit 0.
function Invoke-Hook {
    param([string]$Transcript, [string]$SessionId, [string]$To, [string]$From = 'claude-opus-5', [string]$Event = 'PreModelSwitch')
    $stem = Join-Path $tmp ([guid]::NewGuid().ToString('N'))
    $evt = @{
        hook_event_name = $Event
        session_id      = $SessionId
        transcript_path = $Transcript
        cwd             = 'C:\Proj\ClaudeOps'
        from_model      = $From
        to_model        = $To
    } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllBytes("$stem.json", (New-Object System.Text.UTF8Encoding $false).GetBytes($evt))
    cmd /c "type `"$stem.json`" | powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$hook`" > `"$stem.out`" 2> `"$stem.err`""
    $code = $LASTEXITCODE
    $err = if (Test-Path "$stem.err") { [System.IO.File]::ReadAllText("$stem.err", [System.Text.UTF8Encoding]::new($false)) } else { '' }
    return [pscustomobject]@{ Code = $code; Err = $err }
}

function Check($name, $cond) {
    if ($cond) { Write-Host "  ok  $name" } else { Write-Host "FAIL  $name"; $script:failed++ }
}

$big = New-Transcript -Ctx 150000

# Ход уже был и контекст большой — переключение стоит перезаписи, хук его держит.
$r = Invoke-Hook -Transcript $big -SessionId 's1' -To 'claude-fable-5-1'
Check 'блокирует смену модели посреди сессии' ($r.Code -eq 2)
Check 'называет модель, контекст и цену' ($r.Err -match 'claude-fable-5-1' -and $r.Err -match '150k' -and $r.Err -match '3\.00')

# Повторное переключение на ту же модель — решение осознанное, пропускаем.
$r = Invoke-Hook -Transcript $big -SessionId 's1' -To 'claude-fable-5-1'
Check 'второй раз на ту же модель проходит' ($r.Code -eq 0 -and -not $r.Err.Trim())

# Другая модель в той же сессии — снова новое решение, снова один стоп.
$r = Invoke-Hook -Transcript $big -SessionId 's1' -To 'claude-haiku-4-5-20251001'
Check 'другая модель блокируется заново' ($r.Code -eq 2)
Check 'цена считается по тарифу новой модели' ($r.Err -match '0\.30')

# До первого ответа модели терять нечего: выбор модели на старте — это и есть правило.
$r = Invoke-Hook -Transcript (New-Transcript -Empty) -SessionId 's2' -To 'claude-fable-5-1'
Check 'до первого хода молчит' ($r.Code -eq 0)

# Мелкий контекст: перезапись дешевле, чем помеха от стопа.
$r = Invoke-Hook -Transcript (New-Transcript -Ctx 20000) -SessionId 's3' -To 'claude-fable-5-1'
Check 'на малом контексте молчит' ($r.Code -eq 0)

# Сабагент греет свой префикс, а не наш: его usage не повод считать сессию дорогой.
$r = Invoke-Hook -Transcript (New-Transcript -Ctx 150000 -Sidechain) -SessionId 's4' -To 'claude-fable-5-1'
Check 'usage сабагента не считается' ($r.Code -eq 0)

# Матчер в settings.json можно расширить по ошибке — событие проверяется и здесь.
$r = Invoke-Hook -Transcript $big -SessionId 's5' -To 'claude-fable-5-1' -Event 'PostModelSwitch'
Check 'чужое событие пропускает' ($r.Code -eq 0)

# Клиент может прислать переключение на ту же модель — это не смена.
$r = Invoke-Hook -Transcript $big -SessionId 's6' -To 'claude-opus-5' -From 'claude-opus-5'
Check 'та же модель не считается сменой' ($r.Code -eq 0)

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
if ($failed) { Write-Host "`n$failed failed"; exit 1 }
Write-Host "`nall passed"
exit 0
