"""
NVMe Helper — central configuration.
Edit this file to change model, token, and paths.
"""
import os
import json
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
KB_DIR      = BASE_DIR / "kb"
CMD_DIR     = KB_DIR / "commands"
TABLE_DIR   = KB_DIR / "tables"
SCHEMA_DIR  = KB_DIR / "schemas"

# ── LLM (used only in intent parser and the KB generator — runs via Ollama) ───
# Ollama must be installed and running locally (https://ollama.com).
# Pull the model once before first use, e.g.:
#   ollama pull qwen2.5:7b-instruct
# LLM_MODEL is the Ollama model tag (not a Hugging Face repo id).
LLM_MODEL    = os.environ.get("NVME_HELPER_MODEL", "qwen2.5:7b-instruct")
LLM_HOST     = os.environ.get("NVME_HELPER_OLLAMA_HOST", "http://localhost:11434")
LLM_MAX_NEW_TOKENS = 512
LLM_TIMEOUT_SECONDS = int(os.environ.get("NVME_HELPER_TIMEOUT", "300"))

# ── Intent parser behaviour ───────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.6    # below this → clarification requested

# ── Debug / output behaviour ──────────────────────────────────────────────────
DEBUG = os.environ.get("NVME_HELPER_DEBUG", "0") == "1"
DEFAULT_OUTPUT_MODE = "both"   # "human" | "json" | "both"


def _load_json_table(filename: str) -> dict:
    path = TABLE_DIR / filename
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


# ── Pre-loaded shared reference tables ────────────────────────────────────────
KB_TABLES = {
    "cns_values":   _load_json_table("cns_values.json"),
    "status_codes": _load_json_table("status_codes.json"),
    "opcodes":      _load_json_table("opcodes.json"),
}