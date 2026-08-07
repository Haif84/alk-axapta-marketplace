@echo off
rem Wrapper for AxTrace/analyze-trace.py.
python "%~dp0..\analyze-trace.py" %*
exit /B %ERRORLEVEL%
