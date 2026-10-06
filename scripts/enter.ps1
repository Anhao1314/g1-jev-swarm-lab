# Activate the repository virtual environment and keep pip cache and temp
# files inside the repository instead of the user profile.
$RepoRoot = Split-Path -Parent $PSScriptRoot

& "$RepoRoot\.venv\Scripts\Activate.ps1"

$env:PIP_CACHE_DIR = "$RepoRoot\cache\pip"
$env:TEMP = "$RepoRoot\cache\tmp"
$env:TMP = "$RepoRoot\cache\tmp"
$env:PYTHONNOUSERSITE = "1"
