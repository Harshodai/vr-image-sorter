@echo off
echo ==========================================
echo Starting Saree Sorter Full Stack
echo ==========================================
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:8080
echo.
echo Building and starting containers...
echo.

REM `docker compose` is the current form; fall back to the v1 binary.
docker compose version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    docker compose up --build
) else (
    docker-compose up --build
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to start. Is Docker Desktop running?
    pause
    exit /b %ERRORLEVEL%
)
