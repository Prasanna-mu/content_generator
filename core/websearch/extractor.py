from bs4 import BeautifulSoup
from typing import List
from core.models.schemas import WebSearchResult


class ContentExtractor:
    UNWANTED_TAGS = [
        "script", "style", "nav", "footer", "header", "aside",
        "noscript", "iframe", "form", "button", "input", "select",
        "textarea", "svg", "canvas", "audio", "video", "source",
        "track", "map", "area", "embed", "object", "param",
        "advertisement", "ad", "ads", "banner", "popup", "modal",
        "cookie", "consent", "newsletter", "subscribe", "social",
        "share", "comment", "comments", "related", "sidebar"
    ]

    UNWANTED_CLASSES = [
        "ad", "ads", "advertisement", "banner", "popup", "modal",
        "cookie", "consent", "newsletter", "subscribe", "social",
        "share", "comment", "comments", "related", "sidebar",
        "navigation", "nav", "menu", "header", "footer",
        "widget", "promo", "sponsor", "affiliate", "tracking"
    ]

    UNWANTED_IDS = [
        "ad", "ads", "advertisement", "banner", "popup", "modal",
        "cookie", "consent", "newsletter", "subscribe", "sidebar",
        "navigation", "nav", "menu", "header", "footer",
        "widget", "promo", "sponsor", "affiliate", "tracking"
    ]

    def __init__(self):
        pass

    def extract_batch(self, results: List[WebSearchResult]) -> List[WebSearchResult]:
        for result in results:
            if result.normalized_content:
                result.normalized_content = self._extract_text(result.normalized_content)
        return results

    def _extract_text(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            for tag_name in self.UNWANTED_TAGS:
                for tag in soup.find_all(tag_name):
                    tag.decompose()
            
            for tag in soup.find_all(class_=True):
                classes = tag.get("class", [])
                if any(unwanted in " ".join(classes).lower() for unwanted in self.UNWANTED_CLASSES):
                    tag.decompose()
            
            for tag in soup.find_all(id=True):
                tag_id = tag.get("id", "").lower()
                if any(unwanted in tag_id for unwanted in self.UNWANTED_IDS):
                    tag.decompose()
            
            main_content = self._find_main_content(soup)
            if main_content:
                text = main_content.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)
            
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            filtered_lines = [line for line in lines if len(line) > 20]
            
            return "\n".join(filtered_lines)
        except Exception as e:
            print(f"Extraction error: {e}")
            return ""

    def _find_main_content(self, soup: BeautifulSoup):
        selectors = [
            "main", "article", "[role='main']", ".main-content",
            ".content", ".post-content", ".entry-content", ".article-content",
            ".post-body", ".entry-body", "#content", "#main", "#article",
            ".container .content", ".wrapper .content"
        ]
        
        for selector in selectors:
            element = soup.select_one(selector)
            if element and len(element.get_text(strip=True)) > 200:
                return element
        
        return None