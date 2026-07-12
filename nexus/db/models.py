"""
SQLAlchemy Async Database Models and Configuration for Nexus Scraper.
Uses SQLite via aiosqlite under the hood.
"""

import json
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional
from sqlalchemy import String, Integer, DateTime, Text, Float
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, Mapped, mapped_column

from nexus.config import settings

Base = declarative_base()


class ScrapeJob(Base):
    """
    Represents an asynchronous bulk scraping job.
    """
    __tablename__ = "scrape_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING, RUNNING, COMPLETED, FAILED
    urls: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of URLs
    results: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of results
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        """Convert job to a dictionary."""
        return {
            "id": self.id,
            "status": self.status,
            "urls": json.loads(self.urls) if self.urls else [],
            "results": json.loads(self.results) if self.results else [],
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ScrapeTask(Base):
    """
    Represents a prioritized, queueable scraping task with automatic retries,
    exponential backoff, persistence, and disaster recovery.
    """
    __tablename__ = "scrape_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1)  # 1 = Low, 5 = High
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING, RUNNING, COMPLETED, FAILED, RETRYING
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON config overrides (headers, dynamic, etc.)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Result JSON payload
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "priority": self.priority,
            "status": self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "payload": json.loads(self.payload) if self.payload else {},
            "result": json.loads(self.result) if self.result else None,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ControlConfig(Base):
    """
    Dynamic control plane configuration overrides managed remotely by LLM Agents.
    """
    __tablename__ = "control_configs"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)  # e.g., 'proxy_rules', 'headers_override', 'bypass_rules'
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON object/string
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchEvent(Base):
    """
    Represents a registered watch/event monitoring target.
    """
    __tablename__ = "watch_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    selector: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=60)  # in minutes
    last_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_checked: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "selector": self.selector,
            "frequency": self.frequency,
            "last_value": self.last_value,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ExecutionStat(Base):
    """
    Stores metrics/statistics for scrapes.
    """
    __tablename__ = "execution_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(50))  # scrape, bulk, watch, fusion, compliance
    status_code: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float)  # seconds
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# Async Database Engine and Sessionmaker
async_engine = create_async_engine(settings.db_path, echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db() -> None:
    """Initialize database tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection for database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
