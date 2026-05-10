from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

try:
    from .database.session import init_db, close_db
except ImportError:
    from database.session import init_db, close_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(Path('/workspace/open-omniscience/data/logs/backend.log'))),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path("/workspace/open-omniscience/data").mkdir(parents=True, exist_ok=True)
    Path("/workspace/open-omniscience/data/logs").mkdir(parents=True, exist_ok=True)
    Path("/workspace/open-omniscience/data/scraped_content").mkdir(parents=True, exist_ok=True)
    Path("/workspace/open-omniscience/data/exports").mkdir(parents=True, exist_ok=True)
    
    init_db()
    logger.info("Database initialized successfully")
    
    yield
    
    await close_db()
    logger.info("Database connection closed")


app = FastAPI(
    title="Open-Omniscience",
    description="Local article intelligence and source tracking system",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/")
async def root():
    return {
        "name": "Open-Omniscience",
        "description": "Local article intelligence and source tracking system",
        "version": "1.0.0",
        "docs": "/api/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
