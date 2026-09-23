# Тесты install.ps1 на временной домашней папке: боевой ~/.claude не трогается.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install.test.ps1
# Junction снимаются через rmdir до удаления папки: Remove-Item -Recurse в
# PowerShell 5.1 проходит по junction и удалил бы файлы самого плагина.
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$install = Join-Path $PSScriptRoot 'install.ps1'
$root = Split-Path $PSScriptRoot -Parent
$tmp = Join-Path $env:TEMP ('install-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$realHome = $env:USERPROFILE
$failed = 0
$utf8 = New-Object System.Text.UTF8Encoding $false

function New-Home {
    param([string]$ClaudeMd = "# Мои правила`n", [string]$Settings = '{"permissions":{"allow":["Bash(ls)"]}}')
    $h = Join-Path $tmp ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Join-Path $h '.claude') -Force | Out-Null
    if ($ClaudeMd) { [IO.File]::WriteAllText((Join-Path $h '.claude\CLAUDE.md'), $ClaudeMd, $utf8) }
    [IO.File]::WriteAllText((Join-Path $h '.claude\settings.json'), $Settings, $utf8)
    return $h
}

function Invoke-Install {
    param([string]$FakeHome, [switch]$Apply, [string]$Script = $install)
    $env:USERPROFILE = $FakeHome
    try {
        $out = if ($Apply) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Apply 2>&1 }
               else { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script 2>&1 }
        $code = $LASTEXITCODE
    } finally { $env:USERPROFILE = $realHome }
    return [pscustomobject]@{ Out = ($out -join "`n"); Code = $code }
}

function Read-Text([string]$Path) { [IO.File]::ReadAllText($Path) }
function Count([string]$Text, [string]$Sub) { ([regex]::Matches($Text, [regex]::Escape($Sub))).Count }

function Test-Case {
    param([string]$Name, [scriptblock]$Body)
    try { & $Body; Write-Host "PASS  $Name" }
    catch { $script:failed++; Write-Host "FAIL  $Name`n      $($_.Exception.Message)" }
}
function Assert-True { param([bool]$Cond, [string]$Msg) if (-not $Cond) { throw $Msg } }

try {
    Test-Case 'просмотр ничего не пишет' {
        $h = New-Home
        $claudeBefore = Read-Text "$h\.claude\CLAUDE.md"
        $settingsBefore = Read-Text "$h\.claude\settings.json"
        $r = Invoke-Install $h
        Assert-True ($r.Code -eq 0) "код $($r.Code)"
        Assert-True ($r.Out -match 'MISSING junction') 'нет строки о junction'
        Assert-True (-not (Test-Path "$h\.claude\scripts")) 'junction создан без -Apply'
        Assert-True (-not (Test-Path "$h\.claude\agents\explore.md")) 'агент скопирован без -Apply'
        Assert-True ((Read-Text "$h\.claude\CLAUDE.md") -eq $claudeBefore) 'CLAUDE.md изменён без -Apply'
        Assert-True ((Read-Text "$h\.claude\settings.json") -eq $settingsBefore) 'settings.json изменён без -Apply'
    }

    Test-Case 'установка: junction, агент, блок правил, ключи, бэкапы' {
        $h = New-Home
        $r = Invoke-Install $h -Apply
        Assert-True ($r.Code -eq 0) "код $($r.Code): $($r.Out)"
        foreach ($d in 'scripts', 'docs') {
            $item = Get-Item "$h\.claude\$d"
            Assert-True ($item.LinkType -eq 'Junction' -and ($item.Target -contains (Join-Path $root $d))) "$d не junction в плагин"
        }
        Assert-True (Test-Path "$h\.claude\agents\explore.md") 'агент не скопирован'
        $md = Read-Text "$h\.claude\CLAUDE.md"
        Assert-True ($md.StartsWith('# Мои правила')) 'свой текст владельца потерян'
        Assert-True ((Count $md 'alk-llm-economy:begin') -eq 1 -and (Count $md 'alk-llm-economy:end') -eq 1) 'маркеры не по одному'
        Assert-True ($md -match '## LLM economy' -and $md -match '## ALK team baseline') 'в блоке нет одного из разделов'
        Assert-True (@(Get-ChildItem "$h\.claude" -Filter 'CLAUDE.md.bak-*').Count -eq 1) 'нет бэкапа CLAUDE.md'
        $s = Read-Text "$h\.claude\settings.json" | ConvertFrom-Json
        Assert-True ($s.autoCompactWindow -eq 133000) 'ключи фрагмента не влиты'
        Assert-True (@($s.permissions.allow) -contains 'Bash(ls)') 'allowlist владельца потерян'
        Assert-True (@($s.permissions.deny) -contains 'Workflow') 'deny не влит'
    }

    Test-Case 'повторный запуск ничего не меняет' {
        $h = New-Home
        Invoke-Install $h -Apply | Out-Null
        $md = Read-Text "$h\.claude\CLAUDE.md"
        $settings = Read-Text "$h\.claude\settings.json"
        $r = Invoke-Install $h -Apply
        Assert-True ($r.Out -match 'junction ok') 'junction не узнан'
        Assert-True ((Read-Text "$h\.claude\settings.json") -eq $settings) 'settings.json изменился при повторе'
        Assert-True (@(Get-ChildItem "$h\.claude" -Filter 'settings.json.bak-*').Count -eq 1) 'повтор сделал лишний бэкап settings.json'
        Assert-True (@(Get-ChildItem "$h\.claude" -Filter 'CLAUDE.md.bak-*').Count -eq 1) 'повтор сделал лишний бэкап CLAUDE.md'
        Assert-True ((Read-Text "$h\.claude\CLAUDE.md") -eq $md) 'CLAUDE.md изменился при повторе'
    }

    Test-Case 'устаревший блок заменяется, текст вокруг остаётся' {
        $old = "# До`n`n<!-- alk-llm-economy:begin -->`nстарое правило`n<!-- alk-llm-economy:end -->`n`n# После`n"
        $h = New-Home -ClaudeMd $old
        Invoke-Install $h -Apply | Out-Null
        $md = Read-Text "$h\.claude\CLAUDE.md"
        Assert-True ($md -notmatch 'старое правило') 'старый блок остался'
        Assert-True ($md.StartsWith('# До') -and $md.TrimEnd().EndsWith('# После')) 'текст вокруг блока потерян'
        Assert-True ((Count $md 'alk-llm-economy:begin') -eq 1) 'блок задвоился'
    }

    Test-Case 'нет CLAUDE.md — создаётся с блоком' {
        $h = New-Home -ClaudeMd ''
        Invoke-Install $h -Apply | Out-Null
        $md = Read-Text "$h\.claude\CLAUDE.md"
        Assert-True ($md.StartsWith('<!-- alk-llm-economy:begin -->')) 'файл не создан или начинается не с блока'
    }

    Test-Case 'чужая папка scripts — конфликт, содержимое цело' {
        $h = New-Home
        New-Item -ItemType Directory "$h\.claude\scripts" | Out-Null
        'mine' | Out-File "$h\.claude\scripts\my.txt"
        $r = Invoke-Install $h -Apply
        Assert-True ($r.Out -match 'CONFLICT') 'конфликт не назван'
        Assert-True (Test-Path "$h\.claude\scripts\my.txt") 'чужой файл пропал'
        Assert-True ((Get-Item "$h\.claude\scripts").LinkType -ne 'Junction') 'чужая папка подменена junction'
    }

    Test-Case 'хук комплекта в settings.json — предупреждение о задвоении' {
        $h = New-Home -Settings '{"hooks":{"PreToolUse":[{"matcher":"Read","hooks":[{"type":"command","command":"x\\read-gate.ps1"}]}]}}'
        $r = Invoke-Install $h
        Assert-True ($r.Out -match 'DUPLICATE: .*read-gate\.ps1') "задвоение не найдено: $($r.Out)"
    }

    Test-Case 'запуск из кэша плагина — отказ' {
        $h = New-Home
        $cache = Join-Path $tmp 'plugins\cache\alk-axapta\alk-llm-economy\1.0.0\scripts'
        New-Item -ItemType Directory $cache -Force | Out-Null
        Copy-Item $install $cache
        $r = Invoke-Install $h -Apply -Script (Join-Path $cache 'install.ps1')
        Assert-True ($r.Code -eq 1 -and $r.Out -match 'STOP') "из кэша не отказал: $($r.Out)"
        Assert-True (-not (Test-Path "$h\.claude\scripts")) 'из кэша создан junction'
    }
} finally {
    $env:USERPROFILE = $realHome
    Get-ChildItem $tmp -Directory | ForEach-Object {
        foreach ($d in 'scripts', 'docs') {
            $link = Join-Path $_.FullName ".claude\$d"
            if ((Get-Item $link -ErrorAction SilentlyContinue).LinkType -eq 'Junction') { cmd /c rmdir "$link" | Out-Null }
        }
    }
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

if ($failed -gt 0) { Write-Host "`n$failed провалено"; exit 1 }
Write-Host "`nвсе тесты пройдены"
exit 0
