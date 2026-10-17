# Open Omniscience -- the Windows launcher's server wrapper (the counterpart of the stderr filter and exit record in scripts/launch.sh).
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# launch.cmd runs this instead of the bare server when it exists. It starts the server, hands EVERY line of the server's stderr on to the
# window unchanged, and records two small things in <data dir>\diagnostics for the app's next boot to read:
#   * launcher_stderr.jsonl -- a line the server printed ONLY when the whole line is exactly one of the fixed fatal-error headers below
#     (string equality, no pattern), at most 20 per launch, plus a summary row that counts what was dropped. Nothing else is stored.
#   * launcher_exits.jsonl  -- how the server ended when this window did not ask it to stop: its exit status (.NET's signed 32-bit
#     ExitCode, so 0xC0000005 is -1073741819) with the server's pid. Windows ends a crashed process with the NTSTATUS of the fault and
#     prints nothing, so on Windows this status is the main account of a crash; the reader names it (exit_evidence._NT_STATUS_MEANING).
#
# WHAT IS NOT HERE, ON PURPOSE. No pid file and so nothing to sweep (the filter runs in this process, not beside it). No boot id: Windows has
# none the app reads, so both records carry null and the reader says the match is by pid alone. No glibc or libmalloc lines (Windows prints none).
# It NEVER stops the server from starting: a failure to find the data folder or to write a record is swallowed and the server runs as before;
# launch.cmd also starts the bare server when this script could not even start it (the marker file below is how it knows).
#
# NOT RUN ON WINDOWS. Written for Windows PowerShell 5.1 (the `powershell` launch.cmd calls) and tested on PowerShell 7 on Linux with a fake
# server (tests/test_launch_wrapper.py); the console behaviour of a real Windows window, `powershell.exe` 5.1 itself and the signed exit codes
# of a real crash are untested. See docs/ledger/OPEN_QUEUE.md.
param(
    [Parameter(Mandatory = $true)][string]$App,
    [string]$Marker = "",
    [string]$DataDir = ""
)

$ErrorActionPreference = "Continue"
$Keep = 20
# The whole lines worth keeping, exactly (tests/test_launch_wrapper.py pins this list to the Python fatal-error headers in ABORT_MESSAGES).
$Messages = @(
    "Fatal Python error: Aborted",
    "Fatal Python error: Segmentation fault",
    "Fatal Python error: Bus error",
    "Fatal Python error: Illegal instruction",
    "Fatal Python error: Floating point exception"
)
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Get-Stamp { [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ") }

function Add-Row([string]$Path, $Row) {
    try {
        $text = ($Row | ConvertTo-Json -Compress) + "`n"
        [System.IO.File]::AppendAllText($Path, $text, $Utf8)
        return $true
    } catch { return $false }
}

# Where the app keeps its data: ask the app (src/paths.py data_dir), so the precedence is never copied here.
function Get-DataDir {
    if ($DataDir) { return $DataDir }
    try {
        $py = Join-Path (Split-Path -Parent $App) "python.exe"
        if (-not (Test-Path $py)) { return $null }
        $out = & $py -c "from src.paths import data_dir; print(data_dir())" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ([string]($out | Select-Object -Last 1)).Trim() }
    } catch { }
    return $null
}

$diag = $null
if ($env:OO_EPHEMERAL -ne "1") {
    try {
        $dd = Get-DataDir
        if ($dd) {
            $diag = Join-Path $dd "diagnostics"
            [void][System.IO.Directory]::CreateDirectory($diag)
        }
    } catch { $diag = $null }
}
$stderrRecord = if ($diag) { Join-Path $diag "launcher_stderr.jsonl" } else { $null }
$exitRecord = if ($diag) { Join-Path $diag "launcher_exits.jsonl" } else { $null }
$stopRecord = if ($diag) { Join-Path $diag "launcher_stops.jsonl" } else { $null }

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $App
$psi.UseShellExecute = $false
$psi.RedirectStandardError = $true
$p = New-Object System.Diagnostics.Process
$p.StartInfo = $psi
$startedAt = Get-Stamp
try {
    [void]$p.Start()
} catch {
    # could not start the server through this wrapper: say nothing was started, so launch.cmd starts it the plain way
    exit 9009
}
if ($Marker) { try { [System.IO.File]::WriteAllText($Marker, [string]$p.Id, $Utf8) } catch { } }

$kept = 0; $dropped = 0; $over = 0
$writable = [bool]$stderrRecord
$stderr = [Console]::Error
while ($true) {
    $line = $p.StandardError.ReadLine()
    if ($null -eq $line) { break }
    $stderr.WriteLine($line)   # every line reaches the window, as before
    if ($Messages -ccontains $line) {
        if ($kept -lt $Keep) {
            if ($writable) {
                $ok = Add-Row $stderrRecord ([ordered]@{ schema = "oo-launcher-stderr-1"; at = (Get-Stamp); pid = $p.Id; boot_id = $null; line = $line })
                if (-not $ok) { $writable = $false }
            }
            $kept++
        } else { $over++ }
    } else { $dropped++ }
}
$p.WaitForExit()
$code = $p.ExitCode

if ($stderrRecord -and $writable) {
    [void](Add-Row $stderrRecord ([ordered]@{ schema = "oo-launcher-stderr-1"; at = (Get-Stamp); pid = $p.Id; boot_id = $null; summary = $true; kept_lines = $kept; dropped_lines = $dropped; over_cap_lines = $over }))
    try {
        $rows = [System.IO.File]::ReadAllLines($stderrRecord, $Utf8)
        if ($rows.Length -gt 100) { [System.IO.File]::WriteAllLines($stderrRecord, ($rows | Select-Object -Last 100), $Utf8) }
    } catch { }
}

# 0 is a normal stop; 0xC000013A (-1073741510) is Ctrl-C in this window, a stop somebody asked for. Anything else is an end to record.
# A Ctrl-C leaves the stop-asked row the bash launcher writes (R168): the next boot reads an unclean end WITH that row as "stop requested,
# teardown incomplete", never a crash. It is written AFTER the server ended (this script has no console handler: not written on Windows, untested),
# carries no signal name (Windows has none) and the status instead, and is trimmed the way launcher_exits.jsonl is.
if ($stopRecord -and $code -eq -1073741510) {
    [void](Add-Row $stopRecord ([ordered]@{ schema = "oo-launcher-stop-1"; at = (Get-Stamp); pid = $p.Id; boot_id = $null; signal = $null; status = $code }))
    try {
        $rows = [System.IO.File]::ReadAllLines($stopRecord, $Utf8)
        if ($rows.Length -gt 40) { [System.IO.File]::WriteAllLines($stopRecord, ($rows | Select-Object -Last 20), $Utf8) }
    } catch { }
}
if ($exitRecord -and $code -ne 0 -and $code -ne -1073741510) {
    [void](Add-Row $exitRecord ([ordered]@{ schema = "oo-launcher-exit-1"; at = (Get-Stamp); started_at = $startedAt; pid = $p.Id; boot_id = $null; status = $code; signal = $null }))
    try {
        $rows = [System.IO.File]::ReadAllLines($exitRecord, $Utf8)
        if ($rows.Length -gt 40) { [System.IO.File]::WriteAllLines($exitRecord, ($rows | Select-Object -Last 20), $Utf8) }
    } catch { }
}
exit $code
