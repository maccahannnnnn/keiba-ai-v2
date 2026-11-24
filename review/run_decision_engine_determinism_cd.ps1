param(
    [string]$OutputRoot = ''
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv_keibaai_ml_v4\Scripts\python.exe'
$runner = Join-Path $repo 'review\decision_engine_determinism_fix_v1.py'
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repo 'reports\full_field_redesign_iter0_v1_retry6\pre_only_regeneration'
}
$env:WS2_REGEN_OUTPUT_ROOT = $OutputRoot

foreach ($laneSeed in @(@('run_c', '271828'), @('run_d', '314159'))) {
    $lane = $laneSeed[0]
    $env:PYTHONHASHSEED = $laneSeed[1]
    for ($start = 0; $start -lt 62; $start += 2) {
        $stop = [Math]::Min($start + 2, 62)
        & $python $runner --shard $lane $start $stop
        if ($LASTEXITCODE -ne 0) { throw "PRE_ONLY_SHARD_FAILED:${lane}:${start}:${stop}" }
    }
}

Remove-Item Env:PYTHONHASHSEED -ErrorAction SilentlyContinue
& $python $runner --finalize
if ($LASTEXITCODE -ne 0) { throw 'PRE_ONLY_FINALIZE_FAILED' }
