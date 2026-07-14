# UserPromptSubmit hook: on every new user prompt, checks the relay's inbox
# for this project (free-text messages typed into the project's Telegram
# topic - see relay's GET /inbox/{project}) and surfaces any as
# additionalContext. This is the only realistic delivery point: Claude Code
# has no periodic/background hook, so a Telegram reply can only ever "arrive"
# at whatever hook fires next - in practice, the user's next prompt. Must
# never block or fail prompt submission - any error means silently no
# feedback surfaces this time.

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\hook-common.ps1"

try {
    $stdin = Read-HookStdin
    if (-not $stdin) { exit 0 }

    $hook = $stdin | ConvertFrom-Json

    $secretsPath = Get-TgApproveSecretsPath
    if (-not $secretsPath) { exit 0 }
    $secrets = Get-Content -LiteralPath $secretsPath -Raw | ConvertFrom-Json

    $projectCtx = Get-ProjectContext -Hook $hook -Secrets $secrets
    $feedback = Get-PendingTelegramFeedback -Secrets $secrets -Project $projectCtx.Raw
    if (-not $feedback) { exit 0 }

    $output = @{
        hookSpecificOutput = @{
            hookEventName    = 'UserPromptSubmit'
            additionalContext = "Сообщения из Telegram-темы проекта, ожидавшие следующего обращения к сессии:`n$feedback"
        }
    } | ConvertTo-Json -Compress -Depth 5

    Write-HookOutput -Text $output
} catch {
    # Never let a Telegram/relay failure affect prompt submission.
}

exit 0
