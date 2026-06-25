@echo off
rem Wrapper for python -m Modules.split_shared_project.
pushd "%~dp0.."
python -m Modules.split_shared_project %*
set RC=%ERRORLEVEL%
popd
exit /B %RC%
