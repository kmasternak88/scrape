'''
WAF Detection and Bypass strategy router.
'''
import structlog
from typing import Dict, Any, Optional

logger = structlog.get_logger()

class WAFBypasser:
    def detect_waf(self, headers: Dict[str, str], html: str) -> Optional[str]:
        html_lower = html.lower() if html else ''
        if 'cloudflare' in html_lower or 'cf-ray' in [k.lower() for k in headers.keys()]:
            return 'Cloudflare'
        if 'akamai' in html_lower or 'sc-ray' in [k.lower() for k in headers.keys()]:
            return 'Akamai'
        if 'datadome' in html_lower:
            return 'DataDome'
        return None

    def get_bypass_strategy(self, waf: str) -> Dict[str, Any]:
        logger.info('Selecting bypass strategy for WAF', waf=waf)
        if waf == 'Cloudflare':
            return {'use_browser': True, 'delay': 5.0, 'impersonate': 'chrome120'}
        elif waf == 'Akamai':
            return {'use_browser': True, 'delay': 8.0, 'impersonate': 'safari17'}
        elif waf == 'DataDome':
            return {'use_browser': True, 'delay': 10.0, 'impersonate': 'chrome120', 'use_residential': True}
        return {'use_browser': False, 'delay': 1.0, 'impersonate': 'chrome120'}