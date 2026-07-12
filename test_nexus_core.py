import asyncio
import os
import sys

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nexus.config import settings
from nexus.utils.logger import get_logger
from nexus.utils.retry import retry
from nexus.storage.database import init_db, get_db, engine
from nexus.storage.cache import cache
from nexus.storage.models import Watcher, HarvestedPage
from sqlalchemy import select, text

logger = get_logger("integration_test")


@retry(max_retries=2, initial_delay=0.1)
async def sample_retry_func(fail_count: list):
    """A helper function that fails a few times and then succeeds."""
    if len(fail_count) < 2:
        fail_count.append(1)
        raise ValueError("Simulated temporary failure")
    return "success"


async def main():
    print("\n=== STARTING NEXUS CORE API & STORAGE INTEGRATION TESTS ===\n")

    # 1. Verify Settings
    print("[1] Verifying Settings configuration loading...")
    print(f"    Environment: {settings.env}")
    print(f"    DB Path: {settings.db_path}")
    print(f"    Redis URL: {settings.redis_url}")
    assert settings.env == "production" or settings.env == "development"
    print("    -> PASS: Settings loaded successfully.\n")

    # 2. Verify Logger
    print("[2] Verifying Structured Logger (structlog)...")
    logger.info("Test log from structured logger", env=settings.env, status="ok")
    print("    -> PASS: Logger successfully executed.\n")

    # 3. Verify Async Retry Decorator
    print("[3] Verifying Async Retry decorator with backoff...")
    fail_tracker = []
    retry_result = await sample_retry_func(fail_tracker)
    print(f"    Retry result: {retry_result} (Failed {len(fail_tracker)} times first)")
    assert retry_result == "success"
    assert len(fail_tracker) == 2
    print("    -> PASS: Retry decorator successfully backed off and succeeded.\n")

    # 4. Verify Database WAL Mode and Table Creation
    print("[4] Verifying SQLite Database & WAL initialization...")
    # Clean previous db file if any to ensure fresh run for the test
    db_file = "nexus.db"
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
            print("    Cleaned up pre-existing nexus.db")
        except Exception as e:
            print(f"    Warning: Could not remove old db file: {e}")

    await init_db()

    # Verify tables actually exist
    async with engine.connect() as conn:
        # Check journal mode
        result = await conn.execute(text("PRAGMA journal_mode;"))
        mode = result.scalar()
        print(f"    SQLite Active Journal Mode: {mode}")
        assert mode.lower() == "wal"

        # Check table list
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
        tables = [row[0] for row in result.fetchall()]
        print(f"    Created tables: {tables}")
        required_tables = {"watchers", "harvested_pages", "dom_snapshots", "events", "audit_logs"}
        assert required_tables.issubset(set(tables))

    print("    -> PASS: SQLite async DB initialized in WAL mode and all tables verified.\n")

    # 5. Verify Cache & In-Memory Fallback
    print("[5] Verifying Cache with Seamless Fallback...")
    # We will test set/get/delete
    print("    Setting key 'test_key' to 'nexus_rocks' with 5s TTL...")
    await cache.set("test_key", "nexus_rocks", expire_seconds=5)

    cached_val = await cache.get("test_key")
    print(f"    Retrieved value: {cached_val}")
    assert cached_val == "nexus_rocks"

    # Test TTL expiration in fallback
    if cache.use_fallback:
        print("    [Fallback Active] Simulating TTL expiration...")
        # Manually alter the store's expire time to be in the past to test
        val, _ = cache._in_memory_store["test_key"]
        cache._in_memory_store["test_key"] = (val, 0.0)  # expired
        expired_val = await cache.get("test_key")
        print(f"    Retrieved expired key (should be None): {expired_val}")
        assert expired_val is None

    # Clean up key
    print("    Deleting key 'test_key'...")
    await cache.delete("test_key")
    after_del = await cache.get("test_key")
    assert after_del is None
    print(f"    Backend used fallback memory: {cache.use_fallback}")
    print("    -> PASS: Cache successfully executed in transparent mode.\n")

    print("=== ALL INTEGRATION TESTS PASSED TRIUMPHANTLY! ===")


if __name__ == "__main__":
    asyncio.run(main())
