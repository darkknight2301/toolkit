"""
workspace_lib.py
------------------
Shared logic for managing persistent, incrementally-built test case files
under generated_tests/. Used by 05_assemble_prompt.py and 06_generate_code.py.

Each test case = one .cpp file + one .meta.json file, keyed by function name.
Steps are inserted as marked blocks inside the function body so progress can
be recovered either from meta.json OR by re-parsing the markers directly
(the spec's "alternatively, infer from annotated markers" fallback).
"""

import json
import re
from pathlib import Path

WORKSPACE_DIR = Path("generated_tests")

STEP_MARKER_START = "// ---- Step {n} ----"
STEP_MARKER_END = "// ---- End Step {n} ----"
STEP_BLOCK_RE = re.compile(
    r'[ \t]*// ---- Step (\d+) ----\n(.*?)\n[ \t]*// ---- End Step \1 ----',
    re.DOTALL
)


def paths_for(function_name):
    WORKSPACE_DIR.mkdir(exist_ok=True)
    cpp_path = WORKSPACE_DIR / f"{function_name}.cpp"
    meta_path = WORKSPACE_DIR / f"{function_name}.meta.json"
    return cpp_path, meta_path


def load_meta(function_name, test_case_description=None):
    _, meta_path = paths_for(function_name)
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {
        "function": function_name,
        "test_case": test_case_description or "",
        "completed_steps": [],
    }


def save_meta(function_name, meta):
    _, meta_path = paths_for(function_name)
    meta_path.write_text(json.dumps(meta, indent=2))


def load_or_create_source(function_name, test_case_description=None):
    """Returns the current .cpp text. Creates a fresh skeleton if the
    file doesn't exist yet."""
    cpp_path, _ = paths_for(function_name)
    if cpp_path.exists():
        return cpp_path.read_text()

    skeleton = (
        f"// Test Case: {test_case_description or '(not specified)'}\n"
        f"// Function: {function_name}\n\n"
        f"void {function_name}()\n"
        f"{{\n"
        f"}}\n"
    )
    cpp_path.write_text(skeleton)
    return skeleton


def get_completed_steps_from_markers(cpp_text):
    """Fallback / cross-check: parse step numbers directly from the
    markers actually present in the file, independent of meta.json."""
    return sorted(int(n) for n, _ in STEP_BLOCK_RE.findall(cpp_text))


def get_step_fragment_text(cpp_text, step_number):
    """Return the existing fragment text for a step, or None."""
    for n, body in STEP_BLOCK_RE.findall(cpp_text):
        if int(n) == step_number:
            return body
    return None


def find_matching_brace(text, open_index):
    """Given the index of an opening '{', return the index of its
    matching closing '}'."""
    depth = 0
    i = open_index
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("No matching closing brace found -- file may be malformed.")


def insert_step_fragment(cpp_text, step_number, fragment, overwrite=False):
    """
    Inserts `fragment` as a marked block for `step_number` into the
    function body, just before its closing brace. If that step's marker
    already exists:
      - overwrite=False -> raises ValueError (caller should warn/skip)
      - overwrite=True  -> replaces just that step's block in place,
                            leaving every other step untouched
    """
    existing = get_step_fragment_text(cpp_text, step_number)

    indented_fragment = "\n".join(
        ("    " + line if line.strip() else line)
        for line in fragment.strip().split("\n")
    )
    block = (
        f"    {STEP_MARKER_START.format(n=step_number)}\n"
        f"{indented_fragment}\n"
        f"    {STEP_MARKER_END.format(n=step_number)}"
    )

    if existing is not None:
        if not overwrite:
            raise ValueError(
                f"Step {step_number} already exists. Pass overwrite=True "
                f"to regenerate it -- existing steps are otherwise never "
                f"touched."
            )
        # Replace just that one block, leave all others untouched
        pattern = re.compile(
            r'\s*[ \t]*// ---- Step ' + str(step_number) + r' ----\n.*?'
            r'[ \t]*// ---- End Step ' + str(step_number) + r' ----'
        , re.DOTALL)
        new_text = pattern.sub("\n" + block, cpp_text)
        return new_text

    # First open brace in the file is assumed to be the function's
    # opening brace (skeleton format guarantees this).
    open_idx = cpp_text.index("{")
    close_idx = find_matching_brace(cpp_text, open_idx)

    before_close = cpp_text[:close_idx].rstrip("\n ")
    after_close = cpp_text[close_idx:]  # starts with the closing '}'

    # Add a blank line before the new block if there's already content
    # inside the function body.
    body_so_far = cpp_text[open_idx + 1:close_idx].strip()
    separator = "\n\n" if body_so_far else "\n"

    new_text = before_close + separator + block + "\n" + after_close
    return new_text


def update_completed_steps(meta, step_number):
    if step_number not in meta["completed_steps"]:
        meta["completed_steps"].append(step_number)
        meta["completed_steps"].sort()
    return meta