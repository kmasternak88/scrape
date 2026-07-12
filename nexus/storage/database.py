from typing import AsyncGenerator
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from nexus.config import settings
from nexus.storage.models import Base
from nexus.utils.logger import get_logger

logger = get_logger("database")

# Create async engine for SQLite (aiosqlite)
# We enable echo only if settings.env is 'development' or 'local'
is_dev = settings.env.lower() in ("development", "local")
engine = create_async_engine(
    settings.db_path,
    echo=is_dev,
    future=True,
)

# Async session factory
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enables WAL mode, foreign key support, and performance optimizations for SQLite."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        logger.debug("Successfully configured SQLite PRAGMAs: WAL=ON, foreign_keys=ON, synchronous=NORMAL")
    except Exception as exc:
        logger.error("Failed to set SQLite connection pragmas", error=str(exc))
    finally:
        cursor.close()


async def init_db() -> None:
    """Initializes the database by creating all schema tables.

    Executes in WAL mode asynchronously.
    """
    logger.info("Initializing SQLite database and creating tables if missing...", db_path=settings.db_path)
    try:
        async with engine.begin() as conn:
            # Re-verify journal mode via active connection for logging/verification
            result = await conn.execute(text("PRAGMA journal_mode;"))
            journal_mode = result.scalar()
            logger.info("Current SQLite journal mode", mode=journal_mode)

            # Create tables
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Database schema tables created successfully.")
    except Exception as exc:
        logger.critical("Database initialization failed", error=str(exc))
        raise exc


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency generator that provides an asynchronous database session.

    Yields:
        AsyncSession: The active database session.
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            logger.error("Database session encountered an error, rolled back", error=str(exc))
            raise exc
        finally:
            await session.close()
