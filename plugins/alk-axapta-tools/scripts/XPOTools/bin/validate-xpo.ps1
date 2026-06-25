#!/usr/bin/env pwsh
# Wrapper for python -m Modules.validate_xpo.
# Push-Location нужен, чтобы `python -m` нашёл пакет Modules в XPOTools/.
Push-Location "$PSScriptRoot\.."
try { & python -m Modules.validate_xpo @args; $code = $LASTEXITCODE }
finally { Pop-Location }
exit $code
