"""
local_llm.py

Runs the LLM locally via Ollama (https://ollama.com) instead of calling a
hosted API or loading the model into this process directly via transformers.
No API key/token needed — Ollama serves the model from a local HTTP server
on your machine, and manages GPU/CPU placement, quantization, and memory
itself.

Requires Ollama to be installed and running, and the model pulled once:
    ollama pull qwen2.5:7b-instruct
    ollama serve        # usually started automatically on install

Only uses Python's standard library (urllib) — no extra HTTP client
dependency required.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import LLM_MODEL, LLM_MAX_NEW_TOKENS, LLM_HOST, LLM_TIMEOUT_SECONDS

_CHAT_ENDPOINT = "/api/chat"
_TAGS_ENDPOINT = "/api/tags"

_checked_model = False


def _check_ollama_available_and_model_pulled():
    """
    One-time sanity check (cached for the process) that Ollama is reachable
    and the configured model has actually been pulled. Fails with a clear,
    actionable error instead of a confusing connection/HTTP error deep in
    a generate() call.
    """
    global _checked_model
    if _checked_model:
        return

    url = f"{LLM_HOST}{_TAGS_ENDPOINT}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach Ollama at {LLM_HOST}. Is it running?\n"
            f"  Install: https://ollama.com\n"
            f"  Start:   ollama serve\n"
            f"  (underlying error: {e})"
        )

    available = {m.get("name", "") for m in data.get("models", [])}
    # Ollama tags can include/omit a ":latest" suffix — match loosely.
    model_base = LLM_MODEL.split(":")[0]
    if not any(name == LLM_MODEL or name.split(":")[0] == model_base for name in available):
        raise RuntimeError(
            f"Model '{LLM_MODEL}' is not pulled in Ollama.\n"
            f"  Run:  ollama pull {LLM_MODEL}\n"
            f"  Currently available models: {sorted(available) or '(none)'}"
        )

    _checked_model = True


def generate_chat(system_prompt: str, user_content: str,
                   max_new_tokens: int | None = None, temperature: float = 0.1) -> str:
    """
    Run a single chat-style completion via the local Ollama server.
    Returns the assistant's reply text (stripped).
    """
    _check_ollama_available_and_model_pulled()

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        "stream": False,
        "options": {
            "num_predict": max_new_tokens or LLM_MAX_NEW_TOKENS,
            "temperature": temperature,
        },
    }

    url = f"{LLM_HOST}{_CHAT_ENDPOINT}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Ollama returned HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Ollama at {url}: {e}")
    except TimeoutError:
        raise RuntimeError(
            f"Ollama did not respond within {LLM_TIMEOUT_SECONDS}s. "
            f"Increase NVME_HELPER_TIMEOUT if the model is just slow on your hardware."
        )

    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    reply = data.get("message", {}).get("content", "")
    return reply.strip()