# PreToolUse hook (matcher Read): denies reading a long file whole and tells the
# agent to read a range instead. The rule "big logs and foreign code mirrors go
# through grep, only summaries into context" lives in CLAUDE.md, but a rule is a
# hope; pause-guard and context-budget showed that only what cannot be
# rationalised actually holds. Pattern: shunt from spotify/portal-ai-plugins.
# Why it pays: each turn is billed for the whole accumulated context, so a file
# pulled in on turn 10 of 40 is paid for thirty times (docs/costs.md). The
# measurement behind the threshold is in docs/decisions/2026-09-14-read-gate.md:
# above 350 lines a read leads to an Edit of that file one time in five, so a
# summary or a grep-located range is enough almost always.
# Window = min(limit or 2000, lines left from offset); at or below the threshold
# the hook stays silent. The same gate applies inside subagents: that is where
# nearly all whole-file reads happen.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')

$MaxLines = 350          # calibrated on own transcripts, see the decision note
$SkipBelowBytes = 16384  # ≈4k tokens: cheap to read whole whatever the line count, so no line counting
$ReadDefaultLimit = 2000 # what Read takes when limit is not given
$CountCap = 20000        # lines counted past offset before giving up: the verdict is deny long before, and a 500 MB log must not hit the 10 s hook timeout
$BinaryExt = '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.pdf'
# Оглавление в отказе: замер 2026-09-18 показал, что после половины отказов
# уходит отдельный ход на grep -n, лишь бы найти строки (decisions/2026-09-18-read-gate-remeasure.md).
$MaxToc = 40             # записей: дальше оглавление само стоит дороже сэкономленного хода
$TocLineMax = 90         # знаков в записи
$DeclRe = '^\s*(#{1,6}\s+\S|(export\s+)?(async\s+)?function\s+[\w-]|(export\s+)?class\s+[\w-]|(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s*)?(\(|function|\w+\s*=>)|(public|private|protected|internal)\s+[\w<>\[\],\s]+\s\w+\s*\(|def\s+\w+|(test|describe|it)\s*\(|\[Test|param\s*\()'

# UTF-8 on stdin, not the console codepage: paths may carry Cyrillic.
$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
$raw = $reader.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }
# Checked here and not only by the matcher: widen the matcher by accident and
# every tool with a file_path would be gated.
if ($j.hook_event_name -ne 'PreToolUse' -or $j.tool_name -ne 'Read') { exit 0 }
$in = $j.tool_input
$path = $in.file_path
if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { exit 0 }  # Read reports the error itself
if ($in.pages) { exit 0 }
if ($BinaryExt -contains [IO.Path]::GetExtension($path).ToLowerInvariant()) { exit 0 }

$size = (Get-Item -LiteralPath $path).Length
if ($size -lt $SkipBelowBytes) { exit 0 }

$limit = if ($in.limit) { [int]$in.limit } else { $ReadDefaultLimit }
if ($limit -le $MaxLines) { exit 0 }
$offset = if ($in.offset -and [int]$in.offset -gt 1) { [int]$in.offset } else { 1 }

$total = 0
$cap = $offset + $CountCap
$toc = New-Object System.Collections.ArrayList
foreach ($line in [IO.File]::ReadLines($path)) {
    $total++
    if ($total -ge $offset -and $line -match $DeclRe) {
        $t = $line.Trim()
        if ($t.Length -gt $TocLineMax) { $t = $t.Substring(0, $TocLineMax) }
        [void]$toc.Add("${total}: $t")
    }
    if ($total -ge $cap) { break }
}
$window = [Math]::Min($limit, $total - $offset + 1)
if ($window -le $MaxLines) { exit 0 }

$ktok = [string]::Format([cultureinfo]::InvariantCulture, '{0:0.0}', $size / 4000)
$shown = if ($total -ge $cap) { "более $CountCap" } else { "$total" }
$msg = "${path}: $shown строк, ≈${ktok}k токенов, порог $MaxLines строк за одно чтение. Нужное место — Read с offset/limit до $MaxLines строк; чего нет в оглавлении — grep -n по файлу. Обзор файла целиком — сабагент Explore или Haiku, в контекст только отчёт."
if ($toc.Count -gt 0) {
    $shownToc = $toc
    # Длинный файл прореживается равномерно: карта всего файла полезнее, чем его начало.
    if ($toc.Count -gt $MaxToc) {
        $step = [Math]::Ceiling($toc.Count / $MaxToc)
        $shownToc = @(for ($i = 0; $i -lt $toc.Count; $i += $step) { $toc[$i] })
        $shownToc[$shownToc.Count - 1] = $toc[$toc.Count - 1]
    }
    $head = if ($shownToc.Count -lt $toc.Count) { "Оглавление ($($shownToc.Count) из $($toc.Count) объявлений)" } else { "Оглавление ($($toc.Count) объявлений)" }
    $msg += "`n${head}:`n" + ($shownToc -join "`n")
}
ConvertTo-AsciiJson @{ hookSpecificOutput = @{ hookEventName = 'PreToolUse'; permissionDecision = 'deny'; permissionDecisionReason = $msg } }
exit 0
