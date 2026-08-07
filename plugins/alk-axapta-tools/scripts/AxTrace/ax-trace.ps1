#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Управление трассировкой клиента Microsoft Dynamics AX 2012.

.DESCRIPTION
    Создаёт и ведёт набор сборщиков данных с поставщиком Microsoft-DynamicsAX-Tracing —
    единственным источником, который показывает ИМЕНА методов X++, форму-источник
    и уровень вложенности. Ни дампы, ни ETW-трассировка RPC этого не дают.

    ВСЕ действия требуют прав администратора: набор работает от имени СИСТЕМА,
    из обычной сессии logman отвечает Access Denied, а файл в его папке не прочитать.
    Скрипт сам перезапустится с повышением и вернёт вывод.

.PARAMETER Action
    setup   создать набор (спросит путь, если не задан ключом -Path)
    start   начать запись
    stop    остановить запись
    status  показать состояние и параметры
    fetch   скопировать свежий .etl в доступную папку и выдать права на чтение

.PARAMETER Name
    Имя набора сборщиков. По умолчанию "AX Trace".

.PARAMETER Path
    Куда набор пишет .etl. Только для setup. Каталог должен быть доступен СИСТЕМЕ —
    профиль пользователя не годится. По умолчанию предлагается C:\ProgramData\AxTrace.

.PARAMETER MaxMB
    Предел размера файла, МБ. По умолчанию 512.
    Буфер КОЛЬЦЕВОЙ: при достижении предела старые события вытесняются новыми,
    запись не обрывается. Нециклический набор на горячем клиенте (до 1 ГБ/мин)
    выбирает 2 ГБ за две минуты и молча останавливается.

.PARAMETER Dest
    Куда копировать .etl при fetch. По умолчанию текущий каталог.

.PARAMETER Force
    Для setup: пересоздать набор, если он уже есть.

.EXAMPLE
    .\ax-trace.ps1 setup -Path C:\ProgramData\AxTrace -MaxMB 512
    .\ax-trace.ps1 start
    .\ax-trace.ps1 stop
    .\ax-trace.ps1 fetch -Dest .\traces
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('setup', 'start', 'stop', 'status', 'fetch')]
    [string]$Action,

    [string]$Name = 'AX Trace',
    [string]$Path,
    [int]$MaxMB = 512,
    [string]$Dest = '.',
    [switch]$Force,

    # Служебный: путь к файлу, куда повышенный экземпляр пишет вывод. Не задавать вручную.
    [string]$RelayFile
)

$ErrorActionPreference = 'Stop'

# Поставщик трассировки AX. Ключевые слова 0x3bf =
# XppMarker, TraceInfo, RPC, XPP, SQL, DatabaseDetailed, BindParameter, AxUtilFunc, XPPParm.
$ProviderName = 'Microsoft-DynamicsAX-Tracing'
$Keywords = '0x3bf'
$Level = '0xff'
$DefaultPath = 'C:\ProgramData\AxTrace'

# --- вывод: в стандартный поток (чтобы вызывающий скрипт мог перехватить)
#     и, если мы повышенный экземпляр, в файл-реле ---
$script:Lines = @()
function Say([string]$Message) {
    $script:Lines += $Message
    Write-Output $Message
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Elevated {
    <#  Перезапускает себя с повышением. Вывод дочернего процесса иначе теряется,
        поэтому он пишет его в файл, а мы показываем содержимое. #>
    $relay = [IO.Path]::Combine([IO.Path]::GetTempPath(), "axtrace-$([guid]::NewGuid()).txt")

    # Dest разрешаем в абсолютный путь: у повышенного процесса другой текущий каталог
    $destAbs = $Dest
    $resolved = Resolve-Path -LiteralPath $Dest -ErrorAction SilentlyContinue
    if ($resolved) { $destAbs = $resolved.Path }

    $argv = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $PSCommandPath,
        $Action,
        '-Name', $Name,
        '-MaxMB', $MaxMB,
        '-Dest', $destAbs,
        '-RelayFile', $relay
    )
    if ($Path) { $argv += @('-Path', $Path) }
    if ($Force) { $argv += '-Force' }

    Write-Host "Требуются права администратора — подтвердите запрос UAC..."
    try {
        $proc = Start-Process -FilePath (Get-Process -Id $PID).Path `
            -ArgumentList $argv -Verb RunAs -PassThru -WindowStyle Hidden
        $proc.WaitForExit(300000) | Out-Null
    } catch {
        Write-Host "Повышение отклонено. Запусти PowerShell от имени администратора и повтори."
        exit 2
    }

    if (Test-Path $relay) {
        Get-Content $relay -Encoding UTF8 | ForEach-Object { Write-Host $_ }
        Remove-Item $relay -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "Повышенный экземпляр не вернул результат (возможно, UAC отклонён)."
        exit 2
    }
    exit 0
}

function Get-SetExists {
    $null = & logman.exe query $Name 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Show-Status {
    # Ничего не возвращает в конвейер: весь вывод идёт через Say, иначе вызывающий
    # код с "| Out-Null" проглотил бы полезные строки вместе со служебным значением.
    $out = & logman.exe query $Name 2>&1
    if ($LASTEXITCODE -ne 0) {
        Say "Набор «$Name» не найден. Создай его: ax-trace.ps1 setup"
        return
    }
    foreach ($line in $out) {
        $t = ($line -replace '\s+', ' ').Trim()
        if ($t -match '^(Имя|Name|Состояние|Status|Корневой путь|Root Path|Размещение вывода|Output Location|Максимальный размер|Maximum|Поставщик|Provider|Keywords|Level)') {
            Say "  $t"
        }
    }
}

# --- действия ---------------------------------------------------------------

function Initialize-TraceSet {
    if ((Get-SetExists) -and -not $Force) {
        Say "Набор «$Name» уже существует. Текущие параметры:"
        Show-Status
        Say ""
        Say "Пересоздать с новыми параметрами: ax-trace.ps1 setup -Force -Path <путь>"
        return
    }

    if ((Get-SetExists) -and $Force) {
        & logman.exe stop $Name 2>&1 | Out-Null
        & logman.exe delete $Name 2>&1 | Out-Null
        Say "Прежний набор удалён."
    }

    $target = if ($Path) { $Path } else { $DefaultPath }
    if (-not (Test-Path $target)) {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Say "Создан каталог: $target"
    }

    # Имя файла собирается из двух частей, и обе нужны:
    #   метка времени в базовом имени — уникальна для каждого создания набора.
    #     Без неё пересозданный набор обнуляет счётчик и натыкается на файлы
    #     прошлых прогонов: «Невозможно создать файл, так как он уже существует»;
    #   -v nnnnnn — автоинкремент на каждый start внутри одного набора.
    #     Штамп времени вместо счётчика (-v mmddhhmm) не годится: старт и рестарт
    #     в пределах одной минуты дают одинаковое имя и ту же ошибку.
    # Побочная польза: каждый замер в своём файле, прогоны «до» и «после» правки
    # можно сравнивать между собой.
    $base = 'AxTrace-{0}' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
    $out = & logman.exe create trace $Name -p $ProviderName $Keywords $Level `
        -o (Join-Path $target $base) -f bincirc -max $MaxMB -v nnnnnn 2>&1
    if ($LASTEXITCODE -ne 0) {
        Say "Не удалось создать набор:"
        $out | ForEach-Object { Say "  $(($_ -replace '\s+',' ').Trim())" }
        exit 1
    }

    Say "Набор «$Name» создан."
    Say "  поставщик:       $ProviderName"
    Say "  ключевые слова:  $Keywords (XppMarker, TraceInfo, RPC, XPP, SQL, DatabaseDetailed, BindParameter, AxUtilFunc, XPPParm)"
    Say "  каталог:         $target"
    Say "  предел файла:    $MaxMB МБ, буфер КОЛЬЦЕВОЙ (запись не оборвётся)"
    Say ""
    Say "Дальше: ax-trace.ps1 start"
}

function Start-Capture {
    if (-not (Get-SetExists)) { Say "Набор «$Name» не найден. Сначала: ax-trace.ps1 setup"; exit 1 }
    $out = & logman.exe start $Name 2>&1
    if ($LASTEXITCODE -ne 0) {
        Say "Не удалось запустить:"
        $out | ForEach-Object { Say "  $(($_ -replace '\s+',' ').Trim())" }
        exit 1
    }
    Say "Запись начата: $(Get-Date -Format 'HH:mm:ss')"
    Show-Status
    Say ""
    Say "Включай прицельно: воспроизведи проблему и сразу останови — ax-trace.ps1 stop"
}

function Stop-Capture {
    if (-not (Get-SetExists)) { Say "Набор «$Name» не найден."; exit 1 }
    $out = & logman.exe stop $Name 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = ($out -join ' ')
        if ($joined -match 'не запущен|not running') {
            Say "Набор уже остановлен."
        } else {
            Say "Не удалось остановить:"
            $out | ForEach-Object { Say "  $(($_ -replace '\s+',' ').Trim())" }
            exit 1
        }
    } else {
        Say "Запись остановлена: $(Get-Date -Format 'HH:mm:ss')"
    }
    Say ""
    Say "Забрать файл: ax-trace.ps1 fetch -Dest <папка>"
}

function Copy-LatestTrace {
    $q = & logman.exe query $Name 2>&1
    if ($LASTEXITCODE -ne 0) { Say "Набор «$Name» не найден."; exit 1 }

    $root = ($q | Select-String -Pattern '(Корневой путь|Root Path)\s*:\s*(.+)$' |
        ForEach-Object { $_.Matches[0].Groups[2].Value.Trim() } | Select-Object -First 1)
    if ($root) { $root = [Environment]::ExpandEnvironmentVariables($root) }
    if (-not $root -or -not (Test-Path $root)) { $root = $DefaultPath }

    $etl = Get-ChildItem $root -Recurse -Filter '*.etl' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $etl) { Say "В «$root» файлов .etl нет. Запись хоть раз запускалась?"; exit 1 }

    if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest -Force | Out-Null }
    $stamp = $etl.LastWriteTime.ToString('yyyyMMdd-HHmm')
    $target = Join-Path (Resolve-Path $Dest) "axtrace-$stamp.etl"

    Copy-Item -LiteralPath $etl.FullName -Destination $target -Force
    # файл создан СИСТЕМОЙ — без явных прав его не прочитать под обычной учёткой
    & icacls.exe $target /grant "$($env:USERNAME):(R)" 2>&1 | Out-Null

    $mb = (Get-Item $target).Length / 1MB
    Say "Скопирован: $target"
    Say "  размер: $([math]::Round($mb,2)) МБ  (запись от $($etl.LastWriteTime.ToString('dd.MM HH:mm:ss')))"
    Say ""
    Say "Разбор: python analyze-trace.py summary `"$target`""
}

# --- точка входа ------------------------------------------------------------

if (-not (Test-Admin)) { Invoke-Elevated }

try {
    switch ($Action) {
        'setup'  { Initialize-TraceSet }
        'start'  { Start-Capture }
        'stop'   { Stop-Capture }
        'status' { Show-Status }
        'fetch'  { Copy-LatestTrace }
    }
} finally {
    if ($RelayFile) {
        $script:Lines | Set-Content -LiteralPath $RelayFile -Encoding UTF8
    }
}
