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

    $secretsPath = Get-TgApproveSecretsPath
    if (-not $secretsPath) { exit 0 }
    $secrets = Get-Content -LiteralPath $secretsPath -Raw | ConvertFrom-Json

    Remove-StaleApproveStates
    # A new permission prompt in this session means any older pending one was
    # already resolved (a local deny leaves no hook event, so this is the only
    # signal to retire its watcher and strip its stale Telegram buttons).
    Complete-ApproveStatesForSession -SessionId $hook.session_id -OlderThanSeconds 3

    $projectCtx = Get-ProjectContext -Hook $hook -Secrets $secrets
    $summary = Get-ToolSummary -Hook $hook

    # Auto-approve window active (set from the phone via the bot's /auto)?
    # Then answer the permission question right here with "allow" - verified
    # empirically 2026-07-14 that a PreToolUse allow IS honored by the VS Code
    # extension, so the native dialog never appears at all. That's why this
    # path needs no keystroke injection (and can't steal focus) unlike the
    # phone-answer flow in watch-and-inject.ps1.
    #
    # The trade-off this buys: an allow here suppresses PermissionRequest
    # entirely, so nothing downstream can tell which calls WOULD have prompted
    # versus which the allowlist would have passed silently. That's exactly why
    # the notification is a rolling digest rather than a message per call - one
    # message per matched tool call would mean hundreds an hour.
    if (Get-AutoApproveActive -Secrets $secrets) {
        Write-ApproveState -ToolUseId $toolUseId -State @{
            status        = 'auto'
            project       = $projectCtx.Display
            raw_project   = $projectCtx.Raw
            summary       = $summary
            digest_label  = Get-CompactToolLabel -Hook $hook
            tool_name     = $hook.tool_name
            corr_key      = Get-ToolCorrelationKey -ToolInput $hook.tool_input
            session_id    = [string]$hook.session_id
            created       = [int][double]::Parse((Get-Date -UFormat %s))
        }
        # Watcher posts the digest line; doing it here would add an HTTP
        # round-trip to every single tool call before it may proceed.
        $watcher = Join-Path $PSScriptRoot 'watch-and-inject.ps1'
        Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$watcher`"", "`"$toolUseId`""
        ) | Out-Null

        Write-HookOutput -Text (@{
            hookSpecificOutput = @{
                hookEventName      = 'PreToolUse'
                permissionDecision = 'allow'
            }
        } | ConvertTo-Json -Compress -Depth 5)
        exit 0
    }

    Write-ApproveState -ToolUseId $toolUseId -State @{
        status      = 'pending'
        project     = $projectCtx.Display
        raw_project = $projectCtx.Raw
        summary     = $summary
        tool_name   = $hook.tool_name
        corr_key    = Get-ToolCorrelationKey -ToolInput $hook.tool_input
        session_id  = [string]$hook.session_id
        created     = [int][double]::Parse((Get-Date -UFormat %s))
    }

    # Cost / trade-off worth knowing: this spawns a hidden watcher process on
    # EVERY matched tool call (Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|
    # WebFetch). For allowlisted / auto-approved calls no PermissionRequest ever
    # fires, so the watcher sends nothing to Telegram - it just waits up to
    # promptWaitBudgetSec (15s, defined in watch-and-inject.ps1) and exits. On a
    # busy session that's a steady stream of short-lived background processes.
    # It's the accepted price of racing the native dialog: PreToolUse can't know
    # up front whether a call is allowlisted, so it must arm a watcher for all.
    $watcher = Join-Path $PSScriptRoot 'watch-and-inject.ps1'
    Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$watcher`"", "`"$toolUseId`""
    ) | Out-Null
} catch {
    # Fall back to a normal local prompt on any failure.
}

exit 0
