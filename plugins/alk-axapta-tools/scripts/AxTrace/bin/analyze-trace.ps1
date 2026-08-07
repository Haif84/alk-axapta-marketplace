#!/usr/bin/env pwsh
# Wrapper for AxTrace/analyze-trace.py (разбор трассировки клиента AX 2012).
# This file lives in AxTrace/bin/ which is added to user $env:PATH by setup.ps1.
& python "$PSScriptRoot\..\analyze-trace.py" @args
exit $LASTEXITCODE
