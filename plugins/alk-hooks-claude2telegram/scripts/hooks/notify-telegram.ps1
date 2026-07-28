# Relays Claude Code hook events (PermissionRequest/Notification, Stop, PreToolUse)
# to a Telegram group via the existing tg-relay HTTP relay (LT_TGProxy/tg-relay on proxy-01).
# Shipped as part of the alk-hooks-claude2telegram plugin; activated via the
# plugin's hooks/hooks.json (no manual ~/.claude/settings.json edit needed).
# Must never block or fail the session — always exits 0, swallows all errors.

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\hook-common.ps1"

try {
    $stdin = Read-HookStdin
    if (-not $stdin) { exit 0 }

    $hook = $stdin | ConvertFrom-Json
    $eventName = $hook.hook_event_name

    # Loaded up here (it used to be read below, after the branches) so the call
    # log and Get-MachineLabel are available to every branch. Null-safe on
    # purpose: a missing or unparseable secrets file must still let the
    # 'prompting' flip happen - that flip is local file work and needs no relay.
    $secrets = $null
    $secretsPath = Get-TgApproveSecretsPath
    if ($secretsPath) {
        try {
            $secrets = Get-Content -LiteralPath $secretsPath -Raw | ConvertFrom-Json
        } catch {
        }
    }

    $projectCtx = Get-ProjectContext -Hook $hook -Secrets $secrets
    $project = $projectCtx.Display

    # ANY PermissionRequest means the native dialog is provably on screen. If the
    # approve flow armed a watcher for this call, flip its state to 'prompting' so
    # the watcher knows it may send the Telegram ask (it stays silent otherwise,
    # e.g. for allowlisted calls that never prompt), and skip the redundant plain
    # FYI. PermissionRequest's hook JSON has no tool_use_id (confirmed
    # empirically), so match on tool_name+correlation key instead.
    #
    # There used to be a hardcoded $interactiveToolNames whitelist here that had
    # to be kept in sync with the hooks.json matcher by hand. It is gone on
    # purpose: the matcher is now "*", so mcp__* calls arm watchers too, and under
    # the whitelist they fell through to a useless FYI while their watcher sat out
    # phase 1 and died - i.e. no Allow/Deny buttons on the phone for any MCP call
    # at all. The existence of a state file is now the whole gate, and that cannot
    # drift out of sync with the matcher.
    if ($eventName -eq 'PermissionRequest') {
        $corrKey = Get-ToolCorrelationKey -ToolInput $hook.tool_input
        # PreToolUse and PermissionRequest can fire close enough together that
        # pretooluse-approve.ps1 hasn't written its state file yet (it does more
        # work first: HTML escaping, JSON serialization). Retry briefly instead
        # of checking once, to close that race rather than just narrowing it.
        $statePath = $null
        for ($i = 0; $i -lt 6; $i++) {
            $statePath = Find-ApproveStateFile -ToolName $hook.tool_name -CorrelationKey $corrKey
            if ($statePath) { break }
            Start-Sleep -Milliseconds 200
        }
        if ($statePath) {
            Update-ApproveStateStatus -Path $statePath -Status 'prompting'
            Write-CallLog -Secrets $secrets -Fields @{
                ev   = 'perm'
                res  = 'dialog_shown'
                tool = [string]$hook.tool_name
                tuid = [System.IO.Path]::GetFileNameWithoutExtension($statePath)
                sid  = [string]$hook.session_id
                proj = $projectCtx.Raw
                mach = (Get-MachineLabel -Secrets $secrets)
                det  = (Get-ToolLogDetail -Hook $hook)
            }
            exit 0
        }
    }

    # Turn is over - nothing can still be prompting. Retire any leftover watchers
    # of THIS session (e.g. after a local deny, which produces no hook event) so
    # their stale Telegram buttons get stripped instead of lingering until expiry.
    if ($eventName -eq 'Stop') {
        Complete-ApproveStatesForSession -SessionId $hook.session_id
    }

    if (-not $secrets -or -not $secrets.relay_url) { exit 0 }

    $toolSummary = Get-ToolSummary -Hook $hook

    $message = switch ($eventName) {
        'PermissionRequest' { "🔔 $project — Claude ждёт разрешения: $toolSummary" }
        'Notification'      { "🔔 $project — $(Format-HtmlEscape $hook.message)" }
        'Stop' {
            $lastMsg = if ($hook.last_assistant_message) { [string]$hook.last_assistant_message } else { '' }
            if ($lastMsg) {
                # Raw cap is the /length preset from the relay (500/1000/3800);
                # Format-TruncatedTelegramHtml then guarantees the converted
                # HTML fits Telegram's 4096 hard cap with prefix headroom.
                $limit = Get-EffectiveMaxLength -Secrets $secrets
                "✅ $project — Claude:`n$(Format-TruncatedTelegramHtml -Text $lastMsg -MaxRawChars $limit)"
            } else { "✅ $project — Claude завершил ответ" }
        }
        'PreToolUse'        { "⚙️ $project — выполняется: $toolSummary" }
        default             { "ℹ️ $project — $(Format-HtmlEscape $eventName)" }
    }

    Send-RelayJson -Uri $secrets.relay_url -Secret $secrets.relay_secret -TimeoutSec 5 -Body @{
        text    = $message
        chat_id = $secrets.claude_chat_id
        project = $projectCtx.Raw
    } | Out-Null

    # A PermissionRequest reaching this far means no state file was found for it,
    # so no watcher is racing the dialog and the phone gets a plain FYI with no
    # buttons. Worth recording: it is the signature of an approve-flow miss.
    $notifyNote = $null
    if ($eventName -eq 'PermissionRequest') { $notifyNote = 'no state file - watcher not armed' }
    Write-CallLog -Secrets $secrets -Fields @{
        ev   = 'notify'
        res  = [string]$eventName
        tool = [string]$hook.tool_name
        sid  = [string]$hook.session_id
        proj = $projectCtx.Raw
        mach = (Get-MachineLabel -Secrets $secrets)
        det  = (Get-ToolLogDetail -Hook $hook)
        note = $notifyNote
    }
} catch {
    # Never let a Telegram/relay failure affect the Claude Code session.
}

exit 0
