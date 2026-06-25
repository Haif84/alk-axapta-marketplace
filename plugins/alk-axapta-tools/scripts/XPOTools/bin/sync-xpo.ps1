#!/usr/bin/env pwsh
# Wrapper for XPOTools/sync-xpo.py.
& python "$PSScriptRoot\..\sync-xpo.py" @args
exit $LASTEXITCODE
