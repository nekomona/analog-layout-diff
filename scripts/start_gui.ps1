param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$projectDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonPath) {
    $PythonPath = Join-Path (Split-Path -Parent $projectDirectory) '.venv/Scripts/python.exe'
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
# Compatibility shortcut: SKILL launches the persistent worker on the Virtuoso host.
Push-Location -LiteralPath $projectDirectory
try {
    & $PythonPath -m layoutdiff gui-serve
    if ($LASTEXITCODE -ne 0) { throw 'Virtuoso runtime start request failed.' }
} finally { Pop-Location }
