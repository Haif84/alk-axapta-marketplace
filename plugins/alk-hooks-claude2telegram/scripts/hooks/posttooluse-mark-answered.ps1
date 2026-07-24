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
        # 'ran' is set ONLY here, and this hook fires only when the tool actually
        # executed. The status alone can't carry that: Complete-ApproveStatesForSession
        # also writes 'answered' when sweeping a session or retiring a superseded
        # prompt, neither of which means anything ran. The paranoid-mode warning
        # in watch-and-inject.ps1 depends on that distinction.
        Update-ApproveStateStatus -Path $statePath -Status 'answered' -Fields @{ ran = $true }
    }
} catch {
}

exit 0
