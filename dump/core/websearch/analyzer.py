from typing import List
from core.models.schemas import WebSearchResult, UserInput
from core.llm.base import BaseLLMProvider


class ContentAnalyzer:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    def analyze_batch(self, results: List[WebSearchResult], user_input: UserInput) -> List[WebSearchResult]:
        for result in results:
            if result.normalized_content and result.is_reputable:
                result.analysis = self._analyze_content(result, user_input)
                result.facts_verified = True
        return results

    def _analyze_content(self, result: WebSearchResult, user_input: UserInput) -> str:
        prompt = f"""
Analyze the following web content for the topic: "{user_input.prompt}"

Source: {result.url}
Title: {result.title}

Content:
{result.normalized_content[:3000]}

Provide a concise analysis covering:
1. Key insights relevant to the topic
2. Technical accuracy assessment
3. Credibility indicators
4. Useful information for educational content generation

Return only the analysis text, no JSON.
"""
        system_prompt = f"You are an expert {user_input.content_quality.value} level technical analyst. Evaluate content for educational use."
        try:
            return self.llm.generate(prompt, system_prompt, temperature=0.3)
        except Exception as e:
            return f"Analysis failed: {e}"