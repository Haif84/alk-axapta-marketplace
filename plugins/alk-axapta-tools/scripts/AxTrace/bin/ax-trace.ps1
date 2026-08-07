#!/usr/bin/env pwsh
# Wrapper for AxTrace/ax-trace.ps1 (управление трассировкой клиента AX 2012).
# ВНИМАНИЕ: этот каталог в PATH сам не попадает — setup добавляет только XPOTools/bin.
# Пока его не добавили вручную, зови скрипты по полному пути от $pluginRoot.
& "$PSScriptRoot\..\ax-trace.ps1" @args
exit $LASTEXITCODE
