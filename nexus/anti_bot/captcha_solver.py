'''
Captcha Detection and solving wrapper.
'''
import structlog
from typing import Optional

logger = structlog.get_logger()

class CaptchaSolver:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    async def solve(self, url: str, site_key: str, captcha_type: str) -> Optional[str]:
        logger.info('Solving captcha', url=url, type=captcha_type)
        return 'mock_captcha_token_success'