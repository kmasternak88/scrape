import asyncio
import os
import pytest
import sqlite3
from typing import Dict, List, Any

from nexus.innovations.dom_predictor import DOMPredictor, generate_selector
from nexus.innovations.event_trigger import EventTriggerEngine
from nexus.innovations.data_fusion import DataFusionEngine
from nexus.innovations.biometrics import BiometricsSimulator
from nexus.innovations.compliance import ComplianceEngine


# ==============================================================================
# 1. TEST: Self-Healing DOM (DOMPredictor)
# ==============================================================================

def test_dom_predictor():
    golden_html = """
    <html>
        <body>
            <div class="header">Header Content</div>
            <div class="content">
                <p>Welcome to our site</p>
                <a href="/buy" class="btn btn-primary buy-now-link" id="buy-btn-123">Click here to Buy Now!</a>
            </div>
            <div class="footer">Footer Info</div>
        </body>
    </html>
    """

    changed_html = """
    <html>
        <body>
            <div class="header">Header Content</div>
            <div class="main-wrapper">
                <p>Some welcome message</p>
                <!-- Class is randomized, ID is different, but text and tag are similar -->
                <a href="/buy" class="btn btn-rand-abc987 buy-now-link" id="buy-btn-999">Click here to Buy Now!</a>
            </div>
            <div class="footer">Footer Info</div>
        </body>
    </html>
    """

    predictor = DOMPredictor()
    
    # 1. Learn the target element on the golden page
    selector = "a.buy-now-link"
    success = predictor.learn_element(golden_html, selector)
    assert success is True
    assert selector in predictor.targets
    assert predictor.targets[selector]['tag'] == 'a'
    assert 'buy-btn-123' in predictor.targets[selector]['id']

    # 2. Predict selector on the changed HTML
    # The original selector 'a.buy-now-link' still works here because of 'buy-now-link'
    # Let's verify quick path
    healed_sel, conf = predictor.predict_selector(changed_html, selector)
    assert healed_sel == selector
    assert conf == 1.0

    # Let's break the original selector completely in changed HTML
    heavily_changed_html = """
    <html>
        <body>
            <div class="header">Header Content</div>
            <div class="main-wrapper">
                <p>Some welcome message</p>
                <!-- Original class and ID completely gone, tag and text are key -->
                <a href="/buy" class="completely-different-randomized-style" id="different-id">Click here to Buy Now!</a>
            </div>
            <div class="footer">Footer Info</div>
        </body>
    </html>
    """
    
    healed_sel, conf = predictor.predict_selector(heavily_changed_html, "a.buy-now-link")
    # It should heal the selector to point to the new 'a' element
    assert healed_sel != ""
    assert "a" in healed_sel
    assert conf > 0.5


# ==============================================================================
# 2. TEST: Event Trigger Pipeline (EventTriggerEngine)
# ==============================================================================

@pytest.mark.asyncio
async def test_event_trigger_engine():
    engine = EventTriggerEngine()
    
    # Define a custom local server check or dummy hash calculation
    html = "<html><body><div id='price'>$499.00</div></body></html>"
    
    # Test hash calculation
    hash1 = engine._calculate_hash(html, selector="#price")
    hash2 = engine._calculate_hash(html, selector="#price")
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 length

    html_changed = "<html><body><div id='price'>$510.00</div></body></html>"
    hash_changed = engine._calculate_hash(html_changed, selector="#price")
    assert hash1 != hash_changed

    # Test adding/removing watchers
    watcher_id = "test_watcher"
    url = "https://example.com/products"
    engine.add_watcher(watcher_id, url, interval=10.0, selector="#price")
    
    status = engine.get_watcher_status(watcher_id)
    assert status is not None
    assert status["url"] == url
    assert status["interval"] == 10.0
    assert status["selector"] == "#price"
    
    engine.remove_watcher(watcher_id)
    assert engine.get_watcher_status(watcher_id) is None
    
    await engine.stop()


# ==============================================================================
# 3. TEST: Cross-Domain Data Fusion (DataFusionEngine)
# ==============================================================================

def test_data_fusion_engine():
    r1 = {
        "domain": "allegro.pl",
        "title": "Smartfon Apple iPhone 15 Pro 128GB Czarny",
        "price": 4999.00,
        "sku": "iph15p-128-blk",
        "brand": "Apple",
        "attributes": {"color": "czarny", "memory": "128GB"}
    }
    
    r2 = {
        "domain": "amazon.pl",
        "title": "Apple iPhone 15 Pro (128 GB) - Black",
        "price": 5050.00,
        "sku": "iph15p-128-blk",  # SKU matches exactly!
        "brand": "Apple Inc.",
        "attributes": {"color": "black", "storage": "128 GB"}
    }
    
    r3 = {
        "domain": "olx.pl",
        "title": "iPhone 15 Pro 128GB Black",
        "price": 4999.00,
        "sku": None,
        "brand": None,
        "attributes": {"color": "Czarny"}
    }

    engine = DataFusionEngine(
        domain_weights={"allegro.pl": 0.9, "amazon.pl": 0.8, "olx.pl": 0.5},
        resolution_threshold=0.8
    )

    # 1. Verify similarity
    # r1 & r2 match exactly on SKU
    assert engine.calculate_similarity(r1, r2) == 1.0
    
    # r1 & r3 have fuzzy title similarity
    sim_1_3 = engine.calculate_similarity(r1, r3)
    assert sim_1_3 > 0.6

    # 2. Cluster records
    records = [r1, r2, r3]
    clusters = engine.cluster_records(records)
    # They should all resolve to a single product cluster!
    assert len(clusters) == 1
    assert len(clusters[0]) == 3

    # 3. Fuse cluster
    fused = engine.fuse_cluster(clusters[0])
    assert fused["brand"] == "Apple"  # Consensus / weight preferred
    assert fused["price"] == 4999.00  # Consensus of 4999.00 between r1 and r3
    assert fused["sku"] == "iph15p-128-blk"
    assert "allegro.pl" in fused["sources"]
    assert "amazon.pl" in fused["sources"]
    assert "olx.pl" in fused["sources"]
    
    # Check confidence metadata
    assert "_confidence" in fused
    assert fused["_confidence"]["price"] > 0.5
    assert fused["_confidence"]["brand"] > 0.5
    assert fused["confidence_score"] > 0.6


# ==============================================================================
# 4. TEST: Behavioral Biometrics (BiometricsSimulator)
# ==============================================================================

def test_biometrics_simulator():
    simulator = BiometricsSimulator(random_seed=42)
    
    start = (100, 100)
    end = (500, 400)
    steps = 40
    
    path = simulator.generate_mouse_path(start, end, duration_range=(0.5, 1.0), steps=steps)
    
    # Validate mouse path properties
    assert len(path) == steps
    # First point should be near start, last near end
    assert abs(path[0][0] - start[0]) < 2.0
    assert abs(path[0][1] - start[1]) < 2.0
    assert abs(path[-1][0] - end[0]) < 2.0
    assert abs(path[-1][1] - end[1]) < 2.0
    
    # Check that timestamps are monotonically increasing
    for idx in range(1, len(path)):
        assert path[idx][2] >= path[idx-1][2]

    # Validate click delays
    pre, hold, post = simulator.generate_click_delays()
    assert 0.05 <= pre <= 0.5
    assert 0.04 <= hold <= 0.35
    assert 0.1 <= post <= 0.6

    # Validate scroll steps
    scrolls = simulator.generate_scroll_steps(500, step_size=120)
    assert len(scrolls) > 0
    total_scroll_dist = sum(amt for amt, _ in scrolls)
    assert total_scroll_dist == 500


# ==============================================================================
# 5. TEST: Compliance Engine (ComplianceEngine)
# ==============================================================================

@pytest.mark.asyncio
async def test_compliance_engine():
    db_file = "test_compliance_audit.db"
    if os.path.exists(db_file):
        os.remove(db_file)

    engine = ComplianceEngine(db_path=db_file)
    
    # 1. Test database initialization and async logging
    await engine.initialize_db()
    assert os.path.exists(db_file)

    await engine.log_audit_event(
        event_type="robots_check",
        url="https://example.com/private",
        status="BLOCKED",
        details="Blocked by robots.txt Disallow rule"
    )

    # Verify rows in sqlite
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT event_type, url, status, details FROM compliance_audit")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "robots_check"
    assert rows[0][1] == "https://example.com/private"
    assert rows[0][2] == "BLOCKED"
    assert "Disallow" in rows[0][3]

    # 2. Test robots.txt parsing & checking
    robots_txt = """
    User-agent: *
    Disallow: /admin/
    Disallow: /private
    Allow: /private/public-info
    
    User-agent: SpecificScraper
    Disallow: /
    """
    
    engine.parse_robots_txt("https://example.com", robots_txt)
    
    # Check general agent rules
    assert engine.is_allowed_by_robots("https://example.com/blog", "NexusScraper") is True
    assert engine.is_allowed_by_robots("https://example.com/admin/settings", "NexusScraper") is False
    assert engine.is_allowed_by_robots("https://example.com/private/secret", "NexusScraper") is False
    assert engine.is_allowed_by_robots("https://example.com/private/public-info/index.html", "NexusScraper") is True

    # Check specific agent rules
    assert engine.is_allowed_by_robots("https://example.com/blog", "SpecificScraper") is False

    # 3. Test ToS violation check
    tos_text = "Usage of this website is subject to our terms. Scraping is prohibited under all circumstances."
    violations = engine.check_tos_violation(tos_text)
    assert len(violations) > 0
    assert "Scraping is prohibited" in violations[0]

    # 4. Test PII redaction
    raw_data = {
        "user": "John Doe",
        "email": "john.doe@example.com",
        "phone": "+48 555-123-456",
        "payment": {
            "card": "4111-1111-1111-1111",
            "ip": "192.168.1.15"
        },
        "nested_list": ["Contact at info@site.com", "Call +1 234 567 8900"]
    }

    clean_data = engine.clean_pii(raw_data)
    assert clean_data["user"] == "John Doe"
    assert clean_data["email"] == "[REDACTED_EMAIL]"
    assert clean_data["phone"] == "[REDACTED_PHONE]"
    assert clean_data["payment"]["card"] == "[REDACTED_CARD]"
    assert clean_data["payment"]["ip"] == "[REDACTED_IP]"
    assert clean_data["nested_list"][0] == "Contact at [REDACTED_EMAIL]"
    assert clean_data["nested_list"][1] == "Call [REDACTED_PHONE]"

    # Cleanup test database
    if os.path.exists(db_file):
        os.remove(db_file)
