import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from core.logger import logger
from core.startup import lifespan
from api.routes import router as api_router

# ---------------------------------------------------------------------------
# Initialize FastAPI App with lifespan for startup/shutdown hooks
# ---------------------------------------------------------------------------
app = FastAPI(
    title="VR Saree Sorter Backend API",
    version="2.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Unified Exception Handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unexpected error processing request: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An error occurred processing your request"},
    )

# ---------------------------------------------------------------------------
# CORS Configuration
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
# Include the modular routes
# ---------------------------------------------------------------------------
app.include_router(api_router)
