# PreToolUse hook (registered with matcher
# "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|WebFetch"): writes a 'pending'
# state file and spawns a detached watcher (watch-and-inject.ps1), then emits
# NOTHING - the normal permission flow decides whether a dialog is needed, so
# the settings.json allowlist keeps working. If a dialog does appear,
# notify-telegram.ps1's PermissionRequest branch flips the state to 'prompting'
# and only then does the watcher send the Telegram ask and start racing the
# dialog. posttooluse-mark-answered.ps1 tells the watcher to stand down if the
# local dialog wins (or the tool was auto-approved and simply ran).
#
# Kill switch: set $env:TG_APPROVE_OFF to skip entirely (normal local prompt).
# Must return fast - only spawns a process, never blocks.

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\hook-common.ps1"

try {
    if ($env:TG_APPROVE_OFF) { exit 0 }

    $stdin = Read-HookStdin
    if (-not $stdin) { exit 0 }

    $hook = $stdin | ConvertFrom-Json
    $toolUseId = $hook.tool_use_id
    if (-not $toolUseId) { exit 0 }

    if (-not (Get-TgApproveSecretsPath)) { exit 0 }

    Remove-StaleApproveStates
    # A new permission prompt in this session means any older pending one was
    # already resolved (a local deny leaves no hook event, so this is the only
    # signal to retire its watcher and strip its stale Telegram buttons).
    Complete-ApproveStatesForSession -SessionId $hook.session_id -OlderThanSeconds 3

    $project = 'unknown'
    if ($hook.cwd) { $project = Split-Path -Leaf $hook.cwd }
    $project = Format-HtmlEscape "$project [$env:COMPUTERNAME]"
    $summary = Get-ToolSummary -Hook $hook

    Write-ApproveState -ToolUseId $toolUseId -State @{
        status     = 'pending'
        project    = $project
        summary    = $summary
        tool_name  = $hook.tool_name
        corr_key   = Get-ToolCorrelationKey -ToolInput $hook.tool_input
        session_id = [string]$hook.session_id
        created    = [int][double]::Parse((Get-Date -UFormat %s))
    }

    $watcher = Join-Path $PSScriptRoot 'watch-and-inject.ps1'
    Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$watcher`"", "`"$toolUseId`""
    ) | Out-Null
} catch {
    # Fall back to a normal local prompt on any failure.
}

exit 0
