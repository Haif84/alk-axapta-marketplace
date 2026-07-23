#!/usr/bin/env pwsh
Push-Location "$PSScriptRoot\.."
try { & python .\build-resource-xpo.py @args; $code = $LASTEXITCODE }
finally { Pop-Location }
exit $code
