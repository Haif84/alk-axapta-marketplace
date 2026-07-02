<#
.SYNOPSIS
    Разовая настройка ENV-переменных ALK для XPOTools и скиллов.

.DESCRIPTION
    Записывает user-level ENV-переменные (HKCU\Environment), которые XPOTools
    читает приоритетно, а скиллы используют как значения по умолчанию:
      - ALK_USER_NICK          — ник разработчика (комментарии модификаций)
      - ALK_AOT_PROD           — путь к боевой выгрузке AOT-Prod (для sync-xpo)
      - ALK_PROJECT_PREFIX     — префикс проектов ALK (по умолчанию ALK_DEVAX12)
      - ALK_IDENTIFIER_PREFIX  — аффикс новых идентификаторов (lowercase, напр. alk_)
      - ALK_IDENTIFIER_SUFFIX  — постфикс-альтернатива PREFIX (обычно пусто)
    Переменные хранятся в профиле пользователя и переживают любые обновления
    плагина. Права администратора не нужны. ENV имеет приоритет над
    config.local.json (который лежит в кэше плагина и стирается при обновлении).

    Дополнительно проверяет наличие Python >= 3.9 (нужен для XPOTools).

.PARAMETER UserNick
    Ник разработчика. Пример: -UserNick akaz

.PARAMETER AotProd
    Путь к боевой выгрузке AOT-Prod. Необязательно.
    Пример: -AotProd "E:\ZeroCoder\Axapta\ERP\AOT-Prod"

.PARAMETER ProjectPrefix
    Префикс проектов ALK. По умолчанию ALK_DEVAX12.

.PARAMETER IdentifierPrefix
    Аффикс новых идентификаторов в нижнем регистре (напр. alk_). Применяется к
    методам/переменным/параметрам в существующих объектах; для новых AOT-объектов
    берётся UPPER-версия (ALK_). Пусто = конвенция именования не применяется.

.PARAMETER IdentifierSuffix
    Постфикс-альтернатива IdentifierPrefix. Обычно пусто. Не задавайте вместе с
    IdentifierPrefix.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File setup-env.ps1 -UserNick akaz
    powershell -NoProfile -ExecutionPolicy Bypass -File setup-env.ps1 -UserNick akaz -AotProd "E:\Axapta\AOT-Prod" -IdentifierPrefix alk_
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UserNick,

    [string]$AotProd = '',

    [string]$ProjectPrefix = 'ALK_DEVAX12',

    [string]$IdentifierPrefix = '',

    [string]$IdentifierSuffix = ''
)

$ErrorActionPreference = 'Stop'

Write-Host '==> ALK Axapta Tools: настройка ENV' -ForegroundColor Cyan
Write-Host ''

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

if ($IdentifierPrefix -and $IdentifierSuffix) {
    Write-Warning "IdentifierPrefix и IdentifierSuffix заданы одновременно — используйте что-то одно. Записываю оба как есть."
}

Set-UserEnv 'ALK_PROJECT_PREFIX'    $ProjectPrefix
Set-UserEnv 'ALK_USER_NICK'         $UserNick
Set-UserEnv 'ALK_AOT_PROD'          $AotProd
Set-UserEnv 'ALK_IDENTIFIER_PREFIX' $IdentifierPrefix
Set-UserEnv 'ALK_IDENTIFIER_SUFFIX' $IdentifierSuffix

Write-Host ''
Write-Host '==> Done.' -ForegroundColor Green
Write-Host '    Откройте новую сессию PowerShell/cmd (или перезапустите VS Code),'
Write-Host '    чтобы ENV-переменные подхватились. Проверка: $env:ALK_USER_NICK'
