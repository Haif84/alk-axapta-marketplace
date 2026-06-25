@echo off
rem Wrapper for XPOTools/organize-xpo.py.
python "%~dp0..\organize-xpo.py" %*
exit /B %ERRORLEVEL%
