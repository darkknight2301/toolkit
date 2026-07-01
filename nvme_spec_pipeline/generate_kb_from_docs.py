"""
generate_kb_from_docs.py

Reads one or more NVMe spec documents (PDF, DOCX, or TXT), extracts their
text, and asks the LLM to draft kb/commands/<name>.json files that conform
to kb/schemas/command_schema.json — i.e. the same shape 02-05 in pipeline/
already expect (meta / required_parameters / parameters / sq / cq_prediction
/ response).

IMPORTANT — read this before trusting the output:
  This is an LLM-assisted DRAFTING tool, not a deterministic parser. The
  rest of the pipeline (stages 2-5) is 100% deterministic and trustworthy
  *because* the KB JSON it reads is assumed correct. This script produces
  a first draft only. Opcode values, bit-field positions, and status-code
  rules are exactly the kind of details an LLM can get subtly wrong (off-
  by-one bit ranges, wrong opcode, invented status codes). Always diff the
  generated file against the spec page it came from before using it for
  real predictions — treat this the same way you'd treat a junior
  engineer's first draft of a register map.

Usage:
    pip install pypdf python-docx transformers torch accelerate

    python3 generate_kb_from_docs.py path/to/spec_chapter5.pdf
    python3 generate_kb_from_docs.py spec1.pdf spec2.docx notes.txt
    python3 generate_kb_from_docs.py spec.pdf --out kb/commands --overwrite
    python3 generate_kb_from_docs.py spec.pdf --pages 200-260   # limit page range (PDF only)

  The model runs locally (no API key needed) and is downloaded once from
  Hugging Face Hub on first use, then cached. Set NVME_HELPER_MODEL in your
  environment to use a different model, or point it at a local model
  directory you already have on disk.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CMD_DIR, SCHEMA_DIR, TABLE_DIR
import local_llm


# ── Text extraction ─────────────────────────────────────────────────────────

def extract_text(path: Path, page_range: tuple[int, int] | None = None) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(path, page_range)
    elif suffix == ".docx":
        return _extract_docx(path)
    elif suffix in (".txt", ".md"):
        return path.read_text(errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {suffix} (use .pdf, .docx, .txt, .md)")


def _extract_pdf(path: Path, page_range: tuple[int, int] | None) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    n_pages = len(reader.pages)

    lo, hi = (0, n_pages - 1)
    if page_range:
        lo, hi = max(0, page_range[0] - 1), min(n_pages - 1, page_range[1] - 1)

    chunks = []
    for i in range(lo, hi + 1):
        try:
            chunks.append(reader.pages[i].extract_text() or "")
        except Exception:
            continue
    return "\n".join(chunks)


def _extract_docx(path: Path) -> str:
    import docx
    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


# ── Chunking ─────────────────────────────────────────────────────────────────
# Spec documents are too large to hand the LLM in one shot, and one call
# works best focused on a single command. We chunk on lines that look like
# NVMe command section headers (e.g. "5.17 Identify command") and feed each
# chunk to the LLM separately. If no headers are found, the whole text is
# sent as a single chunk and the LLM is asked to find as many commands as
# it can within it.

_HEADER_RE = re.compile(
    r"^\s*\d+(?:\.\d+)*\s+([A-Z][A-Za-z0-9 /\-]+?)\s+command\b", re.MULTILINE
)


def chunk_by_command(text: str, max_chars: int = 12000) -> list[str]:
    matches = list(_HEADER_RE.finditer(text))
    if not matches:
        # No recognizable headers — fall back to fixed-size chunks.
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)] or [text]

    chunks = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk = text[start:end]
        if len(chunk) > max_chars:
            chunk = chunk[:max_chars]
        chunks.append(chunk)
    return chunks


# ── LLM extraction call ───────────────────────────────────────────────────────

SCHEMA_PROMPT = """You are an NVMe specification parser. You will be given a chunk of text
extracted from the NVMe Base Specification describing one or more admin or I/O commands.

Extract EVERY distinct NVMe command you can find in this text and return a JSON ARRAY,
one object per command, each conforming EXACTLY to this schema:

{schema}

Rules:
- Output ONLY a JSON array. No prose, no markdown fences, no commentary.
- CRITICAL — "meta.opcode" must be copied VERBATIM from a numeric opcode value
  literally present in the chunk of text below (e.g. text says "Opcode 80h" or
  "0x80" → opcode is "0x80"). NEVER recall an opcode from your own training
  knowledge of NVMe, even if you are confident you know it. If no explicit
  opcode value appears anywhere in the given text, set "opcode" to null and
  set "_uncertain": true with "_uncertain_reason": "no opcode value found in
  the provided text — do not guess". This rule exists because incorrect
  opcodes silently corrupt command predictions; an honest null is far better
  than a remembered-but-wrong guess.
- For all OTHER fields (bit positions, status codes, parameter names): if a
  value is not stated in the text, do not guess wildly — use your best-
  supported inference from the text and add a "_uncertain": true flag at the
  top level of that command's object, plus a "_uncertain_reason" string
  explaining what was unclear.
- CRITICAL — every "bits" array must always have exactly TWO elements: [hi, lo].
  For a single-bit field (e.g. a field that occupies only bit 8), write [8, 8],
  NOT [8]. A one-element bits array will break downstream bit-packing code.
- "required_parameters" should list only parameters the command cannot function without.
- "cq_prediction.status_rules" should include at least a "Successful Completion" rule
  (SCT=0x0, SC=0x00) plus any error conditions explicitly described in the text.
- If the text describes a response data structure, include its fields with offset_bytes
  and size_bytes in "response.fields" (flat) or "response.per_cns" (if the structure
  varies by a selector field like CNS — group by the selector's hex value as key).
- If NO command definitions are found in this chunk, return an empty array: []
- command names in "meta.name" should be Title Case (e.g. "Get Log Page", "Set Features").
"""


def call_llm(chunk: str, schema_text: str, verbose: bool = False) -> list[dict]:
    system_prompt = SCHEMA_PROMPT.format(schema=schema_text)

    if verbose:
        print(f"[generate_kb] chunk sent to LLM ({len(chunk)} chars):", file=sys.stderr)
        print(chunk[:2000], file=sys.stderr)
        print("--- end of chunk ---", file=sys.stderr)

    raw = local_llm.generate_chat(system_prompt, chunk, max_new_tokens=4000, temperature=0.0)

    if verbose:
        print(f"[generate_kb] raw LLM output ({len(raw)} chars):", file=sys.stderr)
        print(raw[:2000], file=sys.stderr)

    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e}\n--- raw output ---\n{raw[:500]}")

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON array of commands, got {type(parsed)}")

    # Defensive unwrap: if a command object got wrapped as {"command": {...}}
    # (an LLM habit from seeing similarly-named schema docs elsewhere), unwrap
    # it rather than failing structural validation outright.
    unwrapped = []
    for cmd in parsed:
        if isinstance(cmd, dict) and set(cmd.keys()) == {"command"} and isinstance(cmd["command"], dict):
            unwrapped.append(cmd["command"])
        else:
            unwrapped.append(cmd)

    return unwrapped


# ── Structural validation (not spec-correctness validation) ─────────────────
# This checks the shape matches what pipeline stages 2-5 require to run
# without crashing. It does NOT and CANNOT verify the values are spec-correct.

REQUIRED_TOP_KEYS = ["meta", "required_parameters", "parameters", "sq", "cq_prediction"]
REQUIRED_META_KEYS = ["name", "opcode", "queue"]


def validate_structure(cmd: dict) -> list[str]:
    problems = []
    for k in REQUIRED_TOP_KEYS:
        if k not in cmd:
            problems.append(f"missing top-level key '{k}'")

    meta = cmd.get("meta", {})
    for k in REQUIRED_META_KEYS:
        if k not in meta:
            problems.append(f"missing meta.{k}")
    if not meta.get("opcode"):
        problems.append(
            "meta.opcode is null/empty — the LLM could not find an explicit opcode "
            "value in the provided text (this is the expected, honest outcome when "
            "the chunk doesn't contain it; re-check the page range against the spec "
            "rather than guessing the opcode)"
        )

    cq = cmd.get("cq_prediction", {})
    rules = cq.get("status_rules", [])
    if not rules:
        problems.append("cq_prediction.status_rules is empty")
    elif not any(r.get("SC") == "0x00" and r.get("SCT") == "0x0" for r in rules):
        problems.append("no Successful Completion (SCT=0x0,SC=0x00) rule in status_rules")

    # NSID is ALWAYS CDW1 in every NVMe command and is auto-resolved by
    # 03_sq_builder.py directly from the "nsid" parameter — it must never
    # be defined as a per-command parameter mapped into CDW10+. This is a
    # recurring LLM extraction mistake (it borrows field names/positions
    # from other commands it has seen, e.g. mapping NSID onto CDW10 the
    # way Identify maps CNS onto CDW10), so we check for it explicitly.
    params = cmd.get("parameters", {})
    for pname, pdef in params.items():
        if pname.strip().lower() in ("nsid", "namespace_id", "namespace identifier"):
            cdw = (pdef or {}).get("cdw", "") if isinstance(pdef, dict) else ""
            if cdw.strip().upper() != "CDW1":
                problems.append(
                    f"parameter '{pname}' looks like NSID but is mapped to cdw={cdw or '?'} "
                    f"instead of CDW1 — NSID is always CDW1 in every NVMe command. Either "
                    f"set this parameter's \"cdw\" to \"CDW1\", or remove the entry entirely "
                    f"and just list 'nsid' in required_parameters/optional_parameters "
                    f"(03_sq_builder.py auto-builds CDW1 from the resolved 'nsid' value either way)."
                )

    # Every "bits" array in sq.CDW10-CDW15 field definitions must be a
    # 2-element [hi, lo] pair — a 1-element list (meant as a single-bit
    # shorthand) crashes 03_sq_builder.py's bit-packing logic.
    sq = cmd.get("sq", {})
    for cdw_name, cdw_def in sq.items():
        if not isinstance(cdw_def, dict):
            continue
        for field_name, field_def in cdw_def.items():
            if field_name.startswith("_") or not isinstance(field_def, dict):
                continue
            bits = field_def.get("bits")
            if isinstance(bits, list) and len(bits) != 2:
                problems.append(
                    f"sq.{cdw_name}.{field_name}.bits = {bits} must be a 2-element "
                    f"[hi, lo] pair (use [{bits[0]}, {bits[0]}] for a single-bit field)."
                    if bits else
                    f"sq.{cdw_name}.{field_name}.bits is empty/invalid"
                )

    return problems


def check_opcode_against_table(cmd: dict, opcode_table: dict) -> str | None:
    """
    Cross-check the LLM-extracted opcode/queue against kb/tables/opcodes.json.
    Returns a warning string if they disagree, or None if consistent
    (or if the command isn't in the table at all, which isn't itself an error —
    the table may simply be incomplete).
    """
    meta = cmd.get("meta", {})
    name = meta.get("name", "").strip().lower()
    opc  = (meta.get("opcode") or "").strip().lower()
    queue = meta.get("queue", "").strip().lower()
    group = "admin" if queue == "admin" else "nvm"

    if not opc:
        return None  # no opcode to check — validate_structure() already flags this

    table_entry = opcode_table.get(group, {}).get(opc.replace("0x", "0x").upper().replace("0X", "0x"))
    # normalise case for lookup since opcodes.json keys are like "0x06"
    table_entry = None
    for k, v in opcode_table.get(group, {}).items():
        if k.lower() == opc.lower():
            table_entry = v
            break

    if table_entry is None:
        return None  # not in our reference table — not necessarily wrong

    if table_entry.get("name", "").strip().lower() != name:
        return (f"opcode {opc} in the {group} table is '{table_entry.get('name')}', "
                f"but extracted command is named '{meta.get('name')}' — verify against spec.")
    return None


# ── Main driver ──────────────────────────────────────────────────────────────

def generate(paths: list[Path], out_dir: Path, overwrite: bool,
             page_range: tuple[int, int] | None, verbose: bool, dry_run: bool,
             allow_opcode_mismatch: bool = False) -> None:
    schema_text = (SCHEMA_DIR / "command_schema.json").read_text()
    opcode_table = json.loads((TABLE_DIR / "opcodes.json").read_text()) if (TABLE_DIR / "opcodes.json").exists() else {}

    written, skipped, uncertain, failed, opcode_warnings = [], [], [], [], []

    for path in paths:
        print(f"\n=== Reading {path} ===")
        text = extract_text(path, page_range)
        if not text.strip():
            print(f"  ! No extractable text found in {path}, skipping.")
            continue

        chunks = chunk_by_command(text)
        print(f"  Found {len(chunks)} chunk(s) to process.")

        for i, chunk in enumerate(chunks, 1):
            print(f"  [{i}/{len(chunks)}] Sending chunk to LLM ({len(chunk)} chars)...")
            try:
                commands = call_llm(chunk, schema_text, verbose=verbose)
            except Exception as e:
                print(f"    ✗ LLM call failed: {e}")
                failed.append(f"{path} chunk {i}: {e}")
                continue

            if not commands:
                print(f"    (no commands found in this chunk)")
                continue

            for cmd in commands:
                name = cmd.get("meta", {}).get("name", "").strip()
                if not name:
                    print(f"    ✗ Skipping command with no meta.name")
                    failed.append(f"{path} chunk {i}: command with no name")
                    continue

                problems = validate_structure(cmd)

                # ── Cross-check opcode against the canonical reference table ──
                # A mismatch here means the LLM extracted a command name that
                # doesn't match what kb/tables/opcodes.json says that opcode
                # actually is — this is a strong signal of a hallucinated or
                # misattributed opcode, so it blocks the write by default.
                opcode_warning = check_opcode_against_table(cmd, opcode_table)
                if opcode_warning:
                    opcode_warnings.append(f"{name}: {opcode_warning}")
                    if allow_opcode_mismatch:
                        print(f"    ⚠ {name}: opcode mismatch (allowed via --allow-opcode-mismatch) — {opcode_warning}")
                    else:
                        print(f"    ✗ {name}: opcode mismatch — {opcode_warning}")
                        print(f"      Not writing. Re-run with --allow-opcode-mismatch to write anyway,")
                        print(f"      or fix the source spec text/page range and retry.")
                        failed.append(f"{name}: opcode mismatch — {opcode_warning}")
                        continue

                # ── Choose admin/ or io/ subfolder based on meta.queue ─────────
                queue = cmd.get("meta", {}).get("queue", "").strip().lower()
                subfolder = "admin" if queue == "admin" else "io"
                target_dir = out_dir / subfolder
                target_dir.mkdir(parents=True, exist_ok=True)

                fname = name.lower().replace(" ", "_").replace("/", "_") + ".json"
                out_path = target_dir / fname

                if cmd.pop("_uncertain", False):
                    reason = cmd.pop("_uncertain_reason", "no reason given")
                    uncertain.append(f"{name} ({subfolder}/{fname}): {reason}")
                    print(f"    ⚠ {name}: LLM flagged this as UNCERTAIN — {reason}")
                else:
                    cmd.pop("_uncertain_reason", None)

                if problems:
                    print(f"    ✗ {name}: structural validation failed: {problems}")
                    failed.append(f"{name}: {problems}")
                    continue

                if out_path.exists() and not overwrite:
                    print(f"    - {name}: {subfolder}/{fname} already exists, skipping (use --overwrite to replace)")
                    skipped.append(f"{subfolder}/{fname}")
                    continue

                if dry_run:
                    print(f"    ✓ {name}: would write {subfolder}/{fname} (dry run, not written)")
                else:
                    out_path.write_text(json.dumps(cmd, indent=2))
                    print(f"    ✓ {name}: wrote {out_path}")
                    written.append(f"{subfolder}/{fname}")

    print("\n=== Summary ===")
    print(f"  Written:   {written or '(none)'}")
    print(f"  Skipped (already existed): {skipped or '(none)'}")
    print(f"  Uncertain (review these!):  {uncertain or '(none)'}")
    print(f"  Opcode table mismatches (review these!): {opcode_warnings or '(none)'}")
    print(f"  Failed:    {failed or '(none)'}")
    if written:
        print(f"\nReminder: these are LLM drafts. Spot-check opcodes, bit ranges, and "
              f"status codes in {out_dir}/ against the source spec before relying on them.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="Path(s) to PDF/DOCX/TXT spec documents")
    ap.add_argument("--out", default=str(CMD_DIR), help="Output directory (default: kb/commands)")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing KB files")
    ap.add_argument("--pages", help="Page range for PDFs, e.g. 200-260 (1-indexed, inclusive)")
    ap.add_argument("--verbose", action="store_true", help="Print raw LLM output for debugging")
    ap.add_argument("--dry-run", action="store_true", help="Don't write files, just show what would happen")
    ap.add_argument("--allow-opcode-mismatch", action="store_true",
                     help="Write files even if the extracted opcode disagrees with kb/tables/opcodes.json "
                          "(by default this blocks the write, since it usually means a misattributed/hallucinated opcode)")
    args = ap.parse_args()

    page_range = None
    if args.pages:
        lo, hi = args.pages.split("-")
        page_range = (int(lo), int(hi))

    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.exists():
            print(f"File not found: {p}", file=sys.stderr)
            sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    generate(paths, out_dir, args.overwrite, page_range, args.verbose, args.dry_run,
             allow_opcode_mismatch=args.allow_opcode_mismatch)