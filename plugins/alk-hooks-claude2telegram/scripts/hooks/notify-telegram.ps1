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

    # These tool types are handled interactively by the approve flow. When
    # PermissionRequest fires for one of them, the native dialog is provably on
    # screen - flip the matching state to 'prompting' so the watcher knows it may
    # send the Telegram ask (it stays silent otherwise, e.g. for allowlisted calls
    # that never prompt), and skip the redundant plain FYI. PermissionRequest's
    # hook JSON has no tool_use_id (confirmed empirically), so match on
    # tool_name+correlation key instead. Keep the list in sync with the
    # PreToolUse/PostToolUse matcher in hooks/hooks.json.
    $interactiveToolNames = @('Bash', 'PowerShell', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'WebFetch')
    if ($eventName -eq 'PermissionRequest' -and $interactiveToolNames -contains $hook.tool_name) {
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
            exit 0
        }
    }

    # Turn is over - nothing can still be prompting. Retire any leftover watchers
    # of THIS session (e.g. after a local deny, which produces no hook event) so
    # their stale Telegram buttons get stripped instead of lingering until expiry.
    if ($eventName -eq 'Stop') {
        Complete-ApproveStatesForSession -SessionId $hook.session_id
    }

    $project = 'unknown'
    if ($hook.cwd) { $project = Split-Path -Leaf $hook.cwd }
    $project = Format-HtmlEscape "$project [$env:COMPUTERNAME]"

    $toolSummary = Get-ToolSummary -Hook $hook

    $message = switch ($eventName) {
        'PermissionRequest' { "🔔 $project — Claude ждёт разрешения: $toolSummary" }
        'Notification'      { "🔔 $project — $(Format-HtmlEscape $hook.message)" }
        'Stop' {
            $lastMsg = if ($hook.last_assistant_message) { [string]$hook.last_assistant_message } else { '' }
            if ($lastMsg.Length -gt 500) { $lastMsg = $lastMsg.Substring(0, 500) + '...' }
            if ($lastMsg) { "✅ $project — Claude:`n$(Format-MarkdownToTelegramHtml $lastMsg)" } else { "✅ $project — Claude завершил ответ" }
        }
        'PreToolUse'        { "⚙️ $project — выполняется: $toolSummary" }
        default             { "ℹ️ $project — $(Format-HtmlEscape $eventName)" }
    }

    $secretsPath = Get-TgApproveSecretsPath
    if (-not $secretsPath) { exit 0 }
    $secrets = Get-Content -LiteralPath $secretsPath -Raw | ConvertFrom-Json

    Send-RelayJson -Uri $secrets.relay_url -Secret $secrets.relay_secret -TimeoutSec 5 -Body @{
        text    = $message
        chat_id = $secrets.claude_chat_id
    } | Out-Null
} catch {
    # Never let a Telegram/relay failure affect the Claude Code session.
}

exit 0
