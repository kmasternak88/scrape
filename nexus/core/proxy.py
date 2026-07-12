'''
Proxy list management and rotator.
'''
import random
from typing import Optional, List

class ProxyRotator:
    def __init__(self, proxy_list: Optional[List[str]] = None):
        self.proxies = proxy_list or []

    def get_proxy(self, geo: Optional[str] = None, super_tier: bool = False) -> Optional[str]:
        if not self.proxies:
            return None
        filtered = self.proxies
        if geo:
            filtered = [p for p in filtered if f'country={geo.lower()}' in p.lower() or f'@{geo.lower()}' in p.lower()]
        if not filtered:
            filtered = self.proxies
        return random.choice(filtered)