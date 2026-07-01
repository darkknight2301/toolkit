# """
# 06_generate_code.py
# ---------------------
# Step 6 (generation) of the pipeline. Reads the prompt assembled by
# 05_assemble_prompt.py and sends it to Qwen2.5-Coder-7B-Instruct via the
# Hugging Face Inference API. Saves the extracted code to a file so
# 04_validate_output.py can check it automatically right after.

# Setup:
#     pip install huggingface_hub python-dotenv --break-system-packages

# Create a .env file in the same folder with:
#     HF_KEY=your_hugging_face_token_here

# Usage:
#     python3 05_assemble_prompt.py < retrieval.json > final_prompt.txt
#     python3 06_generate_code.py final_prompt.txt --output generated_step2.cpp
#     python3 04_validate_output.py generated_step2.cpp --chunks chunks.json
# """

# import os
# import re
# import sys
# import argparse
# from pathlib import Path

# from dotenv import load_dotenv
# from huggingface_hub import InferenceClient

# load_dotenv()

# MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"

# # Minimal system message -- the bulk of the rules already live inside the
# # assembled prompt itself (see 05_assemble_prompt.py's SYSTEM_RULES), so
# # this just reinforces the most important constraint at the API level.
# CODER_SYSTEM = (
#     "You are a careful C++ assistant for an existing framework. "
#     "Only use functions/classes shown in the prompt's CONTEXT section. "
#     "Never invent APIs. If something is missing, say so instead of guessing."
# )


# def extract_code_block(raw_text):
#     """If the model wrapped its answer in a ```cpp ... ``` fence, pull just
#     the code out. Otherwise return the raw text as-is."""
#     match = re.search(r"```(?:cpp|c\+\+)?\s*\n(.*?)```", raw_text, re.DOTALL)
#     if match:
#         return match.group(1).strip()
#     return raw_text.strip()


# def main():
#     ap = argparse.ArgumentParser()
#     ap.add_argument("prompt_file", help="Path to final_prompt.txt from step 05")
#     ap.add_argument("--output", default="generated_code.cpp",
#                      help="Where to save the extracted C++ code")
#     ap.add_argument("--raw-output", default=None,
#                      help="Optional: also save the model's full raw response "
#                           "(including any explanation text) to this path")
#     args = ap.parse_args()

#     hf_key = os.getenv("HF_KEY")
#     if not hf_key:
#         raise ValueError("API Key not found. Set HF_KEY in your .env file.")

#     client = InferenceClient(api_key=hf_key)

#     prompt_text = Path(args.prompt_file).read_text()

#     print(f"Sending prompt to {MODEL} ...")
#     completion = client.chat.completions.create(
#         model=MODEL,
#         temperature=0.0,
#         max_tokens=4000,
#         seed=42,
#         messages=[
#             {"role": "system", "content": CODER_SYSTEM},
#             {"role": "user", "content": prompt_text},
#         ],
#     )
#     raw = completion.choices[0].message.content

#     if args.raw_output:
#         Path(args.raw_output).write_text(raw)
#         print(f"Full raw response saved to {args.raw_output}")

#     code = extract_code_block(raw)
#     Path(args.output).write_text(code)
#     print(f"Extracted code saved to {args.output}")
#     print("\n--- Generated code preview ---")
#     print(code[:800])
#     print("\nNext: python3 04_validate_output.py "
#           f"{args.output} --chunks chunks.json")


# if __name__ == "__main__":
#     main()


"""
06_generate_code.py
---------------------
Step 6 of the pipeline: send the assembled prompt to Qwen2.5-Coder-7B-Instruct
and handle the result.

Two modes:

1. SINGLE-SHOT (original behavior) -- save the model's output to a plain
   file. Use this when --function is not given.

       python3 06_generate_code.py final_prompt.txt --output generated_code.cpp

2. INCREMENTAL (new) -- insert ONLY the generated fragment into the
   persistent workspace file for that function/step, and update its
   metadata. This is the mode the new persistent pipeline uses.

       python3 06_generate_code.py final_prompt.txt --function VerifyIdentifyController --step 2

   Add --overwrite-step if you intentionally want to regenerate a step
   that's already been completed (every other step stays untouched).

Setup:
    pip install huggingface_hub python-dotenv --break-system-packages
    .env file with: HF_KEY=your_hugging_face_token_here
"""

import os
import re
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

import workspace_lib as ws

load_dotenv()

MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"

CODER_SYSTEM = (
    "You are a careful C++ assistant for an existing framework. "
    "Only use functions/classes shown in the prompt's CONTEXT section. "
    "Never invent APIs. If something is missing, say so instead of guessing. "
    "When asked for a single step's fragment, output ONLY that fragment -- "
    "no function signature, no braces, no previous steps, no markdown "
    "explanation outside the code."
)


def extract_code_block(raw_text):
    match = re.search(r"```(?:cpp|c\+\+)?\s*\n(.*?)```", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw_text.strip()


def call_model(prompt_text):
    hf_key = os.getenv("HF_KEY")
    if not hf_key:
        raise ValueError("API Key not found. Set HF_KEY in your .env file.")

    client = InferenceClient(api_key=hf_key)

    print(f"Sending prompt to {MODEL} ...")
    completion = client.chat.completions.create(
        model=MODEL,
        temperature=0.0,
        max_tokens=4000,
        seed=42,
        messages=[
            {"role": "system", "content": CODER_SYSTEM},
            {"role": "user", "content": prompt_text},
        ],
    )
    return completion.choices[0].message.content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_file", help="Path to the prompt from 05_assemble_prompt.py")
    ap.add_argument("--output", default="generated_code.cpp",
                     help="(single-shot mode) Where to save the extracted code")
    ap.add_argument("--raw-output", default=None,
                     help="Optional: also save the model's full raw response")
    ap.add_argument("--function", default=None,
                     help="Function name -- switches to incremental mode")
    ap.add_argument("--step", type=int, default=None,
                     help="Step number being generated (incremental mode)")
    ap.add_argument("--test-case", default=None,
                     help="Test case description, used if creating a new workspace")
    ap.add_argument("--overwrite-step", action="store_true",
                     help="Allow regenerating a step that already exists")
    args = ap.parse_args()

    prompt_text = Path(args.prompt_file).read_text()
    raw = call_model(prompt_text)

    if args.raw_output:
        Path(args.raw_output).write_text(raw)
        print(f"Full raw response saved to {args.raw_output}")

    fragment = extract_code_block(raw)

    if args.function:
        if args.step is None:
            print("--step is required when --function is set.", file=sys.stderr)
            sys.exit(1)

        cpp_path, meta_path = ws.paths_for(args.function)
        existing_src = ws.load_or_create_source(args.function, args.test_case)
        meta = ws.load_meta(args.function, args.test_case)

        try:
            new_src = ws.insert_step_fragment(
                existing_src, args.step, fragment, overwrite=args.overwrite_step
            )
        except ValueError as e:
            print(f"Not inserted: {e}", file=sys.stderr)
            print("Pass --overwrite-step if this is intentional.", file=sys.stderr)
            sys.exit(1)

        cpp_path.write_text(new_src)
        meta = ws.update_completed_steps(meta, args.step)
        ws.save_meta(args.function, meta)

        print(f"Step {args.step} inserted into {cpp_path}")
        print(f"Completed steps so far: {meta['completed_steps']}")
        print("\n--- Updated file ---")
        print(new_src)
        print(f"\nNext: python3 04_validate_output.py {cpp_path} --chunks chunks.json")
    else:
        code = fragment
        Path(args.output).write_text(code)
        print(f"Extracted code saved to {args.output}")
        print("\n--- Generated code preview ---")
        print(code[:800])
        print(f"\nNext: python3 04_validate_output.py {args.output} --chunks chunks.json")


if __name__ == "__main__":
    main()