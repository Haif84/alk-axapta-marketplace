#!/usr/bin/env pwsh
# Wrapper for XPOTools/cleanup-xpo.py.
& python "$PSScriptRoot\..\cleanup-xpo.py" @args
exit $LASTEXITCODE
