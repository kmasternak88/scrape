import aiosqlite
import json
import logging
import re
import time
from typing import Dict, List, Optional, Any, Union, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("nexus.innovations.compliance")


class ComplianceEngine:
    """
    ComplianceEngine handles ethical scraping rules, robots.txt parsing,
    Terms of Service (ToS) restriction auditing, high-performance regex-based PII redaction,
    and maintains an asynchronous SQLite-based compliance audit log.
    """

    # High-performance PII detection regex patterns
    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
    
    # Matches international and local phone formats (including Polish spacing/dashes)
    PHONE_REGEX = re.compile(r'\+?\d{1,4}[- ]?\d{2,3}[- ]?\d{3}[- ]?\d{3,4}\b')
    
    # Matches typical Credit Card Numbers (Luhn-like 13-16 digits with optional spaces/hyphens)
    CREDIT_CARD_REGEX = re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b')
    
    # Matches IPv4 addresses
    IP_REGEX = re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b')

    TOS_PROHIBITED_KEYWORDS = [
        r'scraping is prohibited',
        r'crawling is forbidden',
        r'no automated access',
        r'no web scrapers',
        r'automated queries are prohibited',
        r'crawlers or spiders are not allowed',
        r'prohibit automated scraping',
        r'zakaz scrapowania',
        r'zakaz automatycznego pobierania'
    ]

    def __init__(self, db_path: str = "compliance_audit.db") -> None:
        self.db_path = db_path
        # Cache for parsed robots rules: { "domain": { "user_agent": [ ("Allow/Disallow", "/path") ] } }
        self.robots_rules: Dict[str, Dict[str, List[Tuple[str, str]]]] = {}

    async def initialize_db(self) -> None:
        """Asynchronously initializes the SQLite database and compliance log table."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS compliance_audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        event_type TEXT NOT NULL,
                        url TEXT NOT NULL,
                        status TEXT NOT NULL,
                        details TEXT
                    )
                """)
                await db.commit()
            logger.info(f"Compliance audit database initialized successfully at: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize compliance database: {e}", exc_info=True)

    async def log_audit_event(self, event_type: str, url: str, status: str, details: Optional[Union[str, Dict[str, Any]]] = None) -> None:
        """Asynchronously inserts a compliance audit event into the local SQLite database."""
        try:
            details_str = json.dumps(details) if isinstance(details, dict) else str(details or "")
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO compliance_audit (timestamp, event_type, url, status, details) VALUES (?, ?, ?, ?, ?)",
                    (time.time(), event_type, url, status, details_str)
                )
                await db.commit()
            logger.debug(f"Audit log added: {event_type} | URL: {url} | Status: {status}")
        except Exception as e:
            logger.error(f"Failed to write to compliance audit log: {e}")

    def parse_robots_txt(self, domain_or_url: str, robots_content: str) -> None:
        """
        Parses the robots.txt file content for a domain and caches the rules
        for allowed and disallowed paths per user-agent.
        """
        parsed_url = urlparse(domain_or_url)
        domain = parsed_url.netloc if parsed_url.netloc else domain_or_url
        domain = domain.lower()

        domain_rules: Dict[str, List[Tuple[str, str]]] = {}
        current_agents: List[str] = []
        last_line_was_directive = False

        for line in robots_content.splitlines():
            line = line.split('#')[0].strip()
            if not line:
                continue

            parts = line.split(':', 1)
            if len(parts) < 2:
                continue

            key = parts[0].strip().lower()
            val = parts[1].strip()

            if key == "user-agent":
                agent = val.lower()
                if last_line_was_directive:
                    current_agents = []
                current_agents.append(agent)
                if agent not in domain_rules:
                    domain_rules[agent] = []
                last_line_was_directive = False
            elif key in ["disallow", "allow"]:
                rule_type = "ALLOW" if key == "allow" else "DISALLOW"
                for agent in current_agents:
                    domain_rules[agent].append((rule_type, val))
                last_line_was_directive = True

        self.robots_rules[domain] = domain_rules
        logger.info(f"Parsed and cached robots.txt rules for domain: {domain}")

    def is_allowed_by_robots(self, url: str, user_agent: str = "NexusScraper") -> bool:
        """
        Checks if crawling is allowed for a given URL according to parsed robots.txt rules.
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower() if parsed_url.netloc else ""
        path = parsed_url.path if parsed_url.path else "/"
        if parsed_url.query:
            path = f"{path}?{parsed_url.query}"

        if domain not in self.robots_rules:
            # If no robots.txt loaded for domain, assume allowed by default
            return True

        domain_rules = self.robots_rules[domain]
        ua_lower = user_agent.lower()

        # Find matching rules
        # Look for specific user agent match first, otherwise fallback to '*'
        rules = []
        if ua_lower in domain_rules:
            rules = domain_rules[ua_lower]
        elif '*' in domain_rules:
            rules = domain_rules['*']
        else:
            return True

        # Evaluate rules in order of appearance (standard behavior) or specificity
        # Most specific matches or first match. Here we evaluate prefix matches.
        allowed = True
        longest_match_len = -1

        for rule_type, rule_path in rules:
            if not rule_path:
                if rule_type == "DISALLOW":
                    # Empty Disallow means "allow everything"
                    allowed = True
                    longest_match_len = 0
                continue

            # Convert robots wildcards to simple regex prefix matching
            # Escape rule_path except *
            escaped_rule = re.escape(rule_path).replace(r'\*', '.*')
            # Handle trailing matches
            pattern = f"^{escaped_rule}"
            
            if re.match(pattern, path):
                match_len = len(rule_path)
                if match_len > longest_match_len:
                    longest_match_len = match_len
                    allowed = (rule_type == "ALLOW")

        return allowed

    def check_tos_violation(self, text: str) -> List[str]:
        """
        Scans a web page's text for anti-scraping and legal restriction keyphrases.
        Returns a list of matching phrases detected on the page.
        """
        violations = []
        if not text:
            return violations

        for kw_pattern in self.TOS_PROHIBITED_KEYWORDS:
            match = re.search(kw_pattern, text, re.IGNORECASE)
            if match:
                violations.append(match.group(0))

        return violations

    def clean_pii(self, data: Any) -> Any:
        """
        Recursively scans and sanitizes PII (Emails, Phones, IPs, Credit Cards)
        from crawled data objects (dicts, lists, strings).
        Replaces detected PII with generic redacted markers.
        """
        if isinstance(data, str):
            # Apply regex replacements in order of priority
            cleaned = data
            cleaned = self.EMAIL_REGEX.sub("[REDACTED_EMAIL]", cleaned)
            cleaned = self.CREDIT_CARD_REGEX.sub("[REDACTED_CARD]", cleaned)
            cleaned = self.PHONE_REGEX.sub("[REDACTED_PHONE]", cleaned)
            cleaned = self.IP_REGEX.sub("[REDACTED_IP]", cleaned)
            return cleaned
        elif isinstance(data, dict):
            return {k: self.clean_pii(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.clean_pii(item) for item in data]
        elif isinstance(data, (int, float, bool)) or data is None:
            return data
        else:
            return self.clean_pii(str(data))
