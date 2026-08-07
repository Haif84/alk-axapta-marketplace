#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Управление трассировкой клиента Microsoft Dynamics AX 2012.

.DESCRIPTION
    Создаёт и ведёт набор сборщиков данных с поставщиком Microsoft-DynamicsAX-Tracing —
    единственным источником, который показывает ИМЕНА методов X++, форму-источник
    и уровень вложенности. Ни дампы, ни ETW-трассировка RPC этого не дают.

    Права. Создание набора (setup) требует администратора всегда. Остальные действия
    доступны без повышения члену группы «Пользователи журналов производительности»
    (SID S-1-5-32-559) — но членство учитывается только с ближайшего входа в систему,
    так что после добавления в группу надо перезайти. Скрипт проверяет доступ сам
    и запрашивает UAC, только когда без него не обойтись.

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

function ConvertTo-QuotedArg([string]$Value) {
    <#  Start-Process склеивает -ArgumentList пробелами и НЕ кавычит элементы сам.
        Имя набора по умолчанию — «AX Trace», с пробелом: без кавычек дочерний
        процесс получал «-Name AX Trace», падал на разборе аргументов и не создавал
        файл-реле, а вызывающий винил в этом UAC. Кавычим каждый элемент сами.
        Хвостовые обратные слэши удваиваем: в "C:\traces\" последний слэш иначе
        экранирует закрывающую кавычку и склеивает аргумент со следующим. #>
    if ($null -eq $Value) { return '""' }
    return '"' + ([regex]::Replace($Value, '(\\+)$', '$1$1')) + '"'
}

function Invoke-Elevated {
    <#  Перезапускает себя с повышением. Вывод дочернего процесса иначе теряется,
        поэтому он пишет его в файл, а мы показываем содержимое. #>
    $relay = [IO.Path]::Combine([IO.Path]::GetTempPath(), "axtrace-$([guid]::NewGuid()).txt")

    # Dest разрешаем в абсолютный путь: UAC запускает повышенный процесс в System32,
    # и относительный путь увёл бы туда копию трассировки. Resolve-Path тут не годится —
    # он молча не срабатывает на ещё не созданной папке, а именно её обычно и просят.
    $destAbs = try {
        [IO.Path]::GetFullPath([IO.Path]::Combine((Get-Location).ProviderPath, $Dest))
    } catch { $Dest }

    $argv = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', (ConvertTo-QuotedArg $PSCommandPath),
        $Action,
        '-Name', (ConvertTo-QuotedArg $Name),
        '-MaxMB', $MaxMB,
        '-Dest', (ConvertTo-QuotedArg $destAbs),
        '-RelayFile', (ConvertTo-QuotedArg $relay)
    )
    if ($Path) { $argv += @('-Path', (ConvertTo-QuotedArg $Path)) }
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

function Test-PlaAccess {
    <#  Отвечает ли служба журналов производительности этому пользователю.
        Членства в «Пользователях журналов производительности» (S-1-5-32-559) хватает
        для query/start/stop, и тогда дёргать UAC на каждый замер незачем.
        Проверено на стенде: без членства — Access Denied, с членством и после
        перезахода — успех; создание набора при этом всё равно отказано.
        Важно: «набор не найден» — тоже успешный ответ службы, доступ есть. #>
    $out = & logman.exe query $Name 2>&1
    if ($LASTEXITCODE -eq 0) { return $true }
    return (($out -join ' ') -notmatch 'Access is denied|Отказано в доступе')
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

# Повышаемся только там, где без него не обойтись. setup создаёт и удаляет набор —
# правами группы это не покрывается, там UAC обязателен. Для остальных действий
# сперва спрашиваем службу: если она отвечает, идём без повышения — иначе профилирование
# превращается в череду запросов UAC на каждый start/stop.
if (-not (Test-Admin)) {
    if ($Action -eq 'setup' -or -not (Test-PlaAccess)) { Invoke-Elevated }
}

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
