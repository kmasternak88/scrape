'''
Converter module to format raw HTML to multiple representations.
'''
import csv
import io
import json
from typing import Dict, Any, List, Optional
from markdownify import markdownify as md

class OutputConverter:
    def to_markdown(self, html: str) -> str:
        return md(html, heading_style='ATX')

    def to_json(self, text: Any, schema: Optional[Dict[str, Any]] = None) -> str:
        if isinstance(text, str):
            return json.dumps({'raw_text': text, 'extracted_fields': {}})
        return json.dumps(text)

    def to_csv(self, data: List[Dict[str, Any]]) -> str:
        if not data:
            return ''
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        return output.getvalue()

    def to_ndjson(self, data: List[Dict[str, Any]]) -> str:
        return '\n'.join(json.dumps(row) for row in data)
