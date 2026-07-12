import pytest
from fastapi.testclient import TestClient
import json

from nexus.config import settings
from nexus.core.output import OutputConverter
from nexus.core.extractor import DataExtractor
from nexus.core.engine import ScraperEngine
from nexus.main import app

client = TestClient(app)


def test_output_converter_markdown():
    html_content = "<h1>Hello World</h1><p>This is a <strong>test</strong>.</p>"
    converter = OutputConverter()
    markdown = converter.to_markdown(html_content)
    assert "Hello World" in markdown
    assert "**test**" in markdown


def test_output_converter_structured():
    data = [{"title": "Item 1", "price": "10 USD"}, {"title": "Item 2", "price": "20 USD"}]
    converter = OutputConverter()
    
    json_output = converter.to_json(data)
    assert "Item 1" in json_output
    
    csv_output = converter.to_csv(data)
    assert "title" in csv_output
    assert "Item 1" in csv_output
    
    ndjson_output = converter.to_ndjson(data)
    lines = ndjson_output.strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "Item 1"


def test_data_extractor_css():
    html_content = """
    <div class="product">
        <h2 class="title">Product A</h2>
        <span class="price">15.99</span>
    </div>
    """
    extractor = DataExtractor(html_content)
    titles = extractor.extract_by_css(".title")
    assert titles == ["Product A"]
    
    prices = extractor.extract_by_css(".price")
    assert prices == ["15.99"]


def test_data_extractor_xpath():
    html_content = """
    <div class="product">
        <h2 class="title">Product A</h2>
    </div>
    """
    extractor = DataExtractor(html_content)
    titles = extractor.extract_by_xpath("//h2/text()")
    assert "Product A" in titles


def test_data_extractor_auto_extract():
    html_content = """
    <html>
        <body>
            <div class="item-card">
                <a href="/item/1" class="item-link">Item 1</a>
                <span class="item-price">$10</span>
            </div>
            <div class="item-card">
                <a href="/item/2" class="item-link">Item 2</a>
                <span class="item-price">$20</span>
            </div>
        </body>
    </html>
    """
    extractor = DataExtractor(html_content)
    extracted = extractor.auto_extract_structured()
    assert len(extracted) >= 2
    assert any("Item 1" in str(v) for item in extracted for v in item.values())


@pytest.mark.asyncio
async def test_scraping_engine_http():
    engine = ScraperEngine()
    assert hasattr(engine, "scrape")


def test_fastapi_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in ("healthy", "degraded")


def test_fastapi_scrape_endpoint():
    payload = {
        "url": "https://example.com",
        "dynamic": False,
        "timeout": 5000
    }
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    response = client.post("/api/v1/scrape", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
