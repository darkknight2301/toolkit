"""
Stage 1 — Intent Parser
Converts a natural-language NVMe request into a structured intent dict.
Single local LLM call; everything else in the pipeline is deterministic.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CMD_DIR, KB_TABLES
import local_llm

# ── Build command list from the opcode table + detailed KB for the prompt ────
# We tell the LLM about every command in the canonical opcode reference
# table (kb/tables/opcodes.json) — not just the ones that have a detailed
# kb/commands/*.json entry — so intent recognition works for the full NVMe
# command set even before someone has run generate_kb_from_docs.py to flesh
# out a particular command's SQ/CQ details. Stage 2 (parameter gate) is what
# actually distinguishes "recognized but no detailed KB yet" from "complete".

def _detailed_command_names() -> set[str]:
    names = set()
    for f in CMD_DIR.glob("**/*.json"):
        try:
            d = json.loads(f.read_text())
            names.add(d.get("meta", {}).get("name", "").lower())
        except Exception:
            pass
    return names


def _available_commands() -> str:
    detailed = _detailed_command_names()
    opcodes = KB_TABLES.get("opcodes", {})

    lines = []
    for group, label in (("admin", "Admin"), ("nvm", "I/O / NVM")):
        group_cmds = opcodes.get(group, {})
        if not group_cmds:
            continue
        lines.append(f"{label} commands:")
        for opcode, info in sorted(group_cmds.items()):
            name = info.get("name", "")
            tag = "" if name.lower() in detailed else "  [recognized, parameters not yet detailed]"
            lines.append(f"  {name} (opcode {opcode}){tag}")

    return "\n".join(lines) if lines else "  (none loaded)"


SYSTEM_PROMPT = """You are an NVMe command intent parser.
Your ONLY job is to extract the user's NVMe command intent and return a single JSON object.
Return ONLY valid JSON — no prose, no markdown fences.

Available commands in the knowledge base:
{available_commands}

Output schema:
{{
  "command":    "<command_name exactly as listed above, or null if unknown>",
  "parameters": {{
    "<param_name>": "<value>"
    // include only parameters explicitly mentioned or strongly implied
  }},
  "confidence": <float 0.0-1.0>,
  "unknown_reason": "<if command is null, why>"
}}

Rules:
- "confidence" reflects how certain you are about the command AND parameters.
- If the user says "identify controller", set command="Identify" and parameters.cns="0x01".
- If the user says "identify namespace 3", set command="Identify", cns="0x00", nsid="0x3".
- If the user says "get features" without a feature ID, set command="Get Features" but leave fid out of parameters and set confidence <= 0.5.
- Normalize hex values to "0x" prefix lowercase (e.g. "0x01", "0xa").
- Never invent parameter values not mentioned or clearly implied by the user.
"""


def parse_intent(user_query: str, verbose: bool = False) -> dict:
    """
    Run the local LLM to parse user_query into a structured intent.
    Returns dict with keys: command, parameters, confidence, unknown_reason (optional).
    Falls back to a null-command intent on any error.
    """
    prompt = SYSTEM_PROMPT.format(available_commands=_available_commands())
    raw = ""

    try:
        if verbose:
            print(f"[intent_parser] query={user_query!r}", file=sys.stderr)

        raw = local_llm.generate_chat(prompt, user_query, temperature=0.1)

        if verbose:
            print(f"[intent_parser] raw response:\n{raw}", file=sys.stderr)

        # Strip accidental markdown fences
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)

        intent = json.loads(raw)

        # Validate minimal shape
        if "command" not in intent or "confidence" not in intent:
            raise ValueError("Missing required keys in LLM response")

        intent.setdefault("parameters", {})
        return intent

    except json.JSONDecodeError as e:
        return {
            "command": None,
            "parameters": {},
            "confidence": 0.0,
            "unknown_reason": f"LLM returned non-JSON output: {e}",
            "_raw": raw,
        }
    except Exception as e:
        return {
            "command": None,
            "parameters": {},
            "confidence": 0.0,
            "unknown_reason": str(e),
        }


if __name__ == "__main__":
    if len(sys.argv) <= 1:
        print("Usage: python3 01_intent_parser.py <natural language NVMe request>", file=sys.stderr)
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    result = parse_intent(query, verbose=True)
    print(json.dumps(result, indent=2))