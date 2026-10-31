import requests
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from core.models.schemas import WebSearchResult


class WebCrawler:
    def __init__(self, worker_count: int = 4, timeout: int = 15):
        self.worker_count = max(1, worker_count)
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    def crawl_batch(self, results: List[WebSearchResult]) -> List[WebSearchResult]:
        reputable_results = [r for r in results if r.is_reputable]
        
        with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
            future_to_result = {
                executor.submit(self._crawl_single, result): result
                for result in reputable_results
            }
            
            for future in as_completed(future_to_result):
                result = future_to_result[future]
                try:
                    html_content = future.result()
                    result.normalized_content = html_content
                except Exception as e:
                    print(f"Crawl error for {result.url}: {e}")
                    result.normalized_content = ""
        
        return results

    def _crawl_single(self, result: WebSearchResult) -> str:
        try:
            response = requests.get(
                result.url,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return ""
            
            return response.text
        except requests.RequestException as e:
            print(f"Request failed for {result.url}: {e}")
            return ""
        except Exception as e:
            print(f"Unexpected error crawling {result.url}: {e}")
            return ""