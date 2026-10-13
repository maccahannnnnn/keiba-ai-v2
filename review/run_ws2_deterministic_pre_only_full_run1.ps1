[CmdletBinding()]
param(
    [switch]$FinalizeOnly
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $RepoRoot '.venv_keibaai_ml_v4\Scripts\python.exe'
$Harness = Join-Path $RepoRoot 'review\ws2_deterministic_pre_only_regeneration_v1.py'
$RunRoot = Join-Path $RepoRoot 'reports\ws2_deterministic_pre_only_regeneration_v1_full_run1'
$ShardRoot = Join-Path $RunRoot 'shards'
$LogRoot = Join-Path $RunRoot 'logs'
$LedgerPath = Join-Path $RunRoot 'execution_ledger.json'
$ChunkSize = 5
$TotalDates = 62
$Lanes = @('run_a', 'run_b', 'meeting_bias_ablation')

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "PYTHON_MISSING:$Python" }
if (-not (Test-Path -LiteralPath $Harness -PathType Leaf)) { throw "HARNESS_MISSING:$Harness" }
New-Item -ItemType Directory -Force -Path $RunRoot, $ShardRoot, $LogRoot | Out-Null
$env:WS2_REGEN_OUTPUT_ROOT = $RunRoot

function Get-Json([string]$Path) {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
}

function Test-Ws2Shard([string]$Lane, [int]$Start, [int]$Stop) {
    $name = '{0}_{1:d3}_{2:d3}' -f $Lane, $Start, $Stop
    $dir = Join-Path $ShardRoot $name
    $required = @('runtime_pre_only_output.json', 'runtime_import_trace.json', 'runtime_file_access_trace.json', 'stop_access_violation_log.json', 'run_hash_index.json')
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { return $false }
    foreach ($file in $required) { if (-not (Test-Path -LiteralPath (Join-Path $dir $file) -PathType Leaf)) { return $false } }
    try {
        $index = Get-Json (Join-Path $dir 'run_hash_index.json')
        foreach ($entry in $index.files.GetEnumerator()) {
            $path = Join-Path $dir $entry.Key
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
            if ((Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant() -ne $entry.Value.ToLowerInvariant()) { return $false }
        }
        $stop = Get-Json (Join-Path $dir 'stop_access_violation_log.json')
        $payload = Get-Json (Join-Path $dir 'runtime_pre_only_output.json')
        return ($stop.count -eq 0 -and $stop.network_access_attempt_count -eq 0 -and $payload.generated_rows.Count -gt 0)
    } catch { return $false }
}

function Add-Ledger([hashtable]$Entry) {
    $rows = @()
    if (Test-Path -LiteralPath $LedgerPath -PathType Leaf) {
        $existing = Get-Json $LedgerPath
        if ($existing.entries) { $rows = @($existing.entries) }
    }
    $rows += $Entry
    @{ run_root = $RunRoot; entries = $rows } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $LedgerPath -Encoding UTF8
}

function Invoke-Ws2Shard([string]$Lane, [int]$Start, [int]$Stop) {
    $name = '{0}_{1:d3}_{2:d3}' -f $Lane, $Start, $Stop
    $output = Join-Path $ShardRoot $name
    if (Test-Ws2Shard $Lane $Start $Stop) {
        Write-Host "SKIP_VALID:$name"
        return
    }
    if (Test-Path -LiteralPath $output) { throw "EXISTING_INVALID_SHARD_REQUIRES_HUMAN_REVIEW:$output" }
    $stdout = Join-Path $LogRoot "$name.stdout.log"
    $stderr = Join-Path $LogRoot "$name.stderr.log"
    $command = '"{0}" "{1}" --shard {2} {3} {4}' -f $Python, $Harness, $Lane, $Start, $Stop
    $started = (Get-Date).ToString('o')
    $process = Start-Process -FilePath $Python -ArgumentList ('"{0}" --shard {1} {2} {3}' -f $Harness, $Lane, $Start, $Stop) -WorkingDirectory $RepoRoot -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $ended = (Get-Date).ToString('o')
    $hash = if (Test-Path -LiteralPath (Join-Path $output 'run_hash_index.json') -PathType Leaf) { (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $output 'run_hash_index.json')).Hash.ToLowerInvariant() } else { $null }
    Add-Ledger @{ kind = 'shard'; lane = $Lane; start = $Start; stop = $Stop; command = $command; started_at = $started; ended_at = $ended; exit_code = $process.ExitCode; output_directory = $output; stdout_log = $stdout; stderr_log = $stderr; run_hash_index_sha256 = $hash }
    if ($process.ExitCode -ne 0) { throw "SHARD_FAILED:$name:EXIT_$($process.ExitCode)" }
    if (-not (Test-Ws2Shard $Lane $Start $Stop)) { throw "SHARD_COMPLETION_OR_BOUNDARY_VALIDATION_FAILED:$name" }
}

function Assert-AllShardsValid {
    foreach ($lane in $Lanes) {
        for ($start = 0; $start -lt $TotalDates; $start += $ChunkSize) {
            $stop = [Math]::Min($start + $ChunkSize, $TotalDates)
            if (-not (Test-Ws2Shard $lane $start $stop)) { throw "FINALIZATION_BLOCKED_INCOMPLETE_OR_INVALID_SHARD:$lane/$start/$stop" }
        }
    }
}

if (-not $FinalizeOnly) {
    foreach ($lane in $Lanes) {
        for ($start = 0; $start -lt $TotalDates; $start += $ChunkSize) {
            $stop = [Math]::Min($start + $ChunkSize, $TotalDates)
            Invoke-Ws2Shard $lane $start $stop
        }
    }
}

Assert-AllShardsValid
$finalStdout = Join-Path $LogRoot 'finalize.stdout.log'
$finalStderr = Join-Path $LogRoot 'finalize.stderr.log'
$started = (Get-Date).ToString('o')
$process = Start-Process -FilePath $Python -ArgumentList ('"{0}" --finalize' -f $Harness) -WorkingDirectory $RepoRoot -Wait -PassThru -NoNewWindow -RedirectStandardOutput $finalStdout -RedirectStandardError $finalStderr
$ended = (Get-Date).ToString('o')
Add-Ledger @{ kind = 'finalize'; command = ('"{0}" "{1}" --finalize' -f $Python, $Harness); started_at = $started; ended_at = $ended; exit_code = $process.ExitCode; stdout_log = $finalStdout; stderr_log = $finalStderr }
if ($process.ExitCode -ne 0) { throw "FINALIZATION_FAILED:EXIT_$($process.ExitCode)" }
Write-Host "COMPLETE:$RunRoot"
