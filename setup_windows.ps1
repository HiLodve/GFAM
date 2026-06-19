# 少女全自动 / Girl Fully Automatic (GFAM) user bundle environment check
# Encoding: UTF-8 with BOM for Windows PowerShell 5.1 compatibility.
# This user version includes gflzirc inside libs/ZIRC, so Git is not required.

$OutputEncoding = [System.Text.Encoding]::UTF8
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Has-Cmd($name) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  return $null -ne $cmd
}

function Ask-Yes($message) {
  $ans = Read-Host "$message [Y/n]"
  if ([string]::IsNullOrWhiteSpace($ans)) { return $true }
  return $ans.Trim().ToLower() -in @("y", "yes", "1")
}

function Install-WingetPackage($id, $name) {
  if (-not (Has-Cmd "winget")) {
    Write-Host "[错误] 未检测到 winget，无法自动安装 $name。" -ForegroundColor Red
    Write-Host "[提示] 请手动安装 $name 后重新运行 run_windows.bat。"
    return $false
  }

  if (-not (Ask-Yes "未检测到 $name，是否使用 winget 自动安装")) {
    Write-Host "[错误] 缺少 $name，无法继续。" -ForegroundColor Red
    return $false
  }

  Write-Host "[*] 正在安装 $name ..." -ForegroundColor Cyan
  winget install --id $id -e --source winget
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] $name 安装失败。" -ForegroundColor Red
    return $false
  }

  Write-Host "[+] $name 安装命令已完成。" -ForegroundColor Green
  Write-Host "[提示] 如果后续仍提示找不到 $name，请关闭本窗口后重新运行 run_windows.bat。"
  return $true
}

function Get-ScriptRootSafe() {
  if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { return $PSScriptRoot }
  if ($MyInvocation -and $MyInvocation.MyCommand -and $MyInvocation.MyCommand.Path) {
    return Split-Path -Parent $MyInvocation.MyCommand.Path
  }
  return (Get-Location).Path
}

function Get-PythonCmd() {
  if (Has-Cmd "python") { return "python" }
  if (Has-Cmd "py") { return "py" }
  return ""
}

function Ensure-PythonRequirements($root, $pyCmd) {
  $reqFile = Join-Path $root "requirements.txt"
  if (-not (Test-Path $reqFile)) {
    $reqFile = Join-Path $root "requirements-gha.txt"
  }

  if (-not (Test-Path $reqFile)) {
    Write-Host "[警告] 未找到 requirements.txt / requirements-gha.txt，跳过 Python 依赖检查。" -ForegroundColor Yellow
    return $true
  }

  & $pyCmd -c "import requests" 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "[+] 已检测到 Python 依赖：requests" -ForegroundColor Green
    return $true
  }

  Write-Host "[警告] 当前 Python 环境缺少依赖 requests。" -ForegroundColor Yellow
  if (-not (Ask-Yes "是否自动安装 Python 依赖")) {
    Write-Host "[警告] 跳过 Python 依赖安装。GFAM 主要依赖内置 gflzirc，通常不影响使用。" -ForegroundColor Yellow
    Write-Host "[提示] 如果后续模块运行报错，请手动执行：$pyCmd -m pip install requests" -ForegroundColor Yellow
    return $true
  }

  Write-Host "[*] 正在检查 pip ..." -ForegroundColor Cyan
  & $pyCmd -m pip --version 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[*] 未检测到 pip，尝试启用 ensurepip ..." -ForegroundColor Cyan
    & $pyCmd -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
      Write-Host "[警告] pip 初始化失败。GFAM 主要依赖内置 gflzirc，通常不影响使用。" -ForegroundColor Yellow
      Write-Host "[提示] 如需安装依赖，请手动执行：$pyCmd -m ensurepip --upgrade && $pyCmd -m pip install requests" -ForegroundColor Yellow
      return $true
    }
  }

  Write-Host "[*] 正在安装 Python 依赖：$reqFile" -ForegroundColor Cyan
  & $pyCmd -m pip install -r $reqFile
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[警告] Python 依赖安装失败。GFAM 主要依赖内置 gflzirc，通常不影响使用。" -ForegroundColor Yellow
    Write-Host "[提示] 请手动执行：$pyCmd -m pip install requests" -ForegroundColor Yellow
    return $true
  }

  & $pyCmd -c "import requests" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[警告] requests 仍然不可用，但 GFAM 主要依赖内置 gflzirc 进行通信，通常不影响使用。" -ForegroundColor Yellow
    Write-Host "[提示] 如果后续模块运行报错，请手动执行：$pyCmd -m pip install requests" -ForegroundColor Yellow
    return $true
  }

  Write-Host "[+] Python 依赖已安装完成。" -ForegroundColor Green
  return $true
}

Write-Host "================ 少女全自动（GFAM）环境检查 ================" -ForegroundColor Cyan
$root = Get-ScriptRootSafe
Write-Host "[*] 项目目录：$root"

if (Has-Cmd "node") {
  $nodeVer = (& node -v) 2>$null
  Write-Host "[+] 已检测到 Node.js：$nodeVer" -ForegroundColor Green
} else {
  if (-not (Install-WingetPackage "OpenJS.NodeJS.LTS" "Node.js")) { exit 1 }
}

$pyCmd = Get-PythonCmd
if (-not [string]::IsNullOrWhiteSpace($pyCmd)) {
  $pyVer = (& $pyCmd --version) 2>$null
  Write-Host "[+] 已检测到 Python：$pyVer（命令：$pyCmd）" -ForegroundColor Green
} else {
  if (-not (Install-WingetPackage "Python.Python.3.11" "Python 3.11")) { exit 1 }
  $pyCmd = Get-PythonCmd
  if ([string]::IsNullOrWhiteSpace($pyCmd)) {
    Write-Host "[错误] Python 安装后仍不可用，请关闭本窗口后重新运行。" -ForegroundColor Red
    exit 1
  }
}

if (-not (Ensure-PythonRequirements $root $pyCmd)) { exit 1 }

$gflzircInit = Join-Path $root "libs\ZIRC\src\core\gflzirc\__init__.py"
if (Test-Path $gflzircInit) {
  Write-Host "[+] 已检测到内置 gflzirc。" -ForegroundColor Green
  Write-Host "    $gflzircInit"
} else {
  Write-Host "[错误] 未检测到内置 gflzirc。" -ForegroundColor Red
  Write-Host "[路径] $gflzircInit"
  Write-Host "[提示] 用户版压缩包应该已经包含 gflzirc。"
  Write-Host "[提示] 请确认已完整解压压缩包；不要在压缩包预览窗口中直接运行。"
  Write-Host "[提示] 如果文件确实不存在，请重新下载完整用户版压缩包。"
  exit 1
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "[+] 环境检查完成。" -ForegroundColor Green
exit 0
