"""
Main FastAPI Application Entrypoint for Nexus Scraper.
Assembles middlewares, sub-routers, database initializations, dynamic control plane endpoints,
and persistent background queue worker lifecycle hooks.
"""

import uvicorn
from fastapi import FastAPI
import structlog

from nexus.config import settings
from nexus.db.models import init_db
from nexus.api.middleware.auth import AuthMiddleware
from nexus.api.middleware.rate_limit import RateLimitMiddleware
from nexus.api.routes import scrape, bulk, watch, fusion, compliance, health, stats, control
from nexus.core.queue import queue_worker
from nexus.core.browser import browser_manager

# Configure structured logging
structlog.configure()
logger = structlog.get_logger()

# Instantiate FastAPI application
app = FastAPI(
    title="Nexus Scraper API",
    version="1.0.0",
    description="Next-Generation Production Grade Distributed Web Scraping & AI Extraction Engine",
)

# 1. Add Middlewares (executed in reverse order of declaration)
# First we run Rate Limiting, then Authentication
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware, rate_limit=100, time_window=60)

# 2. Add sub-routers
app.include_router(scrape.router)
app.include_router(bulk.router)
app.include_router(watch.router)
app.include_router(fusion.router)
app.include_router(compliance.router)
app.include_router(health.router)
app.include_router(stats.router)
app.include_router(control.router)  # Dynamic Control Plane Router for LLM agents


@app.on_event("startup")
async def on_startup():
    """
    Startup tasks: Initialize SQLite databases, boot queue processing.
    """
    logger.info("Starting up Nexus Scraper API", env=settings.env)
    try:
        # Initialize SQLite tables
        await init_db()
        logger.info("SQLite Database tables initialized successfully")
        
        # Start persistent Priority Task Queue worker loop
        queue_worker.start()
        logger.info("Background queue processor started successfully")
    except Exception as e:
        logger.critical("Database initialization or queue startup failed", error=str(e))
        raise


@app.on_event("shutdown")
async def on_shutdown():
    """
    Shutdown tasks: Stop background workers and clean up browser pools.
    """
    logger.info("Shutting down Nexus Scraper API")
    try:
        # Stop background queue processing loops
        await queue_worker.stop()
        logger.info("Queue processor stopped gracefully")
        
        # Clean up open Chrome Browser-Harness CDP/headless sessions
        await browser_manager.close()
        logger.info("Pooled browser connections closed cleanly")
    except Exception as e:
        logger.error("Failed to perform clean shutdown sequence", error=str(e))


@app.get("/")
async def root():
    """Root metadata response."""
    return {
        "service": "Nexus Scraper API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "control_plane": "/api/v1/control"
    }


if __name__ == "__main__":
    uvicorn.run(
        "nexus.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env == "development"
    )
