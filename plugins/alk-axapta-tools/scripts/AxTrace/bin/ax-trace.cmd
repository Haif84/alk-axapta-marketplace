@echo off
rem Wrapper for AxTrace/ax-trace.ps1.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\ax-trace.ps1" %*
exit /B %ERRORLEVEL%
