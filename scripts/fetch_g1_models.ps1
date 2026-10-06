# Fetch the pinned official Unitree G1 assets used by Phase 1.
# The assets are large binary meshes and policies, so they are vendored into
# third_party/ (git-ignored) and never committed.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ThirdParty = Join-Path $RepoRoot "third_party"
New-Item -ItemType Directory -Force -Path $ThirdParty | Out-Null

$Sources = @(
    @{
        Name   = "unitree_mujoco"
        Url    = "https://github.com/unitreerobotics/unitree_mujoco.git"
        Commit = "1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d"
        Note   = "official full-body G1 MJCF (compatibility spike)"
    },
    @{
        Name   = "unitree_rl_gym"
        Url    = "https://github.com/unitreerobotics/unitree_rl_gym.git"
        Commit = "276801e46c5d433564f24658bac64f254b7d2d4b"
        Note   = "official 12-DOF G1 description + MuJoCo deployment + pretrained policy"
    }
)

$Provenance = @()
foreach ($Source in $Sources) {
    $Target = Join-Path $ThirdParty $Source.Name
    if (-not (Test-Path -LiteralPath $Target)) {
        git clone --depth 1 $Source.Url $Target
    }
    $Actual = (git -C $Target rev-parse HEAD).Trim()
    if ($Actual -ne $Source.Commit) {
        Write-Warning "$($Source.Name): HEAD $Actual differs from pinned $($Source.Commit); fetching the pinned revision"
        git -C $Target fetch --depth 1 origin $Source.Commit
        git -C $Target checkout --detach FETCH_HEAD
        $Actual = (git -C $Target rev-parse HEAD).Trim()
    }
    $Provenance += [ordered]@{
        name   = $Source.Name
        url    = $Source.Url
        commit = $Actual
        note   = $Source.Note
    }
}

$ProvenancePath = Join-Path $ThirdParty "PROVENANCE.json"
$Provenance | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ProvenancePath -Encoding utf8
Write-Host "Wrote $ProvenancePath"
$Provenance | Format-Table -AutoSize
