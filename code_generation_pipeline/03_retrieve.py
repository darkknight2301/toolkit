"""
03_retrieve.py
--------------
Step 4 of the RAG pipeline: given a plain-English step description,
find the most relevant chunk(s), then pull in directly-connected
chunks (anything they call) so the model isn't handed a function call
it can't see the definition of.

Usage:
    python3 03_retrieve.py "Implement Step 3: power cycle the device" \
        --chunks chunks_ast_output.json --db ./chroma_store --top-k 2

Requires:
    pip install sentence-transformers chromadb --break-system-packages
"""

import json
import sys
import argparse
from pathlib import Path


def load_chunk_lookup(chunks_path):
    chunks = json.loads(Path(chunks_path).read_text())
    by_name = {}
    for c in chunks:
        by_name.setdefault(c["name"], []).append(c)
    return chunks, by_name


def expand_with_call_graph(primary_chunks, by_name, max_depth=1):
    """Given the top retrieved chunks, pull in anything they call that
    also exists as a known chunk (so the model can see real definitions
    instead of guessing what a referenced function does)."""
    seen_ids = set()
    result = []

    def key(c):
        return (c["file"], c.get("class"), c["name"])

    def visit(chunk, depth):
        k = key(chunk)
        if k in seen_ids:
            return
        seen_ids.add(k)
        result.append(chunk)
        if depth >= max_depth:
            return
        for called_name in chunk.get("calls", []):
            for candidate in by_name.get(called_name, []):
                visit(candidate, depth + 1)

    for c in primary_chunks:
        visit(c, 0)

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="The step description / request")
    ap.add_argument("--chunks", required=True, help="Path to chunks JSON from step 01")
    ap.add_argument("--db", default="./chroma_store")
    ap.add_argument("--collection", default="framework_chunks")
    ap.add_argument("--model", default="jinaai/jina-embeddings-v2-base-code")
    ap.add_argument("--top-k", type=int, default=2)
    ap.add_argument("--expand-depth", type=int, default=1,
                     help="How many hops of the call graph to pull in")
    args = ap.parse_args()

    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "Missing dependencies. Install with:\n"
            "  pip install sentence-transformers chromadb --break-system-packages",
            file=sys.stderr,
        )
        sys.exit(1)

    chunks, by_name = load_chunk_lookup(args.chunks)

    model = SentenceTransformer(args.model, trust_remote_code=True)
    query_embedding = model.encode([args.query]).tolist()

    client = chromadb.PersistentClient(path=args.db)
    collection = client.get_or_create_collection(args.collection)

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=args.top_k,
    )

    primary = []
    for meta in results["metadatas"][0]:
        for c in chunks:
            if (c["file"] == meta["file"]
                    and (c.get("class") or "") == meta["class"]
                    and c["name"] == meta["name"]):
                primary.append(c)
                break

    expanded = expand_with_call_graph(primary, by_name, max_depth=args.expand_depth)

    print(json.dumps({
        "query": args.query,
        "primary_matches": [{"file": c["file"], "class": c.get("class"),
                              "name": c["name"]} for c in primary],
        "context_chunks": expanded,
    }, indent=2))


if __name__ == "__main__":
    main()
