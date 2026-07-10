# Shared helpers for Claude Code -> Telegram hook scripts.
# Dot-sourced by notify-telegram.ps1 and ask-telegram.ps1; must live alongside them.
#
# Messages are sent with Telegram parse_mode=HTML (see relay's ask.py/notify.py),
# so every piece of dynamic text (commands, descriptions, project names) MUST be
# HTML-escaped before being interpolated into a message - raw command text can
# contain <, >, & which would otherwise break Telegram's HTML parser and cause
# the whole send to fail (or worse, get silently mis-rendered).

function Format-HtmlEscape {
    param([string]$Text)
    if (-not $Text) { return '' }
    return $Text -replace '&', '&amp;' -replace '<', '&lt;' -replace '>', '&gt;'
}

function Format-MarkdownToTelegramHtml {
    # Claude's own reply text (last_assistant_message) uses Markdown, not HTML.
    # Escape first (protects literal <, >, & from the raw text), THEN convert
    # **bold**/`code` spans to real tags. If truncation upstream cut a span in
    # half, the regex just won't match - leaves literal ** as text, never an
    # unclosed tag that could break the rest of the message.
    param([string]$Text)
    if (-not $Text) { return '' }
    $escaped = Format-HtmlEscape $Text
    $escaped = [regex]::Replace($escaped, '\*\*(.+?)\*\*', '<b>$1</b>')
    $escaped = [regex]::Replace($escaped, '`([^`]+?)`', '<code>$1</code>')
    return $escaped
}

function Format-TextPreview {
    # HTML-escaped, truncated, single-line-collapsed preview of arbitrary text
    # for embedding inside a <code> block. Collapsing newlines to a visible
    # marker keeps multi-line content from blowing up message length while
    # still showing it happened.
    param([string]$Text, [int]$MaxLength = 200)
    if (-not $Text) { return '' }
    $t = $Text -replace '\r?\n', ' ⏎ '
    if ($t.Length -gt $MaxLength) { $t = $t.Substring(0, $MaxLength) + '...' }
    return Format-HtmlEscape $t
}

function Format-EditPreview {
    # Two-line before/after preview for an Edit-style old_string/new_string
    # pair, each independently truncated - a quick diff glance, not a full one.
    param([string]$OldString, [string]$NewString)
    $lines = @()
    if ($OldString) { $lines += "<code>- $(Format-TextPreview -Text $OldString -MaxLength 150)</code>" }
    if ($NewString) { $lines += "<code>+ $(Format-TextPreview -Text $NewString -MaxLength 150)</code>" }
    return $lines
}

function Get-ToolSummary {
    param($Hook)

    if (-not $Hook.tool_name) { return '' }

    $summary = Format-HtmlEscape $Hook.tool_name
    $toolInput = $Hook.tool_input
    if (-not $toolInput) { return $summary }

    if ($Hook.tool_name -eq 'AskUserQuestion' -and $toolInput.questions) {
        $qTexts = @()
        foreach ($q in $toolInput.questions) {
            if ($q.question) { $qTexts += [string]$q.question }
        }
        $joined = $qTexts -join ' | '
        if ($joined.Length -gt 300) { $joined = $joined.Substring(0, 300) + '...' }
        return "$summary`: " + (Format-HtmlEscape $joined)
    }

    if ($toolInput.command) {
        $lines = @()
        if ($toolInput.description) {
            $desc = [string]$toolInput.description
            if ($desc.Length -gt 150) { $desc = $desc.Substring(0, 150) + '...' }
            $lines += "<b>$(Format-HtmlEscape $desc)</b>"
        }
        $cmd = [string]$toolInput.command
        if ($cmd.Length -gt 200) { $cmd = $cmd.Substring(0, 200) + '...' }
        $lines += "<code>$(Format-HtmlEscape $cmd)</code>"
        return "$summary`: " + ($lines -join "`n")
    }

    # File-editing tools: mirror the local dialog's own phrasing ("Make this
    # edit to <file>?"), plus a short truncated content preview so the phone
    # side isn't deciding blind - full diffs are still too noisy for a chat
    # message, but a first look at what's changing is worth the extra lines.
    if ($Hook.tool_name -eq 'Write' -and $toolInput.file_path) {
        $fp = Format-HtmlEscape ([string]$toolInput.file_path)
        $lines = @("<b>Create/overwrite ${fp}?</b>")
        if ($toolInput.content) {
            $lines += "<code>$(Format-TextPreview -Text ([string]$toolInput.content) -MaxLength 300)</code>"
        }
        return "$summary`: " + ($lines -join "`n")
    }
    if ($Hook.tool_name -eq 'Edit' -and $toolInput.file_path) {
        $fp = Format-HtmlEscape ([string]$toolInput.file_path)
        $lines = @("<b>Make this edit to ${fp}?</b>")
        $lines += Format-EditPreview -OldString $toolInput.old_string -NewString $toolInput.new_string
        return "$summary`: " + ($lines -join "`n")
    }
    if ($Hook.tool_name -eq 'MultiEdit' -and $toolInput.file_path) {
        $fp = Format-HtmlEscape ([string]$toolInput.file_path)
        $edits = @()
        if ($toolInput.edits) { $edits = @($toolInput.edits) }
        $lines = @("<b>Make $($edits.Count) edit(s) to ${fp}?</b>")
        $shown = [Math]::Min(2, $edits.Count)
        for ($i = 0; $i -lt $shown; $i++) {
            $lines += Format-EditPreview -OldString $edits[$i].old_string -NewString $edits[$i].new_string
        }
        if ($edits.Count -gt $shown) { $lines += "... +$($edits.Count - $shown) more" }
        return "$summary`: " + ($lines -join "`n")
    }
    if ($Hook.tool_name -eq 'NotebookEdit' -and $toolInput.notebook_path) {
        $np = Format-HtmlEscape ([string]$toolInput.notebook_path)
        return "$summary`: <b>Edit notebook ${np}?</b>"
    }
    if ($Hook.tool_name -eq 'WebFetch' -and $toolInput.url) {
        $url = Format-HtmlEscape ([string]$toolInput.url)
        return "$summary`: <b>Fetch ${url}?</b>"
    }

    $parts = @()
    foreach ($prop in $toolInput.PSObject.Properties) {
        if ($prop.Value -is [string] -or $prop.Value -is [System.ValueType]) {
            $parts += "$($prop.Name)=$($prop.Value)"
        }
    }
    if ($parts.Count -eq 0) { return $summary }

    $joined = $parts -join '; '
    if ($joined.Length -gt 300) { $joined = $joined.Substring(0, 300) + '...' }
    return "$summary`: " + (Format-HtmlEscape $joined)
}

function Read-HookStdin {
    $reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
    return $reader.ReadToEnd()
}

# PS 5.1's Console::Out and Invoke-RestMethod's string -Body both silently
# re-encode via the system codepage. Every write/send must go through explicit
# UTF-8 bytes instead - see feedback_powershell_hook_encoding memory.

function Write-HookOutput {
    param([string]$Text)
    $stdout = [Console]::OpenStandardOutput()
    $writer = New-Object System.IO.StreamWriter($stdout, (New-Object System.Text.UTF8Encoding($false)))
    $writer.Write($Text)
    $writer.Flush()
}

function Send-RelayJson {
    param([string]$Uri, [string]$Secret, [hashtable]$Body, [int]$TimeoutSec = 10)
    $json = $Body | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    return Invoke-RestMethod -Uri $Uri -Method Post `
        -Headers @{ 'X-Relay-Secret' = $Secret } `
        -Body $bytes -ContentType 'application/json; charset=utf-8' -TimeoutSec $TimeoutSec
}

function Get-RelayJson {
    param([string]$Uri, [string]$Secret, [int]$TimeoutSec = 10)
    return Invoke-RestMethod -Uri $Uri -Method Get `
        -Headers @{ 'X-Relay-Secret' = $Secret } -TimeoutSec $TimeoutSec
}

function Get-TgApproveSecretsPath {
    # Portable resolution so the same scripts work unmodified whether deployed
    # by hand on this machine, installed as a plugin on someone else's, or run
    # by a teammate: 1) explicit env override, 2) portable per-user default
    # (what a fresh plugin install should use), 3) this machine's original
    # hardcoded path (legacy - kept so nothing breaks here today). Returns
    # $null if none exist; callers already treat that as "exit quietly".
    if ($env:TG_APPROVE_SECRETS_PATH -and (Test-Path $env:TG_APPROVE_SECRETS_PATH)) {
        return $env:TG_APPROVE_SECRETS_PATH
    }
    $portable = Join-Path $env:USERPROFILE '.claude\tg-approve.secrets.json'
    if (Test-Path $portable) { return $portable }
    $legacy = 'E:\ZeroCoder_local\_sync\telegram.secrets.json'
    if (Test-Path $legacy) { return $legacy }
    return $null
}

function Get-EffectiveWaitBudget {
    # Asks the relay how long to poll for a phone answer right now - overridable
    # from the phone via the bot's /wait command (see app/state.py's
    # wait_override), so a 10-minute default doesn't expire a request while
    # away for hours. Relay is the single source of truth specifically so this
    # value can never drift out of sync between here and the relay's own
    # expiry sweep the way two independent hardcoded constants once did.
    # Any failure (secret missing, network hiccup, relay down) falls back to
    # 600s - must never block or fail the approve flow.
    param([object]$Secrets)
    $fallback = 600
    if (-not $Secrets.wait_budget_url) { return $fallback }
    try {
        $response = Get-RelayJson -Uri $Secrets.wait_budget_url -Secret $Secrets.relay_secret -TimeoutSec 5
        if ($response.ok -and $response.budget_seconds) { return [int]$response.budget_seconds }
    } catch {
    }
    return $fallback
}

# --- Keystroke-injection approve flow (pretooluse-approve.ps1 / watch-and-inject.ps1 /
# posttooluse-mark-answered.ps1 / notify-telegram.ps1) --------------------------------
# Coordinated across independent OS processes via small per-tool_use_id JSON files,
# since PowerShell processes don't share memory. Keystroke idea lifted from
# github.com/Mrinal-Sahai/claude-remote-approve: the native VS Code dialog can't be
# resolved programmatically, so race it by injecting a keystroke if the phone answers
# first. Unlike that tool we DON'T force permissionDecision "ask" (that would override
# the settings.json allowlist and prompt for everything); instead the state file
# tracks a lifecycle and the Telegram ask is only sent once a dialog provably exists:
#   pending   - PreToolUse fired, watcher spawned, no dialog confirmed yet
#   prompting - PermissionRequest fired for the same tool_name+corr_key, i.e. the
#               native dialog is actually on screen -> watcher may send the TG ask
#   answered  - resolved locally (PostToolUse) or swept (Stop / superseded by a newer
#               PreToolUse in the same session) -> watcher stands down, no injection

$script:ApproveStateDir = Join-Path $env:TEMP 'claude-tg-approve'

function Get-ApproveStatePath {
    param([string]$ToolUseId)
    if (-not (Test-Path $script:ApproveStateDir)) {
        New-Item -ItemType Directory -Force -Path $script:ApproveStateDir | Out-Null
    }
    return Join-Path $script:ApproveStateDir "$ToolUseId.json"
}

function Write-ApproveState {
    param([string]$ToolUseId, [hashtable]$State)
    $path = Get-ApproveStatePath -ToolUseId $ToolUseId
    ($State | ConvertTo-Json -Compress) | Set-Content -LiteralPath $path -Encoding UTF8
}

function Read-ApproveState {
    param([string]$ToolUseId)
    $path = Get-ApproveStatePath -ToolUseId $ToolUseId
    if (-not (Test-Path $path)) { return $null }
    try { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { return $null }
}

function Remove-ApproveState {
    param([string]$ToolUseId)
    $path = Get-ApproveStatePath -ToolUseId $ToolUseId
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}

function Get-ToolCorrelationKey {
    # Picks the most identifying field per tool type, since Write/Edit/
    # MultiEdit/NotebookEdit/WebFetch don't have tool_input.command the way
    # Bash/PowerShell do. Falls back to a full JSON dump for anything unknown.
    param($ToolInput)
    if (-not $ToolInput) { return '' }
    if ($ToolInput.command) { return [string]$ToolInput.command }
    if ($ToolInput.file_path) { return [string]$ToolInput.file_path }
    if ($ToolInput.url) { return [string]$ToolInput.url }
    return ($ToolInput | ConvertTo-Json -Compress -Depth 5)
}

function Find-ApproveStateFile {
    # PermissionRequest's hook JSON has no tool_use_id (confirmed empirically -
    # only PreToolUse/PostToolUse have it), so it can't be correlated by ID like
    # the approve-flow's own state files are keyed. Fall back to matching on
    # tool_name + correlation key within a short recency window instead.
    # Returns the path of the newest match, or $null.
    param([string]$ToolName, [string]$CorrelationKey, [int]$MaxAgeSeconds = 15)
    if (-not (Test-Path $script:ApproveStateDir)) { return $null }
    $now = [int][double]::Parse((Get-Date -UFormat %s))
    $bestPath = $null
    $bestCreated = -1
    foreach ($file in Get-ChildItem -Path $script:ApproveStateDir -Filter '*.json' -ErrorAction SilentlyContinue) {
        try {
            $state = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        } catch {
            continue
        }
        if ($state.tool_name -eq $ToolName -and $state.corr_key -eq $CorrelationKey -and ($now - $state.created) -le $MaxAgeSeconds) {
            if ([int]$state.created -gt $bestCreated) {
                $bestCreated = [int]$state.created
                $bestPath = $file.FullName
            }
        }
    }
    return $bestPath
}

function Update-ApproveStateStatus {
    # In-place status transition on an existing state file. Never downgrades
    # 'answered' back to 'prompting'/'pending' - once a prompt is resolved the
    # watcher must not be re-armed by a late PermissionRequest event.
    param([string]$Path, [string]$Status)
    try {
        $state = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    } catch {
        return
    }
    if (-not $state) { return }
    if ($state.status -eq 'answered' -and $Status -ne 'answered') { return }
    $state.status = $Status
    ($state | ConvertTo-Json -Compress) | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Complete-ApproveStatesForSession {
    # Marks 'answered' every not-yet-answered state belonging to $SessionId whose
    # created timestamp is at least $OlderThanSeconds old. Used two ways:
    #  - pretooluse-approve: OlderThanSeconds 3 - a NEW permission prompt in the
    #    same session means any older pending one was already resolved (a locally
    #    denied dialog leaves no hook event, so this is the only signal); the 3s
    #    guard spares parallel sibling tool calls created in the same instant.
    #  - notify-telegram Stop: OlderThanSeconds 0 - turn is over, nothing can
    #    still be prompting; sweeps stragglers so their TG buttons get stripped.
    # Watchers notice the 'answered' status within one poll and stand down.
    param([string]$SessionId, [int]$OlderThanSeconds = 0)
    if (-not $SessionId) { return }
    if (-not (Test-Path $script:ApproveStateDir)) { return }
    $now = [int][double]::Parse((Get-Date -UFormat %s))
    foreach ($file in Get-ChildItem -Path $script:ApproveStateDir -Filter '*.json' -ErrorAction SilentlyContinue) {
        try {
            $state = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        } catch {
            continue
        }
        if ($state.session_id -ne $SessionId) { continue }
        if ($state.status -eq 'answered') { continue }
        if (($now - [int]$state.created) -lt $OlderThanSeconds) { continue }
        Update-ApproveStateStatus -Path $file.FullName -Status 'answered'
    }
}

function Remove-StaleApproveStates {
    # Orphan cleanup: a crashed watcher leaves its state file behind forever.
    # Anything older than an hour is long past every poll budget in play.
    param([int]$MaxAgeMinutes = 60)
    if (-not (Test-Path $script:ApproveStateDir)) { return }
    $cutoff = (Get-Date).AddMinutes(-$MaxAgeMinutes)
    Get-ChildItem -Path $script:ApproveStateDir -Filter '*.json' -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Invoke-VSCodeKeystroke {
    # Mirrors claude-remote-approve's _inject_windows: bring VS Code to front via
    # WScript.Shell.AppActivate (title substring match), then SendKeys. Assumes the
    # native Quick Pick's first/highlighted option is Allow, so Enter accepts it and
    # Escape dismisses (denies) it - same assumption their tool makes.
    param([string]$Decision)
    $key = if ($Decision -eq 'deny') { '{ESC}' } else { '{ENTER}' }
    try {
        $wsh = New-Object -ComObject WScript.Shell
        $wsh.AppActivate('Visual Studio Code') | Out-Null
        Start-Sleep -Milliseconds 250
    } catch {
        # Fall through - SendKeys will fire at whatever window is already in front.
    }
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.SendKeys]::SendWait($key)
        return $true
    } catch {
        return $false
    }
}
