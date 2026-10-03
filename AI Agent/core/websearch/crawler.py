import re
import requests
import ipaddress
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from core.models.schemas import WebSearchResult


class WebCrawler:
    PRIVATE_IP_RANGES = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]

    BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "0.0.0.0", "127.0.0.1", "[::1]"}
    BLOCKED_PORTS = {22, 23, 25, 53, 110, 135, 139, 143, 445, 993, 995, 1433, 1521, 3306, 3389, 5432, 5900, 6379, 27017}

    def __init__(self, worker_count: int = 4, timeout: int = 15):
        self.worker_count = max(1, worker_count)
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    def crawl_batch(self, results: List[WebSearchResult]) -> List[WebSearchResult]:
        # Crawl all results that pass security validation (not just "reputable" ones)
        crawlable_results = [r for r in results if getattr(r, 'is_valid_for_crawling', True)]
        
        with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
            future_to_result = {
                executor.submit(self._crawl_single, result): result
                for result in crawlable_results
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
        if not self._is_safe_url(result.url):
            print(f"Blocked unsafe URL: {result.url}")
            return ""
        
        try:
            response = requests.get(
                result.url,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            
            if not self._is_safe_redirect(response.url):
                print(f"Blocked unsafe redirect: {response.url}")
                return ""
            
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

    def _is_safe_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname or ""
        if not hostname:
            return False

        if hostname.lower() in self.BLOCKED_HOSTS:
            return False

        if hostname.endswith(".local") or hostname.endswith(".internal") or hostname.endswith(".lan"):
            return False

        if re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname):
            try:
                ip = ipaddress.ip_address(hostname)
                for private_range in self.PRIVATE_IP_RANGES:
                    if ip in private_range:
                        return False
            except ValueError:
                return False

        port = parsed.port
        if port and port in self.BLOCKED_PORTS:
            return False

        return True

    def _is_safe_redirect(self, url: str) -> bool:
        return self._is_safe_url(url)

    def _resolve_hostname(self, hostname: str) -> List[str]:
        try:
            import socket
            return [addr[4][0] for addr in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)]
        except Exception:
            return []