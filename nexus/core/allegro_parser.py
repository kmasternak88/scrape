"""
Allegro.pl Search Product Extractor and Parser.
Parses search results for "maskownica karnisza" from Allegro listing HTML.
Extracts title, price, shipping, link, and shop name for each product.
"""

import re
import json
from bs4 import BeautifulSoup
from typing import List, Dict, Any

def parse_allegro_products(html_content: str) -> List[Dict[str, Any]]:
    """
    Parses product elements from Allegro search listing HTML.
    Handles Allegro's standard listing selectors (supporting modern layout).
    """
    soup = BeautifulSoup(html_content, "html.parser")
    products = []

    # 1. Look for product cards/articles in the listing
    # Allegro uses 'article' tags or divs with specific class signatures (e.g. nested under listing containers)
    articles = soup.find_all("article")
    
    if not articles:
        # Fallback to general cards if articles are missing
        articles = soup.find_all("div", {"data-box-name": "items-v2"}) or soup.find_all("div", class_=re.compile(r'(item|product|card)', re.I))

    for idx, card in enumerate(articles):
        try:
            product_data = {}
            
            # Extract Title and Link
            title_elem = card.find("h2") or card.find(class_=re.compile(r'(title|name|header)', re.I))
            if title_elem:
                product_data["title"] = title_elem.get_text(strip=True)
                
                # Check for link inside or near the title
                link_elem = title_elem.find("a") or card.find("a")
                if link_elem:
                    href = link_elem.get("href", "")
                    # Clean URL if it's absolute or relative
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = "https://allegro.pl" + href
                    product_data["link"] = href
            else:
                continue

            # Extract Price
            # Allegro prices are often structured as integers and fraction parts
            price_container = card.find(class_=re.compile(r'(price|amount|val)', re.I))
            if price_container:
                # Get clean text
                price_text = price_container.get_text(separator=" ").strip()
                # Extract clean floating value: e.g. "129,00 zł" -> 129.0
                price_match = re.search(r'([\d\s]+[,.]\d+)', price_text)
                if price_match:
                    product_data["price_str"] = price_match.group(1).replace(" ", "").replace(",", ".") + " PLN"
                    product_data["price"] = float(price_match.group(1).replace(" ", "").replace(",", "."))
                else:
                    product_data["price_str"] = price_text
            
            # Extract Delivery/Shipping Price
            shipping_elem = card.find(class_=re.compile(r'(delivery|shipping|dostawa)', re.I))
            if shipping_elem:
                product_data["delivery"] = shipping_elem.get_text(strip=True)
            else:
                product_data["delivery"] = "darmowa dostawa" if "darmow" in card.get_text().lower() else "płatna dostawa"

            # Extract Seller/Shop Info
            seller_elem = card.find(class_=re.compile(r'(seller|shop|user|sklep|sprzedaj)', re.I))
            if seller_elem:
                product_data["seller"] = seller_elem.get_text(strip=True)
            else:
                # Try finding from data attributes
                product_data["seller"] = "Sklep Allegro"

            # Check if we got the basic elements
            if product_data.get("title") and product_data.get("price"):
                products.append(product_data)
        except Exception:
            continue

    return products
