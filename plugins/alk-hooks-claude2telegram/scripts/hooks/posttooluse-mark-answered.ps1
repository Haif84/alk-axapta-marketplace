# PostToolUse hook (registered with matcher
# "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|WebFetch"): fires only after a tool
# call actually executes, i.e. permission was already granted through SOME
# path (usually the local dialog winning the race). Marks the matching
# pending state "answered" so watch-and-inject.ps1 knows not to inject a
# redundant/stale keystroke.

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\hook-common.ps1"

try {
    $stdin = Read-HookStdin
    if (-not $stdin) { exit 0 }

    $hook = $stdin | ConvertFrom-Json
    $toolUseId = $hook.tool_use_id
    if (-not $toolUseId) { exit 0 }

    $statePath = Get-ApproveStatePath -ToolUseId $toolUseId
    if (Test-Path $statePath) {
        Update-ApproveStateStatus -Path $statePath -Status 'answered'
    }
} catch {
}

exit 0
