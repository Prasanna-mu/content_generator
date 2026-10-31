from core.models.schemas import UserInput
from core.llm.base import BaseLLMProvider


class PromptAnalyzer:
    def __init__(self, llm: BaseLLMProvider):
        self.llm = llm

    def analyze(self, user_input: UserInput) -> dict:
        prompt = f"""
Analyze the following topic for educational content generation:
Topic: "{user_input.prompt}"

Provide analysis in JSON format:
{{
    "domain": "main subject domain",
    "complexity": "beginner/intermediate/advanced",
    "key_concepts": ["concept1", "concept2", ...],
    "suggested_structure": "linear/spiral/modular",
    "prerequisites": ["prereq1", "prereq2", ...],
    "learning_objectives": ["objective1", "objective2", ...]
}}
"""
        system_prompt = "You are an expert educational analyst. Analyze topics for curriculum design."
        return self.llm.generate_json(prompt, system_prompt, temperature=0.3)