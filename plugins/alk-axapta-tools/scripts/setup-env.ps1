<#
.SYNOPSIS
    Разовая настройка ENV-переменных AX для XPOTools и скиллов.

.DESCRIPTION
    Записывает user-level ENV-переменные (HKCU\Environment), которые XPOTools
    читает приоритетно, а скиллы требуют перед началом работы (preflight-гейт):
      - AX_USER_NICK      — ник разработчика (комментарии модификаций)      [обязательно]
      - AX_AOT_PATH       — путь к боевой выгрузке AOT-Prod (для sync-xpo)  [обязательно]
      - AX_PROJECT_ID     — префикс проектов ALK (напр. ALK_DEVAX12)        [обязательно]
      - AX_OBJECT_PREFIX  — аффикс новых идентификаторов, lowercase (alk_)  [ровно один
      - AX_OBJECT_SUFFIX  — постфикс-альтернатива PREFIX                    из этих двух]
    Все пять переменных обязательны. Пара PREFIX/SUFFIX — взаимоисключающая:
    должен быть задан ровно один из двух, не оба и не ни одного.

    Переменные хранятся в профиле пользователя и переживают любые обновления
    плагина. Права администратора не нужны. ENV имеет приоритет над
    config.local.json (который лежит в кэше плагина и стирается при обновлении).

    Если на машине остались старые ALK_-переменные (до переименования в AX_),
    скрипт подхватывает их как значения по умолчанию для одноимённых новых
    параметров и удаляет старые после успешной записи новых.

    Дополнительно проверяет наличие Python >= 3.9 (нужен для XPOTools).

.PARAMETER UserNick
    Ник разработчика. Обязательно. Пример: -UserNick akaz

.PARAMETER AotPath
    Путь к боевой выгрузке AOT-Prod. Обязательно.
    Пример: -AotPath "E:\ZeroCoder\Axapta\ERP\AOT-Prod"

.PARAMETER ProjectId
    Префикс проектов ALK. Обязательно. Пример: -ProjectId ALK_DEVAX12

.PARAMETER ObjectPrefix
    Аффикс новых идентификаторов в нижнем регистре (напр. alk_). Применяется к
    методам/переменным/параметрам в существующих объектах; для новых AOT-объектов
    берётся UPPER-версия (ALK_). Ровно один из ObjectPrefix/ObjectSuffix обязателен.

.PARAMETER ObjectSuffix
    Постфикс-альтернатива ObjectPrefix. Ровно один из двух обязателен — не задавайте
    оба одновременно.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File setup-env.ps1 -UserNick akaz -AotPath "E:\Axapta\AOT-Prod" -ProjectId ALK_DEVAX12 -ObjectPrefix alk_
#>

[CmdletBinding()]
param(
    # Не [Parameter(Mandatory)] — вместо этого дефолт из старой ALK_-переменной
    # (реальная миграция), с явной проверкой "непусто" ниже. Так пользователь,
    # уже настроивший ALK_USER_NICK, может просто перезапустить setup без
    # аргумента и получить перенос значения на новое имя.
    [string]$UserNick     = [Environment]::GetEnvironmentVariable('ALK_USER_NICK', 'User'),

    [string]$AotPath      = [Environment]::GetEnvironmentVariable('ALK_AOT_PROD', 'User'),

    [string]$ProjectId    = [Environment]::GetEnvironmentVariable('ALK_PROJECT_PREFIX', 'User'),

    [string]$ObjectPrefix = [Environment]::GetEnvironmentVariable('ALK_IDENTIFIER_PREFIX', 'User'),

    [string]$ObjectSuffix = [Environment]::GetEnvironmentVariable('ALK_IDENTIFIER_SUFFIX', 'User')
)

$ErrorActionPreference = 'Stop'

Write-Host '==> ALK Axapta Tools: настройка ENV' -ForegroundColor Cyan
Write-Host ''

# Все пять — обязательны. Проверяем явно (не через [Parameter(Mandatory)]),
# чтобы дефолты-из-старых-переменных выше могли закрыть требование без
# повторного ввода пользователем.
$missing = @()
if ([string]::IsNullOrWhiteSpace($UserNick))  { $missing += 'UserNick (-UserNick akaz)' }
if ([string]::IsNullOrWhiteSpace($AotPath))   { $missing += 'AotPath (-AotPath "E:\...\AOT-Prod")' }
if ([string]::IsNullOrWhiteSpace($ProjectId)) { $missing += 'ProjectId (-ProjectId ALK_DEVAX12)' }

# Взаимоисключающая пара — ровно один должен быть задан
$prefixSet = -not [string]::IsNullOrWhiteSpace($ObjectPrefix)
$suffixSet = -not [string]::IsNullOrWhiteSpace($ObjectSuffix)
if ($prefixSet -and $suffixSet) {
    throw "ObjectPrefix и ObjectSuffix заданы одновременно ('$ObjectPrefix' / '$ObjectSuffix') — нужен ровно один. Ничего не записано."
}
if (-not $prefixSet -and -not $suffixSet) {
    $missing += 'ObjectPrefix ИЛИ ObjectSuffix (ровно один, например -ObjectPrefix alk_)'
}

if ($missing.Count -gt 0) {
    throw "Не заданы обязательные параметры и не найдены в старых ALK_-переменных:`n  - $($missing -join "`n  - ")`nНичего не записано."
}

# Python (нужен для XPOTools) — предупреждаем, но не блокируем настройку ENV
try {
    $pyVer = (& python --version) 2>&1
    $verMatch = [regex]::Match($pyVer, 'Python (\d+)\.(\d+)')
    if ($verMatch.Success) {
        $major = [int]$verMatch.Groups[1].Value
        $minor = [int]$verMatch.Groups[2].Value
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
            Write-Warning "XPOTools требует Python >= 3.9, обнаружен $major.$minor. Обновите Python."
        } else {
            Write-Host "[ok] Python $major.$minor"
        }
    } else {
        Write-Warning "Не удалось распознать версию Python из: $pyVer"
    }
} catch {
    Write-Warning "Python не найден в PATH. XPOTools потребует Python >= 3.9 (https://www.python.org/)."
}

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

function Remove-UserEnv {
    param([string]$Name)
    if ([Environment]::GetEnvironmentVariable($Name, 'User')) {
        [Environment]::SetEnvironmentVariable($Name, $null, 'User')
        Write-Host "[-]  $Name удалён (мигрировано в новое имя)"
    }
}

# Старые ALK_-переменные уже подхвачены как дефолты параметров выше (реальная
# миграция значений). Здесь только диагностика + удаление после успешной записи
# новых AX_-имён, чтобы не оставлять задвоенный, потенциально расходящийся конфиг.
$legacyMap = @{
    'ALK_USER_NICK'          = 'AX_USER_NICK'
    'ALK_AOT_PROD'           = 'AX_AOT_PATH'
    'ALK_PROJECT_PREFIX'     = 'AX_PROJECT_ID'
    'ALK_IDENTIFIER_PREFIX'  = 'AX_OBJECT_PREFIX'
    'ALK_IDENTIFIER_SUFFIX'  = 'AX_OBJECT_SUFFIX'
}
$legacyFound = @($legacyMap.Keys | Where-Object { [Environment]::GetEnvironmentVariable($_, 'User') })
if ($legacyFound.Count -gt 0) {
    Write-Host "[i] Найдены старые переменные (будут удалены после записи новых): $($legacyFound -join ', ')" -ForegroundColor Yellow
}

Set-UserEnv 'AX_PROJECT_ID'    $ProjectId
Set-UserEnv 'AX_USER_NICK'     $UserNick
Set-UserEnv 'AX_AOT_PATH'      $AotPath
Set-UserEnv 'AX_OBJECT_PREFIX' $ObjectPrefix
Set-UserEnv 'AX_OBJECT_SUFFIX' $ObjectSuffix

foreach ($old in $legacyFound) { Remove-UserEnv $old }

Write-Host ''
Write-Host '==> Done.' -ForegroundColor Green
Write-Host '    Откройте новую сессию PowerShell/cmd (или перезапустите VS Code),'
Write-Host '    чтобы ENV-переменные подхватились. Проверка: $env:AX_USER_NICK'
