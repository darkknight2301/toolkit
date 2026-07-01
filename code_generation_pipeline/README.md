# RAG Pipeline for the NVMe Test Framework

Five scripts, run in order. Steps 1 and 4 need nothing but Python.
Steps 2 and 3 need the embedding model, which requires Hugging Face
access (not available in this sandbox -- run those two on your own
machine with internet access).

## Setup
```
pip install -r requirements.txt --break-system-packages
```

## 1. Extract chunks from your .hpp/.cpp files
```
python3 01_extract_chunks.py file1.hpp file2.hpp ... fileN.cpp > chunks.json
```
Run this once, and re-run it whenever the codebase changes (cheap, no
network needed).

## 2. Build the embedding index
```
python3 02_build_index.py chunks.json --db ./chroma_store
```
First run downloads the embedding model (a few hundred MB) -- needs
internet access. Re-run whenever chunks.json changes.

## 3. Retrieve relevant context for a step request
```
python3 03_retrieve.py "Implement Step 3: power cycle the device" \
    --chunks chunks.json --db ./chroma_store --top-k 2 > retrieval.json
```

## 4. Assemble the prompt to send to the coding LLM
```
cat retrieval.json | python3 05_assemble_prompt.py > final_prompt.txt
```
Send final_prompt.txt's contents to your LLM of choice.

## 5. Validate the LLM's generated code before trusting it
```
python3 04_validate_output.py generated_code.cpp --chunks chunks.json
```
Exits non-zero and lists any identifier not found in your real
codebase -- a strong signal of hallucination.

## Notes
- sample_chunks_output.json is the real extracted output from your
  5 uploaded files, included so you can see the expected shape and
  test steps 3-5 once you've built the index.
- Known limitations of the extractor: it's a real AST parser
  (tree-sitter), so it correctly handles multi-line signatures and
  constructor initializer lists, but it doesn't resolve macros or
  templates deeply. If your other 3 files use heavy macros, spot-check
  their output.
