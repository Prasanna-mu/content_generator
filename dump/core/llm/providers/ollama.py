import json
import requests
from typing import Dict, Any, Optional
from core.llm.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    def __init__(self, model_name: str = "qwen2.5:3b", base_url: str = "http://localhost:11434"):
        super().__init__(model_name, base_url)
        self.api_url = f"{base_url}/api/generate"
        self.chat_url = f"{base_url}/api/chat"

    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "top_p": kwargs.get("top_p", 0.9),
                "num_predict": kwargs.get("num_predict", 4096),
            }
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = requests.post(self.api_url, json=payload, timeout=None)
        response.raise_for_status()
        return response.json().get("response", "").strip()

    def generate_json(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        json_prompt = f"{prompt}\n\nIMPORTANT: Return ONLY valid JSON. No additional text, no markdown formatting."
        
        payload = {
            "model": self.model_name,
            "prompt": json_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": kwargs.get("temperature", 0.3),
                "top_p": kwargs.get("top_p", 0.9),
                "num_predict": kwargs.get("num_predict", 4096),
            }
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = requests.post(self.api_url, json=payload, timeout=None)
        response.raise_for_status()
        
        result_text = response.json().get("response", "").strip()
        try:
            return json.loads(result_text)
        except json.JSONDecodeError as e:
            return self._attempt_json_recovery(result_text)

    def _attempt_json_recovery(self, text: str) -> Dict[str, Any]:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
        return {"lessons": [], "subtopics": [], "questions": []}

    def check_connection(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> list:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                return [model["name"] for model in response.json().get("models", [])]
        except requests.RequestException:
            pass
        return []

    def pull_model(self) -> bool:
        try:
            payload = {"name": self.model_name, "stream": False}
            response = requests.post(f"{self.base_url}/api/pull", json=payload, timeout=600)
            return response.status_code == 200
        except requests.RequestException:
            return False