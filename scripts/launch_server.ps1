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
    [string]$DataDir = "",
    # THE TERMINAL PANEL IN THIS WINDOW (R658). launch.cmd passes the venv's python here when "import curses" works there; the panel
    # (src\tui\panel.py) is then started in THIS console beside the server, with the server's pid, so the launcher is ONE window whose
    # panel stays for as long as the server runs. Empty: no panel, exactly as before.
    [string]$PanelPython = "",
    [string]$Port = "8000",
    [string]$Url = ""
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
# A row that cannot be appended at once (the file held open by a scanner or another program for a moment) is tried again, five tries over 0.5 s, before
# it is given up (item 66). It helps a refusal at open, before any byte is written; an append cut short part way (a full disk) still leaves a torn line.
function Add-RowText([string]$Path, [string]$Text) {
    for ($try = 1; $try -le 5; $try++) {
        try {
            [System.IO.File]::AppendAllText($Path, $Text, $Utf8)
            return $true
        } catch { if ($try -lt 5) { Start-Sleep -Milliseconds (50 * $try) } }
    }
    return $false
}
# A ROW WRITTEN WITHOUT THE LOCK SAYS SO (item 66 follow-up, 2026-11-14). Every such append can race another launcher's trim and be lost, and on CI
# one was (run 43552997010: 24 lines and 7 of 8 rows, which takes an append that skipped both the lock and the trim). These paths were silent, so
# that red could not say which one ran. The words are fixed and carry nothing of the row; the reason is one of a fixed few or an exception's type name.
function Add-RowUnlocked([string]$Path, [string]$Text, [string]$Why) {
    [Console]::Error.WriteLine("launcher record: a row was appended without the lock: $Why")
    $ok = Add-RowText $Path $Text
    if (-not $ok) { [Console]::Error.WriteLine('launcher record: a row could not be appended after 5 tries and was not written') }
    return $ok
}

# THE EVIDENCE FILES AND THE LAUNCHERS THAT SHARE THEM (R173). Every append and every trim of one file happens under ONE named mutex for that file
# (the scripts/launch.sh counterpart), and a trim writes a temp file of its own and replaces the file with it. Before, the trim read the whole file
# and wrote it back in place: a row appended in between was lost, an append during the rewrite failed on the file lock and was swallowed, and a
# half-written line was left in the file (measured with 8 launchers at once: 4 of 48 exit rows lost, 2 torn lines).
# A ROW IS WRITTEN UNDER THE MUTEX (R174) whenever the mutex can be made and waited on; where it cannot, the row is appended without it rather than lost
# (item 66), and only such a row can still be lost, to another launcher's trim. The launcher waits for it only $RecLockWaitMs; when that runs
# out it hands the row to a detached child process and carries on at once. ONLY WHEN NO CHILD CAN BE STARTED does the launcher wait itself (item 66):
# with no bound for the rows it writes after the server ended, and $RecFallbackWaitMs for a stderr row while the server runs, since a launcher blocked
# there stops draining the server's stderr; after that bound the row is appended without the mutex. The child waits for the same mutex with no time bound, then does the locked
# append and the trim if due; a holder that dies abandons the mutex, so the child ends once the holder does. THE ONE WAY A ROW CAN STILL BE LATE: a holder
# that is alive and stuck for ever; the child waits with it. Late is not lost while the machine runs; a machine that goes down before the child writes
# loses the row. A deferred row can land after later rows: the readers order by the row's own time. The child leaves no file behind (the row travels through its
# standard input). WHAT THE WAIT PROTECTS: the time the launcher itself is willing to wait before it defers. $RecLockWaitMs is the longest append-plus-trim hold
# measured under the heaviest load tried (8 launchers at once beside 8 busy loops on 4 CPUs: 515.0 ms, cold PowerShell 7, 17 Oct), rounded up to 520
# (tests/test_launcher_records_race.py pins that the constant is not below that measurement).
$RecLockWaitMs = 520
$RecFallbackWaitMs = 10000
function Get-RecMutex([string]$Path) {
    try {
        $sha = [System.Security.Cryptography.SHA1]::Create()
        $name = "OOLauncherRecords-" + ([System.BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Path.ToLowerInvariant()))) -replace "-", "")
        return New-Object System.Threading.Mutex($false, $name)
    } catch { return $null }
}
# Append $Row to $Path and, when the file then has more than $Max lines, keep its newest $Keep lines. Returns whether the row was appended or handed on.
# $FallbackWaitMs: how long this launcher waits itself when no deferred child can be started (-1: no bound).
function Add-RowTrimmed([string]$Path, $Row, [int]$Max, [int]$Keep, [int]$FallbackWaitMs = -1) {
    $text = ($Row | ConvertTo-Json -Compress) + "`n"
    $mutex = Get-RecMutex $Path
    if (-not $mutex) { return (Add-RowUnlocked $Path $text "no lock could be made for the file") }   # no mutex can be made at all: as before, and said
    $held = $false
    try {
        try { $held = $mutex.WaitOne($RecLockWaitMs) } catch [System.Threading.AbandonedMutexException] { $held = $true } catch { return (Add-RowUnlocked $Path $text ("waiting for its lock failed (" + $_.Exception.GetBaseException().GetType().Name + ")")) }
        if (-not $held) {
            if (Start-DeferredRow $Path $text $Max $Keep) { return $true }
            # no child could be started or handed the row (item 66: that row was dropped): this launcher waits for the mutex itself, so the row is late
            # and the launcher ends late, never the row lost; past a bounded wait the row is appended without the mutex
            try { $held = $mutex.WaitOne($FallbackWaitMs) } catch [System.Threading.AbandonedMutexException] { $held = $true } catch { return (Add-RowUnlocked $Path $text ("waiting for its lock failed (" + $_.Exception.GetBaseException().GetType().Name + ")")) }
            if (-not $held) { return (Add-RowUnlocked $Path $text "its lock was not obtained in time") }
        }
        $ok = Add-RowText $Path $text
        if (-not $ok) { [Console]::Error.WriteLine('launcher record: a row could not be appended after 5 tries and was not written') }
        if ($ok -and $Max -gt 0) { Limit-Rows $Path $Max $Keep }
        return $ok
    } finally {
        if ($held) { try { $mutex.ReleaseMutex() } catch { } }
        $mutex.Dispose()
    }
}
# The row of a launcher that could not get the mutex in time: a detached child process waits for it with no bound, then appends and trims. THE ROW IS NOT
# IN THE CHILD'S COMMAND LINE (R174): a command line is visible to every local user in a process listing, and under script block logging the decoded command
# reaches the event log, and a stderr row carries whatever the server printed. The child's command line is one fixed script; the path, the limits and the row
# go to it through its standard input. Returns $true when the child was started and given the row, $false when not (the caller then waits for the mutex
# itself, item 66). THE CHILD DROPS NOTHING SILENTLY (item 66): a mutex it cannot make or wait on gets the row appended without it, exactly as the launcher
# does in that case; a row it still cannot write, or an input cut short, is said on its standard error in fixed words that carry none of the row.
function Start-DeferredRow([string]$Path, [string]$Text, [int]$Max, [int]$Keep) {
    try {
        $fns = (@("Add-RowText", "Get-RecMutex", "Limit-Rows") | ForEach-Object { "function $_ {" + (Get-Command $_ -CommandType Function).ScriptBlock.ToString() + "}" }) -join "`n"
        $child = "`$Utf8 = New-Object System.Text.UTF8Encoding(`$false)`n" + $fns + "`n" +
            "`$ms = New-Object System.IO.MemoryStream; [Console]::OpenStandardInput().CopyTo(`$ms)`n" +
            "`$in = `$Utf8.GetString(`$ms.ToArray()); `$parts = `$in.Split([char]10, 4)`n" +
            "if (`$parts.Length -lt 4 -or `$parts[3].Length -eq 0 -or `$parts[3][-1] -ne [char]10) { [Console]::Error.WriteLine('launcher record: a deferred row arrived cut short and was not written'); exit 1 }`n" +
            "`$path = `$parts[0]; `$max = [int]`$parts[1]; `$keep = [int]`$parts[2]; `$text = `$parts[3]`n" +
            "`$m = Get-RecMutex `$path; `$held = `$false`n" +
            "if (-not `$m) { [Console]::Error.WriteLine('launcher record: a deferred row was appended without the lock: no lock could be made for the file') }`n" +
            "if (`$m) { try { `$m.WaitOne() | Out-Null; `$held = `$true } catch [System.Threading.AbandonedMutexException] { `$held = `$true } catch { [Console]::Error.WriteLine('launcher record: a deferred row was appended without the lock: waiting for its lock failed (' + `$_.Exception.GetBaseException().GetType().Name + ')') } }`n" +
            "try { `$ok = Add-RowText `$path `$text`n" +
            "  if (`$ok -and `$held -and `$max -gt 0) { Limit-Rows `$path `$max `$keep }`n" +
            "  if (-not `$ok) { [Console]::Error.WriteLine('launcher record: a deferred row could not be appended'); exit 1 }`n" +
            "} finally { if (`$held) { try { `$m.ReleaseMutex() } catch { } } }"
        $enc = [System.Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($child))
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = (Get-Process -Id $PID).Path
        $psi.Arguments = "-NoProfile -NonInteractive -EncodedCommand $enc"
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.CreateNoWindow = $true
        $cp = [System.Diagnostics.Process]::Start($psi)
        $bytes = $Utf8.GetBytes("$Path`n$Max`n$Keep`n$Text")
        $cp.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        $cp.StandardInput.BaseStream.Flush()
    } catch { return $false }   # a row cut short is refused by the child (above), so the caller writing it cannot write it twice
    try { $cp.StandardInput.Close() } catch { }   # the whole row is in the pipe: the child has it, whatever Close says
    return $true
}
function Limit-Rows([string]$Path, [int]$Max, [int]$Keep) {
    $tmp = "$Path.tmp.$PID"
    # a temp file left by a launcher that was killed mid-trim is removed: its name carries that launcher process id
    try {
        foreach ($old in [System.IO.Directory]::GetFiles((Split-Path -Parent $Path), ((Split-Path -Leaf $Path) + ".tmp.*"))) {
            $oldPid = 0
            if ([int]::TryParse(($old -replace '^.*\.tmp\.', ''), [ref]$oldPid) -and $oldPid -ne $PID -and -not (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
                Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
            }
        }
    } catch { }
    try {
        $rows = [System.IO.File]::ReadAllLines($Path, $Utf8)
        if ($rows.Length -gt $Max) {
            [System.IO.File]::WriteAllLines($tmp, ($rows | Select-Object -Last $Keep), $Utf8)
            [System.IO.File]::Replace($tmp, $Path, [NullString]::Value)
        }
    } catch { [Console]::Error.WriteLine("launcher record: a trim failed and the file was left as it was (" + $_.Exception.GetBaseException().GetType().Name + ")") }
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
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

# The panel (R658). It inherits this console, so it draws in the launcher's own window; it watches the server by pid (and start time),
# so it ends when the server ends, never on a quiet server. Neither it nor the curses check below gets the passphrases the server holds
# (the names are src\monitoring\secret_scrub.py HELD_ENV_VARS, which tests\test_launcher_browser_env.py holds this list to): they are
# removed from each one's environment here, and the panel drops them from its own as it starts. The port and the address are checked to
# be what launch.cmd builds (a number; http to 127.0.0.1), so nothing else reaches its command line. Python's curses exists on Windows
# only with windows-curses (no ARM64 build), so the panel starts only when "import curses" works. A panel that cannot start changes
# nothing for the server.
$HeldEnvVars = @("OO_DB_PASSPHRASE", "OO_KEY_PASSPHRASE")
function New-PanelStartInfo([string]$Arguments) {
    $si = New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName = $PanelPython
    $si.Arguments = $Arguments
    $si.UseShellExecute = $false
    foreach ($n in $HeldEnvVars) { if ($si.EnvironmentVariables.ContainsKey($n)) { $si.EnvironmentVariables.Remove($n) } }
    return $si
}
$panel = $null
if ($PanelPython -and ($Port -match '^[0-9]{1,5}$')) {
    try {
        $check = New-PanelStartInfo '-c "import curses"'
        $check.RedirectStandardOutput = $true
        $check.RedirectStandardError = $true
        $cp = [System.Diagnostics.Process]::Start($check)
        $cp.StandardOutput.ReadToEnd() | Out-Null
        $cp.StandardError.ReadToEnd() | Out-Null
        $cp.WaitForExit()
        if ($cp.ExitCode -eq 0) {
            $panelArgs = "-m src.tui.panel --port $Port --server-pid $($p.Id)"
            if ($Url -match '^http://127\.0\.0\.1:[0-9]{1,5}/$') { $panelArgs += " --url $Url" }
            $panel = [System.Diagnostics.Process]::Start((New-PanelStartInfo $panelArgs))
        }
    } catch { $panel = $null }
}

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
                # each row makes its own attempt: one that fails (another launcher held the file) does not switch the later rows off (R173)
                [void](Add-RowTrimmed $stderrRecord ([ordered]@{ schema = "oo-launcher-stderr-1"; at = (Get-Stamp); pid = $p.Id; boot_id = $null; line = $line }) 0 0 $RecFallbackWaitMs)
            }
            $kept++
        } else { $over++ }
    } else { $dropped++ }
}
$p.WaitForExit()
$code = $p.ExitCode
# The panel ends on its own within a second of the server (it watches the pid); it is waited for so the console is the launcher's again
# before "Open Omniscience has stopped" is printed, and ended only if it has not gone after 15 s.
if ($panel) {
    try { if (-not $panel.WaitForExit(15000)) { $panel.Kill() } } catch { }
}

if ($stderrRecord -and $writable) {
    [void](Add-RowTrimmed $stderrRecord ([ordered]@{ schema = "oo-launcher-stderr-1"; at = (Get-Stamp); pid = $p.Id; boot_id = $null; summary = $true; kept_lines = $kept; dropped_lines = $dropped; over_cap_lines = $over }) 100 100)
}

# 0 is a normal stop; 0xC000013A (-1073741510) is Ctrl-C in this window, a stop somebody asked for. Anything else is an end to record.
# A Ctrl-C leaves the stop-asked row the bash launcher writes (R168): the next boot reads an unclean end WITH that row as "stop requested,
# teardown incomplete", never a crash. It is written AFTER the server ended (this script has no console handler: not written on Windows, untested),
# carries no signal name (Windows has none) and the status instead, and is trimmed the way launcher_exits.jsonl is.
if ($stopRecord -and $code -eq -1073741510) {
    [void](Add-RowTrimmed $stopRecord ([ordered]@{ schema = "oo-launcher-stop-1"; at = (Get-Stamp); pid = $p.Id; boot_id = $null; signal = $null; status = $code }) 40 20)
}
if ($exitRecord -and $code -ne 0 -and $code -ne -1073741510) {
    [void](Add-RowTrimmed $exitRecord ([ordered]@{ schema = "oo-launcher-exit-1"; at = (Get-Stamp); started_at = $startedAt; pid = $p.Id; boot_id = $null; status = $code; signal = $null }) 40 20)
}
exit $code
