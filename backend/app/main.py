"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.static import SPAStaticFiles

from app.version import VERSION, BUILD_REVISION
from app.config import get_settings
from app.models.database import init_db
from app.api import auth, scan, media, settings as settings_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    await init_db()
    from app.core.instance import bootstrap_instance
    await bootstrap_instance()
    yield
    # Shutdown (cleanup if needed)


app = FastAPI(
    title=settings.app_name,
    description="Media audio track scanner with Plex integration",
    version=VERSION,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def reject_cross_origin_writes(request: Request, call_next):
    # None mode has no bearer secret. Block cross-origin browser form writes,
    # including POST endpoints that do not require a JSON body.
    origin = request.headers.get("origin")
    if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
        allowed = {str(request.base_url).rstrip("/"), *settings.cors_origins_list}
        if origin not in allowed:
            return JSONResponse(status_code=403, content={"detail": "Cross-origin writes are not allowed."})
    response = await call_next(request)
    if request.url.path in {"/api/auth/config", "/api/auth/me"}:
        response.headers["Cache-Control"] = "no-store"
    return response


# API routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(scan.router, prefix="/api/scan", tags=["Scanning"])
app.include_router(media.router, prefix="/api/media", tags=["Media"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Settings"])


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return consistent 400 errors with actionable validation messages."""
    messages = []
    for error in exc.errors():
        location = " -> ".join(str(part) for part in error.get("loc", []))
        messages.append(f"{location}: {error.get('msg', 'Invalid input')}")

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Invalid request input.",
            "errors": messages,
        },
    )


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": VERSION, "revision": BUILD_REVISION}


@app.get("/api/info")
async def build_info(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"version": VERSION, "revision": BUILD_REVISION}


# Serve static frontend files in production
static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    app.mount("/", SPAStaticFiles(directory=str(static_path), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
