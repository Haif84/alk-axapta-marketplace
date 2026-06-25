@echo off
rem Wrapper for XPOTools/build-shared-project.py.
python "%~dp0..\build-shared-project.py" %*
exit /B %ERRORLEVEL%
