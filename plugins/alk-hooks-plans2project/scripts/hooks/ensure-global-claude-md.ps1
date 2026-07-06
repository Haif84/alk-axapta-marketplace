# Stop hook: ensure ~/.claude/CLAUDE.md contains the memory storage directive.
# Idempotent — appends only if the section is missing.

$ErrorActionPreference = 'Stop'

$claudeDir = Join-Path $env:USERPROFILE '.claude'
$claudeMd  = Join-Path $claudeDir 'CLAUDE.md'
$marker    = '## Memory storage'

$section = @'


## Memory storage

Always store memory files in the project's `memory/` subfolder, not in the system path.

- Write each individual memory file to `{cwd}/memory/filename.md`
- In the MEMORY.md index (system path), use relative paths: `memory/filename.md` — never absolute paths
- When reading a memory file referenced in MEMORY.md, resolve its path as `{primaryWorkingDirectory}/memory/filename.md`
'@

if (Test-Path $claudeMd) {
    $content = Get-Content $claudeMd -Raw -Encoding UTF8
    if ($content -match [regex]::Escape($marker)) { exit 0 }
    Add-Content -Path $claudeMd -Value $section -Encoding UTF8
} else {
    New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
    $initial = "# Global Claude Instructions" + $section
    Set-Content -Path $claudeMd -Value $initial -Encoding UTF8
}
