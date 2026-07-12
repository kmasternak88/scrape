from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, Index
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy 2.0 models."""

    pass


class Watcher(Base):
    """Watcher model defining scraping schedule/target."""

    __tablename__ = "watchers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    events: Mapped[List["Event"]] = relationship(
        "Event", back_populates="watcher", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_watchers_active", "active"),
    )

    def __repr__(self) -> str:
        return f"<Watcher id={self.id} url={self.target_url[:30]}... active={self.active}>"


class HarvestedPage(Base):
    """Stores metadata and content about harvested pages."""

    __tablename__ = "harvested_pages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    html_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    headers: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_html_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    snapshots: Mapped[List["DOMSnapshot"]] = relationship(
        "DOMSnapshot", back_populates="harvested_page", cascade="all, delete-orphan"
    )
    events: Mapped[List["Event"]] = relationship(
        "Event", back_populates="harvested_page", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_harvested_pages_url", "url"),
        Index("ix_harvested_pages_hash", "html_content_hash"),
    )

    def __repr__(self) -> str:
        return f"<HarvestedPage id={self.id} url={self.url[:30]}... status={self.status_code}>"


class DOMSnapshot(Base):
    """Stores structured representation of interactive DOM elements."""

    __tablename__ = "dom_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    harvested_page_id: Mapped[int] = mapped_column(ForeignKey("harvested_pages.id"), nullable=False)
    selector_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    interactive_elements_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    # Relationships
    harvested_page: Mapped["HarvestedPage"] = relationship("HarvestedPage", back_populates="snapshots")

    __table_args__ = (
        Index("ix_dom_snapshots_page_id", "harvested_page_id"),
        Index("ix_dom_snapshots_selector_hash", "selector_hash"),
    )

    def __repr__(self) -> str:
        return f"<DOMSnapshot id={self.id} page_id={self.harvested_page_id}>"


class Event(Base):
    """Tracks changes or anomalies identified during scraping runs."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    watcher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("watchers.id"), nullable=True)
    harvested_page_id: Mapped[Optional[int]] = mapped_column(ForeignKey("harvested_pages.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    # Relationships
    watcher: Mapped[Optional["Watcher"]] = relationship("Watcher", back_populates="events")
    harvested_page: Mapped[Optional["HarvestedPage"]] = relationship("HarvestedPage", back_populates="events")

    __table_args__ = (
        Index("ix_events_watcher_id", "watcher_id"),
        Index("ix_events_type", "event_type"),
    )

    def __repr__(self) -> str:
        return f"<Event id={self.id} type={self.event_type} watcher={self.watcher_id}>"


class AuditLog(Base):
    """General administrative audit log of actions inside Nexus Scraper."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_action: Mapped[str] = mapped_column(String(256), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    change_details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_audit_logs_action", "user_action"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.user_action} entity={self.entity_type}:{self.entity_id}>"
