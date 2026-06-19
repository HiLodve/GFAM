@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 goto FAIL
where python >nul 2>nul
if errorlevel 1 goto NO_PYTHON
python -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
  echo [*] Installing PyInstaller...
  python -m pip install -U pyinstaller
  if errorlevel 1 goto PIP_FAIL
)
echo [*] Building GFAM GUI executable...
python tools\build_gfam_gui_exe.py
if errorlevel 1 goto BUILD_FAIL
echo.
echo [OK] Build complete. Run dist\GFAM-GUI\GFAM-GUI.exe
echo [INFO] Opening the valid dist output folder...
if exist "dist\GFAM-GUI" explorer "dist\GFAM-GUI"
echo.
echo Do NOT run anything from the build folder. The build folder is only temporary.
echo.
pause
exit /b 0
:FAIL
echo [ERROR] Cannot enter this folder.
pause
exit /b 1
:NO_PYTHON
echo [ERROR] Python was not found. Please install Python 3.11 and enable PATH.
pause
exit /b 1
:PIP_FAIL
echo [ERROR] Failed to install PyInstaller.
pause
exit /b 1
:BUILD_FAIL
echo [ERROR] Build failed. Please send the console log.
pause
exit /b 1
