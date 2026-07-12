"""
API routes for compliance checking and redaction.
Detects and redacts PII (Personally Identifiable Information) such as emails, phone numbers,
and credit card numbers from scraped contents.
"""

import re
import time
from typing import Dict, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import get_db, ExecutionStat

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

# Regex patterns for PII detection
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


class CheckRequest(BaseModel):
    content: str


class CheckResponse(BaseModel):
    is_compliant: bool
    detected_pii: Dict[str, List[str]]
    duration: float


class RedactRequest(BaseModel):
    content: str


class RedactResponse(BaseModel):
    redacted_content: str
    redactions_count: int
    duration: float


def detect_pii(text: str) -> Dict[str, List[str]]:
    """Scan text for PII occurrences."""
    emails = EMAIL_REGEX.findall(text)
    phones = PHONE_REGEX.findall(text)
    cards = CARD_REGEX.findall(text)
    
    detected = {}
    if emails:
        detected["email"] = list(set(emails))
    if phones:
        detected["phone"] = list(set(phones))
    if cards:
        detected["credit_card"] = list(set(cards))
        
    return detected


@router.post("/check", response_model=CheckResponse)
async def check_compliance(
    payload: CheckRequest,
    db: AsyncSession = Depends(get_db)
) -> CheckResponse:
    """
    Check if the scraped content is compliant (free of PII).
    """
    start_time = time.time()
    
    detected = detect_pii(payload.content)
    is_compliant = len(detected) == 0
    
    duration = time.time() - start_time
    
    stat = ExecutionStat(
        endpoint="compliance_check",
        status_code=200,
        duration=duration
    )
    db.add(stat)
    await db.commit()
    
    return CheckResponse(
        is_compliant=is_compliant,
        detected_pii=detected,
        duration=duration
    )


@router.post("/redact", response_model=RedactResponse)
async def redact_content(
    payload: RedactRequest,
    db: AsyncSession = Depends(get_db)
) -> RedactResponse:
    """
    Redact PII from the scraped content.
    Replaces emails, phone numbers, and credit cards with safe placeholders.
    """
    start_time = time.time()
    
    text = payload.content
    redactions_count = 0
    
    # Redact Emails
    emails = EMAIL_REGEX.findall(text)
    if emails:
        text, count = EMAIL_REGEX.subn("[REDACTED_EMAIL]", text)
        redactions_count += count
        
    # Redact Phones
    phones = PHONE_REGEX.findall(text)
    if phones:
        text, count = PHONE_REGEX.subn("[REDACTED_PHONE]", text)
        redactions_count += count
        
    # Redact Cards
    cards = CARD_REGEX.findall(text)
    if cards:
        text, count = CARD_REGEX.subn("[REDACTED_CARD]", text)
        redactions_count += count
        
    duration = time.time() - start_time
    
    stat = ExecutionStat(
        endpoint="compliance_redact",
        status_code=200,
        duration=duration
    )
    db.add(stat)
    await db.commit()
    
    return RedactResponse(
        redacted_content=text,
        redactions_count=redactions_count,
        duration=duration
    )


@router.get("/check")
async def get_check_info():
    """Provides information about compliance checking endpoints."""
    return {
        "endpoint": "/api/v1/compliance/check",
        "description": "Send content via POST to scan for PII violations.",
        "scanned_categories": ["email", "phone_number", "credit_card"]
    }


@router.get("/redact")
async def get_redact_info():
    """Provides information about compliance redaction endpoints."""
    return {
        "endpoint": "/api/v1/compliance/redact",
        "description": "Send content via POST to replace PII with anonymized tags."
    }
