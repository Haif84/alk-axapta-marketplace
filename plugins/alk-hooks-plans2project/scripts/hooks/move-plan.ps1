# Move recent plan files from ~/.claude/plans/ to <cwd>/plans/.
# Triggered by PostToolUse hook on ExitPlanMode (see ~/.claude/settings.json).
# Reads cwd from stdin JSON (Claude Code hook protocol).

$ErrorActionPreference = 'Stop'

$stdin = [Console]::In.ReadToEnd()
$cwd = $null
if ($stdin) {
    try {
        $hook = $stdin | ConvertFrom-Json
        $cwd = $hook.cwd
    } catch {
        exit 0
    }
}
if (-not $cwd -or -not (Test-Path $cwd)) { exit 0 }

$src = Join-Path $env:USERPROFILE '.claude\plans'
$dst = Join-Path $cwd 'plans'
if (-not (Test-Path $src)) { exit 0 }

if (Test-Path $dst) {
    $srcResolved = (Resolve-Path $src).Path
    $dstResolved = (Resolve-Path $dst).Path
    if ($srcResolved -ieq $dstResolved) { exit 0 }
}

New-Item -ItemType Directory -Force -Path $dst | Out-Null

$cutoff = (Get-Date).AddMinutes(-60)
Get-ChildItem -Path $src -File |
  Where-Object { $_.Extension -in '.md', '.pdf' -and $_.LastWriteTime -gt $cutoff } |
  ForEach-Object {
    $target = Join-Path $dst $_.Name
    Move-Item -Path $_.FullName -Destination $target -Force
  }
