# PreToolUse hook (registered with matcher "*", i.e. EVERY tool - including all
# mcp__* ones, which is the whole point: a name like
# mcp__plugin_playwright_playwright__browser_close matched none of the tool names
# the matcher used to list, so MCP calls never reached this hook and always got
# the native dialog even during an /auto window): writes a 'pending'
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

    # Measures this hook's own contribution to every tool call's latency. With
    # matcher "*" that cost is paid by EVERY call, so it is worth logging rather
    # than guessing about.
    $hookSw = [System.Diagnostics.Stopwatch]::StartNew()

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

    # Fields shared by every log line this hook writes (see Write-CallLog).
    $log = @{
        tuid = [string]$toolUseId
        sid  = [string]$hook.session_id
        tool = [string]$hook.tool_name
        proj = $projectCtx.Raw
        mach = (Get-MachineLabel -Secrets $secrets)
        det  = (Get-ToolLogDetail -Hook $hook)
    }
    $logRes = 'gate'

    # Tools whose permission prompt IS the feature. With matcher "*" they reach
    # this hook for the first time, and answering 'allow' here during an /auto
    # window would accept a plan on the user's behalf (ExitPlanMode) or answer a
    # question meant for them (AskUserQuestion) - the auto-approve window is
    # consent to skip TOOL confirmations, not to speak for the user. TodoWrite is
    # in the list purely as noise: it never needs permission, so arming a watcher
    # for it is pure cost. Log it and get out: no state, no watcher, no decision.
    if (@('ExitPlanMode', 'AskUserQuestion', 'TodoWrite') -contains [string]$hook.tool_name) {
        Write-CallLog -Secrets $secrets -Fields ($log + @{
            ev  = 'pre'
            res = 'skipped'
            ms  = [int]$hookSw.ElapsedMilliseconds
        })
        exit 0
    }

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
    $autoMode = Get-AutoApproveMode -Secrets $secrets

    # Paranoid mode: score the call first and only auto-approve at or below the
    # chosen threshold. This is the one place scoring blocks the tool call - it
    # has to, since the answer decides whether the call proceeds unattended.
    $risk = $null
    $scoreDetail = $null
    if ($autoMode.Mode -eq 'paranoid' -or $autoMode.ScoreAll) {
        $scoreDetail = Get-ToolScoringDetail -Hook $hook
    }
    if ($autoMode.Mode -eq 'paranoid') {
        $risk = Get-RiskScore -Secrets $secrets -ToolName ([string]$hook.tool_name) -Detail $scoreDetail
        if ($null -eq $risk -or $risk.Score -gt $autoMode.Threshold) {
            # No score available, or over the threshold. Either way: do NOT
            # auto-approve. $null is a scoring failure (relay down, no provider
            # key, unparseable answer) and must fail closed - treating "no
            # opinion" as "safe" would silently turn paranoid mode into blanket
            # approval exactly when the safety net is broken.
            $autoMode.Mode = 'off'
            $logRes = 'paranoid_hold'
        }
    }

    if ($autoMode.Mode -ne 'off') {
        $state = @{
            status        = 'auto'
            project       = $projectCtx.Display
            raw_project   = $projectCtx.Raw
            summary       = $summary
            digest_label  = Get-CompactToolLabel -Hook $hook
            tool_name     = $hook.tool_name
            corr_key      = Get-ToolCorrelationKey -ToolInput $hook.tool_input
            session_id    = [string]$hook.session_id
            created       = [int][double]::Parse((Get-Date -UFormat %s))
            # Milliseconds, real UTC, purely so the log can report how long a
            # call took end to end. 'created' above stays as it is: it is in the
            # local-offset-shifted %s scale that Find-ApproveStateFile and
            # Complete-ApproveStatesForSession compare against their own %s values.
            created_ms    = [long][DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        }
        if ($risk) { $state.risk_score = $risk.Score }
        Write-ApproveState -ToolUseId $toolUseId -State $state

        $autoWho = if ($risk) { 'paranoid' } else { 'auto' }
        $autoScore = $null
        $autoWhy = $null
        if ($risk) {
            $autoScore = $risk.Score
            $autoWhy = Format-LogText -Text ([string]$risk.Reason) -MaxLength 200
        }
        Write-CallLog -Secrets $secrets -Fields ($log + @{
            ev    = 'pre'
            res   = 'auto_allow'
            who   = $autoWho
            mode  = [string]$autoMode.Mode
            thr   = $autoMode.Threshold
            score = $autoScore
            why   = $autoWhy
            ms    = [int]$hookSw.ElapsedMilliseconds
        })

        # Watcher posts the digest line; doing it here would add an HTTP
        # round-trip to every single tool call before it may proceed. Skipped
        # when there is no digest endpoint to post to: with matcher "*" that
        # would be one hidden process per tool call doing literally nothing.
        if ($secrets.auto_digest_url) {
            $watcher = Join-Path $PSScriptRoot 'watch-and-inject.ps1'
            Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$watcher`"", "`"$toolUseId`""
            ) | Out-Null
        } else {
            # The watcher is the only thing that deletes an auto-path state file,
            # so with no watcher this one has no consumer left. Drop it now instead
            # of leaving it to the hourly sweep: under matcher "*" the state
            # directory would otherwise grow with every tool call, and
            # Complete-ApproveStatesForSession parses every file in it per call.
            Remove-ApproveState -ToolUseId $toolUseId
        }

        Write-HookOutput -Text (@{
            hookSpecificOutput = @{
                hookEventName      = 'PreToolUse'
                permissionDecision = 'allow'
            }
        } | ConvertTo-Json -Compress -Depth 5)
        exit 0
    }

    $pendingState = @{
        status      = 'pending'
        project     = $projectCtx.Display
        raw_project = $projectCtx.Raw
        summary     = $summary
        tool_name   = $hook.tool_name
        corr_key    = Get-ToolCorrelationKey -ToolInput $hook.tool_input
        session_id  = [string]$hook.session_id
        created     = [int][double]::Parse((Get-Date -UFormat %s))
        # See the note on created_ms in the auto branch above: real-UTC
        # milliseconds, used only to report call duration in the log.
        created_ms  = [long][DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    }
    # Scored, over the threshold, and heading for the normal gate. The watcher
    # needs to know that to (a) show the risk in the Telegram ask and (b) warn
    # if the call turns out to be allowlisted and runs with no dialog at all.
    if ($risk) {
        $pendingState.paranoid    = $true
        $pendingState.risk_score  = $risk.Score
        $pendingState.risk_reason = $risk.Reason
    }
    # Scoring for every request (bot's /score), independent of auto-approve.
    # Deliberately NOT scored here: only calls that actually reach a dialog get
    # scored, in the detached watcher, so nothing is sent for calls the
    # allowlist passes silently and no tool call waits on an HTTP round-trip.
    if ($autoMode.ScoreAll -and $scoreDetail) {
        $pendingState.score_all    = $true
        $pendingState.score_detail = $scoreDetail
    }
    Write-ApproveState -ToolUseId $toolUseId -State $pendingState

    $gateScore = $null
    $gateWhy = $null
    if ($risk) {
        $gateScore = $risk.Score
        $gateWhy = Format-LogText -Text ([string]$risk.Reason) -MaxLength 200
    }
    # 'thr' is what separates "paranoid was on but wouldn't pass this call"
    # (res=paranoid_hold) from "auto-approve is simply off" (res=gate).
    Write-CallLog -Secrets $secrets -Fields ($log + @{
        ev    = 'pre'
        res   = $logRes
        mode  = [string]$autoMode.Mode
        thr   = $autoMode.Threshold
        score = $gateScore
        why   = $gateWhy
        ms    = [int]$hookSw.ElapsedMilliseconds
    })

    # Cost / trade-off worth knowing: this spawns a hidden watcher process on
    # EVERY tool call, and since the matcher became "*" that means every call of
    # every tool, MCP ones included. For allowlisted / auto-approved calls no
    # PermissionRequest ever fires, so the watcher sends nothing to Telegram - it
    # just waits up to promptWaitBudgetSec (15s, defined in watch-and-inject.ps1)
    # and exits. On a busy session that's a steady stream of short-lived
    # background processes. It's the accepted price of racing the native dialog:
    # PreToolUse can't know up front whether a call is allowlisted, so it must arm
    # a watcher for all. The log now measures exactly how wasteful that is -
    # compare res=no_dialog against res=ask_sent before optimising it.
    # Skipped outright when the relay endpoints the watcher needs are absent:
    # it would exit immediately on its own ask_url check anyway.
    if ($secrets.ask_url -and $secrets.answer_url_base) {
        $watcher = Join-Path $PSScriptRoot 'watch-and-inject.ps1'
        Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$watcher`"", "`"$toolUseId`""
        ) | Out-Null
    }
} catch {
    # Fall back to a normal local prompt on any failure.
}

exit 0
