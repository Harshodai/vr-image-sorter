# VR Image Sorter — Windows task runner.
# Mirrors the Makefile targets so both platforms use the same command names.
#   .\make.cmd setup      (cmd.exe)
#   .\make.ps1 setup      (PowerShell)

param([Parameter(Position = 0)][string]$Target = 'help')

$ErrorActionPreference = 'Stop'
$Root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv  = Join-Path $Root 'backend\.venv'
$VPy   = Join-Path $Venv 'Scripts\python.exe'
$VUvi  = Join-Path $Venv 'Scripts\uvicorn.exe'

function Have($cmd) { $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Resolve-Python {
    foreach ($c in @('python', 'python3', 'py')) {
        if (Have $c) {
            $v = & $c --version 2>&1
            if ($v -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 9) { return $c }
        }
    }
    throw "Python 3.9+ not found. Install from https://python.org and re-open the terminal."
}

function Setup-Backend {
    $py = Resolve-Python
    # uv is 10-100x faster than pip. Use it when present, otherwise fall back.
    if (Have 'uv') {
        Write-Host '==> uv detected: fast install' -ForegroundColor Cyan
        & uv venv $Venv --python $py --allow-existing
        $env:VIRTUAL_ENV = $Venv
        & uv pip install -r (Join-Path $Root 'backend\requirements.txt')
    } else {
        Write-Host '==> uv not found, using pip (slower). Install uv: winget install astral-sh.uv' -ForegroundColor Yellow
        if (-not (Test-Path $VPy)) { & $py -m venv $Venv }
        & $VPy -m pip install --upgrade pip
        & $VPy -m pip install -r (Join-Path $Root 'backend\requirements.txt')
    }
    Push-Location (Join-Path $Root 'backend')
    try { & $VPy preload_models.py } finally { Pop-Location }
}

function Setup-Frontend {
    if (-not (Have 'npm')) { throw "Node.js/npm not found. Install Node 20+ from https://nodejs.org" }
    Push-Location $Root
    try {
        npm ci --prefer-offline --no-audit --fund=false
        if ($LASTEXITCODE -ne 0) { npm install --no-audit --fund=false }
    } finally { Pop-Location }
}

switch ($Target.ToLower()) {

    'help' {
        Write-Host ".\make.cmd <target>`n"
        @(
            @('doctor',    'Check prerequisites are installed'),
            @('setup',     'One-shot install: backend venv + OCR models + frontend deps'),
            @('dev',       'Run backend + frontend together'),
            @('dev-backend',  'Backend only on :8000'),
            @('dev-frontend', 'Frontend only on :8080'),
            @('up',        'Build + start full stack in Docker'),
            @('down',      'Stop Docker stack'),
            @('logs',      'Tail Docker logs'),
            @('test',      'Accuracy check against .\input'),
            @('test-real', 'Accuracy check against sandbox real images'),
            @('bench-varahi', '100-image benchmark on Varahi production saree dataset'),
            @('test-all',  'Master benchmark across all 124+ images in all datasets'),
            @('bench',     'Timing on .\input'),
            @('dist',      'Build distributable zip in .\dist'),
            @('clean',     'Remove venv, node_modules, dist')
        ) | ForEach-Object { '  {0,-16} {1}' -f $_[0], $_[1] }
    }

    'doctor' {
        foreach ($c in @('python', 'uv', 'node', 'npm', 'docker')) {
            $v = if (Have $c) { (& $c --version 2>&1 | Select-Object -First 1) } else { 'NOT FOUND' }
            '{0,-8}: {1}' -f $c, $v
        }
    }

    'setup' {
        Setup-Backend
        Setup-Frontend
        Write-Host "`nSetup complete. Run '.\make.cmd dev' then open http://localhost:8080" -ForegroundColor Green
    }

    'setup-backend'  { Setup-Backend }
    'setup-frontend' { Setup-Frontend }

    'dev' {
        Write-Host ""
        Write-Host "========================================================" -ForegroundColor Cyan
        Write-Host "  Starting VR Saree Image Sorter Full Stack" -ForegroundColor Cyan
        Write-Host "  👉 Open your browser at: http://localhost:8080" -ForegroundColor Green
        Write-Host "  🔌 Backend API running at: http://localhost:8000" -ForegroundColor Gray
        Write-Host "========================================================" -ForegroundColor Cyan
        Write-Host ""

        # Backend in its own window so Ctrl-C on the frontend does not orphan it.
        Start-Process -FilePath 'powershell' -ArgumentList @(
            '-NoExit', '-Command', "Set-Location '$Root\backend'; Write-Host 'Backend API running on http://localhost:8000 (Keep this window open)' -ForegroundColor Green; & '$VUvi' main:app --host 0.0.0.0 --port 8000"
        )
        Start-Sleep -Seconds 2
        $env:VITE_API_URL = 'http://localhost:8000'
        Push-Location $Root
        try { npm run dev -- --port 8080 --open } finally { Pop-Location }
    }

    'dev-backend' {
        Push-Location (Join-Path $Root 'backend')
        try { & $VUvi main:app --host 0.0.0.0 --port 8000 } finally { Pop-Location }
    }

    'dev-frontend' {
        $env:VITE_API_URL = 'http://localhost:8000'
        Push-Location $Root
        try { npm run dev -- --port 8080 } finally { Pop-Location }
    }

    'up' {
        docker compose up --build -d
        $port   = if ($env:PORT)    { $env:PORT }    else { '8001' }
        $uiPort = if ($env:UI_PORT) { $env:UI_PORT } else { '8088' }
        Write-Host "frontend http://localhost:$uiPort   backend http://localhost:$port/docs"
    }
    'down'    { docker compose down }
    'logs'    { docker compose logs -f }
    'build'   { docker compose build }
    'rebuild' { docker compose build --no-cache }

    'test' {
        Push-Location $Root
        try { & $VPy test_pipeline.py } finally { Pop-Location }
    }

    'test-real' {
        Push-Location (Join-Path $Root 'backend')
        try { & $VPy test_real_images.py } finally { Pop-Location }
    }

    'bench-varahi' {
        Push-Location (Join-Path $Root 'backend')
        try { & $VPy test_varahi_benchmark.py } finally { Pop-Location }
    }

    'test-all' {
        Push-Location (Join-Path $Root 'backend')
        try { & $VPy test_all_datasets.py } finally { Pop-Location }
    }

    'bench' {
        Push-Location (Join-Path $Root 'backend')
        try {
            & $VPy -c "import sys,glob,time; sys.path.insert(0,'.'); from scanner.pipeline import process_pipeline as p; fs=sorted(glob.glob('../input/*')); t=time.monotonic(); r=[p(open(f,'rb').read()) for f in fs]; d=time.monotonic()-t; print(f'{len(fs)} imgs {d:.1f}s  {d/len(fs):.2f}s/img  hits={sum(1 for x in r if x)}/{len(fs)}')"
        } finally { Pop-Location }
    }

    'dist' {
        $out = Join-Path $Root 'dist'
        New-Item -ItemType Directory -Force -Path $out | Out-Null
        $zip = Join-Path $out 'vr-image-sorter.zip'
        Remove-Item $zip -ErrorAction SilentlyContinue
        Push-Location $Root
        try { git archive --format=zip -o $zip HEAD } finally { Pop-Location }
        Write-Host "wrote $zip"
    }

    'clean' {
        foreach ($p in @($Venv, (Join-Path $Root 'node_modules'), (Join-Path $Root 'dist'))) {
            Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
        }
    }

    default { throw "Unknown target '$Target'. Run '.\make.cmd help'." }
}
