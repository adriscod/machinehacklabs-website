@echo off
REM Windows launcher — run from this folder or pass a full path to a STEP/STL.
setlocal
cd /d "%~dp0"
python -m mhl_quote %*
exit /b %ERRORLEVEL%
