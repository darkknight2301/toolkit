# """
# 05_assemble_prompt.py
# -----------------------
# Step 5 of the RAG pipeline: take retrieval output (from 03_retrieve.py)
# and build the final prompt to send to the coding LLM -- system rules
# + only the relevant retrieved code + the user's request.

# This is intentionally the "glue" step and has no ML/network dependency.
# You can call it directly after 03_retrieve.py, piping its JSON output in.

# Usage:
#     python3 03_retrieve.py "..." --chunks chunks.json | python3 05_assemble_prompt.py
# """

# import json
# import sys

# SYSTEM_RULES = """You are an assistant for an existing NVMe test framework written in C++.

# Rules:
# - Use ONLY the functions, classes, and signatures shown in the CONTEXT below.
# - Never invent a class, function, helper, or macro that is not shown in CONTEXT.
# - If the requested step cannot be implemented with what's in CONTEXT, say so
#   explicitly and ask for clarification instead of guessing.
# - Generate ONLY the code for the requested step. Do not generate other steps.
# - Match the existing code's naming, formatting, and assertion style.
# """


# def format_chunk(chunk):
#     lines = []
#     header = f"// {chunk['file']}"
#     if chunk.get("namespace"):
#         header += f" | namespace {chunk['namespace']}"
#     if chunk.get("class"):
#         header += f" | class {chunk['class']}"
#     lines.append(header)
#     if chunk.get("doc_comment"):
#         lines.append(f"// {chunk['doc_comment']}")
#     lines.append(chunk["signature"])
#     if chunk.get("body"):
#         lines.append(chunk["body"])
#     else:
#         lines.append("// (declaration only -- no body available in this context)")
#     return "\n".join(lines)


# def main():
#     retrieval_output = json.load(sys.stdin)
#     query = retrieval_output["query"]
#     context_chunks = retrieval_output["context_chunks"]

#     context_text = "\n\n".join(format_chunk(c) for c in context_chunks)

#     prompt = f"""{SYSTEM_RULES}

# CONTEXT (retrieved from the real codebase -- this is the ONLY source of truth):

# {context_text}

# ---

# USER REQUEST:
# {query}
# """
#     print(prompt)


# if __name__ == "__main__":
#     main()


"""
05_assemble_prompt.py
-----------------------
Step 5 of the RAG pipeline: build the final prompt to send to the
coding LLM.

Two modes:

1. SINGLE-SHOT (original behavior) -- one-off code generation with no
   persistent state. Reads retrieval.json from stdin.

       python3 03_retrieve.py "..." --chunks chunks.json | python3 05_assemble_prompt.py

2. INCREMENTAL (new) -- builds a prompt that ALSO includes the current
   state of a persistent test case (existing implementation + completed
   steps), so the model only has to generate the next fragment. Reads
   retrieval.json from stdin same as before, but needs --function and
   --step to pull in workspace state.

       python3 03_retrieve.py "Implement Step 2: ..." --chunks chunks.json \
           | python3 05_assemble_prompt.py --function VerifyIdentifyController \
                 --step 2 --test-case "Verify Identify Controller Command"
"""

import json
import sys
import argparse

import workspace_lib as ws
from prompt_lib import assemble_incremental_prompt, format_chunk

SYSTEM_RULES = """You are an assistant for an existing NVMe test framework written in C++.

Rules:
- Use ONLY the functions, classes, and signatures shown in the CONTEXT below.
- Never invent a class, function, helper, or macro that is not shown in CONTEXT.
- If the requested step cannot be implemented with what's in CONTEXT, say so
  explicitly and ask for clarification instead of guessing.
- Generate ONLY the code for the requested step. Do not generate other steps.
- Match the existing code's naming, formatting, and assertion style.
"""


def assemble_single_shot_prompt(query, context_chunks):
    context_text = "\n\n".join(format_chunk(c) for c in context_chunks)
    return f"""{SYSTEM_RULES}

CONTEXT (retrieved from the real codebase -- this is the ONLY source of truth):

{context_text}

---

USER REQUEST:
{query}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--function", default=None,
                     help="Function name. If set, switches to incremental mode.")
    ap.add_argument("--step", type=int, default=None,
                     help="Step number being requested (incremental mode)")
    ap.add_argument("--test-case", default=None,
                     help="Test case description (used when creating a new workspace)")
    args = ap.parse_args()

    retrieval_output = json.load(sys.stdin)
    query = retrieval_output["query"]
    context_chunks = retrieval_output["context_chunks"]

    if args.function:
        if args.step is None:
            print("--step is required when --function is set.", file=sys.stderr)
            sys.exit(1)

        existing_src = ws.load_or_create_source(args.function, args.test_case)
        meta = ws.load_meta(args.function, args.test_case)

        marker_steps = ws.get_completed_steps_from_markers(existing_src)
        if set(marker_steps) != set(meta["completed_steps"]):
            meta["completed_steps"] = marker_steps
            ws.save_meta(args.function, meta)

        prompt = assemble_incremental_prompt(
            test_case_description=meta["test_case"] or args.test_case or "",
            function_name=args.function,
            step_number=args.step,
            existing_implementation=existing_src,
            completed_steps=meta["completed_steps"],
            context_chunks=context_chunks,
            step_request_text=query,
        )
    else:
        prompt = assemble_single_shot_prompt(query, context_chunks)

    print(prompt)


if __name__ == "__main__":
    main()