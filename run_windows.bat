@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 (
  echo [错误] 无法进入少女全自动 GFAM 文件夹：%~dp0
  pause
  exit /b 1
)

echo ================================================
echo 少女全自动 - Girl Fully Automatic - GFAM
echo GFAM 启动器
echo Project folder: %CD%
echo ================================================
echo.

if not exist "%CD%\main.js" (
  echo [错误] 未找到 main.js。
  echo [提示] 请先完整解压压缩包，再从解压后的 GFAM 文件夹中运行本文件。
  echo [提示] 不要在压缩包预览窗口里直接双击运行。
  echo.
  pause
  exit /b 1
)

where powershell >nul 2>nul
if errorlevel 1 (
  echo [警告] 未检测到 Windows PowerShell，跳过自动环境检查。
) else (
  echo [*] 正在执行环境检查 setup_windows.ps1 ...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup_windows.ps1"
  if errorlevel 1 (
    echo.
    echo [错误] 环境检查未通过。
    echo [提示] 请按上方提示处理后重新运行。
    echo.
    pause
    exit /b 1
  )
)

echo.
echo [*] Node.js 版本：
node -v
if errorlevel 1 (
  echo [错误] Node.js 不可用。
  echo [提示] 如果刚刚安装了 Node.js，请关闭本窗口后重新运行 run_windows.bat。
  echo.
  pause
  exit /b 1
)

rem 统一选择可用的 Python 命令，避免 python 可用但 py 不可用导致模块启动失败。
set "PY_CMD="
where python >nul 2>nul
if not errorlevel 1 (
  set "PY_CMD=python"
)
if not defined PY_CMD (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PY_CMD=py"
  )
)

if not defined PY_CMD (
  echo.
  echo [错误] Python 不可用。
  echo [提示] 请安装 Python 3.11，并勾选 Add Python to PATH。
  echo [提示] 如果刚刚安装了 Python，请关闭本窗口后重新运行 run_windows.bat。
  echo.
  pause
  exit /b 1
)

echo.
echo [*] Python 版本：
%PY_CMD% --version
if errorlevel 1 (
  echo [错误] Python 无法正常运行：%PY_CMD%
  echo [提示] 请检查 Python 安装与 PATH 环境变量。
  echo.
  pause
  exit /b 1
)
echo [*] Python 命令：%PY_CMD%

if not exist "%CD%\libs\ZIRC\src\core\gflzirc\__init__.py" (
  echo.
  echo [错误] 未检测到内置 gflzirc：libs\ZIRC\src\core\gflzirc\__init__.py
  echo [提示] 当前用户版压缩包应该已经内置 gflzirc。
  echo [提示] 如果这里报错，通常是压缩包没有完整解压，或文件被误删。
  echo.
  pause
  exit /b 1
)

rem 每次重新打开启动器时清除上次会话保存的 UID/SIGN，避免 SIGN 过期。
if exist "%CD%\.gfam_auth.json" (
  del /f /q "%CD%\.gfam_auth.json" >nul 2>nul
  echo [*] 已清除上次会话保存的 UID/SIGN，将重新获取。
)

set "GFAM_MAIN_ALREADY_STARTED=0"

:GFAM_MENU
if exist "%CD%\.gfam_next_module.cmd" del /f /q "%CD%\.gfam_next_module.cmd" >nul 2>nul
if "%GFAM_MAIN_ALREADY_STARTED%"=="0" (
  set "GFAM_FORCE_SERVER_SELECT=1"
) else (
  set "GFAM_FORCE_SERVER_SELECT=0"
)
echo.
echo [*] 正在启动少女全自动 GFAM 主菜单...
echo.
node "%CD%\main.js"
set NODE_EXIT=%ERRORLEVEL%
set "GFAM_MAIN_ALREADY_STARTED=1"

if "%NODE_EXIT%"=="77" goto RUN_MODULE
if "%NODE_EXIT%"=="0" goto EXIT_OK

echo.
echo [错误] 少女全自动 GFAM 异常退出，退出码：%NODE_EXIT%
echo [提示] 请把本窗口完整日志发给我。
echo.
pause
exit /b %NODE_EXIT%

:RUN_MODULE
if not exist "%CD%\.gfam_next_module.cmd" (
  echo [错误] 未找到模块启动信息 .gfam_next_module.cmd。
  pause
  exit /b 1
)
set "GFAM_AUTH_CAPTURE=0"
call "%CD%\.gfam_next_module.cmd"
if "%GFAM_MODULE_FILE%"=="" (
  echo [错误] 模块文件名为空。
  pause
  exit /b 1
)
if not exist "%CD%\modules\%GFAM_MODULE_FILE%" (
  echo [错误] 模块文件不存在：modules\%GFAM_MODULE_FILE%
  pause
  exit /b 1
)

echo.
echo ================================================
echo 正在启动模块：%GFAM_MODULE_TITLE%
echo 当前服务器：%GFAM_SELECTED_SERVER%
echo 模块文件：modules\%GFAM_MODULE_FILE%
echo 提示：该模块将直接接管命令行输入。
echo ================================================
echo.
set "PYTHONPATH=%CD%\libs\ZIRC\src\core;%PYTHONPATH%"
set "PYTHONUTF8=1"
if "%GFAM_FAIRY_AUTO_ENABLED%"=="1" (
  if /I not "%GFAM_MODULE_FILE%"=="gfam_auth_capture.py" (
    if not "%GFAM_AUTH_CAPTURE%"=="1" (
      echo [*] 妖精自动建造 / 自动强化已开启，将随当前模块后台运行。
      powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%PY_CMD%' -ArgumentList @('%CD%\modules\gfam_fairy_auto.py') -WorkingDirectory '%CD%' -PassThru -WindowStyle Hidden; Set-Content -Path '%CD%\.gfam_fairy_auto.pid' -Value $p.Id -Encoding ASCII"
    )
  )
)
%PY_CMD% "%CD%\modules\%GFAM_MODULE_FILE%"
set MODULE_EXIT=%ERRORLEVEL%
if exist "%CD%\.gfam_fairy_auto.pid" (
  for /f %%P in (%CD%\.gfam_fairy_auto.pid) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Stop-Process -Id %%P -Force -ErrorAction SilentlyContinue } catch {}" >nul 2>nul
  )
  del /f /q "%CD%\.gfam_fairy_auto.pid" >nul 2>nul
  echo [*] 妖精自动建造 / 自动强化后台循环已停止。
)
echo.
echo [*] 模块已退出，退出码：%MODULE_EXIT%。
if "%GFAM_AUTH_CAPTURE%"=="1" (
  echo [*] UID/SIGN 获取流程已结束，正在返回少女全自动 GFAM 主菜单。
  timeout /t 1 >nul
  goto GFAM_MENU
)
echo [*] 按任意键返回少女全自动 GFAM 主菜单。
pause >nul
goto GFAM_MENU

:EXIT_OK
echo.
if exist "%CD%\.gfam_auth.json" (
  del /f /q "%CD%\.gfam_auth.json" >nul 2>nul
  echo [*] 已清除本地 UID/SIGN，下次启动将重新获取。
)
echo [*] 少女全自动 GFAM 已退出。
pause
exit /b 0
