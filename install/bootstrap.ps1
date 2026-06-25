<#
.SYNOPSIS
    Разовая настройка рабочего места для использования alk-axapta-tools.

.DESCRIPTION
    1. Проверяет наличие Python >= 3.9.
    2. Записывает user-level ENV-переменные, которые XPOTools читает приоритетно
       (ALK_PROJECT_PREFIX, ALK_USER_NICK, ALK_AOT_PROD).
    3. Устанавливает хук move-plan.ps1: после ExitPlanMode автоматически
       перекладывает планы из ~/.claude/plans/ в <cwd>/plans/.
    Эти переменные переживают обновления плагина, т.к. хранятся в профиле
    пользователя (HKCU\Environment), а не внутри кэша плагина.

.PARAMETER UserNick
    Ваш ник разработчика (используется в комментариях модификаций).
    Пример: -UserNick akaz

.PARAMETER AotProd
    Путь к боевой выгрузке AOT-Prod (используется sync-xpo для сверки с Prod).
    Необязательно — оставьте пустым, если не нужен sync.
    Пример: -AotProd "E:\ZeroCoder\Axapta\ERP\AOT-Prod"

.PARAMETER ProjectPrefix
    Префикс проектов ALK. По умолчанию ALK_DEVAX12.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install\bootstrap.ps1 -UserNick akaz
    powershell -ExecutionPolicy Bypass -File .\install\bootstrap.ps1 -UserNick akaz -AotProd "E:\ZeroCoder\Axapta\ERP\AOT-Prod"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UserNick,

    [string]$AotProd = '',

    [string]$ProjectPrefix = 'ALK_DEVAX12'
)

$ErrorActionPreference = 'Stop'

Write-Host '==> ALK Axapta Tools: bootstrap' -ForegroundColor Cyan
Write-Host ''

# 1. Python
try {
    $pyVer = (& python --version) 2>&1
    $verMatch = [regex]::Match($pyVer, 'Python (\d+)\.(\d+)')
    if ($verMatch.Success) {
        $major = [int]$verMatch.Groups[1].Value
        $minor = [int]$verMatch.Groups[2].Value
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
            Write-Error "XPOTools требует Python >= 3.9, обнаружен $major.$minor. Обновите Python и повторите."
            exit 1
        }
        Write-Host "[ok] Python $major.$minor"
    } else {
        Write-Warning "Не удалось распознать версию Python из: $pyVer"
    }
} catch {
    Write-Error "Python не найден в PATH. Установите Python >= 3.9 (https://www.python.org/) и повторите."
    exit 1
}

# 2. ENV-переменные (user-level, без прав администратора)
function Set-UserEnv {
    param([string]$Name, [string]$Value)
    $current = [Environment]::GetEnvironmentVariable($Name, 'User')
    if ($current -eq $Value) {
        Write-Host "[ok] $Name уже задан: $Value"
    } else {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
        if ($current) {
            Write-Host "[~]  $Name обновлён: $current -> $Value"
        } else {
            Write-Host "[+]  $Name = $Value"
        }
    }
}

Set-UserEnv 'ALK_PROJECT_PREFIX' $ProjectPrefix
Set-UserEnv 'ALK_USER_NICK'      $UserNick
Set-UserEnv 'ALK_AOT_PROD'       $AotProd

# 3. Хук move-plan: после ExitPlanMode копирует план в <cwd>/plans/
$hooksDir   = Join-Path $env:USERPROFILE '.claude\hooks'
$hookSrc    = Join-Path $PSScriptRoot '..\plugins\alk-hooks-plans2project\scripts\hooks\move-plan.ps1'
$hookDst    = Join-Path $hooksDir 'move-plan.ps1'

New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null

if (Test-Path $hookSrc) {
    Copy-Item -Path $hookSrc -Destination $hookDst -Force
    Write-Host "[+]  move-plan.ps1 -> $hookDst"
} else {
    Write-Warning "Хук не найден: $hookSrc — пропускаю."
}

# Прописываем хук в ~/.claude/settings.json
$settingsPath = Join-Path $env:USERPROFILE '.claude\settings.json'
$settings = if (Test-Path $settingsPath) {
    Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
    [PSCustomObject]@{}
}

if (-not $settings.PSObject.Properties['hooks']) {
    $settings | Add-Member -NotePropertyName 'hooks' -NotePropertyValue ([PSCustomObject]@{})
}
if (-not $settings.hooks.PSObject.Properties['PostToolUse']) {
    $settings.hooks | Add-Member -NotePropertyName 'PostToolUse' -NotePropertyValue @()
}

$already = $settings.hooks.PostToolUse | Where-Object { $_.matcher -eq 'ExitPlanMode' }
if (-not $already) {
    $newEntry = [PSCustomObject]@{
        matcher = 'ExitPlanMode'
        hooks   = @(
            [PSCustomObject]@{
                type    = 'command'
                command = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$hookDst`""
            }
        )
    }
    $arr = [System.Collections.Generic.List[object]]($settings.hooks.PostToolUse)
    $arr.Add($newEntry)
    $settings.hooks.PostToolUse = $arr.ToArray()
    $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Encoding UTF8
    Write-Host "[+]  ExitPlanMode hook прописан в $settingsPath"
} else {
    Write-Host "[ok] ExitPlanMode hook уже прописан"
}

Write-Host ''
Write-Host '==> Done.' -ForegroundColor Green
Write-Host '    Откройте новую сессию PowerShell/cmd, чтобы ENV-переменные подхватились.'
Write-Host '    Проверка: $env:ALK_USER_NICK'
