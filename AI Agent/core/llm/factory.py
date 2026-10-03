from typing import Optional
from core.llm.base import BaseLLMProvider
from core.llm.providers.ollama import OllamaProvider


class LLMFactory:
    _providers = {
        "ollama": OllamaProvider,
    }

    @classmethod
    def create(cls, provider: str, model_name: str, base_url: str = "http://localhost:11434") -> BaseLLMProvider:
        provider_class = cls._providers.get(provider.lower())
        if not provider_class:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(cls._providers.keys())}")
        return provider_class(model_name=model_name, base_url=base_url)

    @classmethod
    def register_provider(cls, name: str, provider_class: type):
        cls._providers[name.lower()] = provider_class

    @classmethod
    def get_available_providers(cls) -> list:
        return list(cls._providers.keys())