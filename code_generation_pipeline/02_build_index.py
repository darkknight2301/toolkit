"""
02_build_index.py
------------------
Step 2 + 3 of the RAG pipeline: turn each extracted chunk into an
embedding ("fingerprint") and store it in a local vector database
(ChromaDB) for fast similarity search later.

Usage:
    python3 02_build_index.py chunks_ast_output.json --db ./chroma_store

Notes on model choice:
- jinaai/jina-embeddings-v2-base-code is trained for *asymmetric*
  text-to-code retrieval, meaning a plain-English query and a code
  passage can be embedded with the SAME model and still compared
  directly. That's why this script uses ONE model for both chunks and
  queries by default, rather than the two-model split (code model +
  nomic text model) mentioned earlier.
- If you want the two-model split instead (e.g. because you also want
  to search over plain-English doc comments / design notes as a
  separate collection), run this script twice with --collection set to
  different names and --model set to the nomic model for the docs pass.
  Do NOT mix vectors from two different models in the same collection
  search -- their number-spaces aren't compatible and "similarity"
  between them is meaningless.

Requires (only needed on the machine that actually runs indexing):
    pip install sentence-transformers chromadb --break-system-packages
"""

import json
import sys
import argparse
from pathlib import Path


def build_chunk_text(chunk):
    """Construct the text that actually gets embedded for a chunk.
    Signature + doc comment + body gives the embedding model the most
    context to match against natural-language step descriptions."""
    parts = []
    if chunk.get("namespace"):
        parts.append(f"namespace: {chunk['namespace']}")
    if chunk.get("class"):
        parts.append(f"class: {chunk['class']}")
    parts.append(f"signature: {chunk['signature']}")
    if chunk.get("doc_comment"):
        parts.append(f"description: {chunk['doc_comment']}")
    if chunk.get("body"):
        parts.append(f"implementation:\n{chunk['body']}")
    return "\n".join(parts)


def chunk_id(chunk, idx):
    cls = chunk.get("class") or "_"
    return f"{chunk['file']}::{cls}::{chunk['name']}::{idx}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chunks_json", help="Path to chunks JSON from step 01")
    ap.add_argument("--db", default="./chroma_store", help="Vector DB storage dir")
    ap.add_argument("--collection", default="framework_chunks")
    ap.add_argument(
        "--model",
        default="jinaai/jina-embeddings-v2-base-code",
        help="Embedding model. Use the same model for indexing and querying.",
    )
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

    chunks = json.loads(Path(args.chunks_json).read_text())

    # Skip chunks with no real body/signature content worth embedding
    # (e.g. a bare forward declaration with nothing else useful).
    indexable = [c for c in chunks if c.get("signature")]

    print(f"Loading embedding model: {args.model} (first run downloads weights)")
    model = SentenceTransformer(args.model, trust_remote_code=True)

    texts = [build_chunk_text(c) for c in indexable]
    print(f"Embedding {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=True).tolist()

    client = chromadb.PersistentClient(path=args.db)
    collection = client.get_or_create_collection(args.collection)

    ids = [chunk_id(c, i) for i, c in enumerate(indexable)]
    metadatas = []
    for c in indexable:
        metadatas.append({
            "file": c["file"],
            "namespace": c.get("namespace") or "",
            "class": c.get("class") or "",
            "name": c["name"],
            "kind": c["kind"],
            "signature": c["signature"][:500],  # metadata fields have size limits
        })

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    print(f"Indexed {len(indexable)} chunks into '{args.collection}' at {args.db}")


if __name__ == "__main__":
    main()
