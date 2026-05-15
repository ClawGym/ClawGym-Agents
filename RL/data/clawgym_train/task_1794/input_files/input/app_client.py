import os
import sys
import json
import requests
from typing import List, Dict, Any

"""
Current app client: calls a cloud OpenAI-compatible API for chat and embeddings.

- Base URL: defaults to https://api.openai.com/v1, override with CLOUD_BASE_URL
- Auth: Bearer token from OPENAI_API_KEY (or CLOUD_API_KEY fallback)
- Endpoints used:
  - POST /chat/completions
  - POST /embeddings
- Models:
  - Chat: "gpt-3.5-turbo"
  - Embeddings: "text-embedding-3-small"
- Expected response shapes:
  - chat/completions: {"choices":[{"message":{"role":"assistant","content":"..."}}], ...}
  - embeddings: {"data":[{"embedding":[...], "index":0}], "model":"...", ...}
"""

BASE_URL = os.getenv("CLOUD_BASE_URL", "https://api.openai.com/v1")
API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("CLOUD_API_KEY")

if not API_KEY:
    # For local development this prints a warning; production callers should set an env var
    sys.stderr.write("Warning: OPENAI_API_KEY/CLOUD_API_KEY not set; requests will likely fail.\n")


def send_chat(prompt: str, model: str = "gpt-3.5-turbo", temperature: float = 0.7) -> str:
    """
    Sends a chat request to the cloud chat/completions endpoint.
    Returns the assistant message content string.
    """
    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY or ''}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # Cloud shape assumed:
    # {
    #   "id": "...",
    #   "object": "chat.completion",
    #   "choices": [
    #     {"index":0, "message":{"role":"assistant","content":"..."},"finish_reason":"stop"}
    #   ],
    #   ...
    # }
    return data["choices"][0]["message"]["content"]


def get_embeddings(texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
    """
    Sends an embeddings request to the cloud embeddings endpoint.
    Returns a list of embedding vectors.
    """
    url = f"{BASE_URL}/embeddings"
    headers = {
        "Authorization": f"Bearer {API_KEY or ''}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "input": texts,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # Cloud shape assumed:
    # {
    #   "data": [
    #     {"object":"embedding","index":0,"embedding":[...]}
    #   ],
    #   "model":"text-embedding-3-small",
    #   ...
    # }
    vectors = [item["embedding"] for item in data.get("data", [])]
    return vectors


def _demo() -> None:
    # Lightweight demo for current cloud path
    try:
        reply = send_chat("Quick test: say HELLO in one word.")
        print("Chat reply:", reply)
    except Exception as e:
        print("Chat error:", e, file=sys.stderr)

    try:
        vecs = get_embeddings(["hello world", "migration test"])
        print("Embeddings returned:", len(vecs), "vectors; first length:", len(vecs[0]) if vecs else 0)
    except Exception as e:
        print("Embeddings error:", e, file=sys.stderr)


if __name__ == "__main__":
    # Run a basic check if executed directly
    _demo()