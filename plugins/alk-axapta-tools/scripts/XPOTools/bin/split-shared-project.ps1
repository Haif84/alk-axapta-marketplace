#!/usr/bin/env pwsh
# Wrapper for python -m Modules.split_shared_project.
Push-Location "$PSScriptRoot\.."
try { & python -m Modules.split_shared_project @args; $code = $LASTEXITCODE }
finally { Pop-Location }
exit $code
