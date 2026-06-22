from llama_index.core.base.llms.types import ChatResponse, CompletionResponse
from llama_index.llms.litellm import LiteLLM


def _strip(text: str, fence_type: str) -> str:
    return (
        text.strip()
        .removeprefix(f"```{fence_type}").removeprefix("```")
        .removesuffix("```").strip()
    )


class SmartLiteLLM(LiteLLM):
    """LiteLLM subclass with optional markdown fence stripping."""

    async def acomplete(
        self, prompt: str, strip_fences: str | None = None, **kwargs
    ) -> CompletionResponse:
        response = await super().acomplete(prompt, **kwargs)
        if strip_fences is not None:
            response.text = _strip(response.text, strip_fences)
        return response

    async def achat(
        self, messages, strip_fences: str | None = None, **kwargs
    ) -> ChatResponse:
        response = await super().achat(messages, **kwargs)
        if strip_fences is not None:
            response.message.content = _strip(response.message.content, strip_fences)
        return response
