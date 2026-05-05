import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from core.logger import logger
from api.routes import router as api_router


# ---------------------------------------------------------------------------
# Lifespan: startup → serve → shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup checks, start background tasks, then serve.
    On exit, run the graceful shutdown sequence."""

    # --- Startup ---
    from core.startup import run_startup_checks
    from core.monitoring import start_monitoring_task

    try:
        run_startup_checks()
    except RuntimeError as exc:
        # Log and re-raise so uvicorn exits with a non-zero code
        logger.critical("Startup failed — aborting: %s", exc)
        raise

    start_monitoring_task()
    logger.info("Application startup complete — ready to serve traffic")

    yield  # ← application is live here

    # --- Shutdown ---
    from core.shutdown import run_shutdown_sequence
    run_shutdown_sequence()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="VR Saree Sorter Backend API",
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unexpected error processing request: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An error occurred processing your request"},
    )


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

allowed_origins_env = (
    os.getenv("ALLOWED_ORIGINS")
    or os.getenv("ALLOWED_DOMAINS")
    or "https://vaarahi-barcode-scanner.up.railway.app,http://localhost:8080,http://localhost:5173,https://lovable.dev"
)
allowed_origins = [origin.strip().rstrip("/") for origin in allowed_origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(api_router)

