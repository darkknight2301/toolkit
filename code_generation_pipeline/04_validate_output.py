"""
04_validate_output.py
----------------------
Step 6 of the RAG pipeline: after the LLM generates code for a step,
check every identifier it used against the real, known symbol list
built from your actual codebase (Step 1's output). Flags anything that
looks invented.

This needs no embeddings, no model, no network. It's a pure text/AST
check, which is why it's cheap and worth running on every generation.

Usage:
    python3 04_validate_output.py generated_code.cpp --chunks chunks_ast_output.json
"""

import json
import re
import sys
import argparse
from pathlib import Path

# Identifiers that are part of the language/standard library, not your
# framework -- don't flag these as "unknown".
KNOWN_SAFE = {
    "if", "for", "while", "switch", "return", "sizeof",
    "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast",
    "cout", "endl", "memset", "memcpy", "this_thread", "sleep_for",
    "string", "vector", "regex", "regex_search", "chrono", "milliseconds",
    "EXPECT_EQ", "EXPECT_TRUE", "EXPECT_FALSE", "ASSERT_EQ", "ASSERT_TRUE",
    "ASSERT_FALSE", "printf", "assert",
}

CALL_RE = re.compile(r'\b([A-Za-z_]\w*)\s*\(')


def build_whitelist(chunks):
    """Every function/method/class name that actually exists, plus
    their classes (so Class::method-style or Class() constructions are
    recognized too)."""
    whitelist = set()
    for c in chunks:
        whitelist.add(c["name"])
        if c.get("class"):
            whitelist.add(c["class"])
        if c.get("parent_class"):
            whitelist.add(c["parent_class"])
    return whitelist


def find_referenced_identifiers(code_text):
    found = set()
    for m in CALL_RE.finditer(code_text):
        found.add(m.group(1))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("generated_code_file", help="File containing the LLM's generated code")
    ap.add_argument("--chunks", required=True, help="Path to chunks JSON from step 01")
    args = ap.parse_args()

    chunks = json.loads(Path(args.chunks).read_text())
    whitelist = build_whitelist(chunks)

    code_text = Path(args.generated_code_file).read_text()
    referenced = find_referenced_identifiers(code_text)

    unknown = sorted(
        name for name in referenced
        if name not in whitelist and name not in KNOWN_SAFE
    )

    if unknown:
        print("POTENTIAL HALLUCINATION -- these identifiers are not in the known codebase:")
        for name in unknown:
            print(f"  - {name}")
        print(
            "\nThis doesn't necessarily mean the code is wrong (could be a local "
            "variable name, a std:: function not in the safe-list, etc.) -- "
            "but every name above should be manually checked before trusting "
            "this generation."
        )
        sys.exit(1)
    else:
        print("All referenced identifiers match known framework symbols. No red flags.")
        sys.exit(0)


if __name__ == "__main__":
    main()
