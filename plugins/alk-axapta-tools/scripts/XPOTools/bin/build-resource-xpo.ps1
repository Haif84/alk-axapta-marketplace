#!/usr/bin/env pwsh
# Wrapper for XPOTools/build-resource-xpo.py.
# This file lives in XPOTools/bin/ which is added to user $env:PATH by setup.ps1.
# Run from the caller's cwd (like the sibling wrappers) so relative --file/--out
# resolve against the user's task folder, not the tool install dir.
& python "$PSScriptRoot\..\build-resource-xpo.py" @args
exit $LASTEXITCODE
