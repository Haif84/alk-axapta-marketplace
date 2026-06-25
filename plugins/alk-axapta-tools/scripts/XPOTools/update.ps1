#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Синхронизация XPOTools с remote (git pull --ff-only) + проверка config-схемы.

.DESCRIPTION
  1. git fetch + git pull --ff-only в XPOTools/.
  2. Если в обновлённом config.example.json появились новые ключи, отсутствующие
     в config.local.json — печатает diff (чтобы пользователь добавил их вручную).

.NOTES
  Запускать без параметров: ./update.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

Write-Host "==> Updating XPOTools at $root" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $root '.git'))) {
    Write-Error "$root не является git-репозиторием. Сначала clone:`n  git clone <url> `"$root`""
    exit 1
}

try {
    git -C $root fetch
    git -C $root pull --ff-only
} catch {
    Write-Error "git pull завершился с ошибкой: $_"
    exit 1
}

# Сравнение config keys
$example = Join-Path $root 'config.example.json'
$local   = Join-Path $root 'config.local.json'
if ((Test-Path $example) -and (Test-Path $local)) {
    try {
        $exampleKeys = (Get-Content $example -Raw | ConvertFrom-Json).PSObject.Properties.Name
        $localKeys   = (Get-Content $local   -Raw | ConvertFrom-Json).PSObject.Properties.Name
        $missing = $exampleKeys | Where-Object { $_ -notin $localKeys }
        if ($missing) {
            Write-Host ''
            Write-Warning "В config.example.json есть новые ключи, отсутствующие в вашем config.local.json:"
            $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
            Write-Host ''
            Write-Warning "Откройте config.example.json, скопируйте недостающие ключи в config.local.json и заполните значения."
        }
    } catch {
        Write-Warning "Не удалось распарсить config-файлы: $_"
    }
}

Write-Host ''
Write-Host '==> Done.' -ForegroundColor Green
