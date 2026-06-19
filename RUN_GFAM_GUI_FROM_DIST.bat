@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if exist "dist\GFAM-GUI\GFAM-GUI.exe" (
  start "" "dist\GFAM-GUI\GFAM-GUI.exe"
  exit /b 0
)
echo [ERROR] dist\GFAM-GUI\GFAM-GUI.exe not found.
echo Please run build_gfam_gui_exe.bat first, then use this launcher.
echo.
pause
exit /b 1
