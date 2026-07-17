[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ModelDir,

    [Parameter(Mandatory = $true)]
    [string]$Config,

    [string]$DefaultSpeaker,
    [Nullable[int]]$DefaultSpeakerId,
    [int]$Port = 8764,
    [string]$Providers,
    [string]$OpenJTalkDictDir,
    [string]$PythonLauncher = "py",
    [string]$DependencyDir = ".onnx-vits-deps"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$modelPath = (Resolve-Path -LiteralPath $ModelDir).Path
$configPath = (Resolve-Path -LiteralPath $Config).Path
$dependencyPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $DependencyDir))

foreach ($graph in @("enc_p.onnx", "emb_g.onnx", "dp.onnx", "flow.onnx", "dec.onnx")) {
    if (-not (Test-Path -LiteralPath (Join-Path $modelPath $graph) -PathType Leaf)) {
        throw "Missing ONNX-VITS graph: $(Join-Path $modelPath $graph)"
    }
}
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "ONNX-VITS config not found: $configPath"
}

$env:OUMUQ_ONNX_VITS_MODEL_DIR = $modelPath
$env:OUMUQ_ONNX_VITS_CONFIG = $configPath
$env:OUMUQ_ONNX_VITS_PORT = [string]$Port
if ($DefaultSpeaker) {
    $env:OUMUQ_ONNX_VITS_DEFAULT_SPEAKER = $DefaultSpeaker
}
if ($null -ne $DefaultSpeakerId) {
    $env:OUMUQ_ONNX_VITS_DEFAULT_SPEAKER_ID = [string]$DefaultSpeakerId
}
if ($Providers) {
    $env:OUMUQ_ONNX_VITS_PROVIDERS = $Providers
}
if ($OpenJTalkDictDir) {
    $env:OPEN_JTALK_DICT_DIR = (Resolve-Path -LiteralPath $OpenJTalkDictDir).Path
}
if (Test-Path -LiteralPath $dependencyPath -PathType Container) {
    $env:PYTHONPATH = if ($env:PYTHONPATH) { "$dependencyPath;$env:PYTHONPATH" } else { $dependencyPath }
}

Push-Location $projectRoot
try {
    & $PythonLauncher -3.10 -X utf8 -m app.workers.onnx_vits
    if ($LASTEXITCODE -ne 0) {
        throw "ONNX-VITS worker stopped with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
