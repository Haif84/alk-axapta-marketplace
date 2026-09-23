# Stop hook: two reminders about the end-of-session ritual, each at most once
# per session — uncommitted changes, and a handoff (.remember/remember.md) that
# this session never refreshed. Both live here rather than in separate hooks so
# the Stop event spawns one powershell, not two, and so the user gets one
# message instead of two in the same turn.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')
$raw = [Console]::In.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }
$sid = $j.session_id
$threshold = 8
$handoffAfterMinutes = 45
$parts = @()

# Session clock: the first Stop of a session drops this marker, so its age is
# how long the session has been running. There is no SessionStart marker to
# read here, and the handoff reminder must not fire in the first minutes of a
# session, when nothing worth writing down has happened yet.
$clock = Join-Path $env:TEMP ("claude-session-clock-{0}.flag" -f $sid)
if (-not (Test-Path $clock)) { New-Item -ItemType File -Path $clock -Force | Out-Null }
$clockStart = (Get-Item -LiteralPath $clock).CreationTime

$inside = (git rev-parse --is-inside-work-tree 2>$null)
if ($LASTEXITCODE -eq 0 -and $inside -eq "true") {
    $count = @(git status --porcelain 2>$null).Count
    $marker = Join-Path $env:TEMP ("claude-commit-reminder-{0}.flag" -f $sid)
    if ($count -ge $threshold -and -not (Test-Path $marker)) {
        New-Item -ItemType File -Path $marker -Force | Out-Null
        $parts += "$count незакоммиченных изменений в рабочем дереве. Не забудь закоммитить (один коммит = одна задача)."
    }
}

# Handoff staleness. remember.md is written only by an explicit /remember —
# the plugin's own SessionEnd hook flushes now.md and deliberately never
# writes a handoff, so nothing but the user closes this gap.
if ($j.cwd -and ((Get-Date) - $clockStart).TotalMinutes -ge $handoffAfterMinutes) {
    $marker = Join-Path $env:TEMP ("claude-remember-reminder-{0}.flag" -f $sid)
    if (-not (Test-Path $marker)) {
        $handoff = Join-Path $j.cwd ".remember\remember.md"
        $f = Get-Item -LiteralPath $handoff
        if (-not $f -or $f.LastWriteTime -lt $clockStart) {
            New-Item -ItemType File -Path $marker -Force | Out-Null
            $parts += "Хендофф .remember/remember.md не обновлялся в этой сессии. Перед закрытием — /remember."
        }
    }
}

if ($parts.Count -eq 0) { exit 0 }
ConvertTo-AsciiJson @{ systemMessage = ("Напоминание: " + ($parts -join " ")) }
exit 0
