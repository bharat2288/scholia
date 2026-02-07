"""
Scholia Backend Server
======================
FastAPI application serving the Scholia knowledge system.

Endpoints:
- /sources - Source management (documents, web clips, threads, media)
- /reading - Content delivery for reader
- /highlights - Highlight management
- /gluons - Notes, references, tags
- /search - Full-text search

Port: 8200
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

from database import init_db, close_db

# Load environment variables
# Check local .env first, then shared location
local_env = Path(__file__).parent / ".env"
shared_env = Path(r"C:\Users\bhara\dev\.env")

if local_env.exists():
    load_dotenv(local_env, override=True)
elif shared_env.exists():
    load_dotenv(shared_env, override=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown events.
    - On startup: Initialize database connection
    - On shutdown: Close database connection
    """
    # Startup
    await init_db()
    # Restore any queued/processing jobs from previous server run
    processor.start_processing_worker()
    yield
    # Shutdown
    processor.stop_processing_worker()
    await close_db()


# Create FastAPI app
app = FastAPI(
    title="Scholia",
    description="Local-first research knowledge system",
    version="0.1.0",
    lifespan=lifespan
)

# Configure CORS for frontend
# In development, allow requests from the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5176",  # Vite dev server
        "http://127.0.0.1:5176",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/")
async def root():
    """Health check - confirms server is running."""
    return {
        "status": "ok",
        "service": "scholia",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    """Detailed health check with database status."""
    return {
        "status": "ok",
        "database": "connected",
        "version": "0.1.0"
    }


# Import routers
from routers import sources, reading, highlights, gluons, processor, runpod, metadata_lookup, council, chat, sessions, whatsapp

# Register routers
app.include_router(sources.router, prefix="/sources", tags=["sources"])
app.include_router(reading.router, prefix="/reading", tags=["reading"])
app.include_router(highlights.router, prefix="/highlights", tags=["highlights"])
app.include_router(gluons.router, prefix="/gluons", tags=["gluons"])
# Legacy alias for backward compatibility during migration
app.include_router(gluons.router, prefix="/rems", tags=["rems-legacy"])
app.include_router(processor.router, prefix="/processor", tags=["processor"])
app.include_router(runpod.router)  # RunPod integration (prefix defined in router)
app.include_router(metadata_lookup.router, prefix="/metadata", tags=["metadata"])
app.include_router(council.router, prefix="/council", tags=["council"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
app.include_router(whatsapp.router)  # WhatsApp webhook (prefix defined in router)


# Note: RunPod endpoints now handled by routers/runpod.py
