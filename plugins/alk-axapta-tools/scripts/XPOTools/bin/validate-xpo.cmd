@echo off
rem Wrapper for python -m Modules.validate_xpo.
pushd "%~dp0.."
python -m Modules.validate_xpo %*
set RC=%ERRORLEVEL%
popd
exit /B %RC%
