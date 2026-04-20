"""
PoC: LiteLLM Multi-Provider Chat
驗證 LlamaIndex LiteLLM 能否統一介面對多個 provider 完成 chat 呼叫。
支援 CLI 帶入 image 讓 VLM 分析，保留 context 做 sequential 問答。
Image 直接送出；若 provider 不支援，呼叫端會收到錯誤。

Usage:
    python main.py                          # 選擇 provider，純文字問答
    python main.py -i path/to/img.png       # 選擇 provider，帶 image 問答
    python main.py -p gemini -i img.png     # 指定 provider，帶 image 問答
"""

import os
import sys

import click
from dotenv import load_dotenv
from llama_index.core.base.llms.types import ImageBlock, TextBlock
from llama_index.core.llms import ChatMessage
from llama_index.llms.litellm import LiteLLM

# 也支援 poc 目錄內的 .env.local（override 優先）
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env.local"), override=True)

PROVIDERS = [
    {
        "name": "OpenRouter",
        "model": "openrouter/google/gemma-3-27b-it:free",
        # "model": "openrouter/nvidia/nemotron-nano-12b-v2-vl:free",
        # "model": "openrouter/google/gemma-3n-e4b-it:free",
        # "model": "openrouter/minimax/minimax-m2.5:free",
        "kwargs": {},
    },
    {
        "name": "Gemini",
        "model": "gemini/gemini-2.5-flash",
        "kwargs": {},
    },
    {
        "name": "Mistral",
        "model": "mistral/mistral-small-2506",
        "kwargs": {},
    },
    {
        "name": "Groq",
        "model": "groq/openai/gpt-oss-20b",
        # "model": "groq/qwen/qwen3-32b",
        "kwargs": {},
    },
    {
        "name": "Ollama",
        # "model": "ollama/gemma3:4b",
        "model": "ollama/qwen3.5:4b",
        "kwargs": {"api_base": "http://localhost:11434"},
    },
]


def select_provider() -> dict:
    """Interactive numbered menu to pick a provider."""
    print("\nAvailable providers:")
    for i, p in enumerate(PROVIDERS, 1):
        print(f"  {i}. {p['name']}")
    while True:
        try:
            raw = input(f"\nSelect provider (1-{len(PROVIDERS)}): ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(PROVIDERS):
                return PROVIDERS[idx]
            print(f"  Please enter a number between 1 and {len(PROVIDERS)}.")
        except ValueError:
            print("  Invalid input, please enter a number.")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)


def chat_loop(provider: dict, image_path: str | None) -> None:
    model = provider["model"]
    kwargs = provider.get("kwargs", {})
    llm = LiteLLM(model=model, **kwargs)

    # ── Image setup ──────────────────────────────────────────────────────────
    if image_path and not os.path.exists(image_path):
        print(f"❌ Image file not found: {image_path}")
        sys.exit(1)
    if image_path:
        print(f"🖼  Image loaded: {image_path}")

    # ── Chat loop ─────────────────────────────────────────────────────────────
    print(f"\n💬 Chat with {provider['name']} ({model})")
    if image_path:
        print("   Image will be attached to your first message.")
    print("   Type 'quit' or press Ctrl+C to exit.\n")

    messages: list[ChatMessage] = []
    image_attached = False

    while True:
        # Prompt
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Exiting.")
            break

        # Build message (image only on first turn)
        if image_path and not image_attached:
            msg = ChatMessage(role="user", blocks=[
                TextBlock(text=user_input),
                ImageBlock(path=image_path),
            ])
            image_attached = True
        else:
            msg = ChatMessage(role="user", content=user_input)

        messages.append(msg)

        # Call LLM
        try:
            resp = llm.chat(messages)
            assistant_msg = resp.message.content
            messages.append(ChatMessage(role="assistant", content=assistant_msg))
            print(f"\nAssistant: {assistant_msg}\n")

        except Exception as e:
            print(f"❌ Error: {e}")
            messages.pop()


@click.command()
@click.option(
    "--image", "-i",
    metavar="PATH",
    default=None,
    help="Path to a local image file to send to a VLM",
)
@click.option(
    "--provider", "-p",
    metavar="KEYWORD",
    default=None,
    help="Provider keyword to match (e.g. 'gemini', 'ollama'). "
         "If omitted, an interactive selection menu is shown.",
)
def main(image: str | None, provider: str | None) -> None:
    """LlamaIndex LiteLLM Multi-Provider Chat PoC — interactive Q&A with optional image input."""
    print("=" * 60)
    print("LlamaIndex LiteLLM Multi-Provider Chat PoC")
    print("=" * 60)

    # Provider selection
    if provider:
        kw = provider.lower()
        matched = [
            p for p in PROVIDERS
            if kw in p["name"].lower() or kw in p.get("model", "").lower()
        ]
        if not matched:
            print(f"❌ No provider matched '{provider}'. Available:")
            for p in PROVIDERS:
                print(f"   {p['name']}")
            sys.exit(1)
        selected = matched[0]
        print(f"\n✅ Using: {selected['name']}")
    else:
        selected = select_provider()
        print(f"\n✅ Selected: {selected['name']}")

    chat_loop(selected, image)


if __name__ == "__main__":
    main()
