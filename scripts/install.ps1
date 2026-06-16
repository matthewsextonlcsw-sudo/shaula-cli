<#
.SYNOPSIS
    shaula installer — Windows (PowerShell).

    A downloadable, honesty-gated research & workflow agent. BYO model key.

.DESCRIPTION
    Clone-bootstrap install, mirroring scripts/install.sh: clone (or use a local
    checkout), create a venv (uv if present, else python -m venv), pip-install the
    package with provider extras, drop a `shaula.cmd` shim on a bin dir, and run
    the offline honesty-gate self-test. CLI-only — no code-signing certs needed.

.EXAMPLE
    irm https://raw.githubusercontent.com/matthewsextonlcsw-sudo/shaula-cli/main/scripts/install.ps1 | iex

.EXAMPLE
    .\scripts\install.ps1 -CoreOnly -SkipSetup
#>
[CmdletBinding()]
param(
    [string]$Dir,
    [string]$Bin = (Join-Path $HOME ".local\bin"),
    [string]$Ref = "main",
    [switch]$CoreOnly,
    [switch]$NoVenv,
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
# Drop a leaked PYTHONPATH/PYTHONHOME so the install can't be shadowed.
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
$env:UV_NO_CONFIG = "1"

function Say  ($m) { Write-Host "› $m"  -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "✓ $m"  -ForegroundColor Green }
function Warn ($m) { Write-Host "⚠ $m"  -ForegroundColor Yellow }
function Die  ($m) { Write-Host "✗ $m"  -ForegroundColor Red; exit 1 }

$RepoUrl     = if ($env:SHAULA_REPO) { $env:SHAULA_REPO } else { "https://github.com/matthewsextonlcsw-sudo/shaula-cli.git" }
$ShaulaHome  = if ($env:SHAULA_HOME) { $env:SHAULA_HOME } else { Join-Path $HOME ".shaula" }
$InstallDir  = if ($Dir) { $Dir } else { Join-Path $ShaulaHome "src" }
$Extras      = if ($CoreOnly) { "" } else { "[all]" }

function Find-Python {
    foreach ($cand in @("py -3", "python", "python3")) {
        $exe, $exeArgs = $cand.Split(" ", 2)
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            $code = "import sys; sys.exit(0 if sys.version_info[:2] >= (3,9) else 1)"
            & $exe $exeArgs -c $code 2>$null
            if ($LASTEXITCODE -eq 0) { return $cand }
        }
    }
    return $null
}

$HaveUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)

# --- resolve source tree --------------------------------------------------- #
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalRoot = $null
if ($ScriptDir) {
    $pp = Join-Path $ScriptDir "..\pyproject.toml"
    if ((Test-Path $pp) -and (Select-String -Path $pp -Pattern '^name = "shaula"' -Quiet)) {
        $LocalRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
    }
}

if ($LocalRoot) {
    $InstallDir = $LocalRoot
    Say "Installing from local checkout: $InstallDir"
} else {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git is required to clone shaula" }
    if (Test-Path (Join-Path $InstallDir ".git")) {
        Say "Updating existing checkout at $InstallDir"
        git -C $InstallDir fetch --quiet origin $Ref
        git -C $InstallDir checkout --quiet $Ref
        git -C $InstallDir pull --quiet --ff-only origin $Ref
    } else {
        Say "Cloning $RepoUrl → $InstallDir"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallDir) | Out-Null
        git clone --quiet --branch $Ref --depth 1 $RepoUrl $InstallDir
        if ($LASTEXITCODE -ne 0) { Die "git clone failed (is the repo published yet?)" }
    }
    Ok "Source ready at $InstallDir"
}

# --- install --------------------------------------------------------------- #
$Spec    = ".$Extras"
$VenvDir = Join-Path $ShaulaHome "venv"
$VenvShaula = Join-Path $VenvDir "Scripts\shaula.exe"

if (-not $NoVenv) {
    Push-Location $InstallDir
    try {
        if ($HaveUv) {
            Say "Creating virtual environment with uv → $VenvDir"
            uv venv $VenvDir | Out-Null
            Say "Installing shaula$Extras"
            uv pip install --python (Join-Path $VenvDir "Scripts\python.exe") $Spec | Out-Null
        } else {
            $py = Find-Python
            if (-not $py) { Die "need Python >= 3.9 (or install uv)" }
            $pyExe, $pyArgs = $py.Split(" ", 2)
            Say "Creating virtual environment → $VenvDir"
            & $pyExe $pyArgs -m venv $VenvDir
            $venvPy = Join-Path $VenvDir "Scripts\python.exe"
            & $venvPy -m pip install --quiet --upgrade pip | Out-Null
            Say "Installing shaula$Extras"
            & $venvPy -m pip install --quiet $Spec
        }
    } finally { Pop-Location }
    $ShaulaExe = $VenvShaula
} else {
    $py = Find-Python
    if (-not $py) { Die "need Python >= 3.9" }
    $pyExe, $pyArgs = $py.Split(" ", 2)
    Push-Location $InstallDir
    try { & $pyExe $pyArgs -m pip install --user $Spec } finally { Pop-Location }
    $ShaulaExe = (& $pyExe $pyArgs -c "import sysconfig,os;print(os.path.join(sysconfig.get_path('scripts','nt_user'),'shaula.exe'))").Trim()
}

if (-not (Test-Path $ShaulaExe)) { Die "install finished but shaula was not found at $ShaulaExe" }
Ok "Installed: $ShaulaExe"

# --- shim ------------------------------------------------------------------ #
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$ShimPath = Join-Path $Bin "shaula.cmd"
"@echo off`r`n`"$ShaulaExe`" %*" | Set-Content -Path $ShimPath -Encoding Ascii
Ok "Wrote shim $ShimPath → $ShaulaExe"

if (($env:PATH -split ';') -notcontains $Bin) {
    Warn "$Bin is not on your PATH. Add it (PowerShell):"
    Write-Host "      `$env:PATH = `"$Bin;`$env:PATH`"" -ForegroundColor White
}

# --- verify (offline) ------------------------------------------------------ #
Say "Verifying the install (offline honesty-gate self-test)…"
& $ShaulaExe doctor *> $null
if ($LASTEXITCODE -eq 0) { Ok "shaula doctor passed — the honesty gate holds with no network." }
else { Warn "shaula doctor reported problems; run '$ShimPath doctor' to see them." }

# --- setup ----------------------------------------------------------------- #
if (-not $SkipSetup) {
    Write-Host ""
    & $ShaulaExe setup
}

Write-Host ""
Ok "shaula is installed."
@"

  Try it offline (no key needed):
      shaula research "sleep hygiene basics" --stub
      shaula author   "draft a weekly blog workflow" --stub

  Bring your own key when ready:
      shaula setup          # pick a provider (Google / Anthropic / OpenAI) + compliance
      shaula providers      # see which keys are detected

  The honesty gate is always on: a banned, unverifiable claim parks the run
  instead of shipping. Core functions are no-PHI by construction.
"@ | Write-Host
