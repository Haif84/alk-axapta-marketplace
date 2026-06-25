#!/usr/bin/env pwsh
# Wrapper for python -m Modules.fix_mojibake.
Push-Location "$PSScriptRoot\.."
try { & python -m Modules.fix_mojibake @args; $code = $LASTEXITCODE }
finally { Pop-Location }
exit $code
