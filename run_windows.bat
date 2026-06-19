@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto FAIL_CD

echo ================================================
echo GFAM - Girl Fully Automatic
echo Windows launcher
echo Project folder: %CD%
echo ================================================
echo.

if not exist "%CD%\main.js" goto MISSING_MAIN

where powershell >nul 2>nul
if errorlevel 1 goto SKIP_SETUP

echo [*] Running setup_windows.ps1 ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup_windows.ps1"
if errorlevel 1 goto SETUP_FAIL
goto AFTER_SETUP

:SKIP_SETUP
echo [WARN] Windows PowerShell was not found. Setup check is skipped.

:AFTER_SETUP
echo.
echo [*] Node.js version:
node -v
if errorlevel 1 goto NODE_FAIL

set "PY_CMD="
where python >nul 2>nul
if not errorlevel 1 set "PY_CMD=python"
if defined PY_CMD goto PY_FOUND
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py"

:PY_FOUND
if not defined PY_CMD goto PYTHON_FAIL

echo.
echo [*] Python version:
%PY_CMD% --version
if errorlevel 1 goto PYTHON_RUN_FAIL
echo [*] Python command: %PY_CMD%

if not exist "%CD%\libs\ZIRC\src\core\gflzirc\__init__.py" goto MISSING_GFLZIRC

rem Clear previous saved UID/SIGN on every fresh launcher start.
if exist "%CD%\.gfam_auth.json" del /f /q "%CD%\.gfam_auth.json" >nul 2>nul

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "GFAM_MAIN_ALREADY_STARTED=0"

:GFAM_MENU
if exist "%CD%\.gfam_next_module.cmd" del /f /q "%CD%\.gfam_next_module.cmd" >nul 2>nul
if "%GFAM_MAIN_ALREADY_STARTED%"=="0" set "GFAM_FORCE_SERVER_SELECT=1"
if not "%GFAM_MAIN_ALREADY_STARTED%"=="0" set "GFAM_FORCE_SERVER_SELECT=0"

echo.
echo [*] Starting GFAM main menu ...
echo.
node "%CD%\main.js"
set "NODE_EXIT=%ERRORLEVEL%"
set "GFAM_MAIN_ALREADY_STARTED=1"

if "%NODE_EXIT%"=="77" goto RUN_MODULE
if "%NODE_EXIT%"=="0" goto EXIT_OK

echo.
echo [ERROR] GFAM main menu exited with code %NODE_EXIT%.
echo [INFO] Please send the full console log to the developer.
echo.
pause
exit /b %NODE_EXIT%

:RUN_MODULE
if not exist "%CD%\.gfam_next_module.cmd" goto MISSING_MODULE_CMD
set "GFAM_AUTH_CAPTURE=0"
call "%CD%\.gfam_next_module.cmd"
if "%GFAM_MODULE_FILE%"=="" goto EMPTY_MODULE_FILE
if not exist "%CD%\modules\%GFAM_MODULE_FILE%" goto MODULE_NOT_FOUND

echo.
echo ================================================
echo Starting module: %GFAM_MODULE_TITLE%
echo Selected server: %GFAM_SELECTED_SERVER%
echo Module file: modules\%GFAM_MODULE_FILE%
echo ================================================
echo.

set "PYTHONPATH=%CD%\libs\ZIRC\src\core;%PYTHONPATH%"
set "PYTHONUTF8=1"

if "%GFAM_FAIRY_AUTO_ENABLED%"=="1" call :START_FAIRY_AUTO

set "GFAM_FACTORY_SHOULD_START=0"
if "%GFAM_DOLL_FACTORY_AUTO_ENABLED%"=="1" set "GFAM_FACTORY_SHOULD_START=1"
if "%GFAM_EQUIP_FACTORY_AUTO_ENABLED%"=="1" set "GFAM_FACTORY_SHOULD_START=1"
if "%GFAM_FACTORY_SHOULD_START%"=="1" call :START_FACTORY_AUTO

%PY_CMD% -u "%CD%\modules\%GFAM_MODULE_FILE%"
set "MODULE_EXIT=%ERRORLEVEL%"

call :STOP_BACKGROUND "%CD%\.gfam_factory_auto.pid" "factory auto"
call :STOP_BACKGROUND "%CD%\.gfam_fairy_auto.pid" "fairy auto"

echo.
echo [*] Module exited with code %MODULE_EXIT%.
if "%GFAM_AUTH_CAPTURE%"=="1" goto AUTH_RETURN

echo [*] Press any key to return to GFAM main menu.
pause >nul
goto GFAM_MENU

:AUTH_RETURN
echo [*] UID/SIGN capture finished. Returning to GFAM main menu.
timeout /t 1 >nul
goto GFAM_MENU

:START_FAIRY_AUTO
if /I "%GFAM_MODULE_FILE%"=="gfam_auth_capture.py" exit /b 0
if "%GFAM_AUTH_CAPTURE%"=="1" exit /b 0
echo [*] Fairy auto background loop is enabled.
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\tools\start_gfam_background.ps1" -PythonCommand "%PY_CMD%" -ScriptPath "%CD%\modules\gfam_fairy_auto.py" -WorkingDirectory "%CD%" -PidFile "%CD%\.gfam_fairy_auto.pid"
exit /b 0

:START_FACTORY_AUTO
if /I "%GFAM_MODULE_FILE%"=="gfam_auth_capture.py" exit /b 0
if /I "%GFAM_MODULE_FILE%"=="gfam_factory_config.py" exit /b 0
if "%GFAM_AUTH_CAPTURE%"=="1" exit /b 0
echo [*] Factory auto background loop is enabled.
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\tools\start_gfam_background.ps1" -PythonCommand "%PY_CMD%" -ScriptPath "%CD%\modules\gfam_factory_auto.py" -WorkingDirectory "%CD%" -PidFile "%CD%\.gfam_factory_auto.pid"
exit /b 0

:STOP_BACKGROUND
set "PID_FILE=%~1"
set "PID_NAME=%~2"
if not exist "%PID_FILE%" exit /b 0
for /f %%P in (%PID_FILE%) do powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Stop-Process -Id %%P -Force -ErrorAction SilentlyContinue } catch {}" >nul 2>nul
del /f /q "%PID_FILE%" >nul 2>nul
echo [*] Stopped %PID_NAME% background loop.
exit /b 0

:EXIT_OK
echo.
if exist "%CD%\.gfam_auth.json" del /f /q "%CD%\.gfam_auth.json" >nul 2>nul
echo [*] GFAM exited.
pause
exit /b 0

:FAIL_CD
echo [ERROR] Cannot enter the GFAM folder.
pause
exit /b 1

:MISSING_MAIN
echo [ERROR] main.js was not found.
echo [INFO] Please extract the whole zip first, then run this file from the extracted GFAM folder.
pause
exit /b 1

:SETUP_FAIL
echo.
echo [ERROR] Setup check failed.
echo [INFO] Please follow the message above, then run this launcher again.
echo.
pause
exit /b 1

:NODE_FAIL
echo [ERROR] Node.js is unavailable.
echo [INFO] If Node.js was just installed, close this window and run this launcher again.
pause
exit /b 1

:PYTHON_FAIL
echo [ERROR] Python is unavailable.
echo [INFO] Please install Python 3.11 and enable Add Python to PATH.
pause
exit /b 1

:PYTHON_RUN_FAIL
echo [ERROR] Python cannot run: %PY_CMD%
pause
exit /b 1

:MISSING_GFLZIRC
echo [ERROR] Built-in gflzirc was not found at libs\ZIRC\src\core\gflzirc\__init__.py
echo [INFO] The package may not have been extracted completely.
pause
exit /b 1

:MISSING_MODULE_CMD
echo [ERROR] .gfam_next_module.cmd was not found.
pause
exit /b 1

:EMPTY_MODULE_FILE
echo [ERROR] GFAM_MODULE_FILE is empty.
pause
exit /b 1

:MODULE_NOT_FOUND
echo [ERROR] Module file was not found: modules\%GFAM_MODULE_FILE%
pause
exit /b 1
