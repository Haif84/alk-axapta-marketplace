# Shared by every hook that prints JSON with Russian text.
# ConvertTo-Json in PS 5.1 leaves Cyrillic as-is and the hook console is not
# UTF-8, so the bytes reach the agent in CP866 and arrive garbled. Escaping
# every non-ASCII char to \uXXXX makes the payload pure ASCII, immune to the
# console codepage.
# Dot-source it as: . (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')
function ConvertTo-AsciiJson {
    param(
        [Parameter(Mandatory = $true)] $InputObject,
        [int] $Depth = 3
    )
    $json = ConvertTo-Json -InputObject $InputObject -Compress -Depth $Depth
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $json.ToCharArray()) {
        if ([int]$ch -gt 127) { [void]$sb.AppendFormat('\u{0:x4}', [int]$ch) } else { [void]$sb.Append($ch) }
    }
    $sb.ToString()
}
