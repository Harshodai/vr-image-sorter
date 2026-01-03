@echo off
echo ==========================================
echo Building Saree Sorter Docker Image (GPU)
echo ==========================================
docker build -t saree-sorter --build-arg USE_GPU=true .

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Docker build failed. Please check the logs above.
    echo Ensure you have Docker installed and running.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ==========================================
echo Running Saree Sorter Container with GPU
echo ==========================================
echo Note: This requires NVIDIA Container Toolkit to be installed.
echo If this fails with "could not select device driver", verify your NVIDIA Docker setup.
echo.
echo API will be available at: http://localhost:8000/docs
echo.

docker run --gpus all -p 8000:8000 saree-sorter

pause
