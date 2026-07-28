# PostToolUse hook (registered with matcher "*", i.e. every tool - it must cover
# exactly what the PreToolUse matcher covers, or calls it armed a watcher for
# would never be marked as executed): fires only after a tool call actually
# executes, i.e. permission was already granted through SOME path (usually the
# local dialog winning the race). Marks the matching pending state "answered" so
# watch-and-inject.ps1 knows not to inject a redundant/stale keystroke, and writes
# the one log line that proves a call really ran.

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\hook-common.ps1"

try {
    $stdin = Read-HookStdin
    if (-not $stdin) { exit 0 }

    $hook = $stdin | ConvertFrom-Json
    $toolUseId = $hook.tool_use_id
    if (-not $toolUseId) { exit 0 }

    # Read BEFORE the update: the pre-update status is how permission was
    # obtained ('auto' = auto-approved, 'prompting' = a dialog was shown,
    # 'pending' = allowlisted, no dialog at all), which is the single most useful
    # field in the log - and the update below destroys it.
    $state = Read-ApproveState -ToolUseId $toolUseId
    $statePath = Get-ApproveStatePath -ToolUseId $toolUseId
    if (Test-Path $statePath) {
        # 'ran' is set ONLY here, and this hook fires only when the tool actually
        # executed. The status alone can't carry that: Complete-ApproveStatesForSession
        # also writes 'answered' when sweeping a session or retiring a superseded
        # prompt, neither of which means anything ran. The paranoid-mode warning
        # in watch-and-inject.ps1 depends on that distinction.
        Update-ApproveStateStatus -Path $statePath -Status 'answered' -Fields @{ ran = $true }
    }

    # This hook is the only proof a tool really executed, so it logs even with no
    # state file (PreToolUse skipped the call, or an orphan was already swept).
    $secrets = $null
    try {
        $secretsPath = Get-TgApproveSecretsPath
        if ($secretsPath) { $secrets = Get-Content -LiteralPath $secretsPath -Raw | ConvertFrom-Json }
    } catch {
    }
    $projectCtx = Get-ProjectContext -Hook $hook -Secrets $secrets
    # A missing state file is NOT an anomaly and deliberately isn't flagged as
    # one: on the auto-approve path the watcher deletes the state as soon as it
    # has posted the digest line, which for anything but the fastest tools happens
    # before the tool finishes and this hook fires. So 'via' and 'ms' are simply
    # absent there. A call that truly ran without approve-flow coverage is still
    # visible - it has a post.ran line with no pre.* line for the same tuid.
    $ms = $null
    $via = $null
    if ($state) {
        $via = [string]$state.status
        if ($state.created_ms) {
            $ms = [int]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - [long]$state.created_ms)
        }
    }
    Write-CallLog -Secrets $secrets -Fields @{
        ev   = 'post'
        res  = 'ran'
        tool = [string]$hook.tool_name
        tuid = [string]$toolUseId
        sid  = [string]$hook.session_id
        proj = $projectCtx.Raw
        mach = (Get-MachineLabel -Secrets $secrets)
        det  = (Get-ToolLogDetail -Hook $hook)
        via  = $via
        ms   = $ms
    }

    # Log rotation lives here rather than in PreToolUse (which blocks every tool
    # call before it may proceed) or in the watcher (which is not spawned at all
    # when the relay endpoints it needs are missing, so rotation would silently
    # stop happening). By this point the tool has already run, and the throttle
    # stamp means the actual directory sweep happens at most once every 6 hours.
    Remove-StaleCallLogs -Secrets $secrets
} catch {
}

exit 0
