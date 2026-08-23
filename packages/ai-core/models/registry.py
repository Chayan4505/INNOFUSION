from packages.ai_core.models.provider import AIProvider
from packages.ai_core.models.exceptions import UnsupportedProviderError
from langchain_google_genai import ChatGoogleGenerativeAI

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = ChatGoogleGenerativeAI

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = ChatGoogleGenerativeAI

# OpenRouter uses OpenAI-compatible API, so we use ChatOpenAI with custom base_url
class OpenRouterChatOpenAI(ChatOpenAI):
    """ChatOpenAI adapter for OpenRouter API"""
    def __init__(self, api_key: str = None, model: str = None, **kwargs):
        super().__init__(
            openai_api_key=api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            model_name=model or "nvidia/nemotron-3.5-lightning:free",
            **kwargs
        )

class ModelRegistry:
    """
    Resolves a string provider name into the corresponding LangChain implementation.
    """
    @staticmethod
    def get_langchain_class(provider: str):
        if provider == AIProvider.GEMINI or provider == "gemini":
            return ChatGoogleGenerativeAI
        elif provider == AIProvider.OPENAI or provider == "openai":
            return ChatOpenAI
        elif provider == AIProvider.ANTHROPIC or provider == "anthropic":
            return ChatAnthropic
        elif provider == "openrouter":
            return OpenRouterChatOpenAI
        else:
            return ChatGoogleGenerativeAI
