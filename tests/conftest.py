"""
Pytest configuration and global fixtures for Nexus Scraper.
Overrides settings for in-memory SQLite testing, configures HTTP clients, and mocks external components.
"""

import asyncio
from typing import AsyncGenerator, Generator
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from unittest.mock import AsyncMock, patch

from nexus.config import settings

# 1. Override settings for the test environment
settings.env = "test"
settings.api_key = "test_nexus_master_key"
settings.db_path = "sqlite+aiosqlite:///:memory:"
settings.redis_url = None  # Force in-memory rate limiting during tests

from nexus.db.models import Base, get_db
from nexus.main import app


# 2. Setup the async event loop fixture
@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create and yield a session-level event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


# 3. Setup in-memory SQLite test database engine and sessionmaker
test_engine = create_async_engine(settings.db_path, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# 3.5 Re-bind app models engine to use the test engine/sessionmaker
import nexus.db.models
nexus.db.models.async_engine = test_engine
nexus.db.models.AsyncSessionLocal = TestSessionLocal



@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db() -> AsyncGenerator[None, None]:
    """Initialize in-memory database tables before each test and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a functional async database session for raw database tests."""
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# 4. Override get_db dependency in FastAPI app
async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

app.dependency_overrides[get_db] = override_get_db


# 5. Fast HTTP Client fixtures (authenticated and unauthenticated)
@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an unauthenticated Async HTTP Client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def auth_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an authenticated Async HTTP Client."""
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers
    ) as ac:
        yield ac


# 6. Mock external fetch components of ScraperEngine
@pytest.fixture(scope="function", autouse=True)
def mock_scraper_engine() -> Generator[None, None, None]:
    """
    Mock ScraperEngine's fetch methods to prevent real network requests.
    """
    with patch("nexus.core.engine.scraper_engine.fetch_static", new_callable=AsyncMock) as mock_static, \
         patch("nexus.core.engine.scraper_engine.fetch_dynamic", new_callable=AsyncMock) as mock_dynamic:
         
        # Set default mock return values (HTML content)
        mock_static.return_value = "<html><head><title>Mock Page</title></head><body><h1>Hello World</h1><p>Contact: info@example.com, Call 123-456-7890</p></body></html>"
        mock_dynamic.return_value = "<html><head><title>Mock Dynamic Page</title></head><body><h1>Hello Dynamic World</h1></body></html>"
        
        yield
