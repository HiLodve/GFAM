param(
  [Parameter(Mandatory=$true)][string]$PythonCommand,
  [Parameter(Mandatory=$true)][string]$ScriptPath,
  [Parameter(Mandatory=$true)][string]$WorkingDirectory,
  [Parameter(Mandatory=$true)][string]$PidFile
)

try {
  $p = Start-Process -FilePath $PythonCommand -ArgumentList @($ScriptPath) -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden
  Set-Content -Path $PidFile -Value $p.Id -Encoding ASCII
  exit 0
} catch {
  Write-Host "[ERROR] Failed to start background process: $($_.Exception.Message)"
  exit 1
}
