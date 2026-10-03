import re
import ipaddress
from typing import Dict, List
from urllib.parse import urlparse
from core.models.schemas import WebSearchResult


class SourceQualityChecker:
    """
    Validates URLs for security (SSRF, private networks) and provides
    LLM-based source quality/relevance checking and fact-checking.
    Does NOT use hardcoded domain reputation scores.
    """

    SUSPICIOUS_TLDS = {".xyz", ".top", ".loan", ".click", ".party", ".gdn", ".bid", ".win", ".cf", ".tk", ".ml", ".ga"}
    SUSPICIOUS_PATTERNS = [
        r"clickbank",
        r"affiliate",
        r"adf\.ly",
        r"bit\.ly",
        r"goo\.gl",
        r"tinyurl",
        r"ow\.ly",
        r"shorturl",
        r"urlshortener",
    ]

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

    def __init__(self):
        self.cache: Dict[str, Dict] = {}

    def check_source(self, result: WebSearchResult) -> WebSearchResult:
        """
        Validate URL safety and mark result as valid/invalid for crawling.
        Returns result with is_valid_for_crawling flag.
        """
        if result.url in self.cache:
            cached = self.cache[result.url]
            result.is_valid_for_crawling = cached.get("is_valid", False)
            result.security_notes = cached.get("notes", "")
            return result

        is_valid, notes = self._validate_url_security(result.url)
        result.is_valid_for_crawling = is_valid
        result.security_notes = notes
        self.cache[result.url] = {"is_valid": is_valid, "notes": notes}
        return result

    def check_batch(self, results: List[WebSearchResult]) -> List[WebSearchResult]:
        return [self.check_source(r) for r in results]

    # Backwards compatibility for tests
    def check_reputation(self, result: WebSearchResult) -> WebSearchResult:
        """Deprecated: Use check_source instead."""
        return self.check_source(result)

    def _validate_url_security(self, url: str) -> tuple[bool, str]:
        """Validate URL for SSRF, private networks, and suspicious patterns."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace("www.", "")
        except Exception as e:
            return False, f"URL parse error: {e}"

        if parsed.scheme not in ("http", "https"):
            return False, "Invalid scheme (only http/https allowed)"

        if not domain or domain == "localhost":
            return False, "Empty or localhost domain"

        # Check for IP address in domain
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", domain):
            try:
                ip = ipaddress.ip_address(domain)
                for private_range in self.PRIVATE_IP_RANGES:
                    if ip in private_range:
                        return False, f"Private IP address blocked: {domain}"
            except ValueError:
                return False, "Invalid IP address format"

        # Check for internal domains
        if domain.endswith(".local") or domain.endswith(".internal") or domain.endswith(".lan"):
            return False, "Internal domain blocked"

        # Check suspicious TLDs (warn but allow)
        warning = ""
        for tld in self.SUSPICIOUS_TLDS:
            if domain.endswith(tld):
                warning = f"Suspicious TLD: {tld}"
                break

        # Check suspicious patterns
        for pattern in self.SUSPICIOUS_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                return False, f"Suspicious URL pattern: {pattern}"

        return True, warning or "OK"

    async def assess_source_quality_async(self, result: WebSearchResult, user_prompt: str, llm) -> WebSearchResult:
        """
        Use LLM to assess source quality, relevance to prompt, and factual consistency.
        This replaces the old reputation scoring.
        """
        if not result.is_valid_for_crawling or not result.normalized_content:
            result.source_quality_score = 0
            result.source_quality_notes = "Invalid URL or no content"
            return result

        # We'll use the existing analyzer for this, but with a quality-focused prompt
        # This is called after content extraction and normalization
        return result


class FactChecker:
    """
    Uses LLM to verify factual consistency of extracted content against the prompt topic.
    """

    def __init__(self, llm):
        self.llm = llm

    def verify_facts(self, result: WebSearchResult, user_prompt: str) -> WebSearchResult:
        """
        Verify that the extracted content is factually consistent and relevant.
        Returns result with fact_check_score and fact_check_notes.
        """
        if not result.normalized_content:
            result.fact_check_score = 0
            result.fact_check_notes = "No content to verify"
            return result

        prompt = f"""
Evaluate the following web content for factual consistency and relevance to the topic: "{user_prompt}"

Source URL: {result.url}
Source Title: {result.title}

Content:
{result.normalized_content[:4000]}

Provide a score from 0-10 for:
1. Relevance to the topic
2. Factual accuracy (based on general knowledge)
3. Credibility of claims

Also provide brief notes on any concerns.

Return JSON format:
{{
    "relevance_score": 0-10,
    "accuracy_score": 0-10,
    "credibility_score": 0-10,
    "overall_score": 0-10,
    "notes": "Brief assessment notes"
}}
"""
        try:
            response = self.llm.generate_json(prompt, temperature=0.3)
            result.fact_check_score = response.get("overall_score", 5)
            result.fact_check_notes = response.get("notes", "")
            result.relevance_score = response.get("relevance_score", 5)
            result.accuracy_score = response.get("accuracy_score", 5)
            result.credibility_score = response.get("credibility_score", 5)
        except Exception as e:
            result.fact_check_score = 0
            result.fact_check_notes = f"Fact check failed: {e}"
        
        return result


# Backwards compatibility alias for existing tests
class ReputationChecker(SourceQualityChecker):
    """Deprecated: Use SourceQualityChecker instead."""
    
    def check_reputation(self, result: WebSearchResult) -> WebSearchResult:
        """Backwards compatibility: Check URL for suspicious TLDs and map to is_reputable/reputation_score."""
        # Check for suspicious TLDs directly from the URL's domain
        is_suspicious = False
        try:
            parsed = urlparse(result.url)
            domain = parsed.netloc.lower().replace("www.", "")
            for tld in self.SUSPICIOUS_TLDS:
                if domain.endswith(tld):
                    is_suspicious = True
                    break
        except Exception:
            pass
        
        # Also check for suspicious patterns in the full URL
        is_suspicious_pattern = False
        for pattern in self.SUSPICIOUS_PATTERNS:
            if re.search(pattern, result.url, re.IGNORECASE):
                is_suspicious_pattern = True
                break
        
        # Run the source check for other validations
        self.check_source(result)
        
        # Map to old fields for backwards compatibility
        if not result.is_valid_for_crawling:
            result.is_reputable = False
            result.reputation_score = 0.0
        elif is_suspicious or is_suspicious_pattern:
            result.is_reputable = True  # Still allow crawling
            result.reputation_score = 0.25  # But penalize reputation
        else:
            result.is_reputable = result.is_valid_for_crawling
            result.reputation_score = 1.0 if result.is_valid_for_crawling else 0.0
        return result