from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.multi_modal_llms.azure_openai import AzureOpenAIMultiModal

from config import settings

llm = AzureOpenAI(
    azure_deployment=settings.AZURE_OPENAI_GPT4O_MODEL,
    model=settings.AZURE_OPENAI_GPT4O_MODEL,  # this name will be used in trace
    temperature=0.0,
    max_tokens=settings.MAX_TOKENS,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_key=settings.AZURE_OPENAI_API_KEY,
    api_version=settings.AZURE_OPENAI_API_VERSION,
)

vlm = AzureOpenAIMultiModal(
    azure_deployment=settings.AZURE_OPENAI_GPT4O_MODEL,
    model=settings.AZURE_OPENAI_GPT4O_MODEL,  # this name will be used in trace
    temperature=0.0,
    max_new_tokens=settings.MAX_TOKENS,  # 4096 is the maximum number of tokens allowed by the API
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_key=settings.AZURE_OPENAI_API_KEY,
    api_version=settings.AZURE_OPENAI_API_VERSION,
)


def new_vlm(temperature=0.0, callback_manager=None):
    return AzureOpenAIMultiModal(
        azure_deployment=settings.AZURE_OPENAI_GPT4O_MODEL,
        model=settings.AZURE_OPENAI_GPT4O_MODEL,  # this name will be used in trace
        temperature=temperature,
        max_new_tokens=settings.MAX_TOKENS,  # 4096 is the maximum number of tokens allowed by the API
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        callback_manager=callback_manager,
    )


def new_llm(temperature=0.0):
    return AzureOpenAI(
        azure_deployment=settings.AZURE_OPENAI_GPT4O_MODEL,
        model=settings.AZURE_OPENAI_GPT4O_MODEL,  # this name will be used in trace
        temperature=temperature,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )


def new_fast_llm(temperature=0.0):
    return AzureOpenAI(
        azure_deployment=settings.AZURE_OPENAI_GPT4O_MINI_MODEL,
        model=settings.AZURE_OPENAI_GPT4O_MINI_MODEL,  # this name will be used in trace
        temperature=temperature,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )
