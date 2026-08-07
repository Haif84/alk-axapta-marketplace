@echo off
rem Wrapper for AxTrace/ax-trace.ps1.
rem powershell, а не pwsh: PowerShell 7 на рабочей машине AX штатно не стоит.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\ax-trace.ps1" %*
exit /B %ERRORLEVEL%
