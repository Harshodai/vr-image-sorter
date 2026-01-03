@echo off
echo ==========================================
echo Building Saree Sorter Docker Image (CPU)
echo ==========================================
echo This will be a lightweight build (no heavy GPU drivers).
echo.
docker build -t saree-sorter-cpu .

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Docker build failed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ==========================================
echo Running Saree Sorter Container (CPU)
echo ==========================================
echo API will be available at: http://localhost:8000/docs
echo.

docker run -p 8000:8000 saree-sorter-cpu
