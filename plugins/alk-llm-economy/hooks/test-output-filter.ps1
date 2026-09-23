# PostToolUse hook (matcher Bash): replaces the output of a test run with a
# summary and keeps the full text in a file. A green `dotnet test` prints
# restore chatter, a discovery banner and a per-assembly log; all of it is paid
# for on every later turn of the session, because each turn is billed for the
# whole accumulated context (docs/costs.md). The tail of Bash output is one of
# the larger read items in the audit (docs/cost-audit-2026-09-14.md), and
# bashOutputMaxChars only caps it — it cannot tell the verdict from the chatter.
# The summary replaces stdout only: updatedToolOutput carries the other output
# fields through untouched, so exit_code reaches the agent and a red run stays
# red (memory: "пайп съедает код возврата теста").
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')

$MinLines = 40   # ниже этого резать нечего: сводка выйдет не короче исходника

# UTF-8 on stdin, not the console codepage: test output carries Cyrillic.
$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
$raw = $reader.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }
# Checked here and not only by the matcher: widen the matcher by accident and
# every tool's output would be rewritten.
if ($j.hook_event_name -ne 'PostToolUse' -or $j.tool_name -ne 'Bash') { exit 0 }

$cmd = [string]$j.tool_input.command
if (-not $cmd) { exit 0 }
# Узкий список раннеров: чужой формат вывода эвристика разберёт неверно и съест
# нужное. `cd x && dotnet test` ловится тем же выражением.
$IsTestRun = $cmd -match '(^|[\s;&|(])dotnet\s+test(\s|$)' -or
             $cmd -match '(^|[\s;&|(])npm\s+(run\s+)?test(\s|$)' -or
             $cmd -match '(^|[\s;&|(])node\s+--test(\s|$)'
if (-not $IsTestRun) { exit 0 }

$resp = $j.tool_response
$stdout = [string]$resp.stdout
$stderr = [string]$resp.stderr
$full = $stdout
if ($stderr.Trim()) { $full = ($stdout.TrimEnd() + "`n--- stderr ---`n" + $stderr) }
$lines = $full -split "`r?`n"
if ($lines.Count -lt $MinLines) { exit 0 }

# Полный вывод сохраняется всегда: сводка — не единственный экземпляр, при
# нужде агент достаёт из файла grep-ом нужное место.
$dir = [string]$j.scratchpad_dir
if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { $dir = $env:TEMP }
$stem = [string]$j.tool_use_id
if (-not $stem) { $stem = [guid]::NewGuid().ToString('N') }
$stem = ($stem -replace '[^\w\-]', '_')
$logPath = Join-Path $dir "test-output-$stem.log"
[System.IO.File]::WriteAllText($logPath, $full, (New-Object System.Text.UTF8Encoding $false))

# Строки, которые несут вердикт: итоги прогона, имена падений, ошибки сборки.
# Итоги: строка dotnet test на каждый тестовый проект и счётчики node --test.
# У node 24 репортёр по умолчанию — spec (`ℹ`/`✖`) даже в трубе; TAP остаётся
# при `--test-reporter=tap` и на старых версиях, поэтому разбираются оба.
# Вердикт dotnet печатается на языке системы: по-русски глагол склоняется, а
# разделитель — двоеточие вместо " - " (снято с прогона на русском SDK).
$SummaryLine = '^(Passed|Failed|Skipped)!\s+-\s+Failed:|^(Пройден|Не пройден|Пропущен)[а-я]*!\s*:\s*не пройдено|^#\s+(tests|pass|fail|skipped|todo|duration_ms)\b|^ℹ\s+\w'
$FailLine = '^\s*Failed\s+\S+|^\s*Не пройден\s+\S+|^not ok \d+|^✖'  # имя упавшего теста: dotnet (в т.ч. русский), TAP и spec
$DetailAnchor = '^test at \S'                  # у spec диагностика идёт отдельным разделом в конце
$Keep = @(
    $SummaryLine,
    $FailLine,
    '->\s+\S+\.dll\s*$',        # какие проекты собраны и запущены
    '\berror\s+[A-Z]+\d+:',     # error CS0103 / MSB3021: сборка не дошла до тестов
    '^Build FAILED\.'
)
$keepIdx = New-Object 'System.Collections.Generic.SortedSet[int]'
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    foreach ($rx in $Keep) { if ($line -match $rx) { [void]$keepIdx.Add($i); break } }
}

# Диагностика только первого падения: остальные почти всегда повторяют ту же
# причину, а полный текст лежит в файле.
$BlockLines = 25
$anchor = -1
$stopRx = $null
# У spec диагностика лежит в разделе «✖ failing tests:» — отсчёт ведётся от
# первой строки «test at …», иначе от первой строки падения (dotnet, TAP).
for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match $DetailAnchor) { $anchor = $i; $stopRx = $DetailAnchor; break } }
if ($anchor -lt 0) {
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match $FailLine) { $anchor = $i; $stopRx = "$FailLine|$SummaryLine|^#\s"; break } }
}
if ($anchor -ge 0) {
    [void]$keepIdx.Add($anchor)
    $stop = [Math]::Min($lines.Count, $anchor + 1 + $BlockLines)
    for ($k = $anchor + 1; $k -lt $stop; $k++) {
        if ($lines[$k] -match $stopRx) { break }
        [void]$keepIdx.Add($k)
    }
}

$kept = @(foreach ($i in $keepIdx) { $lines[$i] })
while ($kept.Count -gt 0 -and -not $kept[-1].Trim()) { $kept = $kept[0..($kept.Count - 2)] }
if ($kept.Count -eq 0) { exit 0 }

# Потолок bashOutputMaxChars режет вывод раньше, чем он доходит до хука, и у
# длинного прогона вердикт остаётся за обрезом: сводка из одних сборочных
# строк читается как зелёная. Такую сводку надо пометить, а не выдать молча.
$hasVerdict = $false
foreach ($line in $kept) { if ($line -match $SummaryLine) { $hasVerdict = $true; break } }
$summary = ($kept -join "`n")
if (-not $hasVerdict) {
    $summary += "`n`n(вердикт прогона не найден: вывод обрезан до конца прогона — судить по коду возврата)"
}
$summary += "`n`nПолный вывод: $logPath ($($lines.Count) строк)"
if ($summary.Length -ge $full.Length) { exit 0 }

# Форма ответа — вывод самого инструмента: Claude Code сверяет rewrite со
# схемой вывода Bash и молча откатывает его, если пришла строка. stderr
# обнуляется: он уже разобран в сводке и сохранён в файле целиком.
ConvertTo-AsciiJson -InputObject @{
    hookSpecificOutput = @{
        hookEventName     = 'PostToolUse'
        updatedToolOutput = @{
            stdout      = $summary
            stderr      = ''
            interrupted = [bool]$resp.interrupted
            isImage     = [bool]$resp.isImage
        }
    }
} -Depth 5
exit 0
