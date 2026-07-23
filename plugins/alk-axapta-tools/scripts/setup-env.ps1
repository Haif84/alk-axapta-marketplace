<#
.SYNOPSIS
    One-time AX ENV setup for XPOTools and alk-axapta-tools skills.

.DESCRIPTION
    Writes user-level ENV variables (HKCU\Environment) that XPOTools reads first
    and skills require before work (preflight gate):
      - AX_USER_NICK      - developer nick (mod comments)                 [required]
      - AX_AOT_PATH       - path to AOT-Prod dump (sync-xpo)              [required]
      - AX_PROJECT_ID     - ALK project prefix (e.g. ALK_DEVAX12)         [required]
      - AX_OBJECT_PREFIX  - lowercase identifier affix (alk_)             [exactly one
      - AX_OBJECT_SUFFIX  - postfix alternative to PREFIX                 of these two]
    All five are required. PREFIX/SUFFIX are mutually exclusive: exactly one
    must be set.

    Variables live in the user profile and survive plugin updates. No admin
    rights needed. ENV wins over config.local.json (cache is wiped on update).

    Legacy ALK_* variables are used as defaults for the new AX_* names and
    removed after a successful write.

    Also checks for Python >= 3.9 (needed by XPOTools).

.PARAMETER UserNick
    Developer nick. Required. Example: -UserNick akaz

.PARAMETER AotPath
    Path to AOT-Prod. Required.
    Example: -AotPath "E:\ZeroCoder\Axapta\ERP\AOT-Prod"

.PARAMETER ProjectId
    ALK project prefix. Required. Example: -ProjectId ALK_DEVAX12

.PARAMETER ObjectPrefix
    Lowercase identifier affix (e.g. alk_). Exactly one of ObjectPrefix/ObjectSuffix.

.PARAMETER ObjectSuffix
    Postfix alternative to ObjectPrefix. Do not set both.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File setup-env.ps1 -UserNick akaz -AotPath "E:\Axapta\AOT-Prod" -ProjectId ALK_DEVAX12 -ObjectPrefix alk_
#>

[CmdletBinding()]
param(
    [string]$UserNick     = [Environment]::GetEnvironmentVariable('ALK_USER_NICK', 'User'),

    [string]$AotPath      = [Environment]::GetEnvironmentVariable('ALK_AOT_PROD', 'User'),

    [string]$ProjectId    = [Environment]::GetEnvironmentVariable('ALK_PROJECT_PREFIX', 'User'),

    [string]$ObjectPrefix = [Environment]::GetEnvironmentVariable('ALK_IDENTIFIER_PREFIX', 'User'),

    [string]$ObjectSuffix = [Environment]::GetEnvironmentVariable('ALK_IDENTIFIER_SUFFIX', 'User')
)

$ErrorActionPreference = 'Stop'

Write-Host '==> ALK Axapta Tools: ENV setup' -ForegroundColor Cyan
Write-Host ''

$missing = @()
if ([string]::IsNullOrWhiteSpace($UserNick))  { $missing += 'UserNick (-UserNick akaz)' }
if ([string]::IsNullOrWhiteSpace($AotPath))   { $missing += 'AotPath (-AotPath "E:\...\AOT-Prod")' }
if ([string]::IsNullOrWhiteSpace($ProjectId)) { $missing += 'ProjectId (-ProjectId ALK_DEVAX12)' }

$prefixSet = -not [string]::IsNullOrWhiteSpace($ObjectPrefix)
$suffixSet = -not [string]::IsNullOrWhiteSpace($ObjectSuffix)
if ($prefixSet -and $suffixSet) {
    throw "ObjectPrefix and ObjectSuffix are both set ('$ObjectPrefix' / '$ObjectSuffix') - need exactly one. Nothing written."
}
if (-not $prefixSet -and -not $suffixSet) {
    $missing += 'ObjectPrefix OR ObjectSuffix (exactly one, e.g. -ObjectPrefix alk_)'
}

if ($missing.Count -gt 0) {
    throw "Required parameters missing (and not found in legacy ALK_* vars):`n  - $($missing -join "`n  - ")`nNothing written."
}

try {
    $pyVer = (& python --version) 2>&1
    $verMatch = [regex]::Match("$pyVer", 'Python (\d+)\.(\d+)')
    if ($verMatch.Success) {
        $major = [int]$verMatch.Groups[1].Value
        $minor = [int]$verMatch.Groups[2].Value
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
            Write-Warning "XPOTools needs Python >= 3.9, found $major.$minor. Please upgrade Python."
        } else {
            Write-Host "[ok] Python $major.$minor"
        }
    } else {
        Write-Warning "Could not parse Python version from: $pyVer"
    }
} catch {
    Write-Warning "Python not found in PATH. XPOTools needs Python >= 3.9 (https://www.python.org/)."
}

function Set-UserEnv {
    param([string]$Name, [string]$Value)
    $current = [Environment]::GetEnvironmentVariable($Name, 'User')
    if ($current -eq $Value) {
        Write-Host "[ok] $Name already set: $Value"
    } else {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
        if ($current) {
            Write-Host "[~]  $Name updated: $current -> $Value"
        } else {
            Write-Host "[+]  $Name = $Value"
        }
    }
}

function Remove-UserEnv {
    param([string]$Name)
    if ([Environment]::GetEnvironmentVariable($Name, 'User')) {
        [Environment]::SetEnvironmentVariable($Name, $null, 'User')
        Write-Host "[-]  $Name removed (migrated to new name)"
    }
}

$legacyMap = @{
    'ALK_USER_NICK'          = 'AX_USER_NICK'
    'ALK_AOT_PROD'           = 'AX_AOT_PATH'
    'ALK_PROJECT_PREFIX'     = 'AX_PROJECT_ID'
    'ALK_IDENTIFIER_PREFIX'  = 'AX_OBJECT_PREFIX'
    'ALK_IDENTIFIER_SUFFIX'  = 'AX_OBJECT_SUFFIX'
}
$legacyFound = @($legacyMap.Keys | Where-Object { [Environment]::GetEnvironmentVariable($_, 'User') })
if ($legacyFound.Count -gt 0) {
    Write-Host "[i] Legacy vars found (will be removed after write): $($legacyFound -join ', ')" -ForegroundColor Yellow
}

Set-UserEnv 'AX_PROJECT_ID'    $ProjectId
Set-UserEnv 'AX_USER_NICK'     $UserNick
Set-UserEnv 'AX_AOT_PATH'      $AotPath
Set-UserEnv 'AX_OBJECT_PREFIX' $ObjectPrefix
Set-UserEnv 'AX_OBJECT_SUFFIX' $ObjectSuffix

foreach ($old in $legacyFound) { Remove-UserEnv $old }

Write-Host ''
Write-Host '==> Done.' -ForegroundColor Green
Write-Host '    Open a new PowerShell/cmd session (or reload VS Code / Cursor)'
Write-Host '    so ENV is picked up. Check: $env:AX_USER_NICK'