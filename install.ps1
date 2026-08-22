<#
.SYNOPSIS
    Install Open Omniscience on Windows 11 (the PowerShell counterpart of install.sh).

.DESCRIPTION
    Promptless by default, and idempotent: re-running only does what is missing.

        1. finds (or installs, via winget) Git and Python 3.13
        2. clones the repo -- or reuses the checkout this script sits in
        3. creates .venv and installs the app plus its extras
        4. VERIFIES the install by importing the real app (the same boot check CI runs)
        5. creates a Desktop / Start-Menu launcher

    HONEST SUPPORT STATUS -- read this before relying on it.
    Every CI run proves three things on windows-latest: dependency install, the app
    boot check, and SQLCipher at-rest encryption (that last one on a BLOCKING lane).
    Nothing beyond that is proven. The Windows pytest lane is an observation lane
    (continue-on-error) and it HANGS -- recent completed runs sat in pytest for 3h21m
    and ~6h against 18 minutes on macOS -- so the test suite does not pass on Windows
    and no one has clicked through the UI there. Expect install and boot to work;
    treat everything after that as unverified. This script never claims otherwise.

.PARAMETER Path
    Where to install. Defaults to the checkout this script lives in, else
    "$HOME\Open-Omniscience".

.PARAMETER Extras
    Comma-separated pip extras. Default "analysis,compression,columnar" matches
    install.sh. Only "analysis" is proven on Windows by CI; if the full set fails to
    install, the script falls back to "analysis" and SAYS SO rather than failing.

.PARAMETER Ref
    Optional git branch/tag to check out.

.PARAMETER NoPython
    Never install Python/Git automatically; fail with instructions instead.

.PARAMETER NoLauncher
    Skip creating the Desktop / Start-Menu shortcuts.

.PARAMETER Check
    Run the health check (open-omniscience doctor) against an existing install and exit.

.PARAMETER Uninstall
    Remove .venv and the launchers. Your data is KEPT unless you separately confirm.

.PARAMETER Yes
    Assume yes for prompts (unattended).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Extras analysis -NoLauncher

.LINK
    https://github.com/ideotion/Open-Omniscience
#>
[CmdletBinding()]
param(
    [string]  $Path,
    [string]  $Extras = 'analysis,compression,columnar',
    [string]  $Ref,
    [switch]  $NoPython,
    [switch]  $NoLauncher,
    [switch]  $Check,
    [switch]  $Uninstall,
    [switch]  $Yes
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # keeps winget/IWR progress bars out of logs

$RepoUrl     = 'https://github.com/ideotion/Open-Omniscience.git'
$AppName     = 'Open Omniscience'
$MinPython   = [version]'3.13'
$ProvenExtras = 'analysis'                    # the set windows-latest CI installs every run

# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
function Write-Step { param([string] $Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string] $Message) Write-Host "  ok  $Message" -ForegroundColor Green }
function Write-Note { param([string] $Message) Write-Host "      $Message" -ForegroundColor DarkGray }
function Write-Caution { param([string] $Message) Write-Host "  !!  $Message" -ForegroundColor Yellow }

function Stop-WithError {
    param([string] $Message, [string[]] $Hints = @())
    Write-Host ''
    Write-Host "ERROR: $Message" -ForegroundColor Red
    foreach ($h in $Hints) { Write-Host "       $h" -ForegroundColor Yellow }
    Write-Host ''
    exit 1
}

function Confirm-Action {
    param([string] $Question, [bool] $DefaultYes = $false)
    if ($Yes) { return $true }
    if ([Console]::IsInputRedirected) { return $DefaultYes }
    if ($DefaultYes) { $suffix = '[Y/n]' } else { $suffix = '[y/N]' }
    $answer = Read-Host "$Question $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $DefaultYes }
    return ($answer.Trim().ToLowerInvariant() -in @('y', 'yes'))
}

# Run a native executable and fail loudly on a non-zero exit code.
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string] $File,
        [string[]] $Arguments = @(),
        [switch]   $AllowFailure
    )
    $global:LASTEXITCODE = 0
    & $File @Arguments | Out-Host
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "'$File $($Arguments -join ' ')' failed with exit code $code"
    }
    return $code
}

# A winget install leaves the CURRENT session's PATH stale -- the new python/git is on
# disk but not resolvable until the shell re-reads the environment. Re-read it here so
# the very next probe can see what we just installed.
function Update-PathFromRegistry {
    $parts = @()
    foreach ($scope in @('Machine', 'User')) {
        $value = [Environment]::GetEnvironmentVariable('Path', $scope)
        if ($value) { $parts += $value }
    }
    if ($parts.Count -gt 0) { $env:Path = ($parts -join ';') }
}

function Test-HasCommand {
    param([string] $Name)
    return [bool] (Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue)
}

# --------------------------------------------------------------------------- #
# Python discovery
#
# Verified by CAPABILITY, never by a winget exit code: winget returns non-zero for
# benign outcomes such as "no applicable update", so the only trustworthy signal is
# whether a >=3.13 interpreter answers afterwards.
# --------------------------------------------------------------------------- #
function Test-PythonCandidate {
    param([string[]] $Command)
    try {
        $exe  = $Command[0]
        $rest = @()
        if ($Command.Count -gt 1) { $rest = $Command[1..($Command.Count - 1)] }
        $script = 'import sys; print("%d.%d" % sys.version_info[:2]); print(sys.executable)'
        $global:LASTEXITCODE = 0
        $out = & $exe @rest '-c' $script 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $lines = @($out | Where-Object { $_ -ne $null -and $_.ToString().Trim() -ne '' })
        # A bare `python` on a fresh Windows 11 is the Microsoft Store execution-alias
        # stub: it prints nothing and does not run code. Two lines of real output is
        # what separates an interpreter from the stub.
        if ($lines.Count -lt 2) { return $null }
        $version = [version] $lines[0].ToString().Trim()
        if ($version -lt $MinPython) { return $null }
        return [pscustomobject]@{ Version = $version; Exe = $lines[1].ToString().Trim() }
    } catch {
        return $null
    }
}

function Resolve-Python {
    $candidates = @(
        @('py', '-3.13'),
        @('python3.13'),
        @('python'),
        @('python3')
    )
    $wellKnown = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\python.exe'),
        (Join-Path $env:ProgramFiles 'Python313\python.exe'),
        'C:\Python313\python.exe'
    )
    foreach ($p in $wellKnown) {
        if ($p -and (Test-Path -LiteralPath $p)) { $candidates += , @($p) }
    }
    foreach ($candidate in $candidates) {
        $found = Test-PythonCandidate -Command $candidate
        if ($found) { return $found }
    }
    return $null
}

function Install-WingetPackage {
    param([string] $Id, [string] $Label)
    if (-not (Test-HasCommand 'winget')) {
        return $false
    }
    Write-Step "Installing $Label via winget (this can take a few minutes)"
    # winget's exit code is unreliable for our purposes (see above), so ignore it and
    # let the caller re-probe for the capability.
    Invoke-Native -File 'winget' -AllowFailure -Arguments @(
        'install', '--id', $Id, '--exact', '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements',
        '--disable-interactivity'
    ) | Out-Null
    Update-PathFromRegistry
    return $true
}

# --------------------------------------------------------------------------- #
# Launchers
# --------------------------------------------------------------------------- #
function New-Shortcut {
    param([string] $ShortcutPath, [string] $Target, [string] $WorkingDirectory)
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($ShortcutPath)
        $shortcut.TargetPath       = $Target
        $shortcut.WorkingDirectory = $WorkingDirectory
        $shortcut.Description      = "$AppName - local-first research desk (127.0.0.1 only)"
        $shortcut.Save()
    } finally {
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
    }
}

function Get-ShortcutPaths {
    $desktop   = [Environment]::GetFolderPath('Desktop')
    $startMenu = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'
    $paths = @()
    if ($desktop)   { $paths += (Join-Path $desktop   "$AppName.lnk") }
    if ($startMenu) { $paths += (Join-Path $startMenu "$AppName.lnk") }
    return $paths
}

# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
if ($env:OS -ne 'Windows_NT') {
    Stop-WithError 'install.ps1 is the Windows installer.' @('On Linux/macOS use ./install.sh instead.')
}
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Stop-WithError "PowerShell 5.1 or newer is required (found $($PSVersionTable.PSVersion))."
}

Write-Host ''
Write-Host "  $AppName - Windows installer" -ForegroundColor White
Write-Host '  ------------------------------------------------------------' -ForegroundColor DarkGray
Write-Host '  Install and boot are CI-proven on Windows. The test suite is' -ForegroundColor DarkGray
Write-Host '  NOT: its Windows lane hangs, and the UI has never been' -ForegroundColor DarkGray
Write-Host '  clicked through there. Treat anything past boot as unverified.' -ForegroundColor DarkGray
Write-Host ''

# Resolve the install location. When this script sits inside a checkout, that
# checkout is the target and nothing is cloned.
$scriptRoot = $PSScriptRoot
$inRepo     = $false
if ($scriptRoot -and (Test-Path -LiteralPath (Join-Path $scriptRoot 'pyproject.toml'))) {
    $inRepo = $true
}

if ($Path) {
    $target = $Path
} elseif ($inRepo) {
    $target = $scriptRoot
} else {
    $target = Join-Path $HOME 'Open-Omniscience'
}

# --------------------------------------------------------------------------- #
# --Uninstall
# --------------------------------------------------------------------------- #
if ($Uninstall) {
    Write-Step "Uninstalling from $target"
    $venvPath = Join-Path $target '.venv'
    if (Test-Path -LiteralPath $venvPath) {
        Remove-Item -LiteralPath $venvPath -Recurse -Force
        Write-Ok 'Removed .venv'
    } else {
        Write-Note 'No .venv to remove.'
    }
    foreach ($lnk in (Get-ShortcutPaths)) {
        if (Test-Path -LiteralPath $lnk) {
            Remove-Item -LiteralPath $lnk -Force
            Write-Ok "Removed shortcut $lnk"
        }
    }
    $dataPath = Join-Path $target 'data'
    if (Test-Path -LiteralPath $dataPath) {
        Write-Host ''
        Write-Caution "Your corpus, signing keys and settings are in: $dataPath"
        Write-Caution 'Deleting it is IRREVERSIBLE and there is no passphrase recovery.'
        if (Confirm-Action -Question 'Delete that data folder too?' -DefaultYes $false) {
            Remove-Item -LiteralPath $dataPath -Recurse -Force
            Write-Ok 'Data deleted.'
        } else {
            Write-Ok "Data kept at $dataPath"
        }
    }
    Write-Host ''
    Write-Host 'Uninstalled. The source checkout itself was left in place.' -ForegroundColor Green
    exit 0
}

# --------------------------------------------------------------------------- #
# --Check
# --------------------------------------------------------------------------- #
if ($Check) {
    $venvPython = Join-Path $target '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Stop-WithError "No install found at $target." @('Run install.ps1 without -Check first.')
    }
    Push-Location -LiteralPath $target
    try {
        $doctor = Invoke-Native -File $venvPython -AllowFailure `
            -Arguments @('-m', 'src.api.main', 'doctor')
    } finally {
        Pop-Location
    }
    exit $doctor
}

# --------------------------------------------------------------------------- #
# 1. Git
# --------------------------------------------------------------------------- #
if (-not $inRepo) {
    if (-not (Test-HasCommand 'git')) {
        if ($NoPython) {
            Stop-WithError 'git is not installed (and -NoPython was given).' @('Install it from https://git-scm.com/download/win')
        }
        if (-not (Install-WingetPackage -Id 'Git.Git' -Label 'Git')) {
            Stop-WithError 'git is not installed and winget is unavailable.' @(
                'Install Git from https://git-scm.com/download/win, then re-run this script.'
            )
        }
        if (-not (Test-HasCommand 'git')) {
            Stop-WithError 'Git still is not resolvable after the winget install.' @(
                'Close this terminal, open a NEW one, and re-run install.ps1.'
            )
        }
    }
    Write-Ok "Git: $((& git --version) -join '')"
}

# --------------------------------------------------------------------------- #
# 2. Python 3.13
# --------------------------------------------------------------------------- #
Write-Step 'Looking for Python 3.13+'
$python = Resolve-Python
if (-not $python) {
    if ($NoPython) {
        Stop-WithError 'No Python 3.13+ found (and -NoPython was given).' @(
            'Install it from https://www.python.org/downloads/ and re-run.'
        )
    }
    Write-Note 'Not found -- installing it.'
    if (-not (Install-WingetPackage -Id 'Python.Python.3.13' -Label 'Python 3.13')) {
        Stop-WithError 'Python 3.13 is missing and winget is unavailable.' @(
            'Install Python 3.13 from https://www.python.org/downloads/',
            'Tick "Add python.exe to PATH" in the installer, then re-run this script.'
        )
    }
    $python = Resolve-Python
    if (-not $python) {
        Stop-WithError 'Python 3.13 still is not resolvable after the winget install.' @(
            'Close this terminal, open a NEW one, and re-run install.ps1.',
            'If it still fails, install from https://www.python.org/downloads/ manually.'
        )
    }
}
Write-Ok "Python $($python.Version) at $($python.Exe)"

# --------------------------------------------------------------------------- #
# 3. Source
# --------------------------------------------------------------------------- #
if ($inRepo) {
    Write-Ok "Using the checkout this script lives in: $target"
} elseif (Test-Path -LiteralPath (Join-Path $target '.git')) {
    Write-Step "Updating the existing checkout at $target"
    # A failed pull must not abort an otherwise fine install (offline, local commits).
    $code = Invoke-Native -File 'git' -AllowFailure -Arguments @('-C', $target, 'pull', '--ff-only')
    if ($code -ne 0) { Write-Caution 'Could not fast-forward; continuing with the checkout as-is.' }
} else {
    if ((Test-Path -LiteralPath $target) -and (Get-ChildItem -LiteralPath $target -Force | Select-Object -First 1)) {
        Stop-WithError "$target already exists and is not empty (and is not a git checkout)." @(
            'Pass -Path <somewhere-else>, or move that folder aside.'
        )
    }
    Write-Step "Cloning into $target"
    $cloneArgs = @('clone', '--depth', '1')
    if ($Ref) { $cloneArgs += @('--branch', $Ref) }
    $cloneArgs += @($RepoUrl, $target)
    Invoke-Native -File 'git' -Arguments $cloneArgs | Out-Null
    Write-Ok 'Cloned.'
}

if (-not (Test-Path -LiteralPath (Join-Path $target 'pyproject.toml'))) {
    Stop-WithError "$target does not look like the Open Omniscience repository."
}

# --------------------------------------------------------------------------- #
# 4. Virtual environment
# --------------------------------------------------------------------------- #
$venv       = Join-Path $target '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Step 'Creating the virtual environment (.venv)'
    Invoke-Native -File $python.Exe -Arguments @('-m', 'venv', $venv) | Out-Null
} else {
    Write-Ok 'Reusing the existing .venv'
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Stop-WithError "The virtual environment was not created at $venv."
}

# Everything below calls .venv\Scripts\python.exe by full path on purpose: activating
# a venv needs Activate.ps1, which a default Windows execution policy blocks. Not
# activating sidesteps that entire class of failure.

# --------------------------------------------------------------------------- #
# 5. Dependencies
# --------------------------------------------------------------------------- #
Push-Location -LiteralPath $target
try {
    Write-Step 'Upgrading pip'
    Invoke-Native -File $venvPython -Arguments @(
        '-m', 'pip', 'install', '--upgrade', 'pip', '--disable-pip-version-check', '--quiet'
    ) | Out-Null

    $requested = $Extras.Trim()
    Write-Step "Installing Open Omniscience with extras: $requested"
    Write-Note 'First run downloads a few hundred MB; expect several minutes.'

    $spec = ".[$requested]"
    if ([string]::IsNullOrWhiteSpace($requested)) { $spec = '.' }

    $code = Invoke-Native -File $venvPython -AllowFailure -Arguments @(
        '-m', 'pip', 'install', '-e', $spec, '--disable-pip-version-check'
    )
    if ($code -ne 0) {
        # Degrade loudly: name what failed, retry with the set CI actually proves on
        # Windows, and never present the reduced install as the requested one.
        Write-Host ''
        Write-Caution "Installing extras '$requested' failed (pip exit code $code)."
        Write-Caution "Retrying with the Windows CI-proven set: '$ProvenExtras'."
        Write-Caution 'Features from the dropped extras will be unavailable.'
        Write-Host ''
        Invoke-Native -File $venvPython -Arguments @(
            '-m', 'pip', 'install', '-e', ".[$ProvenExtras]", '--disable-pip-version-check'
        ) | Out-Null
        $installedExtras = $ProvenExtras
    } else {
        $installedExtras = $requested
    }
    Write-Ok "Installed (extras: $installedExtras)"

    # ----------------------------------------------------------------------- #
    # 6. Verify -- the same import CI's Windows "Boot check" step runs. An install
    #    that cannot import the app is a failed install, however clean pip looked.
    # ----------------------------------------------------------------------- #
    Write-Step 'Verifying the install (importing the app)'
    $bootCheck = 'from src.api.main import app; print(sum(1 for _ in app.routes))'
    $routes = & $venvPython '-c' $bootCheck 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host ($routes | Out-String) -ForegroundColor DarkGray
        Stop-WithError 'The app failed to import, so the install is not usable.' @(
            'The output above is the real error; please include it in a bug report.'
        )
    }
    $routeLine = $routes | Select-Object -Last 1
    if ($null -eq $routeLine) { $routeLine = '?' }
    Write-Ok "App imports cleanly ($($routeLine.ToString().Trim()) routes)"
} finally {
    Pop-Location
}

# --------------------------------------------------------------------------- #
# 7. Launcher
# --------------------------------------------------------------------------- #
$launchCmd = Join-Path $target 'scripts\launch.cmd'
if (-not $NoLauncher) {
    if (Test-Path -LiteralPath $launchCmd) {
        Write-Step 'Creating launchers'
        foreach ($lnk in (Get-ShortcutPaths)) {
            try {
                New-Shortcut -ShortcutPath $lnk -Target $launchCmd -WorkingDirectory $target
                Write-Ok "Shortcut: $lnk"
            } catch {
                Write-Caution "Could not create $lnk ($($_.Exception.Message))"
            }
        }
    } else {
        Write-Caution "scripts\launch.cmd is missing; skipping the shortcuts."
    }
}

# --------------------------------------------------------------------------- #
# Done
# --------------------------------------------------------------------------- #
$dataDir = Join-Path $target 'data'
Write-Host ''
Write-Host '  ------------------------------------------------------------' -ForegroundColor DarkGray
Write-Host "  $AppName is installed." -ForegroundColor Green
Write-Host '  ------------------------------------------------------------' -ForegroundColor DarkGray
Write-Host ''
Write-Host '  Start it:' -ForegroundColor White
if (-not $NoLauncher) {
    Write-Host "    - double-click the `"$AppName`" icon on your Desktop, or" -ForegroundColor Gray
}
Write-Host "    - run: $launchCmd" -ForegroundColor Gray
Write-Host '    - then open http://127.0.0.1:8000' -ForegroundColor Gray
Write-Host ''
Write-Host '  First launch walks you through: language -> accept the legal terms' -ForegroundColor White
Write-Host '  -> create your corpus passphrase.' -ForegroundColor White
Write-Host ''
Write-Host '  The passphrase has NO RECOVERY. The corpus is encrypted at rest and' -ForegroundColor Yellow
Write-Host '  a lost passphrase cannot be recovered by anyone, including us.' -ForegroundColor Yellow
Write-Host ''
Write-Host '  The app boots OFFLINE (airplane mode) by design. Nothing is fetched' -ForegroundColor White
Write-Host '  until you switch it online, which passes one consent popup.' -ForegroundColor White
Write-Host ''
Write-Host "  Your data lives in: $dataDir" -ForegroundColor White
Write-Host '  (Set OO_DATA_DIR to put it on another drive.)' -ForegroundColor Gray
Write-Host ''
Write-Host '  Health check:  powershell -ExecutionPolicy Bypass -File install.ps1 -Check' -ForegroundColor Gray
Write-Host '  Remove:        powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall' -ForegroundColor Gray
Write-Host ''
