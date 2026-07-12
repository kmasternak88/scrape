'''
Advanced structural content extraction utilizing CSS, XPath, or heuristic approaches.
'''
import re
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional

class DataExtractor:
    def __init__(self, html: str = ""):
        self.html = html
        self.soup = BeautifulSoup(html, 'html.parser') if html else None

    def _get_soup(self, html: Optional[str] = None) -> BeautifulSoup:
        if html is not None:
            return BeautifulSoup(html, 'html.parser')
        if self.soup is not None:
            return self.soup
        return BeautifulSoup("", 'html.parser')

    def extract_by_selector(self, selector: str, html: Optional[str] = None) -> str:
        soup = self._get_soup(html)
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else ''

    def extract_by_css(self, selector: str, html: Optional[str] = None) -> List[str]:
        soup = self._get_soup(html)
        elements = soup.select(selector)
        return [el.get_text(strip=True) for el in elements if el.get_text(strip=True)]

    def extract_by_xpath(self, xpath: str, html: Optional[str] = None) -> List[str]:
        soup = self._get_soup(html)
        # Handle simple xpath extraction using BeautifulSoup
        # e.g., "//h2/text()" -> find all h2 elements and return their text
        # e.g., "//div[@class='product']" etc.
        tag_match = re.match(r'^//([a-zA-Z0-9]+)(?:/text\(\))?$', xpath)
        if tag_match:
            tag = tag_match.group(1)
            elements = soup.find_all(tag)
            return [el.get_text(strip=True) for el in elements if el.get_text(strip=True)]
        
        # Sibling xpath formats
        clean_xpath = xpath.replace('//', '').replace('/text()', '').strip()
        css_sel = clean_xpath.replace('/', ' > ')
        try:
            elements = soup.select(css_sel)
            return [el.get_text(strip=True) for el in elements if el.get_text(strip=True)]
        except Exception:
            return []

    def auto_extract(self, html: Optional[str] = None) -> Dict[str, Any]:
        soup = self._get_soup(html)
        title = soup.title.string if soup.title else ''
        return {
            'title': title,
            'paragraphs': [p.get_text(strip=True) for p in soup.find_all('p')[:5]]
        }

    def auto_extract_structured(self, html: Optional[str] = None) -> List[Dict[str, Any]]:
        soup = self._get_soup(html)
        results = []
        
        # Look for common product/item card containers
        cards = soup.find_all(class_=re.compile(r'(card|product|item|row|listing)', re.I))
        for card in cards:
            item_data = {}
            links = card.find_all('a')
            if links:
                item_data['link_text'] = links[0].get_text(strip=True)
                item_data['link_href'] = links[0].get('href', '')
            
            price_elem = card.find(class_=re.compile(r'(price|amt|amount)', re.I))
            if price_elem:
                item_data['price'] = price_elem.get_text(strip=True)
            else:
                text = card.get_text(separator=' ')
                price_match = re.search(r'(\$\s*\d+|\d+\s*USD|\d+\s*zł)', text)
                if price_match:
                    item_data['price'] = price_match.group(1)
            
            if item_data:
                results.append(item_data)
                
        if not results:
            for link in soup.find_all('a'):
                href = link.get('href', '')
                text = link.get_text(strip=True)
                if text and href:
                    results.append({'text': text, 'href': href})
                    
        return results
