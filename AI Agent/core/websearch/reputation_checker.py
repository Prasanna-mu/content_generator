import re
from typing import Dict, List
from urllib.parse import urlparse
from core.models.schemas import WebSearchResult


class ReputationChecker:
    REPUTABLE_DOMAINS = {
        "wikipedia.org": 0.9,
        "github.com": 0.85,
        "stackoverflow.com": 0.9,
        "docs.python.org": 0.95,
        "developer.mozilla.org": 0.95,
        "docs.microsoft.com": 0.9,
        "cloud.google.com": 0.9,
        "aws.amazon.com": 0.9,
        "kubernetes.io": 0.9,
        "docker.com": 0.85,
        "realpython.com": 0.85,
        "freecodecamp.org": 0.8,
        "geeksforgeeks.org": 0.75,
        "tutorialspoint.com": 0.7,
        "w3schools.com": 0.7,
        "medium.com": 0.65,
        "dev.to": 0.65,
        "reddit.com": 0.5,
        "quora.com": 0.4,
        "djangoproject.com": 0.95,
        "django-rest-framework.org": 0.9,
        "pypi.org": 0.9,
        "readthedocs.io": 0.85,
        "gitlab.com": 0.85,
        "bitbucket.org": 0.8,
        "npmjs.com": 0.85,
        "pypi.python.org": 0.9,
        "anaconda.org": 0.85,
    }

    SUSPICIOUS_TLDS = {".xyz", ".top", ".loan", ".click", ".party", ".gdn", ".bid", ".win"}
    SUSPICIOUS_PATTERNS = [
        r"clickbank",
        r"affiliate",
        r"adf\.ly",
        r"bit\.ly",
        r"goo\.gl",
        r"tinyurl",
        r"ow\.ly",
    ]

    def __init__(self):
        self.cache: Dict[str, float] = {}

    def check_reputation(self, result: WebSearchResult) -> WebSearchResult:
        if result.url in self.cache:
            result.reputation_score = self.cache[result.url]
            result.is_reputable = result.reputation_score >= 0.6
            return result

        score = self._calculate_reputation_score(result.url, result.title)
        result.reputation_score = score
        result.is_reputable = score >= 0.6
        self.cache[result.url] = score
        return result

    def check_batch(self, results: List[WebSearchResult]) -> List[WebSearchResult]:
        return [self.check_reputation(r) for r in results]

    def _calculate_reputation_score(self, url: str, title: str) -> float:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace("www.", "")
        except Exception:
            return 0.1

        score = 0.3

        for known_domain, known_score in self.REPUTABLE_DOMAINS.items():
            if known_domain in domain:
                score = max(score, known_score)
                break

        for tld in self.SUSPICIOUS_TLDS:
            if domain.endswith(tld):
                score = min(score, 0.2)
                break

        for pattern in self.SUSPICIOUS_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                score = min(score, 0.1)
                break

        if "https://" in url:
            score += 0.1

        if any(keyword in title.lower() for keyword in ["official", "documentation", "docs", "guide", "tutorial", "reference"]):
            score += 0.05

        if any(keyword in title.lower() for keyword in ["best", "top 10", "review", "comparison", "vs"]):
            score -= 0.05

        return max(0.0, min(1.0, score))