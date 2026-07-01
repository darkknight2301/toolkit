"""
prompt_lib.py
--------------
Shared prompt construction. Used by both the original single-shot mode
(05_assemble_prompt.py CLI) and the new incremental mode
(06_generate_code.py).
"""

INCREMENTAL_SYSTEM_RULES = """You are an assistant helping incrementally build a single C++ test
function, one step at a time, across multiple separate requests.

Rules:
- Use ONLY the functions, classes, and signatures shown in CONTEXT below.
- Never invent a class, function, helper, or macro not shown in CONTEXT.
- Look at EXISTING IMPLEMENTATION to see what variables/objects already
  exist from previous steps. Reuse them -- do not redeclare or recreate
  anything already present.
- Output ONLY the code fragment for the CURRENTLY REQUESTED STEP.
  Do not repeat previous steps. Do not output the function signature,
  braces, includes, or any step other than the one requested.
- Do not wrap the fragment in commentary -- just the C++ statements for
  this one step, ready to insert as-is.
- If the requested step cannot be implemented with what's in CONTEXT,
  say so explicitly instead of guessing.
"""


def format_chunk(chunk):
    lines = []
    header = f"// {chunk['file']}"
    if chunk.get("namespace"):
        header += f" | namespace {chunk['namespace']}"
    if chunk.get("class"):
        header += f" | class {chunk['class']}"
    lines.append(header)
    if chunk.get("doc_comment"):
        lines.append(f"// {chunk['doc_comment']}")
    lines.append(chunk["signature"])
    if chunk.get("body"):
        lines.append(chunk["body"])
    else:
        lines.append("// (declaration only -- no body available in this context)")
    return "\n".join(lines)


def assemble_incremental_prompt(
    test_case_description,
    function_name,
    step_number,
    existing_implementation,
    completed_steps,
    context_chunks,
    step_request_text=None,
):
    context_text = "\n\n".join(format_chunk(c) for c in context_chunks)
    completed_str = ", ".join(str(s) for s in completed_steps) if completed_steps else "none yet"

    prompt = f"""{INCREMENTAL_SYSTEM_RULES}

TEST CASE: {test_case_description}
FUNCTION: {function_name}
STEPS COMPLETED SO FAR: {completed_str}
CURRENTLY REQUESTED STEP: {step_number}

EXISTING IMPLEMENTATION (do not regenerate any of this -- reuse its
variables/objects where relevant):

```cpp
{existing_implementation}
```

CONTEXT (retrieved from the real codebase -- this is the ONLY source of truth):

{context_text}

---

USER REQUEST:
{step_request_text or f"Implement Step {step_number}"}
"""
    return prompt