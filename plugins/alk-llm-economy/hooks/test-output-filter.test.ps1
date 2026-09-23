# Fixture tests for test-output-filter.ps1. Runs the hook as Claude Code runs it:
# a PostToolUse event on stdin, the replacement output as JSON on stdout.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\test-output-filter.test.ps1
$ErrorActionPreference = 'Stop'
$hook = Join-Path $PSScriptRoot 'test-output-filter.ps1'
$tmp = Join-Path $env:TEMP ('test-output-filter-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$failed = 0

function Check($name, $cond) {
    if ($cond) { Write-Host "  ok  $name" } else { Write-Host "FAIL  $name"; $script:failed++ }
}

# stdout is captured through cmd, not a PowerShell redirect: in 5.1 a native
# command's stderr comes back as ErrorRecords and would fail the test on exit 0.
function Invoke-Hook {
    param(
        [string]$Command,
        [string]$Stdout,
        [string]$Stderr = '',
        [int]$ExitCode = 0,
        [string]$Scratchpad,
        [string]$ToolName = 'Bash'
    )
    $stem = Join-Path $tmp ([guid]::NewGuid().ToString('N'))
    $evt = @{
        hook_event_name = 'PostToolUse'
        session_id      = 's1'
        cwd             = 'C:\Proj\ClaudeOps'
        tool_name       = $ToolName
        tool_use_id     = 'toolu_' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        tool_input      = @{ command = $Command }
        tool_response   = @{ stdout = $Stdout; stderr = $Stderr; exit_code = $ExitCode }
    }
    if ($Scratchpad) { $evt.scratchpad_dir = $Scratchpad }
    $json = $evt | ConvertTo-Json -Compress -Depth 9
    [System.IO.File]::WriteAllBytes("$stem.json", (New-Object System.Text.UTF8Encoding $false).GetBytes($json))
    cmd /c "type `"$stem.json`" | powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$hook`" > `"$stem.out`" 2> `"$stem.err`""
    $code = $LASTEXITCODE
    $out = if (Test-Path "$stem.out") { [System.IO.File]::ReadAllText("$stem.out", [System.Text.UTF8Encoding]::new($false)) } else { '' }
    $rewrite = $null
    if ($out.Trim()) {
        # Не JSON на stdout — это провал теста, а не падение прогона.
        try { $rewrite = ($out | ConvertFrom-Json).hookSpecificOutput.updatedToolOutput } catch { $rewrite = $null }
    }
    # Форму ответа проверяет свой тест; остальным нужен текст сводки.
    $summary = if ($rewrite -is [string]) { $rewrite } else { $rewrite.stdout }
    return [pscustomobject]@{ Code = $code; Raw = $out; Summary = $summary; Rewrite = $rewrite }
}

function New-Noise {
    param([int]$Lines = 60)
    (1..$Lines | ForEach-Object { "  Discovering tests in assembly chunk $_ ..." }) -join "`n"
}

$greenDotnet = @(
    '  Determining projects to restore...',
    '  All projects are up-to-date for restore.',
    '  DateParse.Core -> C:\Proj\DateParse\DateParse.Core\bin\Debug\net8.0\DateParse.Core.dll',
    '  DateParse.Tests -> C:\Proj\DateParse\DateParse.Tests\bin\Debug\net8.0\DateParse.Tests.dll',
    'Test run for C:\Proj\DateParse\DateParse.Tests\bin\Debug\net8.0\DateParse.Tests.dll (.NETCoreApp,Version=v8.0)',
    'Microsoft (R) Test Execution Command Line Tool Version 17.8.0 (x64)',
    'Copyright (c) Microsoft Corporation.  All rights reserved.',
    '',
    'Starting test execution, please wait...',
    'A total of 1 test files matched the specified pattern.',
    (New-Noise 60),
    '',
    'Passed!  - Failed:     0, Passed:    56, Skipped:     0, Total:    56, Duration: 1 s - DateParse.Tests.dll (net8.0)'
) -join "`n"

# --- Цикл 1: молчание там, где резать нечего, и сводка зелёного прогона ---

$r = Invoke-Hook -Command 'dotnet test' -Stdout $greenDotnet -ToolName 'Read'
Check 'молчит на чужом инструменте' ($r.Code -eq 0 -and -not $r.Raw.Trim())

$r = Invoke-Hook -Command 'dotnet build -c Release' -Stdout $greenDotnet
Check 'молчит на нетестовой команде' ($r.Code -eq 0 -and -not $r.Raw.Trim())

$r = Invoke-Hook -Command 'dotnet test' -Stdout "Passed!  - Failed:     0, Passed:    2, Total:    2 - X.dll (net8.0)"
Check 'молчит на коротком выводе' ($r.Code -eq 0 -and -not $r.Raw.Trim())

$sp = Join-Path $tmp 'scratch'
New-Item -ItemType Directory -Path $sp -Force | Out-Null
$r = Invoke-Hook -Command 'dotnet test' -Stdout $greenDotnet -Scratchpad $sp
Check 'зелёный dotnet: сводка отдана' ([bool]$r.Summary)
Check 'зелёный dotnet: итоговая строка на месте' ($r.Summary -match 'Passed!\s+- Failed:\s+0, Passed:\s+56')
Check 'зелёный dotnet: строки собранных проектов на месте' ($r.Summary -match 'DateParse\.Tests -> .*DateParse\.Tests\.dll')
Check 'зелёный dotnet: шум вырезан' ($r.Summary -and $r.Summary -notmatch 'Discovering tests in assembly')
$logPath = if ($r.Summary -match '(?m)^Полный вывод: (.+?) \(') { $Matches[1] } else { $null }
Check 'зелёный dotnet: путь к полному выводу в сводке' ([bool]$logPath)
Check 'зелёный dotnet: файл полного вывода лежит в scratchpad' ($logPath -and $logPath.StartsWith($sp))
Check 'зелёный dotnet: файл хранит исходный вывод целиком' ($logPath -and (Test-Path $logPath) -and ([System.IO.File]::ReadAllText($logPath, [System.Text.UTF8Encoding]::new($false)).Contains('Discovering tests in assembly chunk 60')))
Check 'зелёный dotnet: сводка короче исходника' ($r.Summary -and $r.Summary.Length -lt $greenDotnet.Length)

# --- Цикл 2: красный прогон и провал сборки ---

$redDotnet = @(
    '  DateParse.Tests -> C:\Proj\DateParse\DateParse.Tests\bin\Debug\net8.0\DateParse.Tests.dll',
    'Starting test execution, please wait...',
    (New-Noise 40),
    '  Failed DateParse.Tests.ParseTests.ParsesIso [12 ms]',
    '  Error Message:',
    '   Assert.Equal() Failure: неверный разбор «вчера»',
    'Expected: 2026-09-14',
    'Actual:   2026-09-15',
    '  Stack Trace:',
    '     at DateParse.Tests.ParseTests.ParsesIso() in C:\Proj\DateParse\DateParse.Tests\ParseTests.cs:line 42',
    '',
    '  Failed DateParse.Tests.ParseTests.ParsesRu [3 ms]',
    '  Error Message:',
    '   Assert.True() Failure: value was false',
    '  Stack Trace:',
    '     at DateParse.Tests.ParseTests.ParsesRu() in C:\Proj\DateParse\DateParse.Tests\ParseTests.cs:line 77',
    '',
    'Failed!  - Failed:     2, Passed:    54, Skipped:     0, Total:    56, Duration: 1 s - DateParse.Tests.dll (net8.0)'
) -join "`n"

$r = Invoke-Hook -Command 'cd C:\Proj\DateParse && dotnet test' -Stdout $redDotnet -ExitCode 1 -Scratchpad $sp
Check 'красный dotnet: сводка отдана' ([bool]$r.Summary)
Check 'красный dotnet: имена всех падений на месте' ($r.Summary -match 'Failed DateParse\.Tests\.ParseTests\.ParsesIso' -and $r.Summary -match 'Failed DateParse\.Tests\.ParseTests\.ParsesRu')
Check 'красный dotnet: диагностика первого падения на месте' ($r.Summary -match 'Assert\.Equal\(\) Failure' -and $r.Summary -match 'ParseTests\.cs:line 42')
Check 'красный dotnet: стек второго падения вырезан' ($r.Summary -and $r.Summary -notmatch 'ParseTests\.cs:line 77')
Check 'красный dotnet: итоговая строка на месте' ($r.Summary -match 'Failed!\s+- Failed:\s+2')
Check 'красный dotnet: шум вырезан' ($r.Summary -and $r.Summary -notmatch 'Discovering tests in assembly')
Check 'красный dotnet: кириллица в диагностике цела' ($r.Summary -match 'неверный разбор')

$buildFail = @(
    '  Determining projects to restore...',
    (New-Noise 40),
    'C:\Proj\DateParse\DateParse.Core\Parser.cs(17,9): error CS0103: The name ''foo'' does not exist in the current context [C:\Proj\DateParse\DateParse.Core\DateParse.Core.csproj]',
    '',
    'Build FAILED.',
    '    0 Warning(s)',
    '    1 Error(s)'
) -join "`n"

$r = Invoke-Hook -Command 'dotnet test' -Stdout $buildFail -ExitCode 1 -Scratchpad $sp
Check 'провал сборки: строка ошибки компилятора на месте' ($r.Summary -match 'error CS0103')
Check 'провал сборки: вердикт сборки на месте' ($r.Summary -match 'Build FAILED\.')
Check 'провал сборки: шум вырезан' ($r.Summary -and $r.Summary -notmatch 'Discovering tests in assembly')

$r = Invoke-Hook -Command 'dotnet test' -Stdout $greenDotnet -Stderr 'MSBUILD : warning MSB4078: файл проекта старого формата' -Scratchpad $sp
$logPath = if ($r.Summary -match '(?m)^Полный вывод: (.+?) \(') { $Matches[1] } else { $null }
Check 'stderr сохранён в файле полного вывода' ($logPath -and (Test-Path $logPath) -and ([System.IO.File]::ReadAllText($logPath, [System.Text.UTF8Encoding]::new($false)).Contains('MSB4078')))

# --- Цикл 3: node --test, npm test, отказ от подмены, запасная папка ---

function New-TapNoise {
    param([int]$From, [int]$Count)
    (($From)..($From + $Count - 1) | ForEach-Object { "ok $_ - вспомогательный тест $_" }) -join "`n"
}

$redNode = @(
    'TAP version 13',
    (New-TapNoise 1 45),
    '# Subtest: parses iso',
    'not ok 46 - parses iso',
    '  ---',
    "  location: 'C:\Proj\ClaudeOps\scripts\parse.test.js:5:1'",
    '  failureType: ''testCodeFailure''',
    '  error: |-',
    '    Expected values to be strictly equal:',
    "  code: 'ERR_ASSERTION'",
    '  stack: |-',
    '    TestContext.<anonymous> (C:\Proj\ClaudeOps\scripts\parse.test.js:6:3)',
    '  ...',
    '# Subtest: parses ru',
    'not ok 47 - parses ru',
    '  ---',
    '  stack: |-',
    '    TestContext.<anonymous> (C:\Proj\ClaudeOps\scripts\parse.test.js:21:3)',
    '  ...',
    '1..47',
    '# tests 47',
    '# pass 45',
    '# fail 2',
    '# duration_ms 120'
) -join "`n"

$r = Invoke-Hook -Command 'node --test scripts/' -Stdout $redNode -ExitCode 1 -Scratchpad $sp
Check 'красный node: имена всех падений на месте' ($r.Summary -match 'not ok 46 - parses iso' -and $r.Summary -match 'not ok 47 - parses ru')
Check 'красный node: диагностика первого падения на месте' ($r.Summary -match 'ERR_ASSERTION' -and $r.Summary -match 'parse\.test\.js:6:3')
Check 'красный node: стек второго падения вырезан' ($r.Summary -and $r.Summary -notmatch 'parse\.test\.js:21:3')
Check 'красный node: итоги прогона на месте' ($r.Summary -match '(?m)^# fail 2$' -and $r.Summary -match '(?m)^# tests 47$')
Check 'красный node: прошедшие тесты вырезаны' ($r.Summary -and $r.Summary -notmatch 'вспомогательный тест')

$greenNode = @('TAP version 13', (New-TapNoise 1 50), '1..50', '# tests 50', '# pass 50', '# fail 0', '# duration_ms 90') -join "`n"
$r = Invoke-Hook -Command 'npm test' -Stdout $greenNode -Scratchpad $sp
Check 'зелёный npm: итоги прогона на месте' ($r.Summary -match '(?m)^# pass 50$' -and $r.Summary -match '(?m)^# fail 0$')
Check 'зелёный npm: прошедшие тесты вырезаны' ($r.Summary -and $r.Summary -notmatch 'вспомогательный тест')

# Вывод, где каждая строка несёт вердикт: сводка вышла бы длиннее исходника.
$allSignal = (1..45 | ForEach-Object { "  Failed DateParse.Tests.ParseTests.Case$_ [1 ms]" }) -join "`n"
$r = Invoke-Hook -Command 'dotnet test' -Stdout $allSignal -ExitCode 1 -Scratchpad $sp
Check 'молчит, когда сводка не короче исходника' ($r.Code -eq 0 -and -not $r.Raw.Trim())

$r = Invoke-Hook -Command 'dotnet test' -Stdout $greenDotnet
$logPath = if ($r.Summary -match '(?m)^Полный вывод: (.+?) \(') { $Matches[1] } else { $null }
Check 'без scratchpad полный вывод уходит в TEMP' ($logPath -and $logPath.StartsWith($env:TEMP))

# --- Цикл 4: spec-репортёр node 24 (формат снят с настоящего прогона) ---

$redSpec = @(
    ((1..40 | ForEach-Object { "✔ вспомогательный тест $_ (0.2$($_)ms)" }) -join "`n"),
    '✖ первый падающий (1.8157ms)',
    '✖ второй падающий (0.2374ms)',
    '✔ проходит (0.2496ms)',
    'ℹ tests 43',
    'ℹ suites 0',
    'ℹ pass 41',
    'ℹ fail 2',
    'ℹ duration_ms 117.4995',
    '',
    '✖ failing tests:',
    '',
    'test at scripts\red.test.js:3:1',
    '✖ первый падающий (1.8157ms)',
    '  AssertionError [ERR_ASSERTION]: Expected values to be strictly equal:',
    '',
    "  'вчера' !== 'сегодня'",
    '',
    '      at TestContext.<anonymous> (C:\Proj\ClaudeOps\scripts\red.test.js:3:40)',
    '    code: ''ERR_ASSERTION'',',
    '  }',
    '',
    'test at scripts\red.test.js:4:1',
    '✖ второй падающий (0.2374ms)',
    '  AssertionError [ERR_ASSERTION]: второй провал',
    '      at TestContext.<anonymous> (C:\Proj\ClaudeOps\scripts\red.test.js:4:40)',
    '  }'
) -join "`n"

$r = Invoke-Hook -Command 'node --test scripts/' -Stdout $redSpec -ExitCode 1 -Scratchpad $sp
Check 'красный spec: имена всех падений на месте' ($r.Summary -match '✖ первый падающий' -and $r.Summary -match '✖ второй падающий')
Check 'красный spec: счётчики прогона на месте' ($r.Summary -match '(?m)^ℹ tests 43$' -and $r.Summary -match '(?m)^ℹ fail 2$')
Check 'красный spec: диагностика первого падения на месте' ($r.Summary -match 'ERR_ASSERTION' -and $r.Summary -match 'red\.test\.js:3:40')
Check 'красный spec: место первого падения названо' ($r.Summary -match 'test at scripts\\red\.test\.js:3:1')
Check 'красный spec: стек второго падения вырезан' ($r.Summary -and $r.Summary -notmatch 'red\.test\.js:4:40')
Check 'красный spec: прошедшие тесты вырезаны' ($r.Summary -and $r.Summary -notmatch 'вспомогательный тест')

$greenSpec = @(
    ((1..40 | ForEach-Object { "✔ вспомогательный тест $_ (0.2$($_)ms)" }) -join "`n"),
    'ℹ tests 40',
    'ℹ suites 0',
    'ℹ pass 40',
    'ℹ fail 0',
    'ℹ duration_ms 256.5292'
) -join "`n"

$r = Invoke-Hook -Command 'npm test' -Stdout $greenSpec -Scratchpad $sp
Check 'зелёный spec: счётчики прогона на месте' ($r.Summary -match '(?m)^ℹ pass 40$' -and $r.Summary -match '(?m)^ℹ fail 0$')
Check 'зелёный spec: прошедшие тесты вырезаны' ($r.Summary -and $r.Summary -notmatch 'вспомогательный тест')

# --- Цикл 5: форма ответа. Claude Code сверяет updatedToolOutput со схемой
# вывода инструмента и молча откатывает rewrite, если форма не та: у Bash
# вывод — объект { stdout, stderr, interrupted, isImage }, а не строка. ---
$r = Invoke-Hook -Command 'dotnet test' -Stdout $greenDotnet -Stderr 'MSB3277: конфликт версий' -Scratchpad $sp
Check 'ответ — объект вывода Bash, а не строка' ($r.Rewrite -and $r.Rewrite -isnot [string])
Check 'сводка лежит в поле stdout' ($r.Rewrite.stdout -match 'Passed!')
Check 'stderr не дублирует сводку' ($r.Rewrite.stderr -eq '')
Check 'флаги вывода на месте' ($r.Rewrite.PSObject.Properties.Name -contains 'interrupted' -and $r.Rewrite.PSObject.Properties.Name -contains 'isImage')

# --- Цикл 6: русский SDK. dotnet test печатает вердикт на языке системы, и
# английские шаблоны его не видят: тогда сводка пуста и хук молчит. ---
$greenRu = @(
    '  Определение проектов для восстановления...',
    '  Восстановлен C:\Proj\DateParse\DateParse.Core\DateParse.Core.csproj (за 340 мс).',
    '  DateParse.Tests -> C:\Proj\DateParse\DateParse.Tests\bin\Debug\net47\DateParse.Tests.dll',
    'Тестовый запуск для C:\Proj\DateParse\DateParse.Tests\bin\Debug\net47\DateParse.Tests.dll (.NETFramework,Version=v4.7)',
    'Общее количество тестовых файлов (1), соответствующих указанному шаблону.',
    (New-Noise 60),
    'Пройден!   : не пройдено     0, пройдено   140, пропущено     0, всего   140, длительность 560 ms. - DateParse.Tests.dll (net47)'
) -join "`n"

$r = Invoke-Hook -Command 'dotnet test' -Stdout $greenRu -Scratchpad $sp
Check 'русский зелёный: вердикт прогона на месте' ($r.Summary -match 'Пройден!\s+: не пройдено\s+0')
Check 'русский зелёный: шум восстановления вырезан' ($r.Summary -and $r.Summary -notmatch 'Discovering tests')

$redRu = @(
    '  Определение проектов для восстановления...',
    (New-Noise 60),
    '  Не пройден Splits_by_whitespace_and_lowercases [223 ms]',
    '  Сообщение об ошибке:',
    '   Сбой CollectionAssert.AreEqual. Элемент по индексу 1 не совпадает.',
    'Ожидается: а',
    'Фактическое значение: е',
    'Не пройден!: не пройдено     1, пройдено   139, пропущено     0, всего   140, длительность 733 ms. - DateParse.Tests.dll (net47)'
) -join "`n"

$r = Invoke-Hook -Command 'dotnet test' -Stdout $redRu -ExitCode 1 -Scratchpad $sp
Check 'русский красный: имя упавшего теста на месте' ($r.Summary -match 'Не пройден Splits_by_whitespace_and_lowercases')
Check 'русский красный: причина падения на месте' ($r.Summary -match 'Элемент по индексу 1 не совпадает')
Check 'русский красный: вердикт прогона на месте' ($r.Summary -match 'Не пройден!: не пройдено\s+1')
Check 'русский красный: шум восстановления вырезан' ($r.Summary -and $r.Summary -notmatch 'Discovering tests')

# --- Цикл 7: обрезанный прогон. В хук приходит вывод, уже урезанный потолком
# bashOutputMaxChars, и у длинного прогона вердикт остаётся за обрезом: сводка
# из одних сборочных строк читается как зелёная. Это должно быть сказано. ---
$cutDotnet = @(
    '  Определение проектов для восстановления...',
    '  DateParse.Tests -> C:\Proj\DateParse\DateParse.Tests\bin\Debug\net47\DateParse.Tests.dll',
    (New-Noise 60),
    '  Пройден Parses_compound_numerals [< 1 ms]'
) -join "`n"

$r = Invoke-Hook -Command 'dotnet test -v n' -Stdout $cutDotnet -Scratchpad $sp
Check 'обрезанный прогон: сказано, что вердикта нет' ($r.Summary -match 'вердикт прогона не найден')
Check 'обрезанный прогон: сборочные строки остались' ($r.Summary -match 'DateParse\.Tests\.dll')

# У прогона с вердиктом оговорки быть не должно: она обесценится.
$r = Invoke-Hook -Command 'dotnet test' -Stdout $greenDotnet -Scratchpad $sp
Check 'целый прогон: оговорки нет' ($r.Summary -and $r.Summary -notmatch 'вердикт прогона не найден')

Write-Host ''
if ($failed -eq 0) { Write-Host "Все проверки пройдены"; Remove-Item -Recurse -Force $tmp; exit 0 }
Write-Host "Провалено проверок: $failed"
exit 1
