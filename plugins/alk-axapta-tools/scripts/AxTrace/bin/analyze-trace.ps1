#!/usr/bin/env pwsh
# Wrapper for AxTrace/analyze-trace.py (разбор трассировки клиента AX 2012).
# ВНИМАНИЕ: этот каталог в PATH сам не попадает — setup добавляет только XPOTools/bin.
# Пока его не добавили вручную, зови скрипты по полному пути от $pluginRoot.
& python "$PSScriptRoot\..\analyze-trace.py" @args
exit $LASTEXITCODE
