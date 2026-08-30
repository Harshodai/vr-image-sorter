# VR Image Sorter -- Windows task runner.
# Mirrors the Makefile targets so both platforms use the same command names.
#   .\make.cmd setup      (cmd.exe)
#   .\make.ps1 setup      (PowerShell)

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = 'help',

    [string]$IN = '',
    [string]$OUT = '',
    [string]$CSV = '',
    [string]$SORT_ARGS = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root 'backend\.venv'

$IsWin = ($PSVersionTable.PSEdition -ne 'Core') -or ($IsWindows) -or ($env:OS -like '*Windows*')
if ($IsWin) {
    $VPy  = Join-Path $Venv 'Scripts\python.exe'
    $VUvi = Join-Path $Venv 'Scripts\uvicorn.exe'
} else {
    $VPy  = Join-Path $Venv 'bin/python'
    $VUvi = Join-Path $Venv 'bin/uvicorn'
}

function Have($cmd) {
    return ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue))
}

function Resolve-Python {
    foreach ($c in @('python', 'python3', 'py')) {
        if (Have $c) {
            $v = & $c --version 2>&1
            $vStr = ("$v" | Out-String)
            if ($vStr -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 9) { return $c }
        }
    }
    throw "Python 3.9+ not found. Install from https://python.org and re-open the terminal."
}

function Setup-Backend {
    $py = Resolve-Python
    if (Have 'uv') {
        Write-Host "==> uv detected: fast install" -ForegroundColor Cyan
        & uv venv $Venv --python $py --allow-existing
        $env:VIRTUAL_ENV = $Venv
        & uv pip install -r (Join-Path $Root 'backend\requirements.txt')
    } else {
        Write-Host "==> uv not found, using pip (slower). Install uv: winget install astral-sh.uv" -ForegroundColor Yellow
        if (-not (Test-Path $VPy)) { & $py -m venv $Venv }
        & $VPy -m pip install --upgrade pip
        & $VPy -m pip install -r (Join-Path $Root 'backend\requirements.txt')
    }
    Push-Location (Join-Path $Root 'backend')
    try {
        $env:APP_ENV = 'development'
        & $VPy preload_models.py
    } finally {
        Pop-Location
    }
}

function Setup-Frontend {
    if (-not (Have 'npm')) {
        throw "Node.js/npm not found. To develop frontend code, install Node from https://nodejs.org. Pre-bundled frontend in backend/static is already ready for use without npm."
    }
    Push-Location $Root
    try {
        Write-Host "==> Installing npm packages..." -ForegroundColor Cyan
        npm ci --prefer-offline --no-audit --fund=false
        if ($LASTEXITCODE -ne 0) { npm install --no-audit --fund=false }
        Write-Host "==> Building frontend assets..." -ForegroundColor Cyan
        npm run build
        $staticDir = Join-Path $Root 'backend\static'
        if (-not (Test-Path $staticDir)) { New-Item -ItemType Directory -Path $staticDir | Out-Null }
        Copy-Item -Recurse -Force (Join-Path $Root 'dist\*') $staticDir
        Write-Host "==> Frontend built and copied to backend\static" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

switch ($Target.ToLower()) {

    'help' {
        Write-Host ".\make.cmd <target>`n"
        Write-Host "--- ZERO-NPM MODE (Python Only) ---" -ForegroundColor Cyan
        @(
            @('doctor',          'Check prerequisites are installed (Python only required)'),
            @('setup',           'One-shot install: backend venv + OCR models (no npm needed)'),
            @('dev',             'Run unified full stack at http://localhost:8000 (no npm needed)'),
            @('sort',            'Sort a folder: .\make.cmd sort -IN ./photos -OUT ./sorted'),
            @('resume',          'Continue interrupted sort: .\make.cmd resume -IN ./photos -OUT ./sorted'),
            @('watch',           'Process images as they land: .\make.cmd watch -IN ./dropbox -OUT ./sorted'),
            @('apply',           'Apply corrected codes: .\make.cmd apply -OUT ./sorted'),
            @('test',            'Accuracy check against .\input'),
            @('test-real',       'Accuracy check against sandbox real images'),
            @('bench-varahi',    '100-image benchmark on Varahi production saree dataset'),
            @('test-all',        'Master benchmark across all 124+ images in all datasets'),
            @('bench',           'Timing benchmark on .\input')
        ) | ForEach-Object { '  {0,-18} {1}' -f $_[0], $_[1] }
        Write-Host "`n--- FRONTEND DEV MODE (with npm) ---" -ForegroundColor Cyan
        @(
            @('setup-frontend',  'Install npm dependencies and rebuild static frontend'),
            @('dev-frontend',    'Run Vite frontend server on :8080 with Hot Module Reloading'),
            @('dev-all',         'Run backend on :8000 + Vite HMR on :8080 simultaneously'),
            @('build-frontend',  'Build React app with Vite and sync to backend\static')
        ) | ForEach-Object { '  {0,-18} {1}' -f $_[0], $_[1] }
        Write-Host "`n--- DOCKER & PACKAGING ---" -ForegroundColor Cyan
        @(
            @('up',              'Build + start full stack in Docker'),
            @('down',            'Stop Docker stack'),
            @('logs',            'Tail Docker logs'),
            @('dist',            'Build distributable zip in .\dist'),
            @('clean',           'Remove venv, node_modules, dist')
        ) | ForEach-Object { '  {0,-18} {1}' -f $_[0], $_[1] }
    }

    'doctor' {
        foreach ($c in @('python', 'uv', 'docker', 'node', 'npm')) {
            $status = if (Have $c) { (& $c --version 2>&1 | Select-Object -First 1) } else { 'NOT FOUND (optional)' }
            '{0,-8}: {1}' -f $c, $status
        }
    }

    'setup' {
        Setup-Backend
        Write-Host ""
        Write-Host "========================================================" -ForegroundColor Green
        Write-Host "  Setup complete! (Zero npm/Node dependencies required)" -ForegroundColor Green
        Write-Host "  Run '.\make.cmd dev' to start the web application." -ForegroundColor Green
        Write-Host "========================================================" -ForegroundColor Green
    }

    'setup-backend'  { Setup-Backend }
    'setup-frontend' { Setup-Frontend }
    'build-frontend' { Setup-Frontend }

    'dev' {
        Write-Host ""
        Write-Host "========================================================" -ForegroundColor Cyan
        Write-Host "  Starting VR Saree Image Sorter" -ForegroundColor Cyan
        Write-Host "  [>] Web App running at: http://localhost:8000" -ForegroundColor Green
        Write-Host "  [+] Zero Node.js/npm dependencies needed" -ForegroundColor Gray
        Write-Host "========================================================" -ForegroundColor Cyan
        Write-Host ""

        Start-Process "http://localhost:8000" -ErrorAction SilentlyContinue

        $env:APP_ENV = 'development'
        Push-Location (Join-Path $Root 'backend')
        try {
            & $VUvi main:app --host 0.0.0.0 --port 8000 --reload
        } finally {
            Pop-Location
        }
    }

    'dev-backend' {
        $env:APP_ENV = 'development'
        Push-Location (Join-Path $Root 'backend')
        try { & $VUvi main:app --host 0.0.0.0 --port 8000 --reload } finally { Pop-Location }
    }

    'dev-frontend' {
        if (-not (Have 'npm')) { throw "Node.js/npm not found. For zero-npm mode, run '.\make.cmd dev' instead." }
        $env:VITE_API_URL = 'http://localhost:8000'
        Push-Location $Root
        try { npm run dev -- --port 8080 } finally { Pop-Location }
    }

    'dev-all' {
        if (-not (Have 'npm')) { throw "Node.js/npm not found. For zero-npm mode, run '.\make.cmd dev' instead." }
        Write-Host ""
        Write-Host "========================================================" -ForegroundColor Cyan
        Write-Host "  Starting Dual Development Servers (Vite HMR + Backend)" -ForegroundColor Cyan
        Write-Host "  [>] Vite UI: http://localhost:8080" -ForegroundColor Green
        Write-Host "  [+] API:     http://localhost:8000" -ForegroundColor Gray
        Write-Host "========================================================" -ForegroundColor Cyan
        Write-Host ""

        $backendDir = Join-Path $Root 'backend'
        Start-Process -FilePath 'powershell' -ArgumentList @(
            '-NoExit',
            '-Command',
            "Set-Location '$backendDir'; `$env:APP_ENV='development'; Write-Host 'Backend running on http://localhost:8000 (Keep open)' -ForegroundColor Green; & '$VUvi' main:app --host 0.0.0.0 --port 8000 --reload"
        )
        Start-Sleep -Seconds 2
        $env:VITE_API_URL = 'http://localhost:8000'
        Push-Location $Root
        try { npm run dev -- --port 8080 --open } finally { Pop-Location }
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

    'sort' {
        if (-not $IN -or -not $OUT) {
            throw 'Usage: .\make.cmd sort -IN <photos_dir> -OUT <sorted_dir>'
        }
        $env:APP_ENV = 'development'
        $env:OMP_NUM_THREADS = '1'
        $inPath = [System.IO.Path]::GetFullPath($IN)
        $outPath = [System.IO.Path]::GetFullPath($OUT)
        Push-Location (Join-Path $Root 'backend')
        try {
            & $VPy cli.py sort --input $inPath --output $outPath $SORT_ARGS
        } finally {
            Pop-Location
        }
    }

    'resume' {
        if (-not $IN -or -not $OUT) {
            throw 'Usage: .\make.cmd resume -IN <photos_dir> -OUT <sorted_dir>'
        }
        $env:APP_ENV = 'development'
        $env:OMP_NUM_THREADS = '1'
        $inPath = [System.IO.Path]::GetFullPath($IN)
        $outPath = [System.IO.Path]::GetFullPath($OUT)
        Push-Location (Join-Path $Root 'backend')
        try {
            & $VPy cli.py sort --input $inPath --output $outPath --resume $SORT_ARGS
        } finally {
            Pop-Location
        }
    }

    'watch' {
        if (-not $IN -or -not $OUT) {
            throw 'Usage: .\make.cmd watch -IN <dropbox_dir> -OUT <sorted_dir>'
        }
        $env:APP_ENV = 'development'
        $env:OMP_NUM_THREADS = '1'
        $inPath = [System.IO.Path]::GetFullPath($IN)
        $outPath = [System.IO.Path]::GetFullPath($OUT)
        Push-Location (Join-Path $Root 'backend')
        try {
            & $VPy cli.py watch --input $inPath --output $outPath $SORT_ARGS
        } finally {
            Pop-Location
        }
    }

    'apply' {
        if (-not $OUT) {
            throw 'Usage: .\make.cmd apply -OUT <sorted_dir>'
        }
        $env:APP_ENV = 'development'
        $outPath = [System.IO.Path]::GetFullPath($OUT)
        $csvPath = if ($CSV) { [System.IO.Path]::GetFullPath($CSV) } else { Join-Path $outPath 'review.csv' }
        Push-Location (Join-Path $Root 'backend')
        try {
            & $VPy cli.py apply --csv $csvPath --output $outPath
        } finally {
            Pop-Location
        }
    }

    'test' {
        $env:APP_ENV = 'development'
        Push-Location $Root
        try { & $VPy test_pipeline.py } finally { Pop-Location }
    }

    'test-real' {
        $env:APP_ENV = 'development'
        Push-Location (Join-Path $Root 'backend')
        try { & $VPy test_real_images.py } finally { Pop-Location }
    }

    'bench-varahi' {
        $env:APP_ENV = 'development'
        Push-Location (Join-Path $Root 'backend')
        try { & $VPy test_varahi_benchmark.py } finally { Pop-Location }
    }

    'test-all' {
        $env:APP_ENV = 'development'
        Push-Location (Join-Path $Root 'backend')
        try { & $VPy test_all_datasets.py } finally { Pop-Location }
    }

    'bench' {
        $env:APP_ENV = 'development'
        Push-Location (Join-Path $Root 'backend')
        try { & $VPy bench.py } finally { Pop-Location }
    }

    'dist' {
        $out = Join-Path $Root 'dist'
        New-Item -ItemType Directory -Force -Path $out | Out-Null
        $zip = Join-Path $out 'vr-image-sorter.zip'
        Remove-Item $zip -ErrorAction SilentlyContinue
        Push-Location $Root
        try {
            if (Have 'git') {
                git archive --format=zip -o $zip HEAD
                Write-Host "wrote $zip"
            } else {
                Compress-Archive -Path (Get-ChildItem -Path $Root -Exclude @('.git', 'node_modules', 'dist', '.venv')) -DestinationPath $zip
                Write-Host "wrote $zip"
            }
        } finally {
            Pop-Location
        }
    }

    'clean' {
        foreach ($p in @($Venv, (Join-Path $Root 'node_modules'), (Join-Path $Root 'dist'), (Join-Path $Root 'backend\__pycache__'), (Join-Path $Root '__pycache__'))) {
            if (Test-Path $p) {
                Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
            }
        }
    }

    default {
        throw "Unknown target '$Target'. Run '.\make.cmd help'."
    }
}
