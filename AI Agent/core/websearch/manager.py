import os
from datetime import datetime
from typing import List
from core.models.schemas import UserInput, WebSearchResult, WebSearchReport
from core.llm.base import BaseLLMProvider
from core.websearch.query_generator import SearchQueryGenerator
from core.websearch.searcher import WebSearcher
from core.websearch.reputation_checker import SourceQualityChecker, FactChecker
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
        self.source_quality_checker = SourceQualityChecker()
        self.fact_checker = FactChecker(llm)
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
                valid_sources=0,
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
                valid_sources=0,
                quality_sources=0,
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
        
        print(f"[Web Search] Validating source URLs (security + quality)...")
        results = self.source_quality_checker.check_batch(results)
        valid_count = sum(1 for r in results if r.is_valid_for_crawling)
        print(f"[Web Search] {valid_count}/{len(results)} sources passed security/quality validation")
        
        print(f"[Web Search] Crawling valid sources...")
        results = self.crawler.crawl_batch(results)
        
        print(f"[Web Search] Extracting content...")
        results = self.extractor.extract_batch(results)
        
        print(f"[Web Search] Normalizing content...")
        results = self.normalizer.normalize_batch(results)
        
        print(f"[Web Search] Analyzing content for relevance and quality...")
        results = self.analyzer.analyze_batch(results, user_input)
        
        # Fact-checking step for high-quality sources
        print(f"[Web Search] Fact-checking extracted content...")
        fact_check_count = 0
        for result in results:
            if result.normalized_content and len(result.normalized_content) > 500:
                result = self.fact_checker.verify_facts(result, user_input.prompt)
                fact_check_count += 1
        
        if fact_check_count > 0:
            print(f"[Web Search] Fact-checking completed for {fact_check_count} sources")
        
        print(f"[Web Search] Web search complete!")
        
        # Count sources with good quality scores
        quality_sources = sum(1 for r in results if getattr(r, 'fact_check_score', 0) >= 6)
        valid_sources = sum(1 for r in results if getattr(r, 'is_valid_for_crawling', False))
        
        return WebSearchReport(
            user_prompt=user_input.prompt,
            search_queries=queries,
            results=results,
            total_results=len(results),
            valid_sources=valid_sources,
            quality_sources=quality_sources,
            search_timestamp=datetime.utcnow().isoformat() + "Z"
        )