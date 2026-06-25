@echo off
rem Wrapper for XPOTools/cleanup-xpo.py.
python "%~dp0..\cleanup-xpo.py" %*
exit /B %ERRORLEVEL%
