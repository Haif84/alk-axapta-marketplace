# Claude Code statusline -- Windows PowerShell (ASCII only for PS 5.1 compatibility)
# Reads session JSON from stdin and prints a single status line.
$ErrorActionPreference = 'SilentlyContinue'

$raw = [Console]::In.ReadToEnd()
if (-not $raw) { return }
$d = $raw | ConvertFrom-Json

# ANSI helpers
$e   = [char]27
$dim = "$e[2m"; $cyan = "$e[36m"; $grn = "$e[32m"; $yel = "$e[33m"; $red = "$e[31m"; $rst = "$e[0m"

$model = $d.model.display_name
$dir   = Split-Path -Leaf $d.workspace.current_dir
$cost  = [double]$d.cost.total_cost_usd
$add   = [int]$d.cost.total_lines_added
$del   = [int]$d.cost.total_lines_removed

$sep = "$dim | $rst"
$parts = @()
$parts += "$cyan$model$rst"
# Effort: дефолт high, но уровни S и M идут на medium (global/CLAUDE.md).
# Живое значение с учётом /effort внутри сессии; поля нет, если модель без effort.
$eff = $d.effort.level
if ($eff) {
  $c = if ($eff -in 'high', 'xhigh', 'max') { $yel } else { $dim }
  $parts += "$c$eff$rst"
}
$parts += "$dim[$rst$dir$dim]$rst"
$parts += "$grn`$$('{0:N2}' -f $cost)$rst"
if ($add -or $del) { $parts += "$grn+$add$rst/$red-$del$rst" }
# Контекст: бюджет 100k токенов -- пора /remember и новую сессию (docs/decisions/2026-09-12-cycle-tiers.md).
# Порог в токенах, не в процентах: окно у всех моделей 1M, и 50% окна = 500k,
# а цена хода растёт с абсолютным объёмом перечитываемого контекста.
$pct = [double]$d.context_window.used_percentage
$tok = [int]$d.context_window.total_input_tokens
if ($pct -gt 0 -or $tok -gt 0) {
  $c = if ($tok -ge 150000) { $red } elseif ($tok -ge 100000) { $yel } else { $dim }
  $parts += "$c" + "ctx $([int]$pct)% $('{0:N0}' -f ($tok / 1000))k$rst"
}
elseif ($d.exceeds_200k_tokens) { $parts += "$yel>200k ctx$rst" }

Write-Output ($parts -join $sep)
