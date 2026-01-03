@echo off
echo ==========================================
echo Building Final Monolithic Application
echo ==========================================
echo This builds both Frontend (React) and Backend (FastAPI).
echo.

docker build -t vr-image-sorter-app .

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Docker build failed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ==========================================
echo Running Application
echo ==========================================
echo Open http://localhost:8000
echo.

docker run -p 8000:8000 vr-image-sorter-app

pause
