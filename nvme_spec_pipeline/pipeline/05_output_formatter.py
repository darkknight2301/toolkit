"""
pipeline/05_output_formatter.py

Stage 5: Output Formatter

Combines SQ, CQ, and response results into:
  - Human-readable terminal output (coloured where supported)
  - Machine-readable JSON block

Mode controlled by config.DEFAULT_OUTPUT_MODE:
  "both"  → human + JSON
  "json"  → JSON only
  "human" → human only
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEFAULT_OUTPUT_MODE

# ── ANSI colour helpers ────────────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty() and os.name != "nt"

def _c(text, code):  return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text
def bold(t):         return _c(t, "1")
def green(t):        return _c(t, "32")
def yellow(t):       return _c(t, "33")
def red(t):          return _c(t, "31")
def cyan(t):         return _c(t, "36")
def grey(t):         return _c(t, "90")
def header(t):       return bold(_c(t, "34"))


def format_output(
    intent:      dict,
    gate_result: dict,
    sq_result:   dict,
    cq_result:   dict,
    mode:        str | None = None
) -> str:
    """
    Produce formatted output string.
    mode overrides config default if provided.
    """
    mode = mode or DEFAULT_OUTPUT_MODE

    parts = []

    if mode in ("human", "both"):
        parts.append(_human_output(intent, gate_result, sq_result, cq_result))

    if mode in ("json", "both"):
        parts.append(_json_output(intent, gate_result, sq_result, cq_result))

    return "\n\n".join(parts)


def format_clarification(intent: dict, gate_result: dict) -> str:
    """Format a clarification request (missing required parameters)."""
    lines = [
        header("── NVMe Helper — Clarification Needed ──────────────────"),
        f"  Command: {bold(gate_result['kb']['meta']['name'])}",
        f"  Intent:  {intent.get('raw_intent', intent.get('command', ''))}",
        ""
    ]
    for item in gate_result["missing"]:
        lines.append(yellow(f"  Missing: {item['param'].upper()}"))
        for qline in item["question"].split("\n"):
            lines.append(f"    {qline}")
        lines.append("")

    lines.append(grey("  Provide the missing value(s) and re-run."))
    return "\n".join(lines)


def format_error(message: str) -> str:
    return red(f"[ERROR] {message}")


def format_invalid(intent: dict, gate_result: dict) -> str:
    """Format invalid parameter errors caught at gate stage."""
    lines = [
        header("── NVMe Helper — Invalid Parameter ─────────────────────"),
        f"  Command: {bold(gate_result['kb']['meta']['name'])}",
        ""
    ]
    for inv in gate_result["invalid"]:
        lines.append(red(f"  ✗ {inv['param'].upper()} = {inv['value']}"))
        lines.append(f"    {inv['reason']}")
        lines.append("")
    return "\n".join(lines)


def format_no_detailed_kb(intent: dict, gate_result: dict) -> str:
    """
    Format the case where the command is a recognized NVMe opcode
    (per kb/tables/opcodes.json) but has no detailed kb/commands/*.json
    entry yet, so SQ/CQ prediction isn't possible.
    """
    opcode_info = gate_result.get("opcode_info") or {}
    name  = opcode_info.get("name", intent.get("command", "?"))
    opc   = opcode_info.get("opcode", "?")
    group = opcode_info.get("group", "?")

    lines = [
        header("── NVMe Helper — Command Recognized, No Detailed KB ────"),
        f"  Command: {bold(name)}  {grey(f'(opcode {opc}, {group} command set)')}",
        f"  Intent:  {intent.get('raw_intent', '')}",
        "",
        yellow(f"  '{name}' is a known NVMe command, but there's no detailed"),
        yellow(f"  KB entry for it yet — so SQ/CQ prediction isn't possible."),
        "",
        grey(f"  To add it, run:"),
        grey(f"    python3 generate_kb_from_docs.py <spec.pdf> --pages <range>"),
        grey(f"  which will draft kb/commands/{group}/{name.lower().replace(' ', '_')}.json"),
        grey(f"  for you to review."),
    ]
    return "\n".join(lines)


# ── Human-readable ─────────────────────────────────────────────────────────

def _human_output(intent, gate_result, sq_result, cq_result) -> str:
    kb     = gate_result["kb"]
    meta   = kb["meta"]
    status = cq_result["status"]
    sq     = sq_result["sq_entry"]
    cq     = cq_result["cq_entry"]
    resp   = cq_result.get("response")

    ok = status["SC"] == "0x00" and status["SCT"] == "0x0"
    status_icon = green("✓") if ok else red("✗")
    status_str  = (green if ok else red)(
        f"SCT={status['SCT']} SC={status['SC']} — {status['meaning']}"
    )

    lines = [
        header(f"── NVMe Helper ─────────────────────────────────────────"),
        f"  {bold('Command:')}  {meta['name']}  {grey(meta.get('opcode',''))}  [{meta.get('queue','Admin')} Queue]",
        f"  {bold('Ref:')}      {grey(meta.get('spec_ref',''))}",
        f"  {bold('Intent:')}   {intent.get('raw_intent', '')}",
        "",
        header("── Submission Queue (SQ) Entry ─────────────────────────"),
    ]

    for cdw_name, cdw in sq.items():
        raw = cdw.get("raw", "")
        desc = cdw.get("desc", "")
        if cdw.get("fields"):
            field_strs = [f"{k}={v['value']}" for k, v in cdw["fields"].items()
                          if not k.startswith("reserved") and v["value"] not in ("0x0", "0x00")]
            field_part = grey("  → " + ", ".join(field_strs)) if field_strs else ""
        else:
            field_part = ""

        lines.append(f"  {cyan(cdw_name):8}  {bold(raw):18}  {grey(desc)}")
        if field_part:
            lines.append(f"           {field_part}")

    lines += [
        "",
        header("── Completion Queue (CQ) Entry (Predicted) ─────────────"),
        f"  {status_icon} {status_str}",
        ""
    ]

    for dw_name, dw in cq.items():
        raw  = dw.get("raw", "")
        desc = dw.get("desc", "")
        lines.append(f"  {cyan(dw_name):8}  {bold(raw):18}  {grey(desc)}")

    if resp:
        lines += [
            "",
            header("── Expected Response Data Structure ─────────────────────"),
            f"  Type:     {resp.get('type','')}   Size: {resp.get('size_bytes','')} bytes",
            f"  {grey(resp.get('desc',''))}   {grey(resp.get('spec_ref',''))}",
            ""
        ]
        fields = resp.get("fields", {})
        if fields:
            lines.append(f"  {'Field':<16} {'Offset':>8}  {'Size':>6}   Description")
            lines.append(f"  {'-'*16} {'-'*8}  {'-'*6}   {'-'*30}")
            for fname, fdef in fields.items():
                off  = fdef.get("offset_bytes", "?")
                size = fdef.get("size_bytes",   "?")
                desc = fdef.get("desc", "")
                lines.append(f"  {fname:<16} {str(off):>8}  {str(size):>6}   {grey(desc)}")

    if cq_result.get("notes"):
        lines += ["", grey("  Notes:")]
        for note in cq_result["notes"]:
            lines.append(grey(f"    • {note}"))

    return "\n".join(lines)


# ── JSON output ────────────────────────────────────────────────────────────

def _json_output(intent, gate_result, sq_result, cq_result) -> str:
    kb   = gate_result["kb"]
    meta = kb["meta"]

    out = {
        "command":    meta.get("name"),
        "opcode":     meta.get("opcode"),
        "queue":      meta.get("queue"),
        "spec_ref":   meta.get("spec_ref"),
        "intent":     intent.get("raw_intent", ""),
        "parameters": gate_result.get("resolved", {}),
        "sq_entry":   _serialise_sq(sq_result["sq_entry"]),
        "cq_entry":   _serialise_cq(cq_result["cq_entry"]),
        "status": {
            "SCT":     cq_result["status"]["SCT"],
            "SC":      cq_result["status"]["SC"],
            "meaning": cq_result["status"]["meaning"],
            "DNR":     cq_result["status"].get("DNR", False)
        },
        "response":   cq_result.get("response"),
        "notes":      cq_result.get("notes", [])
    }

    return json.dumps(out, indent=2)


def _serialise_sq(sq: dict) -> dict:
    return {cdw: {"raw": v.get("raw"), "desc": v.get("desc", "")}
            for cdw, v in sq.items()}


def _serialise_cq(cq: dict) -> dict:
    out = {}
    for dw, v in cq.items():
        out[dw] = {"raw": v.get("raw"), "desc": v.get("desc", "")}
        if "fields" in v:
            out[dw]["fields"] = v["fields"]
    return out


# ── CLI entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    data = json.loads(sys.stdin.read())
    print(format_output(
        data["intent"],
        data["gate"],
        data["sq"],
        data["cq"],
        data.get("mode")
    ))