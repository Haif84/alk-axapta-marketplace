@echo off
rem Wrapper for XPOTools/sync-xpo.py.
python "%~dp0..\sync-xpo.py" %*
exit /B %ERRORLEVEL%
