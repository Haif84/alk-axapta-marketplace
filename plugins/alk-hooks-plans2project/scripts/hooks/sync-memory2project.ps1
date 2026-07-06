# PostToolUse(Write): if a system memory file was written, mirror it to <cwd>/memory/
# and keep MEMORY.md links relative (memory/filename.md, not absolute paths).

$ErrorActionPreference = 'Stop'

$stdin = [Console]::In.ReadToEnd()
if (-not $stdin) { exit 0 }

try { $hook = $stdin | ConvertFrom-Json } catch { exit 0 }

$cwd = $hook.cwd
if (-not $cwd -or -not (Test-Path $cwd)) { exit 0 }

# Get written file path from tool_use input
$filePath = $null
if ($hook.tool_use -and $hook.tool_use.input) {
    $filePath = $hook.tool_use.input.file_path
}
if (-not $filePath) { exit 0 }

# Only act on files inside ~/.claude/projects/.../memory/
$systemProjects = Join-Path $env:USERPROFILE '.claude\projects'
if (-not $filePath.StartsWith($systemProjects, [System.StringComparison]::OrdinalIgnoreCase)) { exit 0 }
if ($filePath -notmatch '\\memory\\[^\\]+$') { exit 0 }

$fileName = [System.IO.Path]::GetFileName($filePath)
$destDir  = Join-Path $cwd 'memory'
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$destFile = Join-Path $destDir $fileName

if ($fileName -eq 'MEMORY.md') {
    # Rewrite absolute paths in markdown links to relative:
    #   ](any\path\memory\file.md) or ](any/path/memory/file.md) → ](memory/file.md)
    $content = Get-Content $filePath -Raw -Encoding UTF8
    $content = $content -replace '\]\([^)]*[/\\]memory[/\\]([^)]+)\)', '](memory/$1)'
    Set-Content -Path $filePath -Value $content -Encoding UTF8 -NoNewline
    Set-Content -Path $destFile -Value $content -Encoding UTF8 -NoNewline
} else {
    Copy-Item -Path $filePath -Destination $destFile -Force
}
