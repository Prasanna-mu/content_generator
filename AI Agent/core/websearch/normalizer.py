import re
from datetime import datetime
from typing import List
from core.models.schemas import WebSearchResult


class ContentNormalizer:
    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars

    def normalize_batch(self, results: List[WebSearchResult]) -> List[WebSearchResult]:
        for result in results:
            if result.normalized_content:
                result.normalized_content = self._normalize(result.normalized_content)
                result.extracted_at = datetime.utcnow().isoformat() + "Z"
        return results

    def _normalize(self, text: str) -> str:
        text = re.sub(r'\r\n|\r', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)
        text = re.sub(r'\n +', '\n', text)
        text = re.sub(r' +\n', '\n', text)
        
        lines = text.split('\n')
        cleaned_lines = []
        seen = set()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if len(line) < 15:
                continue
            normalized_line = re.sub(r'\s+', ' ', line.lower())
            if normalized_line in seen:
                continue
            seen.add(normalized_line)
            cleaned_lines.append(line)
        
        normalized = '\n'.join(cleaned_lines)
        
        if len(normalized) > self.max_chars:
            normalized = normalized[:self.max_chars] + "\n[Content truncated...]"
        
        return normalized.strip()