#!/usr/bin/env pwsh
# Wrapper for XPOTools/build-shared-project.py.
# This file lives in XPOTools/bin/ which is added to user $env:PATH by setup.ps1.
& python "$PSScriptRoot\..\build-shared-project.py" @args
exit $LASTEXITCODE
