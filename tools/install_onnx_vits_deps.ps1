[CmdletBinding()]
param(
    [string]$PythonLauncher = "py",
    [string]$Target = ".onnx-vits-deps",
    [switch]$Upgrade
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pyproject = Join-Path $projectRoot "pyproject.toml"
$targetPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Target))

$requirements = & $PythonLauncher -3.10 -X utf8 -c @"
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    data = tomllib.load(handle)
print("\n".join(data["project"]["optional-dependencies"]["onnx-vits"]))
"@ $pyproject
if ($LASTEXITCODE -ne 0 -or -not $requirements) {
    throw "Unable to read the onnx-vits dependency list from pyproject.toml."
}

New-Item -ItemType Directory -Force -Path $targetPath | Out-Null
$pipArgs = @("-3.10", "-m", "pip", "install", "--target", $targetPath)
if ($Upgrade) {
    $pipArgs += "--upgrade"
}
$pipArgs += $requirements

& $PythonLauncher @pipArgs
if ($LASTEXITCODE -ne 0) {
    throw "ONNX-VITS dependency installation failed with exit code $LASTEXITCODE."
}

Write-Host "ONNX-VITS dependencies installed to $targetPath"
