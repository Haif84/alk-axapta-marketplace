#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Локальная установка XPOTools: PATH + config.local.json.

.DESCRIPTION
  1. Проверяет наличие python (>= 3.9) в PATH.
  2. Добавляет XPOTools/bin в user-level $env:PATH (HKCU\Environment, без admin).
  3. Создаёт config.local.json из config.example.json, если ещё нет.
  4. Печатает напоминание про новую сессию.

.NOTES
  Запускать без параметров: ./setup.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$binDir = Join-Path $root 'bin'

Write-Host '==> XPOTools setup' -ForegroundColor Cyan
Write-Host "    Root:  $root"
Write-Host "    Bin:   $binDir"
Write-Host ''

# 1. Python
try {
    $pyVer = (& python --version) 2>&1
    Write-Host "[ok] Python detected: $pyVer"
    $verMatch = [regex]::Match($pyVer, 'Python (\d+)\.(\d+)')
    if ($verMatch.Success) {
        $major = [int]$verMatch.Groups[1].Value
        $minor = [int]$verMatch.Groups[2].Value
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
            Write-Warning "XPOTools требует Python >= 3.9, у вас $major.$minor"
        }
    }
} catch {
    Write-Error "python не найден в PATH. Установите Python >= 3.9 (https://www.python.org/) и повторите."
    exit 1
}

# 2. PATH
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = @()
if ($userPath) { $entries = $userPath.Split(';', [StringSplitOptions]::RemoveEmptyEntries) }
$alreadyOnPath = $entries | Where-Object { $_.TrimEnd('\') -ieq $binDir.TrimEnd('\') }

if ($alreadyOnPath) {
    Write-Host "[ok] $binDir уже в user PATH"
} else {
    $newPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Host "[+]  $binDir добавлен в user PATH"
}

# 3. config.local.json
$example = Join-Path $root 'config.example.json'
$local   = Join-Path $root 'config.local.json'
if (Test-Path $local) {
    Write-Host "[ok] config.local.json уже существует"
} else {
    if (-not (Test-Path $example)) {
        Write-Warning "config.example.json не найден — пропускаю создание config.local.json"
    } else {
        Copy-Item $example $local
        Write-Host "[+]  config.local.json создан из config.example.json"
        Write-Warning "Откройте config.local.json и заполните ALK_USER_NICK, ALK_AOT_PROD и т.п."
    }
}

Write-Host ''
Write-Host '==> Done.' -ForegroundColor Green
Write-Host '    Откройте новую сессию PowerShell/cmd, чтобы PATH подхватился.'
Write-Host '    Проверка: build-shared-project --help'
