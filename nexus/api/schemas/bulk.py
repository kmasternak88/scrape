from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nexus.api.schemas.scrape import ScrapeResponse


class BulkScrapeRequest(BaseModel):
    """Pydantic schema representing a batch request containing multiple URLs."""

    urls: List[str] = Field(
        ...,
        min_items=1,
        description="List of target absolute URLs to scrape in batch",
        examples=[["https://example.com/p1", "https://example.com/p2"]]
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=300000,
        description="Default timeout for each individual scrape action in milliseconds"
    )
    wait_for_selector: Optional[str] = Field(
        default=None,
        description="Default CSS selector to wait for before extracting page DOM"
    )
    use_proxy: bool = Field(
        default=True,
        description="Whether to route individual requests through a proxy by default"
    )
    bypass_captcha: bool = Field(
        default=False,
        description="Whether to attempt automatic captcha solving for individual pages"
    )
    concurrency_limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum concurrent browser scraping contexts to allocate for this job"
    )

    @field_validator("urls")
    @classmethod
    def validate_urls_schemes(cls, urls_list: List[str]) -> List[str]:
        """Validates that each provided URL is well-formed and has http/https scheme."""
        for idx, url in enumerate(urls_list):
            lower_url = url.lower()
            if not (lower_url.startswith("http://") or lower_url.startswith("https://")):
                raise ValueError(f"URL at index {idx} ('{url}') must start with 'http://' or 'https://'")
        return urls_list

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "urls": [
                    "https://example.com/p1",
                    "https://example.com/p2",
                    "https://example.com/p3"
                ],
                "timeout_ms": 30000,
                "wait_for_selector": ".product-title",
                "use_proxy": True,
                "bypass_captcha": False,
                "concurrency_limit": 5
            }
        }
    )


class BulkScrapeResponse(BaseModel):
    """Pydantic schema representing immediate acknowledgment and details of a batch scraping job."""

    job_id: str = Field(..., description="Unique generated UUID identifying the bulk job")
    total_urls: int = Field(..., description="Total count of URLs queued for scraping")
    status: str = Field(..., description="Initial status of the job (e.g., pending, queued)")
    created_at: datetime = Field(..., description="Timestamp of when the job was created")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "job_id": "bfd895e6-4279-4402-9988-ef127b140cc5",
                "total_urls": 3,
                "status": "pending",
                "created_at": "2026-07-12T12:00:00Z"
            }
        }
    )


class BulkJobStatus(BaseModel):
    """Pydantic schema representing the full current execution state of a batch scraping job."""

    job_id: str = Field(..., description="Unique generated UUID identifying the bulk job")
    status: str = Field(..., description="Current status (e.g., pending, running, completed, failed)")
    total_urls: int = Field(..., description="Total URLs registered in this batch")
    processed_urls: int = Field(..., description="Number of URLs that have finished processing (success + fail)")
    success_count: int = Field(..., description="Count of successfully scraped URLs")
    failed_count: int = Field(..., description="Count of URLs that failed to scrape")
    results: List[ScrapeResponse] = Field(
        default_factory=list,
        description="Individual scrape execution results completed so far"
    )
    created_at: datetime = Field(..., description="Timestamp of when the job was created")
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of when the job reached a terminal state (completed/failed)"
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "job_id": "bfd895e6-4279-4402-9988-ef127b140cc5",
                "status": "running",
                "total_urls": 3,
                "processed_urls": 2,
                "success_count": 2,
                "failed_count": 0,
                "results": [
                    {
                        "url": "https://example.com/p1",
                        "status_code": 200,
                        "html_content": "<html>...</html>",
                        "html_content_hash": "a4d33a...",
                        "latency_ms": 842.1,
                        "captured_at": "2026-07-12T12:00:05Z"
                    },
                    {
                        "url": "https://example.com/p2",
                        "status_code": 200,
                        "html_content": "<html>...</html>",
                        "html_content_hash": "b2c11a...",
                        "latency_ms": 910.4,
                        "captured_at": "2026-07-12T12:00:06Z"
                    }
                ],
                "created_at": "2026-07-12T12:00:00Z",
                "completed_at": None
            }
        }
    )
