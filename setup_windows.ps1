# 少女全自动 / Girl Fully Automatic (GFAM) user bundle environment check
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

Write-Host "================ 少女全自动（GFAM）环境检查 ================" -ForegroundColor Cyan
$root = Get-ScriptRootSafe
Write-Host "[*] 项目目录：$root"

if (Has-Cmd "node") {
  $nodeVer = (& node -v) 2>$null
  Write-Host "[+] 已检测到 Node.js：$nodeVer" -ForegroundColor Green
} else {
  if (-not (Install-WingetPackage "OpenJS.NodeJS.LTS" "Node.js")) { exit 1 }
}

if (Has-Cmd "py") {
  $pyVer = (& py --version) 2>$null
  Write-Host "[+] 已检测到 Python Launcher：$pyVer" -ForegroundColor Green
} elseif (Has-Cmd "python") {
  $pyVer = (& python --version) 2>$null
  Write-Host "[+] 已检测到 Python：$pyVer" -ForegroundColor Green
} else {
  if (-not (Install-WingetPackage "Python.Python.3.11" "Python 3.11")) { exit 1 }
}

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
