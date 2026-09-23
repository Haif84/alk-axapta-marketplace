# install.ps1 — ставит в ~/.claude то, что плагин alk-llm-economy не может подключить сам.
# Хуки плагин подключает сам (hooks/hooks.json); здесь — остальное:
#   junction ~/.claude/scripts и ~/.claude/docs -> папки плагина (на них ссылаются правила),
#   агент Explore на Haiku -> ~/.claude/agents/explore.md,
#   блок правил claude/CLAUDE.economy.md + CLAUDE.baseline.md -> ~/.claude/CLAUDE.md между маркерами,
#   ключи claude/settings.fragment.json -> ~/.claude/settings.json (merge-settings.js).
# Windows PowerShell 5.1. Без -Apply ничего не пишет, только показывает.
# Запускать из клона маркетплейса (~/.claude/plugins/marketplaces/...), не из кэша
# плагина: путь кэша содержит версию и сменится при обновлении, junction осиротеет.
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
# Вывод читает агент через Bash: без UTF-8 кириллица приходит в кодовой странице консоли.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$root  = Split-Path $PSScriptRoot -Parent
$target = Join-Path $env:USERPROFILE '.claude'
$begin  = '<!-- alk-llm-economy:begin -->'
$end    = '<!-- alk-llm-economy:end -->'

if ($root -match '\\plugins\\cache\\') {
    Write-Host "STOP: $root — кэш плагина с версией в пути. Запусти install.ps1 из клона маркетплейса (~/.claude/plugins/marketplaces/<имя>/plugins/alk-llm-economy/scripts)."
    exit 1
}

function Show-Diff($src, $dst) {
    if (-not (Test-Path $dst)) { Write-Host "NEW  $dst"; return $true }
    cmd /c "git diff --no-index --quiet -- `"$dst`" `"$src`" 2>nul" | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "same $dst"; return $false }
    Write-Host "DIFF $dst"
    cmd /c "git --no-pager diff --no-index -- `"$dst`" `"$src`" 2>nul"
    return $true
}

# 1. Junction-ы: правила зовут node ~/.claude/scripts/... и читают ~/.claude/docs/...
foreach ($dir in 'scripts', 'docs') {
    $link = Join-Path $target $dir
    $src  = Join-Path $root $dir
    $item = Get-Item $link -ErrorAction SilentlyContinue
    if ($item -and $item.LinkType -eq 'Junction' -and $item.Target -contains $src) {
        Write-Host "junction ok $link"
    } elseif ($item) {
        Write-Host "CONFLICT $link уже есть и ведёт не сюда ($($item.LinkType) $($item.Target)) — решает владелец, скрипт не трогает"
    } else {
        Write-Host "MISSING junction $link -> $src"
        if ($Apply) { cmd /c mklink /J "$link" "$src" | Out-Null; Write-Host "created" }
    }
}

# 2. Explore на Haiku: пользовательский агент с именем встроенного его подменяет.
$agentSrc = Join-Path $root 'claude\agents\explore.md'
$agentDst = Join-Path $target 'agents\explore.md'
if ((Show-Diff $agentSrc $agentDst) -and $Apply) {
    New-Item -ItemType Directory -Force (Split-Path $agentDst) | Out-Null
    Copy-Item $agentSrc $agentDst -Force; Write-Host "copied $agentDst"
}

# 3. Блок правил в глобальный CLAUDE.md: заменяется между маркерами, остальное не трогается.
$claudeMd = Join-Path $target 'CLAUDE.md'
$rules = foreach ($f in 'CLAUDE.economy.md', 'CLAUDE.baseline.md') { [IO.File]::ReadAllText((Join-Path $root "claude\$f")).TrimEnd() }
$block = "$begin`n" + ($rules -join "`n`n") + "`n$end"
$old = if (Test-Path $claudeMd) { [IO.File]::ReadAllText($claudeMd) } else { '' }
$re = [regex]::Escape($begin) + '[\s\S]*?' + [regex]::Escape($end)
$new = if ($old -match $re) { [regex]::Replace($old, $re, { param($m) $block }) }
       elseif ($old) { $old.TrimEnd() + "`n`n$block`n" } else { "$block`n" }
$tmp = Join-Path $env:TEMP 'alk-llm-economy-CLAUDE.md'
[IO.File]::WriteAllText($tmp, $new, (New-Object System.Text.UTF8Encoding $false))
if ((Show-Diff $tmp $claudeMd) -and $Apply) {
    if (Test-Path $claudeMd) { Copy-Item $claudeMd "$claudeMd.bak-$(Get-Date -Format yyyyMMdd-HHmmss)" }
    Copy-Item $tmp $claudeMd -Force; Write-Host "written $claudeMd"
}

# 4. Ключи settings.json: слияние с резервной копией, allowlist и чужие хуки не трогаются.
$fragment = Join-Path $root 'claude\settings.fragment.json'
$merge = Join-Path $root 'scripts\merge-settings.js'
if ($Apply) { node $merge $fragment } else { node $merge $fragment --dry-run }

# 5. Хуки комплекта, подключённые руками в settings.json, задвоятся с хуками плагина.
$settings = Join-Path $target 'settings.json'
if (Test-Path $settings) {
    $names = (Get-ChildItem (Join-Path $root 'hooks') -Filter *.ps1 | Where-Object { $_.Name -notlike '*.test.ps1' }).Name
    $dups = Select-String -LiteralPath $settings -Pattern ($names | ForEach-Object { [regex]::Escape($_) }) | ForEach-Object { $_.Matches[0].Value } | Sort-Object -Unique
    if ($dups) { Write-Host "DUPLICATE: в settings.json подключены $($dups -join ', ') — плагин подключает их сам, записи из settings.json убрать (решает владелец)" }
}

if (-not $Apply) { Write-Host "`nЭто был просмотр. Запустить с -Apply, чтобы записать." }
exit 0  # git diff --no-index оставляет $LASTEXITCODE=1 при найденных отличиях
