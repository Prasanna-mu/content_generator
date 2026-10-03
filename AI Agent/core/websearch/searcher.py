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
        try:
            requests.get("http://www.google.com", timeout=3)
            return True
        except requests.RequestException:
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
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        try:
            response = requests.post(url, data=params, headers=headers, timeout=self.timeout)
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
        for result in soup.select(".result__snippet, .snippet")[:self.results_per_query]:
            link_elem = result.find_previous("a", class_="result__url") or result.find_previous("a")
            url = link_elem.get("href", "") if link_elem else ""
            title_elem = result.find_previous("a", class_="result__title") or result.find_previous("h2")
            title = title_elem.get_text(strip=True) if title_elem else ""
            snippet = result.get_text(strip=True)
            if url and title:
                results.append({
                    "query": query,
                    "url": url,
                    "title": title,
                    "snippet": snippet,
                })
        return results