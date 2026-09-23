# Shared by the UserPromptSubmit hooks that BLOCK a turn (context-budget,
# pause-guard). Not every prompt on that event was typed by the owner: the
# harness delivers a finished subagent's report, a message from another session
# and the output of a local command through the same event. Blocking those
# loses them for good — "send it again" has nothing to resend, and the
# orchestrator keeps waiting for work that is already done (seen in Batch,
# 2026-09-14: a blocked <task-notification> for a completed task 8).
# A block is only ever addressed to the owner, so it must fire only on what the
# owner typed himself. Slash commands are typed, and are not listed here.
# The keepalive ping is scheduled by the session itself (CronCreate, a prompt
# starting with 'keepalive:', docs/decisions/2026-09-18-keepalive-cron.md). It
# exists to read the cache and keep it from expiring, so a block throws away
# the very turn it pays for, and nobody is there to resend it.
# Dot-source it as: . (Join-Path $PSScriptRoot 'lib\system-prompt.ps1')
function Test-SystemPrompt {
    param([string] $Prompt)
    return ($Prompt -match '^\s*(<(task-notification|cross-session-message|local-command-stdout)[\s>]|keepalive:)')
}
