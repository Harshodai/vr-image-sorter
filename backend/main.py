import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core.logger import logger
from api.routes import router as api_router
from scanner.engine_pool import ocr_pool

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm OCR engine on server boot to avoid user-facing cold start delay
    logger.info("Server starting up. Pre-warming RapidOCR engine pool...")
    from core.config import OCR_POOL_SIZE
    ocr_pool.warm_up(count=OCR_POOL_SIZE)
    logger.info("RapidOCR engine pool ready (%d engine(s)).", OCR_POOL_SIZE)
    yield
    logger.info("Server shutting down.")

# Initialize FastAPI App
app = FastAPI(title="VR Saree Sorter Backend API", version="2.0.0", lifespan=lifespan)

# Unified Exception Handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unexpected error processing request: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An error occurred processing your request"}
    )

# CORS Configuration - support all local dev ports & origins seamlessly
allowed_origins_env = os.getenv("ALLOWED_ORIGINS") or os.getenv("ALLOWED_DOMAINS") or "https://vaarahi-barcode-scanner.up.railway.app,http://localhost:8080,http://localhost:5173,https://lovable.dev"
allowed_origins = [origin.strip().rstrip("/") for origin in allowed_origins_env.split(",") if origin.strip()]

for local_origin in [
    "http://localhost:8080", "http://127.0.0.1:8080",
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8088", "http://127.0.0.1:8088",
    "http://localhost:8000", "http://127.0.0.1:8000",
    "http://localhost:3000", "http://127.0.0.1:3000",
]:
    if local_origin not in allowed_origins:
        allowed_origins.append(local_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include the modular API routes
app.include_router(api_router)

# Mount static frontend files if built static directory exists
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.isdir(STATIC_DIR):
    alt_dist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dist")
    if os.path.isdir(alt_dist):
        STATIC_DIR = alt_dist

if os.path.isdir(STATIC_DIR):
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa_frontend(full_path: str):
        # Do not intercept API, health, docs routes
        if full_path.startswith("api/") or full_path in ("health", "docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")

        target_file = os.path.join(STATIC_DIR, full_path)
        if full_path and os.path.isfile(target_file):
            return FileResponse(target_file)

        index_file = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend assets not found")

