#!/usr/bin/env pwsh
# Wrapper for XPOTools/organize-xpo.py.
# This file lives in XPOTools/bin/ which is added to user $env:PATH by setup.ps1.
& python "$PSScriptRoot\..\organize-xpo.py" @args
exit $LASTEXITCODE
