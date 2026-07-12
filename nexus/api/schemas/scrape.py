from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ScrapeRequest(BaseModel):
    """Pydantic schema for a single URL scraping request."""

    url: str = Field(
        ...,
        description="The target absolute HTTP/HTTPS URL to scrape",
        examples=["https://example.com/products"]
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=300000,
        description="Timeout for the scrape action in milliseconds (between 1s and 300s)"
    )
    wait_for_selector: Optional[str] = Field(
        default=None,
        description="CSS selector to wait for before extracting page DOM"
    )
    use_proxy: bool = Field(
        default=True,
        description="Whether to route the request through a proxy"
    )
    bypass_captcha: bool = Field(
        default=False,
        description="Whether to attempt automatic captcha solving if triggered"
    )
    js_scenario: Optional[str] = Field(
        default=None,
        description="Optional custom Javascript scenario code to execute in-page"
    )

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: str) -> str:
        """Validates that the provided URL is well-formed and has http/https scheme."""
        lower_url = v.lower()
        if not (lower_url.startswith("http://") or lower_url.startswith("https://")):
            raise ValueError("URL must start with 'http://' or 'https://'")
        return v

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "url": "https://example.com/products",
                "timeout_ms": 30000,
                "wait_for_selector": "div.product-grid",
                "use_proxy": True,
                "bypass_captcha": False,
                "js_scenario": "window.scrollTo(0, document.body.scrollHeight);"
            }
        }
    )


class ScrapeResponse(BaseModel):
    """Pydantic schema for a scraping request execution response."""

    url: str = Field(..., description="The final resolved URL of the scraped page")
    status_code: int = Field(..., description="The HTTP status code returned by the target host")
    html_content: str = Field(..., description="The raw HTML DOM content extracted from the page")
    html_content_hash: str = Field(..., description="SHA-256 hash of the extracted HTML content")
    extracted_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured dictionary data if an AI/Regex extractor was applied"
    )
    screenshot_url: Optional[str] = Field(
        default=None,
        description="Relative path or public URL to the captured screenshot of the page"
    )
    latency_ms: float = Field(..., description="Total scraping execution duration in milliseconds")
    captured_at: datetime = Field(..., description="Timestamp of when the scrape execution concluded")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "url": "https://example.com/products",
                "status_code": 200,
                "html_content": "<html><body>...</body></html>",
                "html_content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "extracted_data": {"title": "Products Page", "product_count": 42},
                "screenshot_url": "screenshots/20260712/example_products.png",
                "latency_ms": 1240.5,
                "captured_at": "2026-07-12T12:00:00Z"
            }
        }
    )
