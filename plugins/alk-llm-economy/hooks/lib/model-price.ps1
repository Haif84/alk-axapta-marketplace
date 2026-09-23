# Цена модели для денежных оценок в текстах хуков, $/MTok: вход (in) и чтение
# кэша (cr). Источник один — scripts/prices.js рядом с hooks/: таблица читается
# регуляркой, второй копии цен в PowerShell нет, и смена цен правится в одном месте.
# Неизвестная модель (<synthetic>, новая, нет prices.js) — цена Opus 5: на ней
# калибровались оценки хуков, и ошибиться лучше в сторону дороже.
# Dot-source it as: . (Join-Path $PSScriptRoot 'lib\model-price.ps1')
$ModelPricesJs = Join-Path $PSScriptRoot '..\..\scripts\prices.js'

function Get-ModelPrice {
    param([string]$Model)
    $id = (($Model -replace '\[1m\]$', '') -replace '-[0-9]{8}$', '').Trim().ToLowerInvariant()
    if ($id -and (Test-Path -LiteralPath $ModelPricesJs)) {
        $text = [IO.File]::ReadAllText($ModelPricesJs)
        foreach ($m in [regex]::Matches($text, "'([a-z0-9.-]+)'\s*:\s*\{\s*in:\s*([0-9.]+)\s*,\s*cr:\s*([0-9.]+)")) {
            if ($m.Groups[1].Value -eq $id) {
                $inv = [cultureinfo]::InvariantCulture
                return @{ in = [double]::Parse($m.Groups[2].Value, $inv); cr = [double]::Parse($m.Groups[3].Value, $inv) }
            }
        }
    }
    return @{ in = 5.0; cr = 0.5 }
}
