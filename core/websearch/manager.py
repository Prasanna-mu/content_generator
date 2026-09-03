import os
from datetime import datetime
from typing import List
from core.models.schemas import UserInput, WebSearchResult, WebSearchReport
from core.llm.base import BaseLLMProvider
from core.websearch.query_generator import SearchQueryGenerator
from core.websearch.searcher import WebSearcher
from core.websearch.reputation_checker import ReputationChecker
from core.websearch.crawler import WebCrawler
from core.websearch.extractor import ContentExtractor
from core.websearch.normalizer import ContentNormalizer
from core.websearch.analyzer import ContentAnalyzer


class WebSearchManager:
    def __init__(
        self,
        llm: BaseLLMProvider,
        worker_count: int = 4,
        max_queries: int = 5,
        results_per_query: int = 5,
        max_content_chars: int = 50000
    ):
        self.llm = llm
        self.worker_count = max(1, worker_count)
        
        self.query_generator = SearchQueryGenerator(llm, max_queries)
        self.searcher = WebSearcher(worker_count, results_per_query)
        self.reputation_checker = ReputationChecker()
        self.crawler = WebCrawler(worker_count)
        self.extractor = ContentExtractor()
        self.normalizer = ContentNormalizer(max_content_chars)
        self.analyzer = ContentAnalyzer(llm)

    def run_web_search(self, user_input: UserInput) -> WebSearchReport:
        print("\n[Web Search] Starting web search process...")
        
        if not self.searcher._check_internet():
            print("[Web Search] No internet connection available. Skipping web search silently.")
            return WebSearchReport(
                user_prompt=user_input.prompt,
                search_queries=[],
                results=[],
                total_results=0,
                reputable_results=0,
                search_timestamp=datetime.utcnow().isoformat() + "Z"
            )
        
        print(f"[Web Search] Generating search queries...")
        queries = self.query_generator.generate_queries(user_input)
        print(f"[Web Search] Generated {len(queries)} queries: {queries}")
        
        print(f"[Web Search] Performing web search (parallel workers: {self.worker_count})...")
        raw_results = self.searcher.search(queries)
        print(f"[Web Search] Found {len(raw_results)} raw results")
        
        if not raw_results:
            print("[Web Search] No results found. Skipping further processing.")
            return WebSearchReport(
                user_prompt=user_input.prompt,
                search_queries=queries,
                results=[],
                total_results=0,
                reputable_results=0,
                search_timestamp=datetime.utcnow().isoformat() + "Z"
            )
        
        results = [
            WebSearchResult(
                query=r["query"],
                url=r["url"],
                title=r["title"],
                snippet=r["snippet"]
            )
            for r in raw_results
        ]
        
        print(f"[Web Search] Checking site reputation...")
        results = self.reputation_checker.check_batch(results)
        reputable_count = sum(1 for r in results if r.is_reputable)
        print(f"[Web Search] {reputable_count}/{len(results)} results are reputable")
        
        print(f"[Web Search] Crawling reputable sites...")
        results = self.crawler.crawl_batch(results)
        
        print(f"[Web Search] Extracting content...")
        results = self.extractor.extract_batch(results)
        
        print(f"[Web Search] Normalizing content...")
        results = self.normalizer.normalize_batch(results)
        
        print(f"[Web Search] Analyzing content...")
        results = self.analyzer.analyze_batch(results, user_input)
        
        print(f"[Web Search] Web search complete!")
        
        return WebSearchReport(
            user_prompt=user_input.prompt,
            search_queries=queries,
            results=results,
            total_results=len(results),
            reputable_results=reputable_count,
            search_timestamp=datetime.utcnow().isoformat() + "Z"
        )