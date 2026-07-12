"""
Integration and Unit Test Suite for LLM Control Plane and Persistent Priority Task Queue.
"""

import os
import json
import asyncio
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.config import settings
from nexus.db.models import Base, AsyncSessionLocal, ControlConfig, ScrapeTask, init_db, get_db
from nexus.core.engine import scraper_engine
from nexus.core.queue import queue_worker


@pytest.mark.asyncio
async def test_control_plane_override_lifecycle(auth_client: AsyncClient):
    """
    Verifies full lifecycle of LLM Control Plane overrides via API:
    - GET /api/v1/control (read active overrides)
    - POST /api/v1/control (write/overwrite settings)
    - DELETE /api/v1/control/{key} (delete/reset overrides)
    """
    # 1. Initially overrides should be empty
    resp = await auth_client.get("/api/v1/control")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_overrides" in data
    assert "browser_harness_status" in data
    assert len(data["active_overrides"]) == 0

    # 2. Add an override configuration
    payload = {
        "key": "headers_override",
        "value": {
            "User-Agent": "LLM_Stealth_Agent_Chrome_125",
            "X-Anti-Bot-Challenge": "passed_securely"
        }
    }
    post_resp = await auth_client.post("/api/v1/control", json=payload)
    assert post_resp.status_code == 201
    assert post_resp.json()["status"] == "success"

    # 3. Read overrides again to verify persistence
    get_resp = await auth_client.get("/api/v1/control")
    data_updated = get_resp.json()
    assert "headers_override" in data_updated["active_overrides"]
    assert data_updated["active_overrides"]["headers_override"]["User-Agent"] == "LLM_Stealth_Agent_Chrome_125"

    # 4. Delete the override config
    del_resp = await auth_client.delete("/api/v1/control/headers_override")
    assert del_resp.status_code == 200
    assert "Successfully deleted" in del_resp.json()["message"]

    # 5. Verify it's empty again
    final_resp = await auth_client.get("/api/v1/control")
    assert len(final_resp.json()["active_overrides"]) == 0


@pytest.mark.asyncio
async def test_scraper_engine_dynamic_overrides(auth_client: AsyncClient):
    """
    Verifies that Control Plane database overrides are dynamically loaded 
    and applied by ScraperEngine during execution.
    """
    # Setup database override using API
    headers_payload = {
        "key": "headers_override",
        "value": {
            "User-Agent": "Custom_Agent_Dynamic_Override_UA",
            "X-Test-Header": "applied"
        }
    }
    await auth_client.post("/api/v1/control", json=headers_payload)

    # We mock HTTPX request in engine.py to check if our headers are present
    from unittest.mock import AsyncMock, patch
    
    mock_response = AsyncMock()
    mock_response.text = "<html><head><title>Mocked Page</title></head></html>"
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None

    # Patch AsyncClient class and its async context manager enter sequence
    with patch("nexus.core.engine.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)
        
        # Prevent curl_cffi requests.get from running so we fall back to httpx
        with patch("asyncio.to_thread", side_effect=Exception("Forced fallback")):
            html = await scraper_engine.fetch_static("https://example.com/test-dynamic-headers")
            assert html is not None
            
            # Verify custom headers were dynamically read from database and injected
            assert mock_client.get.called is True
            called_headers = mock_client.get.call_args[1]["headers"]
            assert called_headers["User-Agent"] == "Custom_Agent_Dynamic_Override_UA"
            assert called_headers["X-Test-Header"] == "applied"

    # Clean up DB overrides to not pollute sibling tests
    await auth_client.delete("/api/v1/control/headers_override")


@pytest.mark.asyncio
async def test_priority_task_queue_execution(auth_client: AsyncClient):
    """
    Verifies persistent Priority Task Queue API flows:
    - Enqueue task via POST /api/v1/control/queue
    - Verify task priority and state
    - Wait and assert that background worker picks up and completes the task
    """
    # Setup a physical file-based test database so that both test thread and background thread
    # can access the exact same DB schema and tables (bypassing in-memory sqlite isolation)
    test_db_file = "test_queue_run.db"
    if os.path.exists(test_db_file):
        try:
            os.remove(test_db_file)
        except OSError:
            pass

    test_db_path = f"sqlite+aiosqlite:///{test_db_file}"
    
    # Temporarily bind db to use the physical file database for this test case
    import nexus.db.models
    import nexus.api.routes.control
    import nexus.core.queue
    
    original_engine = nexus.db.models.async_engine
    original_session = nexus.db.models.AsyncSessionLocal
    
    test_engine = create_async_engine(test_db_path, echo=False)
    test_sessionmaker = nexus.db.models.async_sessionmaker(
        bind=test_engine,
        class_=nexus.db.models.AsyncSession,
        expire_on_commit=False
    )
    
    nexus.db.models.async_engine = test_engine
    nexus.db.models.AsyncSessionLocal = test_sessionmaker
    nexus.api.routes.control.AsyncSessionLocal = test_sessionmaker
    nexus.core.queue.AsyncSessionLocal = test_sessionmaker
    
    # Initialize database tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 1. Enqueue task via API
    payload = {
        "url": "https://example.com/queued-url",
        "priority": 5,  # High priority
        "payload": {
            "dynamic": False,
            "timeout": 5000
        },
        "max_retries": 1
    }
    
    # We must patch get_db in dependency override to yield sessions connected to the physical db
    async def override_get_db():
        async with test_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
                
    from nexus.main import app
    app.dependency_overrides[nexus.db.models.get_db] = override_get_db

    try:
        resp = await auth_client.post("/api/v1/control/queue", json=payload)
        assert resp.status_code == 202
        task_data = resp.json()
        assert "task_id" in task_data
        assert task_data["status"] == "PENDING"
        assert task_data["priority"] == 5

        task_id = task_data["task_id"]

        # Start persistent Priority Task Queue worker loop
        queue_worker.start()
        
        completed = False
        for _ in range(30):
            status_resp = await auth_client.get(f"/api/v1/control/queue/{task_id}")
            assert status_resp.status_code == 200
            status_data = status_resp.json()
            if status_data["status"] == "COMPLETED":
                completed = True
                assert "Mock Page" in status_data["result"]["title"]
                break
            await asyncio.sleep(0.1)

        assert completed is True
    finally:
        # Graceful shutdown of worker queue
        await queue_worker.stop()
        
        # Restore original database settings
        nexus.db.models.async_engine = original_engine
        nexus.db.models.AsyncSessionLocal = original_session
        nexus.api.routes.control.AsyncSessionLocal = original_session
        nexus.core.queue.AsyncSessionLocal = original_session
        
        # Pop override to cleanly restore conftest's override_get_db generator
        app.dependency_overrides.pop(nexus.db.models.get_db, None)
        
        # Clean up database files
        await test_engine.dispose()
        if os.path.exists(test_db_file):
            for _ in range(5):
                try:
                    os.remove(test_db_file)
                    break
                except OSError:
                    await asyncio.sleep(0.1)
