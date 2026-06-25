@echo off
rem Wrapper for python -m Modules.fix_mojibake.
pushd "%~dp0.."
python -m Modules.fix_mojibake %*
set RC=%ERRORLEVEL%
popd
exit /B %RC%
