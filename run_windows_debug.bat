@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if not exist "logs" mkdir "logs" >nul 2>nul
set "LOG=logs\last_run_windows_debug.log"
echo ================================================ > "%LOG%"
echo GFAM debug launcher started at %DATE% %TIME% >> "%LOG%"
echo Project folder: %CD% >> "%LOG%"
echo ================================================ >> "%LOG%"
echo [*] Debug mode. Output is also saved to: %CD%\%LOG%
echo.
call "%CD%\run_windows.bat" 1>>"%LOG%" 2>>&1
set "EXITCODE=%ERRORLEVEL%"
echo. >> "%LOG%"
echo [*] run_windows.bat exited with code %EXITCODE% at %DATE% %TIME% >> "%LOG%"
echo.
echo [*] run_windows.bat exited with code %EXITCODE%.
echo [*] If the window closed too quickly, send this file:
echo     %CD%\%LOG%
echo.
pause
exit /b %EXITCODE%
