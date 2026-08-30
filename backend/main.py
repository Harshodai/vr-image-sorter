import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from core.logger import logger
from api.routes import router as api_router
from scanner.engine_pool import ocr_pool

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm OCR engine on server boot to avoid user-facing cold start delay
    logger.info("Server starting up. Pre-warming RapidOCR engine...")
    ocr_pool.warm_up(count=1)
    logger.info("RapidOCR engine ready.")
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

# Include the modular routes
app.include_router(api_router)
