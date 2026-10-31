from typing import List
from core.models.schemas import UserInput
from core.llm.base import BaseLLMProvider


class SearchQueryGenerator:
    def __init__(self, llm: BaseLLMProvider, max_queries: int = 5):
        self.llm = llm
        self.max_queries = max_queries

    def generate_queries(self, user_input: UserInput) -> List[str]:
        prompt = f"""
Generate {self.max_queries} diverse and specific web search queries for the topic: "{user_input.prompt}"

The queries should cover different aspects of the topic for comprehensive educational content generation.
Consider the content quality level: {user_input.content_quality.value}
Consider the content length: {user_input.content_length.value}

Return JSON format:
{{
    "queries": [
        "specific query 1",
        "specific query 2",
        "specific query 3",
        "specific query 4",
        "specific query 5"
    ]
}}
"""
        system_prompt = "You are an expert researcher. Generate precise, diverse search queries for comprehensive topic coverage."
        result = self.llm.generate_json(prompt, system_prompt, temperature=0.4)
        queries = result.get("queries", [])
        
        if not queries:
            queries = [user_input.prompt]
        
        return queries[:self.max_queries]