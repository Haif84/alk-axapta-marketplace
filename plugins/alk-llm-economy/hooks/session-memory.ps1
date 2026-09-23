# SessionStart hook: feeds the global memory index into the model's context.
# The prose rule "load memory at the start of every session" is not enforced by
# anything and costs a turn; in the 2026-09-13 session the index never arrived.
# The hook delivers it deterministically (~600 tokens). Individual memory files
# stay on disk and are opened by the links from the index when a task needs them.
# Only the global index: the project index (~/.claude/projects/<slug>/memory/MEMORY.md)
# is loaded by Claude Code itself, injecting it here would pay for it twice a turn.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')

$parts = @()

# Впрыск using-superpowers снят из кэша плагина (docs/decisions/2026-09-14-superpowers-hook.md);
# обновление плагина вернёт его молча, поэтому проверяется каждый старт.
$spHooks = Join-Path $env:USERPROFILE '.claude/plugins/cache/*/superpowers/*/hooks/hooks.json'
$spBack = @(Get-ChildItem -Path $spHooks -ErrorAction SilentlyContinue |
    Where-Object { (Get-Content -LiteralPath $_.FullName -Raw -Encoding utf8) -match '"SessionStart"' })
if ($spBack.Count -gt 0) {
    $parts += "=== ХУК SUPERPOWERS ===`nОбновление плагина вернуло впрыск using-superpowers — это ~1 230 токенов в каждом ходу сессии. Сними командой ``node ~/.claude/scripts/superpowers-hook-off.js`` и скажи об этом владельцу."
}

$index = Join-Path $env:USERPROFILE '.claude\memory\MEMORY.md'
if (Test-Path -LiteralPath $index) {
    $text = Get-Content -LiteralPath $index -Raw -Encoding utf8
    if ($text) { $parts += ("=== GLOBAL MEMORY INDEX ($index) ===`n" + $text) }
}

if ($parts.Count -eq 0) { exit 0 }
ConvertTo-AsciiJson @{ hookSpecificOutput = @{ hookEventName = 'SessionStart'; additionalContext = ($parts -join "`n`n") } }
exit 0
