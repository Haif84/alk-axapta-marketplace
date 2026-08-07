#!/usr/bin/env pwsh
# Wrapper for AxTrace/ax-trace.ps1 (управление трассировкой клиента AX 2012).
# This file lives in AxTrace/bin/ which is added to user $env:PATH by setup.ps1.
& "$PSScriptRoot\..\ax-trace.ps1" @args
exit $LASTEXITCODE
