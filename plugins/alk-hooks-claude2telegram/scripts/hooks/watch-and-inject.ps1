# Detached background watcher spawned by pretooluse-approve.ps1 for one
# potential permission prompt. Waits until notify-telegram.ps1 confirms the
# native VS Code dialog is actually on screen (state flips to 'prompting'),
# only then sends the Telegram ask and polls for a reply, injecting a
# keystroke into the still-open dialog if the phone answers first. Stands
# down without injecting - and strips the Telegram buttons via /edit - if the
# prompt got resolved locally (PostToolUse marked it 'answered', a newer
# prompt superseded it, or the Stop sweep retired it).

param(
    [Parameter(Mandatory = $true)][string]$ToolUseId
)

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\hook-common.ps1"

$promptWaitBudgetSec = 15
$pollIntervalSec = 3

try {
    $secretsPath = Get-TgApproveSecretsPath
    if (-not $secretsPath) { exit 0 }
    $secrets = Get-Content -LiteralPath $secretsPath -Raw | ConvertFrom-Json
    if (-not $secrets.ask_url -or -not $secrets.answer_url_base) { exit 0 }

    $state = Read-ApproveState -ToolUseId $ToolUseId
    if (-not $state) { exit 0 }

    # Phase 1: don't send anything yet - wait for proof that a dialog exists.
    # 'answered' here means the tool was auto-approved (allowlist) and already
    # ran; a timeout means either a long-running auto-approved call (PostToolUse
    # still pending) or an environment where PermissionRequest doesn't fire.
    # In every non-'prompting' outcome the phone must NOT be asked.
    $promptDeadline = (Get-Date).AddSeconds($promptWaitBudgetSec)
    $prompting = $false
    while ((Get-Date) -lt $promptDeadline) {
        $current = Read-ApproveState -ToolUseId $ToolUseId
        if (-not $current) { exit 0 }
        if ($current.status -eq 'answered') { Remove-ApproveState -ToolUseId $ToolUseId; exit 0 }
        if ($current.status -eq 'prompting') { $prompting = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $prompting) {
        Remove-ApproveState -ToolUseId $ToolUseId
        exit 0
    }

    $message = "🔔 $($state.project) — Claude просит разрешение:`n$($state.summary)"

    $askResponse = Send-RelayJson -Uri $secrets.ask_url -Secret $secrets.relay_secret -TimeoutSec 10 -Body @{
        text    = $message
        chat_id = $secrets.claude_chat_id
        project = $state.raw_project
    }
    if (-not $askResponse.ok -or -not $askResponse.request_id) {
        Remove-ApproveState -ToolUseId $ToolUseId
        exit 0
    }

    $requestId = $askResponse.request_id
    $answerUrl = "$($secrets.answer_url_base)/$requestId"
    $pollBudgetSec = Get-EffectiveWaitBudget -Secrets $secrets

    # Strips the inline buttons off our ask message and explains why. Relay-side,
    # /edit also drops the matching pending ask so the expiry sweep won't
    # re-edit the message with a misleading "не дождались ответа" later.
    function Edit-AskMessage {
        param([string]$Suffix)
        if (-not $secrets.edit_url -or -not $askResponse.chat_id -or -not $askResponse.message_id) { return }
        try {
            Send-RelayJson -Uri $secrets.edit_url -Secret $secrets.relay_secret -TimeoutSec 10 -Body @{
                chat_id    = $askResponse.chat_id
                message_id = $askResponse.message_id
                text       = "$message`n`n$Suffix"
                request_id = $requestId
            } | Out-Null
        } catch {
        }
    }

    $deadline = (Get-Date).AddSeconds($pollBudgetSec)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds $pollIntervalSec

        $current = Read-ApproveState -ToolUseId $ToolUseId
        if (-not $current -or $current.status -eq 'answered') {
            # Resolved locally (or state vanished) - stand down, no injection.
            Edit-AskMessage -Suffix '🖥 Решено локально в IDE'
            Remove-ApproveState -ToolUseId $ToolUseId
            exit 0
        }

        try {
            $answer = Get-RelayJson -Uri $answerUrl -Secret $secrets.relay_secret -TimeoutSec 10
        } catch {
            continue
        }
        if ($answer.ok -and $answer.status -eq 'answered') {
            # Last-moment re-check: the local dialog may have been resolved while
            # the /answer request was in flight. Injecting now would land the
            # keystroke in a dialog that no longer exists - or worse, in a NEWER
            # dialog that replaced it.
            $current = Read-ApproveState -ToolUseId $ToolUseId
            if (-not $current -or $current.status -eq 'answered') {
                Edit-AskMessage -Suffix "🖥 Решено локально в IDE (ответ с телефона от $(Format-HtmlEscape $answer.answered_by) не применён)"
                Remove-ApproveState -ToolUseId $ToolUseId
                exit 0
            }

            Invoke-VSCodeKeystroke -Decision $answer.decision | Out-Null

            # Verify the injection actually landed: for "allow", PostToolUse only
            # fires once the tool truly executes, which requires the dialog to have
            # actually been dismissed. No such signal exists for "deny" (the tool
            # never runs either way), so only "allow" gets verified.
            #
            # 25s, not a few seconds: PostToolUse fires on full command completion,
            # not on dialog dismissal - a slow command (network calls, file I/O)
            # can legitimately take a while to finish even though the dialog closed
            # instantly. A short window here produces false "failed to apply"
            # warnings for slow-but-successful commands (confirmed happening with
            # a ~6s window on a command that made real HTTP calls).
            if ($answer.decision -eq 'allow') {
                $verified = $false
                $verifyDeadline = (Get-Date).AddSeconds(25)
                while ((Get-Date) -lt $verifyDeadline) {
                    Start-Sleep -Milliseconds 500
                    $postState = Read-ApproveState -ToolUseId $ToolUseId
                    if ($postState -and $postState.status -eq 'answered') {
                        $verified = $true
                        break
                    }
                }
                if (-not $verified -and $secrets.edit_url -and $answer.chat_id -and $answer.message_id) {
                    $warnText = "$($answer.text)`n`n⚠️ Разрешено, не удалось применить в IDE — проверьте вручную — $(Format-HtmlEscape $answer.answered_by)"
                    try {
                        Send-RelayJson -Uri $secrets.edit_url -Secret $secrets.relay_secret -TimeoutSec 10 -Body @{
                            chat_id    = $answer.chat_id
                            message_id = $answer.message_id
                            text       = $warnText
                        } | Out-Null
                    } catch {
                    }
                }
            }

            Remove-ApproveState -ToolUseId $ToolUseId
            exit 0
        }
    }

    # Poll budget exhausted - the relay's own expiry sweep edits the message.
    Remove-ApproveState -ToolUseId $ToolUseId
} catch {
}

exit 0
