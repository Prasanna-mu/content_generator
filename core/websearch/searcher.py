import os
import requests
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus


class WebSearcher:
    def __init__(self, worker_count: int = 4, results_per_query: int = 5):
        self.worker_count = max(1, worker_count)
        self.results_per_query = results_per_query
        self.api_key = os.getenv("SERPER_API_KEY") or os.getenv("SEARCH_API_KEY")
        self.search_engine = os.getenv("SEARCH_ENGINE", "duckduckgo")
        self.timeout = int(os.getenv("SEARCH_TIMEOUT", "10"))

    def search(self, queries: List[str]) -> List[Dict[str, Any]]:
        if not self._check_internet():
            return []
        
        all_results = []
        with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
            future_to_query = {
                executor.submit(self._search_single_query, query): query
                for query in queries
            }
            
            for future in as_completed(future_to_query):
                query = future_to_query[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception as e:
                    print(f"Search error for query '{query}': {e}")
        
        return all_results

    def _check_internet(self) -> bool:
        """Check internet connectivity using multiple fallback endpoints."""
        endpoints = [
            "http://www.google.com",
            "http://httpbin.org/get",
            "https://api.ipify.org",
            "http://connectivitycheck.gstatic.com/generate_204",
        ]
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=5)
                if response.status_code in (200, 204):
                    return True
            except requests.RequestException:
                continue
        return False

    def _search_single_query(self, query: str) -> List[Dict[str, Any]]:
        if self.search_engine == "serper" and self.api_key:
            return self._search_serper(query)
        elif self.search_engine == "bing" and self.api_key:
            return self._search_bing(query)
        else:
            return self._search_duckduckgo(query)

    def _search_serper(self, query: str) -> List[Dict[str, Any]]:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": self.results_per_query}
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return self._parse_serper_results(data, query)
        except Exception as e:
            print(f"Serper search failed for '{query}': {e}")
            return []

    def _search_bing(self, query: str) -> List[Dict[str, Any]]:
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        params = {"q": query, "count": self.results_per_query}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return self._parse_bing_results(data, query)
        except Exception as e:
            print(f"Bing search failed for '{query}': {e}")
            return []

    def _search_duckduckgo(self, query: str) -> List[Dict[str, Any]]:
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return self._parse_duckduckgo_results(response.text, query)
        except Exception as e:
            print(f"DuckDuckGo search failed for '{query}': {e}")
            return []

    def _parse_serper_results(self, data: Dict, query: str) -> List[Dict[str, Any]]:
        results = []
        for item in data.get("organic", [])[:self.results_per_query]:
            results.append({
                "query": query,
                "url": item.get("link", ""),
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
            })
        return results

    def _parse_bing_results(self, data: Dict, query: str) -> List[Dict[str, Any]]:
        results = []
        for item in data.get("webPages", {}).get("value", [])[:self.results_per_query]:
            results.append({
                "query": query,
                "url": item.get("url", ""),
                "title": item.get("name", ""),
                "snippet": item.get("snippet", ""),
            })
        return results

    def _parse_duckduckgo_results(self, html: str, query: str) -> List[Dict[str, Any]]:
        from bs4 import BeautifulSoup
        results = []
        soup = BeautifulSoup(html, "html.parser")
        
        # Try multiple selectors for DuckDuckGo's changing HTML structure
        # Current structure uses .result with data-testid="result"
        selectors = [
            "article[data-testid='result']",  # New DDG layout
            ".result[data-testid='result']",  # Alternative with class
            ".result",                         # Classic layout
            "[data-testid='result']",          # Test ID based
            ".web-result",                     # Alternative class
            ".result__body",                   # Result body
            "div.results > div",               # Generic result container
        ]
        
        result_elements = []
        for selector in selectors:
            result_elements = soup.select(selector)
            if result_elements:
                break
        
        # Fallback: try to find any link-containing elements with snippets
        if not result_elements:
            # Find all links that have surrounding text (likely results)
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if href.startswith("http") and "duckduckgo.com" not in href:
                    # Get parent element that might contain the result
                    parent = link.parent
                    if parent:
                        result_elements.append(parent)
        
        for elem in result_elements[:self.results_per_query]:
            try:
                # Try to find URL - look for the main result link
                url = ""
                # First try: link with result__url class
                link_elem = elem.find("a", class_="result__url")
                if not link_elem:
                    # Second try: any link with http URL that's not duckduckgo
                    for a in elem.find_all("a", href=True):
                        href = a.get("href", "")
                        if href.startswith("http") and "duckduckgo.com" not in href:
                            link_elem = a
                            break
                if link_elem:
                    url = link_elem.get("href", "")
                
                # Try to find title
                title = ""
                # First try: result__title class
                title_elem = elem.find("a", class_="result__title")
                if not title_elem:
                    # Second try: h2, h3, or strong
                    title_elem = elem.find("h2") or elem.find("h3") or elem.find("strong")
                if not title_elem:
                    # Third try: the link element itself if it has text
                    if link_elem and link_elem.get_text(strip=True):
                        title = link_elem.get_text(strip=True)
                if title_elem and not title:
                    title = title_elem.get_text(strip=True)
                
                # Try to find snippet
                snippet = ""
                snippet_elem = elem.find(class_="result__snippet") or elem.find(class_="snippet") or elem.find("p")
                if snippet_elem:
                    snippet = snippet_elem.get_text(strip=True)
                else:
                    # Try to find any substantial text
                    for p in elem.find_all("p"):
                        text = p.get_text(strip=True)
                        if len(text) > 30:
                            snippet = text
                            break
                
                # Clean up URL - DuckDuckGo sometimes wraps URLs
                if url and url.startswith("//duckduckgo.com/l/?uddg="):
                    import urllib.parse
                    url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
                
                if url and title:
                    results.append({
                        "query": query,
                        "url": url,
                        "title": title,
                        "snippet": snippet,
                    })
            except Exception as e:
                # Skip malformed results but continue parsing
                continue
        
        # If still no results, try a more aggressive parsing
        if not results:
            # Find all links in the page
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if href.startswith("http") and "duckduckgo.com" not in href:
                    title = link.get_text(strip=True)
                    if title and len(title) > 5:
                        results.append({
                            "query": query,
                            "url": href,
                            "title": title,
                            "snippet": "",
                        })
                        if len(results) >= self.results_per_query:
                            break
        
        return results