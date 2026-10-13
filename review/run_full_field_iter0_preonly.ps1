param(
    [string]$OutputRoot = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv_keibaai_ml_v4\Scripts\python.exe'
$runner = Join-Path $repo 'review\ws2_deterministic_pre_only_regeneration_v1.py'
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repo 'reports\full_field_redesign_iter0_v1\pre_only_regeneration'
}
$env:WS2_REGEN_OUTPUT_ROOT = $OutputRoot

foreach ($lane in @('run_a', 'run_b', 'meeting_bias_ablation')) {
    for ($start = 0; $start -lt 62; $start += 10) {
        $stop = [Math]::Min($start + 10, 62)
        & $python $runner --shard $lane $start $stop
        if ($LASTEXITCODE -ne 0) { throw "PRE_ONLY_SHARD_FAILED:${lane}:${start}:${stop}" }
    }
}
& $python $runner --finalize
if ($LASTEXITCODE -ne 0) { throw 'PRE_ONLY_FINALIZE_FAILED' }
