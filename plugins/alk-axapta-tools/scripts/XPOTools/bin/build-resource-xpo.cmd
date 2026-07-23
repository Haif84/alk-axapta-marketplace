@echo off
REM Wrapper — prefer build-resource-xpo.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-resource-xpo.ps1" %*
